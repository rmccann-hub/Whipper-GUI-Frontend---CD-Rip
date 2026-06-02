"""Editable track table for pre-rip metadata.

Composite widget — album-level fields above a QTableView of per-track
data, backed by a custom QAbstractTableModel. The main window populates
the table from a ReleaseDetail and reads back the user-edited metadata
before kicking off a rip.

Layout:
  Album artist:  [_____________]
  Album title:   [_____________]
  Year:          [____]

  ┌─#─┬─Title──────────────┬─Artist──────────┬─Length─┐
  │ 1 │ Speak to Me        │ Pink Floyd      │  1:07  │
  │ 2 │ Breathe            │ Pink Floyd      │  2:45  │
  ...

Editable columns: Title, Artist. Track number and length are read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters.musicbrainz_client import ReleaseDetail, TrackSummary


@dataclass(frozen=True)
class AlbumMetadata:
    """Album-level fields edited above the track table."""

    artist: str = ""
    title: str = ""
    year: str = ""


# Column layout. Defined once so the model + view + tests share it.
_COLUMNS: list[str] = ["#", "Title", "Artist", "Length"]
_COL_NUMBER: int = 0
_COL_TITLE: int = 1
_COL_ARTIST: int = 2
_COL_LENGTH: int = 3
_EDITABLE_COLS: set[int] = {_COL_TITLE, _COL_ARTIST}


def _format_length(ms: int | None) -> str:
    """Render a track length in milliseconds as MM:SS."""
    if ms is None or ms < 0:
        return ""
    total_seconds = round(ms / 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:d}:{seconds:02d}"


class TrackTableModel(QAbstractTableModel):
    """QAbstractTableModel backing the track table.

    Holds a list of TrackSummary; allows editing of Title and Artist.
    TrackSummary is frozen, so edits go through dataclasses.replace.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tracks: list[TrackSummary] = []

    # --- Public surface ---

    def set_tracks(self, tracks: Sequence[TrackSummary]) -> None:
        """Replace the current track list. Resets the view."""
        self.beginResetModel()
        self._tracks = list(tracks)
        self.endResetModel()

    def tracks(self) -> list[TrackSummary]:
        """Return the current track list (with any user edits applied)."""
        return list(self._tracks)

    def set_all_artists(self, artist: str) -> None:
        """Set every track's artist to `artist` (album-artist propagation).

        Overwrites per-track artists in place and refreshes the Artist
        column. Callers invoke this when the album-artist field changes;
        the user can then still edit individual rows afterward.
        """
        if not self._tracks:
            return
        self._tracks = [
            replace(track, artist_credit=artist) for track in self._tracks
        ]
        top = self.index(0, _COL_ARTIST)
        bottom = self.index(len(self._tracks) - 1, _COL_ARTIST)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    # --- QAbstractTableModel overrides ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return _COLUMNS[section]
        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or role not in (
            Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole
        ):
            return None
        track = self._tracks[index.row()]
        col = index.column()
        if col == _COL_NUMBER:
            return str(track.number)
        if col == _COL_TITLE:
            return track.title
        if col == _COL_ARTIST:
            return track.artist_credit
        if col == _COL_LENGTH:
            return _format_length(track.length_ms)
        return None

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        col = index.column()
        if col not in _EDITABLE_COLS:
            return False
        text = str(value) if value is not None else ""
        row = index.row()
        existing = self._tracks[row]
        if col == _COL_TITLE:
            self._tracks[row] = replace(existing, title=text)
        elif col == _COL_ARTIST:
            self._tracks[row] = replace(existing, artist_credit=text)
        self.dataChanged.emit(index, index, [role])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.column() in _EDITABLE_COLS:
            return base | Qt.ItemFlag.ItemIsEditable
        return base


class TrackTable(QWidget):
    """Composite widget: album-level fields + track table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Album-level fields.
        album_form = QFormLayout()
        self._album_artist_edit: QLineEdit = QLineEdit(self)
        self._album_title_edit: QLineEdit = QLineEdit(self)
        self._album_year_edit: QLineEdit = QLineEdit(self)
        album_form.addRow("Album artist:", self._album_artist_edit)
        album_form.addRow("Album title:", self._album_title_edit)
        album_form.addRow("Year:", self._album_year_edit)
        root.addLayout(album_form)

        # Typing an album artist fills the per-track Artist column with it
        # (then individual rows can still be overridden). editingFinished —
        # not textChanged — so it fires once on focus-out/Enter, not on
        # every keystroke, and programmatic setText() (set_release /
        # set_placeholder_tracks) does NOT trigger it.
        self._album_artist_edit.editingFinished.connect(
            self._propagate_album_artist
        )

        # Track table.
        self._model: TrackTableModel = TrackTableModel(self)
        self._view: QTableView = QTableView(self)
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(True)
        # Title + Artist columns stretch; # + Length are content-sized.
        header = self._view.horizontalHeader()
        for col in range(len(_COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if col in _EDITABLE_COLS
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(col, mode)
        root.addWidget(self._view, stretch=1)

    # --- Public surface -----------------------------------------------------

    def set_release(self, detail: ReleaseDetail) -> None:
        """Populate from a MusicBrainz ReleaseDetail."""
        self._album_artist_edit.setText(detail.summary.artist_credit)
        self._album_title_edit.setText(detail.summary.title)
        self._album_year_edit.setText(detail.summary.date)
        self._model.set_tracks(detail.tracks)

    def set_placeholder_tracks(self, count: int) -> None:
        """Pre-fill placeholder metadata for a disc MusicBrainz can't ID.

        Album fields become "Unknown Artist" / "Unknown Album"; each of
        the `count` track rows gets a "Track NN" title and an "Unknown
        Artist" credit. This mirrors the placeholder tags the
        unknown-album rip actually writes (see
        `ui.unknown_album.apply_placeholder_tags`), so the table shows
        the user what will land on disk instead of empty rows.

        Editing these rows doesn't feed the rip yet — that's the P2
        follow-up tracked in TASKS.md.
        """
        self._album_artist_edit.setText("Unknown Artist")
        self._album_title_edit.setText("Unknown Album")
        self._album_year_edit.clear()
        if count <= 0:
            self._model.set_tracks([])
            return
        rows = [
            TrackSummary(
                number=n,
                title=f"Track {n:02d}",
                artist_credit="Unknown Artist",
            )
            for n in range(1, count + 1)
        ]
        self._model.set_tracks(rows)

    def highlight_track(self, track_number: int) -> None:
        """Select and scroll to the row for `track_number` (1-based).

        Called as a rip progresses so the table follows whipper track by
        track instead of staying wherever the user last clicked. The track
        rows are laid out 1..N in order, so row index == track_number - 1.
        Out-of-range numbers (e.g. a stray 0 before the first track, or a
        track beyond the loaded rows) are ignored rather than raising.
        """
        row = track_number - 1
        if row < 0 or row >= self._model.rowCount():
            return
        self._view.selectRow(row)
        self._view.scrollTo(
            self._model.index(row, _COL_NUMBER),
            QAbstractItemView.ScrollHint.EnsureVisible,
        )

    def clear(self) -> None:
        """Reset to the empty state (no album metadata, no tracks)."""
        self._album_artist_edit.clear()
        self._album_title_edit.clear()
        self._album_year_edit.clear()
        self._model.set_tracks([])

    def _propagate_album_artist(self) -> None:
        """Push the album-artist field into every track row's Artist cell."""
        self._model.set_all_artists(self._album_artist_edit.text())

    def album_metadata(self) -> AlbumMetadata:
        """Return the user's current album-level edits."""
        return AlbumMetadata(
            artist=self._album_artist_edit.text(),
            title=self._album_title_edit.text(),
            year=self._album_year_edit.text(),
        )

    def tracks(self) -> list[TrackSummary]:
        """Return the user's current track edits."""
        return self._model.tracks()

    def validate(self) -> tuple[bool, str]:
        """Validate that nothing required is blank.

        Returns (True, "") when everything's filled in; (False, message)
        with the first failure when not. The main window uses this
        before kicking off a rip.
        """
        if not self._album_artist_edit.text().strip():
            return False, "Album artist is required."
        if not self._album_title_edit.text().strip():
            return False, "Album title is required."
        tracks = self._model.tracks()
        if not tracks:
            return False, "No tracks loaded."
        for track in tracks:
            if not track.title.strip():
                return False, f"Track {track.number} is missing a title."
        return True, ""
