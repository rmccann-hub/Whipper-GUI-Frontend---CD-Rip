"""Locate the Platterpus application icon for the in-app window icon.

The canonical icon is the SVG logo. We ship a copy *inside the package*
(``resources/platterpus-logo.svg``) so the window icon works identically from a
source checkout, a ``pipx`` install, and the single-file AppImage — the same
"keep runtime assets in the package, not as loose data files" reasoning as
``help_content`` (this project has been bitten by AppImage package-data gaps).

Best-effort and never raises: if the resource or the Qt SVG plugin is missing,
``app_icon()`` returns ``None`` and the caller simply skips setting an icon.
"""

from __future__ import annotations

import logging
from importlib import resources

log = logging.getLogger(__name__)

_LOGO_RESOURCE: str = "platterpus-logo.svg"


def app_icon() -> object | None:
    """Return a ``QIcon`` for the app, or ``None`` if it can't be loaded.

    Typed as ``object`` so importing this module never forces a Qt import at
    module load (it's only needed when actually building the icon). PySide6
    bundles the Qt SVG image plugin, so a ``QIcon`` built from the ``.svg``
    renders at every size the window manager asks for.
    """
    try:
        from PySide6.QtGui import QIcon

        with resources.as_file(
            resources.files("platterpus.resources") / _LOGO_RESOURCE
        ) as path:
            icon = QIcon(str(path))
        if icon.isNull():
            log.debug("app icon loaded but QIcon is null (no SVG plugin?)")
            return None
        return icon
    except Exception:  # noqa: BLE001 — a missing icon must never block startup
        log.debug("could not load app icon", exc_info=True)
        return None


def logo_pixmap(size: int = 96) -> object | None:
    """Return a square ``QPixmap`` of the logo at `size` px, or ``None``.

    Used to put the logo *forward* in the UI (e.g. the About dialog header).
    Best-effort and never raises — callers skip the image if it's ``None``.
    """
    try:
        from PySide6.QtCore import QSize

        icon = app_icon()
        if icon is None:
            return None
        pixmap = icon.pixmap(QSize(size, size))  # type: ignore[attr-defined]
        return None if pixmap.isNull() else pixmap
    except Exception:  # noqa: BLE001 — a missing logo must never break a dialog
        log.debug("could not build logo pixmap", exc_info=True)
        return None
