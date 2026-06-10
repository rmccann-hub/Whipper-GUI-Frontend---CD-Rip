"""Tests for AppImage self-integration (no real AppImage needed)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from whipper_gui import appimage_integration as ai

# --- env detection --------------------------------------------------------


def test_running_as_appimage_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert ai.running_as_appimage() is False
    monkeypatch.setenv("APPIMAGE", "/home/u/whipper-gui-x86_64.AppImage")
    assert ai.running_as_appimage() is True
    assert ai.appimage_path() == Path("/home/u/whipper-gui-x86_64.AppImage")


# --- icon discovery -------------------------------------------------------


def test_find_bundled_icon_prefers_root_png(tmp_path: Path) -> None:
    (tmp_path / f"{ai.DESKTOP_ID}.png").write_bytes(b"PNG")
    assert ai.find_bundled_icon(tmp_path) == tmp_path / f"{ai.DESKTOP_ID}.png"


def test_find_bundled_icon_falls_back_to_diricon(tmp_path: Path) -> None:
    (tmp_path / ".DirIcon").write_bytes(b"PNG")
    assert ai.find_bundled_icon(tmp_path) == tmp_path / ".DirIcon"


def test_find_bundled_icon_none_when_absent(tmp_path: Path) -> None:
    assert ai.find_bundled_icon(tmp_path) is None
    assert ai.find_bundled_icon(None) is None


# --- integrate ------------------------------------------------------------


def _appimage(tmp_path: Path) -> Path:
    p = tmp_path / "whipper-gui-x86_64.AppImage"
    p.write_bytes(b"\x7fELF fake")
    p.chmod(0o644)  # NOT executable yet
    return p


def test_integrate_writes_desktop_entry_and_copies_icon(tmp_path: Path) -> None:
    appimage = _appimage(tmp_path)
    appdir = tmp_path / "appdir"
    appdir.mkdir()
    (appdir / f"{ai.DESKTOP_ID}.png").write_bytes(b"PNG")
    desktop_dir = tmp_path / "applications"
    icon_dir = tmp_path / "icons"
    refreshed: list[bool] = []

    target = ai.integrate(
        appimage,
        app_dir=appdir,
        desktop_dir=desktop_dir,
        icon_dir=icon_dir,
        desktop_folder=None,
        refresh=lambda: refreshed.append(True),
    )

    text = target.read_text()
    assert f'Exec="{appimage}" %U' in text
    assert "Name=Whipper GUI" in text
    # Icon was copied out of the AppDir and referenced by path.
    icon_dest = icon_dir / f"{ai.DESKTOP_ID}.png"
    assert icon_dest.is_file()
    assert f"Icon={icon_dest}" in text
    # The AppImage was made executable so the menu entry can launch it.
    assert os.access(appimage, os.X_OK)
    assert bool(appimage.stat().st_mode & stat.S_IXUSR)
    assert refreshed == [True]


def test_integrate_writes_uninstaller_menu_entry(tmp_path: Path) -> None:
    """Integration also installs an 'Uninstall Whipper GUI' menu entry that
    launches the app's --uninstall mode — menu only, never on the Desktop,
    and under System rather than Multimedia."""
    appimage = _appimage(tmp_path)
    desktop_dir = tmp_path / "applications"
    desktop_folder = tmp_path / "Desktop"
    desktop_folder.mkdir()

    ai.integrate(
        appimage,
        app_dir=None,
        desktop_dir=desktop_dir,
        icon_dir=tmp_path / "icons",
        desktop_folder=desktop_folder,
        refresh=lambda: None,
    )

    entry = desktop_dir / f"{ai.DESKTOP_ID}-uninstall.desktop"
    text = entry.read_text()
    assert f'Exec="{appimage}" --uninstall' in text
    assert "Name=Uninstall Whipper GUI" in text
    assert "Categories=System;" in text
    # The Desktop folder gets the app shortcut only — no uninstaller there.
    assert not (desktop_folder / f"{ai.DESKTOP_ID}-uninstall.desktop").exists()


def test_integrate_writes_desktop_folder_shortcut(tmp_path: Path) -> None:
    appimage = _appimage(tmp_path)
    desktop_folder = tmp_path / "Desktop"
    desktop_folder.mkdir()
    ai.integrate(
        appimage,
        app_dir=tmp_path / "none",
        desktop_dir=tmp_path / "applications",
        icon_dir=tmp_path / "icons",
        desktop_folder=desktop_folder,
        refresh=lambda: None,
    )
    shortcut = desktop_folder / f"{ai.DESKTOP_ID}.desktop"
    assert shortcut.is_file()
    assert f'Exec="{appimage}" %U' in shortcut.read_text()
    assert os.access(shortcut, os.X_OK)  # executable so launchers accept it


def test_integrate_skips_desktop_shortcut_when_no_desktop_folder(
    tmp_path: Path,
) -> None:
    appimage = _appimage(tmp_path)
    missing = tmp_path / "no-desktop-here"  # does not exist
    # Must not raise, and must not create the folder.
    ai.integrate(
        appimage,
        app_dir=tmp_path / "none",
        desktop_dir=tmp_path / "applications",
        icon_dir=tmp_path / "icons",
        desktop_folder=missing,
        refresh=lambda: None,
    )
    assert not missing.exists()


def test_integrate_without_icon_uses_stock_name(tmp_path: Path) -> None:
    appimage = _appimage(tmp_path)
    target = ai.integrate(
        appimage,
        app_dir=tmp_path / "empty",  # no icon present
        desktop_dir=tmp_path / "apps",
        icon_dir=tmp_path / "ic",
        desktop_folder=None,
        refresh=lambda: None,
    )
    assert "Icon=media-optical" in target.read_text()


# --- is_integrated --------------------------------------------------------


def test_is_integrated_matches_exec_path(tmp_path: Path) -> None:
    appimage = _appimage(tmp_path)
    desktop_dir = tmp_path / "applications"
    assert ai.is_integrated(appimage, desktop_dir) is False

    ai.integrate(
        appimage,
        app_dir=None,
        desktop_dir=desktop_dir,
        icon_dir=tmp_path / "icons",
        desktop_folder=None,
        refresh=lambda: None,
    )
    assert ai.is_integrated(appimage, desktop_dir) is True

    # A different AppImage path is NOT considered integrated (so a moved /
    # updated AppImage re-integrates rather than launching the old one).
    other = tmp_path / "whipper-gui-OLD.AppImage"
    other.write_bytes(b"x")
    assert ai.is_integrated(other, desktop_dir) is False
