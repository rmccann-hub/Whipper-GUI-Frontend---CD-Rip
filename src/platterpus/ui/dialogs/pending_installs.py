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

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QThread, Signal, Slot
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

from platterpus.deps.resolvers import InstallResult, MissingItem

# Installs a single item and returns its outcome. Injected so the dialog
# doesn't depend on a concrete installer (tests pass a fake; the GUI passes
# an AutoInstaller-backed one).
#
# IMPORTANT: this runs on a WORKER THREAD (see _InstallWorker), so it MUST be
# thread-safe — a plain subprocess install is fine, but it must NOT touch Qt
# widgets or open dialogs (that crashes off the GUI thread). GUI-driven installs
# (e.g. the host-setup wizard) are handled by the caller on the GUI thread
# *before* this dialog runs — see main_window_deps._resolve_missing_unified.
InstallOne = Callable[[MissingItem], InstallResult]


class _InstallWorker(QObject):
    """Runs the install loop off the GUI thread (CLAUDE.md never-block rule).

    The actual install of each item (a `flatpak install`/`pip install`
    subprocess that can run for many seconds on a cold network) was previously
    called straight from the dialog's button slot — i.e. on the GUI thread,
    inside the modal `exec()` — which froze the whole app until it returned
    (real-user report on 0.4.2: the window went black mid-Picard-install). This
    worker does that blocking work on a `QThread` and reports each row's outcome
    back via queued signals, so the dialog stays live and repainting.
    """

    item_started = Signal(str)  # dep_id about to install
    item_done = Signal(str, object)  # dep_id, InstallResult
    finished = Signal(object)  # list[InstallResult], one per item, in order

    def __init__(
        self,
        items: list[MissingItem],
        checked_ids: set[str],
        install_one: InstallOne,
    ) -> None:
        super().__init__()
        self._items = items
        self._checked_ids = checked_ids
        self._install_one = install_one

    @Slot()
    def run(self) -> None:
        results: list[InstallResult] = []
        for item in self._items:
            dep_id = item.spec.dep_id
            if dep_id not in self._checked_ids:
                results.append(PendingInstallsDialog._declined(item))
                continue
            self.item_started.emit(dep_id)
            try:
                result = self._install_one(item)
            except Exception as exc:  # noqa: BLE001 — an installer bug must not
                # kill the worker thread; record it as a failure and move on.
                result = InstallResult(
                    spec=item.spec,
                    success=False,
                    message=f"install raised unexpectedly: {exc}",
                )
            results.append(result)
            self.item_done.emit(dep_id, result)
        self.finished.emit(results)


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
        # Off-GUI-thread install machinery (set while a loop runs).
        self._install_thread: QThread | None = None
        self._install_worker: _InstallWorker | None = None
        self._install_active: bool = False

        self.setWindowTitle("Pending installs")
        self.setModal(True)
        # Wide enough that the intro text and a Flatpak row don't truncate —
        # the cramped default made the dialog look broken (real-user report).
        self.setMinimumWidth(440)

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

    def mark_result(self, dep_id: str, success: bool, message: str = "") -> None:
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

        When `active`, checkboxes, the Install button **and Cancel** disable so
        the user can't double-fire installs *and* can't dismiss the dialog
        mid-install — the maintainer asked for the close/dismiss button to stay
        greyed out until the install actually completes. Close only appears
        (via `show_close_button`) once the loop has finished.
        """
        self._install_active = active
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(not active)
        self._install_button.setEnabled(not active)
        self._cancel_button.setEnabled(not active)

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

        While an install is in flight the dialog refuses to close at all — this
        gates the window-manager close (the title-bar ✕) as well as the Cancel
        button, so the user can't dismiss mid-install and leave the worker
        touching a destroyed dialog (the maintainer's "greyed-out until done").
        """
        if self._install_active:
            return
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
        """Install the ticked items on a worker thread, updating rows live.

        The install itself (a subprocess per item) runs OFF the GUI thread so
        the modal dialog stays responsive and repainting — see _InstallWorker.
        Per-item progress and the final results arrive via queued signals, which
        the modal `exec()` loop delivers on the GUI thread.
        """
        assert self._install_one is not None
        self.set_install_phase_active(True)
        self._results = []
        checked = {
            item.spec.dep_id
            for item in self._items
            if self._checkboxes[item.spec.dep_id].isChecked()
        }
        self._install_thread = QThread(self)
        self._install_worker = _InstallWorker(self._items, checked, self._install_one)
        self._install_worker.moveToThread(self._install_thread)
        self._install_worker.item_started.connect(self.mark_in_progress)
        self._install_worker.item_done.connect(self._on_item_done)
        self._install_worker.finished.connect(self._on_install_finished)
        # Standard worker teardown.
        self._install_worker.finished.connect(self._install_thread.quit)
        self._install_worker.finished.connect(self._install_worker.deleteLater)
        self._install_thread.finished.connect(self._install_thread.deleteLater)
        self._install_thread.started.connect(self._install_worker.run)
        self._install_thread.start()

    def _on_item_done(self, dep_id: str, result: InstallResult) -> None:
        """A row finished installing (queued from the worker → GUI thread)."""
        self.mark_result(dep_id, result.success, result.message)

    def _on_install_finished(self, results: list[InstallResult]) -> None:
        """The whole loop finished — record results and reveal Close."""
        self._results = list(results)
        self._install_worker = None
        self._install_thread = None
        self._install_active = False
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
