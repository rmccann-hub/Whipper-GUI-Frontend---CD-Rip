"""RipWorker — drives a WhipperBackend rip off the GUI thread.

The main thread constructs a RipWorker, moves it to a QThread, and
connects QThread.started to RipWorker.start_rip. The worker streams
whipper's stdout via Qt signals so the GUI can update without blocking.

Signals:
  log_line(str)               — one line of whipper output
  progress(int, float)        — (track_number, percent_complete) when
                                parseable from the output stream
  finished(bool, str)         — (success, log_file_path); log path is
                                "" when no .log file was located
  error(str)                  — short human-readable error message

Cancel:
  Call cancel() from the GUI thread. It sets a flag and forwards to
  RipHandle.cancel(), which SIGTERMs (then SIGKILLs) the subprocess.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from whipper_gui.adapters.whipper_backend import (
    RipHandle,
    WhipperBackend,
    WhipperError,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RipParameters:
    """Everything the worker needs to start a rip.

    Keep this typed and frozen so the caller's intent is locked in
    before crossing thread boundaries — a `dict[str, Any]` would let
    typos slip through silently.
    """

    drive: str
    release_id: str
    output_dir: Path
    track_template: str
    disc_template: str
    unknown: bool = False
    cdr: bool = False
    # EAC bit-perfect parity gaps (KDD-13). cover_art "" = don't pass the
    # flag; otherwise one of whipper's {file, embed, complete}.
    cover_art: str = ""
    force_overread: bool = False
    max_retries: int = 5
    keep_going: bool = False
    # When set, passed as whipper's `--offset N`, overriding whipper.conf.
    read_offset_override: int | None = None


# Human-readable phase descriptions for the status line. Without these
# the GUI sat on "Starting rip…" for the whole pre-track disc scan
# (which can run a minute or more) and looked frozen — T32 feedback.
# Whipper's progress lines look like:
#   "Reading TOC  50 %"
#   "Reading table  50 %"
#   "Reading track 3 of 16 (1 of 9) ...  42 %"
#   "Verifying track 3 of 16 (3 of 9) ... 42 %"
#   "Encoding track to FLAC (5 of 9) ...   0 %"
#   "Getting length of audio track (1 of 16) ... 100 %"
_DISC_SCAN_PATTERN = re.compile(
    r"Reading (?P<what>TOC|table)\s+(?P<pct>\d+)\s*%"
)
_TRACK_PHASE_PATTERN = re.compile(
    r"(?P<verb>Reading|Verifying) track (?P<track>\d+) of (?P<total>\d+)"
    r".*?(?P<pct>\d+)\s*%"
)
_LENGTH_PHASE_PATTERN = re.compile(
    r"Getting length of audio track \((?P<track>\d+) of (?P<total>\d+)\)"
)
# Per-track sub-phases that carry no track number on their own line.
_NAMED_PHASES: dict[str, str] = {
    "Encoding track to FLAC": "Encoding to FLAC…",
    "Calculating peak level": "Calculating peak level…",
    "Writing tags to FLAC": "Writing tags…",
    "Embed picture to FLAC": "Finalizing track…",
}


class RipWorker(QObject):
    """QObject worker that owns a rip subprocess for its lifetime.

    Construct on the GUI thread, then move to a QThread:

        worker = RipWorker(backend, params)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.start_rip)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
    """

    log_line = Signal(str)
    # Two-tier progress so the GUI can show an overall bar (whole rip) and
    # a task bar (current operation). Overall is monotonic; task resets per
    # operation (read → verify → encode each sweep 0-100%).
    progress = Signal(float, float)        # overall_percent, task_percent
    status = Signal(str)                   # human-readable current phase
    # Emitted with the 1-based track number whenever whipper starts working
    # on a new track, so the GUI can follow along by highlighting that row.
    current_track = Signal(int)
    finished = Signal(bool, str)           # success, log_path
    error = Signal(str)

    def __init__(
        self,
        backend: WhipperBackend,
        params: RipParameters,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend: WhipperBackend = backend
        self._params: RipParameters = params
        self._handle: RipHandle | None = None
        # Last status text emitted, so we don't re-emit identical phases
        # on every progress tick (whipper prints one line per percent).
        self._last_status: str = ""
        # Progress state. `_overall` only ever moves forward (see
        # _bump_overall); `_total_tracks`/`_current_track` are learned from
        # whipper's "track N of M" lines.
        self._overall: float = 0.0
        self._total_tracks: int = 0
        self._current_track: int = 0
        # Last track number we emitted `current_track` for, so we signal
        # once per track instead of on every per-percent progress line.
        self._emitted_track: int = 0
        # Flag is a plain Python bool — assignment is atomic under the
        # GIL, so reading it from the worker thread while the GUI thread
        # sets it is safe without locks.
        self._cancelled: bool = False

    # --- Slots ---

    @Slot()
    def start_rip(self) -> None:
        """Begin the rip. Invoked via QThread.started."""
        try:
            self._handle = self._backend.rip(
                drive=self._params.drive,
                release_id=self._params.release_id,
                output_dir=self._params.output_dir,
                track_template=self._params.track_template,
                disc_template=self._params.disc_template,
                unknown=self._params.unknown,
                cdr=self._params.cdr,
                cover_art=self._params.cover_art,
                force_overread=self._params.force_overread,
                max_retries=self._params.max_retries,
                keep_going=self._params.keep_going,
                read_offset_override=self._params.read_offset_override,
            )
        except WhipperError as exc:
            log.exception("rip failed to start")
            self.error.emit(str(exc))
            self.finished.emit(False, "")
            return
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            log.exception("unexpected error starting rip")
            self.error.emit(f"unexpected error: {exc}")
            self.finished.emit(False, "")
            return

        # Stream output. Iteration ends when whipper closes its stdout
        # (i.e. exits) or when cancel() flips the flag.
        try:
            for line in self._handle.log_lines():
                if self._cancelled:
                    break
                self.log_line.emit(line)
                # Status text first (covers the pre-track disc scan and
                # the encode/tag sub-phases), then the numeric progress
                # that drives the bar.
                desc = _describe_activity(line)
                if desc is not None and desc != self._last_status:
                    self._last_status = desc
                    self.status.emit(desc)
                prog = self._progress_for(line)
                if prog is not None:
                    self.progress.emit(prog[0], prog[1])
                # _progress_for updates _current_track as a side effect when
                # it sees a "track N of M" line. Emit once per new track so
                # the GUI can highlight the row whipper is on.
                if self._current_track and self._current_track != self._emitted_track:
                    self._emitted_track = self._current_track
                    self.current_track.emit(self._current_track)
        except Exception as exc:  # noqa: BLE001
            log.exception("error reading whipper stdout")
            self.error.emit(f"rip stream error: {exc}")
            self.finished.emit(False, "")
            return

        exit_code = self._handle.wait()
        success = (exit_code == 0) and not self._cancelled
        if success:
            # Peg both bars at 100% so a finished rip never leaves the
            # overall bar short of full (the post-rip AccurateRip phase
            # has no reliable percentage of its own).
            self.progress.emit(100.0, 100.0)
        log_path = self._find_log_path()
        self.finished.emit(success, str(log_path) if log_path else "")

    @Slot()
    def cancel(self) -> None:
        """Cancel an in-progress rip.

        Thread-safe: sets a flag (read by the worker's iteration loop),
        then forwards to the handle's cancel() which is itself thread-safe
        because subprocess methods are.
        """
        self._cancelled = True
        if self._handle is not None:
            try:
                self._handle.cancel()
            except Exception:  # noqa: BLE001
                log.exception("cancel() raised; ignored")

    # --- Internals ---

    def _progress_for(self, line: str) -> tuple[float, float] | None:
        """Map a whipper stdout line to (overall, task) percentages.

        The rip is split into three overall bands so the overall bar
        advances smoothly start-to-finish instead of resetting per track:
          * disc scan (Reading TOC/table)        → 0–5%
          * per-track read/verify (N of M)       → 5–95%
          * post-rip length/AccurateRip checks   → 95–100%
        The task percentage is the current operation's own 0–100%.
        Returns None for lines with no usable percentage (e.g. the
        encode/tag sub-phases) — the status label covers those, and the
        task bar simply holds its last value.
        """
        match = _DISC_SCAN_PATTERN.search(line)
        if match:
            task = float(match.group("pct"))
            return self._bump_overall(task * 0.05), task

        match = _TRACK_PHASE_PATTERN.search(line)
        if match:
            self._current_track = int(match.group("track"))
            self._total_tracks = int(match.group("total"))
            task = float(match.group("pct"))
            frac = (
                ((self._current_track - 1) + task / 100.0) / self._total_tracks
                if self._total_tracks
                else 0.0
            )
            return self._bump_overall(5.0 + frac * 90.0), task

        match = _LENGTH_PHASE_PATTERN.search(line)
        if match:
            done = int(match.group("track"))
            total = int(match.group("total"))
            frac = done / total if total else 1.0
            return self._bump_overall(95.0 + frac * 5.0), 100.0

        return None

    def _bump_overall(self, value: float) -> float:
        """Clamp `value` to [0, 100] and never let the overall bar regress."""
        self._overall = max(self._overall, min(value, 100.0))
        return self._overall

    def _find_log_path(self) -> Path | None:
        """Locate the .log whipper just wrote.

        Whipper drops the rip log next to the FLACs. The output_dir from
        params is the root; we search recursively for the most recent
        .log file. Returns None if nothing was written (e.g. rip failed
        before any output).
        """
        output_dir = self._params.output_dir
        if not output_dir.exists():
            return None

        candidates = list(output_dir.rglob("*.log"))
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]


def _describe_activity(line: str) -> str | None:
    """Return a short human status for a whipper progress line, or None.

    Used to keep the status label live across every phase — especially
    the pre-track disc scan, which otherwise left the GUI on
    "Starting rip…" for a minute-plus and looked hung.
    """
    match = _DISC_SCAN_PATTERN.search(line)
    if match:
        what = "disc TOC" if match.group("what") == "TOC" else "disc table"
        return f"Reading {what}… {match.group('pct')}%"

    match = _TRACK_PHASE_PATTERN.search(line)
    if match:
        return (
            f"{match.group('verb')} track {match.group('track')} "
            f"of {match.group('total')}… {match.group('pct')}%"
        )

    match = _LENGTH_PHASE_PATTERN.search(line)
    if match:
        return (
            f"Checking track {match.group('track')} "
            f"of {match.group('total')}…"
        )

    for phrase, friendly in _NAMED_PHASES.items():
        if phrase in line:
            return friendly
    return None
