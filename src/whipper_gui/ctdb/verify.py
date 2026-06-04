# SPDX-License-Identifier: GPL-3.0-only
"""Verify a finished rip against the CUETools Database (CTDB).

Ties together the lookup adapter, the FLAC decode, and the (offset-0, best-
effort) CTDB CRC into a single verdict. Clean-room per KDD-16.

The flow:
  1. Build the disc TOC from the ripped FLACs (track lengths via metaflac).
  2. Look the TOC up in CTDB.
  3. If found, decode the tracks to PCM and compute our CRC, then compare to
     the database entries.

Every step degrades to a clear verdict rather than raising, so a missing
decoder or a network blip never crashes the caller.

⚠️ The CRC/offset/wire-format pieces are hardware-validation-gated (KDD-16);
a `MATCH` verdict is only trustworthy once `crc.CRC_VALIDATED` is True. Until
then the GUI must label any match "experimental" — which is why the UI wiring
is deliberately deferred (see `docs/test-plan.md`).
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from whipper_gui.adapters.ctdb_client import (
    CTDBClient,
    CtdbLookupError,
    CtdbLookupResult,
)
from whipper_gui.ctdb import crc as crc_mod
from whipper_gui.ctdb import decode
from whipper_gui.ctdb.toc import SamplesProbe, disc_toc_from_files

log = logging.getLogger(__name__)


class Verdict(enum.Enum):
    """The possible outcomes of a CTDB verify."""

    MATCH = "match"  # our CRC matched a DB entry
    NO_MATCH = "no_match"  # disc in DB, but our CRC didn't match
    NOT_IN_DATABASE = "not_in_db"  # TOC not found in CTDB
    DECODER_UNAVAILABLE = "no_decoder"  # can't compute local CRC (no flac)
    LOOKUP_ERROR = "lookup_error"  # network/parse failure


@dataclass(frozen=True)
class CtdbVerifyResult:
    """A verify outcome plus the supporting detail for display/logging."""

    verdict: Verdict
    confidence: int = 0
    our_crc: int | None = None
    matched_crc: int | None = None
    message: str = ""
    crc_validated: bool = crc_mod.CRC_VALIDATED

    @property
    def trustworthy(self) -> bool:
        """A MATCH is only trustworthy once the CRC algorithm is confirmed."""
        return self.verdict is not Verdict.MATCH or self.crc_validated


# A decoder turns a FLAC path into PCM bytes (injected for tests).
PcmDecoder = Callable[[Path], bytes]


def verify_rip(
    flac_paths: Sequence[Path],
    client: CTDBClient,
    *,
    decoder: PcmDecoder | None = None,
    samples_probe: SamplesProbe | None = None,
) -> CtdbVerifyResult:
    """Verify the rip in `flac_paths` against CTDB. Never raises for expected
    failure modes — returns a verdict instead.

    `decoder`/`samples_probe` are injected in tests; production defaults use
    the host `flac`/`metaflac`.
    """
    decoder = decoder or decode.decode_flac_to_pcm
    samples_probe = samples_probe or decode.total_samples

    # 1) TOC → 2) lookup.
    try:
        toc = disc_toc_from_files(flac_paths, samples_probe)
    except decode.DecoderUnavailable as exc:
        return CtdbVerifyResult(Verdict.DECODER_UNAVAILABLE, message=str(exc))
    except (OSError, RuntimeError, ValueError) as exc:
        return CtdbVerifyResult(Verdict.LOOKUP_ERROR, message=f"TOC error: {exc}")

    try:
        result = client.lookup(toc)
    except CtdbLookupError as exc:
        return CtdbVerifyResult(Verdict.LOOKUP_ERROR, message=str(exc))

    if not result.in_database:
        return CtdbVerifyResult(
            Verdict.NOT_IN_DATABASE, message="this disc is not in CTDB"
        )

    # 3) decode + CRC compare.
    try:
        pcm = _decode_all(flac_paths, decoder)
    except decode.DecoderUnavailable as exc:
        return _db_only_result(result, Verdict.DECODER_UNAVAILABLE, str(exc))
    except (OSError, RuntimeError) as exc:
        return _db_only_result(result, Verdict.LOOKUP_ERROR, f"decode error: {exc}")

    our_crc = crc_mod.ctdb_crc_offset0(pcm)
    return _match_verdict(result, our_crc)


def _decode_all(flac_paths: Sequence[Path], decoder: PcmDecoder) -> bytes:
    """Decode every track and concatenate (whole-disc PCM, in track order)."""
    chunks = [decoder(Path(p)) for p in flac_paths]
    return b"".join(chunks)


def _match_verdict(result: CtdbLookupResult, our_crc: int) -> CtdbVerifyResult:
    for entry in result.entries:
        if entry.crc is not None and entry.crc == our_crc:
            return CtdbVerifyResult(
                Verdict.MATCH,
                confidence=entry.confidence,
                our_crc=our_crc,
                matched_crc=entry.crc,
                message=(
                    f"verified against CTDB (confidence {entry.confidence})"
                    if crc_mod.CRC_VALIDATED
                    else "CRC matched, but the CRC algorithm is UNVERIFIED "
                    "(KDD-16) — treat as experimental"
                ),
            )
    best = max((e.confidence for e in result.entries), default=0)
    return CtdbVerifyResult(
        Verdict.NO_MATCH,
        confidence=best,
        our_crc=our_crc,
        message=(
            "disc is in CTDB but our CRC didn't match any entry. Expected if "
            "the rip differs — OR if the offset-0/CRC algorithm needs the "
            "hardware-validated fix (KDD-16)."
        ),
    )


def _db_only_result(
    result: CtdbLookupResult, verdict: Verdict, message: str
) -> CtdbVerifyResult:
    """Verdict for 'found in DB but couldn't compute our CRC'."""
    best = max((e.confidence for e in result.entries), default=0)
    return CtdbVerifyResult(verdict, confidence=best, message=message)
