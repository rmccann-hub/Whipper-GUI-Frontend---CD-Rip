# SPDX-License-Identifier: GPL-3.0-only
"""CtdbVerifyWorker — verify a finished rip against CTDB off the GUI thread.

A CTDB verify (KDD-14 Phase 1) does two slow things that must never run on the
Qt GUI thread: an HTTP lookup against ``db.cuetools.net`` and a decode of every
ripped FLAC to PCM (a ``flac`` subprocess per file). This worker runs the whole
``ctdb.verify.verify_rip`` flow on a ``QThread`` and reports the verdict back
via a queued signal — the same minimal worker pattern as the other ``workers/``
(``DiscInfoWorker`` / ``DriveListWorker`` / ``MusicBrainzWorker``).

The verdict itself is always trustworthy-by-construction-or-labelled: until the
audio-CRC algorithm is confirmed bit-exact on real hardware
(``ctdb.crc.CRC_VALIDATED``), a ``MATCH`` is flagged experimental inside the
result (``CtdbVerifyResult.trustworthy``). The worker never *fabricates* a
verdict — every failure mode is already a verdict from ``verify_rip``.

Signals:
  finished(object) — a ``ctdb.verify.CtdbVerifyResult`` (always emitted once).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from whipper_gui.adapters.ctdb_client import CTDBClient
from whipper_gui.ctdb.toc import SamplesProbe
from whipper_gui.ctdb.verify import (
    CtdbVerifyResult,
    PcmDecoder,
    Verdict,
    verify_rip,
)

log = logging.getLogger(__name__)

# How long to let any in-flight post-rip work (metaflac tagging / cover-art
# embed, on a separate daemon thread) finish before we start decoding. Those
# steps rewrite the SAME FLAC files; decoding one mid-rewrite would read a torn
# file and report a spurious decode error. The wait is bounded so a wedged
# post-rip thread can't hang the verify forever.
_SETTLE_TIMEOUT_S: float = 60.0


class CtdbVerifyWorker(QObject):
    """QObject worker: verify ``rip_dir``'s FLACs against CTDB, emit the verdict.

    ``decoder``/``samples_probe`` are injected in tests (the production defaults
    shell out to host ``flac``/``metaflac`` via ``ctdb.verify``). ``wait_for``
    is the post-rip daemon thread, if one is running — see ``_SETTLE_TIMEOUT_S``.
    """

    finished = Signal(object)  # CtdbVerifyResult

    def __init__(
        self,
        client: CTDBClient,
        rip_dir: Path,
        *,
        decoder: PcmDecoder | None = None,
        samples_probe: SamplesProbe | None = None,
        wait_for: threading.Thread | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._rip_dir = rip_dir
        self._decoder = decoder
        self._samples_probe = samples_probe
        self._wait_for = wait_for

    @Slot()
    def run(self) -> None:
        # Let post-rip tagging / cover-art embedding settle first (see above).
        # Joining a daemon thread here is fine — we're already off the GUI
        # thread, and the wait is bounded.
        if self._wait_for is not None and self._wait_for.is_alive():
            self._wait_for.join(_SETTLE_TIMEOUT_S)

        # Track order = filename order ("NN - Title.flac"), matching how the
        # rest of the app enumerates a ripped album.
        flac_paths = sorted(self._rip_dir.rglob("*.flac"))
        if not flac_paths:
            self.finished.emit(
                CtdbVerifyResult(
                    Verdict.LOOKUP_ERROR, message="no FLAC files found to verify"
                )
            )
            return

        try:
            result = verify_rip(
                flac_paths,
                self._client,
                decoder=self._decoder,
                samples_probe=self._samples_probe,
            )
        except Exception as exc:  # noqa: BLE001 — a worker must always finish
            # verify_rip is built to never raise for expected failures, but a
            # belt-and-braces guard keeps the signal contract (always one emit)
            # even if something unforeseen slips through.
            log.exception("CTDB verify crashed")
            result = CtdbVerifyResult(
                Verdict.LOOKUP_ERROR, message=f"unexpected error: {exc}"
            )
        self.finished.emit(result)
