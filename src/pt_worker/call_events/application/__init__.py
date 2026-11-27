"""Turnos y fin de llamada hacia la app, con reintento en memoria.

Contrato (docs/04-worker-contract.md): `turns` y `end` se reintentan hasta 2 min después de
colgar y ningún error de la app tumba la llamada.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

RETRY_WINDOW_SEC = 120.0
RETRY_DELAY_SEC = 2.0


class CallEventSink(Protocol):
    """Destino de turnos y fin (hoy HTTP). Lanza ante cualquier fallo de entrega."""

    async def send_turns(self, call_id: str, turns: list[dict[str, Any]]) -> None: ...

    async def send_end(self, call_id: str, payload: dict[str, Any]) -> None: ...


class TurnBuffer:
    """Encola turnos en memoria y los entrega al sink; `publish_end` cierra con reintento."""

    def __init__(
        self,
        sink: CallEventSink,
        *,
        retry_window_sec: float = RETRY_WINDOW_SEC,
        retry_delay_sec: float = RETRY_DELAY_SEC,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._window = retry_window_sec
        self._delay = retry_delay_sec
        self._sleep = sleep
        self._now = now
        self._pending: dict[str, list[dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}  # single-flight: un POST turns por llamada

    async def record_turn(
        self, call_id: str, seq: int, role: str, text: str, started_ms: int
    ) -> None:
        self._pending.setdefault(call_id, []).append(
            {"seq": seq, "role": role, "text": text, "started_ms": started_ms}
        )
        await self._flush_turns(call_id)  # un fallo deja los turnos para el siguiente intento

    async def _flush_turns(self, call_id: str) -> bool:
        # Un solo envío en vuelo por llamada: los turnos nuevos esperan y salen en el siguiente.
        # La app no impone UNIQUE(call_id, position); evitar el reenvío simultáneo evita duplicados.
        async with self._locks.setdefault(call_id, asyncio.Lock()):
            return await self._send_pending(call_id)

    async def _send_pending(self, call_id: str) -> bool:
        turns = self._pending.get(call_id)
        if not turns:
            return True
        sent = list(turns)
        try:
            await self._sink.send_turns(call_id, sent)
        except Exception as exc:  # noqa: BLE001 - ningún error de la app tumba la llamada
            logger.warning("turnos sin entregar (%s); se reintentan", type(exc).__name__)
            return False
        # Se borra por `seq` y no por posición: `record_turn` agrega a la lista mientras se envía.
        delivered = {turn["seq"] for turn in sent}
        turns[:] = [turn for turn in turns if turn["seq"] not in delivered]
        return True

    async def publish_end(self, call_id: str, payload: dict[str, Any]) -> None:
        """Entrega turnos pendientes y `end`; reintenta hasta `retry_window_sec`. No lanza."""
        deadline = self._now() + self._window
        while True:
            remaining = deadline - self._now()
            if remaining <= 0:
                logger.error("se agotó la ventana de reintento; end/turnos perdidos")
                self._pending.pop(call_id, None)
                self._locks.pop(call_id, None)
                return
            try:
                async with asyncio.timeout(remaining):  # el último intento no rebasa el plazo
                    if await self._flush_turns(call_id):
                        await self._sink.send_end(call_id, payload)
                        self._pending.pop(call_id, None)
                        self._locks.pop(call_id, None)
                        return
            except Exception as exc:  # noqa: BLE001
                logger.warning("end sin entregar (%s); se reintenta", type(exc).__name__)
            remaining = deadline - self._now()
            if remaining > 0:
                await self._sleep(min(self._delay, remaining))
