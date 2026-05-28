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
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from whipper_gui.parsers.cd_info import DiscInfo, parse_cd_info
from whipper_gui.parsers.drive_list import DriveDescriptor, parse_drive_list

log = logging.getLogger(__name__)

# Generous timeout for one-shot info commands. `whipper drive list` and
# `whipper cd info` return within seconds on a healthy system; the cap
# guards against a hung subprocess.
_INFO_TIMEOUT_S: float = 30.0


class WhipperError(Exception):
    """Raised when a whipper subprocess fails in an actionable way.

    The message holds the last stderr line whipper emitted (or its
    stdout fallback) so the GUI can surface something meaningful to
    the user. The full output is available on `.output` for logging.
    """

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output: str = output


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

        self._process.terminate()
        try:
            return self._process.wait(timeout=term_timeout)
        except subprocess.TimeoutExpired:
            log.warning(
                "whipper did not exit %.1fs after SIGTERM — sending SIGKILL",
                term_timeout,
            )
            self._process.kill()
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
    ) -> RipHandle:
        """Begin a rip. `release_id` is an MBID, never an interactive prompt.

        The returned handle streams whipper's stdout and supports cancel.
        """

    @abstractmethod
    def version(self) -> str:
        """Return whipper's reported version string (raw, untrimmed)."""


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

    # --- Info commands ---

    def list_drives(self) -> list[DriveDescriptor]:
        output = self._run_info(["drive", "list"])
        return parse_drive_list(output)

    def disc_info(self, drive: str) -> DiscInfo:
        # `-d <drive>` is a global whipper flag and must come BEFORE the
        # subcommand (verified against whipper's argparse layout).
        output = self._run_info(["-d", drive, "cd", "info"])
        return parse_cd_info(output)

    def version(self) -> str:
        return self._run_info(["--version"]).strip()

    # --- Streaming rip ---

    def rip(
        self,
        drive: str,
        release_id: str,
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
    ) -> RipHandle:
        argv: list[str] = [
            str(self._binary),
            "-d", drive,
            "cd", "rip",
            "--release-id", release_id,
            "--output-directory", str(output_dir),
            "--track-template", track_template,
            "--disc-template", disc_template,
        ]
        if self._working_dir is not None:
            argv.extend(["--working-directory", str(self._working_dir)])
        if unknown:
            argv.append("--unknown")

        log.info("rip starting: %s", " ".join(argv))
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so a single stream is observable
            text=True,
            bufsize=1,  # line-buffered for responsive UI updates
        )
        return RipHandle(process=process)

    # --- Internals ---

    def _run_info(self, args: list[str]) -> str:
        """Run a one-shot whipper invocation and return combined stdout/stderr.

        Raises `WhipperError` on non-zero exit, with the last error line
        preserved on the exception for the GUI to surface.
        """
        argv: list[str] = [str(self._binary), *args]
        log.debug("whipper info: %s", " ".join(argv))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_INFO_TIMEOUT_S,
            )
        except FileNotFoundError as exc:
            raise WhipperError(
                f"whipper binary not found at {self._binary}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise WhipperError(
                f"whipper timed out after {_INFO_TIMEOUT_S:.0f}s"
            ) from exc

        combined = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            tail = combined.strip().splitlines()
            last = tail[-1] if tail else f"rc={proc.returncode}"
            raise WhipperError(f"whipper failed: {last}", output=combined)
        return combined
