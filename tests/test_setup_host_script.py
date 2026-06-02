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


def test_opensuse_uses_zypper_for_distrobox_and_backend(tmp_path: Path) -> None:
    """On openSUSE the script installs Distrobox + podman via zypper.

    Distro detection reads OS_RELEASE_FILE (defaults to /etc/os-release),
    so we point it at an openSUSE fixture and confirm the dry-run picks the
    zypper branch instead of the upstream-installer fallback.
    """
    os_release = tmp_path / "os-release"
    os_release.write_text('ID="opensuse-tumbleweed"\nID_LIKE="suse opensuse"\n')
    env = dict(os.environ)
    env["OS_RELEASE_FILE"] = str(os_release)
    result = subprocess.run(
        ["bash", str(SETUP), "--dry-run", "--yes", "--no-gui"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # At least the Distrobox install path is exercised on a host without
    # distrobox; assert the zypper branch was taken, not the curl fallback.
    assert "zypper --non-interactive install distrobox" in out
    assert "upstream installer" not in out


def test_both_install_paths_offer_a_zypper_branch() -> None:
    """Static guard: both the Distrobox and backend installers handle suse."""
    text = SETUP.read_text()
    assert "*suse*)" in text
    assert text.count("zypper --non-interactive install") >= 2
