"""Puertos de call_bridge. Los adaptadores viven en infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pt_worker.call_bridge.domain.call import EndReason


class Clock(Protocol):
    """Tiempo monotónico en segundos; en tests se sustituye por un reloj falso."""

    def now(self) -> float: ...


TurnHandler = Callable[[str, str], None]  # (role "user"|"assistant", texto)


class VoiceEngine(Protocol):
    """El motor de voz S2S de una llamada (hoy Phonic sobre LiveKit). Sin tipos de livekit/phonic.

    `on_turn` registra quién recibe cada turno de transcripción (antes de `start_conversation`);
    `start_conversation` conecta la sala con el modelo S2S; `say_goodbye` pide al modelo una
    despedida breve; `wait_for_hangup` espera a que la llamada se cierre y devuelve el motivo;
    `hangup` cuelga desde el worker y libera lo que `start_conversation` haya abierto.
    """

    def on_turn(self, handler: TurnHandler) -> None: ...

    async def start_conversation(
        self,
        *,
        instructions: str,
        voice: str,
        template_variables: dict[str, str],
        welcome_message: str | None,
        language: str = "es",
    ) -> None: ...

    async def say_goodbye(self, instructions: str) -> None: ...

    async def wait_for_hangup(self) -> EndReason: ...

    async def hangup(self) -> None: ...


class CallContextSource(Protocol):
    """Obtiene el contexto de la llamada; `None` si la app no lo conoce (404)."""

    async def fetch(self, call_id: str) -> dict[str, Any] | None: ...


class CallEvents(Protocol):
    """Salida de turnos y fin hacia la app. La implementa `call_events` (la conecta main.py).

    Ninguno de los dos métodos debe lanzar: ningún error de la app tumba la llamada.
    """

    async def record_turn(
        self, call_id: str, seq: int, role: str, text: str, started_ms: int
    ) -> None: ...

    async def publish_end(self, call_id: str, payload: dict[str, Any]) -> None: ...
