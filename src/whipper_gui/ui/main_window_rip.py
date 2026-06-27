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
``_current_release_id``/``_current_release_detail``/``_ctdb_client``/``_ctdb_thread``/
``_flac_verify_thread``;
the ``rip_post_processing_done``, ``cover_art_done``,
``ctdb_verify_done``, ``flac_verify_done``, ``flac_recompress_done`` and
``transcode_done`` signals;
and the cross-mixin methods
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
from whipper_gui.adapters.flac_recompress import (
    RecompressResult,
    recompress_flac_files,
)
from whipper_gui.adapters.flac_verify import FlacVerifyResult
from whipper_gui.adapters.transcode import (
    EMBEDS_COVER_ART,
    TranscodeResult,
    transcode_files,
)
from whipper_gui.adapters.transcode import (
    SUPPORTED_FORMATS as TRANSCODE_FORMATS,
)
from whipper_gui.adapters.whipper_backend import RipMetadata, TrackTag
from whipper_gui.offset_config import is_offset_configured
from whipper_gui.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from whipper_gui.parsers.rip_log import parse_rip_log
from whipper_gui.ui.main_window_helpers import fidelity_summary, safe_path_segment
from whipper_gui.ui.unknown_album import (
    UnknownAlbumDialog,
    apply_track_tags,
    launch_picard_for,
)
from whipper_gui.workers import start_worker_thread
from whipper_gui.workers.ctdb_worker import verify_rip_dir
from whipper_gui.workers.flac_verify_worker import verify_rip_dir as verify_flac_dir
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
        # Genre / disc number / per-track ISRC are MusicBrainz-only silent
        # passthroughs (not editable in the table), so they come from the stored
        # release — and only when it matches THIS rip (guards a stale detail from
        # a previous disc, and unknown-album rips where release_id is "").
        detail = self._current_release_detail
        if detail is not None and detail.summary.mbid == params.release_id:
            genre = detail.summary.genre
            disc_number = detail.summary.disc_number
            total_discs = detail.summary.total_discs
            isrc_by_number = {t.number: t.isrc for t in detail.tracks}
        else:
            genre, disc_number, total_discs, isrc_by_number = "", 1, 1, {}
        params = replace(
            params,
            metadata=RipMetadata(
                album_artist=album.artist,
                album_title=album.title,
                year=album.year,
                genre=genre,
                disc_number=disc_number,
                total_discs=total_discs,
                tracks=tuple(
                    TrackTag(
                        number=t.number,
                        title=t.title,
                        artist=t.artist_credit,
                        isrc=isrc_by_number.get(t.number, ""),
                    )
                    for t in self._track_table.tracks()
                ),
            ),
        )
        self._rip_controls.set_rip_active(True)
        # Remember the params so the finish handler knows the mode + output dir.
        self._active_rip_params = params

        self._rip_worker = RipWorker(self._backend, params)
        self._rip_thread = QThread(self)

        self._rip_worker.log_line.connect(self._rip_progress.append_log_line)
        self._rip_worker.progress.connect(self._rip_progress.set_progress)
        self._rip_worker.status.connect(self._rip_progress.set_status)
        # Follow the rip in the track table — highlight the row whipper is on.
        self._rip_worker.current_track.connect(self._track_table.highlight_track)
        self._rip_worker.error.connect(self._on_rip_error)
        self._rip_worker.finished.connect(self._on_rip_finished)

        # Standard one-shot teardown + start (finished → quit → deleteLater,
        # rip begins on start_rip when the thread spins up).
        start_worker_thread(
            self._rip_worker, self._rip_thread, self._rip_worker.start_rip
        )

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
        """User pressed Force stop — escalate immediately.

        Force-stop is enabled during a rip AND during a disc scan. With a rip
        in flight it's the rip escalation (kill + eject). With only a scan in
        flight (no rip), it's a stuck TOC read holding the drive — free it
        WITHOUT ejecting, so the disc stays in for a Rescan.
        """
        self._force_stop_timer.stop()
        rip_in_flight = self._rip_thread is not None
        scan_in_flight = (
            self._disc_info_thread is not None and self._disc_info_thread.isRunning()
        )
        if scan_in_flight and not rip_in_flight:
            self._scan_force_stopped = True
            self._free_drive_for_scan("manual")
        else:
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

    def _free_drive_for_scan(self, trigger: str) -> None:
        """Free a drive wedged by a stuck disc scan: kill the reader, no eject.

        Runs on a daemon thread because the kill + `distrobox enter` fallback
        can each block for their timeout — we never touch widgets from the
        thread. Unlike `_do_force_stop` it does NOT eject: the disc stays in so
        the user can Rescan. Used by the Force-stop button during a scan and
        automatically on a scan timeout (the in-container reader can keep
        holding the drive after the host-side subprocess gives up). See
        drive_control.free_drive for the user-approved Rule #3 exception.
        """
        device = self._drive_picker.current_device() or ""
        log.info(
            "freeing drive after scan (%s trigger), device=%s",
            trigger,
            device or "(default)",
        )
        thread = threading.Thread(
            target=drive_control.free_drive,
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
            # Output format: both backends rip to FLAC, so a non-FLAC choice
            # means a post-rip transcode (FLAC kept as the master). "flac" (or
            # any value we don't transcode) leaves transcode_fmt empty = no-op.
            transcode_fmt = (
                self._config.output_format
                if self._config.output_format in TRANSCODE_FORMATS
                else ""
            )
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
            # WavPack/WAV can't carry an embedded cover (the transcode drops it —
            # FLAC/MP3 keep theirs), so for those formats make sure the front
            # cover still lands in the album folder as cover.<ext> — the only way
            # they get a visible cover. Force the folder save whenever art is
            # wanted (cover_art mode set) and the disc was identified; this also
            # makes the whipper-known path (which normally leaves art to whipper)
            # fetch a folder copy, since whipper only put it *inside* the FLAC.
            if (
                transcode_fmt
                and transcode_fmt not in EMBEDS_COVER_ART
                and self._config.cover_art
                and (self._current_release_id or "").strip()
            ):
                save_file = True
            # Opt-in (off by default) FLAC re-compress — only for a backend that
            # doesn't already max compression. whipper encodes at flac's default
            # (`-5`), so re-encoding at `-8` can still shrink it; cyanrip already
            # maxes, so it's skipped there. Folded into the post-rip thread (it
            # mutates the same FLACs as tag/cover, so it MUST run after them, not
            # concurrently) — see _start_post_rip_processing.
            recompress = (
                self._config.recompress_flac_after_rip
                and not self._backend.produces_max_compression_flac()
            )
            if tag or embed or save_file or recompress or transcode_fmt:
                rip_dir = Path(log_path).parent if log_path else params.output_dir
                self._start_post_rip_processing(
                    rip_dir,
                    tag=tag,
                    launch_picard=self._pending_picard_launch,
                    release_id=self._current_release_id,
                    embed=embed,
                    save_file=save_file,
                    recompress=recompress,
                    transcode_fmt=transcode_fmt,
                    mp3_vbr_quality=self._config.mp3_vbr_quality,
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

            # Opt-in (default on) FLAC encode-verify — only for a backend that
            # doesn't already self-verify. whipper passes `flac --verify` during
            # the rip, so it's skipped there; cyanrip (FFmpeg) doesn't, so this
            # gives its rips the same decode==PCM guarantee. Off-thread, after
            # any metaflac rewrites settle (wait_for), like CTDB.
            if (
                self._config.verify_flac_after_rip
                and not self._backend.self_verifies_encode()
            ):
                rip_dir = Path(log_path).parent if log_path else params.output_dir
                self._start_flac_verify(rip_dir, wait_for=post_rip_thread)

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
        recompress: bool = False,
        transcode_fmt: str = "",
        mp3_vbr_quality: int = 0,
    ) -> None:
        """Run unknown-mode tagging, then cover art, then FLAC re-compress, then
        an optional transcode, on ONE daemon thread.

        Why one thread, in this order: the first two steps shell out to
        ``metaflac`` on the SAME FLAC files, and the re-compress step *rewrites*
        those same files — so all three MUST run sequentially: tag first, then
        embed/save the front cover, then re-compress. Two processes mutating one
        FLAC at the same time race each other and corrupt or lose the tags,
        artwork, or audio. Re-compress runs after the metaflac work so it
        operates on the final, fully-tagged-and-arted files (``flac`` preserves
        their tags and embedded art when it re-encodes). The transcode runs
        **last** of all, so it reads the final FLACs (tagged, arted, and
        possibly re-compressed) and derives the chosen output format from them;
        it writes *sibling* files and never touches the FLAC, so it can't race
        the earlier steps. Running them on one worker (rather than several) is
        what guarantees the ordering.

        Why off the GUI thread at all: each step is a subprocess per file
        (~1-2s), so a multi-track album would freeze the event loop for tens of
        seconds right when the rip finishes — exactly the "Not Responding"
        class of bug CLAUDE.md forbids (docs/architecture.md §3.2). The
        cover-art fetch is also a network call, which never belongs on the GUI
        thread either.

        Best-effort end to end: tagging, ``apply_cover_art`` and
        ``recompress_flac_files`` each guard their own failures so a stray bug
        here can't take down the app. The cover-art and re-compress outcomes are
        reported back through ``cover_art_done`` / ``flac_recompress_done``
        (queued cross-thread signals, so the slots run on the GUI thread); each
        emit is guarded because the window may have been closed while the work
        ran.

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
            # 3) Re-compress LAST, so it rewrites the final tagged-and-arted
            #    FLACs (flac preserves their tags + embedded art). Best-effort;
            #    each file is swapped in atomically, so a failure or crash leaves
            #    the original untouched. Outcome reported via flac_recompress_done.
            if recompress:
                try:
                    result = recompress_flac_files(sorted(rip_dir.rglob("*.flac")))
                except Exception:  # noqa: BLE001 — must never crash the GUI
                    log.exception("FLAC re-compress failed unexpectedly")
                    result = RecompressResult(error="failed unexpectedly")
                try:
                    self.flac_recompress_done.emit(result)
                except RuntimeError:  # window destroyed — nothing to update
                    pass
            # 4) Transcode LAST, reading the final FLACs (tagged, arted, and
            #    possibly re-compressed) to derive the chosen non-FLAC output.
            #    Writes sibling files and keeps the FLAC as the master; never
            #    raises. Outcome reported via transcode_done.
            if transcode_fmt:
                try:
                    tresult = transcode_files(
                        sorted(rip_dir.rglob("*.flac")),
                        fmt=transcode_fmt,
                        mp3_vbr_quality=mp3_vbr_quality,
                    )
                except Exception:  # noqa: BLE001 — must never crash the GUI
                    log.exception("transcode failed unexpectedly")
                    tresult = TranscodeResult(error="failed unexpectedly")
                try:
                    self.transcode_done.emit(tresult)
                except RuntimeError:  # window destroyed — nothing to update
                    pass

        log.info(
            "post-rip processing in %s "
            "(tag=%s, cover-art embed=%s save=%s, recompress=%s, transcode=%s)",
            rip_dir,
            tag,
            embed,
            save_file,
            recompress,
            transcode_fmt or "no",
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
        """Verify the just-finished rip against CTDB on a daemon thread.

        The lookup (network) and the local FLAC decode (a `flac` subprocess per
        track) must not run on the GUI thread. We use a daemon thread + a
        queued signal — NOT a QThread — for the same reason cover art does: the
        decode can run far longer than any reasonable closeEvent wait, and
        destroying a running QThread aborts the app (§3.2). The daemon thread
        dies with the process and guards its own emit, so closing the window
        mid-verify is always safe. ``wait_for`` is the post-rip metaflac thread
        (or None): we join it first so we never decode a FLAC mid-rewrite. The
        verdict is reported via ``ctdb_verify_done`` (queued to the GUI thread).
        """

        def work() -> None:
            result = verify_rip_dir(self._ctdb_client, rip_dir, wait_for=wait_for)
            try:
                self.ctdb_verify_done.emit(result)
            except RuntimeError:  # window already destroyed — nothing to update
                pass

        log.info("starting CTDB verify for %s", rip_dir)
        self._rip_progress.set_ctdb_status("Verifying against CTDB…")
        thread = threading.Thread(target=work, daemon=True)
        self._ctdb_thread = thread
        thread.start()

    def _on_ctdb_verified(self, result: object) -> None:
        """CTDB verify finished — render the verdict under the AR table.

        Runs on the GUI thread (ctdb_verify_done is queued there). `result` is
        a ctdb.verify.CtdbVerifyResult; rip_progress labels an unvalidated
        match "experimental" (KDD-16).
        """
        self._rip_progress.set_ctdb_result(result)  # type: ignore[arg-type]
        verdict = getattr(getattr(result, "verdict", None), "value", "?")
        log.info("CTDB verify verdict: %s", verdict)

    # --- Post-rip FLAC encode-verify (opt-in, default on) -------------------

    def _start_flac_verify(
        self, rip_dir: Path, wait_for: threading.Thread | None
    ) -> None:
        """Verify the just-finished rip's FLACs decode cleanly, on a daemon
        thread (same rationale as CTDB: a per-file decode can outlast any
        ``closeEvent`` wait, and destroying a running ``QThread`` aborts the app
        — §3.2). Joins the post-rip metaflac thread first (``wait_for``) so it
        never tests a file mid-rewrite. Result reported via ``flac_verify_done``
        (queued to the GUI thread)."""

        def work() -> None:
            result = verify_flac_dir(rip_dir, wait_for=wait_for)
            try:
                self.flac_verify_done.emit(result)
            except RuntimeError:  # window already destroyed — nothing to update
                pass

        log.info("starting FLAC verify for %s", rip_dir)
        self._rip_progress.append_log_line("Verifying FLAC integrity…")
        thread = threading.Thread(target=work, daemon=True)
        self._flac_verify_thread = thread
        thread.start()

    def _on_flac_verified(self, result: object) -> None:
        """FLAC verify finished — record the outcome (runs on the GUI thread).

        Loud on failure (a corrupt archival file is a real problem): the message
        also replaces the status line. A clean pass or a "couldn't run" skip is
        noted only in the log view.
        """
        if not isinstance(result, FlacVerifyResult):
            return
        if result.error:
            message = f"FLAC verify: skipped — {result.error}"
        elif result.failures:
            names = ", ".join(p.name for p in result.failures)
            message = (
                f"⚠ FLAC verify FAILED for {len(result.failures)} file(s): {names}"
            )
        else:
            message = f"FLAC verify: all {result.checked} file(s) decode cleanly."
        if result.failures:
            log.warning("%s", message)
            self._rip_progress.set_status(message)
        else:
            log.info("%s", message)
        self._rip_progress.append_log_line(message)

    # --- Post-rip FLAC re-compress (opt-in, off by default) -----------------

    def _on_flac_recompressed(self, result: object) -> None:
        """FLAC re-compress finished — record the outcome (runs on the GUI
        thread).

        Re-compress is lossless and ``--verify``'d, and any failed file is left
        untouched, so a partial failure is informational rather than alarming: a
        per-file failure is noted in the log (the original FLAC is still a valid
        rip), while a "couldn't run at all" (e.g. ``flac`` missing) is a skip.
        A clean pass just notes how many files shrank.
        """
        if not isinstance(result, RecompressResult):
            return
        if result.error:
            message = f"FLAC re-compress: skipped — {result.error}"
        elif result.failures:
            names = ", ".join(p.name for p in result.failures)
            message = (
                f"FLAC re-compress: {result.reencoded} file(s) re-compressed; "
                f"{len(result.failures)} left as-is (re-encode failed): {names}"
            )
        else:
            message = f"FLAC re-compress: {result.reencoded} file(s) re-compressed."
        if result.failures:
            log.warning("%s", message)
        else:
            log.info("%s", message)
        self._rip_progress.append_log_line(message)

    # --- Post-rip transcode (when a non-FLAC output format is selected) -------

    def _on_transcoded(self, result: object) -> None:
        """Transcode finished — record the outcome (runs on the GUI thread).

        The FLAC master is always kept, so a transcode failure never costs the
        user their lossless rip — it's informational, not alarming. A per-file
        failure is noted (the FLAC is still there to retry from); a "couldn't run
        at all" (e.g. ``ffmpeg`` missing) is a skip; a clean pass notes how many
        files were written.
        """
        if not isinstance(result, TranscodeResult):
            return
        if result.error:
            message = f"Transcode: skipped — {result.error} (FLAC master kept)"
        elif result.failures:
            names = ", ".join(p.name for p in result.failures)
            message = (
                f"Transcode: {result.transcoded} file(s) written; "
                f"{len(result.failures)} failed (FLAC master kept): {names}"
            )
        else:
            message = f"Transcode: {result.transcoded} file(s) written."
        if result.failures or result.error:
            log.warning("%s", message)
        else:
            log.info("%s", message)
        self._rip_progress.append_log_line(message)
