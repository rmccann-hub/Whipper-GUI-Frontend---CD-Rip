# SPDX-License-Identifier: GPL-3.0-only
"""Tests for whipper_gui.ctdb.decode — host flac/metaflac wrappers (no real IO)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whipper_gui.ctdb import decode


def _completed(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_decode_raises_when_flac_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: None)
    with pytest.raises(decode.DecoderUnavailable):
        decode.decode_flac_to_pcm(Path("x.flac"))


def test_decode_returns_stdout_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/flac")
    pcm = b"\x01\x02\x03\x04"
    result = decode.decode_flac_to_pcm(
        Path("x.flac"), runner=lambda argv: _completed(0, stdout=pcm)
    )
    assert result == pcm


def test_decode_raises_on_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/flac")
    with pytest.raises(RuntimeError):
        decode.decode_flac_to_pcm(
            Path("x.flac"),
            runner=lambda argv: _completed(1, stderr=b"boom\n"),
        )


def test_flac_available_reflects_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/flac")
    assert decode.flac_available() is True
    monkeypatch.setattr(decode, "_which", lambda name: None)
    assert decode.flac_available() is False


def test_total_samples_parses_metaflac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/metaflac")
    out = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="17640\n", stderr=""
    )
    assert decode.total_samples(Path("a.flac"), runner=lambda argv: out) == 17640


def test_total_samples_unparseable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/metaflac")
    out = subprocess.CompletedProcess(args=[], returncode=0, stdout="??\n", stderr="")
    with pytest.raises(RuntimeError):
        decode.total_samples(Path("a.flac"), runner=lambda argv: out)


def test_total_samples_missing_metaflac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: None)
    with pytest.raises(decode.DecoderUnavailable):
        decode.total_samples(Path("a.flac"))


def test_total_samples_nonzero_rc_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decode, "_which", lambda name: "/usr/bin/metaflac")
    out = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")
    with pytest.raises(RuntimeError):
        decode.total_samples(Path("a.flac"), runner=lambda argv: out)


def test_which_falls_back_to_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # PATH lookup fails, but the binary exists at a known absolute location.
    monkeypatch.setattr(decode.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        decode.Path, "exists", lambda self: str(self) == "/usr/bin/flac"
    )
    assert decode._which("flac") == "/usr/bin/flac"


def test_which_returns_none_when_nothing_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decode.shutil, "which", lambda name: None)
    monkeypatch.setattr(decode.Path, "exists", lambda self: False)
    assert decode._which("flac") is None
