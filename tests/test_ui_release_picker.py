"""Tests for whipper_gui.ui.release_picker."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from whipper_gui.adapters.musicbrainz_client import ReleaseSummary
from whipper_gui.ui.release_picker import ReleasePickerDialog, _COLUMNS


def _release(
    mbid: str = "mbid-x",
    title: str = "Album",
    artist: str = "Artist",
    year: str = "2024",
    country: str = "US",
    track_count: int | None = 10,
    label: str = "",
    catalog: str = "",
    medium: str = "CD",
    disambiguation: str = "",
) -> ReleaseSummary:
    return ReleaseSummary(
        mbid=mbid,
        title=title,
        artist_credit=artist,
        date=year,
        country=country,
        track_count=track_count,
        label=label,
        catalog_number=catalog,
        medium_format=medium,
        disambiguation=disambiguation,
    )


# --- Construction --------------------------------------------------------


def test_window_title_and_modality(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    assert "MusicBrainz" in dialog.windowTitle()
    assert dialog.isModal() is True


def test_table_has_row_per_release(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog(
        [_release("a"), _release("b"), _release("c")]
    )
    assert dialog._table.rowCount() == 3


def test_table_column_count_matches_definition(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    assert dialog._table.columnCount() == len(_COLUMNS)


def test_intro_label_reports_match_count(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release(), _release(mbid="y")])
    # The intro label is the first item in the root layout. Easier to
    # grep through child labels.
    from PySide6.QtWidgets import QLabel

    labels = dialog.findChildren(QLabel)
    intro_texts = [lbl.text() for lbl in labels]
    assert any("2 matches" in text for text in intro_texts)


# --- Row contents --------------------------------------------------------


def test_row_cells_match_release_fields(qapp: QApplication) -> None:
    release = _release(
        title="The Dark Side of the Moon",
        artist="Pink Floyd",
        year="1973-03-01",
        country="GB",
        label="Harvest",
        catalog="SHVL 804",
        track_count=10,
        medium="CD",
        disambiguation="remastered",
    )
    dialog = ReleasePickerDialog([release])

    # Iterate columns to confirm each maps to the right attribute.
    expected = {
        "Title": "The Dark Side of the Moon",
        "Artist": "Pink Floyd",
        "Year": "1973-03-01",
        "Country": "GB",
        "Label": "Harvest",
        "Catalog #": "SHVL 804",
        "Tracks": "10",
        "Format": "CD",
        "Notes": "remastered",
    }
    for col, (header, _) in enumerate(_COLUMNS):
        actual = dialog._table.item(0, col).text()
        assert actual == expected[header], f"column {header}: {actual!r}"


def test_missing_field_renders_empty_string(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog(
        [_release(track_count=None, label="", catalog="", disambiguation="")]
    )
    tracks_col = [i for i, (h, _) in enumerate(_COLUMNS) if h == "Tracks"][0]
    assert dialog._table.item(0, tracks_col).text() == ""


def test_cells_are_not_editable(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    item = dialog._table.item(0, 0)
    from PySide6.QtCore import Qt

    assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)


# --- Selection -----------------------------------------------------------


def test_first_row_selected_by_default(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release("a"), _release("b")])
    assert dialog._table.currentRow() == 0
    assert dialog.selected_mbid() == "a"


def test_selected_mbid_reflects_current_row(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog(
        [_release("a"), _release("b"), _release("c")]
    )
    dialog._table.selectRow(2)
    assert dialog.selected_mbid() == "c"


def test_selected_release_returns_full_summary(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release("a", title="One")])
    out = dialog.selected_release()
    assert out is not None
    assert out.title == "One"


def test_empty_list_selected_mbid_is_none(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([])
    assert dialog.selected_mbid() is None
    assert dialog.selected_release() is None


# --- Acceptance / cancel -------------------------------------------------


def _button_box(dialog: ReleasePickerDialog) -> QDialogButtonBox:
    return dialog._button_box


def test_pick_button_accepts_dialog(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    _button_box(dialog).button(
        QDialogButtonBox.StandardButton.Ok
    ).click()
    assert dialog.result() == int(dialog.DialogCode.Accepted)


def test_cancel_button_rejects_dialog(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    _button_box(dialog).button(
        QDialogButtonBox.StandardButton.Cancel
    ).click()
    assert dialog.result() == int(dialog.DialogCode.Rejected)


def test_double_click_on_row_accepts(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release("a"), _release("b")])
    dialog._table.selectRow(1)
    # Emit the signal directly — exercising real mouse events is fragile.
    dialog._table.itemDoubleClicked.emit(dialog._table.item(1, 0))
    assert dialog.result() == int(dialog.DialogCode.Accepted)
    assert dialog.selected_mbid() == "b"


# --- Pick-button label ---------------------------------------------------


def test_pick_button_label_is_descriptive(qapp: QApplication) -> None:
    dialog = ReleasePickerDialog([_release()])
    label = _button_box(dialog).button(
        QDialogButtonBox.StandardButton.Ok
    ).text()
    assert "Pick" in label or "pick" in label
