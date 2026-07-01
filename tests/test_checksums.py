"""Tests for platterpus.checksums — the SHA256 integrity digests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from platterpus import checksums


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_compute_digests_covers_audio_only(tmp_path: Path) -> None:
    _write(tmp_path / "01 - A.flac", b"flac-audio")
    _write(tmp_path / "01 - A.mp3", b"mp3-audio")
    _write(tmp_path / "album.log", b"log text")  # non-audio, excluded
    _write(tmp_path / "album.cue", b"cue text")  # non-audio, excluded

    digests = checksums.compute_digests(tmp_path)

    assert set(digests) == {"01 - A.flac", "01 - A.mp3"}
    assert digests["01 - A.flac"] == hashlib.sha256(b"flac-audio").hexdigest()


def test_compute_digests_uses_relative_posix_paths(tmp_path: Path) -> None:
    _write(tmp_path / "The Police" / "Album" / "01 - Roxanne.flac", b"x")
    digests = checksums.compute_digests(tmp_path)
    assert "The Police/Album/01 - Roxanne.flac" in digests


def test_compute_digests_matches_plain_sha256(tmp_path: Path) -> None:
    # The value must equal a straight SHA256 so any external checker agrees.
    data = b"some audio bytes" * 1000
    _write(tmp_path / "track.flac", data)
    digests = checksums.compute_digests(tmp_path)
    assert digests["track.flac"] == hashlib.sha256(data).hexdigest()


def test_compute_digests_empty_dir(tmp_path: Path) -> None:
    assert checksums.compute_digests(tmp_path) == {}


def test_compute_digests_missing_dir_returns_empty_not_raise(tmp_path: Path) -> None:
    assert checksums.compute_digests(tmp_path / "nope") == {}


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    data = b"hello world"
    p = tmp_path / "f.flac"
    p.write_bytes(data)
    assert checksums.sha256_file(p) == hashlib.sha256(data).hexdigest()
