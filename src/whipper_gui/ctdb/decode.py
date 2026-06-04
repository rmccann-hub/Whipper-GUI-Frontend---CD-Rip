# SPDX-License-Identifier: GPL-3.0-only
"""Decode ripped FLACs to raw PCM, and read FLAC sample counts.

CTDB's match CRC is computed over the disc's decoded audio, so we need PCM on
the host. Per the user's decision (2026-06-03) we use the host `flac` binary
**if present** and degrade with a clear message if it isn't — no required new
dependency. `metaflac` (already a project dependency) gives us per-file sample
counts for TOC/lead-out math.

Both tools are resolved to absolute paths (a desktop-launched GUI has a minimal
PATH) and invoked via argument lists (never a shell). Runners are injectable so
tests never shell out.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# Decode timeout per file — a full track is seconds of work; the cap just stops
# a wedged decoder from hanging the caller.
_DECODE_TIMEOUT_S: float = 120.0
_PROBE_TIMEOUT_S: float = 15.0

# Injectable subprocess runner: argv -> CompletedProcess. Default runs for real.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[bytes]"]


class DecoderUnavailable(RuntimeError):
    """Raised when no FLAC decoder is available on the host.

    The caller turns this into a "local CRC unavailable — install `flac`"
    verdict rather than a crash, so CTDB lookup still works without a decoder.
    """


def _which(name: str) -> str | None:
    """Resolve `name` on PATH, then common absolute locations (minimal PATH)."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", f"/bin/{name}"):
        if Path(candidate).exists():
            return candidate
    return None


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv, capture_output=True, timeout=_DECODE_TIMEOUT_S, check=False
    )


def flac_available() -> bool:
    """True if a host `flac` decoder can be found."""
    return _which("flac") is not None


def decode_flac_to_pcm(path: Path, runner: Runner | None = None) -> bytes:
    """Decode one FLAC to headerless little-endian 16-bit stereo PCM.

    Uses `flac -d --force-raw-format --endian=little --sign=signed -c <file>`,
    which writes raw PCM to stdout. Raises `DecoderUnavailable` if `flac` is
    missing, or `RuntimeError` if the decode fails.
    """
    flac = _which("flac")
    if flac is None:
        raise DecoderUnavailable("the `flac` decoder is not installed on the host")
    run = runner or _default_runner
    argv = [
        flac,
        "-d",
        "-s",
        "--force-raw-format",
        "--endian=little",
        "--sign=signed",
        "-c",
        str(path),
    ]
    proc = run(argv)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"flac decode failed: {tail[-1] if tail else 'rc!=0'}")
    return proc.stdout or b""


# --- metaflac sample-count probe -------------------------------------------

ProbeRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_probe_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S, check=False
    )


def total_samples(path: Path, runner: ProbeRunner | None = None) -> int:
    """Per-channel sample count of a FLAC via `metaflac --show-total-samples`."""
    metaflac = _which("metaflac")
    if metaflac is None:
        raise DecoderUnavailable("`metaflac` is not installed on the host")
    run = runner or _default_probe_runner
    proc = run([metaflac, "--show-total-samples", str(path)])
    if proc.returncode != 0:
        raise RuntimeError(f"metaflac failed on {path.name}")
    text = (proc.stdout or "").strip()
    try:
        return int(text)
    except ValueError as exc:
        raise RuntimeError(f"unparseable metaflac output: {text!r}") from exc
