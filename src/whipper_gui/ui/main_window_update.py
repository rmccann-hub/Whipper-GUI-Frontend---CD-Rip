"""In-app self-update flow for the main window (KDD-17b).

Extracted from ``main_window`` (2026-06-13 modularization) as a mixin so
the update concern lives in one focused file while its methods stay
reachable as ``window._on_...`` (which the test-suite and Qt signal
connections rely on). ``MainWindow`` inherits this; the methods run with
``self`` being the real window.

Contract this mixin expects from the host window (all set in
``MainWindow.__init__``):
  * ``self._update_worker`` / ``self._update_thread`` — the check worker+thread slots
  * ``self._install_worker`` / ``self._install_thread`` — the install worker+thread slots
  * ``self`` is a ``QWidget`` (used as the parent for dialogs)

Future contributors: the actual download/verify/install lives in
``update_install.py`` and ``workers/update_worker.py`` — this file is only
the GUI orchestration (threads, the progress dialog, the restart prompt).
A delta-update path via AppImageUpdate is still possible (the build embeds
zsync update-information); wiring it would slot in at ``_on_update_result``
beside the in-app download branch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:  # import only for type hints
    from PySide6.QtWidgets import QProgressDialog

log = logging.getLogger(__name__)


class UpdateMixin:
    """Help → Check for updates, and the download/verify/install/restart UI."""

    def _on_check_updates(self) -> None:
        """Help → Check for updates: ask GitHub for the newest release.

        Runs off-thread (a slow connection must not freeze the window);
        the result lands in _on_update_result. Delivery of the update is
        NOT ours: the AppImage embeds zsync update-information, so we
        delegate to an AppImageUpdate tool or open the releases page.
        """
        if self._update_thread is not None:  # a check is already running
            return
        from whipper_gui.workers.update_worker import UpdateCheckWorker

        self._update_worker = UpdateCheckWorker()
        self._update_thread = QThread(self)
        self._update_worker.moveToThread(self._update_thread)
        self._update_worker.finished.connect(self._on_update_result)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_thread.start()

    def _on_update_result(self, info: object) -> None:
        """Show the verdict; offer the standard update path when newer."""
        from whipper_gui import __version__, appimage_integration
        from whipper_gui.update_check import RELEASES_PAGE_URL, is_newer

        self._update_worker = None
        self._update_thread = None

        if info is None:
            QMessageBox.information(
                self,
                "Check for updates",
                "Couldn't check for updates (no connection, or GitHub is "
                f"unreachable). You can always look yourself:\n{RELEASES_PAGE_URL}",
            )
            return
        version = getattr(info, "version", "")
        url = getattr(info, "url", RELEASES_PAGE_URL)
        if not is_newer(version, __version__):
            QMessageBox.information(
                self,
                "Check for updates",
                f"You're up to date — v{__version__} is the newest release.",
            )
            return

        # Newer release exists. When running as an AppImage, update fully
        # in-app: download + verify against the published .sha256 + install
        # to ~/Applications + offer a restart (KDD-17b amendment 2026-06-10 —
        # the original delegate-to-AppImageUpdate plan dead-ended because
        # that tool isn't installed on the target systems). Source/pipx
        # installs can't be file-swapped, so they get the release page.
        appimage = appimage_integration.appimage_path()
        if appimage is not None:
            choice = QMessageBox.question(
                self,
                "Update available",
                f"Version {version} is available (you have {__version__}).\n\n"
                "Update now? The new version is downloaded in the background, "
                "verified, and installed to ~/Applications — then the app "
                "restarts itself.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if choice == QMessageBox.StandardButton.Yes:
                self._begin_update_install(version)
            return
        choice = QMessageBox.question(
            self,
            "Update available",
            f"Version {version} is available (you have {__version__}).\n\n"
            "Open the download page?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(url))

    def _begin_update_install(self, version: str) -> None:
        """Download + verify + install `version` off-thread with progress."""
        if self._install_thread is not None:  # an install is already running
            return
        from PySide6.QtWidgets import QProgressDialog

        from whipper_gui.workers.update_worker import UpdateInstallWorker

        self._install_worker = UpdateInstallWorker(version)
        self._install_thread = QThread(self)
        self._install_worker.moveToThread(self._install_thread)

        dialog = QProgressDialog(
            f"Downloading Whipper GUI {version}…", "Cancel", 0, 100, self
        )
        dialog.setWindowTitle("Updating")
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)

        def on_progress(percent: float) -> None:
            if percent < 0:  # size unknown → busy indicator
                dialog.setRange(0, 0)
            else:
                dialog.setRange(0, 100)
                dialog.setValue(int(percent))

        def on_status(message: str) -> None:
            # Tell the user which phase we're in — the post-download steps
            # (verify + install) are quick but used to look like a freeze.
            dialog.setLabelText(message)
            # Once we leave the download phase the operation can't be safely
            # cancelled (the file swap is atomic), so retire the Cancel button
            # rather than leave a button that "does nothing" (real-user report
            # 2026-06-13). The Esc/close shortcut is disabled with it.
            if not message.startswith(("Checking", "Downloading")):
                dialog.setCancelButton(None)

        self._install_worker.progress.connect(on_progress)
        self._install_worker.status.connect(on_status)
        self._install_worker.finished.connect(
            lambda ok, payload: self._on_update_install_finished(ok, payload, dialog)
        )
        self._install_worker.finished.connect(self._install_thread.quit)
        self._install_thread.finished.connect(self._install_thread.deleteLater)
        self._install_thread.started.connect(self._install_worker.run)
        # Cancel button → stop between chunks; the worker cleans up the .part.
        dialog.canceled.connect(self._install_worker.cancel)
        self._install_thread.start()
        dialog.show()

    def _on_update_install_finished(
        self, ok: bool, payload: str, dialog: QProgressDialog
    ) -> None:
        """Close the progress dialog; restart into the new version on success."""
        from whipper_gui import appimage_integration as ai

        try:
            dialog.close()
        except Exception:  # noqa: BLE001 — closing UI must never block the flow
            pass
        self._install_worker = None
        self._install_thread = None
        if not ok:
            QMessageBox.warning(
                self,
                "Update failed",
                f"The update wasn't installed: {payload}\n\n"
                "Nothing was changed — you can keep using this version or "
                "download the new one from the releases page.",
            )
            return
        new_path = Path(payload)
        # Point the menu/desktop entries at the new file (best-effort —
        # normally a no-op since the path is the same canonical location).
        try:
            ai.integrate(new_path)
        except Exception:  # noqa: BLE001 — the update itself succeeded
            log.exception("post-update re-integration failed")
        choice = QMessageBox.question(
            self,
            "Update installed",
            "The new version is installed. Restart Whipper GUI now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            import subprocess

            subprocess.Popen(  # noqa: S603 — our own verified binary
                [str(new_path)], start_new_session=True
            )
            self.close()
