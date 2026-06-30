"""Shared pytest fixtures for platterpus's test suite.

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
def _isolate_drive_profiles(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the drive-profile ledger out of the real user config dir.

    `DriveProfileStore` resolves its path live from `platterpus.paths`, so
    redirecting that constant to a per-test temp file means any window code that
    records a drive fact (the recorder calls `save()`) writes to the sandbox,
    never `~/.config/platterpus/drive_profiles.json`. Mirrors how the suite
    injects `save_config` to avoid touching the real config.toml.
    """
    monkeypatch.setattr(
        "platterpus.paths.DRIVE_PROFILES_PATH", tmp_path / "drive_profiles.json"
    )


@pytest.fixture(autouse=True)
def _join_leaked_qthreads(monkeypatch: pytest.MonkeyPatch):
    """Join any `QThread` a test started but didn't drive to completion.

    Destroying a running `QThread` aborts the whole process (Qt). A test that
    triggers a worker (a dialog's install loop, a window's rip/probe) but returns
    before the thread finishes leaves it running; when the test's widgets are
    GC'd, the child thread is destroyed mid-run → a hard `SIGABRT` that takes
    down the *whole suite*, not just that test. This bit the dependency-install
    work: a stub that returned before the worker finished crashed the run.

    We track every `QThread.start()` during the test, then at teardown — which
    runs BEFORE the test's locals (and their threads) are GC'd — quit + bounded-
    wait any that are still running, pumping the loop so a queued `finished` can
    fire first. Leaking isn't failed (it's a latent abort risk, not a behaviour
    bug, and some daemon-style flows are legitimately in flight) but it's warned
    so a chronically-leaking test gets noticed. The real fix in the test is to
    drive the worker to completion (see `docs/testing.md` — bounded
    `processEvents` pump); this is the backstop that keeps a slip from aborting
    everyone else's tests.
    """
    import warnings

    from PySide6.QtCore import QThread

    started: list[QThread] = []
    original_start = QThread.start

    def tracking_start(self: QThread, *args: object, **kwargs: object) -> None:
        started.append(self)
        return original_start(self, *args, **kwargs)

    monkeypatch.setattr(QThread, "start", tracking_start)
    yield

    app = QApplication.instance()
    leaked = 0
    for thread in started:
        try:
            if not thread.isRunning():
                continue
        except RuntimeError:
            continue  # underlying C++ QThread already deleted — nothing to do
        leaked += 1
        try:
            thread.quit()
            if app is not None:
                # Let a queued `finished → quit` be delivered before we wait.
                for _ in range(100):
                    app.processEvents()
            thread.wait(3000)
        except RuntimeError:
            pass
    if leaked:
        warnings.warn(
            f"{leaked} QThread(s) were still running at test teardown and were "
            "joined to avoid a destroyed-while-running abort. Drive workers to "
            "completion in the test (bounded processEvents pump) — see "
            "docs/testing.md.",
            stacklevel=2,
        )


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
