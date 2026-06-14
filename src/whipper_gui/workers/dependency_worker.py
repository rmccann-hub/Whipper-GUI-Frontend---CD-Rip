"""DependencyCheckWorker — runs the launch-time dependency probe off-thread.

`DependencyManager.check_all()` shells out to each dependency's probe — and
the whipper probe runs `~/.local/bin/whipper --version`, which *enters the
Distrobox container*. On a cold container that can take several seconds, so
running it on the GUI thread at launch would freeze the just-shown window
("never block the GUI thread"). This worker runs the pure *probe* phase off
the GUI thread; the result (a `DependencyReport`) is applied back on the GUI
thread, where the resolver dialogs must live.

Same minimal worker pattern as UpdateCheckWorker.

Signals:
  finished(object) — a `DependencyReport`, or None if the probe crashed
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger(__name__)


class DependencyCheckWorker(QObject):
    """QObject worker: probe every dependency (no installs), emit the report.

    Takes a fully-built `DependencyManager`; only calls its `check_all()`
    (pure probing — touches no widgets), so it's safe off the GUI thread. The
    manager's resolvers are used later, on the GUI thread, by the caller.
    """

    finished = Signal(object)  # DependencyReport | None

    def __init__(self, manager: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager

    @Slot()
    def run(self) -> None:
        try:
            report = self._manager.check_all()
        except Exception:  # noqa: BLE001 — a worker must always finish
            log.exception("dependency check crashed")
            report = None
        self.finished.emit(report)
