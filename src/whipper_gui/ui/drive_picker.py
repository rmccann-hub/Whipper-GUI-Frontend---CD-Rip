"""Drive picker widget.

A small horizontal panel: label + dropdown of detected drives + Refresh.
Populates from `WhipperBackend.list_drives()`; emits `drive_changed`
when the selection changes.

The actual list_drives() call shells out to whipper, which can take a
second or two. For v1 we make the call synchronously from the GUI
thread — the user interaction model here is "click refresh, briefly
wait, see the list". P1 could push it into a worker if the latency
becomes annoying in practice.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from whipper_gui.adapters.whipper_backend import WhipperBackend, WhipperError

log = logging.getLogger(__name__)


class DrivePicker(QWidget):
    """A drop-down listing drives the backend can see.

    Signals:
      drive_changed(str) — emitted when the selected device path changes
                           (including initial population, when one or
                           more drives become available).
    """

    drive_changed = Signal(str)
    # Emitted when a refresh finds zero drives (not on backend errors,
    # which are a different failure already shown inline). MainWindow uses
    # this to offer the drive-access diagnosis.
    drives_unavailable = Signal()
    # Emitted when the user clicks Eject. Carries the selected device path
    # ("" if none is selected → eject the system default). MainWindow does
    # the actual (off-thread) eject so this widget stays UI-only.
    eject_requested = Signal(str)

    def __init__(
        self,
        backend: WhipperBackend,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend: WhipperBackend = backend

        layout = QHBoxLayout(self)
        # Zero margins so the row sits flush inside the parent's
        # layout — the main window controls outer padding.
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Drive:", self))
        self._combo: QComboBox = QComboBox(self)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self._combo, stretch=1)

        self._refresh_button: QPushButton = QPushButton("Refresh", self)
        self._refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self._refresh_button)

        # Eject the selected disc. Re-emits as eject_requested so the main
        # window can run the (potentially blocking) eject off the GUI thread.
        self._eject_button: QPushButton = QPushButton("Eject", self)
        self._eject_button.setToolTip("Eject the disc from the selected drive.")
        self._eject_button.clicked.connect(self._on_eject_clicked)
        layout.addWidget(self._eject_button)

    # --- Public surface -----------------------------------------------------

    def refresh(self) -> None:
        """Reload drives from the backend.

        Preserves the current selection if the same device path is
        still present after the refresh. On error from the backend,
        shows an "(error: ...)" placeholder rather than crashing — the
        user can fix the path in Settings and refresh again.
        """
        previous_device: str | None = self.current_device()

        try:
            drives = self._backend.list_drives()
        except WhipperError as exc:
            log.warning("list_drives failed: %s", exc)
            # Block signals so the placeholder doesn't fire drive_changed.
            self._combo.blockSignals(True)
            self._combo.clear()
            self._combo.addItem(f"(error: {exc})", None)
            self._combo.blockSignals(False)
            return

        # Repopulate. Block signals during the clear/add cycle so we
        # only emit drive_changed once at the end (or zero times if
        # nothing's available).
        self._combo.blockSignals(True)
        self._combo.clear()

        if not drives:
            self._combo.addItem("(no drives found)", None)
            self._combo.blockSignals(False)
            # Let the main window explain *why* (permissions / no device)
            # instead of leaving a bare empty dropdown.
            self.drives_unavailable.emit()
            return

        restore_index = 0
        for i, drive in enumerate(drives):
            label = f"{drive.vendor.strip()} {drive.model.strip()} ({drive.device})"
            self._combo.addItem(label, drive.device)
            if drive.device == previous_device:
                restore_index = i

        self._combo.setCurrentIndex(restore_index)
        self._combo.blockSignals(False)

        # Emit once for the restored / initial selection.
        device = self._combo.currentData()
        if device is not None:
            self.drive_changed.emit(device)

    def current_device(self) -> str | None:
        """The device path of the currently selected drive, or None."""
        data = self._combo.currentData()
        if isinstance(data, str):
            return data
        return None

    # --- Internals ---------------------------------------------------------

    def _on_index_changed(self, index: int) -> None:
        device = self._combo.itemData(index)
        if isinstance(device, str):
            self.drive_changed.emit(device)

    def _on_eject_clicked(self) -> None:
        # current_device() is None when only a placeholder is shown; eject
        # the system default ("") in that case rather than blocking the button.
        self.eject_requested.emit(self.current_device() or "")
