"""Trazado de la sala para diagnosticar por qué el participante del conector no llega.

Solo instrumentación: no cambia la espera de `handle_job`. Cómo se leen los datos en el paquete
instalado (`.venv/lib/python3.12/site-packages/livekit/`):

- `ctx.room`: `agents/job.py:527`; `Room.remote_participants` (identity -> RemoteParticipant):
  `rtc/room.py:264-271`.
- `Participant.identity`, `.metadata`, `.attributes`, `.kind`, `.kind_details` y `.state` SÍ están
  expuestos en el objeto de alto nivel: `rtc/participant.py:163-188` (leen `self._info`, el proto
  `ParticipantInfo`), así que no hace falta tocar `_info`.
- Los enums se convierten a nombre con `rtc.ParticipantKind/ParticipantKindDetail/ParticipantState`
  (`rtc/__init__.py:24-26`, wrappers de protobuf con `.Name(valor)`).

Privacidad: de atributos y metadata solo se registran las CLAVES de los atributos y si la metadata
está vacía; nunca valores, tokens ni secretos.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from livekit import rtc

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 2.0
DEFAULT_DURATION_S = 30.0


def _enum_name(enum: Any, value: object) -> str:
    try:
        return str(enum.Name(value))
    except Exception:  # noqa: BLE001 - valor desconocido: se muestra tal cual
        return str(value)


def describe_participant(participant: Any) -> str:
    """Una línea con identity/kind/kind_details/state y SOLO claves de atributos."""
    parts = [f"identity={getattr(participant, 'identity', '?')}"]
    kind = getattr(participant, "kind", None)
    parts.append(f"kind={_enum_name(rtc.ParticipantKind, kind) if kind is not None else '?'}")
    details = getattr(participant, "kind_details", None)
    if details is not None:
        names = [_enum_name(rtc.ParticipantKindDetail, d) for d in details]
        parts.append(f"kind_details={names}")
    state = getattr(participant, "state", None)
    if state is not None:
        parts.append(f"state={_enum_name(rtc.ParticipantState, state)}")
    attributes = getattr(participant, "attributes", None) or {}
    parts.append(f"attribute_keys={sorted(attributes)}")
    parts.append(f"metadata_empty={not getattr(participant, 'metadata', '')}")
    return " ".join(parts)


async def trace_room(
    room: Any,
    *,
    started: float,
    interval: float = DEFAULT_INTERVAL_S,
    duration: float = DEFAULT_DURATION_S,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """Cada `interval` s durante `duration` s registra los participantes remotos. Nunca lanza."""
    try:
        while True:
            elapsed = now() - started
            remote = list(room.remote_participants.values())
            lines = [describe_participant(p) for p in remote]
            logger.info("room_trace t=%.1f remote=%d %s", elapsed, len(remote), " | ".join(lines))
            if elapsed >= duration:
                return
            await sleep(interval)
    except Exception as exc:  # noqa: BLE001 - el trazado jamás debe afectar a la llamada
        logger.warning("room_trace falló: %s", type(exc).__name__)


async def traced_wait(
    ctx: Any,
    wait: Callable[[Any], Awaitable[Any]],
    *,
    started: float,
    now: Callable[[], float] = time.monotonic,
) -> Any:
    """Envuelve la espera con marcas de tiempo; la excepción de la espera se propaga igual."""
    logger.info("room_trace wait_start t=%.1f", now() - started)
    try:
        participant = await wait(ctx)
    except Exception as exc:
        logger.info("room_trace wait_failed t=%.1f exc=%s", now() - started, type(exc).__name__)
        raise
    try:
        described = describe_participant(participant)
    except Exception as exc:  # noqa: BLE001
        described = f"describe_failed={type(exc).__name__}"
    logger.info("room_trace wait_done t=%.1f %s", now() - started, described)
    return participant


def log_job_start(ctx: Any, started: float, *, phase: str) -> None:
    """Registra room name y job id si están disponibles (nunca lanza)."""
    try:
        room_name = getattr(getattr(ctx, "room", None), "name", None)
        job_id = getattr(getattr(ctx, "job", None), "id", None)
        logger.info(
            "room_trace job_%s room=%s job_id=%s started_monotonic=%.3f",
            phase,
            room_name or "(aún no disponible)",
            job_id,
            started,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("room_trace falló: %s", type(exc).__name__)
