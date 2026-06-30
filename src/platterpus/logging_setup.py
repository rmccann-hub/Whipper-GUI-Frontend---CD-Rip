"""Logging configuration for the GUI.

Call `configure_logging()` once at startup (from `app.main`). After that,
every module that does `logging.getLogger(__name__).info(...)` writes to
two destinations:

  1. A rotating file at `LOG_PATH` (DEBUG and up).
  2. The console (INFO and up, configurable).

Modules MUST NOT add their own handlers or call `logging.basicConfig` —
configuration is centralized here per CLAUDE.md's "Log with the `logging`
module, not `print`" rule. New code that wants extra detail in the file
just logs at DEBUG and it shows up there but not on the console.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from platterpus.log_buffer import SessionLogBuffer, set_session_buffer
from platterpus.paths import LOG_DIR, LOG_PATH

# Rotation policy. Five backups of 1 MiB each keeps a useful history
# (~5 MiB total) without growing unbounded on long-running sessions.
_LOG_MAX_BYTES: int = 1_048_576
_LOG_BACKUP_COUNT: int = 5

# Format chosen to be greppable by tail/less without being noisy in the
# console pane. Module name (%(name)s) makes it easy to track which
# subsystem emitted a line.
_LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Sentinel attribute set on the root logger after configure_logging()
# runs once, so repeated imports during tests or re-entries don't pile
# up duplicate handlers.
_CONFIGURED_ATTR: str = "_platterpus_configured"
# Tag the file handler so `set_debug_logging()` can find it again after
# configure_logging() returns (handlers are otherwise anonymous).
_FILE_HANDLER_ATTR: str = "_platterpus_file_handler"
# Same idea for the in-memory session buffer (embedded in the rip report).
_BUFFER_HANDLER_ATTR: str = "_platterpus_buffer_handler"


def configure_logging(console_level: int = logging.INFO, debug: bool = False) -> None:
    """Initialize the root logger with a rotating file and a console handler.

    Idempotent: a second call only re-applies the requested verbosity. Safe to
    call before any other module logs (it's the very first thing `app.main`
    does).

    `console_level` controls how chatty the terminal is. The file handler is at
    INFO by default; `debug=True` (the Settings "Debug logging" toggle,
    `Config.debug_logging`) bumps it to DEBUG so a bug report captures every
    probe/subprocess/parse step. Toggle later at runtime with
    `set_debug_logging()`.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if getattr(root, _CONFIGURED_ATTR, False):
        # Already configured (e.g. a second QApplication in tests) — still
        # honour the requested verbosity.
        set_debug_logging(debug)
        return

    # Root captures everything; per-handler levels do the filtering.
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    # In-memory session buffer: same format and level as the file handler, so
    # the rip report's embedded log mirrors what log.txt records (and respects
    # the Debug-logging toggle). It only lives in memory, so it doesn't add a
    # second file on disk.
    buffer_handler = SessionLogBuffer()
    buffer_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    buffer_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.addHandler(buffer_handler)

    # Remember the file + buffer handlers so the runtime toggle can re-level
    # both, and expose the buffer to the report builder.
    setattr(root, _FILE_HANDLER_ATTR, file_handler)
    setattr(root, _BUFFER_HANDLER_ATTR, buffer_handler)
    set_session_buffer(buffer_handler)
    # Mark configured so subsequent calls bail out early.
    setattr(root, _CONFIGURED_ATTR, True)


def set_debug_logging(enabled: bool) -> None:
    """Raise/lower the FILE log's verbosity at runtime (the Settings toggle).

    DEBUG when enabled, INFO otherwise; the console level is left alone. A
    no-op if logging hasn't been configured yet (configure_logging applies the
    initial level itself).
    """
    root = logging.getLogger()
    file_handler = getattr(root, _FILE_HANDLER_ATTR, None)
    if file_handler is None:
        return
    file_handler.setLevel(logging.DEBUG if enabled else logging.INFO)
    # Keep the in-memory buffer at the same verbosity, so the rip report's
    # embedded log matches what log.txt is capturing.
    buffer_handler = getattr(root, _BUFFER_HANDLER_ATTR, None)
    if buffer_handler is not None:
        buffer_handler.setLevel(logging.DEBUG if enabled else logging.INFO)
    logging.getLogger(__name__).info(
        "debug logging %s", "ENABLED" if enabled else "disabled"
    )
