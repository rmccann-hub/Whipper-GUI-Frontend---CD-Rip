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
from collections.abc import Callable

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.adapters import cover_art
from whipper_gui.adapters.accuraterip_offsets import OffsetDatabase
from whipper_gui.adapters.ctdb_client import CTDBClient, CtdbHttpImpl
from whipper_gui.adapters.metaflac import MetaflacAdapter
from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    ReleaseDetail,
    ReleaseSummary,
)
from whipper_gui.adapters.whipper_backend import (
    DiscInfo,
    WhipperBackend,
)
from whipper_gui.config import Config
from whipper_gui.deps.manager import DependencyManager
from whipper_gui.ui.disc_info_panel import DiscInfoPanel
from whipper_gui.ui.drive_picker import DrivePicker

# _DialogQueuedResolver moved to main_window_deps with the dependency UI;
# re-exported here for the test-facing API (tests import it from main_window).
from whipper_gui.ui.main_window_deps import (  # noqa: F401
    DependencyMixin,
    _DialogQueuedResolver,
)
from whipper_gui.ui.main_window_drive import DriveMixin

# fidelity_summary / safe_path_segment are re-exported for the test-facing
# API (`from ...main_window import _fidelity_summary`); their internal callers
# now live in RipMixin, so they're intentionally unused *in this module*.
from whipper_gui.ui.main_window_helpers import (  # noqa: F401
    fidelity_summary as _fidelity_summary,
)
from whipper_gui.ui.main_window_helpers import (
    friendly_disc_scan_error as _friendly_disc_scan_error,
)
from whipper_gui.ui.main_window_helpers import (  # noqa: F401
    safe_path_segment as _safe_path_segment,
)
from whipper_gui.ui.main_window_provision import ProvisioningMixin
from whipper_gui.ui.main_window_rip import RipMixin
from whipper_gui.ui.main_window_update import UpdateMixin
from whipper_gui.ui.release_picker import ReleasePickerDialog
from whipper_gui.ui.rip_controls import RipControls
from whipper_gui.ui.rip_progress import RipProgress
from whipper_gui.ui.settings_dialog import SettingsDialog
from whipper_gui.ui.track_table import TrackTable
from whipper_gui.workers.mb_worker import MusicBrainzWorker
from whipper_gui.workers.rip_worker import RipParameters, RipWorker

log = logging.getLogger(__name__)


class MainWindow(
    QMainWindow,
    RipMixin,
    UpdateMixin,
    ProvisioningMixin,
    DriveMixin,
    DependencyMixin,
):
    """The main window. Built by app.py with all dependencies injected.

    Cohesive concern-groups are factored into mixins (the ``*Mixin`` bases)
    to keep this file focused on construction and wiring; their methods run
    with ``self`` being this window. See ``docs/architecture.md`` for the
    map of which mixin owns what.
    """

    # Tests can connect to this to know when a slot completed (used so
    # the user-side "after a rip finishes, helpers run" flow is testable).
    rip_post_processing_done = Signal()
    # Emitted (from the cover-art daemon thread; cross-thread emission is
    # queued by Qt, so the slot runs on the GUI thread) with the one-line
    # outcome of the post-rip cover-art fetch.
    cover_art_done = Signal(str)
    # Emitted (from the post-rip CTDB-verify daemon thread; queued to the GUI
    # thread) with the CtdbVerifyResult, so the verdict renders on the GUI
    # thread.
    ctdb_verify_done = Signal(object)
    # Emitted (from the post-rip FLAC-verify daemon thread; queued to the GUI
    # thread) with the FlacVerifyResult, so the integrity outcome renders on the
    # GUI thread.
    flac_verify_done = Signal(object)
    # Emitted (from the post-rip processing daemon thread; queued to the GUI
    # thread) with the RecompressResult, so the FLAC re-compress outcome renders
    # on the GUI thread.
    flac_recompress_done = Signal(object)
    # Emitted (from the post-rip processing daemon thread; queued to the GUI
    # thread) with the TranscodeResult, so the FLAC→MP3/WavPack/WAV transcode
    # outcome renders on the GUI thread.
    transcode_done = Signal(object)

    def __init__(
        self,
        config: Config,
        backend: WhipperBackend,
        mb_client: MusicBrainzClient,
        metaflac: MetaflacAdapter,
        dependency_manager: DependencyManager,
        save_config: Callable[[Config], None] | None = None,
        ctdb_client: CTDBClient | None = None,
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
        # CTDB lookup adapter (KDD-14 Phase 1). Injected so tests pass a fake;
        # defaults to the real HTTP client. Only reached when the user opts in
        # to "Verify with CTDB after a rip" (off by default — it's a network
        # call), so the default real client never touches the net in tests.
        self._ctdb_client: CTDBClient = ctdb_client or CtdbHttpImpl()
        # Read-offset lookup by drive model (the disc-free primary path that
        # replaces relying on whipper's flaky `offset find`). Cheap to build
        # — a curated in-code table overlaid with an optional user CSV.
        self._offset_db: OffsetDatabase = OffsetDatabase.load_default()
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
        # Update-check worker/thread (Help → Check for updates…); one at a
        # time, joined in closeEvent so a slow check can't outlive the window.
        self._update_worker: object | None = None
        self._update_thread: QThread | None = None
        # In-flight update INSTALL (download+verify+swap); cancelled+joined
        # in closeEvent so a half-downloaded update can't outlive the window.
        self._install_worker: object | None = None
        self._install_thread: QThread | None = None
        # Launch-time dependency probe, run off-thread so a cold-container
        # `whipper --version` can't freeze the just-shown window; joined in
        # closeEvent. (DependencyMixin.run_dependency_check_async)
        self._dep_check_worker: object | None = None
        self._dep_check_thread: QThread | None = None
        # The GUI-backed DependencyManager for the in-flight async check. Stashed
        # so the finished handler can be a plain bound method (which Qt queues to
        # the GUI thread) instead of a lambda (which Qt delivers DIRECTLY on the
        # worker thread — building resolver dialogs there is a cross-thread bug).
        self._dep_check_manager: object | None = None
        # Disc probe (disc_info enters the container + reads the disc — slow);
        # run off-thread per drive change so selecting a drive never freezes
        # the window. Joined in closeEvent.
        self._disc_info_worker: object | None = None
        self._disc_info_thread: QThread | None = None
        # Launch-time drive listing (whipper `drive list` enters the container);
        # run off-thread so it can't freeze the just-shown window. Joined in
        # closeEvent. (The Refresh button stays synchronous — user-initiated.)
        self._drive_list_worker: object | None = None
        self._drive_list_thread: QThread | None = None
        # Params of the in-flight rip, captured at start so the finish
        # handler knows whether it was an unknown-mode rip (and where the
        # FLACs landed) without depending on the controls' current state.
        self._active_rip_params: RipParameters | None = None
        # Set when the user hits Cancel, so the finish handler reports a
        # cancellation rather than a failure.
        self._rip_cancelled: bool = False
        # Guards the one-shot auto-heal (rip-as-unknown) per Start.
        self._auto_retry_done: bool = False
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
        # Post-rip cover-art fetch (backend-independent, 2026-06-13): the
        # URL fetcher is injectable so tests never reach the real Cover
        # Art Archive (same hard-learned rule as _begin_update_install — an
        # unstubbed network call can hang the suite). None = the adapter's
        # real urllib fetcher.
        self._cover_art_fetcher: cover_art.Fetcher | None = None
        # Single daemon thread that runs all post-rip work (unknown-mode
        # tagging THEN cover art, sequentially — both shell out to metaflac
        # on the same FLACs, so they must not race). Stored so tests can
        # join it deterministically; not joined in closeEvent (it's a daemon
        # and guards its own signal emit).
        self._post_rip_thread: threading.Thread | None = None
        # Whether the user asked to launch Picard after an unknown rip.
        self._pending_picard_launch: bool = False
        # Post-rip CTDB verify (KDD-14 Phase 1, opt-in). Runs the lookup +
        # local decode on a daemon thread (NOT a QThread) so the long decode
        # can't be destroyed-while-running on window close (§3.2); the verdict
        # comes back via the ctdb_verify_done signal. Stored so tests can join
        # it; not joined in closeEvent (daemon + guarded emit), like cover art.
        self._ctdb_thread: threading.Thread | None = None
        # Post-rip FLAC encode-verify (opt-in, default on). Same daemon-thread +
        # queued-signal pattern as CTDB; only runs for a backend that doesn't
        # already self-verify (cyanrip does not; whipper does via flac --verify).
        # Stored so tests can join it.
        self._flac_verify_thread: threading.Thread | None = None
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

        # Cover-art outcome lands in the rip log view (not the status line —
        # that's showing the fidelity verdict by then, which matters more).
        self.cover_art_done.connect(self._on_cover_art_done)
        # CTDB verdict (opt-in) lands under the AccurateRip table.
        self.ctdb_verify_done.connect(self._on_ctdb_verified)
        # FLAC encode-verify outcome (opt-in) lands in the rip log view.
        self.flac_verify_done.connect(self._on_flac_verified)
        # FLAC re-compress outcome (opt-in, off by default) lands in the rip log.
        self.flac_recompress_done.connect(self._on_flac_recompressed)
        # Transcode outcome (when a non-FLAC output format is selected) lands in
        # the rip log view.
        self.transcode_done.connect(self._on_transcoded)

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
        QTimer.singleShot(0, self._maybe_offer_first_run_setup)

    # --- Top-level lifecycle ------------------------------------------------

    def refresh_drives(self) -> None:
        """Populate the drive picker — `list_drives` runs OFF the GUI thread.

        Called at launch (app.py) and after host setup. `list_drives` shells
        to whipper (container entry, slow on a cold start), so it's probed on
        a worker and the result is applied to the picker on the GUI thread; the
        window stays responsive. (The picker's own Refresh button stays
        synchronous — that's user-initiated.)
        """
        from whipper_gui.workers import start_worker_thread
        from whipper_gui.workers.drive_list_worker import DriveListWorker

        if self._drive_list_thread is not None and self._drive_list_thread.isRunning():
            return  # one refresh at a time
        self._drive_list_worker = DriveListWorker(self._backend)
        self._drive_list_thread = QThread(self)
        # Connect our result slots first (so they run before the thread quits);
        # `failed` is a distinct outcome that must also stop the thread.
        self._drive_list_worker.finished.connect(self._on_drive_list_ready)
        self._drive_list_worker.failed.connect(self._on_drive_list_failed)
        start_worker_thread(
            self._drive_list_worker,
            self._drive_list_thread,
            self._drive_list_worker.run,
            also_quit_on=(self._drive_list_worker.failed,),
        )

    def _on_drive_list_ready(self, drives: object) -> None:
        """Drive list fetched — populate the picker on the GUI thread."""
        self._drive_list_worker = None
        self._drive_list_thread = None
        self._drive_picker.populate(drives)  # type: ignore[arg-type]

    def _on_drive_list_failed(self, message: str) -> None:
        self._drive_list_worker = None
        self._drive_list_thread = None
        self._drive_picker.show_error(message)

    def closeEvent(self, event: object) -> None:  # noqa: N802 — Qt API
        """Tear down the MB worker thread cleanly on window close."""
        # Disarm the auto-force-stop so it can't fire into a torn-down window.
        self._force_stop_timer.stop()
        if self._mb_thread.isRunning():
            self._mb_thread.quit()
            self._mb_thread.wait(2000)
        # Join a still-running update check (short HTTP call; bounded wait).
        if self._update_thread is not None and self._update_thread.isRunning():
            self._update_thread.quit()
            self._update_thread.wait(2000)
        # Cancel + join an in-flight update download (it polls the cancel
        # flag between 1 MiB chunks, so this returns quickly).
        if self._install_thread is not None and self._install_thread.isRunning():
            if self._install_worker is not None:
                self._install_worker.cancel()
            self._install_thread.quit()
            self._install_thread.wait(5000)
        # Join a still-running launch dependency probe (bounded subprocess
        # probes; short wait).
        if self._dep_check_thread is not None and self._dep_check_thread.isRunning():
            self._dep_check_thread.quit()
            self._dep_check_thread.wait(2000)
        # Join a still-running disc probe (disc_info can be mid-read; bounded).
        if self._disc_info_thread is not None and self._disc_info_thread.isRunning():
            self._disc_info_thread.quit()
            self._disc_info_thread.wait(3000)
        # Join a still-running drive-list probe.
        if self._drive_list_thread is not None and self._drive_list_thread.isRunning():
            self._drive_list_thread.quit()
            self._drive_list_thread.wait(2000)
        # The post-rip CTDB verify runs on a DAEMON thread (not a QThread), so
        # it's intentionally not joined here — it dies with the process and
        # guards its own emit. Joining it would risk blocking close on a long
        # decode; that's exactly why it isn't a QThread (§3.2).
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

        # Host bootstrap (installs the whipper container stack) — the no-terminal
        # replacement for setup-host.sh. Listed first: without it there's nothing
        # to rip with.
        host_setup_action = tools_menu.addAction("Set up Whipper &GUI…")
        host_setup_action.triggered.connect(self.open_host_setup_dialog)

        # Re-runnable menu/desktop integration (the first-run offer is one-shot;
        # this lets the user (re)create the shortcut any time).
        shortcut_action = tools_menu.addAction("Add &app shortcut")
        shortcut_action.triggered.connect(self._on_add_app_shortcut)

        drive_setup_action = tools_menu.addAction("Set up &drive…")
        drive_setup_action.triggered.connect(self._on_drive_setup)

        diagnose_action = tools_menu.addAction("Diagnose drive &access…")
        diagnose_action.triggered.connect(self._show_drive_access_diagnosis)
        # The dependency check lives only on the Settings dialog's
        # "Check dependencies" button (it also runs automatically at
        # launch) — no duplicate Tools-menu entry.

        # The in-app Uninstaller — separated at the bottom so it can't be
        # mis-clicked among the everyday actions.
        tools_menu.addSeparator()
        uninstall_action = tools_menu.addAction("&Uninstall Whipper GUI…")
        uninstall_action.triggered.connect(self.open_uninstall_dialog)

        help_menu = menubar.addMenu("&Help")
        guide_action = help_menu.addAction("&User Guide…")
        guide_action.triggered.connect(self._on_show_help)
        update_action = help_menu.addAction("Check for &updates…")
        update_action.triggered.connect(self._on_check_updates)
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
        """User picked a drive — read the disc off-thread, then look up MB.

        `disc_info()` enters the container and reads the disc (slow), so it
        runs on a DiscInfoWorker; `_on_disc_info_ready` / `_on_disc_info_failed`
        pick up on the GUI thread. The window stays responsive throughout.
        """
        log.info("drive changed: %s", device)
        self._disc_info_panel.set_drive(device)
        self._track_table.clear()
        self._current_release_id = ""
        self._current_num_tracks = 0
        self._rip_controls.set_release_id("")
        self._rip_controls.set_drive(device)

        self._disc_info_panel.set_disc_info_loading()
        self._start_disc_info(device)

    def _start_disc_info(self, device: str) -> None:
        """Probe the disc on a worker thread. Replaces any in-flight probe
        (a previous drive's result would be stale)."""
        from whipper_gui.workers import start_worker_thread
        from whipper_gui.workers.disc_info_worker import DiscInfoWorker

        # Stop a still-running probe for the previous drive before starting a
        # new one. quit() is delivered to that thread's own loop directly (not
        # via the queued finished→quit), so it works without an event-loop spin.
        if self._disc_info_thread is not None and self._disc_info_thread.isRunning():
            self._disc_info_thread.quit()
            self._disc_info_thread.wait(2000)

        self._disc_info_worker = DiscInfoWorker(self._backend, device)
        self._disc_info_thread = QThread(self)
        self._disc_info_worker.finished.connect(self._on_disc_info_ready)
        self._disc_info_worker.failed.connect(self._on_disc_info_failed)
        start_worker_thread(
            self._disc_info_worker,
            self._disc_info_thread,
            self._disc_info_worker.run,
            also_quit_on=(self._disc_info_worker.failed,),
        )

    def _on_disc_info_ready(self, device: str, info: DiscInfo) -> None:
        """Disc probe succeeded — render it and kick off the MB lookup."""
        if self._is_stale_disc_result(device):
            return
        self._disc_info_worker = None
        self._disc_info_thread = None
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

    def _on_disc_info_failed(self, device: str, message: str) -> None:
        """Disc probe failed — show a friendly, actionable error."""
        if self._is_stale_disc_result(device):
            return
        self._disc_info_worker = None
        self._disc_info_thread = None
        self._disc_info_panel.set_disc_info_error(_friendly_disc_scan_error(message))

    def _is_stale_disc_result(self, device: str) -> bool:
        """True if a disc-probe result is for a drive the user already left.

        The old probe's `finished`/`failed` can already be queued to the GUI
        thread when a new drive change starts; applying it would clobber the
        new drive's "reading…" state. Ignore it. (When no drive is selected —
        e.g. unit tests calling the handler directly — nothing is stale.)
        """
        current = self._drive_picker.current_device()
        return current is not None and current != device

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

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        dialog.check_dependencies_requested.connect(self._on_check_dependencies)
        # "Re-detect…" next to the read-offset field opens the same wizard.
        dialog.detect_offset_requested.connect(self._on_drive_setup)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            old_backend = self._config.ripper_backend
            self._config = dialog.to_config()
            # Push the new config into the rip controls so the next rip
            # reflects the edits (output dir, templates, Continue-on-CD-R).
            self._rip_controls.set_config(self._config)
            # Apply the debug-logging toggle immediately so the change takes
            # effect for this session (not just the next launch).
            from whipper_gui.logging_setup import set_debug_logging

            set_debug_logging(self._config.debug_logging)
            try:
                self._save_config(self._config)
            except OSError as exc:
                QMessageBox.warning(self, "Couldn't save settings", f"{exc}")
            self._maybe_offer_cyanrip_install(old_backend)
