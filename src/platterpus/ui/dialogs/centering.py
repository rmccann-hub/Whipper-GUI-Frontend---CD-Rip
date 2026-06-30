"""A QDialog base that centres itself on the parent window when first shown.

Real-user report (2026-06-30): on a multi-monitor desktop a first-run modal
popped up on a *different* screen from the main window, so the (application-
modal) window correctly refused all input but the user couldn't see why — it
looked frozen and unclickable. Qt/KDE place a new top-level on the screen under
the cursor or the primary screen, not necessarily over the window the user is
looking at.

Centring every dialog on its parent window puts the prompt where the user's
attention already is. It's best-effort: a no-op under native Wayland (clients
can't position themselves — the app prefers XWayland, where ``move()`` works),
and a no-op in headless tests that construct a dialog but never show it.
"""

from __future__ import annotations

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QApplication, QDialog, QWidget


def center_on_anchor(widget: QWidget) -> None:
    """Move `widget` over its parent window (or the active window / screen).

    Best-effort and never raises: a no-op under native Wayland (clients can't
    position themselves — the app prefers XWayland, where ``move()`` works) and
    in headless tests that construct a dialog but never show it. Shared by
    :class:`CenteredDialog` and the app-wide ``auto_center`` filter (which
    catches ``QMessageBox`` and other dialogs that don't subclass this).
    """
    try:
        parent = widget.parentWidget()
        anchor = parent.window() if parent is not None else QApplication.activeWindow()
        frame = widget.frameGeometry()
        if anchor is not None and anchor is not widget:
            frame.moveCenter(anchor.frameGeometry().center())
        else:
            screen = widget.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            frame.moveCenter(screen.availableGeometry().center())
        widget.move(frame.topLeft())
    except Exception:  # noqa: BLE001 — placement is cosmetic, never fatal
        pass


class CenteredDialog(QDialog):
    """``QDialog`` that moves itself over its parent window on first show."""

    _centered_once: bool = False

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        if self._centered_once:
            return
        self._centered_once = True
        center_on_anchor(self)
