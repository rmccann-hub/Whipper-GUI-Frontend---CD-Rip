"""Parse Exact Audio Copy (EAC) rip logs — the per-track Copy CRCs.

EAC is the bit-perfect baseline this project measures against (see
``output_reference/`` and ``docs/test-plan.md``). Its log format differs from
whipper's YAML-ish log and from cyanrip's report, so it needs its own reader.
Parity only needs each track's **Copy CRC**, so this is intentionally minimal
rather than a full EAC parser.

EAC track-block shape (verified against the committed baseline
``output_reference/EAC_flac/eac_baseline_police_classics.log``)::

    Track  1

         Filename D:\\My Music\\01 - Roxanne - The Police.wav
         Peak level 94.2 %
         Test CRC B0D122E7
         Copy CRC B0D122E7

Like every parser of external output, this must never raise on arbitrary text —
it degrades to an empty mapping (institutional rule, ``docs/testing.md``).
"""

from __future__ import annotations

import re

# "Exact Audio Copy V1.8 from ..." — the first line of any EAC log (often
# preceded by a UTF-8 BOM, which we strip before matching).
_EAC_BANNER = re.compile(r"^Exact Audio Copy\b", re.IGNORECASE)
# A per-track block opens with "Track  N" at column 0 (EAC pads the number with
# spaces). Distinct from the TOC table rows, which are indented and pipe-delimited.
_TRACK_HEADER = re.compile(r"^Track\s+(?P<number>\d+)\s*$")
# "     Copy CRC B0D122E7" — 8 hex digits, space-separated (no colon, unlike
# whipper's "Copy CRC: ...").
_COPY_CRC = re.compile(r"^\s*Copy CRC\s+(?P<crc>[0-9A-Fa-f]{8})\b")


def looks_like_eac_log(text: str) -> bool:
    """True if `text` is an EAC extraction log (first non-blank line is its banner)."""
    for line in text.splitlines():
        if line.strip():
            return bool(_EAC_BANNER.match(line.lstrip("﻿")))
    return False


def parse_eac_copy_crcs(text: str) -> dict[int, str]:
    """Return ``{track_number: uppercase Copy CRC}`` from an EAC log.

    Only the Copy CRC is extracted — that's what bit-perfect parity compares.
    Tolerates absent fields and unexpected lines; never raises.
    """
    crcs: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        header = _TRACK_HEADER.match(line)
        if header:
            current = int(header.group("number"))
            continue
        crc = _COPY_CRC.match(line)
        if crc and current is not None:
            crcs[current] = crc.group("crc").upper()
    return crcs
