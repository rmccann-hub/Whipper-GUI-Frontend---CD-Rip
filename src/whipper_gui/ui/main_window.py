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
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
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
from whipper_gui.drive_access import (
    SEVERITY_NO_DEVICE,
    SEVERITY_OK,
    DriveAccessDiagnosis,
    diagnose_drive_access,
)
from whipper_gui import drive_control
from whipper_gui.offset_config import is_offset_configured
from whipper_gui.parsers.cd_info import DiscInfo
from whipper_gui.parsers.rip_log import parse_rip_log
from whipper_gui.ui.disc_info_panel import DiscInfoPanel
from whipper_gui.ui.drive_setup_dialog import DriveSetupDialog
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
    apply_track_tags,
    launch_picard_for,
)
from whipper_gui.workers.mb_worker import MusicBrainzWorker
from whipper_gui.workers.rip_worker import RipParameters, RipWorker

log = logging.getLogger(__name__)

# How long after Cancel to wait before auto-force-stopping the drive (the
# in-container reader can keep it spinning). The user can hit Force stop to
# escalate sooner.
_FORCE_STOP_COUNTDOWN_MS: int = 5000


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
        # Track count for the current disc (from whipper cd info). Used to
        # render numbered blank rows when MusicBrainz has no match.
        self._current_num_tracks: int = 0
        # Active rip's worker/thread; set during a rip, cleared on finish.
        self._rip_worker: RipWorker | None = None
        self._rip_thread: QThread | None = None
        # Params of the in-flight rip, captured at start so the finish
        # handler knows whether it was an unknown-mode rip (and where the
        # FLACs landed) without depending on the controls' current state.
        self._active_rip_params: RipParameters | None = None
        # Set when the user hits Cancel, so the finish handler reports a
        # cancellation rather than a failure.
        self._rip_cancelled: bool = False
        # Auto-escalation: after Cancel, if the in-container reader keeps the
        # drive spinning, force-stop it once the countdown elapses. Guard so
        # we force-stop at most once per cancel.
        self._force_stop_done: bool = False
        self._force_stop_timer: QTimer = QTimer(self)
        self._force_stop_timer.setSingleShot(True)
        self._force_stop_timer.timeout.connect(self._auto_force_stop)
        # Handle to the daemon thread that runs the (blocking) force-stop, so
        # callers/tests can join it; None when no force-stop is in flight.
        self._force_stop_thread: threading.Thread | None = None
        # Holds the daemon thread for a manual/auto eject so tests can join it.
        self._eject_thread: threading.Thread | None = None
        # Whether the user asked to launch Picard after an unknown rip.
        self._pending_picard_launch: bool = False
        # Guard so the "no drive — here's the fix" nudge auto-shows at most
        # once per session (refreshing shouldn't re-pop the dialog).
        self._drive_access_nudged: bool = False

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

        # First-run: if no read offset is configured yet, offer the drive-setup
        # wizard once (dismissible). Deferred to the event loop so it appears
        # after the window is shown; in tests (no exec loop) it never fires, so
        # it can't interfere — _should_offer_drive_setup() is tested directly.
        QTimer.singleShot(0, self._maybe_offer_drive_setup)

    # --- Top-level lifecycle ------------------------------------------------

    def refresh_drives(self) -> None:
        """Populate the drive picker. Called by app.py at startup."""
        self._drive_picker.refresh()

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt API
        """Tear down the MB worker thread cleanly on window close."""
        # Disarm the auto-force-stop so it can't fire into a torn-down window.
        self._force_stop_timer.stop()
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

        drive_setup_action = tools_menu.addAction("Set up &drive…")
        drive_setup_action.triggered.connect(self._on_drive_setup)

        diagnose_action = tools_menu.addAction("Diagnose drive &access…")
        diagnose_action.triggered.connect(self._show_drive_access_diagnosis)
        # The dependency check lives only on the Settings dialog's
        # "Check dependencies" button (it also runs automatically at
        # launch) — no duplicate Tools-menu entry.

        help_menu = menubar.addMenu("&Help")
        guide_action = help_menu.addAction("&User Guide…")
        guide_action.triggered.connect(self._on_show_help)
        help_menu.addSeparator()
        about_action = help_menu.addAction("&About Whipper GUI…")
        about_action.triggered.connect(self._on_show_about)

    # --- Signal wiring ------------------------------------------------------

    def _wire_signals(self) -> None:
        # Drive selection → disc info + MB lookup pipeline.
        self._drive_picker.drive_changed.connect(self._on_drive_changed)
        # No drive found → offer an actionable diagnosis (once per session).
        self._drive_picker.drives_unavailable.connect(self._on_drives_unavailable)
        # Manual Eject button.
        self._drive_picker.eject_requested.connect(self._on_eject_requested)

        # MB worker responses.
        self._mb_worker.releases_returned.connect(self._on_mb_releases)
        self._mb_worker.release_returned.connect(self._on_mb_release_detail)
        self._mb_worker.error.connect(self._on_mb_error)

        # Rip controls.
        self._rip_controls.rip_requested.connect(self._on_rip_requested)
        self._rip_controls.cancel_requested.connect(self._on_rip_cancel)
        self._rip_controls.force_stop_requested.connect(self._on_force_stop_button)

    # --- Slots: drive selection --------------------------------------------

    def _on_drive_changed(self, device: str) -> None:
        """User picked a drive — fetch disc info, then look up MB."""
        log.info("drive changed: %s", device)
        self._disc_info_panel.set_drive(device)
        self._track_table.clear()
        self._current_release_id = ""
        self._current_num_tracks = 0
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
        # Remember the disc's track count so we can show numbered blank
        # rows if MusicBrainz turns up nothing.
        self._current_num_tracks = info.num_tracks
        if info.musicbrainz_disc_id:
            self._disc_info_panel.set_mb_loading()
            # Run the MB query on the worker thread. A 0-result response
            # routes to _handle_no_mb_match (same as an empty disc ID).
            self._mb_worker.lookup_disc_id(info.musicbrainz_disc_id)
        else:
            # Empty disc ID means whipper couldn't retrieve metadata
            # (per WhipperHostExportedImpl.disc_info's unknown-disc
            # fallback). Surface "not in MusicBrainz" instead of leaving
            # the panel stuck on "reading disc…" forever.
            self._disc_info_panel.set_mb_matches([])
            self._handle_no_mb_match()

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
        else:
            # 0 matches: the disc had a MusicBrainz disc ID but no release
            # is registered for it. Same outcome as a disc with no ID —
            # show blank track rows and offer the unknown-album rip.
            self._handle_no_mb_match()

    def _on_mb_release_detail(self, detail: ReleaseDetail) -> None:
        self._current_release_detail = detail
        self._current_release_id = detail.summary.mbid
        self._track_table.set_release(detail)
        self._rip_controls.set_release_id(detail.summary.mbid)

    def _on_mb_error(self, message: str) -> None:
        log.warning("MB worker error: %s", message)
        self._disc_info_panel.set_mb_error(message)
        # A lookup *failure* (network down, TLS error, rate limit) must not
        # leave the track table empty the way it did before — fall back to
        # numbered placeholder rows so the user can still see the disc and
        # start an unknown-album rip. We don't auto-open the unknown dialog
        # here (unlike a definitive no-match): an error isn't proof the disc
        # is unknown, so we let the user choose via File → Rip as Unknown.
        if self._current_num_tracks > 0:
            self._track_table.set_placeholder_tracks(self._current_num_tracks)

    def _handle_no_mb_match(self) -> None:
        """No MusicBrainz match for the inserted disc.

        Shared by the empty-disc-ID path and the 0-result lookup path.
        Shows numbered blank track rows (so the user sees the disc's
        contents) and proactively offers the unknown-album rip. The
        unknown-mode guard stops it re-prompting once the user has
        already accepted in this session.
        """
        if self._current_num_tracks > 0:
            self._track_table.set_placeholder_tracks(self._current_num_tracks)
        if not self._rip_controls.is_unknown_mode():
            self.open_unknown_album_dialog()

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
        else:
            # Unknown disc: name the folder from the album fields the user
            # typed (e.g. "jimmy2/for/…") instead of the literal
            # "Unknown Artist/Unknown Album". whipper's %A/%d would be the
            # disc-ID hash here, so we inject the (sanitized) literals
            # directly; blanks fall back to the Unknown placeholders.
            album = self._track_table.album_metadata()
            artist = _safe_path_segment(album.artist) or "Unknown Artist"
            title = _safe_path_segment(album.title) or "Unknown Album"
            params = replace(
                params,
                track_template=f"{artist}/{title}/%t - Track %t",
                disc_template=f"{artist}/{title}/{title}",
            )

        self._rip_progress.clear()
        self._rip_progress.set_status("Starting rip…")
        self._rip_controls.set_rip_active(True)

        # Remember the params so the finish handler can run unknown-mode
        # post-processing (tag the FLACs from the track table) against the
        # right output directory.
        self._active_rip_params = params
        # Cleared here, set in _on_rip_cancel — so the finish handler can
        # say "cancelled" instead of "failed".
        self._rip_cancelled = False
        # Disarm any pending auto-force-stop from a previous cancel, so its
        # countdown can't fire into this fresh rip.
        self._force_stop_timer.stop()
        self._force_stop_done = False

        self._rip_worker = RipWorker(self._backend, params)
        self._rip_thread = QThread(self)
        self._rip_worker.moveToThread(self._rip_thread)

        self._rip_worker.log_line.connect(self._rip_progress.append_log_line)
        self._rip_worker.progress.connect(self._rip_progress.set_progress)
        self._rip_worker.status.connect(self._rip_progress.set_status)
        # Follow the rip in the track table — highlight the row whipper is
        # currently working on so the user can see progress track by track.
        self._rip_worker.current_track.connect(self._track_table.highlight_track)
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
        self._rip_cancelled = True
        self._force_stop_done = False
        # The in-container reader can take a moment to stop; set expectations,
        # and arm the auto force-stop in case it doesn't stop on its own.
        secs = _FORCE_STOP_COUNTDOWN_MS // 1000
        self._rip_progress.set_status(
            f"Cancelling rip… if the drive keeps spinning it'll be "
            f"force-stopped in {secs}s (or hit Force stop)."
        )
        self._rip_worker.cancel()
        self._force_stop_timer.start(_FORCE_STOP_COUNTDOWN_MS)

    def _auto_force_stop(self) -> None:
        """Countdown elapsed after Cancel — force-stop if we haven't already."""
        if self._force_stop_done:
            return
        self._do_force_stop("auto")

    def _on_force_stop_button(self) -> None:
        """User pressed Force stop — escalate immediately."""
        self._force_stop_timer.stop()
        self._do_force_stop("manual")

    def _do_force_stop(self, trigger: str) -> None:
        """Eject + kill the in-container reader so the drive stops spinning.

        Runs on a daemon thread because `eject` and `distrobox enter` can each
        block for their timeout — we must not freeze the GUI. We don't touch
        widgets from the thread; the status is set here on the GUI thread
        first. See drive_control for the (user-approved) Rule #3 exception.
        """
        self._force_stop_done = True
        device = self._drive_picker.current_device() or ""
        log.info("force-stopping drive (%s trigger), device=%s", trigger, device or "(default)")
        self._rip_progress.set_status(
            "Force-stopping the drive (eject + stopping the reader)…"
        )
        thread = threading.Thread(
            target=drive_control.force_stop_drive,
            kwargs={"device": device},
            daemon=True,
        )
        self._force_stop_thread = thread
        thread.start()

    def _on_eject_requested(self, device: str) -> None:
        """User clicked Eject — eject the selected disc."""
        self._eject_async(device, status="Ejecting the disc…")

    def _eject_async(self, device: str, status: str) -> None:
        """Eject `device` off a daemon thread.

        `eject` can block for its subprocess timeout, so — like the
        force-stop — we never call it on the GUI thread. Best-effort: the
        status line is informational and we don't surface a failure modally
        (a missing/empty tray isn't worth a dialog). The thread is stored so
        tests can join it deterministically.
        """
        log.info("ejecting device=%s", device or "(default)")
        self._rip_progress.set_status(status)
        thread = threading.Thread(
            target=drive_control.eject_drive,
            kwargs={"device": device},
            daemon=True,
        )
        self._eject_thread = thread
        thread.start()

    def _on_rip_error(self, message: str) -> None:
        log.warning("rip error: %s", message)
        self._rip_progress.set_status(f"Error: {message}")

    def _on_rip_finished(self, success: bool, log_path: str) -> None:
        """The rip subprocess exited."""
        log.info("rip finished: success=%s log=%s", success, log_path)
        self._rip_controls.set_rip_active(False)
        # Default status; replaced with a fidelity summary below if the
        # rip succeeded and we can parse its log. Distinguish a user
        # cancellation from a genuine failure (both report success=False).
        if success:
            status = "Done."
        elif self._rip_cancelled:
            status = "Rip cancelled by user. Partial files may remain."
        else:
            status = "Rip failed."
        self._rip_progress.set_status(status)

        if log_path:
            log_file = Path(log_path)
            self._rip_progress.set_log_path(log_file)
            # Parse and render AR results if the file exists.
            try:
                text = log_file.read_text(encoding="utf-8")
                rip_log = parse_rip_log(text)
                self._rip_progress.set_rip_log(rip_log)
                # Replace the disc panel's blank AccurateRip field with the
                # real outcome (e.g. "not in database" for a CD-R) instead of
                # the old misleading static "verified during rip".
                self._disc_info_panel.set_accuraterip_result(rip_log)
                if success:
                    self._rip_progress.set_status(
                        _fidelity_summary(rip_log)
                    )
            except OSError as exc:
                log.warning("could not read rip log %s: %s", log_file, exc)

        # Unknown-mode post-processing: tag the FLACs from the (possibly
        # edited) track table and optionally launch Picard. Only on a
        # successful rip, and only when the rip we started was unknown-mode.
        # Scope tagging to the album folder whipper just wrote — the .log
        # lands next to the FLACs, so its parent is that folder. Using the
        # configured output root instead would re-tag every previously
        # ripped album in the library with THIS disc's metadata.
        params = self._active_rip_params
        if success and params is not None and params.unknown:
            rip_dir = Path(log_path).parent if log_path else params.output_dir
            try:
                self.run_unknown_post_processing(
                    rip_dir, self._pending_picard_launch
                )
            except Exception:  # noqa: BLE001 — tagging must never crash the GUI
                log.exception("unknown-album post-processing failed")

        # Auto-eject on a clean finish if the user opted in. Only on success —
        # a failed/cancelled rip leaves the disc in so the user can retry, and
        # ejecting mid-failure could fight the force-stop path.
        if success and self._config.auto_eject_after_rip:
            device = (
                params.drive if params is not None
                else self._drive_picker.current_device() or ""
            )
            self._eject_async(device, status="Rip complete — ejecting the disc…")

        # Clear references so a future rip starts cleanly. The thread
        # itself is auto-deleted via finished.connect(deleteLater) above.
        self._rip_worker = None
        self._rip_thread = None
        self._active_rip_params = None

        # Hook for tests to know that finish-time post-processing is done.
        self.rip_post_processing_done.emit()

    # --- Slots: menu actions -----------------------------------------------

    def _on_show_help(self) -> None:
        """Help → User Guide."""
        # Imported lazily so the Help dialogs aren't a startup-import cost.
        from whipper_gui.ui.help_dialogs import HelpDialog

        HelpDialog(self).exec()

    def _on_show_about(self) -> None:
        """Help → About: version number and support-relevant info."""
        from whipper_gui.ui.help_dialogs import AboutDialog

        AboutDialog(whipper_path=self._config.whipper_path, parent=self).exec()

    def _on_drive_setup(self) -> None:
        """Tools → Set up drive: launch the calibration wizard.

        Targets the currently-selected drive (whipper auto-detects a single
        drive anyway, but passing the device is correct for multi-drive).
        """
        device = self._drive_picker.current_device()
        if not device:
            QMessageBox.warning(
                self, "Set up drive", "Select a drive first."
            )
            return
        dialog = DriveSetupDialog(
            self._backend, device, self, current_offset=self._config.read_offset
        )
        dialog.manual_offset_saved.connect(self._on_manual_offset_saved)
        dialog.exec()

    def _should_offer_drive_setup(self) -> bool:
        """True when we should auto-offer calibration on first run.

        Only when (a) we haven't offered before and (b) no read offset is
        configured (neither whipper.conf nor our --offset override). whipper
        can't rip without one, so a fresh user is otherwise stuck.
        """
        if self._config.drive_setup_prompted:
            return False
        return not is_offset_configured(self._config.override_read_offset)

    def _maybe_offer_drive_setup(self) -> None:
        """Show the one-time, dismissible first-run calibration offer."""
        if not self._should_offer_drive_setup():
            return
        # Record the offer first so a decline (or any path out) never re-nags;
        # afterwards calibration lives on Tools → Set up drive….
        self._config.drive_setup_prompted = True
        self._save_config(self._config)
        choice = QMessageBox.question(
            self,
            "Set up your drive",
            "Your drive's read offset isn't configured yet — whipper needs it "
            "to rip. Set it up now?\n\n"
            "You can auto-detect it (insert a popular commercial CD) or enter "
            "it by hand. You can also do this later from Tools → Set up drive….",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self._on_drive_setup()

    def _on_manual_offset_saved(self, value: int) -> None:
        """Store a hand-entered read offset as the GUI's --offset override.

        This is the fallback when auto-detection can't run (no AccurateRip
        disc). We persist it to our own config and pass it as `--offset` at
        rip time, so whipper.conf is never hand-authored (KDD-15).
        """
        self._config.read_offset = value
        self._config.override_read_offset = True
        self._rip_controls.set_config(self._config)
        self._save_config(self._config)
        log.info("manual read offset saved: %+d", value)

    # --- Slots: drive-access diagnostics -----------------------------------

    def _on_drives_unavailable(self) -> None:
        """A refresh found no drives — proactively offer a fix, once.

        Only auto-interrupts when the diagnosis is *actionable* (a
        permission fix). "No device connected" stays quiet (there's no
        command to run); the Tools → Diagnose entry is there for that.
        """
        if self._drive_access_nudged:
            return
        diagnosis = diagnose_drive_access()
        if diagnosis.actionable:
            self._drive_access_nudged = True
            self._present_drive_diagnosis(diagnosis)

    def _show_drive_access_diagnosis(self) -> None:
        """Tools → Diagnose drive access: always show, any severity."""
        self._present_drive_diagnosis(diagnose_drive_access())

    def _present_drive_diagnosis(self, diagnosis: DriveAccessDiagnosis) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Drive access")
        box.setIcon(
            QMessageBox.Icon.Information
            if diagnosis.severity in (SEVERITY_OK, SEVERITY_NO_DEVICE)
            else QMessageBox.Icon.Warning
        )
        box.setText(diagnosis.summary)
        info = diagnosis.detail
        if diagnosis.fix_command:
            info += (
                "\n\nRun this, then log out and back in:\n    "
                f"{diagnosis.fix_command}"
            )
        box.setInformativeText(info)
        # Let the user select/copy the fix command out of the dialog.
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        dialog.check_dependencies_requested.connect(self._on_check_dependencies)
        # "Re-detect…" next to the read-offset field opens the same wizard.
        dialog.detect_offset_requested.connect(self._on_drive_setup)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config = dialog.to_config()
            # Push the new config into the rip controls so the next rip
            # reflects the edits (output dir, templates, Continue-on-CD-R).
            self._rip_controls.set_config(self._config)
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
        # Optional deps (e.g. Picard) shouldn't nag at launch or count as a
        # problem — set them aside so only required deps drive resolution.
        optional_missing = [
            item for item in report.missing
            if getattr(item.spec, "optional", False)
        ]
        report.missing = [
            item for item in report.missing
            if not getattr(item.spec, "optional", False)
        ]
        if report.missing:
            gui_manager.resolve_missing(report)

        if show_summary or report.missing:
            self._show_dep_summary(report, optional_missing=optional_missing)

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

    def _show_dep_summary(
        self, report: object, optional_missing: list | None = None
    ) -> None:
        """Post-check summary popup with install-failure detail when present.

        The popup format:
            "<ok_count> ok, <missing_count> missing/needs-attention."
            "Optional (not installed): <names>"   ← only when present
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
        if optional_missing:
            names = ", ".join(item.spec.display_name for item in optional_missing)
            message += f"\nOptional (not installed): {names}."
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
        """Tag the FLACs from the track table + optionally launch Picard.

        Called after an unknown-mode rip finishes. The track table holds
        the placeholder rows the user saw before ripping — including any
        edits they made to the titles/artist/album/year — so we write
        those through to the FLAC tags (blank fields fall back to the
        "Unknown" placeholders). Public so it can be exercised from tests.
        """
        flac_files = sorted(rip_output_dir.rglob("*.flac"))
        apply_track_tags(
            self._metaflac,
            flac_files,
            self._track_table.album_metadata(),
            self._track_table.tracks(),
        )
        if launch_picard and flac_files:
            launch_picard_for(rip_output_dir)


def _safe_path_segment(value: str) -> str:
    """Make a user string safe to drop literally into a whipper template.

    Strips whitespace, turns `/` into `-` (it'd create stray subdirs), and
    drops `%` (whipper treats it as a format code). Returns "" for blank
    input so callers can fall back to an "Unknown …" placeholder.
    """
    return (value or "").strip().replace("/", "-").replace("%", "")


def _fidelity_summary(rip_log: "object") -> str:
    """One-line rip-quality verdict for the status label.

    whipper rips each track twice and records a Test CRC and Copy CRC; a
    match means the two independent reads were bit-identical (a secure,
    archival-quality rip). This surfaces that confidence directly so the
    user doesn't have to open the log to confirm fidelity — addressing the
    "I can't confirm fidelity" feedback. AccurateRip is reported only when
    it actually matched, since it's "not in database" for any disc nobody
    has submitted (e.g. CD-Rs).
    """
    tracks = getattr(rip_log, "tracks", ()) or ()
    total = len(tracks)
    if total == 0:
        return "Done."
    verified = sum(
        1
        for t in tracks
        if getattr(t, "test_crc", "")
        and getattr(t, "test_crc", "") == getattr(t, "copy_crc", "")
    )
    if verified == total:
        summary = f"Done — all {total} tracks verified, Test/Copy CRCs match."
    else:
        summary = (
            f"Done — {verified}/{total} tracks CRC-verified; "
            f"check the log for the rest."
        )
    # Append AccurateRip confirmation only when at least one track matched.
    ar = (getattr(rip_log, "accuraterip_summary", "") or "").lower()
    if "exact match" in ar or "found" in ar:
        summary += " AccurateRip confirmed."
    return summary
