"""Tests for whipper_gui.parsers.drive_list.

Fixtures live in tests/fixtures/; each fixture is hand-written to match
the format documented in whipper-team/whipper master (command/drive.py).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from whipper_gui.parsers.drive_list import DriveDescriptor, parse_drive_list

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_single_drive_fully_configured() -> None:
    drives = parse_drive_list(_read("drive_list_pioneer.txt"))

    assert len(drives) == 1
    d = drives[0]
    assert d.device == "/dev/sr0"
    assert d.vendor == "PIONEER"
    assert d.model == "BD-RW  BDR-209D"  # double space preserved
    assert d.release == "1.51"
    assert d.read_offset == 667
    assert d.cache_defeat is True


def test_parse_single_drive_unconfigured_properties_become_none() -> None:
    drives = parse_drive_list(_read("drive_list_pioneer_unconfigured.txt"))

    assert len(drives) == 1
    assert drives[0].read_offset is None
    assert drives[0].cache_defeat is None


def test_parse_empty_when_no_drives() -> None:
    assert parse_drive_list(_read("drive_list_empty.txt")) == []


def test_parse_two_drives() -> None:
    drives = parse_drive_list(_read("drive_list_two_drives.txt"))

    assert len(drives) == 2
    assert drives[0].device == "/dev/sr0"
    assert drives[0].read_offset == 667
    assert drives[1].device == "/dev/sr1"
    assert drives[1].cache_defeat is False


def test_parse_handles_completely_empty_input() -> None:
    assert parse_drive_list("") == []


def test_parse_yes_no_cache_values() -> None:
    """Whipper may emit Yes/No variants in some builds; we accept both."""
    output = (
        "drive: /dev/sr0, vendor: ASUS, model: SDRW-08D2S-U, release: D102\n"
        "       Can defeat audio cache: Yes\n"
    )
    drives = parse_drive_list(output)
    assert drives[0].cache_defeat is True


def test_drive_descriptor_is_frozen() -> None:
    d = DriveDescriptor(device="/dev/sr0", vendor="x", model="y", release="z")
    with pytest.raises(FrozenInstanceError):
        d.device = "/dev/sr1"  # type: ignore[misc]
