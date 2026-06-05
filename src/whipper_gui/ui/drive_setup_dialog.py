"""Drive setup wizard — one-click calibration of the optical drive.

Replaces the manual hand-edit of `whipper.conf` (the worst first-run
step) with a guided flow: the user inserts a popular CD and clicks
Detect; we run `whipper drive analyze` + `whipper offset find` (off the
GUI thread, via DriveSetupWorker), which persist the cache verdict and
read offset to `whipper.conf` themselves. We back the file up first so
the user can always revert. See PLANNING.md KDD-15.

The dialog owns the worker thread; `_on_finished` is a plain slot so
tests can exercise the result rendering without a live event loop.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters.whipper_backend import WhipperBackend
from whipper_gui.workers.drive_setup_worker import (
    DriveSetupResult,
    DriveSetupWorker,
)

log = logging.getLogger(__name__)


class DriveSetupDialog(QDialog):
    """Modal-ish dialog that calibrates one drive via whipper's commands."""

    # Emitted when the user saves a manually-entered offset (the fallback for
    # when auto-detection can't run — e.g. no AccurateRip disc to hand). The
    # main window persists it as the GUI's `--offset` override; this dialog
    # stays a view and never writes config itself.
    manual_offset_saved = Signal(int)

    def __init__(
        self,
        backend: WhipperBackend,
        device: str,
        parent: QWidget | None = None,
        current_offset: int = 0,
        known_offset: int | None = None,
        drive_label: str = "",
    ) -> None:
        """`known_offset`, when provided, is the AccurateRip read offset
        looked up by drive model (the primary, disc-free path). We prefill
        the manual field with it and call it out so the user can save it in
        one click — no disc or whipper probe required. `drive_label` is the
        human drive name shown in that callout.
        """
        super().__init__(parent)
        self._backend: WhipperBackend = backend
        self._device: str = device
        self._known_offset: int | None = known_offset
        self._thread: QThread | None = None
        self._worker: DriveSetupWorker | None = None
        # Set true once the dialog is closing, so a late worker result
        # doesn't poke widgets that are being torn down.
        self._closing: bool = False

        self.setWindowTitle("Set up drive")
        # Open at a readable size (the default was cramped — labels and the
        # detection output were clipped and unscrollable). Resizable.
        self.resize(560, 420)
        self.setMinimumSize(460, 320)

        root = QVBoxLayout(self)

        intro = QLabel(
            "This calibrates your drive for bit-perfect rips. It detects the "
            "drive's read offset and audio-cache behaviour and saves them to "
            "whipper.conf (your existing config is backed up first).\n\n"
            "Insert a popular commercial CD — one likely to be in the "
            "AccurateRip database — then click Detect. This can take a minute.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._device_label: QLabel = QLabel(
            f"Drive: {device or '(auto-detected)'}", self
        )
        root.addWidget(self._device_label)

        # Primary path: if we already know this drive's offset from the
        # AccurateRip drive list (looked up by model), say so prominently —
        # the user can save it in one click below without inserting a disc.
        # This sidesteps whipper's unreliable `offset find` entirely.
        if known_offset is not None:
            name = drive_label or "this drive"
            suggestion = QLabel(
                f"✓ Known read offset for {name}: <b>{known_offset:+d}</b> "
                "(from the AccurateRip drive list). It's pre-filled below — "
                'click "Save offset" to use it. No disc needed. '
                "Auto-detect (Detect) is optional verification.",
                self,
            )
            suggestion.setWordWrap(True)
            root.addWidget(suggestion)

        self._detect_button: QPushButton = QPushButton("Detect", self)
        self._detect_button.clicked.connect(self._on_detect_clicked)
        root.addWidget(self._detect_button)

        # Indeterminate (busy) bar — min==max==0 animates with no percentage,
        # which is honest here since neither whipper command reports progress.
        self._progress: QProgressBar = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status_label: QLabel = QLabel("", self)
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        # Read-only, scrollable: detection output can be several lines and
        # the offset-find guidance is long, so a label clipped it.
        self._results_label: QPlainTextEdit = QPlainTextEdit("", self)
        self._results_label.setReadOnly(True)
        root.addWidget(self._results_label, stretch=1)

        # --- Manual fallback ---------------------------------------------------
        # Auto-detection needs a disc that's in AccurateRip; a user with only
        # CD-Rs (or an obscure pressing) can't run it. Let them enter the
        # offset by hand — every drive model's value is published at
        # AccurateRip's list, keyed by the exact drive the GUI already shows.
        manual_intro = QLabel(
            "No AccurateRip disc handy? Look up your drive's offset at "
            '<a href="https://www.accuraterip.com/driveoffsets.htm">'
            "accuraterip.com/driveoffsets.htm</a> and enter it here. It's "
            "applied via whipper's --offset, so whipper.conf isn't touched.",
            self,
        )
        manual_intro.setWordWrap(True)
        manual_intro.setOpenExternalLinks(True)
        root.addWidget(manual_intro)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Read offset (samples):", self))
        self._offset_spin: QSpinBox = QSpinBox(self)
        # AccurateRip offsets sit well within ±2000 samples in practice.
        self._offset_spin.setRange(-2000, 2000)
        # Prefill with the model-looked-up offset when we have one (the
        # primary path); otherwise fall back to the currently-configured
        # value passed in.
        self._offset_spin.setValue(
            known_offset if known_offset is not None else current_offset
        )
        manual_row.addWidget(self._offset_spin)
        self._save_offset_button: QPushButton = QPushButton("Save offset", self)
        self._save_offset_button.clicked.connect(self._on_save_offset_clicked)
        manual_row.addWidget(self._save_offset_button)
        manual_row.addStretch(1)
        root.addLayout(manual_row)

        # Close only — there's no "apply" step because whipper writes the
        # config itself the moment detection succeeds.
        self._button_box: QDialogButtonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, self
        )
        self._button_box.rejected.connect(self.reject)
        self._button_box.accepted.connect(self.accept)
        root.addWidget(self._button_box)

    # --- Detection flow -----------------------------------------------------

    def _on_detect_clicked(self) -> None:
        """Kick off calibration on a worker thread."""
        if self._thread is not None:  # already running
            return
        self._detect_button.setEnabled(False)
        # Lock the manual-offset controls while detection runs: editing or
        # saving an offset mid-detection would race the value whipper is
        # about to write. They're re-enabled in `_on_finished`.
        self._set_manual_controls_enabled(False)
        self._results_label.clear()
        self._progress.setVisible(True)
        self._status_label.setText("Starting…")

        self._worker = DriveSetupWorker(self._backend, self._device)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._worker.status.connect(self._status_label.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _on_finished(self, result: DriveSetupResult) -> None:
        """Render the calibration outcome. Safe to call directly in tests."""
        # If the dialog is closing, the worker's final (likely cancelled)
        # result is irrelevant and the widgets may be on their way out —
        # don't touch them.
        if self._closing:
            return
        self._progress.setVisible(False)
        self._status_label.setText("Done." if result.ok else "Finished with issues.")
        self._results_label.setPlainText(_format_result(result))
        self._detect_button.setEnabled(True)
        self._detect_button.setText("Re-detect")
        self._set_manual_controls_enabled(True)
        self._worker = None
        self._thread = None

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        """Enable/disable the manual read-offset controls as a unit.

        The QSpinBox covers its own up/down arrows, so disabling it locks the
        whole numeric entry; the Save button is locked alongside it.
        """
        self._offset_spin.setEnabled(enabled)
        self._save_offset_button.setEnabled(enabled)

    def _on_save_offset_clicked(self) -> None:
        """Persist a hand-entered offset via the main window (--offset path)."""
        value = self._offset_spin.value()
        self.manual_offset_saved.emit(value)
        self._status_label.setText(
            f"Saved read offset {value:+d} — it will be used for rips."
        )

    # --- Lifecycle ----------------------------------------------------------

    def _stop_detection(self) -> None:
        """Cancel a running detection and join its thread before teardown.

        Cancelling terminates the whipper subprocess, which unblocks the
        worker's run() so the QThread can quit and be waited on. Without
        this, closing mid-detection destroys a still-running QThread (Qt
        aborts the process) and leaves whipper spinning the drive.
        """
        thread = self._thread
        worker = self._worker
        if thread is None:
            return
        if worker is not None:
            worker.cancel()  # kills the subprocess so run() returns promptly
        thread.quit()
        # Generous wait: cancel_setup does SIGTERM then SIGKILL after 5s.
        if not thread.wait(10000):
            log.error("drive-setup thread did not stop within 10s")
        self._worker = None
        self._thread = None

    def reject(self) -> None:  # noqa: D102 — Qt override (Close button / Esc)
        self._closing = True
        self._stop_detection()
        super().reject()

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt API
        """Stop the worker thread cleanly if detection is still running."""
        self._closing = True
        self._stop_detection()
        super().closeEvent(event)  # type: ignore[arg-type]


def _format_result(result: DriveSetupResult) -> str:
    """Build the human-readable summary block for the dialog."""
    lines: list[str] = []

    if result.offset is not None:
        lines.append(
            f"✓ Read offset: {result.offset:+d} samples — saved to whipper.conf."
        )
    else:
        lines.append(f"✗ Read offset: {result.offset_error or 'not detected'}")

    if result.can_defeat_cache is True:
        lines.append("✓ Audio cache: will be defeated for secure rips (saved).")
    elif result.can_defeat_cache is False:
        lines.append("• Audio cache: this drive doesn't need cache-defeating (saved).")
    else:
        lines.append(
            f"• Audio cache: {result.analyze_error or 'could not be determined'}"
        )

    if result.backup_path is not None:
        lines.append(f"Previous whipper.conf backed up to {result.backup_path.name}.")

    return "\n".join(lines)
