"""Force-stop the optical drive when a cancelled rip won't let go.

Why this exists: a rip runs as `~/.local/bin/whipper` (host wrapper) → podman
→ **whipper inside the `ripping` container**, which itself spawns `cdrdao`
(to read the TOC — the "Reading table" phase) and `cd-paranoia` (to rip each
track). Cancelling kills the host-side wrapper, but podman doesn't forward the
signal into the container, so whipper keeps orchestrating reads and the drive
spins — sometimes for minutes (real-user reports, 2026-05/06).

Hard-won facts (2026-06-01, real hardware):

  * **whipper is the orchestrator.** Killing only the reader (`cdrdao` /
    `cd-paranoia`) doesn't help — whipper just respawns it. You must kill the
    **whipper** process. (Confirmed: `pkill cdrdao` did nothing; `pkill -f
    …whipper` stopped it.)
  * On rootless podman/Distrobox (the Bazzite target) the in-container
    processes are **host-visible**, so a host-side `pkill`/`fuser` reaches
    them — no `distrobox enter` needed in the normal case.
  * **Never use `pkill -f` with the bare word "whipper" or with the reader
    names.** `-f` matches the full command line, so it also matches the GUI's
    own "whipper-gui" command line (killing the app) and the `distrobox enter
    … whipper …` wrapper / the pkill's own command line (self-kill). Match the
    whipper *sub-command* (`whipper cd …`), and match readers by process
    *name* (no `-f`).
  * The drive ignores the physical eject button while a read holds the device,
    which is why pressing eject by hand doesn't stop the spin — and why a
    software `eject` only works *after* the holder is killed.

The in-container `distrobox enter …` fallback (used only when the host can't
see the processes) calls *into* the `ripping` container, which CLAUDE.md
Critical Rule #3 normally forbids. This is a **deliberate, user-approved
exception (2026-05-31)**, scoped strictly to *force-stopping a cancelled rip*.
Ripping itself still goes through `~/.local/bin/whipper`.

Everything here is best-effort and synchronous; the caller runs it off the GUI
thread (it can block for the subprocess timeout). The `runner` is injectable so
tests never touch a real drive or container.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable

log = logging.getLogger(__name__)

# The Distrobox container whipper lives in (README/setup-host default).
DEFAULT_CONTAINER: str = "ripping"

# The reader subprocess names, matched against the process *name* (pkill
# default, NOT `-f`). `-f` here would self-match the wrapper/pkill command line.
_READER_NAMES: str = "cdparanoia|cd-paranoia|cdrdao"

# The whipper CLI process — the orchestrator that must die for the rip to stop
# (it respawns the reader otherwise). Matched on the full command line (`-f`)
# but anchored as `whipper <subcommand>` so it can NEVER match:
#   * the GUI — its command line is "whipper-gui" (hyphen, no space+subcommand);
#   * this pkill or the `distrobox enter … pkill …` wrapper — their command line
#     contains the literal pattern text "whipper (cd|…", i.e. "whipper (" not
#     "whipper cd", so the regex doesn't match.
_WHIPPER_CLI: str = r"whipper (cd|drive|offset|image|accurip|mblookup|rip)"

# A runner takes an argv list and returns something with a `.returncode`.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# When the GUI is launched from a desktop icon (not a shell), PATH can be
# minimal and miss ~/.local/bin or even /usr/bin. Resolve these tools to an
# absolute path so the force-stop doesn't silently no-op.
_PKILL_FALLBACKS: tuple[str, ...] = ("/usr/bin/pkill", "/bin/pkill")
_FUSER_FALLBACKS: tuple[str, ...] = ("/usr/bin/fuser", "/bin/fuser", "/usr/sbin/fuser")
_EJECT_FALLBACKS: tuple[str, ...] = ("/usr/bin/eject", "/usr/sbin/eject", "/sbin/eject")
_DISTROBOX_FALLBACKS: tuple[str, ...] = (
    os.path.expanduser("~/.local/bin/distrobox"),
    "/usr/bin/distrobox",
    "/usr/local/bin/distrobox",
)


def _resolve(name: str, *fallbacks: str) -> str:
    """Find an executable even under a minimal PATH. Falls back to common
    absolute locations, then to the bare name (which FileNotFoundErrors if the
    tool is genuinely absent — caught and treated as best-effort)."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in fallbacks:
        if os.path.exists(candidate):
            return candidate
    return name


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
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


def _run_rc(argv: list[str], run: Runner) -> int | None:
    """Run argv, returning its exit code, or None if it couldn't run."""
    try:
        return run(argv).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("command %s failed: %s", argv[:1], exc)
        return None


def _pkill_arglists() -> list[list[str]]:
    """The pkill argument lists (after the `pkill` token) that stop a rip, in
    order: whipper FIRST (the orchestrator — kill it so it can't respawn the
    reader), then the reader processes by name."""
    return [
        ["-KILL", "-f", _WHIPPER_CLI],  # whipper CLI, anchored (never the GUI)
        ["-KILL", _READER_NAMES],  # cdrdao / cd-paranoia, by process name
    ]


def _run_pkills(prefix: list[str], run: Runner) -> bool:
    """Run the pkill arg-lists with a prefix (`[pkill_path]` on the host, or
    `[distrobox, enter, c, --, pkill]` for the container). True if any killed."""
    killed = False
    for args in _pkill_arglists():
        rc = _run_rc(prefix + args, run)
        log.info("pkill %s rc=%s", args, rc)
        if rc == 0:
            killed = True
    return killed


def eject_drive(device: str = "", runner: Runner | None = None) -> bool:
    """Eject `device` on the host (call *after* the holder is killed, so the
    device is free). Returns True if the eject succeeded."""
    run = runner or _default_runner
    argv = [_resolve("eject", *_EJECT_FALLBACKS), *([device] if device else [])]
    rc = _run_rc(argv, run)
    if rc == 0:
        log.info("ejected %s", device or "(default)")
        return True
    log.info("eject %s returned rc=%s", device or "(default)", rc)
    return False


def free_device_holders(device: str, runner: Runner | None = None) -> bool:
    """`fuser -k <device>`: SIGKILL whatever holds the device, matched by the
    *device* rather than a process name — so it catches the holder no matter
    what it's called, and never the GUI (which doesn't open the device). No-op
    without a device path. Returns True if something was using/killed."""
    if not device:
        return False
    run = runner or _default_runner
    argv = [_resolve("fuser", *_FUSER_FALLBACKS), "-s", "-k", device]
    rc = _run_rc(argv, run)
    log.info("fuser -k %s rc=%s", device, rc)
    return rc == 0


def kill_reader_on_host(runner: Runner | None = None) -> bool:
    """SIGKILL the whipper CLI and the reader as host-visible processes. On
    rootless podman/Distrobox the in-container processes are host-visible, so
    this is the primary lever. Returns True if something was killed."""
    run = runner or _default_runner
    pkill = _resolve("pkill", *_PKILL_FALLBACKS)
    return _run_pkills([pkill], run)


def force_stop_in_container(
    container: str = DEFAULT_CONTAINER, runner: Runner | None = None
) -> bool:
    """SIGKILL the rip from *inside* the container (USER-APPROVED Rule #3
    exception), used only as a fallback when the host pkill matched nothing.
    Returns True if something was killed."""
    run = runner or _default_runner
    distrobox = _resolve("distrobox", *_DISTROBOX_FALLBACKS)
    return _run_pkills([distrobox, "enter", container, "--", "pkill"], run)


def force_stop_drive(
    device: str = "",
    container: str = DEFAULT_CONTAINER,
    runner: Runner | None = None,
) -> str:
    """Stop a runaway drive, then eject.

    Sequence (all best-effort, host-side first):
      1. kill the whipper CLI + reader (host pkill) — whipper first so it can't
         respawn the reader;
      2. `fuser -k <device>` — name-independent catch-all for whatever still
         holds the device;
      3. only if the host saw nothing, kill inside the container;
      4. eject (now that the device is free).

    Synchronous and best-effort; run it off the GUI thread.
    """
    run = runner or _default_runner
    killed = kill_reader_on_host(runner=run)
    if free_device_holders(device, runner=run):
        killed = True
    if not killed:
        killed = force_stop_in_container(container, runner=run)
    ejected = eject_drive(device, runner=run)
    log.info("force_stop_drive: killed=%s ejected=%s", killed, ejected)
    if killed:
        return "Stopped the rip — the drive should spin down."
    if ejected:
        return "Ejected the disc — the drive should stop."
    return "Tried to force-stop the drive (kill + eject)."
