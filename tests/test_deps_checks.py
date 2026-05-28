"""Tests for whipper_gui.deps.checks.

The probes shell out to real tools, so we test by patching `shutil.which`
and `subprocess.run` to deterministic stubs. The shape of each
ProbeResult is what we care about — not whether whipper itself runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whipper_gui.deps import checks
from whipper_gui.deps.checks import (
    ProbeResult,
    check_metaflac,
    check_picard_flatpak,
    check_python_pkg,
    check_whipper,
)


def _fake_run(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    """Build a fake `subprocess.run` return value."""
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# --- check_whipper ---


def test_check_whipper_missing_when_binary_absent(tmp_path: Path) -> None:
    probe = check_whipper(tmp_path / "does-not-exist")
    assert probe.present is False
    assert probe.version is None


def test_check_whipper_parses_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "whipper"
    binary.write_text("#!/bin/sh\necho 'whipper 0.10.0'\n")
    binary.chmod(0o755)

    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *a, **kw: _fake_run(stdout="whipper 0.10.0\n"),
    )

    probe = check_whipper(binary)
    assert probe.present is True
    assert probe.version == (0, 10, 0)
    assert probe.location == str(binary)


def test_check_whipper_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "whipper"
    binary.write_text("#!/bin/sh\nsleep 60\n")
    binary.chmod(0o755)

    def boom(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="whipper", timeout=10)

    monkeypatch.setattr(checks.subprocess, "run", boom)

    probe = check_whipper(binary)
    assert probe.present is False
    assert probe.version is None


# --- check_metaflac ---


def test_check_metaflac_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: None)

    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(checks.subprocess, "run", not_found)

    probe = check_metaflac()
    assert probe.present is False


def test_check_metaflac_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: "/usr/bin/metaflac")
    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *a, **kw: _fake_run(stdout="metaflac 1.4.3\n"),
    )

    probe = check_metaflac()
    assert probe.present is True
    assert probe.version == (1, 4, 3)
    assert probe.location == "/usr/bin/metaflac"


# --- check_picard_flatpak ---


def test_check_picard_flatpak_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: "/usr/bin/flatpak")
    output = (
        "MusicBrainz Picard - Picard\n"
        "ID:      org.musicbrainz.Picard\n"
        "Version: 2.11.0\n"
    )
    monkeypatch.setattr(
        checks.subprocess, "run", lambda *a, **kw: _fake_run(stdout=output)
    )

    probe = check_picard_flatpak()
    assert probe.present is True
    assert probe.version == (2, 11, 0)


def test_check_picard_flatpak_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: "/usr/bin/flatpak")
    # `flatpak info` for a missing app prints to stderr without "Version:".
    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *a, **kw: _fake_run(
            stdout="",
            stderr="error: org.musicbrainz.Picard not installed\n",
            returncode=1,
        ),
    )

    probe = check_picard_flatpak()
    assert probe.present is False


# --- check_python_pkg ---


def test_check_python_pkg_present() -> None:
    # `pytest` is definitely installed when this test runs.
    probe = check_python_pkg("pytest")
    assert probe.present is True
    assert probe.version is not None
    assert probe.location == "python: pytest"


def test_check_python_pkg_missing() -> None:
    probe = check_python_pkg("this-package-does-not-exist-9c8a")
    assert probe.present is False
    assert probe.version is None


# --- ProbeResult dataclass shape ---


def test_probe_result_is_frozen() -> None:
    probe = ProbeResult(present=True, version=(0, 1, 0), location="/x")
    with pytest.raises(Exception):
        probe.present = False  # type: ignore[misc]
