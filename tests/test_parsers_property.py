"""Property-based tests for the three whipper-output parsers.

These complement the example-based `test_parsers_*` files. Example tests
prove the parsers handle the *known* shapes; these prove they uphold a
hard invariant across a huge space of *unknown* inputs:

    A parser must NEVER raise on arbitrary text — it degrades to empty /
    default values instead.

That invariant is exactly what a real-hardware regression needs: whipper
is an unmaintained tool whose output can drift, and the GUI calls these
parsers at startup (drive list) and after a rip (log). A parser that
throws on unexpected bytes is what makes the whole window vanish — see
the startup-resilience fix. Hypothesis generates hundreds of adversarial
inputs and shrinks any failure to a minimal reproducer.

Hypothesis docs: https://hypothesis.readthedocs.io/
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from whipper_gui.parsers.cd_info import DiscInfo, parse_cd_info
from whipper_gui.parsers.cyanrip_info import parse_cyanrip_info
from whipper_gui.parsers.cyanrip_log import parse_cyanrip_log
from whipper_gui.parsers.drive_list import DriveDescriptor, parse_drive_list
from whipper_gui.parsers.eac_log import parse_eac_copy_crcs
from whipper_gui.parsers.rip_log import RipLog, parse_rip_log

# `deadline=None`: the parsers are fast, but CI runners are noisy and we
# don't want a timing blip to fail a correctness test.
_SETTINGS = settings(max_examples=300, deadline=None)


# --- A vocabulary of plausible-but-mangled whipper lines ------------------
#
# Pure st.text() is great for "never crash", but most random strings miss
# the parser's interesting branches. This strategy mixes real whipper line
# shapes (with random fills) and garbage, so the state machines actually
# get exercised on near-miss input — the "unexpected" tier of cases.

_FRAGMENTS = st.sampled_from(
    [
        "drive: /dev/sr0, vendor: ACME, model: X, release: 1.0",
        "drive: , vendor: , model: , release: ",  # empty-ish fields
        "       Configured read offset: 667",
        "       Configured read offset: not-a-number",  # bad int
        "       Can defeat audio cache: True",
        "       Can defeat audio cache: maybe",  # unrecognized bool
        "CDDB disc id: 940A6A0B",
        "MusicBrainz disc id wzr8h2ssXg4",
        "Disc duration: 01:02:08.026, 16 audio tracks",
        "Disc duration: ?, audio tracks",  # no number
        "Tracks:",
        "  1:",
        "    Peak level: 0.9",
        "    Peak level: not-a-float",  # bad float
        "    Extraction speed: 8.0 X",
        "    Extraction quality: 100.00 %",
        "    AccurateRip v1:",
        "      Confidence: 5",
        "      Confidence: lots",  # bad int
        "Log created by: whipper 0.10.0",
        "SHA-256 hash: deadbeef",
        # cyanrip -I report shapes (exercise the cyanrip_info parser).
        "Disc tracks:    16",
        "Disc tracks:    many",  # bad int
        "DiscID:         xA2hjkk0Jl0gKKtIdYuTje4JTXY-",
        "CDDB ID:        c50a780f",
        "MusicBrainz URL:",
        "https://musicbrainz.org/cdtoc/attach?id=x",
        "(null)",  # printf'd NULL after the URL label
        # cyanrip log shapes (exercise the cyanrip_log parser).
        "Track 5 ripped and encoded successfully!",
        "Track 5 ripped and encoded with errors.",
        "  EAC CRC32:     A1B2C3D4 (after 2 rips)",
        "    Accurip v1:  12345678 (accurately ripped, confidence 3)",
        "    Accurip v1:  12345678 (confidence lots)",  # bad int
        "Offset:         +667 samples",
        "Tracks ripped accurately: 1/2",
        "Ripping errors: many",  # bad int
        # EAC log shapes (exercise the eac_log parser).
        "Exact Audio Copy V1.8 from 15. July 2024",
        "Track  1",
        "Track  not-a-number",  # bad track number
        "     Copy CRC B0D122E7",
        "     Copy CRC nothex!!",  # not 8 hex digits
        "     Test CRC B0D122E7",
        ":::::",  # degenerate colons
        "",  # blank line
        "\t\t\t",  # whitespace only
    ]
)

_noisy_text = st.lists(_FRAGMENTS, max_size=40).map("\n".join)

# The full input strategy: either fully-random text or noisy whipper-ish text.
_any_text = st.one_of(st.text(max_size=2000), _noisy_text)


# --- Invariant 1: never raises, always returns the right type -------------


@_SETTINGS
@given(_any_text)
def test_parse_drive_list_never_raises(text: str) -> None:
    result = parse_drive_list(text)
    assert isinstance(result, list)
    for drive in result:
        assert isinstance(drive, DriveDescriptor)
        # Declared optional-numeric fields hold their declared types.
        assert drive.read_offset is None or isinstance(drive.read_offset, int)
        assert drive.cache_defeat is None or isinstance(drive.cache_defeat, bool)
        assert isinstance(drive.device, str)


@_SETTINGS
@given(_any_text)
def test_parse_cd_info_never_raises(text: str) -> None:
    result = parse_cd_info(text)
    assert isinstance(result, DiscInfo)
    assert isinstance(result.num_tracks, int)
    assert result.num_tracks >= 0


@_SETTINGS
@given(_any_text)
def test_parse_cyanrip_info_never_raises(text: str) -> None:
    result = parse_cyanrip_info(text)
    assert isinstance(result, DiscInfo)
    assert isinstance(result.num_tracks, int)
    assert result.num_tracks >= 0


@_SETTINGS
@given(_any_text)
def test_parse_cyanrip_log_never_raises(text: str) -> None:
    result = parse_cyanrip_log(text)
    assert isinstance(result, RipLog)
    for track in result.tracks:
        assert isinstance(track.number, int)
        for ar in (track.accuraterip_v1, track.accuraterip_v2):
            if ar is not None:
                assert ar.confidence is None or isinstance(ar.confidence, int)


@_SETTINGS
@given(_any_text)
def test_parse_rip_log_never_raises(text: str) -> None:
    result = parse_rip_log(text)
    assert isinstance(result, RipLog)
    assert isinstance(result.tracks, tuple)
    for track in result.tracks:
        assert isinstance(track.number, int)
        # Optional numerics keep their declared types or stay None.
        assert track.peak_level is None or isinstance(track.peak_level, float)
        assert track.extraction_speed is None or isinstance(
            track.extraction_speed, float
        )
        for ar in (track.accuraterip_v1, track.accuraterip_v2):
            if ar is not None:
                assert ar.confidence is None or isinstance(ar.confidence, int)


@_SETTINGS
@given(_any_text)
def test_parse_eac_copy_crcs_never_raises(text: str) -> None:
    result = parse_eac_copy_crcs(text)
    assert isinstance(result, dict)
    for number, crc in result.items():
        assert isinstance(number, int)
        # Only 8-hex-digit Copy CRCs are captured, always upper-cased.
        assert isinstance(crc, str) and len(crc) == 8
        assert crc == crc.upper()


# --- Invariant 2: a well-formed drive block round-trips -------------------
#
# If we synthesise a *valid* drive block, the parser must recover its
# fields exactly. This guards against over-eager "degrade to empty"
# behaviour swallowing good data.

_word = st.from_regex(r"[A-Za-z0-9 ]{1,12}", fullmatch=True)
_device = st.from_regex(r"/dev/sr[0-9]", fullmatch=True)
_release = st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True)


@_SETTINGS
@given(
    device=_device,
    vendor=_word,
    model=_word,
    release=_release,
    offset=st.integers(min_value=-2000, max_value=2000),
    cache=st.booleans(),
)
def test_drive_block_round_trips(
    device: str,
    vendor: str,
    model: str,
    release: str,
    offset: int,
    cache: bool,
) -> None:
    # vendor/model are .strip()'d by the parser; only compare meaningfully
    # when they survive stripping.
    block = (
        f"drive: {device}, vendor: {vendor}, model: {model}, release: {release}\n"
        f"       Configured read offset: {offset}\n"
        f"       Can defeat audio cache: {cache}\n"
    )
    drives = parse_drive_list(block)
    assert len(drives) == 1
    d = drives[0]
    assert d.device == device
    assert d.vendor == vendor.strip()
    assert d.model == model.strip()
    assert d.release == release
    assert d.read_offset == offset
    assert d.cache_defeat is cache


# --- Invariant 3: a metamorphic property ----------------------------------
#
# Concatenating N independent single-drive blocks yields exactly N drives.
# (Whipper prints one block per call, but multi-drive output is on the
# roadmap; this pins the accumulator's flush logic.)


@_SETTINGS
@given(n=st.integers(min_value=0, max_value=8))
def test_concatenated_drive_blocks_count(n: int) -> None:
    block = "drive: /dev/sr0, vendor: ACME, model: X, release: 1.0\n"
    drives = parse_drive_list(block * n)
    assert len(drives) == n
