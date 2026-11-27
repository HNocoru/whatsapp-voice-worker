"""TurnBuffer: entrega de turnos con envíos concurrentes en vuelo."""

from __future__ import annotations

import asyncio
from typing import Any

from pt_worker.call_events.application import TurnBuffer
from tests.fakes import FakeClock

CALL_ID = "3f2b8c1e-5a47-4d0e-9b6a-1c2d3e4f5a6b"


class GatedSink:
    """Sink con latencia controlada: cada envío espera su compuerta."""

    def __init__(self, fail_calls: frozenset[int] = frozenset()) -> None:
        self.gates: list[asyncio.Event] = []
        self.batches: list[list[int]] = []
        self.delivered: list[int] = []
        self.inflight = 0
        self.max_inflight = 0
        self.calls = 0
        self._fail = fail_calls

    async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
        index = self.calls
        self.calls += 1
        self.batches.append([t["seq"] for t in turns])
        gate = asyncio.Event()
        self.gates.append(gate)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await gate.wait()
            if index in self._fail:
                msg = "app caída"
                raise ConnectionError(msg)
        finally:
            self.inflight -= 1
        self.delivered.extend(t["seq"] for t in turns)

    async def send_end(self, call_id: str, payload: dict[str, Any]) -> None:
        return None


async def _ticks() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _buffer(sink: GatedSink) -> TurnBuffer:
    clock = FakeClock()

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    return TurnBuffer(sink, sleep=sleep, now=clock.now)


async def test_three_quick_turns_are_delivered_once_each_in_order() -> None:
    sink = GatedSink()
    buffer = _buffer(sink)
    tasks = []
    for seq, role in ((1, "user"), (2, "assistant"), (3, "user")):
        tasks.append(asyncio.ensure_future(buffer.record_turn(CALL_ID, seq, role, "x", seq)))
        await _ticks()
    assert sink.max_inflight == 1  # un solo POST en vuelo por llamada
    while sink.gates and not all(t.done() for t in tasks):
        for gate in sink.gates:
            gate.set()
        await _ticks()
    await buffer.publish_end(CALL_ID, {"ended_reason": "completed"})
    assert sink.delivered == [1, 2, 3]
    assert sink.max_inflight == 1


async def test_after_a_failure_retry_resends_pending_without_loss_or_reorder() -> None:
    sink = GatedSink(fail_calls=frozenset({0}))
    buffer = _buffer(sink)
    t1 = asyncio.ensure_future(buffer.record_turn(CALL_ID, 1, "user", "a", 0))
    await _ticks()
    t2 = asyncio.ensure_future(buffer.record_turn(CALL_ID, 2, "assistant", "b", 10))
    await _ticks()
    sink.gates[0].set()  # el primer envío falla
    await _ticks()
    for gate in sink.gates:
        gate.set()
    await _ticks()
    for gate in sink.gates:
        gate.set()
    await asyncio.gather(t1, t2)
    publish = asyncio.ensure_future(buffer.publish_end(CALL_ID, {"ended_reason": "completed"}))
    while not publish.done():
        for gate in sink.gates:
            gate.set()
        await _ticks()
    assert sink.delivered == [1, 2]
    assert sink.max_inflight == 1
