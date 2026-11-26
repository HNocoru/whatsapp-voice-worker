"""`VoiceEngine` sobre LiveKit + Phonic (modelo S2S); aquí se usan `livekit` y `phonic`.

Sin llm/stt/tts sueltos: `AgentSession(llm=RealtimeModel(...))` (el parámetro `llm` acepta un
`RealtimeModel`, agents/voice/agent_session.py:417) y `Agent(instructions=...)` (obligatorio,
agents/voice/agent.py:891). Ya no se reproduce `hola.wav`: el saludo lo da el modelo.

Verificado en el paquete (livekit-agents 1.8.13, livekit-plugins-phonic):
- `RealtimeModel.__init__` keyword-only: realtime_model.py:226 (voice, welcome_message,
  generate_welcome_message, template_variables, default_language, api_key -> env PHONIC_API_KEY).
- Las `instructions` del Agent llegan como `system_prompt` de Phonic: realtime_model.py:1267-1272.
- Transcripción: el plugin emite `input_audio_transcription_completed` (realtime_model.py:1474) y
  la sesión lo publica como `conversation_item_added` (agent_activity.py:2367-2393) con
  `ChatMessage.role`/`text_content`. NO verificado con una llamada real, ni que el texto del
  asistente llegue por ese mismo evento (se espera de agent_activity.py:3603/4172).
- Despedida: `AgentSession.generate_reply(instructions=...)` (agent_session.py:1642) que para
  Phonic se traduce a `system_message` (realtime_model.py:1122-1132). NO verificado en llamada real.
- El plugin NO expone `max_conversation_duration_sec`; el tope de 5 min es del dominio `Call`.

Adaptado de `reference/api-caliope-core-s2s/.../livekit/session.py` (cierre por evento `close`).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from livekit.agents import Agent, AgentSession, JobContext, room_io
from livekit.agents.voice.events import CloseReason
from livekit.plugins import phonic

from pt_worker.call_bridge.application.ports import TurnHandler
from pt_worker.call_bridge.domain.call import EndReason


def end_reason_from_close(reason: Any) -> EndReason:
    """Del motivo de cierre de la sesión de LiveKit al del contrato (mapeo explícito).

    - PARTICIPANT_DISCONNECTED: cuelga quien llama -> caller_hangup.
    - USER_INITIATED / TASK_COMPLETED: cierre pedido por nosotros -> completed.
    - ERROR y JOB_SHUTDOWN: la llamada se cortó por causa nuestra (fallo, o el worker se apaga
      a media llamada) -> failed; run_call añade un `error` fijo y no sensible.
    - Cualquier motivo desconocido también es failed: no se afirma "completed" sin saberlo.
    """
    value = str(getattr(reason, "value", reason))
    if value == CloseReason.PARTICIPANT_DISCONNECTED.value:
        return EndReason.CALLER_HANGUP
    if value in (CloseReason.USER_INITIATED.value, CloseReason.TASK_COMPLETED.value):
        return EndReason.COMPLETED
    return EndReason.FAILED


class LiveKitVoiceEngine:
    def __init__(self, ctx: JobContext, participant_identity: str) -> None:
        self._ctx = ctx
        self._identity = participant_identity
        self._closed: asyncio.Future[EndReason] = asyncio.get_running_loop().create_future()
        self._session: AgentSession[Any] | None = None
        self._handler: TurnHandler | None = None

    def on_turn(self, handler: TurnHandler) -> None:
        self._handler = handler

    def _on_close(self, event: Any) -> None:
        if not self._closed.done():
            self._closed.set_result(end_reason_from_close(getattr(event, "reason", None)))

    def _on_item(self, event: Any) -> None:
        item = getattr(event, "item", None)
        role, text = getattr(item, "role", None), getattr(item, "text_content", None)
        if self._handler is not None and role in ("user", "assistant") and text:
            self._handler(str(role), str(text))

    async def start_conversation(
        self,
        *,
        instructions: str,
        voice: str,
        template_variables: dict[str, str],
        welcome_message: str | None,
        language: str = "es",
    ) -> None:
        """Abre la sesión S2S. Cada intento crea una sesión nueva; si falla, cierra la parcial."""
        await self._discard_session()
        # Sin saludo de la app, el modelo lo genera (ignora welcome_message).
        welcome: dict[str, Any] = (
            {"welcome_message": welcome_message}
            if welcome_message
            else {"generate_welcome_message": True}
        )
        model = phonic.realtime.RealtimeModel(
            voice=voice,
            template_variables=template_variables,
            default_language=language,
            **welcome,
        )
        session: AgentSession[Any] = AgentSession(llm=model)
        session.on("close", self._on_close)
        session.on("conversation_item_added", self._on_item)
        self._session = session
        try:
            await session.start(
                Agent(instructions=instructions),
                room=self._ctx.room,
                room_options=room_io.RoomOptions(
                    participant_identity=self._identity, close_on_disconnect=True
                ),
            )
        except BaseException:
            await self._discard_session()
            raise

    async def _discard_session(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            with contextlib.suppress(Exception):
                await session.aclose()
        if self._closed.done():  # un intento fallido pudo cerrar el futuro: rearmarlo
            self._closed = asyncio.get_running_loop().create_future()

    async def say_goodbye(self, instructions: str) -> None:
        if self._session is not None:
            self._session.generate_reply(instructions=instructions)

    async def wait_for_hangup(self) -> EndReason:
        return await asyncio.shield(self._closed)  # cancelar la espera no cierra el futuro

    async def hangup(self) -> None:
        await self._ctx.delete_room()  # saca a todos los participantes
