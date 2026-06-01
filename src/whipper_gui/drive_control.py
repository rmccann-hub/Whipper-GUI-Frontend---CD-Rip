"""Force-stop the optical drive when a cancelled rip won't let go.

Why this exists: a rip runs as `~/.local/bin/whipper` (host wrapper) → podman
→ whipper → **cdparanoia inside the `ripping` container**. Cancelling kills
the host-side process tree, but podman doesn't forward the signal into the
container, so cdparanoia keeps reading and the drive spins — sometimes for
minutes (real-user report, 2026-05-31). Two levers can stop it:

  1. **Eject the disc on the host** (`eject <device>`) — stays within the
     "GUI talks to the host, never the container" architecture. Often
     fails mid-rip with "device busy" because cdparanoia holds the device
     open; in that case lever 2 does the work.
  2. **Kill cdparanoia/whipper inside the container.**

Lever 2 runs a command *inside* the `ripping` container, which CLAUDE.md
Critical Rule #3 normally forbids ("the GUI never calls into the container
directly"). This is a **deliberate, user-approved exception (2026-05-31)**,
scoped strictly to *force-stopping a cancelled rip* — the only reliable way
to stop a runaway in-container reader from the host. It is NOT a general
licence to drive whipper inside the container; ripping itself still goes
through `~/.local/bin/whipper`.

Everything here is best-effort and synchronous; the caller runs it off the
GUI thread (it can block for the subprocess timeout). The `runner` is
injectable so tests never touch a real drive or container.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Callable

log = logging.getLogger(__name__)

# The Distrobox container whipper lives in (README/setup-host default).
DEFAULT_CONTAINER: str = "ripping"

# Process names the in-container reader/ripper runs under. Matched as an
# extended-regex alternation by `pkill -f`.
_KILL_PATTERN: str = "cdparanoia|cd-paranoia|whipper"

# A runner takes an argv list and returns something with a `.returncode`.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: list[str]) -> "subprocess.CompletedProcess[str]":
    """Run a command, swallowing its output; never inherit stdin (so a
    `distrobox enter` can't block waiting on a TTY). Bounded by a timeout so a
    wedged container can't hang the caller forever."""
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )


def eject_drive(device: str = "", runner: Runner | None = None) -> bool:
    """Eject `device` on the host. Returns True if the eject succeeded.

    A non-zero exit is the normal "device busy" case during an active read —
    not an error worth surfacing; the caller falls back to the in-container
    kill.
    """
    run = runner or _default_runner
    argv = ["eject", *([device] if device else [])]
    try:
        rc = run(argv).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("eject %s failed: %s", device or "(default)", exc)
        return False
    if rc == 0:
        log.info("ejected %s", device or "(default)")
        return True
    log.info("eject %s returned rc=%s (likely busy — will try the reader)", device or "(default)", rc)
    return False


def force_stop_in_container(
    container: str = DEFAULT_CONTAINER, runner: Runner | None = None
) -> bool:
    """Kill the in-container reader/ripper. USER-APPROVED Rule #3 exception.

    Returns True if pkill ran (whether or not it matched a process — exit 1
    just means "nothing to kill", which is fine).
    """
    run = runner or _default_runner
    argv = ["distrobox", "enter", container, "--",
            "pkill", "-TERM", "-f", _KILL_PATTERN]
    try:
        rc = run(argv).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("in-container force-stop failed: %s", exc)
        return False
    log.info("in-container pkill '%s' rc=%s", _KILL_PATTERN, rc)
    return rc in (0, 1)  # 0 killed something, 1 matched nothing


def force_stop_drive(
    device: str = "",
    container: str = DEFAULT_CONTAINER,
    runner: Runner | None = None,
) -> str:
    """Try both levers (eject, then in-container kill) and report what happened.

    Synchronous and best-effort — run it off the GUI thread. Both levers are
    attempted regardless of each other's outcome, so a busy-failed eject still
    gets the reader killed.
    """
    ejected = eject_drive(device, runner=runner)
    killed = force_stop_in_container(container, runner=runner)
    if ejected:
        return "Drive ejected — it should stop now."
    if killed:
        return "Stopped the in-container reader — the drive should spin down."
    return "Tried to force-stop the drive (eject + reader kill)."
