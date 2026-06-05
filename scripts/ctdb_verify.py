#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Standalone CTDB verify — the hardware-validation vehicle for KDD-16.

Run this against a folder of freshly-ripped FLACs (a disc you believe is in
CTDB) to exercise the whole verify path WITHOUT the GUI:

    python3 scripts/ctdb_verify.py ~/Music/rips/Artist/Album/

It prints the disc TOC, the exact lookup URL, the database verdict, and (if
`flac` is installed) our computed CRC vs. the database CRCs. Use it to confirm
— or correct — the wire format and the CRC algorithm before the GUI is wired
(see docs/test-plan.md, Test 1).

This script imports the project package, so run it from a checkout with the
package importable (e.g. `pip install -e .` or `PYTHONPATH=src`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whipper_gui.adapters.ctdb_client import CtdbHttpImpl
from whipper_gui.ctdb import crc as crc_mod
from whipper_gui.ctdb import decode
from whipper_gui.ctdb.toc import disc_toc_from_files
from whipper_gui.ctdb.verify import Verdict, verify_rip


def _find_flacs(folder: Path) -> list[Path]:
    """Return the album's FLACs in track order (sorted by filename)."""
    return sorted(folder.glob("*.flac"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a rip against CTDB.")
    parser.add_argument(
        "folder", type=Path, help="folder containing the ripped .flac files"
    )
    args = parser.parse_args(argv)

    flacs = _find_flacs(args.folder)
    if not flacs:
        print(f"No .flac files found in {args.folder}", file=sys.stderr)
        return 2

    print(f"Found {len(flacs)} track(s):")
    for p in flacs:
        print(f"  - {p.name}")

    # Show the TOC + lookup URL so the wire format can be eyeballed/confirmed.
    try:
        toc = disc_toc_from_files(flacs, decode.total_samples)
    except decode.DecoderUnavailable as exc:
        print(f"\nCannot build TOC: {exc} (install `flac`/metaflac).", file=sys.stderr)
        return 3
    print(f"\nDisc TOC (sectors): {toc.toc_string()}")
    client = CtdbHttpImpl()
    print(f"Lookup URL:\n  {client.build_url(toc)}")

    print(f"\nFLAC decoder present: {decode.flac_available()}")
    print(f"CRC algorithm validated (KDD-16): {crc_mod.CRC_VALIDATED}\n")

    result = verify_rip(flacs, client)

    print(f"Verdict:    {result.verdict.value}")
    print(f"Confidence: {result.confidence}")
    if result.our_crc is not None:
        print(f"Our CRC:    {result.our_crc:08x}")
    if result.matched_crc is not None:
        print(f"Matched CRC:{result.matched_crc:08x}")
    print(f"Detail:     {result.message}")
    if result.verdict is Verdict.MATCH and not result.trustworthy:
        print(
            "\nNOTE: a MATCH here is EXPERIMENTAL until the CRC algorithm is "
            "confirmed bit-exact on hardware (KDD-16)."
        )
    # Exit 0 for a clean run regardless of verdict — the verdict is the data.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
