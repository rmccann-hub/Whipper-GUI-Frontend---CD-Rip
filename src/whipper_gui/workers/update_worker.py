"""UpdateCheckWorker — runs the release lookup off the GUI thread.

The check is one short HTTPS GET, but the GUI thread must never block on
the network (a slow or absent connection would freeze the window for the
whole timeout). Same minimal worker pattern as HostSetupWorker.

Signals:
  finished(object) — a `ReleaseInfo` or None (couldn't determine)
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from whipper_gui.update_check import latest_release

log = logging.getLogger(__name__)


class UpdateCheckWorker(QObject):
    """QObject worker: fetch the newest published release, emit it."""

    finished = Signal(object)  # ReleaseInfo | None

    @Slot()
    def run(self) -> None:
        try:
            result = latest_release()
        except Exception:  # noqa: BLE001 — a worker must always finish
            log.exception("update check crashed")
            result = None
        self.finished.emit(result)


class UpdateInstallWorker(QObject):
    """QObject worker: download + verify + install a release off-thread.

    Signals:
      progress(float) — download percentage (0–100), or -1.0 if unknown
      status(str) — short phase label (Downloading/Verifying/Installing…)
      finished(bool, str) — (True, installed path) or (False, error text)
    """

    progress = Signal(float)
    status = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, version: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._version: str = version
        # Plain bool: atomic under the GIL; set from the GUI thread when the
        # user cancels the progress dialog or closes the window.
        self._cancelled: bool = False

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        from whipper_gui.update_install import UpdateInstallError, download_and_install

        try:
            path = download_and_install(
                self._version,
                progress=self.progress.emit,
                cancelled=lambda: self._cancelled,
                status=self.status.emit,
            )
        except UpdateInstallError as exc:
            self.finished.emit(False, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — a worker must always finish
            log.exception("update install crashed")
            self.finished.emit(False, f"unexpected error: {exc}")
            return
        self.finished.emit(True, str(path))
