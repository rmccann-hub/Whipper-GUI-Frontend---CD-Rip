"""Tests for the app-wide dialog-centering filter."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from platterpus.ui.dialogs.auto_center import DialogCenterFilter
from platterpus.ui.dialogs.centering import CenteredDialog


def test_filter_marks_plain_dialog_seen_on_show(qapp: QApplication) -> None:
    # A plain QDialog (e.g. QMessageBox is one) gets centred — and recorded — on
    # its first Show, and only once.
    f = DialogCenterFilter()
    box = QMessageBox()
    f.eventFilter(box, QEvent(QEvent.Type.Show))
    assert id(box) in f._seen
    # A second show is a no-op (already seen) — must not raise.
    f.eventFilter(box, QEvent(QEvent.Type.Show))


def test_filter_skips_centered_dialog(qapp: QApplication) -> None:
    # CenteredDialog self-centres, so the filter must not also handle it.
    f = DialogCenterFilter()
    dlg = CenteredDialog()
    f.eventFilter(dlg, QEvent(QEvent.Type.Show))
    assert id(dlg) not in f._seen


def test_filter_ignores_non_show_events(qapp: QApplication) -> None:
    f = DialogCenterFilter()
    box = QMessageBox()
    f.eventFilter(box, QEvent(QEvent.Type.Hide))
    assert id(box) not in f._seen


def test_filter_never_consumes_event(qapp: QApplication) -> None:
    # The filter only observes; it must always return False so the dialog still
    # processes its own Show.
    f = DialogCenterFilter()
    assert f.eventFilter(QDialog(), QEvent(QEvent.Type.Show)) is False
