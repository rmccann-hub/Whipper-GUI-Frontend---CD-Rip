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
# The user's Desktop folder (for a clickable desktop icon, in addition to the
# applications-menu entry). Plain ~/Desktop matches dev-setup.sh's behaviour.
DESKTOP_FOLDER = Path.home() / "Desktop"
# Where an integrated AppImage should LIVE (real-user feedback, 2026-06-10:
# the menu entry pointing into ~/Downloads "defeats the purpose" — deleting
# a stray download would break the installed app). ~/Applications is the
# de-facto Linux convention (AppImageLauncher uses it too).
APPLICATIONS_DIR = Path.home() / "Applications"
# The artifact name every release publishes — also what the uninstaller
# looks for in APPLICATIONS_DIR.
CANONICAL_APPIMAGE_NAME = "whipper-gui-x86_64.AppImage"


def is_settled(appimage: Path, applications_dir: Path = APPLICATIONS_DIR) -> bool:
    """True if the AppImage already lives in its proper home.

    Real-user case this exists for: downloading an update OVER the path an
    old menu entry pointed at makes `is_integrated()` true, but the file is
    still sitting in Downloads — integration must still be offered so it
    gets moved (and the desktop icon remade).
    """
    try:
        return appimage.parent.resolve() == applications_dir.resolve()
    except OSError:
        return False


def relocate_to_applications(
    appimage: Path, applications_dir: Path = APPLICATIONS_DIR
) -> Path:
    """Move the AppImage into `applications_dir` and return its new path.

    Moving the file the app is currently running from is safe on Linux —
    the AppImage runtime holds the mounted/extracted image open, so the
    running session keeps working; only future launches use the new path.

    Never raises: already inside the target dir → returned unchanged; a
    failed move (permissions, exotic mounts) → logged, original returned,
    and integration simply proceeds where the file already is.
    """
    try:
        if appimage.parent.resolve() == applications_dir.resolve():
            return appimage
    except OSError:
        return appimage
    target = applications_dir / appimage.name
    try:
        applications_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(appimage), str(target))
    except OSError:
        log.warning("could not move %s to %s", appimage, target, exc_info=True)
        return appimage
    log.info("relocated AppImage: %s -> %s", appimage, target)
    return target


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
    """Best-effort refresh of the freedesktop + KDE menu caches.

    Fire-and-forget: `kbuildsycoca6` in particular can take tens of seconds
    to rebuild KDE's system cache, and this is sometimes called on the GUI
    thread (e.g. right after an in-app update). Blocking on it froze the
    window ("Not Responding") — a real-user report 2026-06-13. We don't
    need the result (the menu entry appears once the cache catches up on its
    own), so we launch each command detached and return immediately.
    """
    cmds = [
        ["update-desktop-database", str(DESKTOP_DIR)],
        ["kbuildsycoca6"],
        ["kbuildsycoca5"],
    ]
    for argv in cmds:
        if shutil.which(argv[0]) is None:
            continue
        try:
            # Popen (not run): start it and move on — never wait. start_new_session
            # detaches it so it isn't tied to our process group.
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, subprocess.SubprocessError):  # best-effort only
            log.debug("menu refresh via %s failed to launch", argv[0], exc_info=True)


def integrate(
    appimage: Path,
    *,
    app_dir: Path | None = None,
    desktop_dir: Path = DESKTOP_DIR,
    icon_dir: Path = ICON_DIR,
    desktop_folder: Path | None = DESKTOP_FOLDER,
    refresh: Callable[[], None] | None = None,
) -> Path:
    """Install a menu entry + icon for `appimage`. Returns the .desktop path.

    Idempotent: re-running just rewrites the entry. Ensures the AppImage is
    executable (so launchers can run it), copies the bundled icon to the user
    icon dir when found, drops a clickable icon in the Desktop folder (when one
    exists), and refreshes the menu caches.
    """
    desktop_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)

    # Launchers can only run the AppImage if it's executable.
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

    contents = _desktop_contents(appimage, icon_value)
    target = _desktop_file(desktop_dir)
    target.write_text(contents, encoding="utf-8")
    log.info("integrated AppImage: wrote %s", target)

    # A separate "Uninstall Whipper GUI" menu entry (menu only — deliberately
    # NOT on the Desktop) that opens the in-app uninstaller directly via the
    # app's --uninstall mode. Filed under System so it doesn't sit beside the
    # app in the Multimedia menu. The uninstaller removes this entry too.
    uninstall_entry = desktop_dir / f"{DESKTOP_ID}-uninstall.desktop"
    uninstall_entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Uninstall Whipper GUI\n"
        "Comment=Remove Whipper GUI and everything it installed "
        "(your music is kept)\n"
        f'Exec="{appimage}" --uninstall\n'
        f"Icon={icon_value}\n"
        "Terminal=false\n"
        "Categories=System;\n",
        encoding="utf-8",
    )
    log.info("wrote uninstaller menu entry %s", uninstall_entry)

    # Also drop a clickable icon on the Desktop (only if the user has a Desktop
    # folder — don't create one). Mark it executable; GNOME may still need a
    # one-time right-click "Allow Launching", KDE shows it directly.
    if desktop_folder is not None and desktop_folder.is_dir():
        try:
            shortcut = desktop_folder / f"{DESKTOP_ID}.desktop"
            shortcut.write_text(contents, encoding="utf-8")
            shortcut.chmod(0o755)
            _mark_trusted(shortcut)
            log.info("wrote desktop shortcut %s", shortcut)
        except OSError:
            log.warning("could not write desktop shortcut", exc_info=True)

    (refresh or _default_refresh)()
    return target


def _mark_trusted(shortcut: Path) -> None:
    """Best-effort: tell GNOME the .desktop is trusted so it launches on
    double-click without the 'Untrusted application launcher' prompt. No-op
    where `gio` is absent (e.g. KDE, which doesn't need it)."""
    if shutil.which("gio") is None:
        return
    try:
        subprocess.run(
            ["gio", "set", str(shortcut), "metadata::trusted", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        log.debug("gio trust failed", exc_info=True)
