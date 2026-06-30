"""Tests for platterpus.app_icon (the in-app window icon loader)."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from platterpus import app_icon as app_icon_mod
from platterpus.app_icon import app_icon, logo_pixmap


def test_app_icon_loads_the_bundled_logo(qapp: QApplication) -> None:
    # The SVG ships inside the package, so this resolves from a source checkout
    # (and would from a wheel/AppImage). PySide6 bundles the Qt SVG plugin, so
    # the QIcon is non-null.
    icon = app_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_app_icon_never_raises_without_qt(monkeypatch) -> None:
    # If the Qt import fails (or anything else goes wrong), the loader returns
    # None rather than blocking startup.
    import builtins

    real_import = builtins.__import__

    def boom(name, *args, **kwargs):
        if name == "PySide6.QtGui":
            raise ImportError("simulated missing Qt")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert app_icon() is None


def test_logo_pixmap_returns_a_pixmap(qapp: QApplication) -> None:
    from PySide6.QtGui import QPixmap

    pixmap = logo_pixmap(48)
    assert isinstance(pixmap, QPixmap)
    assert not pixmap.isNull()


def test_logo_pixmap_none_when_icon_missing(qapp: QApplication, monkeypatch) -> None:
    # If the icon can't be loaded, the pixmap helper degrades to None rather
    # than raising (the About dialog then just skips the header image).
    monkeypatch.setattr(app_icon_mod, "app_icon", lambda: None)
    assert logo_pixmap(48) is None
