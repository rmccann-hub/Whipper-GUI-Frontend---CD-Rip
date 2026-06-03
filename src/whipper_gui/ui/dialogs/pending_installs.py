"""Pending-installs dialog — tier (b) of the dependency subsystem.

Shown when one or more dependencies can be installed automatically but
benefit from explicit user consent and batching (multiple Flatpaks at
once, a Python wheel that needs network retry). Per the brief P0 #11:

  "present them in a dedicated 'Pending installs' dialog with per-item
   checkboxes, an 'Install selected' button, and per-item progress
   feedback. The user clicks once; the GUI handles the loop."

When an `install_one` callable is supplied, the dialog drives the install
loop **itself** on "Install Selected": it installs each ticked item in turn,
updating that row's status live (`mark_in_progress` → `mark_result`), then
swaps in a Close button. `results()` then returns one `InstallResult` per
item (a `user_declined` result for unticked items). This is what lets the
user watch progress instead of the dialog vanishing the instant they click.

If `install_one` is omitted the dialog keeps its original passive behaviour
(emit `install_requested` and stay open for an external driver) — used by
older callers and the unit tests.
"""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.deps.resolvers import InstallResult, MissingItem

# Installs a single item and returns its outcome. Injected so the dialog
# doesn't depend on a concrete installer (tests pass a fake; the GUI passes
# an AutoInstaller-backed one).
InstallOne = Callable[[MissingItem], InstallResult]


class PendingInstallsDialog(QDialog):
    """Modal dialog showing N missing items the user can install in one click.

    Signals:
      install_requested — emitted when the user clicks "Install Selected".
                          The caller handles the actual install loop.
    """

    install_requested = Signal()

    def __init__(
        self,
        items: Iterable[MissingItem],
        install_one: InstallOne | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list[MissingItem] = list(items)
        self._install_one: InstallOne | None = install_one
        # Populated when the dialog drives its own install loop; one entry
        # per item (a user_declined result for unticked / not-attempted ones).
        self._results: list[InstallResult] = []
        self._checkboxes: dict[str, QCheckBox] = {}
        self._status_labels: dict[str, QLabel] = {}

        self.setWindowTitle("Pending installs")
        self.setModal(True)

        root = QVBoxLayout(self)

        intro = QLabel(
            "These dependencies are missing. Tick the ones you want "
            "to install and press Install Selected."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Per-item rows. Each row is: checkbox + name + min-version
        # hint + status label (initially empty; populated during install).
        for item in self._items:
            row_widget = QWidget(self)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)

            checkbox = QCheckBox(self._row_label(item), row_widget)
            checkbox.setChecked(True)  # default to "yes, install"; user
                                       # can uncheck individual items
            self._checkboxes[item.spec.dep_id] = checkbox
            row.addWidget(checkbox, stretch=1)

            status_label = QLabel("", row_widget)
            self._status_labels[item.spec.dep_id] = status_label
            row.addWidget(status_label)

            root.addWidget(row_widget)

        # Button box. We start with Install Selected (default) + Cancel;
        # after the user starts an install, the caller can swap us into
        # a "Close" mode via show_close_button().
        self._button_box: QDialogButtonBox = QDialogButtonBox(self)
        self._install_button: QPushButton = self._button_box.addButton(
            "Install Selected", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._cancel_button: QPushButton = self._button_box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self._close_button: QPushButton | None = None  # added on demand
        self._install_button.setDefault(True)
        self._install_button.clicked.connect(self._on_install_clicked)
        self._cancel_button.clicked.connect(self.reject)
        root.addWidget(self._button_box)

    # --- Public surface -----------------------------------------------------

    def selected_items(self) -> list[MissingItem]:
        """Return the items whose checkbox is currently checked."""
        return [
            item
            for item in self._items
            if self._checkboxes[item.spec.dep_id].isChecked()
        ]

    def results(self) -> list[InstallResult]:
        """Outcomes of a self-driven install loop, one per item.

        Empty until the dialog has driven an install (or been cancelled).
        Only meaningful when constructed with an `install_one`.
        """
        return list(self._results)

    def mark_in_progress(self, dep_id: str) -> None:
        """Show 'installing…' on the row for `dep_id`."""
        label = self._status_labels.get(dep_id)
        if label is not None:
            label.setText("installing…")

    def mark_result(
        self, dep_id: str, success: bool, message: str = ""
    ) -> None:
        """Update the status label for `dep_id` with the install outcome."""
        label = self._status_labels.get(dep_id)
        if label is None:
            return
        if success:
            label.setText("OK")
        else:
            # Compact rendering — the full message lives in the log.
            short = message if len(message) <= 60 else message[:57] + "…"
            label.setText(f"FAILED: {short}" if short else "FAILED")

    def set_install_phase_active(self, active: bool) -> None:
        """Lock down the picker during the install loop.

        When `active`, checkboxes and the Install button disable so the
        user can't double-fire installs. When inactive, they re-enable.
        """
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(not active)
        self._install_button.setEnabled(not active)

    def show_close_button(self) -> None:
        """Swap the button row to a single Close button.

        Called by the caller when the install loop has finished. The
        user dismisses the dialog from here.
        """
        if self._close_button is not None:
            return  # idempotent

        self._install_button.hide()
        self._cancel_button.hide()
        self._close_button = self._button_box.addButton(
            "Close", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._close_button.setDefault(True)
        self._close_button.clicked.connect(self.accept)

    # --- Internals ---------------------------------------------------------

    def reject(self) -> None:
        """Cancel / close-before-installing → record a decline for every item.

        So the resolver/manager see "the user declined", not an empty result
        set (which would look like nothing was offered). Guarded by
        `not self._results` so closing the window *after* a completed install
        doesn't clobber the real outcomes. No-op for the passive (legacy) mode.
        """
        if self._install_one is not None and not self._results:
            self._results = [self._declined(item) for item in self._items]
        super().reject()

    def _on_install_clicked(self) -> None:
        """Start the install. Either drive the loop here (when we have an
        `install_one`) or just signal an external driver (legacy mode)."""
        # Emit for observers/tests regardless of mode.
        self.install_requested.emit()
        if self._install_one is None:
            # Passive mode: caller drives the loop; we stay open, no accept().
            return
        self._run_install_loop()

    def _run_install_loop(self) -> None:
        """Install each ticked item in turn, updating its row live."""
        assert self._install_one is not None
        self.set_install_phase_active(True)
        self._results = []
        for item in self._items:
            dep_id = item.spec.dep_id
            if not self._checkboxes[dep_id].isChecked():
                # Unticked → the user declined this one; don't install it.
                self._results.append(self._declined(item))
                continue
            self.mark_in_progress(dep_id)
            # Force an immediate synchronous repaint so the "installing…"
            # label shows before the (blocking) install. We use repaint()
            # rather than QApplication.processEvents() on purpose: this runs
            # as a slot inside the modal exec() loop, and processEvents() would
            # re-enter that loop (and pump unrelated timers/threads) — a
            # re-entrancy hazard. repaint() just paints, synchronously.
            self.repaint()
            result = self._install_one(item)
            self._results.append(result)
            self.mark_result(dep_id, result.success, result.message)
            self.repaint()
        # Loop done — let the user dismiss with Close.
        self.show_close_button()

    @staticmethod
    def _declined(item: MissingItem) -> InstallResult:
        return InstallResult(
            spec=item.spec,
            success=False,
            message="not selected for install",
            user_declined=True,
        )

    def _row_label(self, item: MissingItem) -> str:
        version = ".".join(str(part) for part in item.spec.min_version)
        if version == "0.0.0":
            return item.spec.display_name
        return f"{item.spec.display_name}  (need >= {version})"
