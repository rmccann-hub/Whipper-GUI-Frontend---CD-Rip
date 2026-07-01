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
``_flac_verify_thread``/``_derived_verify_thread``;
the ``rip_post_processing_done``, ``cover_art_done``,
``ctdb_verify_done``, ``flac_verify_done``, ``flac_recompress_done``,
``transcode_done`` and ``derived_verify_done`` signals;
and the cross-mixin methods
``self._auto_apply_known_offset`` / ``self._on_drive_setup`` (DriveMixin).

Future contributors: the rip itself runs in ``workers/rip_worker.py`` via a
backend behind the ``RipBackend`` ABC — this file is GUI orchestration
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

from platterpus import drive_control
from platterpus.adapters import cover_art
from platterpus.adapters.derived_verify import DerivedVerifyResult
from platterpus.adapters.flac_recompress import (
    RecompressResult,
    recompress_flac_files,
)
from platterpus.adapters.flac_verify import FlacVerifyResult
from platterpus.adapters.rip_backend import RipMetadata, TrackTag
from platterpus.adapters.transcode import (
    EMBEDS_COVER_ART,
    TranscodeResult,
    transcode_files,
)
from platterpus.adapters.transcode import (
    SUPPORTED_FORMATS as TRANSCODE_FORMATS,
)
from platterpus.offset_config import is_offset_configured
from platterpus.parsers.cyanrip_log import looks_like_cyanrip_log, parse_cyanrip_log
from platterpus.parsers.rip_log import parse_rip_log
from platterpus.ui.main_window_helpers import fidelity_summary, safe_path_segment
from platterpus.ui.unknown_album import (
    UnknownAlbumDialog,
    apply_track_tags,
    launch_picard_for,
)
from platterpus.workers import start_worker_thread
from platterpus.workers.ctdb_worker import verify_rip_dir
from platterpus.workers.derived_verify_worker import (
    verify_rip_dir as verify_derived_dir,
)
from platterpus.workers.flac_verify_worker import verify_rip_dir as verify_flac_dir
from platterpus.workers.rip_worker import RipParameters, RipWorker

log = logging.getLogger(__name__)

# How long after Cancel to wait before auto-force-stopping the drive (the
# in-container reader can keep it spinning). The user can hit Force stop to
# escalate sooner.
_FORCE_STOP_COUNTDOWN_MS: int = 5000

# Bound on how long the checksum step waits for in-flight tagging/transcode to
# settle before hashing (mirrors the CTDB/FLAC-verify settle bound), so a wedged
# post-rip step can't hang the digest thread forever.
_CHECKSUM_SETTLE_TIMEOUT_S: float = 120.0


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
        # Stamp the rip's start for the elapsed-time record. Set here (the
        # user-perceived Start), NOT in _start_rip_worker, so an auto-heal retry
        # is included in the total — the user waited for the whole thing. cyanrip
        # logs neither its start time nor its run time, so this is the only place
        # the actual wall-clock can be measured (real-disc lesson: 2h45m actual
        # vs cyanrip's "~35m" ETA — see rip_timing.py).
        import time as _time
        from datetime import datetime as _datetime

        self._rip_started_monotonic = _time.monotonic()
        self._rip_started_at = (
            _datetime.now().astimezone().isoformat(timespec="seconds")
        )
        # Epoch start (wall time, comparable to LogRecord.created) bounds this
        # rip's slice of the session log so other albums' reports can exclude it.
        self._rip_epoch_start = _time.time()
        # Drop the previous rip's parsed-log/report state, so a CTDB verify that
        # finishes late can never re-write THIS rip's report against the old one.
        self._last_rip_log = None
        self._last_rip_log_file = None
        self._last_rip_timing = None
        self._current_rip_window = None
        # Async post-rip verification outcomes, accumulated as each finishes.
        # The report is re-written after each, passing all of them, so the final
        # .platterpus.json holds every check regardless of completion order — and
        # a late-finishing verify from THIS rip never carries into the next
        # (they're reset here at the start of each finish).
        self._last_ctdb_result = None
        self._last_flac_verify_result = None
        self._last_transcode_result = None
        self._last_checksums = None
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
        self._set_rip_lock(True)  # grey out everything that would conflict mid-rip
        # Keep the window repainting during the rip (Plasma 6 Wayland black-window
        # belt — see MainWindow.__init__ / app.py XWayland preference).
        self._repaint_timer.start()
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

        # Measure the actual wall-clock elapsed and record it against cyanrip's
        # own estimate. This is the ONLY place the real run time exists — cyanrip
        # logs the disc's audio length and a finish timestamp but never how long
        # the rip took. Captured here (worker still alive) before it's cleared.
        self._last_rip_timing = self._build_rip_timing()
        # Capture the read-speed ladder's per-pass history now, while the worker
        # is still alive (it's cleared below), so the report can record which
        # speed / -Z the disc needed — or that it never read clean at the floor.
        self._last_speed_attempts = getattr(self._rip_worker, "speed_attempts", [])

        self._rip_controls.set_rip_active(False)
        self._set_rip_lock(False)  # rip over — re-enable the locked-down UI
        self._repaint_timer.stop()  # rip over — stop the Wayland repaint belt
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
                # Write the machine-readable JSON rip report beside the log
                # (the "two outputs every time" rule, docs/ux-design-principles
                # #2). Kept for the CTDB handler to re-write with the CTDB
                # verdict once that async check finishes.
                self._last_rip_log = rip_log
                self._last_rip_log_file = log_file
                # Now that the log is parsed, enrich the timing with the realtime
                # multiplier (elapsed ÷ the disc's audio length) — a meaningful
                # metric that replaces cyanrip's bogus ETA. Best-effort.
                self._enrich_timing_with_disc_duration(rip_log)
                self._write_rip_report(rip_log, log_file)
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
            # Cover art (2026-06-13): the ripper itself never fetches art —
            # cyanrip is fed tags and bypasses its own MusicBrainz lookup — so
            # the GUI fetches the front cover from the Cover Art Archive using
            # the release the user picked, and embeds/saves it per the cover-art
            # setting. A disc that was never identified has no release ID, so
            # plan_actions() makes this a no-op.
            embed, save_file = cover_art.plan_actions(
                mode=self._config.cover_art,
                ripper_fetches_art=False,
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
            # cyanrip can't take a literal ':' in its tag args, so we fed it the
            # ∶ lookalike; restore the real ':' in the written tags afterward
            # (KDD-22 colon handling). Only on the cyanrip path, and only when
            # the metadata actually contains a colon — so a colon-free album
            # (the common case) doesn't spin up the post-rip thread for nothing.
            restore_colons = self._metadata_has_colon()
            if (
                tag
                or embed
                or save_file
                or recompress
                or transcode_fmt
                or restore_colons
            ):
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
                    restore_colons=restore_colons,
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

            # Derived-file verify: when a non-FLAC output was produced, prove the
            # derived MP3/WavPack/WAV are good too — bit-identical to the FLAC
            # master for the lossless formats, decode-clean + complete for lossy
            # MP3 (honest per Critical Rule #4). Runs off-thread AFTER the
            # transcode (post_rip_thread) so it never reads a file mid-write.
            if transcode_fmt:
                rip_dir = Path(log_path).parent if log_path else params.output_dir
                self._start_derived_verify(
                    rip_dir, transcode_fmt, wait_for=post_rip_thread
                )

            # Per-file SHA256 digests for the report's integrity section. Always
            # on a successful rip (every format), after the post-rip thread so it
            # hashes the final masters + any derived files. Off-thread; folded
            # into the one debug report via checksums_done.
            rip_dir = Path(log_path).parent if log_path else params.output_dir
            self._start_checksums(rip_dir, wait_for=post_rip_thread)

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

    def _metadata_has_colon(self) -> bool:
        """True if the album or any track's name contains a ``:``.

        Drives the cyanrip colon-restore (KDD-22): only worth a post-rip metaflac
        pass when a colon was actually substituted. Reads the current track table
        (the names the user saw/edited), so it's accurate for known discs.
        """
        album = self._track_table.album_metadata()
        if ":" in (album.title or "") or ":" in (album.artist or ""):
            return True
        return any(
            ":" in (track.title or "") or ":" in (track.artist_credit or "")
            for track in self._track_table.tracks()
        )

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
        restore_colons: bool = False,
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
            # 0) Restore the real ':' in cyanrip's tags (it was fed the ∶
            #    lookalike because its parser can't take a literal colon). Runs
            #    FIRST so cover-art and the transcode see the corrected tags.
            #    Never raises; a no-op for colon-free albums.
            if restore_colons:
                from platterpus.adapters.cyanrip_backend import (
                    restore_substituted_colons,
                )

                fixed = restore_substituted_colons(
                    self._metaflac, sorted(rip_dir.rglob("*.flac"))
                )
                if fixed:
                    log.info("colon-restore: fixed tags in %d file(s)", fixed)
            # 1) Tagging next. run_unknown_post_processing is the synchronous
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
        # Record + schedule a (debounced) re-write so the report picks up the
        # CTDB verdict alongside whatever else has finished.
        self._last_ctdb_result = result
        self._schedule_rip_report_write()

    def _build_rip_timing(self) -> dict | None:
        """Build the timing dict for the just-finished rip and log it.

        Returns None when no start was stamped (e.g. a finish with no matching
        request, as some tests drive). The realtime multiplier (elapsed ÷ disc
        length) is added later, once the log is parsed for the disc duration
        (see the enrichment in ``_on_rip_finished``); cyanrip's own ETA is no
        longer recorded — it was wildly wrong (it logged "822h" on a real disc).
        """
        import time as _time
        from datetime import datetime as _datetime

        from platterpus import rip_report
        from platterpus.rip_timing import format_duration

        if self._rip_started_monotonic is None:
            return None
        elapsed = _time.monotonic() - self._rip_started_monotonic
        finished_at = _datetime.now().astimezone().isoformat(timespec="seconds")
        timing = rip_report.build_timing(
            elapsed,
            started_at=self._rip_started_at,
            finished_at=finished_at,
        )
        log.info("rip elapsed (actual): %s", format_duration(elapsed))
        # Record this rip's epoch window for the debug-log filtering. It's kept
        # in `_rip_windows` (so a LATER album's report excludes these lines) AND
        # remembered as the current window (so THIS report never excludes its
        # own lines — see _write_rip_report). The end is "now"; post-rip steps
        # (CTDB/FLAC verify) that log a little later are this rip's own lines and
        # stay included in this report anyway.
        if self._rip_epoch_start is not None:
            window = (self._rip_epoch_start, _time.time())
            self._rip_windows.append(window)
            self._current_rip_window = window
            self._rip_epoch_start = None
        # The start clock is one-shot per rip — clear it so a stray later finish
        # can't reuse it.
        self._rip_started_monotonic = None
        return timing

    def _enrich_timing_with_disc_duration(self, rip_log: object) -> None:
        """Add ``disc_seconds`` + ``realtime_multiplier`` to the stored timing.

        Called once the log is parsed (the disc's audio length lives in cyanrip's
        ``Total time:`` line → ``rip_log.disc_duration``). Best-effort: a missing
        or unparseable duration just leaves the multiplier off. The report is
        (re)written after this, so the enriched timing lands in the JSON.
        """
        from platterpus.rip_timing import parse_hms_to_seconds

        timing = self._last_rip_timing
        if not isinstance(timing, dict):
            return
        elapsed = timing.get("elapsed_seconds")
        disc_seconds = parse_hms_to_seconds(getattr(rip_log, "disc_duration", ""))
        if isinstance(elapsed, int | float) and disc_seconds and disc_seconds > 0:
            timing["disc_seconds"] = round(disc_seconds)
            timing["realtime_multiplier"] = round(elapsed / disc_seconds, 2)

    def _build_rip_debug_log(self) -> dict | None:
        """Capture this session's log for the report, minus other albums' rips.

        Returns a ``{"scope", "truncated", "lines"}`` dict (see
        ``rip_report.build_debug_log``) or None if no buffer is installed. The
        excluded windows are every OTHER rip this session — the current rip's own
        window is kept, so its lines (including the post-rip verify steps that
        land after this is first called) are never filtered out of its own
        report. Recomputed on each write so the CTDB re-write picks up the lines
        logged since the first write.
        """
        from platterpus.log_buffer import get_session_buffer
        from platterpus.rip_report import build_debug_log

        buffer = get_session_buffer()
        if buffer is None:
            return None
        others = [w for w in self._rip_windows if w is not self._current_rip_window]
        return build_debug_log(
            buffer.lines_excluding(others), truncated=buffer.truncated
        )

    def _write_rip_report(self, rip_log: object, log_file: Path) -> None:
        """Write the JSON rip report beside ``log_file`` (best-effort).

        Pulls every accumulated post-rip result from ``self`` (CTDB, FLAC-verify,
        transcode, checksums) so the file always reflects whatever has finished
        so far. The first write (from ``_on_rip_finished``) calls this directly
        so the report exists the instant the rip ends; the later async verifies
        route through ``_schedule_rip_report_write`` so their re-writes coalesce
        onto the debounce timer instead of serializing the whole JSON per check.
        Since every write passes *all* results, a coalesced write is never lossy
        — the final file holds everything regardless of completion order. A small
        JSON write — safe on the GUI thread (computing the checksums, which is
        NOT, happens off-thread and is passed in via ``self._last_checksums``).
        Never raises (write_report swallows OSError).
        """
        from datetime import datetime

        from platterpus import read_speed_ladder, rip_report

        debug_log = self._build_rip_debug_log()
        rip_report.write_report(
            rip_log,
            log_file,
            ctdb_result=getattr(self, "_last_ctdb_result", None),
            flac_verify_result=getattr(self, "_last_flac_verify_result", None),
            transcode_result=getattr(self, "_last_transcode_result", None),
            derived_verify_result=getattr(self, "_last_derived_verify_result", None),
            read_speed=read_speed_ladder.attempts_to_report(
                getattr(self, "_last_speed_attempts", []) or []
            ),
            checksums=getattr(self, "_last_checksums", None),
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            timing=self._last_rip_timing,
            debug_log=debug_log,
        )
        # Also drop the human-readable, session-scoped debug log beside the rip
        # (X.platterpus.log) so it lives WITH the album, not only in the global
        # log.txt — same "other albums excluded" scoping as the JSON's copy.
        rip_report.write_debug_log(log_file, debug_log)

    def _schedule_rip_report_write(self) -> None:
        """Coalesce a rip-report re-write onto the debounce timer.

        The post-rip async checks (CTDB / FLAC-verify / checksums / transcode)
        each finish independently and each wants the report refreshed with its
        result. Instead of every handler serializing the whole JSON itself (up
        to ~5×/rip), they call this: a single-shot timer (re)armed here writes
        once when the burst settles. Because every write pulls *all* accumulated
        results from ``self`` (see ``_write_rip_report``), a coalesced write is
        never lossy — the file still ends up holding every finished check. A
        no-op until a rip log exists; flushed on window close so nothing pending
        is dropped.
        """
        if self._last_rip_log is None or self._last_rip_log_file is None:
            return
        self._rip_report_timer.start()  # (re)arm; single-shot, so it coalesces

    def _flush_rip_report(self) -> None:
        """Write any pending debounced rip report immediately (timer slot + close).

        Stops the debounce timer and serializes now, so a queued write is never
        left unwritten when the window closes mid-verify. Safe to call when
        nothing is pending (no rip log yet, or the timer already fired)."""
        self._rip_report_timer.stop()
        if self._last_rip_log is not None and self._last_rip_log_file is not None:
            self._write_rip_report(self._last_rip_log, self._last_rip_log_file)

    # --- Per-file SHA256 digests (embedded in the report) -------------------

    def _start_checksums(
        self, rip_dir: Path, wait_for: threading.Thread | None
    ) -> None:
        """Compute a SHA256 for every audio file, on a daemon thread.

        Runs after ``wait_for`` (the post-rip metaflac/transcode thread) so it
        hashes the FINAL files — the tagged/re-compressed FLAC masters *and* any
        derived MP3/WavPack/WAV. Hashing does real disk I/O across a whole album,
        so it must never touch the GUI thread (§3.2); the result is delivered via
        ``checksums_done`` (queued to the GUI thread), which folds it into the
        one debug report. Daemon + guarded emit, like the CTDB/FLAC-verify steps.
        """
        from platterpus import checksums

        def work() -> None:
            if wait_for is not None:
                wait_for.join(timeout=_CHECKSUM_SETTLE_TIMEOUT_S)
            digests = checksums.compute_digests(rip_dir)
            try:
                self.checksums_done.emit(digests)
            except RuntimeError:  # window already destroyed — nothing to update
                pass

        log.info("computing SHA256 digests for %s", rip_dir)
        thread = threading.Thread(target=work, daemon=True)
        self._checksums_thread = thread
        thread.start()

    def _on_checksums_done(self, digests: object) -> None:
        """Digests computed — record + re-write the report (on the GUI thread)."""
        if not isinstance(digests, dict):
            return
        self._last_checksums = digests
        log.info("SHA256 digests: %d file(s) hashed", len(digests))
        self._schedule_rip_report_write()

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
        # Record + schedule a re-write so the FLAC-integrity outcome lands in the
        # one debug file alongside the other checks (debounced/coalesced).
        self._last_flac_verify_result = result
        self._schedule_rip_report_write()
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
        # Record + schedule a (debounced) re-write so the transcode outcome is
        # in the report too.
        self._last_transcode_result = result
        self._schedule_rip_report_write()
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

    # --- Post-transcode derived-file verify (MP3/WavPack/WAV) ----------------

    def _start_derived_verify(
        self, rip_dir: Path, fmt: str, wait_for: threading.Thread | None
    ) -> None:
        """Verify the derived ``fmt`` files on a daemon thread (same rationale as
        CTDB/FLAC-verify: a full-album decode can outlast any ``closeEvent`` wait,
        and destroying a running ``QThread`` aborts the app — §3.2). Joins the
        post-rip transcode thread first (``wait_for``) so it never reads a derived
        file mid-write. Result reported via ``derived_verify_done`` (queued to the
        GUI thread)."""

        def work() -> None:
            result = verify_derived_dir(rip_dir, fmt, wait_for=wait_for)
            try:
                self.derived_verify_done.emit(result)
            except RuntimeError:  # window already destroyed — nothing to update
                pass

        log.info("starting derived-file verify (%s) for %s", fmt, rip_dir)
        self._rip_progress.append_log_line(f"Verifying derived {fmt.upper()} files…")
        thread = threading.Thread(target=work, daemon=True)
        self._derived_verify_thread = thread
        thread.start()

    def _on_derived_verified(self, result: object) -> None:
        """Derived-file verify finished — record + surface the outcome.

        Runs on the GUI thread (``derived_verify_done`` is queued there). The
        FLAC master is always the archival copy, so a derived-file problem is
        never catastrophic — but a LOSSLESS mismatch (a WavPack/WAV that isn't
        bit-identical to the master) is a real defect, so it's surfaced loudly;
        a lossy-MP3 pass is stated honestly as "decode-clean", never as
        bit-perfect. A "couldn't run" is a neutral skip.
        """
        if not isinstance(result, DerivedVerifyResult):
            return
        self._last_derived_verify_result = result
        self._schedule_rip_report_write()
        fmt = (result.fmt or "").upper()
        if result.error:
            message = f"{fmt} verify: skipped — {result.error} (FLAC master kept)"
        elif result.mismatches:
            names = ", ".join(p.name for p in result.mismatches)
            message = (
                f"⚠ {fmt} verify FAILED — {len(result.mismatches)} file(s) are NOT "
                f"bit-identical to the FLAC master: {names}"
            )
        elif result.failures:
            names = ", ".join(p.name for p in result.failures)
            message = (
                f"⚠ {fmt} verify: {len(result.failures)} file(s) could not be "
                f"decoded/verified: {names}"
            )
        elif not result.complete:
            message = (
                f"{fmt} verify: only {result.checked}/{result.expected} file(s) "
                "were derived (transcode incomplete; FLAC master kept)"
            )
        elif result.lossless:
            message = (
                f"{fmt} verify: all {result.checked} file(s) are bit-identical to "
                "the FLAC master."
            )
        else:
            message = (
                f"{fmt} verify: all {result.checked} file(s) decode cleanly "
                "(lossy — decodability + completeness, not bit-identity)."
            )
        if result.mismatches or result.failures:
            log.warning("%s", message)
            self._rip_progress.set_status(message)
        else:
            log.info("%s", message)
        self._rip_progress.append_log_line(message)
