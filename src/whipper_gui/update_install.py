"""Download-verify-install for app updates (KDD-17b amendment, 2026-06-10).

KDD-17 originally rejected a built-in downloader in favour of delegating to
AppImageUpdate. Real-world testing changed the call: `appimageupdatetool`
isn't installed on the target systems (and isn't easily installable on
atomic distros), so "Check for updates" dead-ended in a browser download,
a manual file swap, and a stale menu entry — the user asked for true
in-app updating. This module does it, with the release's published
`.sha256` as the integrity gate:

  1. fetch ``<release>/whipper-gui-x86_64.AppImage.sha256``  (tiny)
  2. stream the AppImage to ``<dest>/.whipper-gui-update.part``
     (progress + cancel callbacks between chunks)
  3. verify the download's SHA-256 against step 1 — mismatch → abort+delete
  4. mark executable, then atomically rename over
     ``~/Applications/whipper-gui-x86_64.AppImage``

Replacing the file the app is currently running from is safe on Linux (the
runtime holds the old inode open); the caller offers a restart afterwards.
The zsync update-information stays embedded in our builds, so delta updates
via AppImageUpdate remain possible for users who have that tool.
"""

from __future__ import annotations

import hashlib
import http.client
import logging
import urllib.request
from collections.abc import Callable
from pathlib import Path

from whipper_gui.appimage_integration import (
    APPLICATIONS_DIR,
    CANONICAL_APPIMAGE_NAME,
)

log = logging.getLogger(__name__)

_REPO_SLUG: str = "rmccann-hub/Whipper-GUI-Frontend---CD-Rip"
_CHUNK_BYTES: int = 1024 * 1024  # 1 MiB per read → progress/cancel granularity
_TIMEOUT_S: float = 30.0  # per network operation (connect/read stall)


class UpdateInstallError(Exception):
    """Any failure installing an update. The message is user-presentable."""


def asset_url(version: str) -> str:
    """The published AppImage URL for release `version` (e.g. "0.2.3")."""
    return (
        f"https://github.com/{_REPO_SLUG}/releases/download/"
        f"v{version}/{CANONICAL_APPIMAGE_NAME}"
    )


def _default_open(url: str) -> http.client.HTTPResponse:
    """Open a streaming HTTP response (callers read() it in chunks)."""
    request = urllib.request.Request(url, headers={"User-Agent": "whipper-gui"})
    return urllib.request.urlopen(request, timeout=_TIMEOUT_S)


def download_and_install(
    version: str,
    dest_dir: Path = APPLICATIONS_DIR,
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    opener: Callable[[str], object] | None = None,
    status: Callable[[str], None] | None = None,
) -> Path:
    """Download release `version`, verify it, install it. Returns the path.

    `progress` gets a percentage (0–100), or -1.0 when the server didn't
    say how big the file is. `cancelled` is polled between chunks. `status`
    gets a short phase label ("Downloading…", "Verifying…", "Installing…")
    so the UI can tell the user what's happening — the post-download phases
    are quick but used to look like a freeze. Raises
    :class:`UpdateInstallError` on any failure — after cleaning up the
    partial download, and never having touched the existing install.
    """
    open_url = opener or _default_open
    url = asset_url(version)
    target = dest_dir / CANONICAL_APPIMAGE_NAME
    part = dest_dir / ".whipper-gui-update.part"

    def _status(message: str) -> None:
        if status is not None:
            status(message)

    # 1. The published checksum is the integrity gate for the download.
    _status("Checking for the update…")
    try:
        with open_url(url + ".sha256") as response:
            expected = response.read().decode("utf-8").split()[0].strip().lower()
    except Exception as exc:  # noqa: BLE001 — network/shape errors alike
        raise UpdateInstallError(f"couldn't fetch the update checksum: {exc}") from exc
    if len(expected) != 64:
        raise UpdateInstallError("the published checksum looks malformed")

    # 2. Stream the AppImage to a .part file next to the final location
    # (same filesystem → the final rename is atomic).
    _status(f"Downloading Whipper GUI {version}…")
    digest = hashlib.sha256()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with open_url(url) as response, open(part, "wb") as out:
            total = int(getattr(response, "headers", {}).get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateInstallError("update cancelled")
                chunk = response.read(_CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done * 100.0 / total if total else -1.0)
    except UpdateInstallError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 — any I/O or network failure
        part.unlink(missing_ok=True)
        raise UpdateInstallError(f"download failed: {exc}") from exc

    # 3. Verify BEFORE touching the existing install.
    _status("Verifying the download…")
    actual = digest.hexdigest().lower()
    if actual != expected:
        part.unlink(missing_ok=True)
        raise UpdateInstallError(
            "the downloaded file failed checksum verification — not installed "
            f"(expected {expected[:12]}…, got {actual[:12]}…)"
        )

    # 4. Make it launchable and atomically swap it in. Replacing the file
    # the app is running from is safe — the old session keeps its inode.
    _status("Installing — almost done, please don't close…")
    try:
        part.chmod(0o755)
        part.replace(target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise UpdateInstallError(f"couldn't install the update: {exc}") from exc

    log.info("installed update v%s at %s", version, target)
    return target
