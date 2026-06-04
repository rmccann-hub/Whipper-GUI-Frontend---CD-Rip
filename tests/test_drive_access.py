"""Tests for whipper_gui.drive_access.

The public diagnose function takes injectable probes, so we simulate
every system state without real hardware or root.
"""

from __future__ import annotations

import grp
import pwd
from types import SimpleNamespace

import pytest

from whipper_gui import drive_access as da
from whipper_gui.drive_access import (
    SEVERITY_NO_DEVICE,
    SEVERITY_OK,
    SEVERITY_PERMISSION,
    diagnose_drive_access,
)


def test_no_device_node() -> None:
    d = diagnose_drive_access(list_nodes=lambda: [])
    assert d.severity == SEVERITY_NO_DEVICE
    assert d.actionable is False
    assert d.fix_command is None
    assert "No optical drive" in d.summary


def test_readable_node_reports_ok() -> None:
    d = diagnose_drive_access(
        list_nodes=lambda: ["/dev/sr0"],
        is_readable=lambda p: True,
    )
    assert d.severity == SEVERITY_OK
    assert d.actionable is False
    assert "/dev/sr0" in d.detail
    assert d.devices == ("/dev/sr0",)


def test_unreadable_node_not_in_group_is_actionable() -> None:
    d = diagnose_drive_access(
        list_nodes=lambda: ["/dev/sr0"],
        is_readable=lambda p: False,
        group_of=lambda p: "cdrom",
        in_group=lambda g: False,
    )
    assert d.severity == SEVERITY_PERMISSION
    assert d.actionable is True
    assert d.fix_command == "sudo usermod -aG cdrom $USER"
    assert "isn't a member" in d.detail


def test_unreadable_node_already_in_group_suggests_relogin() -> None:
    d = diagnose_drive_access(
        list_nodes=lambda: ["/dev/sr0"],
        is_readable=lambda p: False,
        group_of=lambda p: "optical",
        in_group=lambda g: True,
    )
    assert d.severity == SEVERITY_PERMISSION
    assert d.fix_command == "sudo usermod -aG optical $USER"
    assert "Log out" in d.detail or "log out" in d.detail


def test_unknown_group_falls_back_to_cdrom() -> None:
    d = diagnose_drive_access(
        list_nodes=lambda: ["/dev/sr0"],
        is_readable=lambda p: False,
        group_of=lambda p: None,
        in_group=lambda g: False,
    )
    assert d.fix_command == "sudo usermod -aG cdrom $USER"


# --- default probe implementations (exercised directly, monkeypatched) -----


def test_find_device_nodes_globs_symlinks_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # /dev/sr0 from the glob, and /dev/cdrom symlink resolving onto /dev/sr0:
    # the result must dedupe to a single node.
    monkeypatch.setattr(da.glob, "glob", lambda pat: ["/dev/sr0"])
    monkeypatch.setattr(da.os.path, "exists", lambda p: p == "/dev/cdrom")
    monkeypatch.setattr(da.os.path, "realpath", lambda p: "/dev/sr0")
    assert da._find_device_nodes() == ["/dev/sr0"]


def test_is_readable_wraps_os_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da.os, "access", lambda path, mode: True)
    assert da._is_readable("/dev/sr0") is True


def test_group_of_node_resolves_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(da.os, "stat", lambda p: SimpleNamespace(st_gid=44))
    monkeypatch.setattr(grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="cdrom"))
    assert da._group_of_node("/dev/sr0") == "cdrom"


def test_group_of_node_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_p: str) -> object:
        raise OSError("no such node")

    monkeypatch.setattr(da.os, "stat", boom)
    assert da._group_of_node("/dev/sr0") is None


def test_in_group_true_via_getgroups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grp, "getgrnam", lambda n: SimpleNamespace(gr_gid=44))
    monkeypatch.setattr(da.os, "getgroups", lambda: [44, 100])
    assert da._in_group("cdrom") is True


def test_in_group_false_for_unknown_group(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_n: str) -> object:
        raise KeyError(_n)

    monkeypatch.setattr(grp, "getgrnam", boom)
    assert da._in_group("nope") is False


def test_in_group_true_via_primary_group(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not in getgroups(), but it's the user's primary group → still a member.
    monkeypatch.setattr(grp, "getgrnam", lambda n: SimpleNamespace(gr_gid=44))
    monkeypatch.setattr(da.os, "getgroups", lambda: [100])
    monkeypatch.setattr(da.os, "getuid", lambda: 1000)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_gid=44))
    assert da._in_group("cdrom") is True


def test_in_group_false_when_pwd_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grp, "getgrnam", lambda n: SimpleNamespace(gr_gid=44))
    monkeypatch.setattr(da.os, "getgroups", lambda: [100])
    monkeypatch.setattr(da.os, "getuid", lambda: 1000)

    def boom(_uid: int) -> object:
        raise KeyError(_uid)

    monkeypatch.setattr(pwd, "getpwuid", boom)
    assert da._in_group("cdrom") is False
