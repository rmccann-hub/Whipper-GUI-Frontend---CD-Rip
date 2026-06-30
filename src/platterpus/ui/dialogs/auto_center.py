"""An application-wide event filter that centres dialogs on the main window.

:class:`~platterpus.ui.dialogs.centering.CenteredDialog` only helps dialogs that
*subclass* it. The most common first-run prompts — the "add to menu" offer, the
shortcut prompt, update prompts — are plain ``QMessageBox`` static calls, which
can't subclass anything and so still popped up on whatever screen the compositor
chose (real-user report on a multi-monitor desktop, 0.4.4). Installing one
filter on the ``QApplication`` catches *every* dialog's first show — including
``QMessageBox`` and ``QFileDialog`` — and centres it over the window the user is
looking at.

Like all our centring, this is best-effort: under native Wayland clients can't
position themselves (the app prefers XWayland, where ``move()`` works), so there
it's a harmless no-op. ``CenteredDialog`` instances are skipped — they already
centre themselves, so we don't fight them.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QDialog

from platterpus.ui.dialogs.centering import CenteredDialog, center_on_anchor


class DialogCenterFilter(QObject):
    """Centres each top-level dialog over the active window on its first show."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Track which dialogs we've already placed (by id) so we only move a
        # dialog on its FIRST show — re-showing it shouldn't yank it back.
        self._seen: set[int] = set()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt API
        # Cheapest check first: only Show events are interesting.
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
            # CenteredDialog already self-centres; don't double-handle it.
            if not isinstance(obj, CenteredDialog) and id(obj) not in self._seen:
                self._seen.add(id(obj))
                center_on_anchor(obj)
        # Never consume the event — we only observe it.
        return False
