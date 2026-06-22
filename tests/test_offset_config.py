"""Tests for whipper_gui.offset_config."""

from __future__ import annotations

from pathlib import Path

from whipper_gui.offset_config import (
    WhipperConfOffset,
    describe_conf_offsets,
    is_offset_configured,
    read_drive_offsets,
    whipper_conf_has_offset,
)

_CONF_WITH_OFFSET = """\
[main]
path = something

[drive:PIONEER :BD-RW   BDR-209D:1.51]
defeats_cache = True
read_offset = 667
"""

_CONF_NO_OFFSET = """\
[drive:PIONEER :BD-RW   BDR-209D:1.51]
defeats_cache = True
"""

_CONF_COMMENTED_OFFSET = """\
[drive:Foo]
# read_offset = 6
defeats_cache = True
"""


def _write(tmp_path: Path, text: str) -> Path:
    conf = tmp_path / "whipper.conf"
    conf.write_text(text, encoding="utf-8")
    return conf


def test_has_offset_true_when_present(tmp_path: Path) -> None:
    assert whipper_conf_has_offset(_write(tmp_path, _CONF_WITH_OFFSET)) is True


def test_has_offset_handles_negative(tmp_path: Path) -> None:
    conf = _write(tmp_path, "[drive:X]\nread_offset = -12\n")
    assert whipper_conf_has_offset(conf) is True


def test_has_offset_false_when_absent(tmp_path: Path) -> None:
    assert whipper_conf_has_offset(_write(tmp_path, _CONF_NO_OFFSET)) is False


def test_has_offset_ignores_commented_line(tmp_path: Path) -> None:
    assert whipper_conf_has_offset(_write(tmp_path, _CONF_COMMENTED_OFFSET)) is False


def test_has_offset_false_when_file_missing(tmp_path: Path) -> None:
    assert whipper_conf_has_offset(tmp_path / "nope.conf") is False


def test_is_configured_true_when_override_on(tmp_path: Path) -> None:
    # Override short-circuits — whipper.conf is irrelevant.
    assert is_offset_configured(True, tmp_path / "missing.conf") is True


def test_is_configured_true_from_conf(tmp_path: Path) -> None:
    conf = _write(tmp_path, _CONF_WITH_OFFSET)
    assert is_offset_configured(False, conf) is True


def test_is_configured_false_when_neither(tmp_path: Path) -> None:
    conf = _write(tmp_path, _CONF_NO_OFFSET)
    assert is_offset_configured(False, conf) is False


# --- read_drive_offsets / describe_conf_offsets ----------------------------


def test_read_drive_offsets_parses_value_and_drive(tmp_path: Path) -> None:
    offsets = read_drive_offsets(_write(tmp_path, _CONF_WITH_OFFSET))
    assert offsets == [
        WhipperConfOffset(drive="PIONEER :BD-RW   BDR-209D:1.51", offset=667)
    ]


def test_read_drive_offsets_url_decodes_drive_id(tmp_path: Path) -> None:
    conf = _write(tmp_path, "[drive:PIONEER%20BD-RW%20BDR-209D]\nread_offset = 667\n")
    assert read_drive_offsets(conf)[0].drive == "PIONEER BD-RW BDR-209D"


def test_read_drive_offsets_multiple_drives(tmp_path: Path) -> None:
    conf = _write(
        tmp_path,
        "[drive:A]\nread_offset = 6\n[drive:B]\nread_offset = -12\n",
    )
    assert read_drive_offsets(conf) == [
        WhipperConfOffset(drive="A", offset=6),
        WhipperConfOffset(drive="B", offset=-12),
    ]


def test_read_drive_offsets_ignores_non_drive_section(tmp_path: Path) -> None:
    # A read_offset outside a [drive:...] section is not a per-drive offset.
    conf = _write(tmp_path, "[main]\nread_offset = 99\n")
    assert read_drive_offsets(conf) == []


def test_read_drive_offsets_missing_file(tmp_path: Path) -> None:
    assert read_drive_offsets(tmp_path / "nope.conf") == []


def test_describe_conf_offsets_none(tmp_path: Path) -> None:
    assert describe_conf_offsets(_write(tmp_path, _CONF_NO_OFFSET)) == "none set"


def test_describe_conf_offsets_formats(tmp_path: Path) -> None:
    out = describe_conf_offsets(_write(tmp_path, _CONF_WITH_OFFSET))
    assert "PIONEER" in out and "+667" in out
