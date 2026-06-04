"""Help-menu dialogs: About (version + environment) and User Guide.

Both are thin read-only viewers built on `QTextBrowser` so links are clickable
and the (Markdown) content renders nicely. They construct off whatever is
available without doing any I/O that could block the UI — the About box reports
*configured* paths and interpreter/Qt versions, and deliberately does NOT shell
out to whipper (which would mean entering the container and could stall).
"""

from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from whipper_gui import __version__, help_content
from whipper_gui.paths import (
    CONFIG_PATH,
    LOG_PATH,
    WHIPPER_BINARY_DEFAULT,
    WHIPPER_CONFIG_PATH,
)


def _markdown_viewer(parent: QWidget | None, markdown: str) -> QTextBrowser:
    """A read-only, link-clickable Markdown view."""
    view = QTextBrowser(parent)
    view.setOpenExternalLinks(True)  # open repo/issue links in the browser
    view.setMarkdown(markdown)
    return view


class AboutDialog(QDialog):
    """Version number and other support-relevant info, on Help → About."""

    def __init__(
        self,
        whipper_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Whipper GUI")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        layout.addWidget(_markdown_viewer(self, self._build_markdown(whipper_path)))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _build_markdown(whipper_path: str | None) -> str:
        whipper = whipper_path or str(WHIPPER_BINARY_DEFAULT)
        py = "{}.{}.{}".format(*sys.version_info[:3])
        return (
            f"# Whipper GUI\n\n"
            f"**Version {__version__}**\n\n"
            f"{help_content.TAGLINE}\n\n"
            f"### Environment\n"
            f"- Python: {py}\n"
            f"- Qt: {qVersion()}\n"
            f"- PySide6: {PYSIDE_VERSION}\n"
            f"- Platform: {platform.platform()}\n\n"
            f"### Paths\n"
            f"- Config: `{CONFIG_PATH}`\n"
            f"- Log: `{LOG_PATH}`\n"
            f"- whipper binary: `{whipper}`\n"
            f"- whipper.conf: `{WHIPPER_CONFIG_PATH}`\n\n"
            f"### Project\n"
            f"- [Source & releases]({help_content.REPO_URL})\n"
            f"- [Report an issue]({help_content.ISSUES_URL})\n"
            f"- License: {help_content.LICENSE_NAME}\n"
        )


class HelpDialog(QDialog):
    """The user guide, on Help → User Guide."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Whipper GUI — User Guide")
        self.resize(720, 580)

        layout = QVBoxLayout(self)
        layout.addWidget(_markdown_viewer(self, help_content.USER_GUIDE))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
