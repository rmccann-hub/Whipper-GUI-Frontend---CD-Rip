"""Parse `whipper drive list` output into DriveDescriptor records.

Whipper emits one drive per call to the `List` command, with this shape
(verified against whipper-team/whipper master, command/drive.py):

    drive: /dev/sr0, vendor: PIONEER, model: BD-RW  BDR-209D, release: 1.51
           Configured read offset: 667
           Can defeat audio cache: True

Either of the indented properties may be absent (whipper prints
"no read offset found..." or "unknown whether audio cache can be
defeated..." instead). Both absences leave the corresponding field as
None on the DriveDescriptor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each regex uses named groups so output drift in column order or
# whitespace doesn't break parsing (CLAUDE.md rule).
_DRIVE_LINE = re.compile(
    r"^drive:\s*(?P<device>\S+),\s*"
    r"vendor:\s*(?P<vendor>.+?),\s*"
    r"model:\s*(?P<model>.+?),\s*"
    r"release:\s*(?P<release>\S+)\s*$"
)
_READ_OFFSET = re.compile(r"^\s*Configured read offset:\s*(?P<offset>-?\d+)\s*$")
_CACHE_DEFEAT = re.compile(
    r"^\s*Can defeat audio cache:\s*(?P<value>True|False|Yes|No)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DriveDescriptor:
    """One drive detected by whipper.

    - `device`: kernel device node, e.g. "/dev/sr0".
    - `vendor` / `model` / `release`: as whipper reports them. Whipper
      sometimes emits double-spaced model strings (Pioneer's actual
      output includes "BD-RW  BDR-209D"); we preserve whatever it sent.
    - `read_offset`: integer sample offset, or None if not configured.
    - `cache_defeat`: True/False, or None if unknown.
    """

    device: str
    vendor: str
    model: str
    release: str
    read_offset: int | None = None
    cache_defeat: bool | None = None


def parse_drive_list(stdout: str) -> list[DriveDescriptor]:
    """Parse a `whipper drive list` invocation's stdout into descriptors.

    Returns an empty list if no `drive:` line is found (which is also
    what whipper outputs for a system with no drives — its actual
    message is "no drives found...").
    """
    drives: list[DriveDescriptor] = []
    pending_header: dict[str, str] | None = None
    pending_offset: int | None = None
    pending_cache: bool | None = None

    def _flush() -> None:
        """Commit the in-progress drive once we hit a new header or EOF."""
        nonlocal pending_header, pending_offset, pending_cache
        if pending_header is None:
            return
        drives.append(
            DriveDescriptor(
                device=pending_header["device"],
                vendor=pending_header["vendor"].strip(),
                model=pending_header["model"].strip(),
                release=pending_header["release"],
                read_offset=pending_offset,
                cache_defeat=pending_cache,
            )
        )
        pending_header = None
        pending_offset = None
        pending_cache = None

    for line in stdout.splitlines():
        match = _DRIVE_LINE.match(line)
        if match:
            _flush()
            pending_header = match.groupdict()
            continue

        # An indented property only matters if we've seen a header.
        if pending_header is None:
            continue

        match = _READ_OFFSET.match(line)
        if match:
            pending_offset = int(match.group("offset"))
            continue

        match = _CACHE_DEFEAT.match(line)
        if match:
            pending_cache = match.group("value").lower() in ("true", "yes")
            continue

    _flush()
    return drives
