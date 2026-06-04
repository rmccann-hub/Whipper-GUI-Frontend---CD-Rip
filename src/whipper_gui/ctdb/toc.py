# SPDX-License-Identifier: GPL-3.0-only
"""CD table-of-contents model for CTDB lookups.

Clean-room implementation per PLANNING.md KDD-16: the CTDB protocol and the
disc-TOC math are *facts* (not copyrightable expression), reimplemented here
from the LGPL `cuetools.net` reference and the spec in
`docs/upstream-modification-investigation.md`. We never read or port the
GPL-2.0-only `python-cuetoolsdb`.

What this module owns:
  * `DiscToc` — the track offsets + lead-out that identify a disc to CTDB.
  * Building the `toc=` query string CTDB's `lookup2.php` expects.
  * Deriving a `DiscToc` from a whipper-written `.cue` plus the FLAC files
    (track lengths come from `metaflac`, which we already depend on).

⚠️ HARDWARE-VALIDATION GATE (KDD-16): the exact `toc=` wire format — in
particular whether offsets carry the 150-frame lead-in and how the lead-out is
expressed — is reconstructed from the spec and MUST be confirmed against a real
CD that is in CTDB (see `docs/test-plan.md`). The transformations here are
unit-tested for *what we intend*; hardware confirms the intent matches CTDB.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# CD-DA geometry: 75 sectors per second; each sector is 588 stereo 16-bit
# samples (2352 bytes). The 150-sector (2-second) lead-in offset is part of
# the absolute MSF addressing CTDB/AccurateRip use.
SECTORS_PER_SECOND: int = 75
SAMPLES_PER_SECTOR: int = 588
LEAD_IN_SECTORS: int = 150


@dataclass(frozen=True)
class DiscToc:
    """A disc's TOC as CTDB keys it: per-track start sectors + the lead-out.

    `track_offsets` are absolute sector addresses (lead-in included) of each
    track's start; `leadout` is the absolute sector immediately past the last
    audio frame. Both follow the AccurateRip/CTDB convention (offsets include
    the 150-sector lead-in).
    """

    track_offsets: tuple[int, ...]
    leadout: int

    def __post_init__(self) -> None:
        if not self.track_offsets:
            raise ValueError("a disc TOC needs at least one track offset")
        if self.leadout <= self.track_offsets[-1]:
            raise ValueError("lead-out must be past the last track offset")

    @property
    def num_tracks(self) -> int:
        return len(self.track_offsets)

    def toc_string(self) -> str:
        """The `toc=` value for `lookup2.php`: offsets then lead-out, ':'-joined.

        Example: ``150:18172:...:295716``. ⚠️ Format reconstructed from the
        spec — confirm on hardware (KDD-16)."""
        return ":".join(str(n) for n in (*self.track_offsets, self.leadout))


# --- MSF / sector helpers --------------------------------------------------


def msf_to_sectors(minutes: int, seconds: int, frames: int) -> int:
    """Convert an MM:SS:FF (minute/second/frame) timestamp to a sector count."""
    return (minutes * 60 + seconds) * SECTORS_PER_SECOND + frames


def samples_to_sectors(total_samples: int) -> int:
    """Round a per-channel sample count up to whole CD sectors.

    A CD frame holds exactly `SAMPLES_PER_SECTOR` samples per channel; a track
    whose audio doesn't fill its last sector still occupies that whole sector.
    """
    full, remainder = divmod(total_samples, SAMPLES_PER_SECTOR)
    return full + (1 if remainder else 0)


# `.cue` INDEX line: `    INDEX 01 MM:SS:FF` (we key off INDEX 01 — the audio
# start; INDEX 00 is pre-gap). Named groups per the project's parsing rule.
_INDEX01_RE = re.compile(
    r"^\s*INDEX\s+01\s+(?P<m>\d+):(?P<s>\d+):(?P<f>\d+)", re.IGNORECASE
)


def parse_cue_index01_sectors(cue_text: str) -> list[int]:
    """Return each track's INDEX 01 start as absolute sectors (lead-in added).

    whipper writes one `FILE`/`TRACK`/`INDEX 01` block per track; for a
    file-per-track rip the INDEX 01 times are relative to each file (usually
    00:00:00), so callers that need cumulative offsets should prefer
    `disc_toc_from_files` which sums real track lengths. This parser is used
    for single-file-image cues and for tests.
    """
    sectors: list[int] = []
    for line in cue_text.splitlines():
        m = _INDEX01_RE.match(line)
        if m:
            rel = msf_to_sectors(int(m["m"]), int(m["s"]), int(m["f"]))
            sectors.append(rel + LEAD_IN_SECTORS)
    return sectors


# A "samples probe" returns the per-channel total sample count of a FLAC file.
# Injected so tests don't shell out; the default uses metaflac (see decode.py).
SamplesProbe = Callable[[Path], int]


def disc_toc_from_files(
    flac_paths: Sequence[Path], samples_probe: SamplesProbe
) -> DiscToc:
    """Build a `DiscToc` from a file-per-track rip.

    Track 1 starts at the lead-in (sector 150); each subsequent track starts
    where the previous ended; the lead-out is one past the final track. Track
    lengths come from `samples_probe` (metaflac total-samples ÷ samples/sector).
    """
    if not flac_paths:
        raise ValueError("no FLAC files given")
    offsets: list[int] = []
    cursor = LEAD_IN_SECTORS
    for path in flac_paths:
        offsets.append(cursor)
        cursor += samples_to_sectors(samples_probe(path))
    return DiscToc(track_offsets=tuple(offsets), leadout=cursor)
