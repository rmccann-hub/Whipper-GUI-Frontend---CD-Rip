"""RipWorker — drives a RipBackend rip off the GUI thread.

The main thread constructs a RipWorker, moves it to a QThread, and
connects QThread.started to RipWorker.start_rip. The worker streams the
backend's stdout (cyanrip — the sole backend, KDD-18) via Qt signals so
the GUI can update without blocking.

Signals:
  log_line(str)               — one line of rip output
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
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from platterpus.adapters.rip_backend import (
    RipBackend,
    RipError,
    RipHandle,
    RipMetadata,
)
from platterpus.read_speed_ladder import (
    MAX_ATTEMPTS,
    SpeedAttempt,
    next_step,
    read_errors_present,
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
    # EAC bit-perfect parity gap (KDD-13). cover_art "" = don't fetch art;
    # otherwise the front cover is embedded after the rip.
    cover_art: str = ""
    max_retries: int = 5
    # cyanrip's `-Z N` (rip until N reads' checksums match) for marginal
    # discs. 0 = off.
    secure_rerip_matches: int = 0
    # Adaptive read-speed ladder (0.4.6). `read_speed_mode` is "auto_ladder"
    # (start fast, re-rip slower on read errors) or "fixed"; `read_speed` is the
    # fixed/starting `-S` value (0 = drive max). Defaults are conservative here
    # ("fixed" / 0 == today's behaviour) so a worker constructed without them —
    # e.g. in a unit test — never enters the escalation loop; the GUI passes the
    # user's config values (auto_ladder by default) explicitly.
    read_speed_mode: str = "fixed"
    read_speed: int = 0
    # When set, applied as the read offset for the rip (cyanrip's `-s`).
    read_offset_override: int | None = None
    # The GUI's already-fetched album/track tags (track table content),
    # fed to cyanrip via -a/-t so the rip needs no in-container network.
    metadata: RipMetadata | None = None


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
_DISC_SCAN_PATTERN = re.compile(r"Reading (?P<what>TOC|table)\s+(?P<pct>\d+)\s*%")
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

# --- cyanrip progress lines (KDD-18) ---------------------------------------
# cyanrip redraws ONE progress line with `\r` (cyanrip_main.c):
#   "Ripping track 5, progress - 42.37%, ETA - 3m, errors - 0"
#   "Ripping and encoding track 5, progress - 42.37%"
# Popen(text=True) reads in universal-newlines mode, which translates every
# bare `\r` to `\n` — so each redraw reaches log_lines() as its own line and
# these regexes see them one at a time, no extra plumbing.
_CYANRIP_TRACK_PROGRESS = re.compile(
    r"Ripping(?P<encoding> and encoding)? track (?P<track>\d+), progress - "
    r"(?P<pct>\d+(?:\.\d+)?)%(?:, ETA - (?P<eta>[^,]+))?"
)
# Per-track completion ("Track 5 ripped and encoded successfully!" / "with
# errors.") — pegs that track's slice of the overall bar.
_CYANRIP_TRACK_DONE = re.compile(
    r"^Track (?P<track>\d+) ripped and encoded (?P<how>successfully|with errors)"
)
# The start report carries the track total ("Disc tracks:    16") — cyanrip's
# progress lines don't repeat it, so we capture it here for the overall bar.
_CYANRIP_DISC_TRACKS = re.compile(r"^Disc tracks:\s+(?P<total>\d+)\s*$")

# A ripper can abort when it can't fetch online metadata (e.g. the container
# has no network) and wasn't told the disc is "unknown". We detect that so the
# GUI can auto-retry as an unknown-album rip — which needs no network — and tag
# locally afterward from the metadata it already has. These are whipper's abort
# strings; cyanrip is always run with `-N` and fed the GUI's tags (Critical
# Rule #5), so it never does an online lookup and never hits this — the heal
# path is currently inert, kept as the seam for any future networked backend.
_NO_METADATA_MARKERS: tuple[str, ...] = (
    "--unknown argument not passed",
    "unable to retrieve disc metadata",
)

# A ripper can exhaust its retries on a track it can't read consistently (a
# scratched/dirty disc). We turn that into an actionable message instead of a
# bare "Rip failed". This matches whipper's "giving up on track N" wording;
# cyanrip instead rips the track "with errors" and keeps going, so it doesn't
# trip this — the hint stays for the whipper-format seam and is harmless inert.
_TRACK_GIVEUP_RE = re.compile(r"giving up on track (?P<track>\d+)")

# Minimum wall-clock gap between forwarding consecutive *progress redraw* lines
# to the GUI. cyanrip redraws its progress many times a second (each `\r` becomes
# its own line — see above), and forwarding every one floods the GUI's event loop
# with queued signals: the window can't service paint events and goes black when
# another window is dragged over it (real-user report, 2026-06-27). Coalescing to
# ~10 updates/second keeps the bar and ETA feeling live while leaving the event
# loop plenty of room to repaint. Only progress lines are throttled — phase
# changes, errors, and end-of-rip markers always go through immediately.
_PROGRESS_MIN_INTERVAL_S: float = 0.1

# Don't show an album ETA until at least this much wall-clock has elapsed —
# before that, elapsed÷fraction projects wild/"0s" values off almost no data.
_MIN_ELAPSED_FOR_ETA_S: float = 8.0


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
    progress = Signal(float, float)  # overall_percent, task_percent
    status = Signal(str)  # human-readable current phase
    # Emitted with the 1-based track number whenever whipper starts working
    # on a new track, so the GUI can follow along by highlighting that row.
    current_track = Signal(int)
    finished = Signal(bool, str)  # success, log_path
    error = Signal(str)

    def __init__(
        self,
        backend: RipBackend,
        params: RipParameters,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend: RipBackend = backend
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
        # Monotonic timestamp of the last progress redraw we forwarded to the
        # GUI, for rate-limiting the flood (see _PROGRESS_MIN_INTERVAL_S). 0.0
        # means "none yet" → the first progress line always goes through.
        self._last_progress_emit: float = 0.0
        # Flag is a plain Python bool — assignment is atomic under the
        # GIL, so reading it from the worker thread while the GUI thread
        # sets it is safe without locks.
        self._cancelled: bool = False
        # Set true if whipper aborts for lack of online metadata, so the GUI
        # can heal by retrying as an unknown-album rip. Only meaningful when
        # this rip wasn't already unknown.
        self._needs_unknown_retry: bool = False
        # A user-facing explanation set when a known fatal pattern is seen
        # (e.g. whipper giving up on an unreadable track). "" if none.
        self._failure_hint: str = ""
        # Wall-clock start of the rip, stamped when the stream loop begins. Used
        # to compute our OWN album-level ETA (elapsed × (1-frac)/frac) — stable
        # and self-correcting, unlike cyanrip's per-operation ETA which resets
        # every phase and is wildly wrong early (it printed "822h" at 0.01% on a
        # real disc). None until the loop starts.
        self._started_monotonic: float | None = None
        # The adaptive read-speed ladder's history: one SpeedAttempt per rip pass
        # (speed + -Z + whether it read clean). The GUI reads this at finish and
        # folds it into the report, so a disc that needed a slow re-read — or that
        # never read clean even at the floor — is recorded honestly, not hidden.
        self._speed_attempts: list[SpeedAttempt] = []

    def _album_eta_text(self, overall_pct: float) -> str:
        """A smoothed, self-correcting album ETA suffix (" · about 25m left").

        Computed from actual elapsed and the album fraction done — so it absorbs
        secure re-read slowdowns instead of jumping like cyanrip's per-operation
        ETA. Returns "" until we're actually ripping tracks (past the ≤5% disc
        scan), until a few seconds have elapsed (before which any projection is
        noise — no "about 0s left"), and once effectively done. Never raises.
        """
        from platterpus.rip_timing import format_duration

        started = self._started_monotonic
        if started is None:
            return ""
        frac = overall_pct / 100.0
        # Skip the disc-scan band (0-5%) and the very end; both give noise.
        if frac <= 0.05 or frac >= 0.999:
            return ""
        elapsed = time.monotonic() - started
        if elapsed < _MIN_ELAPSED_FOR_ETA_S:
            return ""
        remaining = elapsed * (1.0 - frac) / frac
        if not remaining >= 1:  # guards NaN/inf and sub-second "0s left"
            return ""
        return f" · about {format_duration(round(remaining))} left"

    @property
    def needs_unknown_retry(self) -> bool:
        """True if the rip failed because whipper couldn't fetch online
        metadata (and this wasn't already an unknown-album rip)."""
        return self._needs_unknown_retry

    @property
    def failure_hint(self) -> str:
        """An actionable failure explanation, or "" if the failure was generic.
        Set when whipper gives up on an unreadable track."""
        return self._failure_hint

    @property
    def speed_attempts(self) -> list[SpeedAttempt]:
        """The adaptive read-speed ladder's per-pass history (empty on a normal
        single-pass rip). The GUI reads this at finish for the report."""
        return list(self._speed_attempts)

    # --- Slots ---

    @Slot()
    def start_rip(self) -> None:
        """Begin the rip. Invoked via QThread.started.

        Runs the adaptive read-speed ladder: rip once, and — in ``auto_ladder``
        mode — if the pass completed with unrecoverable read errors, re-rip the
        disc a rung slower (and, at the floor, with a higher ``-Z``), until it
        reads clean or the ladder is exhausted (then the disc is FLAGGED via the
        recorded attempts). A clean disc, or ``fixed`` mode, is a single pass
        exactly as before — no regression. Each pass's speed/``-Z``/outcome is
        recorded in ``_speed_attempts`` for honest reporting.
        """
        # Stamp the wall-clock start once (album-ETA baseline spans all passes).
        self._started_monotonic = time.monotonic()

        auto_ladder = self._params.read_speed_mode == "auto_ladder"
        # Starting rung: the ladder starts at the drive's max (0); a fixed mode
        # uses the configured speed for its single pass.
        speed = 0 if auto_ladder else self._params.read_speed
        secure_rerip = self._params.secure_rerip_matches

        success = False
        log_path_str = ""
        attempt = 0
        while True:
            attempt += 1
            self._reset_pass_progress()
            outcome = self._rip_once(
                read_speed=speed, secure_rerip_matches=secure_rerip
            )
            if outcome is None:
                # A hard start/stream error already emitted `error`; stop here.
                self.finished.emit(False, "")
                return
            success, log_path_str = outcome
            if self._cancelled:
                break
            # Did this pass read clean? (No unrecoverable errors in its log.)
            errors = success and read_errors_present(self._parse_log(log_path_str))
            self._speed_attempts.append(
                SpeedAttempt(attempt, speed, secure_rerip, clean=not errors)
            )
            # Escalate only in auto_ladder mode, only on a completed-with-errors
            # pass, and only while the ladder + hard cap allow.
            if not (auto_ladder and errors) or attempt >= MAX_ATTEMPTS:
                break
            step = next_step(current_speed=speed, current_secure_rerip=secure_rerip)
            if step is None:
                # Floor + -Z exhausted — stop and leave the disc FLAGGED
                # (unresolved in the report). Quality never went DOWN.
                log.warning("read-speed ladder exhausted; disc still has read errors")
                break
            speed, secure_rerip = step.speed, step.secure_rerip_matches
            self.status.emit(f"Read errors — {step.reason}…")
            self.log_line.emit(f"[read-speed ladder] {step.reason}")

        if success:
            # Peg both bars at 100% so a finished rip never leaves the
            # overall bar short of full (the post-rip AccurateRip phase
            # has no reliable percentage of its own).
            self.progress.emit(100.0, 100.0)
        self.finished.emit(success, log_path_str)

    def _rip_once(
        self, *, read_speed: int, secure_rerip_matches: int
    ) -> tuple[bool, str] | None:
        """Run ONE rip pass at the given speed/``-Z``; stream its output.

        Returns ``(success, log_path_str)`` for a completed pass, or None on a
        hard start/stream error (having already emitted ``error``) so the caller
        stops the whole rip. Emits log/progress/status/current_track exactly as
        the single-pass rip always did.
        """
        try:
            self._handle = self._backend.rip(
                drive=self._params.drive,
                release_id=self._params.release_id,
                output_dir=self._params.output_dir,
                track_template=self._params.track_template,
                disc_template=self._params.disc_template,
                unknown=self._params.unknown,
                cover_art=self._params.cover_art,
                max_retries=self._params.max_retries,
                secure_rerip_matches=secure_rerip_matches,
                read_offset_override=self._params.read_offset_override,
                metadata=self._params.metadata,
                read_speed=read_speed,
            )
        except RipError as exc:
            log.exception("rip failed to start")
            self.error.emit(str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            log.exception("unexpected error starting rip")
            self.error.emit(f"unexpected error: {exc}")
            return None

        # Close the startup-window cancel race: if cancel() arrived while
        # backend.rip() was still spawning the subprocess — before _handle was
        # assigned — it could only flip the flag (it found _handle is None).
        # Now that we hold the handle, honour the pending cancel by stopping the
        # subprocess; otherwise the loop below would break on the flag but
        # self._handle.wait() would block on a still-running rip ("Cancel did
        # nothing" until the 5s force-stop backstop fired).
        if self._cancelled:
            try:
                self._handle.cancel()
            except Exception:  # noqa: BLE001 — cancel is best-effort
                log.exception("startup-window cancel() raised; ignored")

        # Stream output. Iteration ends when whipper closes its stdout
        # (i.e. exits) or when cancel() flips the flag.
        try:
            for line in self._handle.log_lines():
                if self._cancelled:
                    break
                # `_progress_for` both classifies the line (a numeric progress
                # redraw → not None) AND updates `_current_track` as a side
                # effect, so call it once up front.
                prog = self._progress_for(line)
                is_progress = prog is not None
                # Forward the line to the GUI's log pane — but RATE-LIMIT the
                # high-frequency progress redraws. Appending to the log widget
                # (text layout + repaint) is the expensive per-tick work; at
                # cyanrip's redraw rate it floods the event loop and starves
                # repaints, so the window goes black when overlapped (real-user
                # report, 2026-06-27). The bar/status/track signals below are
                # cheap and stay unthrottled, so the progress bar still moves
                # smoothly even when the log pane updates only ~10×/second.
                now = time.monotonic()
                if is_progress:
                    if now - self._last_progress_emit >= _PROGRESS_MIN_INTERVAL_S:
                        self._last_progress_emit = now
                        self.log_line.emit(line)
                else:
                    self.log_line.emit(line)
                # Watch for whipper's "no online metadata" abort so the GUI
                # can heal by re-ripping as unknown (only worth it if this
                # rip wasn't already unknown). Detection runs on EVERY line.
                if not self._params.unknown and any(
                    m in line for m in _NO_METADATA_MARKERS
                ):
                    self._needs_unknown_retry = True
                giveup = _TRACK_GIVEUP_RE.search(line)
                if giveup:
                    track = giveup.group("track")
                    self._failure_hint = (
                        f"Track {track} couldn't be read after repeated tries. "
                        "The disc may be scratched or dirty — clean it and try "
                        "again."
                    )
                # Status text first (covers the pre-track disc scan and
                # the encode/tag sub-phases), then the numeric progress
                # that drives the bar.
                desc = _describe_activity(line)
                # Append our own smoothed album ETA to a progress phase (never
                # cyanrip's per-op ETA — see _album_eta_text / _describe_activity).
                if desc is not None and prog is not None:
                    desc += self._album_eta_text(prog[0])
                if desc is not None and desc != self._last_status:
                    self._last_status = desc
                    self.status.emit(desc)
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
            return None

        exit_code = self._handle.wait()
        success = (exit_code == 0) and not self._cancelled
        log_path = self._find_log_path()
        return success, str(log_path) if log_path else ""

    def _reset_pass_progress(self) -> None:
        """Reset the per-pass progress state before a (re-)rip pass, so a re-rip's
        bar sweeps fresh from 0 instead of inheriting the previous pass's value."""
        self._overall = 0.0
        self._current_track = 0
        self._emitted_track = 0
        self._last_status = ""
        self._last_progress_emit = 0.0

    def _parse_log(self, log_path_str: str) -> object | None:
        """Parse a rip log for the escalation decision. Never raises (parsers
        don't, and a missing/unreadable file just yields None → 'no errors')."""
        if not log_path_str:
            return None
        from platterpus.parsers.cyanrip_log import (
            looks_like_cyanrip_log,
            parse_cyanrip_log,
        )
        from platterpus.parsers.rip_log import parse_rip_log

        try:
            text = Path(log_path_str).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return (
            parse_cyanrip_log(text)
            if looks_like_cyanrip_log(text)
            else parse_rip_log(text)
        )

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

        # --- cyanrip lines (mutually exclusive with whipper's formats) ---

        match = _CYANRIP_DISC_TRACKS.search(line)
        if match:
            # Total learned from the start report; no bar movement yet.
            self._total_tracks = int(match.group("total"))
            return None

        match = _CYANRIP_TRACK_PROGRESS.search(line)
        if match:
            self._current_track = int(match.group("track"))
            task = float(match.group("pct"))
            frac = (
                ((self._current_track - 1) + task / 100.0) / self._total_tracks
                if self._total_tracks
                else 0.0
            )
            return self._bump_overall(5.0 + frac * 90.0), task

        match = _CYANRIP_TRACK_DONE.search(line)
        if match:
            done = int(match.group("track"))
            frac = done / self._total_tracks if self._total_tracks else 0.0
            return self._bump_overall(5.0 + frac * 90.0), 100.0

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
        return f"Checking track {match.group('track')} of {match.group('total')}…"

    match = _CYANRIP_TRACK_PROGRESS.search(line)
    if match:
        pct = float(match.group("pct"))
        # Name the phase so the per-track bar visibly restarting for the encode
        # pass reads as expected, not a regression. cyanrip's own per-op ETA is
        # deliberately dropped here — it resets every phase and is wildly wrong
        # early (it once printed "822h"); the run loop appends our own smoothed
        # album ETA instead.
        phase = "Encoding" if match.group("encoding") else "Reading"
        return f"{phase} track {match.group('track')}… {pct:.0f}%"

    match = _CYANRIP_TRACK_DONE.search(line)
    if match:
        outcome = "✓" if match.group("how") == "successfully" else "with errors"
        return f"Track {match.group('track')} done {outcome}"

    for phrase, friendly in _NAMED_PHASES.items():
        if phrase in line:
            return friendly
    return None
