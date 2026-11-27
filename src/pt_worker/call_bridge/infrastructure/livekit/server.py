"""Servidor de agentes de LiveKit y punto de entrada de cada llamada despachada.

Adaptado de `reference/api-caliope-core-s2s/.../livekit/server.py`. La función de entrada debe
poder serializarse (LiveKit corre cada sala en otro proceso): por eso `register` recibe una
`functools.partial` de funciones de módulo, nunca una clausura.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from livekit.agents import AgentServer, JobContext, cli

from pt_worker.call_bridge.application.call_id import MissingCallIdError, resolve_call_id
from pt_worker.call_bridge.application.ports import VoiceEngine
from pt_worker.call_bridge.application.run_call import (
    CallServices,
    report_start_failure,
    run_call,
)
from pt_worker.call_bridge.infrastructure.livekit.room_trace import (
    DEFAULT_DURATION_S,
    DEFAULT_INTERVAL_S,
    log_job_start,
    trace_room,
    traced_wait,
)
from pt_worker.call_bridge.infrastructure.livekit.voice_engine import LiveKitVoiceEngine

logger = logging.getLogger(__name__)

NO_PARTICIPANT = "no_participant"  # texto fijo para `error` y el motivo de shutdown
PARTICIPANT_TIMEOUT_SEC = 30.0  # tope a la espera del participante (F15)
NO_PARTICIPANT_END_TIMEOUT_SEC = 20.0  # tope a `end` sin participante (libera el slot)
AGENT_NAME = "whatsapp-agent"  # despacho explícito: el Connector/regla de despacho usa este nombre


def _livekit_engine(ctx: JobContext, identity: str) -> VoiceEngine:
    return LiveKitVoiceEngine(ctx, identity)


async def _default_wait(ctx: JobContext) -> Any:
    return await ctx.wait_for_participant()


async def handle_job(
    ctx: JobContext,
    services_factory: Callable[[], CallServices],
    engine_factory: Callable[[JobContext, str], VoiceEngine] = _livekit_engine,
    *,
    trace_interval: float = DEFAULT_INTERVAL_S,
    trace_duration: float = DEFAULT_DURATION_S,
    wait: Callable[[JobContext], Awaitable[Any]] = _default_wait,
    participant_timeout_sec: float = PARTICIPANT_TIMEOUT_SEC,
    no_participant_end_timeout_sec: float = NO_PARTICIPANT_END_TIMEOUT_SEC,
) -> None:
    """Atiende una sala: espera al participante, resuelve el call_id y corre la llamada.

    El trazado (`room_trace`) es solo diagnóstico: la espera sigue siendo `wait_for_participant`.
    """
    started = time.monotonic()
    log_job_start(ctx, started, phase="start")
    await ctx.connect()
    log_job_start(ctx, started, phase="connected")
    trace_task = asyncio.create_task(
        trace_room(
            getattr(ctx, "room", None),
            started=started,
            interval=trace_interval,
            duration=trace_duration,
        ),
        name="trace_room",
    )
    try:
        await _run_job(
            ctx,
            services_factory,
            engine_factory,
            wait,
            started,
            participant_timeout_sec,
            no_participant_end_timeout_sec,
        )
    finally:
        trace_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await trace_task


async def _run_job(
    ctx: JobContext,
    services_factory: Callable[[], CallServices],
    engine_factory: Callable[[JobContext, str], VoiceEngine],
    wait: Callable[[JobContext], Awaitable[Any]],
    started: float,
    participant_timeout_sec: float,
    end_timeout_sec: float,
) -> None:
    try:
        async with asyncio.timeout(participant_timeout_sec) as limit:
            participant = await traced_wait(ctx, wait, started=started)
    except TimeoutError:
        if not limit.expired():
            raise  # un TimeoutError propio de la espera sigue propagándose igual que antes
        await _close_without_participant(
            ctx, services_factory, participant_timeout_sec, end_timeout_sec
        )
        return
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


async def _close_without_participant(
    ctx: JobContext,
    services_factory: Callable[[], CallServices],
    timeout_sec: float,
    end_timeout_sec: float,
) -> None:
    """El llamante nunca entró: cierra la sala, informa `end` failed (acotado) y libera el slot.

    Orden: 1) delete_room, 2) `end` con tope (con la app caída su ventana de reintento sería de
    120 s y retendría el slot), 3) shutdown siempre, 4) cierre de servicios. No lanza.
    """
    logger.warning("TimeoutError: ningún participante entró a la sala en %.1f s", timeout_sec)
    with contextlib.suppress(Exception):
        await ctx.delete_room()
    services: CallServices | None = None
    try:
        try:
            call_id = resolve_call_id(ctx.job.metadata, {})
        except MissingCallIdError:
            logger.error("sin participante y sin call_id en el despacho: no hay dónde publicar end")
        else:
            services = services_factory()
            try:
                async with asyncio.timeout(end_timeout_sec):
                    await report_start_failure(
                        call_id,
                        TimeoutError(),
                        services,
                        error=NO_PARTICIPANT,
                        answered=False,
                    )
            except TimeoutError:
                logger.error(
                    "end perdido: la app no lo recibió en %.1f s (call_id=%s)",
                    end_timeout_sec,
                    call_id,
                )
    except Exception as exc:  # noqa: BLE001 - el shutdown debe correr igual
        logger.error("no se pudo informar la llamada sin participante: %s", type(exc).__name__)
    finally:
        with contextlib.suppress(Exception):
            ctx.shutdown(reason=NO_PARTICIPANT)
        if services is not None:
            with contextlib.suppress(Exception):
                await services.close()


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
