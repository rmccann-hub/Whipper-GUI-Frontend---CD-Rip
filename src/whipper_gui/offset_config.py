"""Detect whether a usable optical-drive read offset is configured.

whipper refuses to rip until a read offset is known (it errors with
"drive offset unconfigured"). An offset can come from one of two places:

  * whipper's own `whipper.conf`, written by the drive-setup wizard's
    `whipper offset find` (whipper is authoritative for it), or
  * the GUI's `--offset` override (Config.override_read_offset), which lets
    a user set the value by hand when they can't run auto-detection (no
    AccurateRip disc) — we pass it as `--offset N` at rip time.

This module answers "is either present?" so the GUI can offer first-run
calibration only when it's actually needed. Pure stdlib + injectable path
so it's trivially testable; no whipper.conf authoring happens here (per
PLANNING.md KDD-15, the GUI never hand-writes that file).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from whipper_gui.paths import WHIPPER_CONFIG_PATH

log = logging.getLogger(__name__)

# A `read_offset = <signed int>` assignment that isn't commented out. whipper
# writes it under a `[drive:...]` section; we only care that one exists.
_OFFSET_LINE = re.compile(r"^\s*read_offset\s*=\s*-?\d+\s*$")

# A section header `[name]` and a `read_offset = N` key=value, for the
# per-drive parse below. whipper keys each drive section as
# `[drive:<vendor%20model%20…>]` (the id is URL-quoted), so we decode it for
# display.
_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_OFFSET_KV = re.compile(r"^\s*read_offset\s*=\s*(?P<val>-?\d+)\s*$")
_DRIVE_PREFIX = "drive:"


def whipper_conf_has_offset(conf_path: Path = WHIPPER_CONFIG_PATH) -> bool:
    """True if whipper.conf exists and assigns a read_offset for some drive."""
    try:
        text = conf_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as exc:  # unreadable file — treat as "not configured"
        log.warning("could not read %s: %s", conf_path, exc)
        return False
    return any(_OFFSET_LINE.match(line) for line in text.splitlines())


def is_offset_configured(
    override_read_offset: bool,
    conf_path: Path = WHIPPER_CONFIG_PATH,
) -> bool:
    """True if a read offset will reach whipper from either source.

    `override_read_offset` is Config.override_read_offset — when set, the GUI
    passes `--offset` and whipper.conf is irrelevant.
    """
    return bool(override_read_offset) or whipper_conf_has_offset(conf_path)


@dataclass(frozen=True)
class WhipperConfOffset:
    """One per-drive read offset whipper has persisted, for display.

    `drive` is the human-readable drive id (whipper's URL-quoted section name,
    decoded); `offset` is the signed sample offset whipper will apply to that
    drive when the GUI does *not* pass `--offset`.
    """

    drive: str
    offset: int


def read_drive_offsets(
    conf_path: Path = WHIPPER_CONFIG_PATH,
) -> list[WhipperConfOffset]:
    """Parse whipper.conf's per-drive `read_offset` values — the offsets
    whipper will *actually* apply (authoritative when the GUI isn't overriding).

    This is the trust check the GUI's own stored `read_offset` can't give: the
    config file may have been written by the wizard or hand-edited and drifted
    from what the GUI thinks. **Never raises** — a missing/unreadable/malformed
    file just yields `[]`, like the other config probes here.
    """
    try:
        text = conf_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("could not read %s: %s", conf_path, exc)
        return []

    offsets: list[WhipperConfOffset] = []
    current_section: str | None = None
    for line in text.splitlines():
        section = _SECTION_RE.match(line)
        if section:
            current_section = section.group("name")
            continue
        kv = _OFFSET_KV.match(line)
        if kv and current_section and current_section.startswith(_DRIVE_PREFIX):
            raw_id = current_section[len(_DRIVE_PREFIX) :]
            offsets.append(
                WhipperConfOffset(
                    drive=unquote(raw_id).strip() or raw_id,
                    offset=int(kv.group("val")),
                )
            )
    return offsets


def describe_conf_offsets(conf_path: Path = WHIPPER_CONFIG_PATH) -> str:
    """A one-line, human summary of whipper.conf's per-drive read offsets.

    Used by the Settings dialog and `--doctor` to show what whipper will apply,
    rather than the GUI's stored copy. Never raises.
    """
    offsets = read_drive_offsets(conf_path)
    if not offsets:
        return "none set"
    return "; ".join(f"{o.drive} → {o.offset:+d}" for o in offsets)
