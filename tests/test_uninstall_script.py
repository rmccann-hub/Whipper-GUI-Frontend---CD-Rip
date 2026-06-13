"""Smoke tests for uninstall.sh.

The script removes things from the live filesystem and can't be
exercised end-to-end in unit tests. We verify shape and behavior
through --help and --dry-run output instead.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNINSTALL = REPO_ROOT / "uninstall.sh"


def _run(
    args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run uninstall.sh with args; return the completed process.

    `env` overrides are merged onto the current environment — used to
    point $HOME at a tmp dir so $HOME-based removals can be exercised
    without touching the real home directory.
    """
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(UNINSTALL), *args],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )


def test_script_exists_and_is_executable() -> None:
    assert UNINSTALL.is_file()
    assert os.access(UNINSTALL, os.X_OK), "uninstall.sh is not executable"


def test_help_exits_zero_and_shows_usage() -> None:
    result = _run(["--help"])
    assert result.returncode == 0
    assert "Uninstall Whipper GUI" in result.stdout
    assert "--full" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--remove-rips" in result.stdout


def test_unknown_flag_exits_non_zero() -> None:
    result = _run(["--bogus-flag"])
    assert result.returncode != 0
    assert "Unknown option" in result.stderr or "Unknown option" in result.stdout


def test_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    """A --dry-run --yes invocation should be a no-op (in particular,
    it must NOT delete the script's own repo or the test's tmp_path)."""
    # Touch a sentinel file inside the repo to be sure dry-run doesn't
    # clobber it.
    sentinel = REPO_ROOT / ".dry-run-sentinel"
    sentinel.write_text("kept")
    try:
        result = _run(["--yes", "--dry-run"])
        assert result.returncode == 0
        assert sentinel.exists()
        assert "DRY RUN" in result.stdout
    finally:
        sentinel.unlink(missing_ok=True)


def test_dry_run_full_shows_what_would_be_removed() -> None:
    """--full + --dry-run should mention each optional removal in the output."""
    result = _run(["--yes", "--dry-run", "--full"])
    assert result.returncode == 0
    out = result.stdout
    # Header signals dry-run mode
    assert "DRY RUN" in out
    # Each of the four optional categories must show up
    for category in [
        "Picard",
        "Distrobox",
        ".config/whipper",  # the whipper config dir (calibration + .bak)
        "whipper",  # also in the host-exported wrapper section
    ]:
        assert category in out, f"category {category!r} missing from output"


def test_full_removes_whipper_config_dir_including_bak(tmp_path: Path) -> None:
    """Regression (2026-06-13): a `--full` uninstall must remove the whole
    ~/.config/whipper/ directory, not just whipper.conf — otherwise the
    drive-setup wizard's whipper.conf.bak survives and a "fresh" reinstall
    isn't actually fresh. A real user hit exactly this leftover.
    """
    home = tmp_path / "home"
    whipper_dir = home / ".config" / "whipper"
    whipper_dir.mkdir(parents=True)
    (whipper_dir / "whipper.conf").write_text("offset = 667\n")
    (whipper_dir / "whipper.conf.bak").write_text("offset = 0\n")

    result = _run(["--yes", "--dry-run", "--full"], env={"HOME": str(home)})

    assert result.returncode == 0
    # The planned action must be an `rm -rf` of the directory itself (which
    # inherently covers whipper.conf.bak), not a file-only `rm -f`.
    planned = [
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("DRY-RUN:")
    ]
    assert any("rm -rf" in line and str(whipper_dir) in line for line in planned), (
        f"whipper config dir not planned for recursive removal; planned={planned}"
    )


def test_dry_run_does_not_touch_rips_without_explicit_flag() -> None:
    """Music files must never be a planned removal without --remove-rips,
    even when --full is set."""
    result = _run(["--yes", "--dry-run", "--full"])
    assert result.returncode == 0
    # Music/rips can appear in the footer note ("use --remove-rips if
    # you really want to") but MUST NOT appear in any "DRY-RUN: rm"
    # planned-action line.
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("DRY-RUN:"):
            assert "Music/rips" not in line, (
                f"Music/rips planned for removal without --remove-rips: {line!r}"
            )
    # The 'Type DELETE' confirmation prompt only appears via --remove-rips
    # in interactive mode; it must not be in --full's output.
    assert "Type 'DELETE'" not in result.stdout
