"""Filesystem paths used across the GUI.

Single source of truth for user config, user log, and the paths the
Distrobox container shares with the GUI. Honors `XDG_CONFIG_HOME` and
`XDG_DATA_HOME` when set, falling back to `~/.config` and
`~/.local/share` per the freedesktop.org Base Directory spec.

No I/O happens here — every constant is just a `pathlib.Path`. The
modules that consume these constants (`config.py`, `logging_setup.py`)
are responsible for creating parent directories on first write.
"""

from __future__ import annotations

import os
from pathlib import Path

# XDG base dirs with conventional fallbacks. We resolve once at import
# time; if the user's HOME or XDG_* changes mid-process, restart.
_XDG_CONFIG_HOME: Path = Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
)
_XDG_DATA_HOME: Path = Path(
    os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
)

# Application slot under each XDG base dir.
APP_NAME: str = "whipper-gui"

# Where our own settings live.
CONFIG_DIR: Path = _XDG_CONFIG_HOME / APP_NAME
CONFIG_PATH: Path = CONFIG_DIR / "config.toml"

# Where our log file lives (rotated by logging_setup.py).
LOG_DIR: Path = _XDG_DATA_HOME / APP_NAME
LOG_PATH: Path = LOG_DIR / "log.txt"

# Whipper's own config file, shared with the Distrobox `ripping` container.
# It holds the per-drive `read_offset` and `defeats_cache` settings and is
# authoritative for them. The GUI does not hand-author this file; the only
# writer is the drive-setup wizard, which runs whipper's OWN `drive analyze`
# / `offset find` commands (they persist here themselves) after backing the
# file up to `whipper.conf.bak` first. See PLANNING.md KDD-15.
WHIPPER_CONFIG_PATH: Path = _XDG_CONFIG_HOME / "whipper" / "whipper.conf"

# Default location of the host-exported whipper binary. The Settings
# dialog lets the user override this at runtime, but this is the value
# we assume on first launch (matches the brief's documented setup).
WHIPPER_BINARY_DEFAULT: Path = Path.home() / ".local" / "bin" / "whipper"

# Default location of the host-exported cyanrip binary (the optional
# KDD-18 backend). Same export route as whipper: the host-setup wizard
# runs `distrobox-export` inside the `ripping` container, which drops a
# wrapper here.
CYANRIP_BINARY_DEFAULT: Path = Path.home() / ".local" / "bin" / "cyanrip"
