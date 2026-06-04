"""Tests for whipper_gui.adapters.metaflac.

`metaflac` is shelled out at runtime; tests monkeypatch subprocess so
they're hermetic and don't require a real metaflac install.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whipper_gui.adapters import metaflac as metaflac_module
from whipper_gui.adapters.metaflac import MetaflacAdapter, MetaflacError


def _ok(stdout: str = "") -> Any:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def _fail(stderr: str = "boom\n") -> Any:
    return SimpleNamespace(stdout="", stderr=stderr, returncode=1)


# --- read_tags ------------------------------------------------------------


def test_read_tags_parses_key_value_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = (
        "ARTIST=Pink Floyd\n"
        "TITLE=Speak to Me\n"
        "ALBUM=The Dark Side of the Moon\n"
        "TRACKNUMBER=01\n"
    )
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> Any:
        captured.append(argv)
        return _ok(stdout=sample)

    monkeypatch.setattr(metaflac_module.subprocess, "run", fake_run)

    adapter = MetaflacAdapter()
    tags = adapter.read_tags(Path("/x/track.flac"))

    assert tags == {
        "ARTIST": "Pink Floyd",
        "TITLE": "Speak to Me",
        "ALBUM": "The Dark Side of the Moon",
        "TRACKNUMBER": "01",
    }
    assert captured[0] == ["metaflac", "--export-tags-to=-", "/x/track.flac"]


def test_read_tags_ignores_lines_without_equals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = "ARTIST=Pink Floyd\ngarbage-line-without-equals\nTITLE=Track\n"
    monkeypatch.setattr(
        metaflac_module.subprocess, "run", lambda *a, **kw: _ok(stdout=sample)
    )

    tags = MetaflacAdapter().read_tags(Path("/x/track.flac"))

    assert tags == {"ARTIST": "Pink Floyd", "TITLE": "Track"}


def test_read_tags_duplicate_keys_keep_last_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = "ARTIST=First\nARTIST=Second\n"
    monkeypatch.setattr(
        metaflac_module.subprocess, "run", lambda *a, **kw: _ok(stdout=sample)
    )

    tags = MetaflacAdapter().read_tags(Path("/x/track.flac"))

    assert tags == {"ARTIST": "Second"}


# --- write_tags -----------------------------------------------------------


def test_write_tags_emits_remove_then_set_for_each_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> Any:
        captured.append(argv)
        return _ok()

    monkeypatch.setattr(metaflac_module.subprocess, "run", fake_run)

    MetaflacAdapter().write_tags(
        Path("/x/track.flac"),
        {"ARTIST": "Pink Floyd", "TITLE": "Breathe"},
    )

    argv = captured[0]
    assert argv[0] == "metaflac"
    # All --remove-tag come before all --set-tag.
    remove_indices = [i for i, a in enumerate(argv) if a.startswith("--remove-tag")]
    set_indices = [i for i, a in enumerate(argv) if a.startswith("--set-tag")]
    assert all(r < s for r in remove_indices for s in set_indices)
    # Path is last.
    assert argv[-1] == "/x/track.flac"
    # Both keys appear in remove and set forms.
    assert "--remove-tag=ARTIST" in argv
    assert "--remove-tag=TITLE" in argv
    assert "--set-tag=ARTIST=Pink Floyd" in argv
    assert "--set-tag=TITLE=Breathe" in argv


def test_write_tags_is_noop_for_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []

    def fake_run(*a: Any, **kw: Any) -> Any:
        called.append(True)
        return _ok()

    monkeypatch.setattr(metaflac_module.subprocess, "run", fake_run)

    MetaflacAdapter().write_tags(Path("/x/track.flac"), {})

    assert called == []


# --- Error handling -------------------------------------------------------


def test_read_tags_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        metaflac_module.subprocess,
        "run",
        lambda *a, **kw: _fail(stderr="ERROR: bad FLAC\n"),
    )

    with pytest.raises(MetaflacError) as info:
        MetaflacAdapter().read_tags(Path("/x/bad.flac"))
    assert "bad FLAC" in str(info.value)


def test_raises_when_metaflac_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError("metaflac")

    monkeypatch.setattr(metaflac_module.subprocess, "run", not_found)

    with pytest.raises(MetaflacError) as info:
        MetaflacAdapter().read_tags(Path("/x/track.flac"))
    assert "not found" in str(info.value)


def test_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="metaflac", timeout=30)

    monkeypatch.setattr(metaflac_module.subprocess, "run", boom)

    with pytest.raises(MetaflacError) as info:
        MetaflacAdapter().read_tags(Path("/x/track.flac"))
    assert "timed out" in str(info.value)


# --- Constructor with custom binary --------------------------------------


def test_custom_binary_path_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> Any:
        captured.append(argv)
        return _ok()

    monkeypatch.setattr(metaflac_module.subprocess, "run", fake_run)

    MetaflacAdapter(binary_name="/opt/flac/bin/metaflac").read_tags(
        Path("/x/track.flac")
    )
    assert captured[0][0] == "/opt/flac/bin/metaflac"
