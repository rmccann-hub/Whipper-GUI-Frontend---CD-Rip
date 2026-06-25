"""Compare a rip's per-track Copy CRCs against an EAC baseline.

EAC is the bit-perfect baseline (``output_reference/``, ``docs/test-plan.md``).
A rip from any backend is byte-identical to EAC's when every track's **Copy
CRC** matches. This module reads the per-track Copy CRCs out of a log —
whichever of the three formats it is (EAC, whipper, cyanrip) — and diffs a
candidate against a baseline.

Pure and never-raises; backs ``scripts/eac_parity.py`` and the parity tests.
It's the "proof it's working" check for ``output_reference/``: a backend's log
is only committed there once it shows parity here.

**Output format (FLAC / WAV / MP3) doesn't matter to this check.** The Copy CRC
is computed on the *extracted PCM*, before the output encoder, so one comparison
covers all three:

* **FLAC / WAV** are lossless → identical PCM → identical Copy CRC, so a WAV rip
  is bit-perfect against the same EAC *FLAC* baseline (no separate WAV baseline
  needed).
* **MP3** is lossy → the encoded audio is *not* bit-comparable, but the
  extraction CRC still proves the read was bit-perfect. "MP3 parity" therefore
  means this CRC matches **plus** correct encoder/tag behaviour — the latter is
  out of scope for this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from whipper_gui.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from whipper_gui.parsers.eac_log import looks_like_eac_log, parse_eac_copy_crcs
from whipper_gui.parsers.rip_log import parse_rip_log


def decode_log_bytes(raw: bytes) -> str:
    """Decode rip-log bytes to text, honoring the encoding the tool wrote.

    **EAC writes its logs as UTF-16** (with a BOM) — naively reading them as
    UTF-8 turns every character into a replacement char, so the parser finds no
    CRCs and the parity check silently false-fails (every track "missing").
    whipper/cyanrip write UTF-8. We sniff the BOM (and fall back to a NUL-heavy
    heuristic for the rare BOM-less UTF-16), then default to UTF-8. Never raises
    — undecodable bytes are replaced.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")  # BOM picks LE/BE
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    # BOM-less UTF-16 is rare, but an ASCII-ish UTF-16 file is ~half NUL bytes;
    # if the head is NUL-heavy, guess UTF-16 and its endianness from where the
    # NULs fall (LE → the high byte, at odd indices, is NUL).
    head = raw[:256]
    if head and head.count(0) > len(head) // 4:
        le_nuls = sum(1 for i in range(1, len(head), 2) if head[i] == 0)
        be_nuls = sum(1 for i in range(0, len(head), 2) if head[i] == 0)
        enc = "utf-16-le" if le_nuls >= be_nuls else "utf-16-be"
        return raw.decode(enc, errors="replace")
    return raw.decode("utf-8", errors="replace")


def track_copy_crcs(text: str) -> dict[int, str]:
    """Per-track ``{number: uppercase Copy CRC}`` from a rip log of ANY backend.

    Sniffs the format (cyanrip → EAC → whipper as the default) and dispatches to
    the matching parser. Never raises — unrecognised input yields an empty map.
    Tracks with no Copy CRC (e.g. a data track) are omitted.
    """
    if looks_like_cyanrip_log(text):
        return {
            t.number: t.copy_crc.upper()
            for t in parse_cyanrip_log(text).tracks
            if t.copy_crc
        }
    if looks_like_eac_log(text):
        return parse_eac_copy_crcs(text)
    return {
        t.number: t.copy_crc.upper() for t in parse_rip_log(text).tracks if t.copy_crc
    }


@dataclass(frozen=True)
class TrackParity:
    """One track's baseline vs candidate Copy CRC."""

    number: int
    baseline_crc: str
    candidate_crc: str  # "" means the candidate has no CRC for this track

    @property
    def ok(self) -> bool:
        return bool(self.candidate_crc) and self.candidate_crc == self.baseline_crc


@dataclass(frozen=True)
class ParityReport:
    """The result of comparing a candidate rip log to a baseline."""

    tracks: tuple[TrackParity, ...]
    extra: tuple[int, ...] = ()  # track numbers in the candidate but not baseline

    @property
    def ok(self) -> bool:
        """True only when every baseline track matched and nothing is extra.

        An empty baseline (nothing parsed) is never parity — we can't claim a
        match against nothing.
        """
        return bool(self.tracks) and all(t.ok for t in self.tracks) and not self.extra

    @property
    def matched(self) -> int:
        return sum(1 for t in self.tracks if t.ok)

    @property
    def total(self) -> int:
        return len(self.tracks)


def compare_logs(baseline_text: str, candidate_text: str) -> ParityReport:
    """Compare a candidate rip log against a baseline by per-track Copy CRC."""
    base = track_copy_crcs(baseline_text)
    cand = track_copy_crcs(candidate_text)
    tracks = tuple(TrackParity(n, base[n], cand.get(n, "")) for n in sorted(base))
    extra = tuple(sorted(set(cand) - set(base)))
    return ParityReport(tracks=tracks, extra=extra)
