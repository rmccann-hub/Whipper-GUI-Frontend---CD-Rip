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
from pathlib import Path

from whipper_gui.paths import WHIPPER_CONFIG_PATH

log = logging.getLogger(__name__)

# A `read_offset = <signed int>` assignment that isn't commented out. whipper
# writes it under a `[drive:...]` section; we only care that one exists.
_OFFSET_LINE = re.compile(r"^\s*read_offset\s*=\s*-?\d+\s*$")


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
