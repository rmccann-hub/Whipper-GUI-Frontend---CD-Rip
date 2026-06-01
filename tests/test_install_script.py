"""Smoke tests for install.sh — the one-file end-user installer.

We can't run a real install in CI (Distrobox, network, a real AppImage), so we
verify shape, help, syntax, and that --dry-run narrates the three steps without
touching the filesystem.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "install.sh"


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
    assert os.access(SCRIPT, os.X_OK), "install.sh is not executable"


def test_passes_bash_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_help_shows_usage() -> None:
    result = _run(["--help"])
    assert result.returncode == 0
    assert "install.sh" in result.stdout
    assert "--appimage" in result.stdout
    assert "--no-host" in result.stdout


def test_dry_run_narrates_three_steps_without_touching_fs(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / ".local" / "share")
    result = _run(["--dry-run", "--yes"], env=env)
    assert result.returncode == 0, result.stderr
    # The three phases are announced...
    assert "1/3" in result.stdout and "2/3" in result.stdout and "3/3" in result.stdout
    # ...and everything is a DRY-RUN line, so nothing was created under HOME.
    assert "DRY-RUN" in result.stdout
    assert not (tmp_path / "Applications").exists()


def test_unknown_flag_errors() -> None:
    result = _run(["--bogus"])
    assert result.returncode != 0
