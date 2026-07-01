"""Tests for the adaptive read-speed ladder policy engine (pure, never raises)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from platterpus import read_speed_ladder as rsl
from platterpus.read_speed_ladder import (
    DEFAULT_LADDER,
    FLOOR_SPEED,
    MAX_SECURE_REREP,
    SpeedAttempt,
    attempts_to_report,
    next_step,
    read_errors_present,
)

# --- next_step: step DOWN the speed ladder, then escalate -Z at the floor -----


def test_next_step_steps_down_the_speed_ladder() -> None:
    # From the drive's max (0), the next rung is 8×, keeping -Z unchanged.
    step = next_step(current_speed=0, current_secure_rerip=0)
    assert step is not None
    assert step.speed == 8 and step.secure_rerip_matches == 0
    # 8× → 4× → 2× (the floor).
    assert next_step(current_speed=8, current_secure_rerip=0).speed == 4
    assert next_step(current_speed=4, current_secure_rerip=0).speed == FLOOR_SPEED


def test_next_step_escalates_z_at_the_floor() -> None:
    # At the floor speed, don't go slower — re-read harder (-Z 2, then 3).
    step = next_step(current_speed=FLOOR_SPEED, current_secure_rerip=0)
    assert step is not None
    assert step.speed == FLOOR_SPEED and step.secure_rerip_matches == 2
    step2 = next_step(current_speed=FLOOR_SPEED, current_secure_rerip=2)
    assert step2.speed == FLOOR_SPEED and step2.secure_rerip_matches == 3


def test_next_step_exhausted_returns_none() -> None:
    # Floor speed + max -Z → nothing left to try (the disc will be FLAGGED).
    assert (
        next_step(current_speed=FLOOR_SPEED, current_secure_rerip=MAX_SECURE_REREP)
        is None
    )


def test_next_step_unknown_speed_treated_as_top_rung() -> None:
    # A speed not on the ladder still makes progress toward the floor.
    step = next_step(current_speed=99, current_secure_rerip=0)
    assert step is not None
    assert step.speed == DEFAULT_LADDER[1]  # steps to the second rung


def test_next_step_preserves_z_while_stepping_speed() -> None:
    # If the user already had -Z=2, stepping the speed keeps it.
    step = next_step(current_speed=0, current_secure_rerip=2)
    assert step.speed == 8 and step.secure_rerip_matches == 2


# --- read_errors_present (the escalation trigger) -----------------------------


class _Track:
    def __init__(self, status: str = "") -> None:
        self.status = status


class _Log:
    def __init__(self, health_status: str = "", tracks=()) -> None:
        self.health_status = health_status
        self.tracks = tracks


def test_read_errors_present_true_on_error_health() -> None:
    assert read_errors_present(_Log(health_status="3 ripping errors")) is True


def test_read_errors_present_false_on_clean_health() -> None:
    assert read_errors_present(_Log(health_status="No errors occurred")) is False


def test_read_errors_present_false_on_unknown_disc() -> None:
    # An empty health + no track errors (e.g. a disc not in AccurateRip) is NOT
    # an error — the ladder must not spin on it.
    assert read_errors_present(_Log(health_status="", tracks=())) is False


def test_read_errors_present_true_on_track_error_status() -> None:
    log = _Log(health_status="", tracks=(_Track("ripped with errors"),))
    assert read_errors_present(log) is True


def test_read_errors_present_never_raises_on_junk() -> None:
    assert read_errors_present(object()) is False
    assert read_errors_present(None) is False


def test_read_errors_present_swallows_internal_failure() -> None:
    # A log whose `tracks` is a truthy non-iterable makes the loop raise; the
    # predicate must swallow it and assume "no errors" rather than crash the rip.
    class _Bad:
        health_status = ""
        tracks = 5  # `5 or ()` → 5 → `for x in 5` raises TypeError

    assert read_errors_present(_Bad()) is False


# --- attempts_to_report -------------------------------------------------------


def test_attempts_to_report_records_history_and_resolution() -> None:
    attempts = [
        SpeedAttempt(1, 0, 0, clean=False),
        SpeedAttempt(2, 8, 0, clean=True),
    ]
    report = attempts_to_report(attempts)
    assert report is not None
    assert report["escalated"] is True
    assert report["unresolved"] is False
    assert report["final_speed"] == 8 and report["final_speed_label"] == "8×"
    assert len(report["attempts"]) == 2
    assert report["attempts"][0]["speed_label"] == "max speed"


def test_attempts_to_report_flags_unresolved_disc() -> None:
    # The disc never read clean, even at the floor → unresolved (FLAGGED).
    attempts = [
        SpeedAttempt(1, 0, 0, clean=False),
        SpeedAttempt(2, 2, 3, clean=False),
    ]
    report = attempts_to_report(attempts)
    assert report["unresolved"] is True


def test_attempts_to_report_single_clean_pass_not_escalated() -> None:
    report = attempts_to_report([SpeedAttempt(1, 0, 0, clean=True)])
    assert report["escalated"] is False and report["unresolved"] is False


def test_attempts_to_report_empty_is_none() -> None:
    assert attempts_to_report([]) is None


# --- Never-raises property ----------------------------------------------------


@given(
    st.integers(min_value=-5, max_value=100),
    st.integers(min_value=-5, max_value=10),
)
def test_next_step_never_raises(speed: int, z: int) -> None:
    result = next_step(current_speed=speed, current_secure_rerip=z)
    assert result is None or isinstance(result, rsl.LadderStep)


def _boom(*_a, **_k):
    raise RuntimeError("internal failure")


def test_next_step_swallows_internal_failure(monkeypatch) -> None:
    # Belt-and-braces: even if an internal helper blew up, next_step degrades to
    # "stop escalating" (None) rather than crashing the rip.
    monkeypatch.setattr(rsl, "_speed_label", _boom)
    assert next_step(current_speed=0, current_secure_rerip=0) is None


def test_attempts_to_report_swallows_internal_failure(monkeypatch) -> None:
    monkeypatch.setattr(rsl, "_speed_label", _boom)
    assert attempts_to_report([SpeedAttempt(1, 0, 0, clean=True)]) is None
