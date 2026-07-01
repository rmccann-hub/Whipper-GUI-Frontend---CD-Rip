"""Tests for platterpus.workers.rip_worker.

We drive the worker synchronously (no QThread, no event loop) — Qt
signals are callable regardless of whether an event loop is running.
Connected slots receive emissions immediately because we use direct
connections by default. This keeps the tests fast and deterministic.

The RipBackend is replaced with a fake so we don't need a real
whipper binary.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from platterpus.adapters.rip_backend import (
    RipBackend,
    RipError,
    RipHandle,
)
from platterpus.workers.rip_worker import (
    RipParameters,
    RipWorker,
    _describe_activity,
)

# The `qapp` fixture comes from tests/conftest.py. Worker tests don't
# strictly need a QApplication (QCoreApplication would be enough), but
# the UI tests in the same suite do — so we standardize on the wider
# fixture to avoid "QCoreApplication created, can't upgrade" crashes.


# --- Fakes ----------------------------------------------------------------


class _FakeHandle:
    """Implements the RipHandle interface for the worker to consume."""

    def __init__(
        self,
        lines: Iterable[str] = (),
        exit_code: int = 0,
    ) -> None:
        self._lines: list[str] = list(lines)
        self._exit_code: int = exit_code
        self.cancel_calls: int = 0

    def log_lines(self) -> Iterable[str]:
        yield from self._lines

    def wait(self, timeout: float | None = None) -> int:
        return self._exit_code

    def cancel(self, term_timeout: float = 5.0) -> int:
        self.cancel_calls += 1
        return -15


class _FakeBackend(RipBackend):
    """Backend whose `rip()` returns a pre-baked _FakeHandle."""

    def __init__(self, handle: _FakeHandle | None = None) -> None:
        self._handle: _FakeHandle | None = handle
        self._raise_on_rip: Exception | None = None
        self.rip_calls: list[dict[str, object]] = []

    def set_handle(self, handle: _FakeHandle) -> None:
        self._handle = handle

    def raise_on_rip(self, exc: Exception) -> None:
        self._raise_on_rip = exc

    # ABC plumbing — not used by the worker tests but required to be a
    # non-abstract subclass.
    def list_drives(self) -> list:  # type: ignore[type-arg]
        return []

    def disc_info(self, drive: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def rip(
        self,
        drive: str,
        release_id: str,
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
        cover_art: str = "",
        max_retries: int = 5,
        secure_rerip_matches: int = 0,
        read_offset_override: int | None = None,
        metadata=None,
        read_speed: int = 0,
    ) -> RipHandle:
        self.rip_calls.append(
            {
                "drive": drive,
                "release_id": release_id,
                "output_dir": output_dir,
                "unknown": unknown,
                "cover_art": cover_art,
                "max_retries": max_retries,
                "secure_rerip_matches": secure_rerip_matches,
                "read_offset_override": read_offset_override,
                "metadata": metadata,
                "read_speed": read_speed,
            }
        )
        if self._raise_on_rip:
            raise self._raise_on_rip
        assert self._handle is not None
        return self._handle  # type: ignore[return-value]

    def version(self) -> str:
        return "fake 0.0.0"


def _params(tmp_path: Path, **overrides: object) -> RipParameters:
    defaults: dict = {
        "drive": "/dev/sr0",
        "release_id": "mbid-abc",
        "output_dir": tmp_path,
        "track_template": "t",
        "disc_template": "d",
    }
    defaults.update(overrides)
    return RipParameters(**defaults)


# --- Signal-collector helper ----------------------------------------------


class _Signals:
    """Accumulates signal emissions for assertion."""

    def __init__(self) -> None:
        self.log_lines: list[str] = []
        self.progress: list[tuple[float, float]] = []  # (overall, task)
        self.statuses: list[str] = []
        self.current_tracks: list[int] = []
        self.errors: list[str] = []
        self.finished: list[tuple[bool, str]] = []

    def attach(self, worker: RipWorker) -> None:
        worker.log_line.connect(self.log_lines.append)
        worker.progress.connect(
            lambda overall, task: self.progress.append((overall, task))
        )
        worker.status.connect(self.statuses.append)
        worker.current_track.connect(self.current_tracks.append)
        worker.error.connect(self.errors.append)
        worker.finished.connect(lambda ok, path: self.finished.append((ok, path)))


# --- Happy-path tests -----------------------------------------------------


def test_emits_log_lines_in_order(qapp: QApplication, tmp_path: Path) -> None:
    handle = _FakeHandle(lines=["one", "two", "three"], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert sigs.log_lines == ["one", "two", "three"]
    assert sigs.finished == [(True, "")]
    assert sigs.errors == []


def test_finished_reports_success_on_zero_exit(
    qapp: QApplication, tmp_path: Path
) -> None:
    handle = _FakeHandle(lines=[], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert sigs.finished[0][0] is True


def test_secure_rerip_param_forwarded_to_backend(
    qapp: QApplication, tmp_path: Path
) -> None:
    """RipParameters.secure_rerip_matches must reach RipBackend.rip()."""
    handle = _FakeHandle(lines=[], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path, secure_rerip_matches=2))

    worker.start_rip()

    assert backend.rip_calls[0]["secure_rerip_matches"] == 2


# --- Adaptive read-speed ladder -------------------------------------------


def test_fixed_speed_mode_is_single_pass_and_forwards_read_speed(
    qapp: QApplication, tmp_path: Path
) -> None:
    backend = _FakeBackend(handle=_FakeHandle(lines=[], exit_code=0))
    worker = RipWorker(
        backend, _params(tmp_path, read_speed_mode="fixed", read_speed=4)
    )

    worker.start_rip()

    assert len(backend.rip_calls) == 1  # no ladder in fixed mode
    assert backend.rip_calls[0]["read_speed"] == 4


def test_auto_ladder_clean_disc_is_a_single_pass(
    qapp: QApplication, tmp_path: Path
) -> None:
    # No read errors (the default parse of no-log → no errors) → one pass, at max.
    backend = _FakeBackend(handle=_FakeHandle(lines=[], exit_code=0))
    worker = RipWorker(backend, _params(tmp_path, read_speed_mode="auto_ladder"))

    worker.start_rip()

    assert len(backend.rip_calls) == 1
    assert backend.rip_calls[0]["read_speed"] == 0  # started at the drive's max
    assert worker.speed_attempts[0].clean is True


def test_auto_ladder_re_rips_slower_on_read_errors_then_stops_clean(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pass with unrecoverable read errors triggers a re-rip a rung slower;
    once a pass reads clean, the ladder stops."""
    import platterpus.workers.rip_worker as mod

    backend = _FakeBackend(handle=_FakeHandle(lines=["ripping"], exit_code=0))
    worker = RipWorker(backend, _params(tmp_path, read_speed_mode="auto_ladder"))
    # Errors on the first pass, clean on the second.
    verdicts = iter([True, False])
    monkeypatch.setattr(mod, "read_errors_present", lambda _log: next(verdicts, False))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert len(backend.rip_calls) == 2  # re-ripped once
    assert backend.rip_calls[0]["read_speed"] == 0  # max first
    assert backend.rip_calls[1]["read_speed"] == 8  # stepped down to 8×
    attempts = worker.speed_attempts
    assert [a.clean for a in attempts] == [False, True]
    assert sigs.finished == [(True, "")]


def test_auto_ladder_flags_unresolved_after_exhausting_the_ladder(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disc that never reads clean escalates down the whole ladder + -Z, then
    stops (bounded) and is left FLAGGED as unresolved — quality never went down."""
    import platterpus.workers.rip_worker as mod
    from platterpus.read_speed_ladder import MAX_ATTEMPTS, attempts_to_report

    backend = _FakeBackend(handle=_FakeHandle(lines=["ripping"], exit_code=0))
    worker = RipWorker(backend, _params(tmp_path, read_speed_mode="auto_ladder"))
    monkeypatch.setattr(mod, "read_errors_present", lambda _log: True)

    worker.start_rip()

    assert len(backend.rip_calls) <= MAX_ATTEMPTS  # bounded, never infinite
    assert worker.speed_attempts[-1].clean is False
    report = attempts_to_report(worker.speed_attempts)
    assert report["unresolved"] is True and report["escalated"] is True


def test_cyanrip_progress_lines_drive_bars_and_track(
    qapp: QApplication, tmp_path: Path
) -> None:
    """cyanrip's \\r-redrawn progress lines (arriving as separate lines via
    universal newlines) must move both bars, set the current track, and
    produce a live status — KDD-18 progress parsing."""
    handle = _FakeHandle(
        lines=[
            "Disc tracks:    16",
            "Ripping track 1, progress - 25.00%, ETA - 3m, errors - 0",
            "Ripping and encoding track 1, progress - 75.00%",
            "Track 1 ripped and encoded successfully!",
            "Ripping track 2, progress - 10.00%",
        ],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    # Track 1 at 25%: overall = 5 + (0 + .25)/16*90 ≈ 6.4; task = 25.
    overall_1, task_1 = sigs.progress[0]
    assert task_1 == 25.0
    assert 6.0 < overall_1 < 7.0
    # "and encoding" variant parses too.
    assert sigs.progress[1][1] == 75.0
    # Track-done pegs that track's slice (task 100).
    done_overall, done_task = sigs.progress[2]
    assert done_task == 100.0
    assert 10.0 < done_overall < 11.0  # 5 + 1/16*90 ≈ 10.6
    # Track follows along for the row highlight; once per track.
    assert sigs.current_tracks == [1, 2]
    # Status names the phase (read) — cyanrip's own per-op ETA is NOT echoed
    # (it resets every phase and is wildly wrong early). No ETA suffix here
    # because the test rip elapses <8s (the minimum before we project one).
    assert any(s.startswith("Reading track 1… 25%") for s in sigs.statuses)
    # The "and encoding" pass is labelled "Encoding" so its 0→100% restart reads
    # as expected, not a regression.
    assert any(s.startswith("Encoding track 1… 75%") for s in sigs.statuses)
    assert any(s.startswith("Track 1 done") for s in sigs.statuses)
    # cyanrip's raw "(ETA 3m)" is never surfaced verbatim.
    assert not any("(ETA" in s for s in sigs.statuses)


def test_album_eta_is_self_computed_from_elapsed(
    qapp: QApplication, tmp_path: Path
) -> None:
    """We compute our OWN album ETA from elapsed ÷ fraction — stable and
    self-correcting — instead of capturing cyanrip's per-op ETA (which once
    logged '822h' at 0.01%)."""
    worker = RipWorker(_FakeBackend(handle=_FakeHandle(lines=[])), _params(tmp_path))
    # Not started yet → no estimate.
    assert worker._album_eta_text(50.0) == ""
    # Pretend the rip started 100s ago and is 50% done → ~100s remain.
    worker._started_monotonic = time.monotonic() - 100.0
    text = worker._album_eta_text(50.0)
    assert "left" in text and ("1m" in text or "2m" in text)
    # Too early (disc-scan band ≤5%) → suppressed.
    assert worker._album_eta_text(3.0) == ""
    # cyanrip's obsolete first-ETA capture is gone.
    assert not hasattr(worker, "estimated_seconds")


def test_progress_redraws_are_rate_limited_in_the_log(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A flood of cyanrip progress redraws must NOT each hit the log pane — that
    flood (one expensive text-append per redraw) starved repaints and blacked out
    the window when overlapped (real-user report, 2026-06-27). Processed in a
    tight loop (well under the 0.1s window), only the first redraw is logged;
    the bar signal stays unthrottled so progress still moves smoothly."""
    handle = _FakeHandle(
        lines=[
            "Ripping track 1, progress - 10.00%",
            "Ripping track 1, progress - 11.00%",
            "Ripping track 1, progress - 12.00%",
            "Ripping track 1, progress - 13.00%",
        ],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    # Only the first redraw reaches the log pane (the rest are within 0.1s).
    assert len([line for line in sigs.log_lines if "progress" in line]) == 1
    # …but every redraw still moved the progress bar (cheap, unthrottled) —
    # all four task percentages, plus the final 100% emitted after the loop.
    assert [task for _, task in sigs.progress] == [10.0, 11.0, 12.0, 13.0, 100.0]


def test_non_progress_lines_are_never_throttled(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The rate limit applies ONLY to progress redraws — ordinary log lines
    (errors, phase markers) must always reach the pane, even back-to-back."""
    handle = _FakeHandle(lines=["one", "two", "three", "four"], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert sigs.log_lines == ["one", "two", "three", "four"]


def test_cyanrip_progress_without_disc_total_keeps_task_bar_moving(
    qapp: QApplication, tmp_path: Path
) -> None:
    """If the 'Disc tracks:' line was missed, the overall bar can't be
    computed — but the task bar must still track the percentage."""
    handle = _FakeHandle(
        lines=["Ripping track 3, progress - 50.00%"],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    overall, task = sigs.progress[0]
    assert task == 50.0
    assert overall == 5.0  # banded floor, no regression to 0


def test_metadata_param_forwarded_to_backend(
    qapp: QApplication, tmp_path: Path
) -> None:
    """RipParameters.metadata (the GUI's tag snapshot) must reach the
    backend so cyanrip can be fed -a/-t."""
    from platterpus.adapters.rip_backend import RipMetadata, TrackTag

    meta = RipMetadata(album_title="X", tracks=(TrackTag(1, "One", "A"),))
    handle = _FakeHandle(lines=[], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path, metadata=meta))

    worker.start_rip()

    assert backend.rip_calls[0]["metadata"] == meta


def test_finished_reports_failure_on_nonzero_exit(
    qapp: QApplication, tmp_path: Path
) -> None:
    handle = _FakeHandle(lines=[], exit_code=1)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert sigs.finished[0][0] is False


def test_needs_unknown_retry_set_on_no_metadata_abort(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A known rip that aborts for lack of online metadata flags a heal."""
    handle = _FakeHandle(
        lines=[
            "Reading TOC 100 %",
            "WARNING: network error: (NetworkError(),)",
            "CRITICAL: unable to retrieve disc metadata, --unknown argument not passed",
        ],
        exit_code=1,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path, unknown=False))
    worker.start_rip()
    assert worker.needs_unknown_retry is True


def test_no_unknown_retry_when_already_unknown(
    qapp: QApplication, tmp_path: Path
) -> None:
    """An already-unknown rip never asks to heal (nothing better to retry)."""
    handle = _FakeHandle(
        lines=["CRITICAL: unable to retrieve disc metadata, --unknown ..."],
        exit_code=1,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path, unknown=True))
    worker.start_rip()
    assert worker.needs_unknown_retry is False


def test_no_unknown_retry_on_clean_rip(qapp: QApplication, tmp_path: Path) -> None:
    handle = _FakeHandle(lines=["Reading TOC 100 %"], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    worker.start_rip()
    assert worker.needs_unknown_retry is False


def test_failure_hint_set_on_track_giveup(qapp: QApplication, tmp_path: Path) -> None:
    """An unreadable track yields an actionable hint, not a bare failure."""
    handle = _FakeHandle(
        lines=["CRITICAL:whipper.command.cd:giving up on track 3 after 5 times"],
        exit_code=1,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    worker.start_rip()
    assert "Track 3" in worker.failure_hint
    # Actionable, backend-neutral advice (no stale "Keep going" setting, which
    # was removed with whipper, and no false >587 cd-paranoia claim).
    assert "scratched or dirty" in worker.failure_hint


def test_no_failure_hint_on_clean_rip(qapp: QApplication, tmp_path: Path) -> None:
    handle = _FakeHandle(lines=["Reading TOC 100 %"], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    worker.start_rip()
    assert worker.failure_hint == ""


# --- Progress parsing -----------------------------------------------------


def test_progress_two_tier_overall_monotonic_and_task_resets(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Overall bar moves forward across the whole rip; the task bar
    tracks the current operation and resets per phase (T32 feedback:
    "bar goes by track; want an overall bar and a task bar")."""
    handle = _FakeHandle(
        lines=[
            "Reading TOC  50 %",  # scan → 0-5% band
            "Reading table  100 %",
            "Reading track 1 of 2 (1 of 9) ...  50 %",  # track → 5-95% band
            "Verifying track 1 of 2 (3 of 9) ... 100 %",
            "Reading track 2 of 2 (1 of 9) ...  50 %",
            "Getting length of audio track (2 of 2) ... 100 %",  # 95-100%
        ],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    overalls = [o for o, _ in sigs.progress]
    tasks = [t for _, t in sigs.progress]
    # Overall is monotonic non-decreasing and ends at 100 (success peg).
    assert overalls == sorted(overalls)
    assert overalls[-1] == 100.0
    # Disc scan occupied the low band before any track work.
    assert sigs.progress[0] == (2.5, 50.0)
    assert sigs.progress[1] == (5.0, 100.0)
    # The task bar reset back down when a new operation started.
    assert 50.0 in tasks and 100.0 in tasks


def test_emits_current_track_once_per_new_track(
    qapp: QApplication, tmp_path: Path
) -> None:
    """current_track fires once when whipper moves to a new track — not on
    every per-percent line for the same track — so the GUI can follow the
    rip by highlighting the active row."""
    handle = _FakeHandle(
        lines=[
            "Reading TOC  100 %",  # no track yet
            "Reading track 1 of 3 (1 of 9) ...  10 %",  # → track 1
            "Reading track 1 of 3 (1 of 9) ...  90 %",  # same track, no re-emit
            "Verifying track 1 of 3 (3 of 9) ... 100 %",  # still track 1
            "Reading track 2 of 3 (1 of 9) ...  50 %",  # → track 2
            "Reading track 3 of 3 (1 of 9) ...  50 %",  # → track 3
        ],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    # One emission per distinct track, in order; no duplicate for track 1.
    assert sigs.current_tracks == [1, 2, 3]


def test_progress_for_ignores_lines_without_usable_percent(
    qapp: QApplication, tmp_path: Path
) -> None:
    worker = RipWorker(_FakeBackend(handle=_FakeHandle([], 0)), _params(tmp_path))
    # Encode/tag sub-phases carry no meaningful percent → no progress emit
    # (the status label covers them; the task bar holds its last value).
    assert worker._progress_for("Encoding track to FLAC (5 of 9) ...   0 %") is None
    assert worker._progress_for("INFO:whipper.command.cd:CRCs match") is None
    assert worker._progress_for("") is None


# --- Status / phase descriptions ------------------------------------------


def test_describe_activity_recognizes_disc_scan() -> None:
    assert _describe_activity("Reading TOC  50 %") == "Reading disc TOC… 50%"
    assert _describe_activity("Reading table  12 %") == "Reading disc table… 12%"


def test_describe_activity_recognizes_track_phases() -> None:
    assert (
        _describe_activity("Reading track 3 of 16 (1 of 9) ...  42 %")
        == "Reading track 3 of 16… 42%"
    )
    assert (
        _describe_activity("Verifying track 3 of 16 (3 of 9) ... 100 %")
        == "Verifying track 3 of 16… 100%"
    )


def test_describe_activity_recognizes_named_subphases() -> None:
    assert (
        _describe_activity("Encoding track to FLAC (5 of 9) ...   0 %")
        == "Encoding to FLAC…"
    )
    assert (
        _describe_activity("Getting length of audio track (1 of 16) ... 100 %")
        == "Checking track 1 of 16…"
    )


def test_describe_activity_returns_none_for_unrelated_lines() -> None:
    assert _describe_activity("INFO:whipper.command.cd:CRCs match") is None
    assert _describe_activity("") is None


def test_status_signal_fires_for_disc_scan_phase(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The pre-track disc scan must drive the status so the GUI doesn't
    look frozen on "Starting rip…" (T32 feedback)."""
    statuses: list[str] = []
    handle = _FakeHandle(
        lines=[
            "Reading TOC  50 %",
            "Reading table  10 %",
            "Reading track 1 of 16 (1 of 9) ...  20 %",
        ],
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    worker.status.connect(statuses.append)

    worker.start_rip()

    assert "Reading disc TOC… 50%" in statuses
    assert "Reading disc table… 10%" in statuses
    assert "Reading track 1 of 16… 20%" in statuses


def test_status_signal_deduplicates_repeated_phase(
    qapp: QApplication, tmp_path: Path
) -> None:
    handle = _FakeHandle(
        lines=["Encoding track to FLAC (5 of 9) ...   0 %"] * 3,
        exit_code=0,
    )
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    statuses: list[str] = []
    worker.status.connect(statuses.append)

    worker.start_rip()

    assert statuses == ["Encoding to FLAC…"]


# --- Error paths ----------------------------------------------------------


def test_whipper_error_on_start_emits_error_and_finished_false(
    qapp: QApplication, tmp_path: Path
) -> None:
    backend = _FakeBackend()
    backend.raise_on_rip(RipError("device busy"))
    worker = RipWorker(backend, _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert sigs.errors == ["device busy"]
    assert sigs.finished == [(False, "")]


def test_unexpected_exception_on_start_emits_error(
    qapp: QApplication, tmp_path: Path
) -> None:
    backend = _FakeBackend()
    backend.raise_on_rip(RuntimeError("kaboom"))
    worker = RipWorker(backend, _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    assert len(sigs.errors) == 1
    assert "kaboom" in sigs.errors[0]
    assert sigs.finished == [(False, "")]


# --- Cancellation ---------------------------------------------------------


def test_cancel_before_start_stops_the_subprocess_once_it_exists(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A cancel that lands during rip() startup — before the handle is set —
    must still stop the subprocess. cancel() can only flip the flag then (it
    finds _handle is None); start_rip re-checks the flag after it has the
    handle and cancels it. Regression for the startup-window race where the
    flag was set but the subprocess kept running and wait() blocked on it."""
    handle = _FakeHandle(lines=["one", "two"], exit_code=-15)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path))

    # Cancel before start: the handle isn't set yet, so only the flag is set.
    worker.cancel()
    assert handle.cancel_calls == 0

    worker.start_rip()  # gets the handle, sees the flag, and stops the rip

    assert handle.cancel_calls == 1  # the subprocess was actually cancelled


def test_cancel_after_start_forwards_to_handle(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The normal path: with the handle set, cancel() forwards to it."""
    handle = _FakeHandle(lines=["one", "two"], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path))

    worker.start_rip()  # no cancel → completes; the startup re-check is a no-op
    assert handle.cancel_calls == 0

    worker.cancel()  # handle exists now → forwarded
    assert handle.cancel_calls == 1


def test_cancellation_makes_finished_report_false(
    qapp: QApplication, tmp_path: Path
) -> None:
    """When the cancel flag is set during iteration, success must be
    False even if the subprocess exits with 0."""
    handle = _FakeHandle(lines=["x"], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    # Pre-cancel so the loop's first iteration sees the flag.
    worker.cancel()
    worker.start_rip()

    assert sigs.finished[0][0] is False


# --- Log path discovery ---------------------------------------------------


def test_finished_includes_log_path_when_log_present(
    qapp: QApplication, tmp_path: Path
) -> None:
    rip_log = tmp_path / "Artist" / "Album" / "rip.log"
    rip_log.parent.mkdir(parents=True)
    rip_log.write_text("dummy log content")

    handle = _FakeHandle(lines=[], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    success, path = sigs.finished[0]
    assert success is True
    assert path == str(rip_log)


def test_finished_log_path_empty_when_no_log_file(
    qapp: QApplication, tmp_path: Path
) -> None:
    handle = _FakeHandle(lines=[], exit_code=0)
    worker = RipWorker(_FakeBackend(handle=handle), _params(tmp_path))
    sigs = _Signals()
    sigs.attach(worker)

    worker.start_rip()

    _, path = sigs.finished[0]
    assert path == ""
