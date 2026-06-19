"""Tests for whipper_gui.parsers.eac_log.

Golden test against the committed EAC baseline (output_reference/EAC_flac/),
plus format-sniffing and degrade-to-empty behaviour.
"""

from __future__ import annotations

from pathlib import Path

from whipper_gui.parsers.eac_log import looks_like_eac_log, parse_eac_copy_crcs

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EAC_BASELINE = (
    _REPO_ROOT / "output_reference" / "EAC_flac" / "eac_baseline_police_classics.log"
)

# Ground truth read off the committed EAC baseline — the bit-perfect reference.
_EXPECTED_CRCS = {
    1: "B0D122E7",
    2: "985AAE32",
    3: "59D352DD",
    4: "60D796AE",
    5: "E0036697",
    6: "B32769D6",
    7: "CCBFF669",
    8: "D723C1B0",
    9: "6F6E4A5F",
    10: "3A33519F",
    11: "56BFC63D",
    12: "D78CEAEF",
    13: "DA6A4DAF",
    14: "787BA2D6",
}


def test_parses_the_committed_eac_baseline() -> None:
    text = _EAC_BASELINE.read_text(encoding="utf-8")
    assert parse_eac_copy_crcs(text) == _EXPECTED_CRCS


def test_looks_like_eac_log_true_for_the_baseline() -> None:
    text = _EAC_BASELINE.read_text(encoding="utf-8")
    assert looks_like_eac_log(text) is True


def test_looks_like_eac_log_false_for_other_formats() -> None:
    assert looks_like_eac_log("Log created by: whipper 0.10.0\n") is False
    assert looks_like_eac_log("cyanrip 0.9.3.1 (abc)\n") is False
    assert looks_like_eac_log("") is False


def test_parse_handles_minimal_block() -> None:
    log = "Exact Audio Copy V1.8\n\nTrack  1\n     Copy CRC ABCD1234\n"
    assert parse_eac_copy_crcs(log) == {1: "ABCD1234"}


def test_lowercase_crc_is_normalised_to_uppercase() -> None:
    log = "Track  7\n     Copy CRC abcd1234\n"
    assert parse_eac_copy_crcs(log) == {7: "ABCD1234"}


def test_copy_crc_without_a_track_header_is_ignored() -> None:
    # A Copy CRC line with no preceding "Track N" can't be attributed.
    assert parse_eac_copy_crcs("     Copy CRC ABCD1234\n") == {}


def test_garbage_yields_empty_mapping() -> None:
    assert parse_eac_copy_crcs("not a log at all\n:::\n") == {}
    assert parse_eac_copy_crcs("") == {}
