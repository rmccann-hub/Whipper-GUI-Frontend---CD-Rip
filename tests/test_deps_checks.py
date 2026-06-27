"""Tests for whipper_gui.deps.checks.

The probes shell out to real tools, so we test by patching `shutil.which`
and `subprocess.run` to deterministic stubs. The shape of each
ProbeResult is what we care about — not whether whipper itself runs.
"""

from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whipper_gui.deps import checks
from whipper_gui.deps.checks import (
    ProbeResult,
    check_ffmpeg,
    check_flac,
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


def test_check_whipper_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "whipper"
    binary.write_text("#!/bin/sh\nsleep 60\n")
    binary.chmod(0o755)

    def boom(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="whipper", timeout=10)

    monkeypatch.setattr(checks.subprocess, "run", boom)

    probe = check_whipper(binary)
    assert probe.present is False
    assert probe.version is None


def test_probe_timeout_budgets_for_cold_container() -> None:
    """The launch probe timeout must tolerate a Distrobox container cold-start.

    Regression guard (real-user report, Bazzite + BDR-209D, 2026-06-27): the
    first `whipper --version` of a session starts the `ripping` container, which
    can take tens of seconds. The old 10s cap made a cold container look like a
    MISSING whipper at launch and left it cold for the disc scan. Keep this
    high enough that the launch probe waits for the container to come up (which
    also warms it for the scan that follows). Native-binary probes return in ms
    regardless, so the larger ceiling only bites a cold-start or a wedged tool.
    """
    assert checks._PROBE_TIMEOUT_S >= 45.0


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


# --- check_flac ---


def test_check_flac_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: None)

    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(checks.subprocess, "run", not_found)

    probe = check_flac()
    assert probe.present is False


def test_check_flac_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: "/usr/bin/flac")
    monkeypatch.setattr(
        checks.subprocess,
        "run",
        lambda *a, **kw: _fake_run(stdout="flac 1.4.3\n"),
    )

    probe = check_flac()
    assert probe.present is True
    assert probe.version == (1, 4, 3)
    assert probe.location == "/usr/bin/flac"


# --- check_ffmpeg ---


def test_check_ffmpeg_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: None)

    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(checks.subprocess, "run", not_found)

    probe = check_ffmpeg()
    assert probe.present is False
    assert probe.version is None


def test_check_ffmpeg_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checks.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    captured: dict[str, Any] = {}

    def fake_run(argv: Any, *a: Any, **kw: Any) -> Any:
        captured["argv"] = argv
        # ffmpeg prints its banner to the version flag.
        return _fake_run(stdout="ffmpeg version 6.1.1-3ubuntu5 Copyright (c)\n")

    monkeypatch.setattr(checks.subprocess, "run", fake_run)

    probe = check_ffmpeg()
    assert probe.present is True
    assert probe.version == (6, 1, 1)
    assert probe.location == "/usr/bin/ffmpeg"
    # ffmpeg uses single-dash `-version`, not GNU `--version`.
    assert captured["argv"] == ["ffmpeg", "-version"]


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
    with pytest.raises(FrozenInstanceError):
        probe.present = False  # type: ignore[misc]


# --- check_libdiscid (ctypes-driven; monkeypatch the loader) --------------


def test_check_libdiscid_absent_when_no_variant_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SONAME resolves / loads → present=False (the documented default;
    whipper computes the disc ID in-container, so this is the common case)."""
    import ctypes
    import ctypes.util

    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)

    def no_load(_name: str):
        raise OSError("not found")

    monkeypatch.setattr(ctypes, "CDLL", no_load)

    result = checks.check_libdiscid()
    assert result.present is False
    assert result.version is None
    assert result.location is None


def test_check_libdiscid_present_with_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SONAME that loads and answers discid_get_version_string() → present,
    with the parsed version and the SONAME as the location."""
    import ctypes
    import ctypes.util

    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: "libdiscid.so.0")

    class _FakeLib:
        class discid_get_version_string:  # noqa: N801 — mimics a ctypes func
            restype = None

            def __call__(self) -> bytes:
                return b"libdiscid 0.6.2"

        def __init__(self) -> None:
            # ctypes accesses lib.discid_get_version_string as an attribute
            # and sets .restype on it, then calls it — model that.
            self.discid_get_version_string = _FakeLib.discid_get_version_string()

    monkeypatch.setattr(ctypes, "CDLL", lambda _name: _FakeLib())

    result = checks.check_libdiscid()
    assert result.present is True
    assert result.location == "libdiscid.so.0"
    assert result.version is not None  # parse_version extracted something


def test_check_libdiscid_present_but_version_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Library loads but the version symbol is missing → still present, with
    an empty version string (the AttributeError branch)."""
    import ctypes
    import ctypes.util

    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)

    class _NoVersionLib:
        def __getattr__(self, _name: str):  # any symbol access raises
            raise AttributeError("no such symbol")

    monkeypatch.setattr(ctypes, "CDLL", lambda _name: _NoVersionLib())

    result = checks.check_libdiscid()
    assert result.present is True
    assert result.raw_output == ""
