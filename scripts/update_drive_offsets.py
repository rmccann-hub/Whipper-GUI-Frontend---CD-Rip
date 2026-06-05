#!/usr/bin/env python3
"""Regenerate the bundled AccurateRip drive-offset table.

Downloads AccurateRip's ``DriveOffsets.bin`` (or reads a local copy),
decodes it, and writes the compressed in-code data module
``src/whipper_gui/adapters/accuraterip_offsets_data.py``.

We bundle the list **in code** (a gzip+base64 blob), not as packaged data,
to dodge the AppImage package-data pitfalls that already bit ``help_content``
— and so offset lookup works fully offline for every drive. Re-run this
whenever you want to refresh the list:

    python3 scripts/update_drive_offsets.py            # download fresh
    python3 scripts/update_drive_offsets.py FILE.bin   # use a local file

Binary format (reverse-engineered + validated against the Pioneer BDR-209D,
whose known read offset is +667): a flat array of 69-byte records, each
``<int16 little-endian signed offset><67-byte null-padded ASCII name>``.
AccurateRip names look like ``"PIONEER  - BD-RW   BDR-209D"``; we normalize
them with the SAME function the runtime lookup uses, so keys match whipper's
vendor+model. Names that normalize to the same key with conflicting offsets
are dropped (never guess).
"""

from __future__ import annotations

import base64
import collections
import datetime
import gzip
import sys
import urllib.request
from pathlib import Path

# Import the canonical normalizer so generated keys match runtime lookups.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from whipper_gui.adapters.accuraterip_offsets import (  # noqa: E402
    normalize_drive_name,
)

SOURCE_URL = "http://www.accuraterip.com/accuraterip/DriveOffsets.bin"
RECORD = 69
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "whipper_gui"
    / "adapters"
    / "accuraterip_offsets_data.py"
)


def fetch(arg: str | None) -> bytes:
    if arg:
        return Path(arg).read_bytes()
    print(f"downloading {SOURCE_URL} …")
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:  # noqa: S310
        return resp.read()


def parse(data: bytes) -> dict[str, int]:
    if len(data) % RECORD != 0:
        raise SystemExit(
            f"unexpected file size {len(data)} (not a multiple of {RECORD})"
        )
    # Collect every offset seen per normalized key, then resolve.
    seen: dict[str, list[int]] = collections.defaultdict(list)
    for i in range(len(data) // RECORD):
        rec = data[i * RECORD : (i + 1) * RECORD]
        offset = int.from_bytes(rec[0:2], "little", signed=True)
        name = rec[2:].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
        if not name:
            continue
        key = normalize_drive_name("", name)
        if key:
            seen[key].append(offset)

    entries: dict[str, int] = {}
    conflicts = 0
    for key, offsets in seen.items():
        counts = collections.Counter(offsets)
        (top, top_n), *rest = counts.most_common()
        if rest and rest[0][1] == top_n:
            # Tie between distinct offsets → ambiguous → drop (never guess).
            conflicts += 1
            continue
        entries[key] = top
    if conflicts:
        print(f"dropped {conflicts} ambiguous (tied-offset) keys")
    return entries


def validate(entries: dict[str, int]) -> None:
    """Sanity gate: the tested drive must come out at +667, or refuse."""
    got = entries.get(normalize_drive_name("PIONEER", "BD-RW  BDR-209D"))
    if got != 667:
        raise SystemExit(
            f"VALIDATION FAILED: BDR-209D resolved to {got!r}, expected 667 — "
            "the binary format may have changed; not writing the data module."
        )
    print(f"validation OK: BDR-209D → +667; {len(entries)} drives")


def write_module(entries: dict[str, int]) -> None:
    csv = "".join(f"{k},{v}\n" for k, v in sorted(entries.items()))
    blob = base64.b64encode(gzip.compress(csv.encode("utf-8"), 9)).decode("ascii")
    today = datetime.date.today().isoformat()
    # Wrap the base64 to a sane width for the source file.
    wrapped = "\n".join(blob[i : i + 76] for i in range(0, len(blob), 76))
    OUT_PATH.write_text(
        '"""Auto-generated AccurateRip drive-offset table — DO NOT EDIT BY HAND.\n'
        "\n"
        f"Regenerate with: python3 scripts/update_drive_offsets.py\n"
        f"Source: {SOURCE_URL}\n"
        f"Generated: {today} | drives: {len(entries)}\n"
        "\n"
        "Stored as gzip+base64 of a normalized `key,offset` CSV (kept in code,\n"
        "not as packaged data, so it ships reliably in the AppImage and works\n"
        'offline). Decoded lazily by accuraterip_offsets.py.\n"""\n'
        "\n"
        "DRIVES: int = " + str(len(entries)) + "\n"
        'GENERATED: str = "' + today + '"\n'
        "\n"
        '_BLOB: str = (\n    "' + '"\n    "'.join(wrapped.splitlines()) + '"\n)\n',
        encoding="utf-8",
    )
    print(f"wrote {OUT_PATH} ({len(blob)} base64 chars)")


def main() -> None:
    data = fetch(sys.argv[1] if len(sys.argv) > 1 else None)
    entries = parse(data)
    validate(entries)
    write_module(entries)


if __name__ == "__main__":
    main()
