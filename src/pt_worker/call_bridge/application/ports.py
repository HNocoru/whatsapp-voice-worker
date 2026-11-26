"""Puertos de call_bridge. Los adaptadores viven en infrastructure."""

from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    """Tiempo monotónico en segundos; en tests se sustituye por un reloj falso."""

    def now(self) -> float: ...
