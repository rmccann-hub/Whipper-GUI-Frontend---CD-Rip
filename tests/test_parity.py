"""Tests for whipper_gui.parity and the scripts/eac_parity.py CLI.

Covers the cross-format Copy-CRC dispatch (EAC / whipper / cyanrip), the
baseline-vs-candidate comparison (match, mismatch, missing, extra), and a
smoke test of the CLI against the committed EAC baseline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from whipper_gui.parity import compare_logs, decode_log_bytes, track_copy_crcs

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EAC_BASELINE = (
    _REPO_ROOT / "output_reference" / "EAC_flac" / "eac_baseline_police_classics.log"
)


# --- Synthetic log builders (one per format) ------------------------------


def _eac(crcs: dict[int, str]) -> str:
    body = "Exact Audio Copy V1.8 from 15. July 2024\n\n"
    for n, crc in crcs.items():
        body += f"Track  {n}\n\n     Copy CRC {crc}\n\n"
    return body


def _whipper(crcs: dict[int, str]) -> str:
    body = "Log created by: whipper 0.10.0\n\nTracks:\n"
    for n, crc in crcs.items():
        body += f"  {n}:\n    Copy CRC: {crc}\n"
    return body


def _cyanrip(crcs: dict[int, str]) -> str:
    body = "cyanrip 0.9.3.1 (test)\n"
    for n, crc in crcs.items():
        body += f"Track {n} ripped and encoded successfully!\n  EAC CRC32:     {crc}\n"
    return body


# --- track_copy_crcs: format dispatch -------------------------------------


def test_dispatch_reads_eac() -> None:
    assert track_copy_crcs(_eac({1: "AAAA1111", 2: "BBBB2222"})) == {
        1: "AAAA1111",
        2: "BBBB2222",
    }


def test_dispatch_reads_whipper() -> None:
    assert track_copy_crcs(_whipper({1: "aaaa1111"})) == {1: "AAAA1111"}  # upper-cased


def test_dispatch_reads_cyanrip() -> None:
    assert track_copy_crcs(_cyanrip({1: "AAAA1111", 2: "BBBB2222"})) == {
        1: "AAAA1111",
        2: "BBBB2222",
    }


def test_dispatch_on_the_committed_eac_baseline() -> None:
    crcs = track_copy_crcs(_EAC_BASELINE.read_text(encoding="utf-8"))
    assert len(crcs) == 14
    assert crcs[1] == "B0D122E7"
    assert crcs[14] == "787BA2D6"


def test_unknown_text_yields_empty() -> None:
    assert track_copy_crcs("nonsense\n:::\n") == {}


# --- compare_logs ----------------------------------------------------------


def test_identical_is_parity() -> None:
    base = _eac({1: "AAAA1111", 2: "BBBB2222"})
    report = compare_logs(base, base)
    assert report.ok is True
    assert report.matched == report.total == 2


def test_cross_format_same_crcs_is_parity() -> None:
    # The whole point: EAC baseline vs a whipper rip with identical Copy CRCs.
    crcs = {1: "AAAA1111", 2: "BBBB2222"}
    report = compare_logs(_eac(crcs), _whipper(crcs))
    assert report.ok is True
    assert report.matched == 2


def test_one_wrong_crc_fails_and_is_identified() -> None:
    report = compare_logs(
        _eac({1: "AAAA1111", 2: "BBBB2222"}),
        _cyanrip({1: "AAAA1111", 2: "DEADBEEF"}),
    )
    assert report.ok is False
    assert report.matched == 1
    failing = [t.number for t in report.tracks if not t.ok]
    assert failing == [2]


def test_missing_track_in_candidate_fails() -> None:
    report = compare_logs(
        _eac({1: "AAAA1111", 2: "BBBB2222"}), _whipper({1: "AAAA1111"})
    )
    assert report.ok is False
    track2 = next(t for t in report.tracks if t.number == 2)
    assert track2.candidate_crc == ""  # missing
    assert track2.ok is False


def test_extra_track_in_candidate_fails() -> None:
    report = compare_logs(
        _eac({1: "AAAA1111"}), _whipper({1: "AAAA1111", 2: "BBBB2222"})
    )
    assert report.ok is False  # candidate has a track the baseline doesn't
    assert report.extra == (2,)


def test_empty_baseline_is_never_parity() -> None:
    report = compare_logs("nonsense", _whipper({1: "AAAA1111"}))
    assert report.ok is False
    assert report.total == 0


# --- Output-format semantics: WAV and MP3 share the extraction-CRC path -----
#
# The per-track Copy CRC is computed on the EXTRACTED PCM, before (and
# independent of) the output encoder, so ONE parity check covers FLAC, WAV and
# MP3:
#   * WAV is lossless → a WAV rip's Copy CRCs equal the FLAC baseline's, so the
#     committed EAC *FLAC* baseline IS the WAV target — no separate WAV baseline
#     is needed (TASKS.md "WAV (lossless → same Copy CRCs as FLAC)").
#   * MP3 is lossy → the audio is NOT bit-comparable, but the extraction CRC
#     still proves the disc read was bit-perfect; "MP3 parity" = that CRC matches
#     PLUS correct encoder/tag behaviour (the latter verified elsewhere, not here).
# These two tests pin those invariants against the real committed baseline so a
# future regression in the format-dispatch is caught.


def test_wav_rip_parities_against_the_committed_flac_baseline() -> None:
    base = _EAC_BASELINE.read_text(encoding="utf-8")
    flac_crcs = track_copy_crcs(base)
    # A WAV rip of the same disc yields the SAME per-track Copy CRCs (lossless),
    # so a WAV-rip log compares clean against the FLAC baseline.
    wav_rip_log = _whipper(flac_crcs)
    report = compare_logs(base, wav_rip_log)
    assert report.ok is True
    assert report.matched == report.total == 14


def test_mp3_rip_parities_on_extraction_crc() -> None:
    base = _EAC_BASELINE.read_text(encoding="utf-8")
    flac_crcs = track_copy_crcs(base)
    # A cyanrip MP3 rip still logs the per-track EAC CRC32 of the *decoded PCM*;
    # that extraction CRC matches the baseline even though the MP3 audio is lossy.
    mp3_rip_log = _cyanrip(flac_crcs)
    report = compare_logs(base, mp3_rip_log)
    assert report.ok is True
    assert report.matched == 14


# --- decode_log_bytes: EAC writes UTF-16 (regression) ----------------------
#
# Real EAC logs are UTF-16-with-BOM. Reading them as UTF-8 turned every char
# into a replacement char → the parser found zero CRCs → the parity check
# silently reported "NOT parity (0/N)" on a perfectly good rip. Found 2026-06-25
# when a real EAC MP3 log was run through scripts/eac_parity.py.


def test_decode_utf16le_bom() -> None:
    text = "Exact Audio Copy\n     Copy CRC B0D122E7\n"
    raw = b"\xff\xfe" + text.encode("utf-16-le")
    assert decode_log_bytes(raw) == text


def test_decode_utf16be_bom() -> None:
    text = "Exact Audio Copy\n     Copy CRC B0D122E7\n"
    raw = b"\xfe\xff" + text.encode("utf-16-be")
    assert decode_log_bytes(raw) == text


def test_decode_utf8_bom() -> None:
    text = "Log created by: whipper 0.10.0\n"
    assert decode_log_bytes(b"\xef\xbb\xbf" + text.encode("utf-8")) == text


def test_decode_plain_utf8() -> None:
    text = "cyanrip 0.9.3.1\n  EAC CRC32:     AAAA1111\n"
    assert decode_log_bytes(text.encode("utf-8")) == text


def test_decode_bomless_utf16le_heuristic() -> None:
    # No BOM, but NUL-heavy → guessed as UTF-16-LE.
    text = "Exact Audio Copy\n     Copy CRC AAAA1111\n"
    assert decode_log_bytes(text.encode("utf-16-le")) == text


def test_decode_never_raises_on_garbage() -> None:
    # Arbitrary bytes must not blow up (errors="replace").
    assert isinstance(decode_log_bytes(b"\xff\xfe\x00\x01\x80\x81"), str)
    assert isinstance(decode_log_bytes(b"\x80\x81\x82"), str)


def test_utf16_eac_log_parities_after_decode() -> None:
    """The actual bug: an EAC log encoded as UTF-16 must compare clean once
    decoded, instead of every track reading as 'missing'."""
    crcs = {1: "AAAA1111", 2: "BBBB2222"}
    baseline = _eac(crcs)
    eac_utf16_bytes = b"\xff\xfe" + _eac(crcs).encode("utf-16-le")
    candidate = decode_log_bytes(eac_utf16_bytes)
    report = compare_logs(baseline, candidate)
    assert report.ok is True
    assert report.matched == 2
    # And the pre-fix failure mode (decode as UTF-8) would have found nothing:
    assert track_copy_crcs(eac_utf16_bytes.decode("utf-8", errors="replace")) == {}


# --- CLI smoke (scripts/eac_parity.py) ------------------------------------


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "eac_parity_cli", _REPO_ROOT / "scripts" / "eac_parity.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_exit_zero_when_candidate_matches_baseline(capsys) -> None:
    cli = _load_cli()
    # Baseline compared against itself → every CRC matches → exit 0.
    rc = cli.main([str(_EAC_BASELINE), str(_EAC_BASELINE)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PARITY" in out
    assert "Track  1: PASS" in out


def test_cli_exit_one_on_mismatch(tmp_path: Path, capsys) -> None:
    cli = _load_cli()
    bad = tmp_path / "bad.log"
    bad.write_text(_whipper({1: "DEADBEEF"}), encoding="utf-8")  # wrong CRCs
    rc = cli.main([str(_EAC_BASELINE), str(bad)])
    assert rc == 1
    assert "NOT parity" in capsys.readouterr().out


def test_cli_unreadable_baseline_returns_2(tmp_path: Path) -> None:
    cli = _load_cli()
    rc = cli.main([str(tmp_path / "missing.log"), str(_EAC_BASELINE)])
    assert rc == 2
