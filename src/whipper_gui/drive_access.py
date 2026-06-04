"""Host-side optical-drive access diagnostics.

When no drive shows up in the picker, an empty dropdown tells the user
nothing. This module explains *why* in actionable terms — most often
"you're not in the `cdrom` group" with the exact command to fix it.

Why checking the host is correct: the GUI runs on the host, and the
AppImage inherits the host user's permissions. whipper runs inside the
Distrobox `ripping` container, but distrobox runs as the *same* user and
passes `/dev` through, so the host user's group membership is the gate.
Probing the device node here therefore reflects what whipper will see.

Pure stdlib, no whipper call — fast and safe to run anytime. The public
function takes injectable probes so it's testable without real hardware.
"""

from __future__ import annotations

import glob
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Optical device nodes (sr0, sr1, …) and the conventional symlinks that
# point at them. We resolve symlinks to their real node so the list
# dedupes cleanly.
_DEVICE_GLOBS: tuple[str, ...] = ("/dev/sr[0-9]*",)
_DEVICE_SYMLINKS: tuple[str, ...] = (
    "/dev/cdrom",
    "/dev/cdrw",
    "/dev/dvd",
    "/dev/dvdrw",
)

# Severities — string constants (not an enum) to keep the dataclass
# trivially serialisable and comparable in tests.
SEVERITY_OK: str = "ok"
SEVERITY_PERMISSION: str = "permission"
SEVERITY_NO_DEVICE: str = "no_device"


@dataclass(frozen=True)
class DriveAccessDiagnosis:
    """Result of probing optical-drive accessibility."""

    severity: str
    summary: str  # one-line headline
    detail: str  # fuller explanation
    fix_command: str | None = None  # shell command the user can run, if any
    devices: tuple[str, ...] = ()  # device nodes we found

    @property
    def actionable(self) -> bool:
        """True when there's a concrete command the user can run to fix it."""
        return self.fix_command is not None


# --- Default probes (overridable for tests) --------------------------------


def _find_device_nodes() -> list[str]:
    """Return existing optical device nodes, symlinks resolved + deduped."""
    found: list[str] = []
    for pattern in _DEVICE_GLOBS:
        found.extend(sorted(glob.glob(pattern)))
    for link in _DEVICE_SYMLINKS:
        if os.path.exists(link):
            found.append(os.path.realpath(link))
    # Preserve order, drop duplicates (a symlink may resolve onto a glob hit).
    return list(dict.fromkeys(found))


def _is_readable(path: str) -> bool:
    return os.access(path, os.R_OK)


def _group_of_node(path: str) -> str | None:
    """Owning group name of a device node, or None if it can't be resolved."""
    import grp  # Unix-only stdlib; the project is Linux-only

    try:
        return grp.getgrgid(os.stat(path).st_gid).gr_name
    except (OSError, KeyError):
        return None


def _in_group(name: str) -> bool:
    """Whether the current user belongs to the named group (any kind)."""
    import grp
    import pwd

    try:
        gid = grp.getgrnam(name).gr_gid
    except KeyError:
        return False
    if gid in os.getgroups():
        return True
    try:  # primary group isn't always in getgroups()
        return pwd.getpwuid(os.getuid()).pw_gid == gid
    except KeyError:
        return False


# --- Public API ------------------------------------------------------------


def diagnose_drive_access(
    *,
    list_nodes: Callable[[], list[str]] = _find_device_nodes,
    is_readable: Callable[[str], bool] = _is_readable,
    group_of: Callable[[str], str | None] = _group_of_node,
    in_group: Callable[[str], bool] = _in_group,
) -> DriveAccessDiagnosis:
    """Diagnose why no optical drive is usable. Never raises.

    The probe callables are injected so tests can simulate any system
    state without real hardware or root.
    """
    nodes = list_nodes()

    if not nodes:
        return DriveAccessDiagnosis(
            severity=SEVERITY_NO_DEVICE,
            summary="No optical drive detected.",
            detail=(
                "No /dev/sr* device node is present. Check that an optical "
                "drive is connected and powered on. USB drives: try a "
                "different port or re-plugging. If the drive is internal and "
                "definitely connected, your kernel may not have detected it."
            ),
            devices=(),
        )

    if any(is_readable(node) for node in nodes):
        # The node is accessible to us, yet whipper still listed nothing —
        # so it's not a host permission problem. Point at the next suspects.
        return DriveAccessDiagnosis(
            severity=SEVERITY_OK,
            summary="The optical drive is accessible.",
            detail=(
                f"Found {', '.join(nodes)} and your user can read it, so this "
                "isn't a host permission problem. If whipper still lists no "
                "drive, the cause is likely the Distrobox 'ripping' container "
                "not seeing the device, or whipper itself — run Tools → Check "
                "dependencies, and confirm the container can reach the drive."
            ),
            devices=tuple(nodes),
        )

    # A node exists but we can't read it → classic group-permission issue.
    node = nodes[0]
    group = group_of(node) or "cdrom"
    fix = f"sudo usermod -aG {group} $USER"
    if in_group(group):
        detail = (
            f"The drive node {node} is owned by group '{group}', which you "
            "appear to already belong to — but the membership hasn't taken "
            "effect in this session. Log out and back in (or reboot) and try "
            "again. If it still fails, a udev rule may be restricting access."
        )
    else:
        detail = (
            f"The drive node {node} is owned by group '{group}', and your "
            "user isn't a member — so whipper can't open the drive. Add "
            "yourself to the group with the command below, then log out and "
            "back in (or reboot) for it to take effect."
        )
    return DriveAccessDiagnosis(
        severity=SEVERITY_PERMISSION,
        summary=f"No permission to access the optical drive ({node}).",
        detail=detail,
        fix_command=fix,
        devices=tuple(nodes),
    )
