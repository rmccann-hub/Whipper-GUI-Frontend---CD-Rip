"""Rip lifecycle for the main window.

Extracted from ``main_window`` (2026-06-13 modularization) as a mixin —
the single largest concern: starting a rip, the cancel → force-stop
escalation, eject, the finish handler (fidelity verdict, auto-heal,
auto-eject), the unknown-album flow, post-rip tagging, and backend-
independent cover art. ``MainWindow`` inherits this, so its methods stay
reachable as ``window._on_rip_finished`` etc. (which the test suite and Qt
signal connections depend on).

Contract this mixin expects from the host window (all set in
``MainWindow.__init__``): the widgets ``self._track_table``,
``self._rip_progress``, ``self._rip_controls``, ``self._drive_picker``,
``self._disc_info_panel``; the adapters ``self._backend``,
``self._metaflac``; ``self._config``; the rip-state attributes
``self._rip_worker``/``_rip_thread``/``_active_rip_params``/
``_rip_cancelled``/``_auto_retry_done``/``_force_stop_done``/
``_force_stop_timer``/``_force_stop_thread``/``_eject_thread``/
``_post_rip_thread``/``_cover_art_fetcher``/``_pending_picard_launch``/
``_current_release_id``/``_ctdb_client``/``_ctdb_worker``/``_ctdb_thread``;
the ``rip_post_processing_done`` and
``cover_art_done`` signals; and the cross-mixin methods
``self._auto_apply_known_offset`` / ``self._on_drive_setup`` (DriveMixin).

Future contributors: the rip itself runs in ``workers/rip_worker.py`` via a
backend behind the ``WhipperBackend`` ABC — this file is GUI orchestration
only. To support a new backend's log, extend the sniff/parse block in
``_on_rip_finished`` and ``fidelity_summary`` (see ``docs/architecture.md``).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from whipper_gui import drive_control
from whipper_gui.adapters import cover_art
from whipper_gui.adapters.whipper_backend import RipMetadata
from whipper_gui.offset_config import is_offset_configured
from whipper_gui.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from whipper_gui.parsers.rip_log import parse_rip_log
from whipper_gui.ui.main_window_helpers import fidelity_summary, safe_path_segment
from whipper_gui.ui.unknown_album import (
    UnknownAlbumDialog,
    apply_track_tags,
    launch_picard_for,
)
from whipper_gui.workers.ctdb_worker import CtdbVerifyWorker
from whipper_gui.workers.rip_worker import RipParameters, RipWorker

log = logging.getLogger(__name__)

# How long after Cancel to wait before auto-force-stopping the drive (the
# in-container reader can keep it spinning). The user can hit Force stop to
# escalate sooner.
_FORCE_STOP_COUNTDOWN_MS: int = 5000


class RipMixin:
    """Start/cancel/finish a rip, plus eject, unknown-album, and cover art."""

    # --- Slots: rip flow ----------------------------------------------------

    def _on_rip_requested(self, params: RipParameters) -> None:
        """User clicked Start. Validate, then start the worker thread."""
        # A read offset is mandatory: whipper refuses to rip without one (and
        # fails with a cryptic error), and an accurate offset is what makes the
        # rip bit-perfect. If neither whipper.conf nor our --offset override has
        # one, stop here and point the user at the drive-setup wizard rather
        # than letting the rip start and fail. The wizard pre-fills the offset
        # when the drive model is known; otherwise it's found from a CD that's
        # in the AccurateRip database.
        if (
            not is_offset_configured(self._config.override_read_offset)
            and not self._auto_apply_known_offset()
        ):
            # No offset configured AND we don't know this drive's offset →
            # the only case that still needs the wizard. (A known drive is
            # auto-applied above, so the user is never blocked for it.)
            answer = QMessageBox.warning(
                self,
                "Set up your drive first",
                "No read offset is configured for your drive, so ripping can't "
                "start — an accurate read offset is what makes the rip "
                "bit-perfect.\n\n"
                "Open Tools → Set up drive… and either accept the offset it "
                "fills in, or insert a CD that's in the AccurateRip database and "
                "click Detect, then Save.\n\n"
                "Open the drive-setup wizard now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._on_drive_setup()
            return

        # The offset is configured now — but `params` was built by the rip
        # controls BEFORE any auto-apply above, so it may still carry
        # read_offset_override=None. Inject it here so whipper actually gets
        # `--offset` (otherwise it aborts with "drive offset unconfigured").
        if self._config.override_read_offset and params.read_offset_override is None:
            params = replace(params, read_offset_override=self._config.read_offset)

        # Only validate the track table for non-unknown rips — placeholder
        # tags will be applied after the fact in unknown mode.
        if not params.unknown:
            ok, message = self._track_table.validate()
            if not ok:
                QMessageBox.warning(self, "Cannot start rip", message)
                return
        else:
            # Unknown disc: build the output templates from the album fields
            # (the literals, not whipper's %A/%d disc-ID hash).
            params = self._as_unknown_params(params)

        self._rip_progress.clear()
        self._rip_progress.set_status("Starting rip…")
        # Cleared here, set in _on_rip_cancel — so the finish handler can
        # say "cancelled" instead of "failed".
        self._rip_cancelled = False
        # Allow exactly one auto-heal retry (rip-as-unknown) per Start, so a
        # persistent failure can't loop.
        self._auto_retry_done = False
        # Disarm any pending auto-force-stop from a previous cancel, so its
        # countdown can't fire into this fresh rip.
        self._force_stop_timer.stop()
        self._force_stop_done = False

        self._start_rip_worker(params)

    def _as_unknown_params(self, params: RipParameters) -> RipParameters:
        """Return `params` rewritten for an unknown-album rip: `--unknown`,
        no release-id (so whipper needs no network), and output templates
        built from the album fields the user sees (blanks → Unknown)."""
        album = self._track_table.album_metadata()
        artist = safe_path_segment(album.artist) or "Unknown Artist"
        title = safe_path_segment(album.title) or "Unknown Album"
        return replace(
            params,
            unknown=True,
            release_id="",
            track_template=f"{artist}/{title}/%t - Track %t",
            disc_template=f"{artist}/{title}/{title}",
        )

    def _start_rip_worker(self, params: RipParameters) -> None:
        """Spin up the rip worker thread for `params`. Shared by the initial
        Start and the auto-heal retry, so both wire signals identically."""
        # Snapshot the track table (MB lookup result + user edits) into the
        # params. whipper ignores it (it tags from --release-id itself);
        # cyanrip is fed these tags directly so it never needs its own
        # MusicBrainz lookup (Critical Rule #5, KDD-18 metadata model).
        album = self._track_table.album_metadata()
        params = replace(
            params,
            metadata=RipMetadata(
                album_artist=album.artist,
                album_title=album.title,
                year=album.year,
                tracks=tuple(
                    (t.number, t.title, t.artist_credit)
                    for t in self._track_table.tracks()
                ),
            ),
        )
        self._rip_controls.set_rip_active(True)
        # Remember the params so the finish handler knows the mode + output dir.
        self._active_rip_params = params

        self._rip_worker = RipWorker(self._backend, params)
        self._rip_thread = QThread(self)
        self._rip_worker.moveToThread(self._rip_thread)

        self._rip_worker.log_line.connect(self._rip_progress.append_log_line)
        self._rip_worker.progress.connect(self._rip_progress.set_progress)
        self._rip_worker.status.connect(self._rip_progress.set_status)
        # Follow the rip in the track table — highlight the row whipper is on.
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
        log.info(
            "force-stopping drive (%s trigger), device=%s",
            trigger,
            device or "(default)",
        )
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

        # Autonomous heal: whipper aborts when it can't fetch online metadata
        # (e.g. the container has no network). The GUI already has the metadata
        # (its own host-side MusicBrainz lookup), so re-rip as unknown-album —
        # which needs no network — and tag locally afterward. Once per Start.
        needs_retry = bool(self._rip_worker and self._rip_worker.needs_unknown_retry)
        params = self._active_rip_params
        if (
            not success
            and not self._rip_cancelled
            and needs_retry
            and params is not None
            and not params.unknown
            and not self._auto_retry_done
        ):
            self._auto_retry_done = True
            log.info("rip lacked online metadata — auto-retrying as unknown-album")
            self._rip_progress.set_status(
                "The ripper couldn't reach MusicBrainz — re-ripping without "
                "online metadata and tagging from what's on screen…"
            )
            unknown_params = self._as_unknown_params(params)
            # Defer so the just-finished thread fully unwinds before we start
            # a new worker/thread.
            QTimer.singleShot(0, lambda: self._start_rip_worker(unknown_params))
            return

        self._rip_controls.set_rip_active(False)
        # Default status; replaced with a fidelity summary below if the
        # rip succeeded and we can parse its log. Distinguish a user
        # cancellation from a genuine failure (both report success=False).
        if success:
            status = "Done."
        elif self._rip_cancelled:
            status = "Rip cancelled by user. Partial files may remain."
        else:
            # Prefer an actionable hint (e.g. an unreadable track) over the
            # bare "Rip failed", so the user knows what to do next.
            hint = self._rip_worker.failure_hint if self._rip_worker else ""
            status = hint or "Rip failed."
        self._rip_progress.set_status(status)

        if log_path:
            log_file = Path(log_path)
            self._rip_progress.set_log_path(log_file)
            # Parse and render AR results if the file exists.
            try:
                text = log_file.read_text(encoding="utf-8")
                # Sniff the format instead of trusting the configured
                # backend: a folder can hold logs from either ripper, and
                # the auto-heal path can change mid-session.
                if looks_like_cyanrip_log(text):
                    rip_log = parse_cyanrip_log(text)
                else:
                    rip_log = parse_rip_log(text)
                self._rip_progress.set_rip_log(rip_log)
                # Replace the disc panel's blank AccurateRip field with the
                # real outcome (e.g. "not in database" for a CD-R) instead of
                # the old misleading static "verified during rip".
                self._disc_info_panel.set_accuraterip_result(rip_log)
                if success:
                    self._rip_progress.set_status(fidelity_summary(rip_log))
            except OSError as exc:
                log.warning("could not read rip log %s: %s", log_file, exc)

        # Post-rip processing: unknown-mode tagging + backend-independent
        # cover art. Both shell out to metaflac on the SAME FLAC files, so
        # they run SEQUENTIALLY on ONE daemon thread (tag first, then embed
        # art) — never concurrently (two metaflac processes mutating one file
        # race → corrupted/lost tags or artwork). The whole block is off the
        # GUI thread because each step is a subprocess-per-file (~1-2s each):
        # on a 16-track album it would otherwise freeze the window for 15-30s
        # right when the rip finishes (CLAUDE.md "never block the GUI thread";
        # docs/architecture.md §3.2). Only on a successful rip.
        if success and params is not None:
            # Tagging — only when the rip we started was unknown-mode
            # (identified discs are tagged by whipper itself). Scope it to the
            # album folder whipper just wrote: the .log lands next to the
            # FLACs, so its parent is that folder. Using the configured output
            # root instead would re-tag every previously ripped album in the
            # library with THIS disc's metadata.
            tag = params.unknown
            # Cover art (2026-06-13): when the ripper itself didn't fetch art
            # — cyanrip never does (the GUI feeds it tags and bypasses its
            # MusicBrainz lookup), and whipper can't in --unknown mode — fetch
            # the front cover from the Cover Art Archive using the release the
            # user picked, and embed/save it per the cover-art setting. A disc
            # that was never identified has no release ID, so plan_actions()
            # makes this a no-op.
            ripper_fetches_art = (
                self._config.ripper_backend != "cyanrip" and not params.unknown
            )
            embed, save_file = cover_art.plan_actions(
                mode=self._config.cover_art,
                ripper_fetches_art=ripper_fetches_art,
                release_id=self._current_release_id,
            )
            if tag or embed or save_file:
                rip_dir = Path(log_path).parent if log_path else params.output_dir
                self._start_post_rip_processing(
                    rip_dir,
                    tag=tag,
                    launch_picard=self._pending_picard_launch,
                    release_id=self._current_release_id,
                    embed=embed,
                    save_file=save_file,
                )
                post_rip_thread = self._post_rip_thread
            else:
                post_rip_thread = None

            # Opt-in CTDB verify (KDD-14 Phase 1): a second, TOC-keyed
            # verification path alongside AccurateRip. Runs off the GUI thread
            # (network lookup + local FLAC decode), AFTER any post-rip metaflac
            # work settles (passed as wait_for) so it never decodes a file
            # mid-rewrite. Works for known and unknown discs (CTDB is keyed by
            # TOC, not MBID).
            if self._config.ctdb_verify_after_rip:
                rip_dir = Path(log_path).parent if log_path else params.output_dir
                self._start_ctdb_verify(rip_dir, wait_for=post_rip_thread)

        # Auto-eject on a clean finish if the user opted in. Only on success —
        # a failed/cancelled rip leaves the disc in so the user can retry, and
        # ejecting mid-failure could fight the force-stop path.
        if success and self._config.auto_eject_after_rip:
            device = (
                params.drive
                if params is not None
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

    # --- Post-rip processing: tagging + cover art (one off-GUI thread) -------

    def _start_post_rip_processing(
        self,
        rip_dir: Path,
        *,
        tag: bool,
        launch_picard: bool,
        release_id: str,
        embed: bool,
        save_file: bool,
    ) -> None:
        """Run unknown-mode tagging, then cover art, on ONE daemon thread.

        Why one thread, in this order: both steps shell out to ``metaflac`` on
        the SAME FLAC files, so they MUST run sequentially — tag first, then
        embed/save the front cover — never concurrently. Two ``metaflac``
        processes mutating one file race each other and corrupt or lose the
        tags or the artwork. Running them on one worker (rather than two) is
        what guarantees the ordering.

        Why off the GUI thread at all: each step is a subprocess per file
        (~1-2s), so a multi-track album would freeze the event loop for tens of
        seconds right when the rip finishes — exactly the "Not Responding"
        class of bug CLAUDE.md forbids (docs/architecture.md §3.2). The
        cover-art fetch is also a network call, which never belongs on the GUI
        thread either.

        Best-effort end to end: tagging and ``apply_cover_art`` each guard
        their own failures so a stray bug here can't take down the app. The
        cover-art outcome is reported back through ``cover_art_done`` (a queued
        cross-thread signal, so the slot runs on the GUI thread); the emit is
        guarded because the window may have been closed while the work ran.

        Not joined in ``closeEvent``: it's a daemon thread that guards its own
        emit (the same pattern the cover-art fetch always used). Tests join the
        handle on ``self._post_rip_thread`` for determinism.
        """

        def work() -> None:
            # 1) Tagging first. run_unknown_post_processing is the synchronous
            #    worker body (tests call it directly); we just invoke it here,
            #    off the GUI thread, instead of inline in _on_rip_finished.
            if tag:
                try:
                    self.run_unknown_post_processing(rip_dir, launch_picard)
                except Exception:  # noqa: BLE001 — tagging must never crash the GUI
                    log.exception("unknown-album post-processing failed")
            # 2) Cover art second, only after tagging has fully finished so the
            #    two never touch a FLAC at the same time.
            if embed or save_file:
                try:
                    message = cover_art.apply_cover_art(
                        rip_dir,
                        release_id,
                        embed=embed,
                        save_file=save_file,
                        metaflac=self._metaflac,
                        fetcher=self._cover_art_fetcher,
                    )
                except Exception:  # noqa: BLE001 — art must never crash the GUI
                    log.exception("cover art post-processing failed")
                    message = "Cover art: failed unexpectedly (rip unaffected)."
                try:
                    self.cover_art_done.emit(message)
                except RuntimeError:  # window destroyed — nothing to update
                    pass

        log.info(
            "post-rip processing in %s (tag=%s, cover-art embed=%s save=%s)",
            rip_dir,
            tag,
            embed,
            save_file,
        )
        thread = threading.Thread(target=work, daemon=True)
        self._post_rip_thread = thread
        thread.start()

    def _on_cover_art_done(self, message: str) -> None:
        """Cover-art thread finished — record the outcome in the log view."""
        log.info("%s", message)
        self._rip_progress.append_log_line(message)

    # --- Post-rip CTDB verify (opt-in, KDD-14 Phase 1) ----------------------

    def _start_ctdb_verify(
        self, rip_dir: Path, wait_for: threading.Thread | None
    ) -> None:
        """Verify the just-finished rip against CTDB on a QThread.

        The lookup (network) and the local FLAC decode (a `flac` subprocess per
        track) must not run on the GUI thread — same worker-on-a-QThread
        pattern as the disc-info / drive-list probes. ``wait_for`` is the
        post-rip metaflac thread (or None): the worker joins it before decoding
        so it never reads a FLAC while it's being re-tagged. The verdict lands
        on the GUI thread via the queued ``finished`` signal.
        """
        log.info("starting CTDB verify for %s", rip_dir)
        self._rip_progress.set_ctdb_status("Verifying against CTDB…")
        worker = CtdbVerifyWorker(self._ctdb_client, rip_dir, wait_for=wait_for)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_ctdb_verified)
        # Standard deterministic cleanup (worker.finished → thread.quit →
        # thread.deleteLater); the worker reference is dropped in the handler.
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)
        self._ctdb_worker = worker
        self._ctdb_thread = thread
        thread.start()

    def _on_ctdb_verified(self, result: object) -> None:
        """CTDB verify finished — render the verdict under the AR table."""
        self._ctdb_worker = None
        self._ctdb_thread = None
        # `result` is a ctdb.verify.CtdbVerifyResult; rip_progress renders it
        # (and labels an unvalidated match "experimental", KDD-16).
        self._rip_progress.set_ctdb_result(result)  # type: ignore[arg-type]
        verdict = getattr(getattr(result, "verdict", None), "value", "?")
        log.info("CTDB verify verdict: %s", verdict)
