"""Tests for whipper_gui.ui.rip_progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from whipper_gui.parsers.rip_log import (
    AccurateRipResult,
    RipLog,
    TrackResult,
)
from whipper_gui.ui.rip_progress import RipProgress, _ar_cell, _basename

# --- Helpers --------------------------------------------------------------


class _OpenUrlSpy:
    def __init__(self) -> None:
        self.calls: list[QUrl] = []

    def __call__(self, url: QUrl) -> bool:
        self.calls.append(url)
        return True


def _track(
    number: int = 1,
    filename: str = "Artist/Album/01. Track.flac",
    status: str = "Copy OK",
    v1: AccurateRipResult | None = None,
    v2: AccurateRipResult | None = None,
) -> TrackResult:
    return TrackResult(
        number=number,
        filename=filename,
        status=status,
        accuraterip_v1=v1,
        accuraterip_v2=v2,
    )


# --- Initial state -------------------------------------------------------


def test_default_state(qapp: QApplication) -> None:
    widget = RipProgress()
    assert widget._status_label.text() == "Idle."
    assert widget._progress_bar.value() == 0
    assert widget._log_view.toPlainText() == ""
    assert widget._ar_table.rowCount() == 0
    assert widget._view_log_button.isEnabled() is False


# --- Log streaming -------------------------------------------------------


def test_append_log_line_adds_text(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.append_log_line("first")
    widget.append_log_line("second")

    text = widget._log_view.toPlainText()
    assert "first" in text
    assert "second" in text


# --- Progress updates ----------------------------------------------------


def test_set_progress_updates_both_bars_only(qapp: QApplication) -> None:
    # set_progress drives the overall + task bars; the status label is
    # owned by set_status (fed from the worker's phase signal).
    widget = RipProgress()
    before = widget._status_label.text()
    widget.set_progress(60.0, 42.0)

    assert widget._overall_bar.value() == 60
    assert widget._progress_bar.value() == 42
    assert widget._status_label.text() == before  # unchanged


def test_set_status_updates_label(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_status("All done.")
    assert widget._status_label.text() == "All done."


# --- AccurateRip table ---------------------------------------------------


def test_set_rip_log_populates_table(qapp: QApplication) -> None:
    widget = RipProgress()
    log = RipLog(
        tracks=(
            _track(
                1,
                filename="Pink Floyd/Dark Side/01. Speak to Me.flac",
                v1=AccurateRipResult(
                    version=1, result="Found, exact match", confidence=14
                ),
                v2=AccurateRipResult(
                    version=2, result="Found, exact match", confidence=11
                ),
            ),
            _track(
                2,
                filename="Pink Floyd/Dark Side/02. Breathe.flac",
                v1=AccurateRipResult(
                    version=1,
                    result="Track not present in AccurateRip database",
                    confidence=0,
                ),
                v2=None,
            ),
        )
    )

    widget.set_rip_log(log)

    assert widget._ar_table.rowCount() == 2
    assert widget._ar_table.item(0, 0).text() == "1"
    assert "Speak to Me" in widget._ar_table.item(0, 1).text()
    assert widget._ar_table.item(0, 2).text() == "Copy OK"
    assert widget._ar_table.item(0, 3).text() == "OK (14)"
    assert widget._ar_table.item(0, 4).text() == "OK (11)"
    # Track 2 — v1 not in DB, v2 missing.
    assert widget._ar_table.item(1, 3).text() == "not in DB"
    assert widget._ar_table.item(1, 4).text() == "—"


def test_set_rip_log_empty_tracks_clears_table(qapp: QApplication) -> None:
    widget = RipProgress()
    widget._ar_table.setRowCount(3)  # pretend we had results
    widget.set_rip_log(RipLog())
    assert widget._ar_table.rowCount() == 0


# --- View log button -----------------------------------------------------


def test_set_log_path_enables_button(qapp: QApplication, tmp_path: Path) -> None:
    widget = RipProgress()
    log_file = tmp_path / "rip.log"
    log_file.write_text("dummy")

    widget.set_log_path(log_file)

    assert widget._view_log_button.isEnabled() is True


def test_set_log_path_none_disables_button(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_log_path(Path("/tmp/x"))  # enable
    widget.set_log_path(None)
    assert widget._view_log_button.isEnabled() is False


def test_view_log_click_opens_url(qapp: QApplication, tmp_path: Path) -> None:
    spy = _OpenUrlSpy()
    widget = RipProgress(open_url=spy)
    log_file = tmp_path / "rip.log"
    log_file.write_text("dummy")
    widget.set_log_path(log_file)

    widget._view_log_button.click()

    assert len(spy.calls) == 1
    url = spy.calls[0]
    assert url.isLocalFile()
    assert url.toLocalFile() == str(log_file)


def test_view_log_no_op_without_path(qapp: QApplication) -> None:
    spy = _OpenUrlSpy()
    widget = RipProgress(open_url=spy)
    widget._on_view_log_clicked()  # call directly; button is disabled
    assert spy.calls == []


# --- clear() -------------------------------------------------------------


def test_clear_resets_all_state(qapp: QApplication, tmp_path: Path) -> None:
    widget = RipProgress()
    widget.append_log_line("noise")
    widget.set_progress(70.0, 90.0)
    widget.set_rip_log(RipLog(tracks=(_track(),)))
    widget.set_log_path(tmp_path / "x.log")

    widget.clear()

    assert widget._status_label.text() == "Idle."
    assert widget._overall_bar.value() == 0
    assert widget._progress_bar.value() == 0
    assert widget._log_view.toPlainText() == ""
    assert widget._ar_table.rowCount() == 0
    assert widget._view_log_button.isEnabled() is False


# --- _basename helper ----------------------------------------------------


def test_basename_strips_extension() -> None:
    assert _basename("Artist/Album/01. Title.flac") == "01. Title"


def test_basename_handles_empty() -> None:
    assert _basename("") == ""


# --- _ar_cell helper -----------------------------------------------------


def test_ar_cell_none_renders_placeholder() -> None:
    assert _ar_cell(None) == "—"


def test_ar_cell_exact_match() -> None:
    ar = AccurateRipResult(version=1, result="Found, exact match", confidence=14)
    assert _ar_cell(ar) == "OK (14)"


def test_ar_cell_not_in_db() -> None:
    ar = AccurateRipResult(
        version=2,
        result="Track not present in AccurateRip database",
        confidence=0,
    )
    assert _ar_cell(ar) == "not in DB"
