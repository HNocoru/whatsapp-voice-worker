"""Dobles de prueba compartidos."""

from __future__ import annotations


class FakeClock:
    """Reloj controlado por la prueba: `advance` mueve el tiempo sin esperar."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
