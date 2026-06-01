"""Smoke tests for install-appimage.sh.

The script integrates a downloaded AppImage into the desktop (menu entry +
icon). We can't run a real AppImage in CI, so we verify shape, help, syntax,
and that --uninstall is safe to run when nothing is installed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "install-appimage.sh"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_script_exists_and_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK), "install-appimage.sh is not executable"


def test_passes_bash_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_help_shows_usage() -> None:
    result = _run(["--help"])
    assert result.returncode == 0
    assert "install-appimage.sh" in result.stdout
    assert "--uninstall" in result.stdout


def test_uninstall_is_safe_with_nothing_installed(tmp_path: Path) -> None:
    # Point XDG/HOME at a temp dir so we don't touch the real desktop.
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / ".local" / "share")
    result = _run(["--uninstall"], env=env)
    assert result.returncode == 0
    assert "Removed" in result.stdout


def test_install_without_appimage_errors_clearly(tmp_path: Path) -> None:
    # Empty HOME and cwd → no AppImage to find → a helpful non-zero exit.
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / ".local" / "share")
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode != 0
    assert "Couldn't find" in result.stderr or "find a" in result.stderr


def test_install_creates_then_removes_uninstall_shortcut(tmp_path: Path) -> None:
    """A full install drops the AppImage, an app launcher, AND an 'Uninstall
    Whipper GUI' shortcut + a staged copy of uninstall.sh; --uninstall removes
    the integration again."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / ".local" / "share")

    # A stand-in AppImage (icon extraction fails → stock-icon fallback, fine).
    appimage = tmp_path / "whipper-gui-x86_64.AppImage"
    appimage.write_text("#!/bin/sh\necho fake\n")
    appimage.chmod(0o755)

    apps = tmp_path / "Applications"
    desktop_dir = tmp_path / ".local" / "share" / "applications"
    uninstall_desktop = desktop_dir / "whipper-gui-uninstall.desktop"
    staged_uninstaller = apps / "whipper-gui-uninstall.sh"

    install = _run([str(appimage)], env=env)
    assert install.returncode == 0, install.stderr
    assert uninstall_desktop.is_file()
    assert staged_uninstaller.is_file()
    # The shortcut runs the staged uninstaller.
    assert "whipper-gui-uninstall.sh" in uninstall_desktop.read_text()

    remove = _run(["--uninstall"], env=env)
    assert remove.returncode == 0, remove.stderr
    assert not uninstall_desktop.exists()
    assert not staged_uninstaller.exists()
