# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the CTDB-CRC calibration sweep (pure; no disc needed).

The calibration's job: given whole-disc PCM and the CTDB-expected CRC(s), find
the offset-guard trim that reproduces an expected CRC — pinning the algorithm.
We synthesise PCM, compute the CRC of a known trim ourselves, and assert the
sweep recovers exactly that trim.
"""

from __future__ import annotations

import zlib

from platterpus.ctdb.calibrate import (
    BYTES_PER_SAMPLE_FRAME,
    TrimCandidate,
    calibrate,
    candidate_trims,
    crc_for_trim,
)

# A deterministic, non-trivial PCM blob big enough to trim a 2940-frame guard
# band off both ends and still have audio left (5*588 = 2940 frames each end).
_PCM = bytes((i * 7 + 13) & 0xFF for i in range(40000))


def _crc_of_trim(pcm: bytes, front: int, back: int) -> int:
    start = front * BYTES_PER_SAMPLE_FRAME
    end = len(pcm) - back * BYTES_PER_SAMPLE_FRAME
    return zlib.crc32(pcm[start:end]) & 0xFFFFFFFF


def test_crc_for_trim_matches_zlib_slice() -> None:
    assert crc_for_trim(_PCM, 10, 20) == _crc_of_trim(_PCM, 10, 20)


def test_crc_for_trim_none_when_trim_too_big() -> None:
    # Trimming more frames than exist leaves nothing → skipped (None).
    huge = len(_PCM)  # way more frames than the blob holds
    assert crc_for_trim(_PCM, huge, huge) is None


def test_no_trim_equals_whole_disc_crc() -> None:
    assert crc_for_trim(_PCM, 0, 0) == zlib.crc32(_PCM) & 0xFFFFFFFF


def test_calibrate_recovers_the_guard_band_trim() -> None:
    # The real-world hypothesis: a symmetric 5*588 = 2940-frame guard band.
    expected = _crc_of_trim(_PCM, 2940, 2940)
    matches = calibrate(_PCM, {expected})
    assert TrimCandidate(2940, 2940, expected) in matches


def test_calibrate_recovers_a_no_trim_crc() -> None:
    expected = zlib.crc32(_PCM) & 0xFFFFFFFF
    matches = calibrate(_PCM, {expected})
    assert any(m.front_frames == 0 and m.back_frames == 0 for m in matches)


def test_calibrate_empty_when_nothing_matches() -> None:
    # A CRC no candidate trim can produce → no match (honest negative).
    assert calibrate(_PCM, {0xDEADBEEF}) == []


def test_calibrate_empty_expected_is_empty() -> None:
    assert calibrate(_PCM, set()) == []


def test_candidate_set_is_bounded_and_includes_key_hypotheses() -> None:
    trims = candidate_trims()
    # Bounded enough for a seconds-long sweep, not a brute force.
    assert len(trims) < 120
    assert (0, 0) in trims  # the placeholder baseline
    assert (2940, 2940) in trims  # the offset guard-band hypothesis
    # Deterministic ordering (stable script output / test runs).
    assert trims == sorted(trims)
