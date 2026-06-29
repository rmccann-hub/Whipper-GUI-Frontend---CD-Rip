#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Emit the machine-readable JSON rip report for a rip log.

The structured companion to the human `.log` (docs/ux-design-principles.md #2):
a versioned summary — drive/rip settings, per-track CRCs + AccurateRip results,
the overall verification verdict — that QA, re-verification, or repair tooling
can consume. Platterpus writes this automatically beside each rip's log; this
CLI lets you (re)generate it from any cyanrip/whipper log.

    python3 scripts/rip_report.py ~/Music/rips/Album/Album.log
    python3 scripts/rip_report.py Album.log -o Album.platterpus.json

Run from a checkout with the package importable (`pip install -e .` or
`PYTHONPATH=src`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from platterpus import rip_report
from platterpus.parity import decode_log_bytes
from platterpus.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from platterpus.parsers.eac_log import looks_like_eac_log
from platterpus.parsers.rip_log import RipLog, parse_rip_log


def _parse_to_rip_log(text: str) -> RipLog:
    """Parse a cyanrip or whipper log into a RipLog (auto-detected)."""
    if looks_like_cyanrip_log(text):
        return parse_cyanrip_log(text)
    return parse_rip_log(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the JSON rip report for a cyanrip/whipper rip log."
    )
    parser.add_argument("rip_log", type=Path, help="a cyanrip or whipper rip log")
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="write here instead of stdout"
    )
    args = parser.parse_args(argv)

    try:
        text = decode_log_bytes(args.rip_log.read_bytes())
    except OSError as exc:
        print(f"cannot read {args.rip_log}: {exc}", file=sys.stderr)
        return 2

    # This report is built from a cyanrip/whipper RipLog. An EAC log only yields
    # per-track Copy CRCs through our minimal EAC parser (not a full RipLog), so
    # feeding one here would silently produce an empty report — refuse instead.
    if looks_like_eac_log(text):
        print(
            f"{args.rip_log} is an EAC log; this tool reports on cyanrip/whipper "
            "rips. (EAC logs aren't parsed into a full report.)",
            file=sys.stderr,
        )
        return 2

    report = rip_report.build_report(_parse_to_rip_log(text))
    rendered = rip_report.report_to_json(report)

    if args.output is not None:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"cannot write {args.output}: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
