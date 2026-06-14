"""Shared pytest fixtures for whipper-gui's test suite.

Only one QApplication instance can exist per process. The `qapp`
session-scoped fixture guarantees that — tests that need a Qt event
loop, widgets, or the clipboard depend on it; tests that don't, ignore
it.

We force the Qt platform plugin to `offscreen` BEFORE importing any
Qt module, so the suite runs on CI / headless containers without a
real display.
"""

from __future__ import annotations

import os

# Set before any Qt import. Subsequent imports of QtGui/QtWidgets
# inherit this platform choice; widgets are created in-memory and
# never draw to a real display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Return the single QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _non_blocking_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give `QMessageBox`'s static helpers safe, non-blocking defaults.

    A modal `QMessageBox.question/.information/...` calls `.exec()`, which
    **blocks forever** under the headless `offscreen` platform (no user to
    click). That's a real hazard whenever a test pumps the event loop
    (`processEvents()`): a *stale* `QTimer.singleShot` left by an earlier
    test's window — e.g. the first-run `_maybe_offer_host_setup` offer — can
    fire and hang the whole suite (a hard abort).

    So we default them to a harmless answer for every test: `question` →
    `No` (decline), the notice boxes → `Ok`. Tests that assert specific
    dialog behaviour monkeypatch the relevant method themselves; that
    per-test patch is applied after this autouse one and wins.
    """
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox, method, lambda *a, **k: QMessageBox.StandardButton.Ok
        )
