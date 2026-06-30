"""Tests for the cyanrip rip-log parser (parsers/cyanrip_log.py).

Sample shapes reconstructed from cyanrip master's format strings
(`cyanrip_log.c::cyanrip_log_track_end` / `cyanrip_log_finish_report`).
A real hardware log (test-plan Test 8 step 6) should be added as a golden
fixture when available. Cases follow docs/testing.md's taxonomy.
"""

from __future__ import annotations

from platterpus.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from platterpus.parsers.rip_log import RipLog

_FULL_LOG = """\
cyanrip 0.9.3.1 (master)
Drive used:     PIONEER BD-RW   BDR-209D (revision 1.10)
System device:  /dev/sr0
Offset:         +667 samples
Paranoia level: full
Frame retries:  10
Outputs:        flac
Disc tracks:    2
DiscID:         xA2hjkk0Jl0gKKtIdYuTje4JTXY-
Album:          Greatest Hits
Album artist:   The Police

Track 1 ripped and encoded successfully!
  Preemphasis:   none detected
    Data bytes:  40841920 (38.95 Mib)
    Frames:      17369
    Duration:    03:51.44
    Samples:     10210480
  EAC CRC32:     A1B2C3D4
  Accurip:       found in database (max confidence: 3)
    Accurip v1:  12345678 (accurately ripped, confidence 3)
    Accurip v2:  9ABCDEF0 (accurately ripped, confidence 2)
  File(s):
    The Police/Greatest Hits/01 - Roxanne.flac

Track 2 ripped and encoded with errors.
  Preemphasis:   present (subcode) (deemphasis applied)
  EAC CRC32:     00FF00FF (after 5 rips)
    Accurip v1:  DEADBEEF (not found, either a new pressing, or bad rip)

Tracks ripped accurately: 1/2
Ripping errors: 3
Ripping finished at 2026-06-09 12:34:56
"""


# --- Easy: full log ---------------------------------------------------------


def test_full_log_parses_header_and_finish() -> None:
    log = parse_cyanrip_log(_FULL_LOG)
    assert log.log_creator == "cyanrip 0.9.3.1"
    assert log.creation_date == "2026-06-09 12:34:56"
    assert log.ripping_info.drive.startswith("PIONEER")
    assert log.ripping_info.read_offset_correction == 667
    assert log.accuraterip_summary == "1/2 tracks ripped accurately (AccurateRip)"
    assert log.health_status == "3 ripping errors"


def test_full_log_parses_tracks() -> None:
    log = parse_cyanrip_log(_FULL_LOG)
    assert len(log.tracks) == 2

    one = log.tracks[0]
    assert one.number == 1
    assert one.status == "ripped successfully"
    assert one.copy_crc == "A1B2C3D4"
    assert one.test_crc == ""  # cyanrip has no test+copy dual read
    assert one.pre_emphasis is False
    assert one.accuraterip_v1 is not None
    assert one.accuraterip_v1.confidence == 3
    assert one.accuraterip_v1.local_crc == "12345678"
    assert one.accuraterip_v2 is not None
    assert one.accuraterip_v2.confidence == 2

    # A clean single-pass track records no explicit rip count.
    assert one.rip_count is None
    assert one.accuraterip_offset is None

    two = log.tracks[1]
    assert two.status == "ripped with errors"
    assert two.copy_crc == "00FF00FF"  # "(after N rips)" suffix tolerated
    assert two.rip_count == 5  # ...and the count is captured from that suffix
    assert two.pre_emphasis is True
    assert two.accuraterip_v1 is not None
    assert two.accuraterip_v1.confidence is None  # not found → no confidence
    assert two.accuraterip_v2 is None


# --- The -Z secure-rerip extras (offset variant, partial summary, …) ---------

# A marginal-disc shape: a track that only matched the +450-frame offset
# variant after several re-reads, plus the finish-report extras cyanrip writes
# under -Z. Mirrors the real Police "Classics" rip (tracks 3 & 5).
_MARGINAL_LOG = """\
cyanrip 0.9.3 (release)
Offset:         +667 samples
Total time:     00:59:42.354

Track 3 ripped and encoded successfully!
  Preemphasis:   none detected
  EAC CRC32:     7E50D2FA (after 5 rips)
  Accurip:       found in database
    Accurip 450: BF62B1DA (matches Accurip DB, confidence 200, track is partially accurately ripped)

Tracks ripped accurately: 12/14
Tracks ripped partially accurately: 2/2

Paranoia status counts:
  READ:          71948
  VERIFY:        11098
  FIXUP_ATOM:    193
  OVERLAP:       1677

Ripping errors: 0
Ripping finished at 2026-06-29T21:36:39
"""


def test_disc_duration_captured_from_start_report() -> None:
    log = parse_cyanrip_log(_MARGINAL_LOG)
    # The disc's AUDIO length — not the rip wall-clock (that lives in the JSON
    # report's timing section, measured by the GUI).
    assert log.disc_duration == "00:59:42.354"


def test_rip_count_captured_from_after_n_rips() -> None:
    log = parse_cyanrip_log(_MARGINAL_LOG)
    assert log.tracks[0].rip_count == 5


def test_offset_variant_match_is_captured_but_not_a_plain_match() -> None:
    log = parse_cyanrip_log(_MARGINAL_LOG)
    track = log.tracks[0]
    # The "Accurip 450" offset-pressing variant is recorded as data...
    assert track.accuraterip_offset is not None
    assert track.accuraterip_offset.version == 450
    assert track.accuraterip_offset.confidence == 200
    assert track.accuraterip_offset.local_crc == "BF62B1DA"
    # ...but it is NOT a plain v1/v2 match, so the shared "verified" rule
    # (confidence>=1 on v1/v2) does not over-claim it as accurately ripped.
    from platterpus.parsers.rip_log import track_accuraterip_verified

    assert track.accuraterip_v1 is None
    assert track.accuraterip_v2 is None
    assert track_accuraterip_verified(track) is False


def test_partial_accurate_summary_and_paranoia_counts() -> None:
    log = parse_cyanrip_log(_MARGINAL_LOG)
    assert "2/2" in log.partially_accurate_summary
    assert log.paranoia_counts == {
        "READ": 71948,
        "VERIFY": 11098,
        "FIXUP_ATOM": 193,
        "OVERLAP": 1677,
    }


def test_paranoia_block_ends_cleanly_before_finish_lines() -> None:
    # The block must not swallow the "Ripping errors:" / "finished at" lines
    # that follow it (they don't match the indented KEY: N shape, so the block
    # closes). Health + date still parse.
    log = parse_cyanrip_log(_MARGINAL_LOG)
    assert log.health_status == "No errors occurred"
    assert log.creation_date == "2026-06-29T21:36:39"


# --- Medium: negative offset, zero errors normalize like whipper ------------


def test_negative_offset_and_clean_finish() -> None:
    log = parse_cyanrip_log(
        "cyanrip 0.9.3.1 (master)\nOffset:         -12 samples\nRipping errors: 0\n"
    )
    assert log.ripping_info.read_offset_correction == -12
    # Normalized to whipper's phrasing so downstream checks are shared.
    assert log.health_status == "No errors occurred"


def test_data_track_recorded_not_crashed() -> None:
    log = parse_cyanrip_log("cyanrip 0.9.3.1 (x)\nTrack 9 is data:\n  Frames: 1\n")
    assert log.tracks[0].number == 9
    assert log.tracks[0].status == "data track (skipped)"


# --- Hard: truncated log (crash mid-rip) -------------------------------------


def test_truncated_log_keeps_completed_tracks() -> None:
    truncated = _FULL_LOG.split("Track 2")[0]  # ends after track 1's block
    log = parse_cyanrip_log(truncated)
    assert len(log.tracks) == 1
    assert log.tracks[0].copy_crc == "A1B2C3D4"
    assert log.health_status == ""  # finish report never written


# --- Edge / unexpected -------------------------------------------------------


def test_empty_and_garbage_inputs_degrade_to_empty() -> None:
    assert parse_cyanrip_log("") == RipLog()
    garbage = parse_cyanrip_log("::::\nTrack x ripped\nEAC CRC32 nope\n")
    assert garbage.tracks == ()


def test_whipper_log_is_not_detected_as_cyanrip() -> None:
    whipper_text = "Log created by: whipper 0.10.0\nRipping phase information:\n"
    assert looks_like_cyanrip_log(whipper_text) is False
    assert looks_like_cyanrip_log(_FULL_LOG) is True
    assert looks_like_cyanrip_log("") is False
    assert looks_like_cyanrip_log("\n\n  \n") is False
