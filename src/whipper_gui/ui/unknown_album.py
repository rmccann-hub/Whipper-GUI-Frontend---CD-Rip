"""Unknown-album flow — dialog confirming the rip + helper functions.

When MusicBrainz returns no matches for the inserted disc, the user
can choose to rip anyway with placeholder tags (whipper's `--unknown`
mode). This module provides:

- `UnknownAlbumDialog` — modal confirmation. Lets the user toggle
  "auto-launch Picard" before committing.
- `apply_track_tags(metaflac, flac_files, album, tracks)` — writes the
  (possibly user-edited) album + per-track fields from the track table
  to the FLACs, falling back to the "Track NN" / "Unknown Album" /
  "Unknown Artist" placeholders for blank fields. This is the path the
  main window uses after an unknown rip.
- `apply_placeholder_tags(metaflac, flac_files)` — the simpler no-edits
  path: always writes the placeholder template.
- `launch_picard_for(folder)` — runs `flatpak run org.musicbrainz.Picard`
  with the rip folder as an argument. Returns True on success.

The main window orchestrates: it shows the dialog, kicks off the rip
with `unknown=True`, tags the FLACs from the track table after the rip
finishes, and optionally invokes Picard.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters.metaflac import MetaflacAdapter, MetaflacError

if TYPE_CHECKING:  # avoid importing Qt-heavy track_table at runtime
    from whipper_gui.adapters.musicbrainz_client import TrackSummary
    from whipper_gui.ui.track_table import AlbumMetadata

log = logging.getLogger(__name__)


# Picard's Flatpak app ID. Single constant so the dependency registry
# and this module agree on the spelling.
_PICARD_FLATPAK_ID: str = "org.musicbrainz.Picard"


class UnknownAlbumDialog(QDialog):
    """Modal confirmation before running an unknown-album rip."""

    def __init__(
        self,
        auto_launch_picard_default: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rip as unknown album")
        self.setModal(True)

        root = QVBoxLayout(self)

        intro = QLabel(
            "MusicBrainz has no record of this disc. You can still rip "
            "it now with placeholder tags (Track 01, Track 02, …). "
            "You can edit the tags later in MusicBrainz Picard."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._picard_check: QCheckBox = QCheckBox(
            "Launch MusicBrainz Picard when the rip finishes", self
        )
        self._picard_check.setChecked(auto_launch_picard_default)
        root.addWidget(self._picard_check)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Rip as unknown")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    # --- Public surface -----------------------------------------------------

    def auto_launch_picard(self) -> bool:
        """Whether the user wants Picard to open after the rip."""
        return self._picard_check.isChecked()


# --- Helper functions -------------------------------------------------------


def apply_placeholder_tags(
    metaflac: MetaflacAdapter,
    flac_files: Sequence[Path],
) -> list[Path]:
    """Apply "Track NN" placeholder tags to each FLAC.

    Tags written per file:
        TITLE       = Track NN
        ARTIST      = Unknown Artist
        ALBUM       = Unknown Album
        TRACKNUMBER = NN

    Returns the list of files that succeeded. Files that fail
    individually are logged at WARNING; we don't abort the whole batch
    because partial placeholders are still better than no tags at all.
    """
    succeeded: list[Path] = []
    for index, flac_path in enumerate(flac_files, start=1):
        number = f"{index:02d}"
        tags = {
            "TITLE": f"Track {number}",
            "ARTIST": "Unknown Artist",
            "ALBUM": "Unknown Album",
            "TRACKNUMBER": number,
        }
        try:
            metaflac.write_tags(flac_path, tags)
            succeeded.append(flac_path)
        except MetaflacError as exc:
            log.warning("placeholder tag write failed for %s: %s", flac_path, exc)
    return succeeded


def apply_track_tags(
    metaflac: MetaflacAdapter,
    flac_files: Sequence[Path],
    album: AlbumMetadata,
    tracks: Sequence[TrackSummary],
) -> list[Path]:
    """Apply the user's (possibly edited) album + per-track tags to FLACs.

    This is the edit-aware version of `apply_placeholder_tags`: it reads
    whatever the user typed into the track table for an unknown disc and
    writes it to the FLACs after the rip. Files are matched to table rows
    by track number (both are in track order). Any blank field falls back
    to the unknown-album placeholder, so a half-filled table still yields
    complete, sensible tags rather than empty ones.

    Tags written per file:
        TITLE        = edited title          (fallback "Track NN")
        ARTIST       = edited track artist   (fallback album artist)
        ALBUM        = edited album title    (fallback "Unknown Album")
        ALBUMARTIST  = edited album artist   (fallback "Unknown Artist")
        TRACKNUMBER  = NN
        DATE         = edited year           (omitted when blank)

    Returns the list of files that tagged successfully; per-file failures
    are logged at WARNING without aborting the batch.
    """
    album_artist = (album.artist or "").strip() or "Unknown Artist"
    album_title = (album.title or "").strip() or "Unknown Album"
    album_year = (album.year or "").strip()
    by_number = {track.number: track for track in tracks}

    succeeded: list[Path] = []
    for index, flac_path in enumerate(flac_files, start=1):
        number = f"{index:02d}"
        track = by_number.get(index)
        title = (track.title or "").strip() if track else ""
        artist = (track.artist_credit or "").strip() if track else ""
        tags = {
            "TITLE": title or f"Track {number}",
            "ARTIST": artist or album_artist,
            "ALBUM": album_title,
            "ALBUMARTIST": album_artist,
            "TRACKNUMBER": number,
        }
        if album_year:
            tags["DATE"] = album_year
        try:
            metaflac.write_tags(flac_path, tags)
            succeeded.append(flac_path)
        except MetaflacError as exc:
            log.warning("tag write failed for %s: %s", flac_path, exc)
    return succeeded


def launch_picard_for(folder: Path) -> bool:
    """Launch MusicBrainz Picard via Flatpak with `folder` as an argument.

    Returns True if the subprocess started, False on FileNotFoundError
    (flatpak missing) or OSError. Doesn't block — Picard runs detached.
    """
    argv: list[str] = [
        "flatpak",
        "run",
        _PICARD_FLATPAK_ID,
        str(folder),
    ]
    try:
        subprocess.Popen(argv)
    except (FileNotFoundError, OSError) as exc:
        log.warning("launch_picard_for(%s) failed: %s", folder, exc)
        return False
    return True
