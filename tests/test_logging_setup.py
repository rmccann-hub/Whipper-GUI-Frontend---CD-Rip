"""Tests for whipper_gui.logging_setup.

configure_logging() mutates the global root logger and writes under a real
path, so each test snapshots and restores the root logger and points the log
path at a tmp dir.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from whipper_gui import logging_setup


@pytest.fixture
def clean_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[logging.Logger]:
    """Give each test a fresh, isolated root logger + a tmp log path."""
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "LOG_DIR", log_dir)
    monkeypatch.setattr(logging_setup, "LOG_PATH", log_dir / "log.txt")

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_attr = getattr(root, logging_setup._CONFIGURED_ATTR, None)

    root.handlers = []
    root.setLevel(logging.WARNING)
    if hasattr(root, logging_setup._CONFIGURED_ATTR):
        delattr(root, logging_setup._CONFIGURED_ATTR)
    try:
        yield root
    finally:
        # Close the handlers this test opened, then restore the original state.
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        if saved_attr is not None:
            setattr(root, logging_setup._CONFIGURED_ATTR, saved_attr)
        elif hasattr(root, logging_setup._CONFIGURED_ATTR):
            delattr(root, logging_setup._CONFIGURED_ATTR)


def _handler_names(root: logging.Logger) -> set[str]:
    return {type(h).__name__ for h in root.handlers}


def test_configure_logging_adds_file_and_console_handlers(
    clean_root: logging.Logger,
) -> None:
    logging_setup.configure_logging(console_level=logging.WARNING)

    # The log directory is created up front.
    assert logging_setup.LOG_DIR.exists()
    names = _handler_names(clean_root)
    assert "RotatingFileHandler" in names
    assert "StreamHandler" in names  # exact-name match: the console handler
    # Root captures everything; per-handler levels filter.
    assert clean_root.level == logging.DEBUG


def test_console_level_is_honoured(clean_root: logging.Logger) -> None:
    logging_setup.configure_logging(console_level=logging.ERROR)
    console = next(
        h for h in clean_root.handlers if type(h).__name__ == "StreamHandler"
    )
    file_handler = next(
        h for h in clean_root.handlers if type(h).__name__ == "RotatingFileHandler"
    )
    assert console.level == logging.ERROR
    assert file_handler.level == logging.DEBUG  # file is always full detail


def test_configure_logging_is_idempotent(clean_root: logging.Logger) -> None:
    # (pytest's own logging plugin may also attach handlers to root, so we
    # assert the count doesn't *increase* on a second call rather than a
    # fixed absolute count.)
    logging_setup.configure_logging()
    count = len(clean_root.handlers)
    # Our two handlers are present after the first call.
    assert "RotatingFileHandler" in _handler_names(clean_root)
    assert "StreamHandler" in _handler_names(clean_root)
    # A second call must not pile on duplicate handlers.
    logging_setup.configure_logging()
    assert len(clean_root.handlers) == count
