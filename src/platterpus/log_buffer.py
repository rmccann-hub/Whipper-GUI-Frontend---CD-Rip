"""In-memory capture of this session's log lines, for the rip report.

The `.platterpus.json` rip report is a single self-contained debug record for
one album's rip (maintainer decision, 2026-06-30). Alongside the verdict, CRCs
and timing it embeds the session's log lines — **everything since this launch**
(host setup, dependency probes, the MusicBrainz lookup, the read offset, *this*
rip) — **minus the lines that belong to a different album's rip**. So each
album's report carries the full environmental picture without the noise of other
albums ripped in the same session.

The on-disk rolling log (`log.txt`) is unchanged and still records everything,
including every rip — it's the catch-all for problems with no rip to attach to
(startup, a dependency install, a crash before any rip ever runs).

This handler is installed once by ``logging_setup.configure_logging`` and reached
by the report builder through the module-level singleton — so no call site has
to thread a buffer reference around.
"""

from __future__ import annotations

import logging

# Cap so a marathon session can't grow the buffer without bound. log.txt on disk
# is the complete record; this in-memory copy only needs to cover a normal
# session. Oldest lines drop first once the cap is hit (and `truncated` flips so
# the report can say so honestly).
_MAX_RECORDS: int = 50_000


class SessionLogBuffer(logging.Handler):
    """A logging handler that keeps formatted records in memory for the session.

    Each entry is ``(created_epoch, formatted_line)``. Capped at ``_MAX_RECORDS``
    with oldest-first eviction; ``truncated`` flips True once anything is dropped.
    """

    def __init__(self) -> None:
        super().__init__()
        self._records: list[tuple[float, str]] = []
        self.truncated: bool = False

    def emit(self, record: logging.LogRecord) -> None:
        # A handler must never crash the app at logging time; on a formatting
        # error, defer to handleError (which respects logging.raiseExceptions).
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 — logging must not raise into callers
            self.handleError(record)
            return
        self._records.append((record.created, line))
        if len(self._records) > _MAX_RECORDS:
            # Drop the oldest 10% in one shot rather than popping on every line.
            drop = len(self._records) - _MAX_RECORDS + _MAX_RECORDS // 10
            del self._records[:drop]
            self.truncated = True

    def lines_excluding(self, windows: list[tuple[float, float]]) -> list[str]:
        """Formatted lines whose timestamp falls in NONE of ``windows``.

        ``windows`` are ``(start_epoch, end_epoch)`` spans of *other* rips this
        session; their lines are dropped so an album's report doesn't carry
        another album's rip chatter. Everything else — pre-rip setup, inter-rip
        general activity, and this rip's own lines — is kept, in order.
        """
        if not windows:
            return [line for _created, line in self._records]
        return [
            line
            for created, line in self._records
            if not any(start <= created <= end for start, end in windows)
        ]


# Module-level singleton: logging_setup installs exactly one, and the report
# builder reaches it here without it being threaded through every call site.
_BUFFER: SessionLogBuffer | None = None


def get_session_buffer() -> SessionLogBuffer | None:
    """The installed session buffer, or None if logging isn't configured yet."""
    return _BUFFER


def set_session_buffer(buffer: SessionLogBuffer | None) -> None:
    """Record (or clear) the installed buffer. Called by ``logging_setup``."""
    global _BUFFER
    _BUFFER = buffer
