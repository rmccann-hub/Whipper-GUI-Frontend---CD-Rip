"""Tests for whipper_gui.ui.drive_setup_dialog.

We don't drive a real worker thread — we construct the dialog and call
its `_on_finished` slot directly to verify result rendering.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.whipper_backend import WhipperBackend
from whipper_gui.ui.drive_setup_dialog import DriveSetupDialog, _format_result
from whipper_gui.workers.drive_setup_worker import DriveSetupResult


class _StubBackend(WhipperBackend):
    def list_drives(self):  # type: ignore[override]
        return []

    def disc_info(self, drive):  # type: ignore[override]
        raise NotImplementedError

    def rip(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    def version(self) -> str:  # type: ignore[override]
        return "fake"


def _dialog(qapp: QApplication) -> DriveSetupDialog:
    return DriveSetupDialog(_StubBackend(), "/dev/sr0")


def test_initial_state(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    assert dialog._detect_button.isEnabled() is True
    assert dialog._progress.isVisible() is False
    assert "/dev/sr0" in dialog._device_label.text()
    assert dialog._results_label.toPlainText() == ""


def test_manual_offset_save_emits_signal(qapp: QApplication) -> None:
    """The manual fallback emits the entered offset for the main window."""
    dialog = _dialog(qapp)
    captured: list[int] = []
    dialog.manual_offset_saved.connect(captured.append)

    dialog._offset_spin.setValue(667)
    dialog._on_save_offset_clicked()

    assert captured == [667]
    assert "+667" in dialog._status_label.text()


def test_manual_offset_prefilled_from_current(qapp: QApplication) -> None:
    dialog = DriveSetupDialog(_StubBackend(), "/dev/sr0", current_offset=-12)
    assert dialog._offset_spin.value() == -12


def test_on_finished_renders_success(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._on_finished(
        DriveSetupResult(
            offset=667,
            can_defeat_cache=True,
            backup_path=Path("/home/u/.config/whipper/whipper.conf.bak"),
        )
    )
    text = dialog._results_label.toPlainText()
    assert "+667 samples" in text
    assert "Audio cache" in text
    assert "backed up to whipper.conf.bak" in text
    assert dialog._progress.isVisible() is False
    assert dialog._detect_button.text() == "Re-detect"


def test_on_finished_ignored_while_closing(qapp: QApplication) -> None:
    """A late worker result must not poke widgets once the dialog is closing.

    This is what prevented the crash: on close we cancel + join the thread,
    and any queued finished signal that arrives afterward is a no-op."""
    dialog = _dialog(qapp)
    dialog._closing = True
    dialog._on_finished(DriveSetupResult(offset=667, can_defeat_cache=True))
    assert dialog._results_label.toPlainText() == ""  # untouched


def test_format_result_offset_failure() -> None:
    text = _format_result(
        DriveSetupResult(offset=None, offset_error="not in AccurateRip")
    )
    assert "✗ Read offset: not in AccurateRip" in text


def test_format_result_negative_offset_signed() -> None:
    text = _format_result(DriveSetupResult(offset=-582, can_defeat_cache=False))
    assert "-582 samples" in text
    assert "doesn't need cache-defeating" in text
