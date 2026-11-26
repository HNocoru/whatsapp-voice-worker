"""Dominio de la llamada: máquina de estados y límites de duración.

Solo stdlib. El tiempo entra como parámetro (segundos monotónicos) para poder probar el tope
de 5 min con un reloj falso, sin esperar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CallState(StrEnum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDING = "ending"
    ENDED = "ended"


class EndReason(StrEnum):
    """Valores de `ended_reason` del contrato (docs/04-worker-contract.md)."""

    COMPLETED = "completed"
    CALLER_HANGUP = "caller_hangup"
    TIME_LIMIT = "time_limit"
    FAILED = "failed"


class InvalidTransitionError(Exception):
    """Se intentó una transición de estado que la llamada no permite."""


_ALLOWED: dict[CallState, frozenset[CallState]] = {
    CallState.CONNECTING: frozenset({CallState.ACTIVE, CallState.ENDED}),
    CallState.ACTIVE: frozenset({CallState.ENDING, CallState.ENDED}),
    CallState.ENDING: frozenset({CallState.ENDED}),
    CallState.ENDED: frozenset(),
}


@dataclass(frozen=True)
class CallLimits:
    """Tope de duración: despedida a 4:30 y corte a 5:00 por defecto."""

    max_call_seconds: int = 300
    goodbye_at_seconds: int = 270

    def __post_init__(self) -> None:
        if self.goodbye_at_seconds <= 0 or self.max_call_seconds <= 0:
            msg = "Los límites deben ser positivos"
            raise ValueError(msg)
        if self.goodbye_at_seconds >= self.max_call_seconds:
            msg = "La despedida debe ocurrir antes del corte máximo"
            raise ValueError(msg)


@dataclass(frozen=True)
class Turn:
    """Un turno de transcripción (`seq` es la clave de idempotencia del contrato)."""

    seq: int
    role: str  # "user" | "assistant"
    text: str
    started_ms: int


class Call:
    """Ciclo de vida de una llamada: connecting → active → ending → ended."""

    def __init__(self, call_id: str, limits: CallLimits | None = None) -> None:
        self.call_id = call_id
        self.limits = limits or CallLimits()
        self.state = CallState.CONNECTING
        self.ended_reason: EndReason | None = None
        self._started_at: float | None = None
        self._ended_at: float | None = None

    def _transition(self, new_state: CallState) -> None:
        if new_state not in _ALLOWED[self.state]:
            msg = f"Transición inválida: {self.state.value} -> {new_state.value}"
            raise InvalidTransitionError(msg)
        self.state = new_state

    def start(self, now: float) -> None:
        self._transition(CallState.ACTIVE)
        self._started_at = now

    def elapsed(self, now: float) -> float:
        """Segundos desde que la llamada se activó; se congela al terminar."""
        if self._started_at is None:
            return 0.0
        end = self._ended_at if self._ended_at is not None else now
        return max(0.0, end - self._started_at)

    def should_say_goodbye(self, now: float) -> bool:
        return self.state == CallState.ACTIVE and (
            self.elapsed(now) >= self.limits.goodbye_at_seconds
        )

    def is_over_limit(self, now: float) -> bool:
        return self.state in (CallState.ACTIVE, CallState.ENDING) and (
            self.elapsed(now) >= self.limits.max_call_seconds
        )

    def begin_ending(self) -> None:
        self._transition(CallState.ENDING)

    def end(self, reason: EndReason, now: float) -> None:
        self._transition(CallState.ENDED)
        self.ended_reason = reason
        self._ended_at = now

    def duration_sec(self, now: float) -> int:
        return int(self.elapsed(now))
