"""Release picker dialog — substitutes for whipper's interactive TTY prompt.

Critical Rule #5: when MusicBrainz returns multiple matches for the
inserted disc, the GUI presents them in this dialog and obtains the
chosen MBID — whipper is then invoked with `--release-id <MBID>` and
never opens a prompt.

The dialog is a pure picker: it doesn't do MB lookups itself. The
caller passes in a list[ReleaseSummary] (typically from the
MusicBrainzWorker) and reads back the chosen MBID via
`selected_mbid()` after the dialog accepts.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters.musicbrainz_client import ReleaseSummary


# Column layout for the candidates table. Defined once so the test can
# assert on positions without magic numbers.
_COLUMNS: list[tuple[str, str]] = [
    # (header label, attribute on ReleaseSummary)
    ("Title", "title"),
    ("Artist", "artist_credit"),
    ("Year", "date"),
    ("Country", "country"),
    ("Label", "label"),
    ("Catalog #", "catalog_number"),
    ("Tracks", "track_count"),
    ("Format", "medium_format"),
    ("Notes", "disambiguation"),
]


class ReleasePickerDialog(QDialog):
    """Modal picker shown when MusicBrainz returns >1 release candidate."""

    def __init__(
        self,
        releases: Sequence[ReleaseSummary],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._releases: list[ReleaseSummary] = list(releases)

        self.setWindowTitle("Pick a MusicBrainz release")
        self.setModal(True)
        # Generous default size; users frequently have long album titles.
        self.resize(900, 380)

        root = QVBoxLayout(self)

        intro = QLabel(
            f"MusicBrainz returned {len(self._releases)} matches. "
            "Pick the release that matches the disc in the drive."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._table: QTableWidget = QTableWidget(
            len(self._releases), len(_COLUMNS), self
        )
        self._table.setHorizontalHeaderLabels(
            [header for header, _ in _COLUMNS]
        )
        # Select whole rows, one at a time — the user is picking a
        # release, not editing cells.
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        # Stretch the Title and Artist columns; the rest fit content.
        header = self._table.horizontalHeader()
        for i in range(len(_COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if i in (0, 1)
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(i, mode)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        self._populate_rows()
        root.addWidget(self._table, stretch=1)

        # Double-click on a row accepts the dialog (matches OS pattern
        # for "pick from list" dialogs).
        self._table.itemDoubleClicked.connect(lambda _: self.accept())

        # Button box. Pick is the primary; we default to row 0 so the
        # user can just press Enter to accept the top result.
        self._button_box: QDialogButtonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Pick this release"
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        root.addWidget(self._button_box)

        # Default selection: row 0 if any rows exist.
        if self._releases:
            self._table.selectRow(0)

    # --- Public surface -----------------------------------------------------

    def selected_mbid(self) -> str | None:
        """Return the MBID of the selected row, or None if nothing selected."""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._releases):
            return None
        return self._releases[row].mbid

    def selected_release(self) -> ReleaseSummary | None:
        """Return the full ReleaseSummary of the selected row, or None."""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._releases):
            return None
        return self._releases[row]

    # --- Internals ---------------------------------------------------------

    def _populate_rows(self) -> None:
        for row, release in enumerate(self._releases):
            for col, (_, attr) in enumerate(_COLUMNS):
                value = getattr(release, attr, "")
                if value is None:
                    text = ""
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                # Cells aren't editable but should support copy via
                # selection (per the disc_info_panel precedent).
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsEditable
                )
                self._table.setItem(row, col, item)
