"""Smoke tests for setup-host.sh.

The script provisions a Distrobox container and installs system packages,
so it can't be run for real in CI. We verify shape and that --dry-run is a
true no-op (prints commands, changes nothing).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "setup-host.sh"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists_and_is_executable() -> None:
    assert SETUP.is_file()
    assert os.access(SETUP, os.X_OK), "setup-host.sh is not executable"


def test_passes_bash_syntax_check() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SETUP)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_help_exits_zero_and_shows_usage() -> None:
    result = _run(["--help"])
    assert result.returncode == 0
    assert "setup-host.sh" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--no-gui" in result.stdout


def test_unknown_flag_exits_non_zero() -> None:
    result = _run(["--bogus"])
    assert result.returncode != 0
    assert "Unknown option" in result.stderr or "Unknown option" in result.stdout


def test_dry_run_prints_all_steps_without_executing() -> None:
    result = _run(["--dry-run", "--yes"])
    assert result.returncode == 0
    out = result.stdout
    assert "DRY RUN" in out
    # Every mutating command must be a DRY-RUN line, never executed.
    assert "DRY-RUN: distrobox create" in out
    assert "DRY-RUN: distrobox enter ripping -- sudo dnf install -y whipper" in out
    assert "distrobox-export --bin /usr/bin/whipper" in out
    # Run from this checkout → it must NOT try to clone.
    assert "git clone" not in out
    assert "Running from a checkout" in out


def test_dry_run_checks_for_a_container_backend() -> None:
    # Distrobox needs podman/docker; the script must verify a backend exists
    # before trying to create the container (the Ubuntu install gotcha).
    result = _run(["--dry-run", "--yes", "--no-gui"])
    assert result.returncode == 0
    assert "container backend" in result.stdout


def test_dry_run_no_gui_skips_install_step() -> None:
    result = _run(["--dry-run", "--yes", "--no-gui"])
    assert result.returncode == 0
    assert "skipped (--no-gui)" in result.stdout
    assert "dev-setup.sh" not in result.stdout


def test_custom_container_and_image_are_used() -> None:
    result = _run(
        ["--dry-run", "--yes", "--container", "myrip", "--image", "fedora:41"]
    )
    assert result.returncode == 0
    assert "--name myrip --image fedora:41" in result.stdout
