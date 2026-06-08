"""Tests for whipper_gui.workers.rip_worker.

We drive the worker synchronously (no QThread, no event loop) — Qt
signals are callable regardless of whether an event loop is running.
Connected slots receive emissions immediately because we use direct
connections by default. This keeps the tests fast and deterministic.

The WhipperBackend is replaced with a fake so we don't need a real
whipper binary.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.whipper_backend import (
    RipHandle,
    WhipperBackend,
    WhipperError,
)
from whipper_gui.workers.rip_worker import (
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


class _FakeBackend(WhipperBackend):
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
        cdr: bool = False,
        cover_art: str = "",
        force_overread: bool = False,
        max_retries: int = 5,
        keep_going: bool = False,
        read_offset_override: int | None = None,
    ) -> RipHandle:
        self.rip_calls.append(
            {
                "drive": drive,
                "release_id": release_id,
                "output_dir": output_dir,
                "unknown": unknown,
                "cdr": cdr,
                "cover_art": cover_art,
                "force_overread": force_overread,
                "max_retries": max_retries,
                "keep_going": keep_going,
                "read_offset_override": read_offset_override,
            }
        )
        if self._raise_on_rip:
            raise self._raise_on_rip
        assert self._handle is not None
        return self._handle  # type: ignore[return-value]

    def version(self) -> str:
        return "fake 0.0.0"


def _params(tmp_path: Path, unknown: bool = False, cdr: bool = False) -> RipParameters:
    return RipParameters(
        drive="/dev/sr0",
        release_id="mbid-abc",
        output_dir=tmp_path,
        track_template="t",
        disc_template="d",
        unknown=unknown,
        cdr=cdr,
    )


# --- Signal-collector helper ----------------------------------------------


class _Signals:
    """Accumulates signal emissions for assertion."""

    def __init__(self) -> None:
        self.log_lines: list[str] = []
        self.progress: list[tuple[float, float]] = []  # (overall, task)
        self.current_tracks: list[int] = []
        self.errors: list[str] = []
        self.finished: list[tuple[bool, str]] = []

    def attach(self, worker: RipWorker) -> None:
        worker.log_line.connect(self.log_lines.append)
        worker.progress.connect(
            lambda overall, task: self.progress.append((overall, task))
        )
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


def test_cdr_param_forwarded_to_backend(qapp: QApplication, tmp_path: Path) -> None:
    """RipParameters.cdr must reach WhipperBackend.rip()."""
    handle = _FakeHandle(lines=[], exit_code=0)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path, cdr=True))

    worker.start_rip()

    assert backend.rip_calls[0]["cdr"] is True


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
    assert "Keep going" in worker.failure_hint


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
    backend.raise_on_rip(WhipperError("device busy"))
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


def test_cancel_sets_flag_and_calls_handle_cancel(
    qapp: QApplication, tmp_path: Path
) -> None:
    handle = _FakeHandle(lines=["one", "two"], exit_code=-15)
    backend = _FakeBackend(handle=handle)
    worker = RipWorker(backend, _params(tmp_path))

    # Cancel must be safe before start.
    worker.cancel()
    # cancel() before start() — handle isn't yet set, so handle.cancel
    # is NOT called. The flag is set, though.
    assert handle.cancel_calls == 0

    worker.start_rip()  # but iteration sees the flag set, exits early

    # After start_rip, the handle exists; calling cancel again should
    # forward to it.
    worker.cancel()
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
