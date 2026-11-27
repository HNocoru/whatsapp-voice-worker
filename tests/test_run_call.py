"""run_call y call_events con fakes: sin red ni LiveKit."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from pt_worker.app_client.fake import FakeAppClient
from pt_worker.app_client.port import CallAlreadyEndedError
from pt_worker.call_bridge.application.call_id import MissingCallIdError, resolve_call_id
from pt_worker.call_bridge.application.run_call import CallServices, run_call
from pt_worker.call_bridge.domain.call import EndReason
from pt_worker.call_bridge.infrastructure.app_context import AppContextSource
from pt_worker.call_bridge.infrastructure.livekit.server import handle_job
from pt_worker.call_bridge.infrastructure.livekit.voice_engine import end_reason_from_close
from pt_worker.call_events.application import TurnBuffer
from pt_worker.call_events.infrastructure import HttpCallEventSink
from tests.fakes import FakeClock

CALL_ID = "3f2b8c1e-5a47-4d0e-9b6a-1c2d3e4f5a6b"


class FakeEngine:
    """Motor falso: registra el arranque, emite turnos guionados y cuelga cuando se le indica."""

    def __init__(
        self,
        hangup: EndReason | None = EndReason.COMPLETED,
        script: list[tuple[str, str]] | None = None,
        start_failures: int = 0,
        hangup_failures: int = 0,
        goodbye_hangs: bool = False,
        hangup_hangs: bool = False,
    ) -> None:
        self._hangup_failures = hangup_failures
        self._goodbye_hangs = goodbye_hangs
        self._hangup_hangs = hangup_hangs
        self.started: list[dict[str, Any]] = []
        self.start_attempts = 0
        self.goodbyes: list[float] = []
        self.hangups = 0
        self.clock: FakeClock | None = None
        self._hangup = hangup  # None: la llamada no se cierra sola (prueba del tope)
        self._script = script or []
        self._start_failures = start_failures
        self._handler: Any = None

    def on_turn(self, handler: Any) -> None:
        self._handler = handler

    async def start_conversation(self, **kwargs: Any) -> None:
        self.start_attempts += 1
        if self.start_attempts <= self._start_failures:
            msg = "token secreto-123"
            raise ConnectionError(msg)
        self.started.append(kwargs)
        for role, text in self._script:
            self._handler(role, text)

    async def say_goodbye(self, instructions: str) -> None:
        if self._goodbye_hangs:
            await asyncio.Event().wait()  # la despedida nunca retorna
        self.goodbyes.append(self.clock.now() if self.clock else 0.0)

    async def wait_for_hangup(self) -> EndReason:
        if self._hangup is None:
            await asyncio.Event().wait()
        assert self._hangup is not None
        return self._hangup

    async def hangup(self) -> None:
        self.hangups += 1
        if self._hangup_hangs:
            await asyncio.Event().wait()  # el colgado nunca retorna
        if self.hangups <= self._hangup_failures:
            msg = "LiveKit no respondió"
            raise RuntimeError(msg)


class FakeSleep:
    """Sleep falso: avanza el reloj sin esperar y repara la app tras N pausas."""

    def __init__(self, clock: FakeClock, app: FakeAppClient, heal_after: int | None = None) -> None:
        self.clock, self.app, self.heal_after, self.calls = clock, app, heal_after, 0
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls += 1
        self.durations.append(seconds)
        self.clock.advance(seconds)
        if self.heal_after is not None and self.calls >= self.heal_after:
            self.app.fail_next = 0


def make(
    app: FakeAppClient,
    clock: FakeClock,
    heal_after: int | None = None,
    **overrides: Any,
) -> CallServices:
    sleep = FakeSleep(clock, app, heal_after)
    buffer = TurnBuffer(HttpCallEventSink(app), sleep=sleep, now=clock.now)
    return CallServices(
        context_source=AppContextSource(app),
        events=buffer,
        clock=clock,
        close=app.aclose,
        sleep=sleep,
        **overrides,
    )


async def test_caller_hangup_is_reported() -> None:
    app, clock = FakeAppClient(), FakeClock()
    await run_call(CALL_ID, FakeEngine(EndReason.CALLER_HANGUP), make(app, clock))
    assert app.ends[CALL_ID]["ended_reason"] == "caller_hangup"


async def test_app_down_forever_gives_up_after_the_window_without_raising() -> None:
    app, clock = FakeAppClient(), FakeClock()
    app.fail_next = 10_000
    services = make(app, clock)
    await run_call(CALL_ID, FakeEngine(), services)
    assert app.ends == {}
    # Se ignoran los temporizadores del tope (270/30 s): solo cuenta la espera de reintentos.
    waits = [d for d in services.sleep.durations if d <= 2.0]  # type: ignore[attr-defined]
    assert sum(waits) <= 120.0 + 2.0  # no espera más de la ventana de 2 min


def test_call_id_from_job_metadata_wins_over_participant_attribute() -> None:
    other = "11111111-1111-4111-8111-111111111111"
    assert resolve_call_id(f'{{"call_id": "{CALL_ID}"}}', {"call_id": other}) == CALL_ID


def test_invalid_metadata_call_id_falls_back_to_valid_attribute() -> None:
    assert resolve_call_id('{"call_id": "no-es-uuid"}', {"call_id": CALL_ID}) == CALL_ID


def test_call_id_falls_back_to_participant_attribute() -> None:
    assert resolve_call_id("", {"call_id": CALL_ID}) == CALL_ID
    assert resolve_call_id("no es json", {"call_id": CALL_ID}) == CALL_ID


@pytest.mark.parametrize("metadata", [None, "", "{}", '{"call_id": "no-uuid"}', "[1]"])
def test_missing_call_id_fails_in_a_controlled_way(metadata: str | None) -> None:
    with pytest.raises(MissingCallIdError):
        resolve_call_id(metadata, {})


# --- huecos del verificador -------------------------------------------------------------------


async def test_http_sink_treats_409_as_delivered() -> None:
    class Gone(FakeAppClient):
        async def post_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
            raise CallAlreadyEndedError

        async def post_end(self, call_id: str, payload: dict[str, Any]) -> None:
            raise CallAlreadyEndedError

    app = Gone()
    sink = HttpCallEventSink(app)
    await sink.send_turns(CALL_ID, [{"seq": 1}])  # no lanza
    await sink.send_end(CALL_ID, {"ended_reason": "completed"})
    # entregado: el buffer no reintenta ni duerme
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    buffer = TurnBuffer(sink, sleep=sleep, now=FakeClock().now)
    await buffer.publish_end(CALL_ID, {"ended_reason": "completed"})
    assert sleeps == []


class FakeJob:
    def __init__(self, metadata: str) -> None:
        self.metadata = metadata


class FakeParticipant:
    identity = "wa-user"
    attributes: dict[str, str] = {}  # noqa: RUF012


class FakeCtx:
    def __init__(self, metadata: str) -> None:
        self.job = FakeJob(metadata)
        self.deleted = 0
        self.shutdowns: list[str] = []

    async def connect(self) -> None:
        return None

    async def wait_for_participant(self) -> FakeParticipant:
        return FakeParticipant()

    async def delete_room(self) -> None:
        self.deleted += 1

    def shutdown(self, reason: str = "") -> None:
        self.shutdowns.append(reason)


async def test_handle_job_without_call_id_closes_room_and_creates_nothing() -> None:
    ctx, created = FakeCtx("{}"), []

    def services_factory() -> CallServices:
        created.append("services")
        return make(FakeAppClient(), FakeClock())

    def engine_factory(_ctx: Any, _identity: str) -> FakeEngine:
        created.append("engine")
        return FakeEngine()

    await handle_job(ctx, services_factory, engine_factory)  # type: ignore[arg-type]
    assert created == []
    assert ctx.deleted == 1
    assert ctx.shutdowns == ["missing_call_id"]


async def test_handle_job_shuts_down_even_if_delete_room_fails() -> None:
    class FailingCtx(FakeCtx):
        async def delete_room(self) -> None:
            msg = "sala ya cerrada"
            raise RuntimeError(msg)

    ctx = FailingCtx("{}")
    await handle_job(ctx, lambda: make(FakeAppClient(), FakeClock()))  # type: ignore[arg-type]
    assert ctx.shutdowns == ["missing_call_id"]


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("participant_disconnected", EndReason.CALLER_HANGUP),
        ("user_initiated", EndReason.COMPLETED),
        ("task_completed", EndReason.COMPLETED),
        ("error", EndReason.FAILED),
        ("job_shutdown", EndReason.FAILED),
        ("algo_nuevo", EndReason.FAILED),
    ],
)
def test_close_reason_mapping(reason: str, expected: EndReason) -> None:
    assert end_reason_from_close(reason) is expected


async def test_engine_closed_with_error_reports_non_empty_non_sensitive_error() -> None:
    app, clock = FakeAppClient(), FakeClock()
    reason = await run_call(CALL_ID, FakeEngine(EndReason.FAILED), make(app, clock))
    assert reason is EndReason.FAILED
    assert app.ends[CALL_ID]["error"] == "voice_engine_failure"


async def test_retry_sleep_is_capped_so_total_wait_is_exactly_the_window() -> None:
    clock, calls = FakeClock(), 0

    class Down:
        async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
            return None

        async def send_end(self, call_id: str, payload: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise ConnectionError

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    buffer = TurnBuffer(
        Down(), retry_window_sec=120, retry_delay_sec=50, sleep=sleep, now=clock.now
    )
    await buffer.publish_end(CALL_ID, {})
    assert clock.now() == 1000.0 + 120.0  # 50 + 50 + 20
    assert calls == 3  # intentos en 0, 50 y 100; la última pausa se acota a 20 s


async def test_hanging_send_cannot_exceed_the_retry_window() -> None:
    class Hang:
        async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
            return None

        async def send_end(self, call_id: str, payload: dict[str, Any]) -> None:
            await asyncio.sleep(3600)

    buffer = TurnBuffer(Hang(), retry_window_sec=0.2, retry_delay_sec=0.05)
    async with asyncio.timeout(3):
        await buffer.publish_end(CALL_ID, {})


async def test_timer_waking_exactly_at_the_limit_still_cuts_and_hangs_up() -> None:
    app, clock = FakeAppClient(), FakeClock()
    services = make(app, clock)
    base_sleep = services.sleep

    async def early_sleep(seconds: float) -> None:
        # despierta una pizca antes del límite (imprecisión del temporizador real)
        early = seconds - 0.001 if seconds == 30.0 else seconds  # el corte espera 300 - 270
        await base_sleep(early)  # type: ignore[operator]

    services = CallServices(
        context_source=services.context_source,
        events=services.events,
        clock=clock,
        close=app.aclose,
        sleep=early_sleep,
    )
    engine = FakeEngine(hangup=None)
    engine.clock = clock
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, services)
    assert reason is EndReason.TIME_LIMIT
    assert engine.hangups == 1
    assert app.ends[CALL_ID]["ended_reason"] == "time_limit"


async def test_hard_cut_reports_time_limit_even_if_hangup_fails_and_retries_it() -> None:
    # R4-001 de la revisión: si delete_room falla justo en el corte, la llamada no debe quedar
    # abierta ni registrarse como `failed`: se reintenta el corte y el motivo sigue siendo
    # time_limit.
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(hangup=None, hangup_failures=2)
    engine.clock = clock
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock))
    assert reason is EndReason.TIME_LIMIT
    assert engine.hangups == 3  # dos fallos y un tercer intento que sí cuelga
    assert app.ends[CALL_ID]["ended_reason"] == "time_limit"
    assert app.ends[CALL_ID]["error"] is None


async def test_hard_cut_gives_up_after_bounded_attempts_but_still_reports_time_limit() -> None:
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(hangup=None, hangup_failures=99)
    engine.clock = clock
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock))
    assert reason is EndReason.TIME_LIMIT
    assert engine.hangups == 3  # acotado: no reintenta sin fin
    assert app.ends[CALL_ID]["ended_reason"] == "time_limit"
    assert app.ends[CALL_ID]["error"] == "hangup_failed"  # la sala pudo quedar abierta


async def test_context_failure_starts_generic_after_a_single_timeout() -> None:
    import httpx

    from pt_worker.app_client.http import HttpAppClient

    attempts: list[httpx.Request] = []
    sleeps: list[float] = []

    def boom(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectTimeout("lento")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = HttpAppClient(
        "https://app.test", "tok", transport=httpx.MockTransport(boom), sleep=sleep
    )
    clock = FakeClock()
    app = FakeAppClient()
    services = CallServices(
        context_source=AppContextSource(client),
        events=TurnBuffer(HttpCallEventSink(app), sleep=sleep, now=clock.now),
        clock=clock,
        close=client.aclose,
        sleep=sleep,
    )
    engine = FakeEngine()
    reason = await run_call(CALL_ID, engine, services)
    assert reason is EndReason.COMPLETED
    assert len(attempts) == 1  # un solo intento de GET context
    assert all(s > 100 for s in sleeps)  # solo temporizadores del tope, sin backoff de contexto
    assert engine.started[0]["voice"] == "roberto"  # configuración genérica


async def test_goodbye_that_never_returns_does_not_block_the_hard_cut() -> None:
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(hangup=None, goodbye_hangs=True)
    engine.clock = clock
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock, goodbye_timeout_sec=0.05))
    assert reason is EndReason.TIME_LIMIT
    assert engine.hangups >= 1
    assert app.ends[CALL_ID]["ended_reason"] == "time_limit"
    assert app.ends[CALL_ID]["error"] is None


async def test_hangup_that_never_returns_is_bounded_per_attempt() -> None:
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(hangup=None, hangup_hangs=True)
    engine.clock = clock
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock, hangup_timeout_sec=0.05))
    assert reason is EndReason.TIME_LIMIT
    assert engine.hangups == 3
    assert app.ends[CALL_ID]["error"] == "hangup_failed"


async def test_start_failure_retries_hangup_and_still_publishes_failed() -> None:
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(start_failures=99, hangup_failures=2)
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock, hangup_timeout_sec=0.05))
    assert reason is EndReason.FAILED
    assert engine.hangups == 3  # dos fallos y un tercer intento que sí cuelga
    assert app.ends[CALL_ID]["ended_reason"] == "failed"
    # arranque fallido con valores por defecto: sí se contestó (answered_at ISO) y error = excepción
    datetime.fromisoformat(app.ends[CALL_ID]["answered_at"])
    assert app.ends[CALL_ID]["error"] == "ConnectionError"


async def test_start_failure_with_hanging_hangup_still_publishes_failed() -> None:
    app, clock = FakeAppClient(), FakeClock()
    engine = FakeEngine(start_failures=99, hangup_hangs=True)
    async with asyncio.timeout(3):
        reason = await run_call(CALL_ID, engine, make(app, clock, hangup_timeout_sec=0.05))
    assert reason is EndReason.FAILED
    assert engine.hangups == 3
    assert app.ends[CALL_ID]["ended_reason"] == "failed"


class RaisingContext:
    """Fuente de contexto que lanza el error indicado (409, timeout, 5xx)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def fetch(self, call_id: str) -> dict[str, Any] | None:
        raise self._exc


async def test_context_409_does_not_start_phonic_nor_publish_end_but_hangs_up() -> None:
    app, clock, engine = FakeAppClient(), FakeClock(), FakeEngine()
    services = make(app, clock)
    services = CallServices(
        context_source=RaisingContext(CallAlreadyEndedError("409")),
        events=services.events,
        clock=clock,
        close=app.aclose,
        sleep=services.sleep,
    )
    await run_call(CALL_ID, engine, services)  # no lanza
    assert engine.started == []
    assert app.ends == {}
    assert engine.hangups >= 1


@pytest.mark.parametrize("exc", [TimeoutError("lento"), ConnectionError("5xx")])
async def test_context_timeout_or_5xx_still_starts_generic_conversation(exc: Exception) -> None:
    app, clock, engine = FakeAppClient(), FakeClock(), FakeEngine()
    base = make(app, clock)
    services = CallServices(
        context_source=RaisingContext(exc),
        events=base.events,
        clock=clock,
        close=app.aclose,
        sleep=base.sleep,
    )
    await run_call(CALL_ID, engine, services)
    assert len(engine.started) == 1
    assert engine.started[0]["voice"] == "roberto"
    assert engine.hangups == 0
    assert app.ends[CALL_ID]["ended_reason"] == "completed"


async def test_drain_is_bounded_when_turn_sends_are_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hallazgo del verificador: con envíos serializados y la app lenta, `drain` esperaba sin tope
    # y retrasaba `end`. Ahora espera a lo sumo DRAIN_TIMEOUT_SEC; publish_end entrega el resto.
    from pt_worker.call_bridge.application import run_call as run_call_module
    from pt_worker.call_bridge.application.run_call import _TurnRecorder
    from pt_worker.call_bridge.domain.call import Call

    class SlowEvents:
        async def record_turn(self, *args: Any) -> None:
            await asyncio.sleep(5)

    app, clock = FakeAppClient(), FakeClock()
    services = make(app, clock)
    services = CallServices(
        context_source=services.context_source,
        events=SlowEvents(),  # type: ignore[arg-type]
        clock=clock,
        close=app.aclose,
        sleep=services.sleep,
    )
    monkeypatch.setattr(run_call_module, "DRAIN_TIMEOUT_SEC", 0.05)
    recorder = _TurnRecorder(CALL_ID, Call(CALL_ID), services)
    recorder.handle("user", "hola")
    try:
        async with asyncio.timeout(1):
            await recorder.drain()
    finally:
        for task in list(recorder._tasks):
            task.cancel()
