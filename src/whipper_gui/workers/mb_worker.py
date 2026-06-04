"""MusicBrainzWorker — drives MusicBrainz lookups off the GUI thread.

MusicBrainz HTTP requests can take several seconds (especially on a
cold cache) and MUST NOT block input. The main thread constructs a
MusicBrainzWorker, moves it to a QThread, and invokes its slots either
directly (queued connection) or via signal emission.

Signals:
  releases_returned(list)   — list[ReleaseSummary] from disc-id / TOC
  release_returned(object)  — single ReleaseDetail from MBID fetch
  error(str)                — query failure, short message

Slots:
  lookup_disc_id(disc_id)
  lookup_toc(toc)
  fetch_release(mbid)

One worker handles all three query types. Because a single worker on a
single thread processes slots serially, queries don't interleave —
which is what we want (each user action triggers exactly one query at
a time).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    MusicBrainzQueryError,
    TocSignature,
)

log = logging.getLogger(__name__)


class MusicBrainzWorker(QObject):
    """QObject worker for MusicBrainz queries via MusicBrainzClient."""

    releases_returned = Signal(list)  # list[ReleaseSummary]
    release_returned = Signal(object)  # ReleaseDetail (object so PySide
    # doesn't need an explicit type
    # registration for the dataclass)
    error = Signal(str)

    def __init__(
        self,
        client: MusicBrainzClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client: MusicBrainzClient = client

    @Slot(str)
    def lookup_disc_id(self, disc_id: str) -> None:
        """Lookup release candidates by MB disc ID. Empty list when no match."""
        log.debug("MB disc-id lookup: %s", disc_id)
        try:
            results = self._client.releases_by_disc_id(disc_id)
        except MusicBrainzQueryError as exc:
            log.warning("MB disc-id lookup failed: %s", exc)
            self.error.emit(str(exc))
            return
        self.releases_returned.emit(results)

    @Slot(object)
    def lookup_toc(self, toc: TocSignature) -> None:
        """Lookup release candidates by TOC fingerprint."""
        log.debug("MB TOC lookup: %s", toc.to_query())
        try:
            results = self._client.releases_by_toc(toc)
        except MusicBrainzQueryError as exc:
            log.warning("MB TOC lookup failed: %s", exc)
            self.error.emit(str(exc))
            return
        self.releases_returned.emit(results)

    @Slot(str)
    def fetch_release(self, mbid: str) -> None:
        """Fetch full release details for one MBID."""
        log.debug("MB release fetch: %s", mbid)
        try:
            detail = self._client.release_by_mbid(mbid)
        except MusicBrainzQueryError as exc:
            log.warning("MB release fetch failed: %s", exc)
            self.error.emit(str(exc))
            return
        self.release_returned.emit(detail)
