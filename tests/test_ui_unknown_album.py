"""Tests for whipper_gui.ui.unknown_album."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from whipper_gui.adapters.metaflac import MetaflacAdapter, MetaflacError
from whipper_gui.adapters.musicbrainz_client import TrackSummary
from whipper_gui.ui import unknown_album as unknown_module
from whipper_gui.ui.track_table import AlbumMetadata
from whipper_gui.ui.unknown_album import (
    UnknownAlbumDialog,
    apply_placeholder_tags,
    apply_track_tags,
    launch_picard_for,
)

# --- UnknownAlbumDialog --------------------------------------------------


def test_dialog_title_and_modality(qapp: QApplication) -> None:
    dialog = UnknownAlbumDialog()
    assert "unknown" in dialog.windowTitle().lower()
    assert dialog.isModal() is True


def test_dialog_initial_picard_state_from_default(
    qapp: QApplication,
) -> None:
    off = UnknownAlbumDialog(auto_launch_picard_default=False)
    on = UnknownAlbumDialog(auto_launch_picard_default=True)
    assert off.auto_launch_picard() is False
    assert on.auto_launch_picard() is True


def test_dialog_picard_toggle_round_trips(qapp: QApplication) -> None:
    dialog = UnknownAlbumDialog(auto_launch_picard_default=False)
    dialog._picard_check.setChecked(True)
    assert dialog.auto_launch_picard() is True


def test_dialog_ok_accepts(qapp: QApplication) -> None:
    dialog = UnknownAlbumDialog()
    button_box = dialog.findChild(QDialogButtonBox)
    button_box.button(QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == int(dialog.DialogCode.Accepted)


def test_dialog_cancel_rejects(qapp: QApplication) -> None:
    dialog = UnknownAlbumDialog()
    button_box = dialog.findChild(QDialogButtonBox)
    button_box.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert dialog.result() == int(dialog.DialogCode.Rejected)


# --- apply_placeholder_tags ----------------------------------------------


class _FakeMetaflac(MetaflacAdapter):
    """Captures write_tags calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[Path, dict[str, str]]] = []
        self._fail_for: set[Path] = set()

    def fail_for(self, path: Path) -> None:
        self._fail_for.add(path)

    def write_tags(self, flac_path: Path, tags: dict[str, str]) -> None:
        if flac_path in self._fail_for:
            raise MetaflacError(f"intentional failure for {flac_path}")
        self.calls.append((flac_path, dict(tags)))


def test_apply_placeholder_tags_writes_track_nn(tmp_path: Path) -> None:
    metaflac = _FakeMetaflac()
    files = [tmp_path / f"track{i}.flac" for i in range(1, 4)]

    apply_placeholder_tags(metaflac, files)

    assert len(metaflac.calls) == 3
    for i, (path, tags) in enumerate(metaflac.calls, start=1):
        number = f"{i:02d}"
        assert path == files[i - 1]
        assert tags == {
            "TITLE": f"Track {number}",
            "ARTIST": "Unknown Artist",
            "ALBUM": "Unknown Album",
            "TRACKNUMBER": number,
        }


def test_apply_placeholder_tags_returns_successes(tmp_path: Path) -> None:
    metaflac = _FakeMetaflac()
    files = [tmp_path / "a.flac", tmp_path / "b.flac", tmp_path / "c.flac"]
    metaflac.fail_for(files[1])  # b.flac will fail

    succeeded = apply_placeholder_tags(metaflac, files)

    assert succeeded == [files[0], files[2]]


def test_apply_placeholder_tags_handles_empty_list() -> None:
    metaflac = _FakeMetaflac()
    succeeded = apply_placeholder_tags(metaflac, [])
    assert succeeded == []
    assert metaflac.calls == []


# --- apply_track_tags (edit-aware) ---------------------------------------


def test_apply_track_tags_writes_edited_values(tmp_path: Path) -> None:
    metaflac = _FakeMetaflac()
    files = [tmp_path / "01.flac", tmp_path / "02.flac"]
    album = AlbumMetadata(artist="Pink Floyd", title="The Wall", year="1979")
    tracks = [
        TrackSummary(number=1, title="In the Flesh?", artist_credit="Pink Floyd"),
        TrackSummary(number=2, title="The Thin Ice", artist_credit=""),
    ]

    apply_track_tags(metaflac, files, album, tracks)

    assert metaflac.calls[0][1] == {
        "TITLE": "In the Flesh?",
        "ARTIST": "Pink Floyd",
        "ALBUM": "The Wall",
        "ALBUMARTIST": "Pink Floyd",
        "TRACKNUMBER": "01",
        "DATE": "1979",
    }
    # Track 2 left its artist blank → falls back to the album artist.
    assert metaflac.calls[1][1]["TITLE"] == "The Thin Ice"
    assert metaflac.calls[1][1]["ARTIST"] == "Pink Floyd"


def test_apply_track_tags_falls_back_to_placeholders(tmp_path: Path) -> None:
    metaflac = _FakeMetaflac()
    files = [tmp_path / "01.flac"]
    # Nothing edited: blank album, no track rows.
    apply_track_tags(metaflac, files, AlbumMetadata(), [])

    assert metaflac.calls[0][1] == {
        "TITLE": "Track 01",
        "ARTIST": "Unknown Artist",
        "ALBUM": "Unknown Album",
        "ALBUMARTIST": "Unknown Artist",
        "TRACKNUMBER": "01",
    }
    # No year typed → no DATE tag at all (rather than an empty one).
    assert "DATE" not in metaflac.calls[0][1]


# --- launch_picard_for ---------------------------------------------------


def test_launch_picard_invokes_flatpak_with_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[list[str]] = []

    class _FakePopen:
        def __init__(self, argv: list[str], *a: Any, **kw: Any) -> None:
            captured.append(argv)

    monkeypatch.setattr(unknown_module.subprocess, "Popen", _FakePopen)

    ok = launch_picard_for(tmp_path)

    assert ok is True
    assert captured == [
        [
            "flatpak",
            "run",
            "org.musicbrainz.Picard",
            str(tmp_path),
        ]
    ]


def test_launch_picard_returns_false_when_flatpak_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError("flatpak")

    monkeypatch.setattr(unknown_module.subprocess, "Popen", boom)

    assert launch_picard_for(tmp_path) is False


def test_launch_picard_returns_false_on_other_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise PermissionError("no exec")

    monkeypatch.setattr(unknown_module.subprocess, "Popen", boom)

    assert launch_picard_for(tmp_path) is False
