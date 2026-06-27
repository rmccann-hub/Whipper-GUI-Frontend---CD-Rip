"""Tests for whipper_gui.drive_control.

The runner is injected so we never touch a real drive or container. We assert
the right commands are issued, the kill ordering (whipper before reader), and —
crucially — the regex-safety properties that earlier attempts got wrong:
the whipper pattern must match the whipper CLI but NEVER "whipper-gui", and the
reader kill must not use `-f`.
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace

from whipper_gui import drive_control


class _Recorder:
    """Fake runner: records argv calls, returns a chosen exit code."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv: list[str]) -> SimpleNamespace:
        self.calls.append(argv)
        return SimpleNamespace(returncode=self.returncode)


def _base(argv: list[str]) -> list[str]:
    """argv with the executable reduced to its basename, so assertions don't
    depend on whether a tool resolved to an absolute path."""
    return [os.path.basename(argv[0]), *argv[1:]]


# --- regex safety (the bugs that bit us in real use) ---------------------


def test_whipper_pattern_matches_the_cli() -> None:
    pat = drive_control._WHIPPER_CLI
    assert re.search(pat, "/usr/bin/python3 /usr/bin/whipper cd rip --cdr")
    assert re.search(pat, "whipper drive analyze")
    assert re.search(pat, "whipper offset find")


def test_whipper_pattern_never_matches_the_gui() -> None:
    pat = drive_control._WHIPPER_CLI
    # The GUI must survive a force-stop.
    assert not re.search(pat, "/usr/bin/whipper-gui")
    assert not re.search(pat, "python3 -m whipper_gui")
    assert not re.search(pat, "/opt/whipper-gui-x86_64.AppImage")
    # ...and the pkill command line that *carries* the pattern must not match
    # itself (the "whipper (" self-match bug).
    assert not re.search(pat, "pkill -KILL -f whipper (cd|drive|offset)")


# --- eject_drive ---------------------------------------------------------


def test_eject_success() -> None:
    rec = _Recorder(returncode=0)
    assert drive_control.eject_drive("/dev/sr0", runner=rec) is True
    assert _base(rec.calls[0]) == ["eject", "/dev/sr0"]


def test_eject_busy_returns_false() -> None:
    rec = _Recorder(returncode=1)
    assert drive_control.eject_drive("/dev/sr0", runner=rec) is False


# --- fuser (device-based kill) -------------------------------------------


def test_fuser_kills_device_holders() -> None:
    rec = _Recorder(returncode=0)
    assert drive_control.free_device_holders("/dev/sr0", runner=rec) is True
    assert _base(rec.calls[0]) == ["fuser", "-s", "-k", "/dev/sr0"]


def test_fuser_noop_without_device() -> None:
    rec = _Recorder(returncode=0)
    assert drive_control.free_device_holders("", runner=rec) is False
    assert rec.calls == []


# --- host kill -----------------------------------------------------------


def test_host_kill_targets_whipper_first_then_reader() -> None:
    rec = _Recorder(returncode=0)
    assert drive_control.kill_reader_on_host(runner=rec) is True
    first, second = _base(rec.calls[0]), _base(rec.calls[1])
    # whipper CLI first (anchored, with -f)...
    assert first == ["pkill", "-KILL", "-f", drive_control._WHIPPER_CLI]
    # ...then the reader by name (NO -f).
    assert second == ["pkill", "-KILL", "cdparanoia|cd-paranoia|cdrdao"]
    assert "-f" not in rec.calls[1]


# --- in-container fallback ----------------------------------------------


def test_in_container_uses_distrobox_enter() -> None:
    rec = _Recorder(returncode=0)
    assert drive_control.force_stop_in_container("ripping", runner=rec) is True
    assert _base(rec.calls[0]) == [
        "distrobox",
        "enter",
        "ripping",
        "--",
        "pkill",
        "-KILL",
        "-f",
        drive_control._WHIPPER_CLI,
    ]


# --- force_stop_drive orchestration --------------------------------------


def test_force_stop_host_path_no_container_call() -> None:
    # Host kill succeeds (rc 0) → no distrobox fallback.
    rec = _Recorder(returncode=0)
    msg = drive_control.force_stop_drive("/dev/sr0", runner=rec)
    cmds = [os.path.basename(c[0]) for c in rec.calls]
    assert "distrobox" not in cmds
    assert cmds == ["pkill", "pkill", "fuser", "eject"]
    assert "spin down" in msg.lower()


def test_force_stop_falls_back_to_container_when_host_misses() -> None:
    # rc 1 everywhere → host pkills + fuser match nothing → distrobox fallback.
    rec = _Recorder(returncode=1)
    drive_control.force_stop_drive("/dev/sr0", runner=rec)
    cmds = [os.path.basename(c[0]) for c in rec.calls]
    assert cmds == ["pkill", "pkill", "fuser", "distrobox", "distrobox", "eject"]


def test_force_stop_kills_before_ejecting() -> None:
    rec = _Recorder(returncode=0)
    drive_control.force_stop_drive("/dev/sr0", runner=rec)
    order = [os.path.basename(c[0]) for c in rec.calls]
    assert order.index("pkill") < order.index("eject")


# --- free_drive (scan-stall recovery: kill the reader, do NOT eject) ------


def test_free_drive_kills_but_never_ejects() -> None:
    """A wedged disc *scan* frees the drive without ejecting, so the disc stays
    in for a Rescan — the kill sequence runs but `eject` never does."""
    rec = _Recorder(returncode=0)
    msg = drive_control.free_drive("/dev/sr0", runner=rec)
    cmds = [os.path.basename(c[0]) for c in rec.calls]
    assert "eject" not in cmds
    assert cmds == ["pkill", "pkill", "fuser"]
    assert "free" in msg.lower()


def test_free_drive_falls_back_to_container_when_host_misses() -> None:
    # rc 1 everywhere → host pkills + fuser match nothing → distrobox fallback,
    # still without any eject.
    rec = _Recorder(returncode=1)
    drive_control.free_drive("/dev/sr0", runner=rec)
    cmds = [os.path.basename(c[0]) for c in rec.calls]
    assert cmds == ["pkill", "pkill", "fuser", "distrobox", "distrobox"]
    assert "eject" not in cmds
