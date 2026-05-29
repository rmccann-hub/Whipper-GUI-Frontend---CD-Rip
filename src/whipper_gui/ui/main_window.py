"""Main window — composes the entire GUI.

Lays out the widgets in the order the brief specifies (drive picker →
disc info → track table → rip controls → progress) and wires worker
signals into widget slots.

This module is the only place that knows about ALL the pieces — every
other module is either a pure widget or a pure adapter. The signal
graph is documented inline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters.metaflac import MetaflacAdapter
from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    ReleaseDetail,
    ReleaseSummary,
)
from whipper_gui.adapters.whipper_backend import (
    WhipperBackend,
    WhipperError,
)
from whipper_gui.config import Config
from whipper_gui.deps.manager import DependencyManager
from whipper_gui.deps.resolvers import (
    AutoInstaller,
    ManualPrompt,
    MissingItem,
    QueuedInstaller,
)
from whipper_gui.parsers.cd_info import DiscInfo
from whipper_gui.parsers.rip_log import parse_rip_log
from whipper_gui.ui.disc_info_panel import DiscInfoPanel
from whipper_gui.ui.dialogs.manual_install import ManualInstallDialog
from whipper_gui.ui.dialogs.pending_installs import PendingInstallsDialog
from whipper_gui.ui.drive_picker import DrivePicker
from whipper_gui.ui.release_picker import ReleasePickerDialog
from whipper_gui.ui.rip_controls import RipControls
from whipper_gui.ui.rip_progress import RipProgress
from whipper_gui.ui.settings_dialog import SettingsDialog
from whipper_gui.ui.track_table import TrackTable
from whipper_gui.ui.unknown_album import (
    UnknownAlbumDialog,
    apply_placeholder_tags,
    launch_picard_for,
)
from whipper_gui.workers.mb_worker import MusicBrainzWorker
from whipper_gui.workers.rip_worker import RipParameters, RipWorker

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """The main window. Built by app.py with all dependencies injected."""

    # Tests can connect to this to know when a slot completed (used so
    # the user-side "after a rip finishes, helpers run" flow is testable).
    rip_post_processing_done = Signal()

    def __init__(
        self,
        config: Config,
        backend: WhipperBackend,
        mb_client: MusicBrainzClient,
        metaflac: MetaflacAdapter,
        dependency_manager: DependencyManager,
        save_config: Callable[[Config], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Whipper GUI")
        self.resize(960, 720)

        # --- Injected dependencies -----------------------------------------
        self._config: Config = config
        self._backend: WhipperBackend = backend
        self._mb_client: MusicBrainzClient = mb_client
        self._metaflac: MetaflacAdapter = metaflac
        self._dependency_manager: DependencyManager = dependency_manager
        # save_config is injectable so tests don't need to monkeypatch
        # whipper_gui.config.save. Defaults to the real save() function.
        if save_config is None:
            from whipper_gui import config as config_module
            save_config = config_module.save
        self._save_config: Callable[[Config], None] = save_config

        # --- Per-session state ---------------------------------------------
        self._current_release_id: str = ""
        self._current_release_detail: ReleaseDetail | None = None
        self._last_mb_releases: list[ReleaseSummary] = []
        # Active rip's worker/thread; set during a rip, cleared on finish.
        self._rip_worker: RipWorker | None = None
        self._rip_thread: QThread | None = None

        # --- Widgets -------------------------------------------------------
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._drive_picker: DrivePicker = DrivePicker(backend, self)
        self._disc_info_panel: DiscInfoPanel = DiscInfoPanel(self)
        self._track_table: TrackTable = TrackTable(self)
        self._rip_controls: RipControls = RipControls(config, self)
        self._rip_progress: RipProgress = RipProgress(self)

        root.addWidget(self._drive_picker)
        root.addWidget(self._disc_info_panel)
        root.addWidget(self._track_table, stretch=2)
        root.addWidget(self._rip_controls)
        root.addWidget(self._rip_progress, stretch=2)

        self.setCentralWidget(central)

        # --- MusicBrainz worker --------------------------------------------
        # One worker for the lifetime of the window. Lives on its own
        # QThread so HTTP queries don't block the GUI.
        self._mb_worker: MusicBrainzWorker = MusicBrainzWorker(mb_client)
        self._mb_thread: QThread = QThread(self)
        self._mb_worker.moveToThread(self._mb_thread)
        self._mb_thread.start()
        # Stop the thread cleanly when the window closes.
        self.destroyed.connect(self._mb_thread.quit)

        # --- Menus ---------------------------------------------------------
        self._build_menus()

        # --- Signal wiring -------------------------------------------------
        self._wire_signals()

    # --- Top-level lifecycle ------------------------------------------------

    def refresh_drives(self) -> None:
        """Populate the drive picker. Called by app.py at startup."""
        self._drive_picker.refresh()

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt API
        """Tear down the MB worker thread cleanly on window close."""
        if self._mb_thread.isRunning():
            self._mb_thread.quit()
            self._mb_thread.wait(2000)
        # Cancel any in-progress rip before the window goes away.
        if self._rip_worker is not None:
            self._rip_worker.cancel()
        super().closeEvent(event)  # type: ignore[arg-type]

    # --- Menus --------------------------------------------------------------

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        unknown_action = file_menu.addAction("Rip as &Unknown Album…")
        unknown_action.triggered.connect(self._on_rip_as_unknown)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.triggered.connect(self.close)

        tools_menu = menubar.addMenu("&Tools")
        settings_action = tools_menu.addAction("&Settings…")
        settings_action.triggered.connect(self._on_open_settings)

        deps_action = tools_menu.addAction("&Check dependencies…")
        deps_action.triggered.connect(self._on_check_dependencies)

    # --- Signal wiring ------------------------------------------------------

    def _wire_signals(self) -> None:
        # Drive selection → disc info + MB lookup pipeline.
        self._drive_picker.drive_changed.connect(self._on_drive_changed)

        # MB worker responses.
        self._mb_worker.releases_returned.connect(self._on_mb_releases)
        self._mb_worker.release_returned.connect(self._on_mb_release_detail)
        self._mb_worker.error.connect(self._on_mb_error)

        # Rip controls.
        self._rip_controls.rip_requested.connect(self._on_rip_requested)
        self._rip_controls.cancel_requested.connect(self._on_rip_cancel)

    # --- Slots: drive selection --------------------------------------------

    def _on_drive_changed(self, device: str) -> None:
        """User picked a drive — fetch disc info, then look up MB."""
        log.info("drive changed: %s", device)
        self._disc_info_panel.set_drive(device)
        self._track_table.clear()
        self._current_release_id = ""
        self._rip_controls.set_release_id("")
        self._rip_controls.set_drive(device)

        self._disc_info_panel.set_disc_info_loading()
        try:
            info = self._backend.disc_info(device)
        except WhipperError as exc:
            log.warning("disc_info failed: %s", exc)
            self._disc_info_panel.set_disc_info_error(str(exc))
            return

        self._disc_info_panel.set_disc_info(info)
        if info.musicbrainz_disc_id:
            self._disc_info_panel.set_mb_loading()
            # Run the MB query on the worker thread.
            self._mb_worker.lookup_disc_id(info.musicbrainz_disc_id)
        else:
            # Empty disc ID means whipper couldn't retrieve metadata
            # (per WhipperHostExportedImpl.disc_info's unknown-disc
            # fallback). Surface "not in MusicBrainz" instead of leaving
            # the panel stuck on "reading disc…" forever.
            self._disc_info_panel.set_mb_matches([])
            # Auto-prompt the Unknown Album flow: the user has a disc
            # inserted but MB doesn't recognize it, so the only path
            # forward is to rip as unknown. Surfacing the dialog
            # proactively beats requiring the user to discover
            # File → Rip as Unknown Album. Guard against re-prompting
            # if the user already accepted it in this session.
            if not self._rip_controls.is_unknown_mode():
                self.open_unknown_album_dialog()

    # --- Slots: MusicBrainz results ----------------------------------------

    def _on_mb_releases(self, releases: list[ReleaseSummary]) -> None:
        """MB lookup returned candidates."""
        self._last_mb_releases = list(releases)
        self._disc_info_panel.set_mb_matches(releases)

        if len(releases) == 1:
            self._fetch_release_detail(releases[0].mbid)
        elif len(releases) > 1:
            # Defer to user. The picker is modal; we block here briefly
            # to keep the flow linear.
            dialog = ReleasePickerDialog(releases, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                mbid = dialog.selected_mbid()
                if mbid:
                    self._fetch_release_detail(mbid)
        # If 0: nothing more to do here. The user can open the Unknown
        # Album flow via the menu (or future "Rip as unknown" button).

    def _on_mb_release_detail(self, detail: ReleaseDetail) -> None:
        self._current_release_detail = detail
        self._current_release_id = detail.summary.mbid
        self._track_table.set_release(detail)
        self._rip_controls.set_release_id(detail.summary.mbid)

    def _on_mb_error(self, message: str) -> None:
        log.warning("MB worker error: %s", message)
        self._disc_info_panel.set_mb_error(message)

    def _fetch_release_detail(self, mbid: str) -> None:
        self._mb_worker.fetch_release(mbid)

    # --- Slots: rip flow ----------------------------------------------------

    def _on_rip_requested(self, params: RipParameters) -> None:
        """User clicked Start. Validate, then start the worker thread."""
        # Only validate the track table for non-unknown rips — placeholder
        # tags will be applied after the fact in unknown mode.
        if not params.unknown:
            ok, message = self._track_table.validate()
            if not ok:
                QMessageBox.warning(self, "Cannot start rip", message)
                return

        self._rip_progress.clear()
        self._rip_progress.set_status("Starting rip…")
        self._rip_controls.set_rip_active(True)

        self._rip_worker = RipWorker(self._backend, params)
        self._rip_thread = QThread(self)
        self._rip_worker.moveToThread(self._rip_thread)

        self._rip_worker.log_line.connect(self._rip_progress.append_log_line)
        self._rip_worker.progress.connect(self._rip_progress.set_progress)
        self._rip_worker.error.connect(self._on_rip_error)
        self._rip_worker.finished.connect(self._on_rip_finished)

        # On finish, clean up the worker thread.
        self._rip_worker.finished.connect(self._rip_thread.quit)
        self._rip_thread.finished.connect(self._rip_thread.deleteLater)

        # Start the rip when the thread fires up.
        self._rip_thread.started.connect(self._rip_worker.start_rip)
        self._rip_thread.start()

    def _on_rip_cancel(self) -> None:
        if self._rip_worker is None:
            return
        self._rip_progress.set_status("Cancelling rip…")
        self._rip_worker.cancel()

    def _on_rip_error(self, message: str) -> None:
        log.warning("rip error: %s", message)
        self._rip_progress.set_status(f"Error: {message}")

    def _on_rip_finished(self, success: bool, log_path: str) -> None:
        """The rip subprocess exited."""
        log.info("rip finished: success=%s log=%s", success, log_path)
        self._rip_controls.set_rip_active(False)
        self._rip_progress.set_status("Done." if success else "Rip failed.")

        if log_path:
            log_file = Path(log_path)
            self._rip_progress.set_log_path(log_file)
            # Parse and render AR results if the file exists.
            try:
                text = log_file.read_text(encoding="utf-8")
                self._rip_progress.set_rip_log(parse_rip_log(text))
            except OSError as exc:
                log.warning("could not read rip log %s: %s", log_file, exc)

        # Clear references so a future rip starts cleanly. The thread
        # itself is auto-deleted via finished.connect(deleteLater) above.
        self._rip_worker = None
        self._rip_thread = None

        # Hook for tests to know that finish-time post-processing is done.
        self.rip_post_processing_done.emit()

    # --- Slots: menu actions -----------------------------------------------

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        dialog.check_dependencies_requested.connect(self._on_check_dependencies)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config = dialog.to_config()
            try:
                self._save_config(self._config)
            except OSError as exc:
                QMessageBox.warning(
                    self, "Couldn't save settings", f"{exc}"
                )

    def _on_check_dependencies(self) -> None:
        """Run the dependency subsystem with GUI-backed resolvers.

        Always shows the summary popup at the end. Use
        `run_dependency_check(show_summary=False)` to suppress the
        popup when nothing's missing — that's the launch-time path.
        """
        self.run_dependency_check(show_summary=True)

    def run_dependency_check(self, show_summary: bool = True) -> None:
        """Run check_all + resolve_missing with GUI-backed resolvers.

        Public so app.py can call it at launch. `show_summary=False`
        means the OK popup is suppressed when nothing's missing — but
        dialogs still appear for items that need attention.
        """
        auto = AutoInstaller(consent=self._gui_auto_consent)
        queued = QueuedInstaller(dialog_callback=self._gui_queued_dialog)
        manual = ManualPrompt(dialog_callback=self._gui_manual_dialog)

        # Reuse the registry from the injected DependencyManager so the
        # menu-driven check sees exactly the deps the app cares about.
        from whipper_gui.deps.manager import DependencyManager
        gui_manager = DependencyManager(
            auto=auto,
            queued=queued,
            manual=manual,
            specs=self._dependency_manager._specs,  # type: ignore[attr-defined]
        )

        report = gui_manager.check_all()
        if report.missing:
            gui_manager.resolve_missing(report)

        if show_summary or report.missing:
            self._show_dep_summary(report)

    def _gui_auto_consent(self, items: list[MissingItem]) -> bool:
        if not items:
            return True
        names = ", ".join(item.spec.display_name for item in items)
        choice = QMessageBox.question(
            self,
            "Install dependencies",
            f"Install the following automatically?\n\n{names}",
        )
        return choice == QMessageBox.StandardButton.Yes

    def _gui_queued_dialog(
        self, items: list[MissingItem]
    ) -> list[MissingItem]:
        dialog = PendingInstallsDialog(items, self)
        # PendingInstallsDialog emits install_requested when the user
        # clicks Install Selected but doesn't accept itself — its
        # original design called for the caller to drive a per-item
        # progress loop while the dialog stayed open. We don't do that
        # yet (the AutoInstaller runs synchronously after the callback
        # returns). Connect install_requested → accept so exec() unblocks
        # when the user clicks the button; otherwise the dialog sits
        # there forever and the user has to Cancel.
        dialog.install_requested.connect(dialog.accept)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_items()
        return []

    def _gui_manual_dialog(self, item: MissingItem) -> None:
        dialog = ManualInstallDialog(item.spec, item.probe, self)
        dialog.exec()

    def _show_dep_summary(self, report: object) -> None:
        """Post-check summary popup with install-failure detail when present.

        The popup format:
            "<ok_count> ok, <missing_count> missing/needs-attention."
            (blank line)
            "Install failures:"           ← only when failures exist
            "  - <dep>: <error message>"  ← one per failure
        """
        ok_count = len(getattr(report, "ok", []))
        missing_count = len(getattr(report, "missing", []))
        # Collect real install failures (not user declines — those are
        # surfaced via the dialog the user already saw).
        install_results = getattr(report, "install_results", [])
        failures = [
            r for r in install_results
            if not r.success and not getattr(r, "user_declined", False)
        ]

        message = f"{ok_count} ok, {missing_count} missing/needs-attention."
        if failures:
            failure_lines = "\n".join(
                f"  • {r.spec.display_name}: {r.message}" for r in failures
            )
            message = (
                f"{message}\n\nInstall failures:\n{failure_lines}\n\n"
                f"Full output is in ~/.local/share/whipper-gui/log.txt."
            )

        QMessageBox.information(
            self, "Dependency check complete", message
        )

    # --- Convenience for the Unknown Album flow ----------------------------

    def _on_rip_as_unknown(self) -> None:
        """File → Rip as Unknown Album… menu action.

        Validates that a drive is selected, then opens the Unknown Album
        dialog. Sets unknown mode on the rip controls so the user can
        click Start without needing a MusicBrainz release ID.
        """
        if not self._drive_picker.current_device():
            QMessageBox.warning(
                self,
                "Cannot rip",
                "Select a drive first.",
            )
            return
        self.open_unknown_album_dialog()

    def open_unknown_album_dialog(self) -> bool:
        """Show the Unknown Album confirmation. Returns True if accepted.

        Exposed publicly so a future "Rip as unknown" button or menu
        action can drive it. After the dialog accepts, this method sets
        unknown mode on the rip controls and stashes the user's Picard
        preference for use after the rip finishes.
        """
        dialog = UnknownAlbumDialog(
            auto_launch_picard_default=self._config.auto_launch_picard,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._rip_controls.set_unknown_mode(True)
        # Stash the user's Picard preference until after the rip finishes.
        self._pending_picard_launch: bool = dialog.auto_launch_picard()
        return True

    # --- Hook used by tests + the unknown flow -----------------------------

    def run_unknown_post_processing(
        self,
        rip_output_dir: Path,
        launch_picard: bool,
    ) -> None:
        """Apply placeholder tags + optionally launch Picard.

        Called after an unknown-mode rip finishes. Public so the same
        helper can be exercised from tests.
        """
        flac_files = sorted(rip_output_dir.rglob("*.flac"))
        apply_placeholder_tags(self._metaflac, flac_files)
        if launch_picard and flac_files:
            launch_picard_for(rip_output_dir)
