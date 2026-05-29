"""Tests for whipper_gui.ui.track_table."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.musicbrainz_client import (
    ReleaseDetail,
    ReleaseSummary,
    TrackSummary,
)
from whipper_gui.ui.track_table import (
    AlbumMetadata,
    TrackTable,
    TrackTableModel,
    _format_length,
)


def _track(
    number: int = 1,
    title: str = "Track",
    artist: str = "Artist",
    length_ms: int | None = 60_000,
) -> TrackSummary:
    return TrackSummary(
        number=number, title=title, artist_credit=artist, length_ms=length_ms
    )


def _detail() -> ReleaseDetail:
    return ReleaseDetail(
        summary=ReleaseSummary(
            mbid="m",
            title="Dark Side",
            artist_credit="Pink Floyd",
            date="1973",
        ),
        tracks=(
            _track(1, "Speak to Me", "Pink Floyd", 67_000),
            _track(2, "Breathe", "Pink Floyd", 165_000),
        ),
    )


# --- _format_length -------------------------------------------------------


def test_format_length_basic() -> None:
    assert _format_length(67_000) == "1:07"
    assert _format_length(165_000) == "2:45"


def test_format_length_zero() -> None:
    assert _format_length(0) == "0:00"


def test_format_length_none() -> None:
    assert _format_length(None) == ""


def test_format_length_negative_is_empty() -> None:
    assert _format_length(-1) == ""


# --- TrackTableModel ------------------------------------------------------


def test_model_starts_empty(qapp: QApplication) -> None:
    model = TrackTableModel()
    assert model.rowCount() == 0
    assert model.columnCount() == 4


def test_model_set_tracks_populates_rows(qapp: QApplication) -> None:
    model = TrackTableModel()
    model.set_tracks([_track(1), _track(2)])
    assert model.rowCount() == 2


def test_model_data_displays_track_fields(qapp: QApplication) -> None:
    model = TrackTableModel()
    model.set_tracks([_track(1, "Speak to Me", "Pink Floyd", 67_000)])

    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "Speak to Me"
    assert model.data(model.index(0, 2)) == "Pink Floyd"
    assert model.data(model.index(0, 3)) == "1:07"


def test_model_title_and_artist_are_editable(qapp: QApplication) -> None:
    model = TrackTableModel()
    model.set_tracks([_track()])

    title_flags = model.flags(model.index(0, 1))
    artist_flags = model.flags(model.index(0, 2))
    number_flags = model.flags(model.index(0, 0))
    length_flags = model.flags(model.index(0, 3))

    assert title_flags & Qt.ItemFlag.ItemIsEditable
    assert artist_flags & Qt.ItemFlag.ItemIsEditable
    assert not (number_flags & Qt.ItemFlag.ItemIsEditable)
    assert not (length_flags & Qt.ItemFlag.ItemIsEditable)


def test_model_setData_updates_title(qapp: QApplication) -> None:
    model = TrackTableModel()
    model.set_tracks([_track(title="Old")])

    ok = model.setData(model.index(0, 1), "New")

    assert ok is True
    assert model.tracks()[0].title == "New"


def test_model_setData_updates_artist(qapp: QApplication) -> None:
    model = TrackTableModel()
    model.set_tracks([_track(artist="Old")])

    ok = model.setData(model.index(0, 2), "New")

    assert ok is True
    assert model.tracks()[0].artist_credit == "New"


def test_model_setData_refuses_to_edit_number_or_length(
    qapp: QApplication,
) -> None:
    model = TrackTableModel()
    model.set_tracks([_track(number=1)])

    assert model.setData(model.index(0, 0), "99") is False
    assert model.setData(model.index(0, 3), "9:99") is False
    # Underlying data unchanged.
    assert model.tracks()[0].number == 1


def test_model_headers(qapp: QApplication) -> None:
    model = TrackTableModel()
    expected = ["#", "Title", "Artist", "Length"]
    for i, header in enumerate(expected):
        assert (
            model.headerData(i, Qt.Orientation.Horizontal) == header
        )


# --- TrackTable widget ----------------------------------------------------


def test_default_state_is_empty(qapp: QApplication) -> None:
    widget = TrackTable()
    assert widget.album_metadata() == AlbumMetadata()
    assert widget.tracks() == []


def test_set_release_populates_album_and_tracks(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())

    meta = widget.album_metadata()
    assert meta.artist == "Pink Floyd"
    assert meta.title == "Dark Side"
    assert meta.year == "1973"
    assert len(widget.tracks()) == 2
    assert widget.tracks()[0].title == "Speak to Me"


def test_set_blank_tracks_creates_numbered_empty_rows(
    qapp: QApplication,
) -> None:
    widget = TrackTable()
    widget.set_blank_tracks(16)

    tracks = widget.tracks()
    assert len(tracks) == 16
    assert [t.number for t in tracks] == list(range(1, 17))
    assert all(t.title == "" for t in tracks)


def test_set_blank_tracks_zero_or_negative_clears(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget.set_blank_tracks(0)
    assert widget.tracks() == []


def test_clear_resets_to_empty(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget.clear()

    assert widget.album_metadata() == AlbumMetadata()
    assert widget.tracks() == []


def test_user_edit_album_artist_visible_in_metadata(
    qapp: QApplication,
) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget._album_artist_edit.setText("Edited Artist")

    assert widget.album_metadata().artist == "Edited Artist"


def test_user_edit_track_title_visible_in_tracks(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget._model.setData(widget._model.index(0, 1), "Edited Title")

    assert widget.tracks()[0].title == "Edited Title"


# --- validate -------------------------------------------------------------


def test_validate_ok_for_complete_release(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    ok, message = widget.validate()
    assert ok is True
    assert message == ""


def test_validate_rejects_blank_artist(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget._album_artist_edit.setText("   ")
    ok, message = widget.validate()
    assert ok is False
    assert "artist" in message.lower()


def test_validate_rejects_blank_title(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget._album_title_edit.setText("")
    ok, message = widget.validate()
    assert ok is False
    assert "title" in message.lower()


def test_validate_rejects_no_tracks(qapp: QApplication) -> None:
    widget = TrackTable()
    widget._album_artist_edit.setText("A")
    widget._album_title_edit.setText("T")
    ok, message = widget.validate()
    assert ok is False
    assert "tracks" in message.lower()


def test_validate_rejects_blank_track_title(qapp: QApplication) -> None:
    widget = TrackTable()
    widget.set_release(_detail())
    widget._model.setData(widget._model.index(0, 1), "")
    ok, message = widget.validate()
    assert ok is False
    assert "track 1" in message.lower() or "track" in message.lower()
