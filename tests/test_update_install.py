"""Tests for the in-app update installer (update_install.py).

Driven through a fake opener — no network. The contract under test: the
published .sha256 gates the install (a corrupt download never replaces
anything), the swap is atomic via a .part file, and every failure path
cleans up after itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from whipper_gui.update_install import (
    UpdateInstallError,
    asset_url,
    download_and_install,
)

_PAYLOAD = b"new appimage bytes" * 1000


class _FakeResponse:
    """Stands in for urllib's response: read(n) streaming + context manager."""

    def __init__(self, body: bytes, content_length: bool = True) -> None:
        self._body = body
        self._pos = 0
        self.headers = {"Content-Length": str(len(body))} if content_length else {}

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._body)
        chunk = self._body[self._pos : self._pos + n]
        self._pos += n
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload: bytes = _PAYLOAD, sha: str | None = None):
    """An opener serving the AppImage and its .sha256 (correct by default)."""
    digest = sha if sha is not None else hashlib.sha256(payload).hexdigest()

    def open_url(url: str):
        if url.endswith(".sha256"):
            return _FakeResponse(f"{digest}  whipper-gui-x86_64.AppImage\n".encode())
        return _FakeResponse(payload)

    return open_url


def test_asset_url_points_at_the_release_tag() -> None:
    url = asset_url("0.2.3")
    assert "/releases/download/v0.2.3/whipper-gui-x86_64.AppImage" in url


def test_success_installs_atomically_and_is_executable(tmp_path: Path) -> None:
    seen: list[float] = []
    result = download_and_install(
        "0.2.3", dest_dir=tmp_path, progress=seen.append, opener=_opener()
    )

    assert result == tmp_path / "whipper-gui-x86_64.AppImage"
    assert result.read_bytes() == _PAYLOAD
    assert result.stat().st_mode & 0o111  # executable
    assert not (tmp_path / ".whipper-gui-update.part").exists()  # no leftovers
    assert seen and seen[-1] == pytest.approx(100.0)  # progress reached 100%


def test_status_reports_each_phase(tmp_path: Path) -> None:
    """The UI relies on phase labels so the quick post-download steps don't
    look like a freeze (real-user report 2026-06-13). Verify + install must
    each announce themselves, in order, after downloading."""
    phases: list[str] = []
    download_and_install(
        "0.2.3", dest_dir=tmp_path, status=phases.append, opener=_opener()
    )

    joined = " | ".join(phases)
    assert "Downloading" in joined
    assert "Verifying" in joined
    assert "Installing" in joined
    # Order: download before verify before install.
    download_i = next(i for i, p in enumerate(phases) if "Downloading" in p)
    verify_i = next(i for i, p in enumerate(phases) if "Verifying" in p)
    install_i = next(i for i, p in enumerate(phases) if "Installing" in p)
    assert download_i < verify_i < install_i


def test_checksum_mismatch_never_installs(tmp_path: Path) -> None:
    """The integrity gate: a corrupted/tampered download is discarded and
    the existing install is untouched."""
    existing = tmp_path / "whipper-gui-x86_64.AppImage"
    existing.write_bytes(b"the old version")
    bad = _opener(sha="0" * 64)  # plausible-looking but wrong checksum

    with pytest.raises(UpdateInstallError, match="checksum"):
        download_and_install("0.2.3", dest_dir=tmp_path, opener=bad)

    assert existing.read_bytes() == b"the old version"  # untouched
    assert not (tmp_path / ".whipper-gui-update.part").exists()  # cleaned up


def test_malformed_published_checksum_aborts_before_download(
    tmp_path: Path,
) -> None:
    def open_url(url: str):
        if url.endswith(".sha256"):
            return _FakeResponse(b"not-a-checksum\n")
        raise AssertionError("the big download must not start")

    with pytest.raises(UpdateInstallError, match="malformed"):
        download_and_install("0.2.3", dest_dir=tmp_path, opener=open_url)


def test_cancel_mid_download_cleans_up(tmp_path: Path) -> None:
    with pytest.raises(UpdateInstallError, match="cancelled"):
        download_and_install(
            "0.2.3", dest_dir=tmp_path, cancelled=lambda: True, opener=_opener()
        )
    assert not (tmp_path / ".whipper-gui-update.part").exists()
    assert not (tmp_path / "whipper-gui-x86_64.AppImage").exists()


def test_network_failure_raises_presentable_error(tmp_path: Path) -> None:
    def open_url(url: str):
        raise OSError("connection reset")

    with pytest.raises(UpdateInstallError, match="checksum"):
        download_and_install("0.2.3", dest_dir=tmp_path, opener=open_url)


def test_unknown_size_reports_indeterminate_progress(tmp_path: Path) -> None:
    def open_url(url: str):
        if url.endswith(".sha256"):
            digest = hashlib.sha256(_PAYLOAD).hexdigest()
            return _FakeResponse(f"{digest}  x\n".encode())
        return _FakeResponse(_PAYLOAD, content_length=False)

    seen: list[float] = []
    download_and_install(
        "0.2.3", dest_dir=tmp_path, progress=seen.append, opener=open_url
    )
    assert seen and all(p == -1.0 for p in seen)  # busy indicator, no bogus %
