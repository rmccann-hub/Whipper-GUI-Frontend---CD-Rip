"""Tests for platterpus.log_buffer (the in-memory session log for the report)."""

from __future__ import annotations

import logging

from platterpus.log_buffer import SessionLogBuffer


def _record(message: str, created: float) -> logging.LogRecord:
    r = logging.LogRecord("t", logging.INFO, __file__, 0, message, None, None)
    r.created = created
    return r


def _buffer() -> SessionLogBuffer:
    b = SessionLogBuffer()
    b.setFormatter(logging.Formatter("%(message)s"))
    return b


def test_captures_formatted_lines_in_order() -> None:
    b = _buffer()
    for i, msg in enumerate(["a", "b", "c"]):
        b.emit(_record(msg, float(i)))
    assert b.lines_excluding([]) == ["a", "b", "c"]
    assert b.truncated is False


def test_lines_excluding_drops_other_rip_windows() -> None:
    b = _buffer()
    b.emit(_record("setup before any rip", 100.0))
    b.emit(_record("other album rip line", 150.0))
    b.emit(_record("inter-rip activity", 200.0))
    b.emit(_record("my rip line", 250.0))
    # Exclude the other album's rip window [140,160]; keep everything else,
    # including general session lines on either side and this rip's own line.
    kept = b.lines_excluding([(140.0, 160.0)])
    assert kept == ["setup before any rip", "inter-rip activity", "my rip line"]


def test_window_bounds_are_inclusive() -> None:
    b = _buffer()
    b.emit(_record("on start edge", 10.0))
    b.emit(_record("on end edge", 20.0))
    assert b.lines_excluding([(10.0, 20.0)]) == []


def test_multiple_windows_excluded() -> None:
    b = _buffer()
    for i in range(6):
        b.emit(_record(f"line{i}", float(i)))
    # Drop lines at t=1 and t=4.
    kept = b.lines_excluding([(1.0, 1.0), (4.0, 4.0)])
    assert kept == ["line0", "line2", "line3", "line5"]


def test_emit_never_raises_on_bad_format(monkeypatch) -> None:
    # A formatting blow-up must be swallowed (handlers can't crash the app).
    b = _buffer()
    monkeypatch.setattr(logging, "raiseExceptions", False)

    def boom(_record: logging.LogRecord) -> str:
        raise ValueError("bad format")

    b.format = boom  # type: ignore[method-assign]
    b.emit(_record("x", 1.0))  # must not raise
    assert b.lines_excluding([]) == []
