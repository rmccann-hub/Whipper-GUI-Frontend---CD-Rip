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

from platterpus.adapters.ctdb_client import CtdbHttpImpl
from platterpus.ctdb import crc as crc_mod
from platterpus.ctdb import decode
from platterpus.ctdb.calibrate import calibrate, candidate_trims
from platterpus.ctdb.toc import disc_toc_from_files
from platterpus.ctdb.verify import Verdict, verify_rip


def _find_flacs(folder: Path) -> list[Path]:
    """Return the album's FLACs in track order (sorted by filename)."""
    return sorted(folder.glob("*.flac"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a rip against CTDB.")
    parser.add_argument(
        "folder", type=Path, help="folder containing the ripped .flac files"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help=(
            "if the disc is in CTDB, sweep candidate offset-guard trims over the "
            "decoded PCM and report which one reproduces the database CRC "
            "(pins the CTDB-CRC algorithm on real hardware — KDD-16)."
        ),
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

    if args.calibrate:
        _run_calibration(flacs, client)

    # Exit 0 for a clean run regardless of verdict — the verdict is the data.
    return 0


def _run_calibration(flacs: list[Path], client: CtdbHttpImpl) -> None:
    """Sweep candidate offset-guard trims to pin the CTDB-CRC algorithm.

    Re-runs the lookup to collect the database's expected CRC(s), decodes the
    disc to PCM, and reports which trim (if any) reproduces an expected CRC.
    A hit IS the validated algorithm; paste the result back so it can be baked
    into `ctdb/crc.py` and `CRC_VALIDATED` flipped.
    """
    print("\n=== CTDB CRC calibration (KDD-16) ===")
    if not decode.flac_available():
        print("Cannot calibrate: the `flac` decoder isn't available.")
        return
    try:
        toc = disc_toc_from_files(flacs, decode.total_samples)
        lookup = client.lookup(toc)
    except Exception as exc:  # noqa: BLE001 — diagnostic tool: report, don't crash
        print(f"Cannot calibrate: lookup failed ({exc}).")
        return
    if not lookup.in_database:
        print("Cannot calibrate: this disc isn't in CTDB (no expected CRC to match).")
        return

    expected = {e.crc for e in lookup.entries if e.crc is not None}
    print(f"Disc is in CTDB. Expected disc CRC(s): {_fmt_crcs(expected)}")
    print(f"Entry confidence(s): {sorted({e.confidence for e in lookup.entries})}")

    try:
        pcm = b"".join(decode.decode_flac_to_pcm(p) for p in flacs)
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot calibrate: decode failed ({exc}).")
        return
    frames = len(pcm) // 4
    print(f"Decoded whole-disc PCM: {len(pcm)} bytes = {frames} stereo frames.")
    print(f"Trying {len(candidate_trims())} candidate trims…")

    matches = calibrate(pcm, expected)
    if matches:
        print("\n✅ MATCH — the CTDB-CRC algorithm is pinned:")
        for m in matches:
            print(
                f"   front={m.front_frames} back={m.back_frames} frames "
                f"→ CRC {m.crc:08x}"
            )
        print(
            "Paste this back: I'll set the trim in ctdb/crc.py and flip "
            "CRC_VALIDATED=True."
        )
    else:
        print(
            "\n❌ No candidate trim reproduced the expected CRC. Paste these "
            "numbers back so the exact trim can be solved:\n"
            f"   expected CRC(s): {_fmt_crcs(expected)}\n"
            f"   whole-disc frames: {frames}\n"
            f"   no-trim CRC: {crc_mod.ctdb_crc_offset0(pcm):08x}"
        )


def _fmt_crcs(crcs: set[int]) -> str:
    return ", ".join(f"{c:08x}" for c in sorted(crcs)) or "(none)"


if __name__ == "__main__":
    raise SystemExit(main())
