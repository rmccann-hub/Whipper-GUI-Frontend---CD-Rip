"""Adapter over the host-exported `whipper` CLI.

`WhipperBackend` is an abstract base class with the four operations the
GUI needs. `WhipperHostExportedImpl` is the v1 concrete implementation
that shells out to `~/.local/bin/whipper`. A future `CyanripImpl` could
implement the same ABC and be selected via config — see PLANNING.md §5.

The adapter is deliberately thin: it builds argv, runs subprocess, and
hands stdout to the parsers in `whipper_gui.parsers`. It does NOT parse
output inline.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from whipper_gui.parsers.cd_info import DiscInfo, parse_cd_info
from whipper_gui.parsers.drive_list import DriveDescriptor, parse_drive_list
from whipper_gui.paths import WHIPPER_CONFIG_PATH

log = logging.getLogger(__name__)

# Generous timeout for one-shot info commands. `whipper drive list` and
# `whipper cd info` return within seconds on a healthy system; the cap
# guards against a hung subprocess.
_INFO_TIMEOUT_S: float = 30.0

# Drive-calibration commands take much longer: `drive analyze` spins the
# disc, and `offset find` tries many candidate offsets against AccurateRip.
_SETUP_TIMEOUT_S: float = 300.0

# whipper's success/diagnostic lines, matched defensively (named-group
# regex per CLAUDE.md, not column splits). Sources:
#   offset find → "Read offset of device is: %d."  (whipper/command/offset.py)
#   drive analyze → "cdparanoia (can|cannot) defeat the audio cache …"
#                   "cannot analyze the drive: is there a CD in it?"
_OFFSET_RE: re.Pattern[str] = re.compile(
    r"[Rr]ead offset of device is:\s*(?P<offset>-?\d+)"
)
_CACHE_CAN: str = "can defeat the audio cache"
_CACHE_CANNOT: str = "cannot defeat the audio cache"
_NO_DISC_MARKER: str = "is there a CD in it"


def _last_line(text: str, rc: int) -> str:
    """The last non-empty line of `text`, or an rc= fallback for the GUI."""
    lines = text.strip().splitlines()
    return lines[-1] if lines else f"rc={rc}"


def _kill_group(proc: subprocess.Popen[str], sig: int) -> None:
    """Send `sig` to the subprocess's whole process group.

    whipper spawns children (the `~/.local/bin/whipper` wrapper →
    distrobox/podman → whipper → cdparanoia, the actual disc reader).
    Signalling only the parent leaves cdparanoia reading the disc, so the
    drive keeps spinning. Because we launch these processes with
    `start_new_session=True`, the parent is a group leader and one
    killpg() reaches the whole tree. Falls back to the single process if
    the group can't be addressed.

    NOTE: the in-*container* whipper/cdparanoia (under podman) is a
    separate process tree; podman doesn't always forward the signal
    instantly, so the drive can take a moment to spin down even after
    this. It does stop — just not always immediately.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


def back_up_whipper_config(conf_path: Path = WHIPPER_CONFIG_PATH) -> Path | None:
    """Copy `whipper.conf` to `whipper.conf.bak` before the drive-setup
    wizard lets whipper rewrite it, so the user can always revert.

    Returns the backup path, or None if there was no existing config to
    back up (a fresh system — whipper will create it on first write).
    """
    if not conf_path.exists():
        return None
    backup = conf_path.with_name(conf_path.name + ".bak")
    shutil.copy2(conf_path, backup)
    log.info("backed up %s -> %s", conf_path, backup)
    return backup


class WhipperError(Exception):
    """Raised when a whipper subprocess fails in an actionable way.

    The message holds the last stderr line whipper emitted (or its
    stdout fallback) so the GUI can surface something meaningful to
    the user. The full output is available on `.output` for logging.
    """

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output: str = output


def run_capture(
    tool_name: str,
    binary: str,
    args: list[str],
    *,
    timeout: float,
    stdin_devnull: bool = False,
) -> tuple[int, str]:
    """Run a one-shot ripper subprocess; return (returncode, combined output).

    The shared core of both backends' info/version probes (whipper's
    ``_run_capture`` and cyanrip's ``_run``). It deliberately does NOT raise on
    a non-zero exit — some callers (drive analyze, offset find) classify the
    output themselves — but it DOES translate the two unrecoverable failures
    into a :class:`WhipperError` the GUI can surface: a missing binary and a
    timeout.

    The pieces that genuinely differ between backends are parameters, not
    forks: ``timeout`` (whipper's info probes and cyanrip's differ on purpose),
    ``tool_name`` (shapes the log line and the error messages), and
    ``stdin_devnull`` (cyanrip reads stdin and must have it closed; whipper
    inherits, matching ``subprocess.run``'s default of ``stdin=None``).
    """
    argv: list[str] = [binary, *args]
    log.debug("%s: %s", tool_name, " ".join(argv))
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL if stdin_devnull else None,
        )
    except FileNotFoundError as exc:
        raise WhipperError(f"{tool_name} binary not found at {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise WhipperError(f"{tool_name} timed out after {timeout:.0f}s") from exc
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


@dataclass(frozen=True)
class TrackTag:
    """One track's tags for a metadata-fed backend (cyanrip's `-t`).

    `number` is the 1-based track position. `title`/`artist` are the
    (possibly user-edited) values from the track table; `isrc` is the
    MusicBrainz-supplied recording ISRC (silent passthrough — not editable),
    empty when MB has none.
    """

    number: int
    title: str = ""
    artist: str = ""
    isrc: str = ""


@dataclass(frozen=True)
class RipMetadata:
    """The GUI's already-fetched album/track metadata, offered to the backend.

    Filled by the main window from the track table (the MusicBrainz lookup
    result plus any user edits) right before a rip starts. Backends that
    fetch their own metadata (whipper does, via `--release-id`) ignore it;
    backends that can be fed tags directly (cyanrip's `-a`/`-t`) use it so
    the rip needs no in-container network and the user's edits win.

    `tracks` holds :class:`TrackTag` entries, 1-based numbers. The album-level
    `genre` / `disc_number` / `total_discs` are MusicBrainz-supplied silent
    passthroughs (best-effort; defaults are harmless when MB has nothing).
    """

    album_artist: str = ""
    album_title: str = ""
    year: str = ""
    genre: str = ""
    disc_number: int = 1
    total_discs: int = 1
    tracks: tuple[TrackTag, ...] = ()


class RipHandle:
    """Handle to a running rip subprocess.

    Exposes line-streaming, blocking wait, and cancellation. Doesn't
    know where whipper writes the `.log` file — the rip worker locates
    that itself by scanning `output_dir` after the process exits.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process: subprocess.Popen[str] = process

    def log_lines(self) -> Iterator[str]:
        """Yield whipper's combined stdout/stderr lines as they come.

        Iteration ends when whipper closes its stream (i.e. exits).
        Call `.wait()` afterward to harvest the exit code.
        """
        assert self._process.stdout is not None
        for line in self._process.stdout:
            yield line.rstrip("\n")

    def wait(self, timeout: float | None = None) -> int:
        """Block until whipper exits; return its exit code."""
        return self._process.wait(timeout=timeout)

    def cancel(self, term_timeout: float = 5.0) -> int:
        """Cancel the rip. SIGTERM first, then SIGKILL after the timeout.

        Returns the eventual exit code. Safe to call multiple times.
        """
        if self._process.returncode is not None:
            return self._process.returncode

        _kill_group(self._process, signal.SIGTERM)
        try:
            return self._process.wait(timeout=term_timeout)
        except subprocess.TimeoutExpired:
            log.warning(
                "whipper did not exit %.1fs after SIGTERM — sending SIGKILL",
                term_timeout,
            )
            _kill_group(self._process, signal.SIGKILL)
            return self._process.wait()

    @property
    def returncode(self) -> int | None:
        return self._process.returncode


# --- Abstract base ----------------------------------------------------------


class WhipperBackend(ABC):
    """Abstract base for any whipper-or-equivalent ripping backend.

    Implementations: WhipperHostExportedImpl (this module). Future:
    CyanripImpl could be slotted in by implementing this interface.
    """

    @abstractmethod
    def list_drives(self) -> list[DriveDescriptor]:
        """Return all drives the backend can see, parsed."""

    @abstractmethod
    def disc_info(self, drive: str) -> DiscInfo:
        """Return TOC/MB-disc-ID info for the disc currently in `drive`."""

    @abstractmethod
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
        metadata: RipMetadata | None = None,
    ) -> RipHandle:
        """Begin a rip. `release_id` is an MBID, never an interactive prompt.

        `metadata` is the GUI's already-fetched album/track tags (see
        :class:`RipMetadata`); backends that fetch their own may ignore it.
        `read_offset_override`, when set, passes whipper's `--offset N` to
        override whipper.conf for this rip.
        `cdr=True` passes whipper's `--cdr` flag so it will rip a burned
        CD-R (it refuses by default). `cover_art` (one of whipper's
        {file, embed, complete}, or "" to skip), `force_overread`,
        `max_retries`, and `keep_going` map to the matching `cd rip`
        flags — the EAC bit-perfect parity gaps (KDD-13). The returned
        handle streams whipper's stdout and supports cancel.
        """

    @abstractmethod
    def version(self) -> str:
        """Return whipper's reported version string (raw, untrimmed)."""

    # --- Optional drive-calibration capability ------------------------------
    # Deliberately NOT abstract: not every backend can auto-calibrate (a
    # future CyanripImpl might expect whipper.conf to be pre-populated).
    # The drive-setup wizard treats NotImplementedError as "this backend
    # can't do it" rather than crashing.

    def analyze_drive(self, device: str) -> bool | None:
        """Profile the drive's audio cache (for the setup wizard).

        Returns True/False when whipper determines the cache can / cannot
        be defeated, or None if it ran but couldn't classify. whipper
        persists the result to whipper.conf itself. Raises `WhipperError`
        if no disc is present (it needs one to test).
        """
        raise NotImplementedError

    def find_offset(self, device: str) -> int:
        """Auto-detect the drive read offset in samples, signed.

        Tests candidate offsets against AccurateRip; whipper persists the
        winner to whipper.conf itself. Raises `WhipperError` if none was
        found (most often: the inserted disc isn't in AccurateRip).
        """
        raise NotImplementedError

    def cancel_setup(self) -> None:  # noqa: B027 — intentional optional no-op hook
        """Terminate an in-progress `analyze_drive`/`find_offset` subprocess.

        Default no-op (deliberately concrete, not abstract: most backends have
        nothing to cancel and shouldn't be forced to implement it). The host-
        setup wizard can stop the (slow, disc-spinning) whipper process
        when the user closes the dialog — otherwise it keeps the optical
        drive busy long after the GUI is done with it.
        """


# --- v1 concrete implementation --------------------------------------------


class WhipperHostExportedImpl(WhipperBackend):
    """Calls the whipper binary exported by Distrobox to ~/.local/bin/whipper.

    Per CLAUDE.md Critical Rule #3, the GUI never enters the Distrobox
    container directly — it invokes the host-exported entry point
    whipper itself manages.
    """

    def __init__(
        self,
        binary_path: Path,
        working_dir: Path | None = None,
    ) -> None:
        """`binary_path` defaults via config to ~/.local/bin/whipper.

        `working_dir`, when set, is passed as `--working-directory`. None
        means whipper uses its own default.
        """
        self._binary: Path = binary_path
        self._working_dir: Path | None = working_dir
        # The currently-running drive-setup subprocess (analyze/offset),
        # so cancel_setup() can terminate it from the GUI thread. Assigned
        # from the worker thread; reads/writes of a single attribute are
        # atomic under the GIL, which is enough here.
        self._setup_proc: subprocess.Popen[str] | None = None

    # --- Info commands ---

    def list_drives(self) -> list[DriveDescriptor]:
        output = self._run_info(["drive", "list"])
        return parse_drive_list(output)

    def disc_info(self, drive: str) -> DiscInfo:
        # Note: whipper has no -d/--device flag — it auto-detects the
        # single drive on the system. The `drive` parameter is accepted
        # for ABC compatibility and for future multi-drive support
        # (P1 backlog); on single-drive systems (the common case) it's
        # ignored at the subprocess layer. If a multi-drive selection
        # mechanism is later added to whipper, plumb it here.
        del drive  # explicit: parameter intentionally unused for v1
        try:
            output = self._run_info(["cd", "info"])
        except WhipperError as exc:
            # Upstream whipper bug: `whipper cd info` exits -1 with
            # CRITICAL "unable to retrieve disc metadata, --unknown
            # argument not passed" when the inserted disc isn't in
            # MusicBrainz/FreeDB — but the Info subcommand doesn't
            # accept --unknown (only Rip does), so there's no way to
            # pass it. Treat that specific failure as "this disc isn't
            # in any database" and return an empty DiscInfo so the GUI
            # can render a clean "not in MusicBrainz" state and offer
            # the File → Rip as Unknown Album flow.
            if "unable to retrieve disc metadata" in (exc.output or ""):
                # Whipper still prints the disc IDs and "N audio tracks"
                # to stdout before it bails on the missing metadata, so
                # parse what it gave us rather than discarding everything.
                # That salvages the track count (for showing numbered
                # blank rows) and the disc IDs (for the info panel). If
                # the output had none of those, parse_cd_info returns an
                # empty DiscInfo and the unknown-album flow still works.
                log.info(
                    "whipper cd info: disc not in MusicBrainz/FreeDB; "
                    "parsing partial output for the unknown-album flow"
                )
                return parse_cd_info(exc.output)
            raise
        return parse_cd_info(output)

    def version(self) -> str:
        return self._run_info(["--version"]).strip()

    # --- Drive calibration (setup wizard) ---

    def analyze_drive(self, device: str) -> bool | None:
        args = ["drive", "analyze"]
        if device:
            # Unlike `cd rip`/`cd info`, the drive subcommands DO accept
            # -d/--device (whipper/command/drive.py), so pass the selected
            # drive explicitly — matters once multi-drive support lands.
            args += ["-d", device]
        rc, out = self._run_setup_capture(args)
        if _NO_DISC_MARKER in out:
            raise WhipperError("Insert a CD so the drive can be analyzed.", output=out)
        if _CACHE_CAN in out:
            return True
        if _CACHE_CANNOT in out:
            return False
        if rc != 0:
            raise WhipperError(
                f"whipper drive analyze failed: {_last_line(out, rc)}",
                output=out,
            )
        return None  # ran cleanly but produced no recognizable verdict

    def find_offset(self, device: str) -> int:
        args = ["offset", "find"]
        if device:
            args += ["-d", device]
        _rc, out = self._run_setup_capture(args)
        match = _OFFSET_RE.search(out)
        if match:
            return int(match.group("offset"))
        # The usual cause is a disc that isn't in AccurateRip; whipper's
        # own detection is also documented as "primitive". Give the user
        # an actionable message rather than the raw failure.
        raise WhipperError(
            "Could not detect the read offset. Insert a popular commercial "
            "CD (one likely to be in the AccurateRip database) and try again.",
            output=out,
        )

    def cancel_setup(self) -> None:
        """Terminate the running drive-setup subprocess, if any.

        Called from the GUI thread when the user closes the wizard. SIGTERM
        first, then SIGKILL — same escalation as RipHandle.cancel. Without
        this the whipper process (and the disc it's spinning) keeps running
        long after the dialog is gone.
        """
        proc = self._setup_proc
        if proc is None or proc.poll() is not None:
            return
        # SIGKILL the whole group (so the in-tree cdparanoia stops the
        # drive, not just the parent), and don't wait/reap here: the worker
        # thread owns this Popen via communicate() and is the sole reaper,
        # so waiting here too would race on waitpid. KILL is immediate, so
        # communicate() returns at once and the dialog's QThread can join.
        log.info("cancelling drive-setup subprocess group (SIGKILL)")
        _kill_group(proc, signal.SIGKILL)

    def _run_setup_capture(self, args: list[str]) -> tuple[int, str]:
        """Run a slow, *cancellable* setup command via Popen.

        Unlike `_run_capture` (which uses subprocess.run and can't be
        interrupted), this stores the Popen on `self._setup_proc` so
        `cancel_setup()` can terminate it mid-flight. Returns
        (returncode, combined-output); raises WhipperError on a missing
        binary or timeout.
        """
        argv: list[str] = [str(self._binary), *args]
        log.debug("whipper setup: %s", " ".join(argv))
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # New session/group so cancel_setup() can kill the whole
                # tree (cdparanoia included), not just this parent.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise WhipperError(f"whipper binary not found at {self._binary}") from exc
        self._setup_proc = proc
        try:
            out, _ = proc.communicate(timeout=_SETUP_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            out, _ = proc.communicate()
            self._setup_proc = None
            raise WhipperError(
                f"whipper timed out after {_SETUP_TIMEOUT_S:.0f}s", output=out or ""
            ) from exc
        finally:
            self._setup_proc = None
        return proc.returncode, out or ""

    # --- Streaming rip ---

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
        metadata: RipMetadata | None = None,
    ) -> RipHandle:
        # Note: whipper has no -d/--device flag for `cd rip` — it
        # auto-detects the single drive. Multi-drive selection is P1
        # (see TASKS.md). `drive` is accepted for ABC compatibility.
        del drive  # explicit: parameter intentionally unused for v1
        # whipper fetches album/track tags itself from the --release-id
        # (and unknown-mode tags are applied post-rip by the GUI), so the
        # GUI-supplied metadata is intentionally unused here.
        del metadata
        argv: list[str] = [
            str(self._binary),
            "cd",
            "rip",
            "--release-id",
            release_id,
            "--output-directory",
            str(output_dir),
            "--track-template",
            track_template,
            "--disc-template",
            disc_template,
            # Always pass max-retries (defaults to whipper's own 5, so this
            # is a no-op unless the user changed it in Settings).
            "--max-retries",
            str(max_retries),
        ]
        if read_offset_override is not None:
            # Manual offset from Settings — overrides whipper.conf for this rip.
            argv.extend(["--offset", str(read_offset_override)])
        if self._working_dir is not None:
            argv.extend(["--working-directory", str(self._working_dir)])
        if unknown:
            argv.append("--unknown")
        if cdr:
            # Burned discs: whipper aborts with "inserted disc seems to be
            # a CD-R, --cdr not passed" unless we explicitly allow it.
            argv.append("--cdr")
        # --- EAC parity-gap flags (KDD-13) ---
        if cover_art:
            # whipper choices: file | embed | complete. Empty = omit.
            argv.extend(["--cover-art", cover_art])
        if force_overread:
            argv.append("--force-overread")
        if keep_going:
            argv.append("--keep-going")

        # Whipper chdir's into --working-directory without creating it
        # (crashes with FileNotFoundError otherwise — hit on T32 with a
        # fresh ~/.cache/whipper-gui). Create both dirs up front so a
        # first-ever rip on a clean system just works. exist_ok keeps
        # this idempotent for every subsequent rip.
        output_dir.mkdir(parents=True, exist_ok=True)
        if self._working_dir is not None:
            self._working_dir.mkdir(parents=True, exist_ok=True)

        log.info("rip starting: %s", " ".join(argv))
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so a single stream is observable
            text=True,
            bufsize=1,  # line-buffered for responsive UI updates
            # New session/group so cancel kills the whole tree (cdparanoia
            # included) — otherwise the disc keeps spinning after Cancel.
            start_new_session=True,
        )
        return RipHandle(process=process)

    # --- Internals ---

    def _run_capture(
        self, args: list[str], timeout: float = _INFO_TIMEOUT_S
    ) -> tuple[int, str]:
        """Run a one-shot whipper invocation; return (returncode, combined).

        Raises `WhipperError` only for binary-missing or timeout — NOT for
        a non-zero exit, because some callers (drive analyze, offset find)
        need to classify the output themselves before deciding it's an
        error.
        """
        return run_capture("whipper", str(self._binary), args, timeout=timeout)

    def _run_info(self, args: list[str]) -> str:
        """Run a one-shot info command; return combined output, raising
        `WhipperError` on non-zero exit (last error line preserved)."""
        rc, combined = self._run_capture(args)
        if rc != 0:
            raise WhipperError(
                f"whipper failed: {_last_line(combined, rc)}", output=combined
            )
        return combined
