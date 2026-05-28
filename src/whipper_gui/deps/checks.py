"""Probe functions: "is this dependency present, and at what version?"

One probe per dependency, returning a `ProbeResult`. Probes have no side
effects — they MUST NOT install, modify, or write anything; they may
shell out (`subprocess.run`) to ask a tool for its version.

Failures (tool missing, network gone, timeout) are caught and reflected
in the `ProbeResult`, never raised. The dependency manager classifies a
probe with `present=False` as missing; how to resolve it is the
registry's tier decision and the resolvers' job.
"""

from __future__ import annotations

import importlib.metadata
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from whipper_gui.deps.version import parse_version

log = logging.getLogger(__name__)

# Probes that shell out should never hang the GUI. 10s is generous —
# `--version` typically returns in milliseconds; a value this large just
# guards against a wedged binary.
_PROBE_TIMEOUT_S: float = 10.0


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single dependency probe.

    - `present`: True if the dep is installed and we got a usable answer.
    - `version`: parsed version tuple, or None if we couldn't determine it.
    - `location`: where we found it (path, "(python package)", etc.) or None.
    - `raw_output`: stdout/stderr we captured, useful for debugging. Kept
      short — we log it but don't store gigabytes if a probe goes weird.
    """

    present: bool
    version: tuple[int, ...] | None
    location: str | None
    raw_output: str = ""


def _run_version_command(
    argv: list[str],
) -> tuple[bool, str, str | None]:
    """Shell out and capture stdout+stderr. Returns (ran_ok, output, location).

    `location` is `argv[0]` resolved through `shutil.which` when possible
    so the user sees the actual path the GUI is using, not the unresolved
    name. Returns `ran_ok=False` if the command times out or the binary
    isn't found.
    """
    resolved = shutil.which(argv[0]) or argv[0]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
        )
    except FileNotFoundError:
        log.debug("probe: %s not found on PATH", argv[0])
        return False, "", None
    except subprocess.TimeoutExpired:
        log.warning("probe: %s timed out after %.1fs", argv[0], _PROBE_TIMEOUT_S)
        return False, "", resolved

    combined = (proc.stdout or "") + (proc.stderr or "")
    return True, combined, resolved


def check_whipper(binary_path: Path) -> ProbeResult:
    """Probe the host-exported whipper binary.

    The brief mandates calling `~/.local/bin/whipper`, so we accept the
    path explicitly rather than relying on PATH alone — that way the
    user's Settings override is honored.
    """
    if not binary_path.exists():
        return ProbeResult(
            present=False, version=None, location=str(binary_path)
        )

    ran, output, _ = _run_version_command([str(binary_path), "--version"])
    if not ran:
        return ProbeResult(
            present=False, version=None, location=str(binary_path)
        )

    version = parse_version(output)
    return ProbeResult(
        present=True,
        version=version,
        location=str(binary_path),
        raw_output=output.strip()[:200],
    )


def check_metaflac(binary_name: str = "metaflac") -> ProbeResult:
    """Probe `metaflac`, expected on PATH (typically via the same
    Distrobox export route as whipper)."""
    ran, output, location = _run_version_command([binary_name, "--version"])
    if not ran or location is None:
        return ProbeResult(present=False, version=None, location=None)

    version = parse_version(output)
    return ProbeResult(
        present=True,
        version=version,
        location=location,
        raw_output=output.strip()[:200],
    )


def check_libdiscid() -> ProbeResult:
    """Probe libdiscid by attempting to load it via ctypes.

    We try the common SONAME variants the library ships with. If any
    load succeeds, we call `discid_get_version_string()` for the version.
    Returns `present=False` if no variant loads.

    Note (PLANNING.md KDD-06): libdiscid may not actually be required on
    the host because whipper computes the disc ID inside its Distrobox
    container. The probe exists so the dependency subsystem has the
    capability when the answer turns out to be "yes, we need it."
    """
    import ctypes
    import ctypes.util

    # ctypes.util.find_library is the portable way; fall back to common
    # SONAMEs if it doesn't resolve (some systems set it up oddly).
    candidates: list[str] = []
    found = ctypes.util.find_library("discid")
    if found:
        candidates.append(found)
    candidates.extend(["libdiscid.so.0", "libdiscid.so"])

    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue

        try:
            lib.discid_get_version_string.restype = ctypes.c_char_p
            version_str = lib.discid_get_version_string().decode("utf-8")
        except (AttributeError, OSError, UnicodeDecodeError):
            version_str = ""

        version = parse_version(version_str)
        return ProbeResult(
            present=True,
            version=version,
            location=name,
            raw_output=version_str,
        )

    return ProbeResult(present=False, version=None, location=None)


def check_picard_flatpak() -> ProbeResult:
    """Probe MusicBrainz Picard via Flathub.

    Uses `flatpak info --user org.musicbrainz.Picard`. If flatpak itself
    isn't installed, returns `present=False` (which the registry can
    treat as a tier-(a) install opportunity for the Flatpak system).
    """
    ran, output, _ = _run_version_command(
        ["flatpak", "info", "--user", "org.musicbrainz.Picard"]
    )
    if not ran:
        return ProbeResult(present=False, version=None, location=None)

    # `flatpak info` returns non-zero when the app isn't installed; the
    # output then says "error: ...". A successful run includes a
    # "Version:" line.
    if "Version:" not in output:
        return ProbeResult(
            present=False, version=None, location=None, raw_output=output[:200]
        )

    version = parse_version(output)
    return ProbeResult(
        present=True,
        version=version,
        location="flatpak: org.musicbrainz.Picard",
        raw_output=output.strip()[:200],
    )


def check_python_pkg(distribution: str) -> ProbeResult:
    """Probe a Python distribution that's expected to be importable.

    We ask `importlib.metadata` instead of importing the module so we
    can read the version even if importing would have side effects.
    """
    try:
        version_str = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return ProbeResult(present=False, version=None, location=None)

    version = parse_version(version_str)
    return ProbeResult(
        present=True,
        version=version,
        location=f"python: {distribution}",
        raw_output=version_str,
    )
