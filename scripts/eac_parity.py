#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare rip logs against the EAC baseline by per-track Copy CRC.

EAC is the project's bit-perfect baseline (``output_reference/``,
``docs/test-plan.md``). A rip is byte-identical to EAC's when every track's Copy
CRC matches. This is the "proof it's working" tool: rip the baseline disc with a
backend, run this against EAC's log, and — if it passes — commit the backend's
log under ``output_reference/<backend>_<format>/``.

    python3 scripts/eac_parity.py \\
        output_reference/EAC_flac/eac_baseline_police_classics.log \\
        ~/Music/rips/whipper/Album/Album.log [more candidates ...]

The log format (EAC / whipper / cyanrip) is auto-detected per file. Prints a
per-track PASS/FAIL table for each candidate and exits non-zero if any candidate
isn't bit-perfect parity (so it's usable in CI / a release gate).

Run from a checkout with the package importable (``pip install -e .`` or
``PYTHONPATH=src``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from whipper_gui.parity import ParityReport, compare_logs


def _print_report(baseline: Path, candidate: Path, report: ParityReport) -> None:
    print(f"\n{candidate}  vs  {baseline}")
    if not report.tracks:
        print("  ! no per-track Copy CRCs in the baseline — nothing to compare")
        return
    for t in report.tracks:
        mark = "PASS" if t.ok else "FAIL"
        shown = t.candidate_crc or "(missing)"
        print(
            f"  Track {t.number:>2}: {mark}  "
            f"baseline {t.baseline_crc}  candidate {shown}"
        )
    for n in report.extra:
        print(f"  Track {n:>2}: EXTRA  (in candidate, not in the baseline)")
    verdict = "PARITY ✓" if report.ok else "NOT parity ✗"
    print(f"  → {report.matched}/{report.total} tracks match — {verdict}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare rip logs to an EAC baseline by per-track Copy CRC."
    )
    parser.add_argument(
        "baseline", type=Path, help="the EAC (or reference) baseline log"
    )
    parser.add_argument(
        "candidate", type=Path, nargs="+", help="candidate rip log(s) to check"
    )
    args = parser.parse_args(argv)

    try:
        baseline_text = args.baseline.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read baseline {args.baseline}: {exc}", file=sys.stderr)
        return 2

    all_ok = True
    for candidate in args.candidate:
        try:
            candidate_text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"cannot read {candidate}: {exc}", file=sys.stderr)
            all_ok = False
            continue
        report = compare_logs(baseline_text, candidate_text)
        all_ok = all_ok and report.ok
        _print_report(args.baseline, candidate, report)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
