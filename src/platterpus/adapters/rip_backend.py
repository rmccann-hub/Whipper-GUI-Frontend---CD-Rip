"""Backend-neutral ripping interface and shared subprocess plumbing.

`RipBackend` is the abstract base class with the operations the GUI needs;
the active implementation is `CyanripImpl` in `cyanrip_backend.py`, selected by
`composition.build_backend`. (A second backend was supported historically; the
ABC is kept deliberately backend-neutral so another engine could be slotted in
behind it — implement this interface and wire it into `build_backend`.)

This module holds only the pieces every backend shares — the ABC, the rip
handle, the metadata dataclasses, the `RipError` exception, and `run_capture`
— so a concrete backend module depends on *this*, not on a sibling backend.

The adapters are deliberately thin: they build argv, run subprocess, and hand
stdout to the parsers in `platterpus.parsers`. They do NOT parse output inline.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from platterpus.parsers.cd_info import DiscInfo
from platterpus.parsers.drive_list import DriveDescriptor

log = logging.getLogger(__name__)


def _kill_group(proc: subprocess.Popen[str], sig: int) -> None:
    """Send `sig` to the subprocess's whole process group.

    A ripper spawns children (the `~/.local/bin/<tool>` wrapper →
    distrobox/podman → the in-container ripper → libcdio/cdparanoia, the
    actual disc reader). Signalling only the parent leaves the reader running,
    so the drive keeps spinning. Because we launch these processes with
    `start_new_session=True`, the parent is a group leader and one killpg()
    reaches the whole tree. Falls back to the single process if the group
    can't be addressed.

    NOTE: the in-*container* reader (under podman) is a separate process tree;
    podman doesn't always forward the signal instantly, so the drive can take
    a moment to spin down even after this. It does stop — just not always
    immediately.
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


class RipError(Exception):
    """Raised when a ripper subprocess fails in an actionable way.

    The message holds the last stderr line the tool emitted (or its stdout
    fallback) so the GUI can surface something meaningful to the user. The
    full output is available on `.output` for logging. Backend-agnostic: any
    backend's adapter raises this.
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

    The shared core of a backend's info/version probes. It deliberately does
    NOT raise on a non-zero exit — some callers (offset find) classify the
    output themselves — but it DOES translate the two unrecoverable failures
    into a :class:`RipError` the GUI can surface: a missing binary and a
    timeout.

    The pieces that genuinely differ between backends are parameters, not
    forks: ``timeout``, ``tool_name`` (shapes the log line and the error
    messages), and ``stdin_devnull`` (cyanrip reads stdin and must have it
    closed; a tool that inherits stdin passes False, matching
    ``subprocess.run``'s default of ``stdin=None``).
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
        raise RipError(f"{tool_name} binary not found at {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RipError(f"{tool_name} timed out after {timeout:.0f}s") from exc
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
    result plus any user edits) right before a rip starts. Backends that can
    be fed tags directly (cyanrip's `-a`/`-t`) use it so the rip needs no
    in-container network and the user's edits win.

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

    Exposes line-streaming, blocking wait, and cancellation. Doesn't know
    where the backend writes the `.log` file — the rip worker locates that
    itself by scanning `output_dir` after the process exits.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process: subprocess.Popen[str] = process

    def log_lines(self) -> Iterator[str]:
        """Yield the ripper's combined stdout/stderr lines as they come.

        Iteration ends when the ripper closes its stream (i.e. exits).
        Call `.wait()` afterward to harvest the exit code.
        """
        assert self._process.stdout is not None
        for line in self._process.stdout:
            yield line.rstrip("\n")

    def wait(self, timeout: float | None = None) -> int:
        """Block until the ripper exits; return its exit code."""
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
                "ripper did not exit %.1fs after SIGTERM — sending SIGKILL",
                term_timeout,
            )
            _kill_group(self._process, signal.SIGKILL)
            return self._process.wait()

    @property
    def returncode(self) -> int | None:
        return self._process.returncode


# --- Abstract base ----------------------------------------------------------


class RipBackend(ABC):
    """Abstract base for any CD-ripping backend.

    A new backend is added by implementing this interface and wiring it into
    `composition.build_backend`.
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
        cover_art: str = "",
        max_retries: int = 5,
        secure_rerip_matches: int = 0,
        read_offset_override: int | None = None,
        metadata: RipMetadata | None = None,
        read_speed: int = 0,
    ) -> RipHandle:
        """Begin a rip. `release_id` is an MBID, never an interactive prompt.

        `metadata` is the GUI's already-fetched album/track tags (see
        :class:`RipMetadata`). `read_offset_override`, when set, applies that
        read offset for this rip (cyanrip's `-s`). `cover_art` (one of the
        backend's accepted values, or "" to skip) and `max_retries` map to the
        matching rip flags — the EAC bit-perfect parity gaps (KDD-13).
        `secure_rerip_matches`, when > 0, is cyanrip's `-Z N` (re-rip a track
        until N reads' checksums agree) for marginal discs. `read_speed`, when
        > 0, caps the drive read speed for this pass (cyanrip's `-S N`); 0 lets
        the drive pick its maximum. The adaptive ladder feeds slower values here
        on a re-rip (see :mod:`platterpus.read_speed_ladder`). The returned handle
        streams the backend's stdout and supports cancel.
        """

    @abstractmethod
    def version(self) -> str:
        """Return the backend's reported version string (raw, untrimmed)."""

    # --- Optional capability flags ------------------------------------------

    def self_verifies_encode(self) -> bool:
        """True if the backend already proves each encoded file decodes back to
        the read PCM (so a separate post-rip FLAC verify would be redundant).

        Default False (the safe assumption: verify it ourselves). cyanrip
        (FFmpeg) does not self-verify, so it inherits False.
        """
        return False

    def produces_max_compression_flac(self) -> bool:
        """True if the backend already encodes FLAC at the maximum level, so a
        post-rip re-compress (`flac -8`) would gain nothing.

        Default False. cyanrip overrides to True: it drives libavcodec at the
        maximum FLAC compression level already, so the GUI skips re-compression
        for it (and Settings greys the toggle out).
        """
        return False

    def native_output_formats(self) -> frozenset[str]:
        """The output formats (among the ones the GUI offers) this backend can
        produce *natively*, in one rip.

        Default ``{"flac"}``. cyanrip overrides to add the formats it emits
        directly via ``-o``.

        **Reserved seam (KDD-22):** the shipped multi-format feature uses a
        *transcode-always* model instead — every rip produces FLAC and a
        non-FLAC choice is a post-rip ffmpeg transcode
        (``adapters/transcode.py``), which always keeps the FLAC master. So
        nothing consumes this method for the rip today; it's kept for a future
        "let cyanrip encode natively and skip the transcode" optimization.
        """
        return frozenset({"flac"})

    # --- Optional drive-calibration capability ------------------------------
    # Deliberately NOT abstract: not every backend can auto-calibrate. The
    # drive-setup wizard treats NotImplementedError as "this backend can't do
    # it" rather than crashing.

    def analyze_drive(self, device: str) -> bool | None:
        """Profile the drive's audio cache (for the setup wizard).

        Returns True/False when the backend determines the cache can / cannot
        be defeated, or None if it ran but couldn't classify. Raises
        :class:`RipError` if no disc is present (it needs one to test).
        cyanrip has no cache-analysis command, so it leaves this unimplemented.
        """
        raise NotImplementedError

    def find_offset(self, device: str) -> int:
        """Auto-detect the drive read offset in samples, signed.

        Tests candidate offsets against AccurateRip. Raises :class:`RipError`
        if none was found (most often: the inserted disc isn't in AccurateRip).
        The caller persists the returned value (Platterpus's `--offset`
        override); the backend does not write it anywhere.
        """
        raise NotImplementedError

    def cancel_setup(self) -> None:  # noqa: B027 — intentional optional no-op hook
        """Terminate an in-progress `analyze_drive`/`find_offset` subprocess.

        Default no-op (deliberately concrete, not abstract: most backends have
        nothing to cancel and shouldn't be forced to implement it). The
        host-setup wizard can stop a slow, disc-spinning detection process when
        the user closes the dialog — otherwise it keeps the optical drive busy
        long after the GUI is done with it.
        """
