"""TurnBuffer: entrega de turnos con envíos concurrentes en vuelo."""

from __future__ import annotations

import asyncio
from typing import Any

from pt_worker.call_events.application import TurnBuffer
from tests.fakes import FakeClock

CALL_ID = "3f2b8c1e-5a47-4d0e-9b6a-1c2d3e4f5a6b"


class GatedSink:
    """Sink con latencia controlada: cada envío espera su compuerta; el 3.º falla al abrirse."""

    def __init__(self) -> None:
        self.gates: list[asyncio.Event] = []
        self.delivered: list[int] = []
        self.calls = 0

    async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None:
        index = self.calls
        self.calls += 1
        gate = asyncio.Event()
        self.gates.append(gate)
        if index == 2:
            msg = "app caída"
            raise ConnectionError(msg)  # falla sin esperar, con los envíos 1 y 2 aún en vuelo
        if index < 2:
            await gate.wait()  # solo los envíos 1 y 2 quedan en vuelo; los reintentos no esperan
        self.delivered.extend(t["seq"] for t in turns)

    async def send_end(self, call_id: str, payload: dict[str, Any]) -> None:
        return None


async def test_turns_survive_inflight_sends_that_complete_after_a_failure() -> None:
    sink, clock = GatedSink(), FakeClock()

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    buffer = TurnBuffer(sink, sleep=sleep, now=clock.now)
    t1 = asyncio.ensure_future(buffer.record_turn(CALL_ID, 1, "user", "a", 0))
    await asyncio.sleep(0)
    t2 = asyncio.ensure_future(buffer.record_turn(CALL_ID, 2, "assistant", "b", 10))
    await asyncio.sleep(0)
    await buffer.record_turn(CALL_ID, 3, "user", "c", 20)  # falla: 1 y 2 siguen en vuelo
    sink.gates[0].set()
    await t1
    sink.gates[1].set()
    await t2
    await buffer.publish_end(CALL_ID, {"ended_reason": "completed"})
    # Lista exacta de lo entregado, sin `set`. El 1 llega dos veces por diseño (el envío 2 lo
    # incluía mientras el 1 seguía en vuelo; idempotente por seq en la app), pero ningún turno
    # se reenvía después de confirmarse ni se pierde. Con borrado posicional faltaría el 3.
    assert sink.delivered == [1, 1, 2, 3]
    assert sink.calls == 4  # 3 envíos de record_turn + 1 flush de publish_end con solo el turno 3
