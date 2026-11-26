"""Dominio Call + CallLimits: tope de 5 min probado con reloj falso."""

from __future__ import annotations

import pytest

from pt_worker.call_bridge.domain.call import (
    Call,
    CallLimits,
    CallState,
    EndReason,
    InvalidTransitionError,
)
from tests.fakes import FakeClock


def make_active_call() -> tuple[Call, FakeClock]:
    clock = FakeClock()
    call = Call("call-1")
    call.start(clock.now())
    return call, clock


def test_default_limits_are_4_30_and_5_00() -> None:
    limits = CallLimits()
    assert limits.goodbye_at_seconds == 270
    assert limits.max_call_seconds == 300


@pytest.mark.parametrize(("goodbye", "maximum"), [(300, 300), (310, 300), (0, 300), (270, 0)])
def test_invalid_limits_are_rejected(goodbye: int, maximum: int) -> None:
    with pytest.raises(ValueError, match="deben|antes"):
        CallLimits(max_call_seconds=maximum, goodbye_at_seconds=goodbye)


def test_goodbye_fires_at_4_30_not_before() -> None:
    call, clock = make_active_call()
    clock.advance(269)
    assert not call.should_say_goodbye(clock.now())
    clock.advance(1)
    assert call.should_say_goodbye(clock.now())


def test_hangup_limit_fires_at_5_00_not_before() -> None:
    call, clock = make_active_call()
    clock.advance(299)
    assert not call.is_over_limit(clock.now())
    clock.advance(1)
    assert call.is_over_limit(clock.now())


def test_limits_come_from_the_app_context() -> None:
    clock = FakeClock()
    call = Call("call-1", CallLimits(max_call_seconds=60, goodbye_at_seconds=40))
    call.start(clock.now())
    clock.advance(40)
    assert call.should_say_goodbye(clock.now())
    clock.advance(20)
    assert call.is_over_limit(clock.now())


def test_goodbye_is_not_requested_once_ending() -> None:
    call, clock = make_active_call()
    clock.advance(280)
    call.begin_ending()
    assert not call.should_say_goodbye(clock.now())


def test_end_records_reason_and_freezes_duration() -> None:
    call, clock = make_active_call()
    clock.advance(120)
    call.end(EndReason.CALLER_HANGUP, clock.now())
    clock.advance(500)  # el tiempo posterior no cuenta
    assert call.state is CallState.ENDED
    assert call.ended_reason is EndReason.CALLER_HANGUP
    assert call.duration_sec(clock.now()) == 120


def test_full_lifecycle() -> None:
    call, clock = make_active_call()
    assert call.state is CallState.ACTIVE
    call.begin_ending()
    assert call.state is CallState.ENDING
    call.end(EndReason.TIME_LIMIT, clock.now())
    assert call.state is CallState.ENDED


@pytest.mark.parametrize("bad", ["start_twice", "end_twice", "ending_before_start", "revive"])
def test_invalid_transitions_fail(bad: str) -> None:
    call = Call("call-1")
    clock = FakeClock()
    if bad == "ending_before_start":
        with pytest.raises(InvalidTransitionError):
            call.begin_ending()
        return
    call.start(clock.now())
    if bad == "start_twice":
        with pytest.raises(InvalidTransitionError):
            call.start(clock.now())
        return
    call.end(EndReason.COMPLETED, clock.now())
    with pytest.raises(InvalidTransitionError):
        call.end(EndReason.FAILED, clock.now()) if bad == "end_twice" else call.start(clock.now())
    assert call.ended_reason is EndReason.COMPLETED  # el segundo intento no cambia nada
