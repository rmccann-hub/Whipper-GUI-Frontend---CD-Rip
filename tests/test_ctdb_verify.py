# SPDX-License-Identifier: GPL-3.0-only
"""Tests for whipper_gui.ctdb.verify + crc — the verdict logic (fakes only)."""

from __future__ import annotations

import zlib
from pathlib import Path

from whipper_gui.adapters.ctdb_client import (
    CTDBClient,
    CtdbEntry,
    CtdbLookupError,
    CtdbLookupResult,
)
from whipper_gui.ctdb import crc as crc_mod
from whipper_gui.ctdb.toc import SAMPLES_PER_SECTOR, DiscToc
from whipper_gui.ctdb.verify import CtdbVerifyResult, Verdict, verify_rip

# --- crc -------------------------------------------------------------------


def test_ctdb_crc_offset0_is_zlib_crc32() -> None:
    pcm = b"\x00\x01\x02\x03" * 10
    assert crc_mod.ctdb_crc_offset0(pcm) == (zlib.crc32(pcm) & 0xFFFFFFFF)


def test_offset_range_constant() -> None:
    assert crc_mod.CTDB_OFFSET_RANGE == 2939


# --- fakes -----------------------------------------------------------------


class _FakeClient(CTDBClient):
    def __init__(self, result: CtdbLookupResult | Exception) -> None:
        self._result = result

    def lookup(self, toc: DiscToc) -> CtdbLookupResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


_FLACS = [Path("01.flac"), Path("02.flac")]
# Each "file" decodes to one sector of silence so TOC math is happy.
_PCM = {p: b"\x00" * (SAMPLES_PER_SECTOR * 4) for p in _FLACS}


def _probe(_: Path) -> int:
    return SAMPLES_PER_SECTOR


def _decoder(path: Path) -> bytes:
    return _PCM[path]


def _whole_disc_crc() -> int:
    return zlib.crc32(b"".join(_PCM[p] for p in _FLACS)) & 0xFFFFFFFF


# --- verdicts --------------------------------------------------------------


def test_not_in_database() -> None:
    client = _FakeClient(CtdbLookupResult(entries=()))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.NOT_IN_DATABASE


def test_match_when_crc_equals_entry() -> None:
    entry = CtdbEntry(crc=_whole_disc_crc(), confidence=42)
    client = _FakeClient(CtdbLookupResult(entries=(entry,)))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.MATCH
    assert res.confidence == 42
    assert res.our_crc == _whole_disc_crc()


def test_match_is_flagged_experimental_until_validated() -> None:
    entry = CtdbEntry(crc=_whole_disc_crc(), confidence=1)
    client = _FakeClient(CtdbLookupResult(entries=(entry,)))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=_probe)
    # CRC_VALIDATED is False until hardware confirms it (KDD-16).
    assert res.crc_validated is False
    assert res.trustworthy is False
    assert "experimental" in res.message.lower()


def test_no_match_when_crc_differs() -> None:
    entry = CtdbEntry(crc=0xDEADBEEF, confidence=5)
    client = _FakeClient(CtdbLookupResult(entries=(entry,)))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.NO_MATCH
    assert res.confidence == 5  # best confidence still surfaced


def test_lookup_error_is_a_verdict_not_a_raise() -> None:
    client = _FakeClient(CtdbLookupError("network down"))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.LOOKUP_ERROR


def test_decoder_unavailable_after_db_hit() -> None:
    from whipper_gui.ctdb.decode import DecoderUnavailable

    entry = CtdbEntry(crc=123, confidence=3)
    client = _FakeClient(CtdbLookupResult(entries=(entry,)))

    def no_decoder(path: Path) -> bytes:
        raise DecoderUnavailable("no flac")

    res = verify_rip(_FLACS, client, decoder=no_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.DECODER_UNAVAILABLE
    assert res.confidence == 3  # DB hit still reported


def test_trustworthy_true_for_non_match_verdicts() -> None:
    res = CtdbVerifyResult(Verdict.NOT_IN_DATABASE)
    assert res.trustworthy is True


def test_toc_build_error_is_lookup_error() -> None:
    # A probe failure while building the TOC (before any lookup) → LOOKUP_ERROR.
    def bad_probe(_p: Path) -> int:
        raise RuntimeError("metaflac exploded")

    client = _FakeClient(CtdbLookupResult(entries=()))
    res = verify_rip(_FLACS, client, decoder=_decoder, samples_probe=bad_probe)
    assert res.verdict is Verdict.LOOKUP_ERROR
    assert "TOC error" in res.message


def test_decode_oserror_after_db_hit_is_lookup_error() -> None:
    # DB hit, then the decode raises a non-DecoderUnavailable error.
    entry = CtdbEntry(crc=123, confidence=4)
    client = _FakeClient(CtdbLookupResult(entries=(entry,)))

    def bad_decoder(_p: Path) -> bytes:
        raise OSError("disk vanished mid-read")

    res = verify_rip(_FLACS, client, decoder=bad_decoder, samples_probe=_probe)
    assert res.verdict is Verdict.LOOKUP_ERROR
    assert res.confidence == 4  # DB hit still surfaced
