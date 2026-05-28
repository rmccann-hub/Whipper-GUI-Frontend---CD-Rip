"""Tests for whipper_gui.parsers.rip_log.

Primary fixture (`rip_log_real_whipper_0_7.log`) is whipper-team/whipper's
own test fixture from master — i.e., a real log produced by whipper,
not hand-authored. Source:
https://github.com/whipper-team/whipper/blob/master/whipper/test/test_result_logger.log
"""

from __future__ import annotations

from pathlib import Path

from whipper_gui.parsers.rip_log import (
    AccurateRipResult,
    RipLog,
    RippingInfo,
    TrackResult,
    parse_rip_log,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_LOG = "rip_log_real_whipper_0_7.log"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


# --- Top-level metadata ---------------------------------------------------


def test_parse_log_creator_and_creation_date() -> None:
    log = parse_rip_log(_read(REAL_LOG))
    assert log.log_creator.startswith("whipper 0.7.4")
    assert log.creation_date == "2019-10-26T14:25:02Z"


def test_parse_sha256_hash() -> None:
    log = parse_rip_log(_read(REAL_LOG))
    assert log.sha256_hash.startswith("2B176D8C")
    assert len(log.sha256_hash) == 64  # SHA-256 = 64 hex chars


# --- Ripping info (the EAC-equivalent archival block) --------------------


def test_parse_ripping_info_drive() -> None:
    info = parse_rip_log(_read(REAL_LOG)).ripping_info
    assert "HL-DT-ST" in info.drive
    assert "WH14NS40" in info.drive
    assert "revision 1.03" in info.drive


def test_parse_ripping_info_extraction_engine() -> None:
    info = parse_rip_log(_read(REAL_LOG)).ripping_info
    assert "cdparanoia" in info.extraction_engine


def test_parse_ripping_info_cache_and_offset() -> None:
    info = parse_rip_log(_read(REAL_LOG)).ripping_info
    assert info.defeat_audio_cache is True
    assert info.read_offset_correction == 6


def test_parse_ripping_info_overread_and_gap() -> None:
    info = parse_rip_log(_read(REAL_LOG)).ripping_info
    assert info.overread_lead_out is False
    assert "cdrdao" in info.gap_detection
    assert info.cd_r_detected is False


# --- Tracks ---------------------------------------------------------------


def test_parse_track_count() -> None:
    log = parse_rip_log(_read(REAL_LOG))
    assert len(log.tracks) == 2


def test_parse_track_one_basic_fields() -> None:
    track = parse_rip_log(_read(REAL_LOG)).tracks[0]
    assert track.number == 1
    assert "Three Little Birds.flac" in track.filename
    assert track.peak_level is not None
    assert abs(track.peak_level - 0.90036) < 1e-6
    # Pre-emphasis is empty in this fixture -> None (we can't claim
    # either way).
    assert track.pre_emphasis is None
    assert track.extraction_speed == 7.0
    assert track.extraction_quality == 100.0
    assert track.test_crc == "0025D726"
    assert track.copy_crc == "0025D726"
    assert track.status == "Copy OK"


def test_parse_track_one_accuraterip_v1() -> None:
    ar = parse_rip_log(_read(REAL_LOG)).tracks[0].accuraterip_v1
    assert ar is not None
    assert ar.version == 1
    assert ar.result == "Found, exact match"
    assert ar.confidence == 14
    assert ar.local_crc == "95E6A189"
    assert ar.remote_crc == "95E6A189"


def test_parse_track_one_accuraterip_v2() -> None:
    ar = parse_rip_log(_read(REAL_LOG)).tracks[0].accuraterip_v2
    assert ar is not None
    assert ar.version == 2
    assert ar.confidence == 11
    assert ar.local_crc == "113FA733"


def test_parse_track_two_distinct_from_track_one() -> None:
    """Track 2 must not bleed track 1's data — header transitions correctly."""
    tracks = parse_rip_log(_read(REAL_LOG)).tracks
    assert tracks[1].number == 2
    assert tracks[1].test_crc == "F77C14CB"  # different from track 1
    assert tracks[1].extraction_speed == 7.7  # different from track 1


# --- Status section -------------------------------------------------------


def test_parse_status_summary_and_health() -> None:
    log = parse_rip_log(_read(REAL_LOG))
    assert log.accuraterip_summary == "All tracks accurately ripped"
    assert log.health_status == "No errors occurred"


# --- Defensive edge cases -------------------------------------------------


def test_parse_empty_input_returns_empty_log() -> None:
    log = parse_rip_log("")
    assert log.tracks == ()
    assert log.log_creator == ""
    assert log.sha256_hash == ""
    assert log.ripping_info == RippingInfo()


def test_parse_truncated_log_without_status_section() -> None:
    """A rip killed mid-write should still parse partial output."""
    text = (
        "Log created by: whipper 0.10.0\n"
        "\n"
        "Tracks:\n"
        "  1:\n"
        "    Filename: track01.flac\n"
        "    Peak level: 0.5\n"
        "    Test CRC: AAAABBBB\n"
        "    Copy CRC: AAAABBBB\n"
        "    Status: Copy OK\n"
    )
    log = parse_rip_log(text)
    assert len(log.tracks) == 1
    assert log.tracks[0].number == 1
    assert log.tracks[0].test_crc == "AAAABBBB"
    assert log.accuraterip_summary == ""


def test_parse_handles_ar_missing_from_database() -> None:
    """When a track isn't in AccurateRip, the Result line says so and
    the CRC fields are typically blank. We should report this state
    correctly rather than crashing."""
    text = (
        "Tracks:\n"
        "  1:\n"
        "    Filename: track01.flac\n"
        "    Test CRC: AAAABBBB\n"
        "    Copy CRC: AAAABBBB\n"
        "    AccurateRip v2:\n"
        "      Result: Track not present in AccurateRip database\n"
        "      Confidence: 0\n"
        "      Local CRC:\n"
        "      Remote CRC:\n"
        "    Status: Copy OK\n"
    )
    log = parse_rip_log(text)
    ar = log.tracks[0].accuraterip_v2
    assert ar is not None
    assert ar.result.startswith("Track not present")
    assert ar.confidence == 0
    assert ar.local_crc is None
    assert ar.remote_crc is None


def test_track_result_is_frozen() -> None:
    t = TrackResult(number=1)
    try:
        t.number = 2  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass


def test_ripping_info_is_frozen() -> None:
    info = RippingInfo()
    try:
        info.drive = "x"  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass


def test_accuraterip_result_is_frozen() -> None:
    ar = AccurateRipResult(version=1)
    try:
        ar.confidence = 5  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except Exception:
        pass
