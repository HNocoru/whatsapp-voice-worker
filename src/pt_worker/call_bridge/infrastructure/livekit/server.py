"""Servidor de agentes de LiveKit y punto de entrada de cada llamada despachada.

Adaptado de `reference/api-caliope-core-s2s/.../livekit/server.py`. La función de entrada debe
poder serializarse (LiveKit corre cada sala en otro proceso): por eso `register` recibe una
`functools.partial` de funciones de módulo, nunca una clausura.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from functools import partial

from livekit.agents import AgentServer, JobContext, cli

from pt_worker.call_bridge.application.call_id import MissingCallIdError, resolve_call_id
from pt_worker.call_bridge.application.ports import VoiceEngine
from pt_worker.call_bridge.application.run_call import CallServices, run_call
from pt_worker.call_bridge.infrastructure.livekit.voice_engine import LiveKitVoiceEngine

logger = logging.getLogger(__name__)

AGENT_NAME = "whatsapp-agent"  # despacho explícito: el Connector/regla de despacho usa este nombre


def _livekit_engine(ctx: JobContext, identity: str) -> VoiceEngine:
    return LiveKitVoiceEngine(ctx, identity)


async def handle_job(
    ctx: JobContext,
    services_factory: Callable[[], CallServices],
    engine_factory: Callable[[JobContext, str], VoiceEngine] = _livekit_engine,
) -> None:
    """Atiende una sala: espera al participante, resuelve el call_id y corre la llamada."""
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    try:
        call_id = resolve_call_id(ctx.job.metadata, participant.attributes)
    except MissingCallIdError as exc:
        # Sin call_id no hay dónde registrar la llamada: se cierra la sala sin saludar.
        logger.error("despacho inválido: %s", exc)
        with contextlib.suppress(Exception):  # si falla, shutdown debe correr igual
            await ctx.delete_room()
        ctx.shutdown(reason="missing_call_id")
        return

    services: CallServices | None = None
    try:
        services = services_factory()
        engine = engine_factory(ctx, participant.identity)
        # run_call pide el contexto, arranca Phonic (con reintentos) y publica `end` siempre.
        await run_call(call_id, engine, services)
    except Exception as exc:  # noqa: BLE001 - un fallo de armado no debe dejar la sala abierta
        logger.error("la llamada no pudo atenderse: %s", type(exc).__name__)
        with contextlib.suppress(Exception):
            await ctx.delete_room()
    finally:
        if services is not None:
            with contextlib.suppress(Exception):
                await services.close()
        ctx.shutdown(reason="call_finished")


def create_server(
    services_factory: Callable[[], CallServices], *, url: str, api_key: str, api_secret: str
) -> AgentServer:
    server = AgentServer(ws_url=url, api_key=api_key, api_secret=api_secret)
    entrypoint = partial(handle_job, services_factory=services_factory)
    server.rtc_session(entrypoint, agent_name=AGENT_NAME)
    return server


def run_server(server: AgentServer) -> None:
    """Arranca el CLI de LiveKit (`dev`, `start`, ...) leyendo `sys.argv`."""
    cli.run_app(server)
