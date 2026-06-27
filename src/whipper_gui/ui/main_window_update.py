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
  * ``self._install_dialog`` / ``self._install_post_download`` — the progress
    dialog handle + phase flag the install signal-handlers read (so they can be
    bound methods queued to the GUI thread, not worker-thread closures)
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

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

log = logging.getLogger(__name__)


def _is_download_phase(status_message: str) -> bool:
    """True while the update is still DOWNLOADING (a determinate %-complete bar),
    False once it's moved to verify/install (a busy "working" bar — those phases
    have no meaningful percentage and are quick, so a bar pinned at 100% looked
    frozen). Keys on the phase labels ``update_install.download_and_install``
    emits via its ``status`` callback ("Checking…", "Downloading…", then
    "Verifying…"/"Installing…")."""
    return status_message.startswith(("Checking", "Downloading"))


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
        from whipper_gui.workers import start_worker_thread
        from whipper_gui.workers.update_worker import UpdateCheckWorker

        self._update_worker = UpdateCheckWorker()
        self._update_thread = QThread(self)
        self._update_worker.finished.connect(self._on_update_result)
        start_worker_thread(
            self._update_worker, self._update_thread, self._update_worker.run
        )

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
        """Download + verify + install `version` off-thread with progress.

        The worker's progress/status/finished signals are connected to BOUND
        METHODS of this window — NOT local closures or a lambda. This is for
        correctness, not style: a closure/lambda has no QObject receiver, so Qt
        connects it as a DIRECT connection and runs it on the *worker* thread
        when the signal fires there. These handlers touch the progress dialog (a
        widget) and pop a QMessageBox, and doing that off the GUI thread is
        illegal in Qt — it froze the window mid-update ("Not Responding",
        real-user report 2026-06-27). A bound method of this (GUI-thread) window
        is delivered as a queued connection, so it runs on the GUI thread. (Same
        bug + fix as the launch dependency check.)
        """
        if self._install_thread is not None:  # an install is already running
            return
        from PySide6.QtWidgets import QProgressDialog

        from whipper_gui.workers import start_worker_thread
        from whipper_gui.workers.update_worker import UpdateInstallWorker

        self._install_worker = UpdateInstallWorker(version)
        self._install_thread = QThread(self)

        dialog = QProgressDialog(
            f"Downloading Whipper GUI {version}…", "Cancel", 0, 100, self
        )
        dialog.setWindowTitle("Updating")
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        # Stashed on self so the worker→GUI handlers can be bound methods
        # (queued to the GUI thread). `_install_post_download` flips once we
        # leave the download phase, so a late progress(100) can't re-pin a
        # static 100% after we've switched to the busy "working" indicator.
        self._install_dialog = dialog
        self._install_post_download = False

        self._install_worker.progress.connect(self._on_install_progress)
        self._install_worker.status.connect(self._on_install_status)
        self._install_worker.finished.connect(self._on_update_install_finished)
        # Cancel button → stop between chunks; the worker cleans up the .part.
        dialog.canceled.connect(self._install_worker.cancel)
        # Standard teardown + start (finished → quit → deleteLater, run on spin-up).
        start_worker_thread(
            self._install_worker, self._install_thread, self._install_worker.run
        )
        dialog.show()

    def _on_install_progress(self, percent: float) -> None:
        """Update the download progress bar (GUI thread — queued from the
        worker's ``progress`` signal)."""
        dialog = self._install_dialog
        if dialog is None or self._install_post_download:
            return  # verify/install run as a busy bar, not a percentage
        if percent < 0:  # size unknown → busy indicator
            dialog.setRange(0, 0)
        else:
            dialog.setRange(0, 100)
            dialog.setValue(int(percent))

    def _on_install_status(self, message: str) -> None:
        """Reflect the current phase (GUI thread — queued from the worker's
        ``status`` signal)."""
        dialog = self._install_dialog
        if dialog is None:
            return
        dialog.setLabelText(message)
        # Once past the download the operation can't be safely cancelled (the
        # file swap is atomic), so retire the Cancel button (real-user report
        # 2026-06-13). And verify/install have no meaningful percentage and are
        # quick, so a bar pinned at 100% looked frozen ("hanging on 100%",
        # 2026-06-27) — switch to a MOVING busy indicator so it reads "working".
        if not _is_download_phase(message):
            dialog.setCancelButton(None)
            self._install_post_download = True
            dialog.setRange(0, 0)

    def _on_update_install_finished(self, ok: bool, payload: str) -> None:
        """Close the progress dialog; restart into the new version on success.

        Runs on the GUI thread (``finished`` is connected to this bound method,
        so Qt queues it there), which is what makes building the QMessageBox
        below safe — doing it on the worker thread is what froze the window.
        """
        from whipper_gui import appimage_integration as ai

        dialog = self._install_dialog
        self._install_dialog = None
        self._install_post_download = False
        if dialog is not None:
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

            # Log the relaunch explicitly. The new AppImage cold-extracts on its
            # first run (a 230 MB file → the window can take 20-30s to appear),
            # which reads as "it didn't reopen." Logging the spawn here makes the
            # log unambiguous about whether WE relaunched it vs. the user did
            # (real-user question, 2026-06-27), and lets us catch a spawn that
            # fails instead of silently closing into nothing.
            log.info("relaunching into the new version: %s", new_path)
            try:
                subprocess.Popen(  # noqa: S603 — our own verified binary
                    [str(new_path)], start_new_session=True
                )
            except OSError as exc:
                log.exception("relaunch failed")
                QMessageBox.information(
                    self,
                    "Update installed",
                    "The update is installed, but I couldn't relaunch the app "
                    f"automatically ({exc}). Please reopen Whipper GUI from your "
                    "menu or ~/Applications.",
                )
                return  # leave this window open so the user isn't left with nothing
            self.close()
