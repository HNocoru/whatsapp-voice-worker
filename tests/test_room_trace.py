"""Pruebas del trazado de la sala (instrumentación; no cambia la espera)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from pt_worker.app_client.fake import FakeAppClient
from pt_worker.call_bridge.infrastructure.livekit import room_trace
from pt_worker.call_bridge.infrastructure.livekit.server import handle_job
from tests.fakes import FakeClock
from tests.test_run_call import FakeCtx, make

SECRET = "SECRET-VALUE-123"  # noqa: S105 - valor de prueba que NO debe llegar a ningún log
KIND_CONNECTOR = 5  # ParticipantKind.PARTICIPANT_KIND_CONNECTOR
STATE_ACTIVE = 2  # ParticipantState.PARTICIPANT_STATE_ACTIVE


class RoomParticipant:
    identity = "wa-connector"
    kind = KIND_CONNECTOR
    kind_details = [1]  # noqa: RUF012
    state = STATE_ACTIVE
    attributes = {"call_id": SECRET}  # noqa: RUF012
    metadata = SECRET


class FakeRoom:
    name = "call-room-1"

    def __init__(self) -> None:
        self.remote_participants: dict[str, Any] = {}


class Clock:
    """Reloj y sleep falsos: cada sleep avanza el tiempo y puede disparar un efecto."""

    def __init__(self, room: FakeRoom, appear_at_tick: int | None = None) -> None:
        self.t = 100.0
        self.ticks = 0
        self.room = room
        self.appear_at_tick = appear_at_tick

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.ticks += 1
        if self.ticks == self.appear_at_tick:
            self.room.remote_participants["wa-connector"] = RoomParticipant()


async def test_trace_logs_participants_after_they_appear_without_attribute_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    room = FakeRoom()
    clock = Clock(room, appear_at_tick=2)
    caplog.set_level(logging.INFO)
    await room_trace.trace_room(
        room, started=100.0, interval=2.0, duration=6.0, sleep=clock.sleep, now=clock.now
    )
    lines = [r.getMessage() for r in caplog.records if "room_trace" in r.getMessage()]
    assert len(lines) == 4  # t=0, 2, 4, 6
    assert "remote=0" in lines[0]
    assert "remote=0" in lines[1]
    assert "remote=1" in lines[2]
    assert "identity=wa-connector" in lines[2]
    assert "kind=PARTICIPANT_KIND_CONNECTOR" in lines[2]
    assert "state=PARTICIPANT_STATE_ACTIVE" in lines[2]
    assert "attribute_keys=['call_id']" in lines[2]
    assert "metadata_empty=False" in lines[2]
    assert "t=4.0" in lines[2]
    assert SECRET not in caplog.text


async def test_trace_failure_is_swallowed_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenRoom:
        @property
        def remote_participants(self) -> dict[str, Any]:
            msg = SECRET
            raise RuntimeError(msg)

    clock = Clock(FakeRoom())
    await room_trace.trace_room(
        BrokenRoom(), started=100.0, interval=2.0, duration=6.0, sleep=clock.sleep, now=clock.now
    )
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


async def test_handle_job_traces_wait_and_cancels_trace_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ctx: Any = FakeCtx("{}")
    ctx.room = FakeRoom()
    gate = asyncio.Event()

    async def slow_wait(_ctx: Any) -> Any:
        await asyncio.sleep(0.05)  # deja correr la tarea de trazado
        gate.set()
        return RoomParticipant()

    await handle_job(
        ctx,
        lambda: make(FakeAppClient(), FakeClock()),
        trace_interval=0.01,
        trace_duration=1000.0,
        wait=slow_wait,
    )
    text = caplog.text
    assert "room=call-room-1" in text
    assert "wait_start" in text
    assert "wait_done" in text
    assert "identity=wa-connector" in text
    assert SECRET not in text
    assert ctx.shutdowns == ["missing_call_id"]
    # la tarea (duración enorme) debió cancelarse al terminar: no quedan tareas de trazado
    pending = [t for t in asyncio.all_tasks() if "trace_room" in repr(t)]
    assert pending == []


async def test_handle_job_logs_wait_exception_and_propagates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ctx: Any = FakeCtx("{}")
    ctx.room = FakeRoom()

    async def failing_wait(_ctx: Any) -> Any:
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await handle_job(
            ctx, lambda: make(FakeAppClient(), FakeClock()), wait=failing_wait, trace_interval=0.01
        )
    assert "wait_failed" in caplog.text
    assert "TimeoutError" in caplog.text


async def test_trace_failure_does_not_break_handle_job() -> None:
    ctx: Any = FakeCtx("{}")  # sin room: el trazado falla por dentro
    await handle_job(ctx, lambda: make(FakeAppClient(), FakeClock()), trace_interval=0.01)
    assert ctx.shutdowns == ["missing_call_id"]


async def test_trace_failure_breaks_nothing_when_wait_yields() -> None:
    # El trazado falla (la sala no existe) mientras la espera cede el control: si la excepción
    # del trazado se propagara, handle_job se rompería. Antes la prueba pasaba aunque se propagara.
    ctx: Any = FakeCtx("{}")

    async def yielding_wait(c: Any) -> Any:
        await asyncio.sleep(0.05)
        return await c.wait_for_participant()

    await handle_job(
        ctx,
        lambda: make(FakeAppClient(), FakeClock()),
        wait=yielding_wait,
        trace_interval=0.01,
    )
    assert ctx.shutdowns == ["missing_call_id"]
