# SPDX-License-Identifier: GPL-3.0-only
"""Pin the CTDB audio-CRC algorithm against a real, in-database disc (KDD-16).

This is the bridge across the one hardware-validation gate the project can't
close in the cloud. We've established two facts about CUETools' ``CTDBCRC`` from
the LGPL source:

  * the underlying checksum is the **standard IEEE/zlib CRC-32** (polynomial
    ``0x04c11db7``, reflected, init/xor ``0xffffffff``) — i.e. exactly what
    Python's :func:`zlib.crc32` computes; and
  * ``CTDBCRC(offset=0)`` reduces to that CRC over the whole-disc PCM with a
    fixed number of sample-frames trimmed off the **front** (``stride/2``) and
    **back** (``laststride/2``) — an offset guard band so the value is stable
    across small pressing/drive-offset shifts.

The only unknown left is the exact *trim*. Rather than reverse-engineer
CUETools' parity ``stride`` from source (lossy and error-prone), we pin it
**empirically** against a disc that is genuinely in CTDB: the lookup returns the
*expected* CRC, so we sweep candidate trims over the decoded PCM and report
which one reproduces it. That discovered ``(front, back)`` is the validated
algorithm — bake it into :mod:`platterpus.ctdb.crc` and flip ``CRC_VALIDATED``.

Everything here is pure (PCM in, candidates out) so it's unit-tested without a
disc; the disc only supplies the PCM + the expected CRC when run for real (via
``scripts/ctdb_verify.py --calibrate``). No audio is ever committed (Rule #8).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from platterpus.ctdb.crc import BYTES_PER_SAMPLE_FRAME, CTDB_OFFSET_RANGE

# The offset guard band CTDB is tolerant over: 5 CD frames of 588 samples. The
# trim that makes CTDBCRC offset-stable is expected to live right around here,
# so the candidate sweep centres on it (CTDB_OFFSET_RANGE is this minus one).
_GUARD_FRAMES: int = CTDB_OFFSET_RANGE + 1  # 2940 = 5 * 588

# One CD sector is 588 stereo sample-frames; a parity stride is often a frame
# multiple, so we also probe frame-aligned symmetric trims as a fallback.
_FRAMES_PER_SECTOR: int = 588


@dataclass(frozen=True)
class TrimCandidate:
    """One (front, back) frame trim and the CRC it produces over the PCM."""

    front_frames: int
    back_frames: int
    crc: int


def crc_for_trim(pcm: bytes, front_frames: int, back_frames: int) -> int | None:
    """CRC-32 of `pcm` with `front_frames`/`back_frames` trimmed off each end.

    Frames are stereo 16-bit sample-frames (4 bytes). Returns None when the
    trim would leave nothing (or overlaps) — that candidate is simply skipped.
    Uses :func:`zlib.crc32`, which is bit-identical to CUETools' ``Crc32``.
    """
    start = front_frames * BYTES_PER_SAMPLE_FRAME
    end = len(pcm) - back_frames * BYTES_PER_SAMPLE_FRAME
    if start < 0 or back_frames < 0 or end <= start:
        return None
    return zlib.crc32(pcm[start:end]) & 0xFFFFFFFF


def candidate_trims(
    *, window: int = 30, max_sector_multiple: int = 10
) -> list[tuple[int, int]]:
    """The principled set of ``(front, back)`` frame trims to try.

    Bounded so a full sweep is ~tens of CRCs over the disc (seconds), not a
    brute force. It covers: no trim at all (the current placeholder baseline);
    a symmetric band around the ``5*588`` offset guard (±`window`, to absorb an
    off-by-stride); frame-aligned symmetric trims (in case the parity stride is
    a different sector multiple); and asymmetric guard-band variants (the front
    ``stride`` and back ``laststride`` can legitimately differ).
    """
    trims: set[tuple[int, int]] = {(0, 0)}
    for k in range(max(0, _GUARD_FRAMES - window), _GUARD_FRAMES + window + 1):
        trims.add((k, k))
    for n in range(max_sector_multiple + 1):
        trims.add((n * _FRAMES_PER_SECTOR, n * _FRAMES_PER_SECTOR))
    for front in (0, _GUARD_FRAMES):
        for back in (0, _GUARD_FRAMES, _GUARD_FRAMES - 1):
            trims.add((front, back))
    # Deterministic order (front, then back) so output/tests are stable.
    return sorted(trims)


def calibrate(pcm: bytes, expected_crcs: set[int]) -> list[TrimCandidate]:
    """Return every candidate trim whose CRC reproduces an `expected` CRC.

    `expected_crcs` are the CTDB lookup's entry CRCs for this disc. A non-empty
    result pins the algorithm: that ``(front, back)`` trim is what CUETools
    used, validated on a real in-database disc. Empty means none of the probed
    trims matched — widen the sweep, or the disc/offset isn't a clean case.
    Pure and total; never raises.
    """
    if not expected_crcs:
        return []
    matches: list[TrimCandidate] = []
    for front, back in candidate_trims():
        crc = crc_for_trim(pcm, front, back)
        if crc is not None and crc in expected_crcs:
            matches.append(TrimCandidate(front, back, crc))
    return matches
