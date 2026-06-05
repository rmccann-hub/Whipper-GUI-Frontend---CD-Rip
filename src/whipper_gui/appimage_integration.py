"""AppImage self-integration — make a downloaded AppImage behave like an
installed app, from inside the app itself (no `install-appimage.sh`, KDD-17).

An AppImage is a single portable binary: by design it doesn't add itself to
the application menu. On first run we offer to do that — write a `.desktop`
entry pointing at the AppImage, drop its icon, and refresh the menu caches —
so from then on the user launches it from their menu like any other app
(double-click the file once, then it's "installed").

When NOT running from an AppImage (source/pipx install), this is a no-op:
`dev-setup.sh` already installs a launcher.

The AppImage runtime exports two env vars we rely on:
  * ``APPIMAGE`` — absolute path to the .AppImage file the user launched
  * ``APPDIR``   — the mounted root, where the bundled icon lives

All filesystem locations are injectable so the logic is unit-testable without
a real AppImage, and the menu-cache refresh goes through an injected callable.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from whipper_gui.paths import APP_NAME

log = logging.getLogger(__name__)

DESKTOP_ID = APP_NAME  # "whipper-gui" — keeps the .desktop id aligned with paths.py
_DISPLAY_NAME = "Whipper GUI"

_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
DESKTOP_DIR = _DATA_HOME / "applications"
ICON_DIR = _DATA_HOME / "icons"


def appimage_path() -> Path | None:
    """The .AppImage file we're running from, or None if not an AppImage."""
    value = os.environ.get("APPIMAGE")
    return Path(value) if value else None


def appdir() -> Path | None:
    """The mounted AppImage root ($APPDIR), or None."""
    value = os.environ.get("APPDIR")
    return Path(value) if value else None


def running_as_appimage() -> bool:
    return appimage_path() is not None


def find_bundled_icon(app_dir: Path | None) -> Path | None:
    """Locate the app icon inside the mounted AppImage, or None.

    python-appimage puts our PNG at the AppDir root and also writes a
    ``.DirIcon``; fall back through the likely spots.
    """
    if app_dir is None:
        return None
    candidates = [
        app_dir / f"{DESKTOP_ID}.png",
        app_dir / ".DirIcon",
        app_dir / "usr/share/icons/hicolor/256x256/apps" / f"{DESKTOP_ID}.png",
    ]
    return next((p for p in candidates if p.is_file()), None)


def _desktop_file(desktop_dir: Path) -> Path:
    return desktop_dir / f"{DESKTOP_ID}.desktop"


def is_integrated(appimage: Path, desktop_dir: Path = DESKTOP_DIR) -> bool:
    """True if a desktop entry exists that launches *this* AppImage.

    We check the Exec path so that a moved or updated AppImage re-integrates
    (a stale entry pointing at an old path doesn't count as integrated).
    """
    target = _desktop_file(desktop_dir)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return False
    # Exec is written quoted ('Exec="<path>" %U'); match that exact form.
    return f'Exec="{appimage}"' in text


def _desktop_contents(appimage: Path, icon: str) -> str:
    # Exec is quoted so a path with spaces still launches.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_DISPLAY_NAME}\n"
        "GenericName=CD Ripper\n"
        "Comment=Rip audio CDs to FLAC with EAC-equivalent accuracy\n"
        f'Exec="{appimage}" %U\n'
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;\n"
        "Keywords=cd;rip;flac;whipper;audio;\n"
    )


def _default_refresh() -> None:
    """Best-effort refresh of the freedesktop + KDE menu caches."""
    cmds = [
        ["update-desktop-database", str(DESKTOP_DIR)],
        ["kbuildsycoca6"],
        ["kbuildsycoca5"],
    ]
    for argv in cmds:
        if shutil.which(argv[0]) is None:
            continue
        try:
            subprocess.run(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):  # best-effort only
            log.debug("menu refresh via %s failed", argv[0], exc_info=True)


def integrate(
    appimage: Path,
    *,
    app_dir: Path | None = None,
    desktop_dir: Path = DESKTOP_DIR,
    icon_dir: Path = ICON_DIR,
    refresh: Callable[[], None] | None = None,
) -> Path:
    """Install a menu entry + icon for `appimage`. Returns the .desktop path.

    Idempotent: re-running just rewrites the entry. Ensures the AppImage is
    executable (so the menu entry can launch it), copies the bundled icon to
    the user icon dir when found, and refreshes the menu caches.
    """
    desktop_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)

    # The menu entry can only launch the AppImage if it's executable.
    try:
        mode = appimage.stat().st_mode
        appimage.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        log.warning("could not set +x on %s", appimage, exc_info=True)

    # Copy the icon out of the mounted AppImage; fall back to a stock name.
    icon_value = "media-optical"
    bundled = find_bundled_icon(app_dir if app_dir is not None else appdir())
    if bundled is not None:
        icon_dest = icon_dir / f"{DESKTOP_ID}.png"
        try:
            shutil.copyfile(bundled, icon_dest)
            icon_value = str(icon_dest)
        except OSError:
            log.warning("could not copy icon from %s", bundled, exc_info=True)

    target = _desktop_file(desktop_dir)
    target.write_text(_desktop_contents(appimage, icon_value), encoding="utf-8")
    log.info("integrated AppImage: wrote %s", target)

    (refresh or _default_refresh)()
    return target
