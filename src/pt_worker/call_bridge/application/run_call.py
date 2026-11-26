"""Caso de uso de la llamada (W2): contexto -> conversación S2S -> turnos, límite y cierre.

Adaptado de `reference/api-caliope-core-s2s/.../media_bridge/application/` (start_call, end_call),
cambiando repositorios Postgres por puertos. El modelo S2S (Phonic) lo pone el motor de voz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pt_worker.call_bridge.application.conversation import (
    GOODBYE_INSTRUCTIONS,
    ConversationSpec,
    build_conversation,
)
from pt_worker.call_bridge.application.ports import (
    CallContextSource,
    CallEvents,
    Clock,
    VoiceEngine,
)
from pt_worker.call_bridge.domain.call import Call, CallLimits, EndReason

logger = logging.getLogger(__name__)

HANGUP_FAILED = "hangup_failed"  # el corte agotó intentos: la sala pudo quedar abierta
ENGINE_FAILURE = "voice_engine_failure"  # texto fijo: nunca datos sensibles en `error`


@dataclass(frozen=True)
class CallServices:
    """Dependencias de una llamada, armadas por main.py. `close` libera lo que abrieron."""

    context_source: CallContextSource
    events: CallEvents
    clock: Clock
    close: Callable[[], Awaitable[None]]
    default_voice: str = "roberto"
    max_start_retries: int = 3  # reintentos tras el primer intento
    start_backoff_sec: float = 5.0
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    goodbye_timeout_sec: float = 10.0  # tope a la despedida: no puede retrasar el corte
    hangup_timeout_sec: float = 10.0  # tope por intento de colgado


def _limits_from(context: dict[str, Any] | None) -> CallLimits:
    raw = (context or {}).get("limits")
    if isinstance(raw, dict):
        try:
            return CallLimits(
                max_call_seconds=int(raw["max_call_seconds"]),
                goodbye_at_seconds=int(raw["goodbye_at_seconds"]),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("limits del contexto inválidos; se usan los predeterminados")
    return CallLimits()


async def run_call(
    call_id: str,
    engine: VoiceEngine,
    services: CallServices,
    *,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EndReason:
    """Corre una llamada hasta que se cuelga. Nunca lanza por fallos de la app."""
    context: dict[str, Any] | None = None
    try:
        context = await services.context_source.fetch(call_id)
    except Exception as exc:  # noqa: BLE001 - la llamada sigue con configuración genérica
        logger.warning("sin contexto (%s); configuración genérica", type(exc).__name__)

    clock = services.clock
    spec = build_conversation(context, services.default_voice)
    call = Call(call_id, _limits_from(context))
    turns = _TurnRecorder(call_id, call, services)
    engine.on_turn(turns.handle)

    try:
        await _start_with_retries(engine, spec, services)
    except Exception as exc:  # noqa: BLE001 - Phonic no arrancó: end `failed` y colgar
        await report_start_failure(call_id, exc, services, utcnow=utcnow)
        if not await _hang_up(engine, services):
            logger.error("no se pudo colgar tras el fallo de arranque; la sala pudo quedar abierta")
        return EndReason.FAILED

    call.start(clock.now())
    answered_at = utcnow()
    reason = EndReason.COMPLETED
    error: str | None = None
    try:
        reason, error = await _supervise(engine, services, call)
    except Exception as exc:  # noqa: BLE001 - se cierra como fallida y se informa a la app
        logger.error("la llamada falló: %s", type(exc).__name__)
        reason, error = EndReason.FAILED, type(exc).__name__
    if reason is EndReason.FAILED and error is None:
        error = ENGINE_FAILURE  # el motor cerró con error sin excepción (p. ej. CloseReason.ERROR)

    call.end(reason, clock.now())
    await turns.drain()
    await services.events.publish_end(
        call_id,
        {
            "ended_reason": reason.value,
            "answered_at": answered_at.isoformat(),
            "ended_at": utcnow().isoformat(),
            "duration_sec": call.duration_sec(clock.now()),
            "error": error,
        },
    )
    return reason


async def _start_with_retries(
    engine: VoiceEngine, spec: ConversationSpec, services: CallServices
) -> None:
    """Primer intento + `max_start_retries` reintentos con pausa fija; relanza el último error."""
    attempts = services.max_start_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            await engine.start_conversation(
                instructions=spec.instructions,
                voice=spec.voice,
                template_variables=spec.template_variables,
                welcome_message=spec.welcome_message,
                language=spec.language,
            )
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.warning("Phonic no arrancó (%s); reintento %d", type(exc).__name__, attempt)
            await services.sleep(services.start_backoff_sec)


class _TurnRecorder:
    """Convierte los eventos de transcripción en turnos con `seq` incremental (empieza en 1)."""

    def __init__(self, call_id: str, call: Call, services: CallServices) -> None:
        self._call_id, self._call, self._services = call_id, call, services
        self._seq = 0
        self._tasks: set[asyncio.Task[None]] = set()

    def handle(self, role: str, text: str) -> None:
        if not text.strip() or role not in ("user", "assistant"):
            return
        self._seq += 1  # síncrono: el orden de `seq` es el de llegada
        started_ms = int(self._call.elapsed(self._services.clock.now()) * 1000)
        task = asyncio.ensure_future(
            self._services.events.record_turn(self._call_id, self._seq, role, text, started_ms)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


async def _supervise(
    engine: VoiceEngine, services: CallServices, call: Call
) -> tuple[EndReason, str | None]:
    """Espera el cierre con el tope de duración: despedida a `goodbye_at`, corte a `max`.

    Los tiempos salen del dominio `Call`; el reloj y la espera son inyectables (tests sin esperar).
    """
    now = services.clock.now
    hangup = asyncio.ensure_future(engine.wait_for_hangup())
    timer: asyncio.Future[None] | None = None
    try:
        timer = asyncio.ensure_future(
            services.sleep(max(0.0, call.limits.goodbye_at_seconds - call.elapsed(now())))
        )
        await asyncio.wait({hangup, timer}, return_when=asyncio.FIRST_COMPLETED)
        if hangup.done():
            return hangup.result(), None

        if call.should_say_goodbye(now()):
            call.begin_ending()
            try:
                async with asyncio.timeout(services.goodbye_timeout_sec):
                    await engine.say_goodbye(GOODBYE_INSTRUCTIONS)
            except Exception as exc:  # noqa: BLE001 - sin despedida igual se corta a tiempo
                logger.warning("no se pudo pedir la despedida: %s", type(exc).__name__)

        timer = asyncio.ensure_future(
            services.sleep(max(0.0, call.limits.max_call_seconds - call.elapsed(now())))
        )
        await asyncio.wait({hangup, timer}, return_when=asyncio.FIRST_COMPLETED)
        if hangup.done():
            return hangup.result(), None
        # El temporizador venció: se corta siempre, aunque despierte una pizca antes del límite.
        if await _hang_up(engine, services):
            return EndReason.TIME_LIMIT, None
        logger.error("el corte duro agotó los intentos; la sala pudo quedar abierta")
        return EndReason.TIME_LIMIT, HANGUP_FAILED
    finally:
        for task in (timer, hangup):
            if task is not None and not task.done():
                task.cancel()
        for task in (timer, hangup):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


HANGUP_ATTEMPTS = 3  # el corte duro se reintenta de forma acotada si LiveKit falla un momento
HANGUP_RETRY_SEC = 1.0


async def _hang_up(engine: VoiceEngine, services: CallServices) -> bool:
    """Cuelga la sala con reintento acotado y timeout por intento. True si colgó.

    Un fallo al colgar no cambia el motivo del cierre; solo se informa con `error`.
    """
    for attempt in range(1, HANGUP_ATTEMPTS + 1):
        try:
            async with asyncio.timeout(services.hangup_timeout_sec):
                await engine.hangup()
            return True
        except Exception as exc:  # noqa: BLE001 - incluye TimeoutError del intento
            logger.warning(
                "falló el colgado (%d/%d): %s", attempt, HANGUP_ATTEMPTS, type(exc).__name__
            )
            if attempt < HANGUP_ATTEMPTS:
                await services.sleep(HANGUP_RETRY_SEC)
    return False


async def report_start_failure(
    call_id: str,
    exc: BaseException,
    services: CallServices,
    *,
    utcnow: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """La llamada nunca arrancó (el motor no inició): la app igual recibe `end` con `failed`."""
    logger.error("el motor de voz no inició: %s", type(exc).__name__)
    now = utcnow().isoformat()
    await services.events.publish_end(
        call_id,
        {
            "ended_reason": EndReason.FAILED.value,
            "answered_at": now,
            "ended_at": now,
            "duration_sec": 0,
            "error": type(exc).__name__,
        },
    )
