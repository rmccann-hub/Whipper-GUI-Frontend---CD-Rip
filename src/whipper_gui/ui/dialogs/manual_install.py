"""Manual-install dialog — tier (c) of the dependency subsystem.

Shown when a dependency can't be auto-installed and requires user
judgment or root privileges (the brief's classic example: `libdiscid`
via `rpm-ostree install + reboot` on Bazzite). The dialog presents:

  - The missing dependency's name and required minimum version
  - A one-line explanation of why we can't auto-install
  - A copyable read-only QLineEdit with a Google-search-ready query
  - Primary action: Copy. Secondary action: Close.

No installation happens here — the user is expected to follow the
search string to resolve manually and then re-run the dependency check.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.registry import DependencySpec


class ManualInstallDialog(QDialog):
    """Tier (c) dialog. Modal; shown once per unresolvable dependency."""

    def __init__(
        self,
        spec: DependencySpec,
        probe: ProbeResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec: DependencySpec = spec
        self._probe: ProbeResult = probe

        self.setWindowTitle(f"Install required: {spec.display_name}")
        self.setModal(True)

        # Top-level layout: vertical with the form first, then the
        # copyable search-string row, then the button box.
        root = QVBoxLayout(self)

        intro = QLabel(self._intro_text())
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.addRow("Required:", QLabel(self._required_text()))
        form.addRow("Currently:", QLabel(self._current_text()))
        form.addRow("Why manual:", QLabel(self._why_text()))
        root.addLayout(form)

        # The copyable field. ReadOnly so the user can select but not
        # accidentally edit; selectByMouse + selectAll on focus keeps
        # the keyboard workflow ergonomic.
        self._search_field: QLineEdit = QLineEdit(spec.search_string, self)
        self._search_field.setReadOnly(True)
        self._search_field.setCursorPosition(0)
        root.addWidget(QLabel("Copyable search string:"))
        root.addWidget(self._search_field)

        # Button box. Copy is the primary (accept role) action; Close
        # is the secondary (reject role). Qt renders the primary first
        # on KDE/Plasma; matches the brief's "Copy is primary" intent.
        button_box = QDialogButtonBox(self)
        self._copy_button: QPushButton = button_box.addButton(
            "Copy", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._close_button: QPushButton = button_box.addButton(
            "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        self._copy_button.setDefault(True)
        # Copy button doesn't close the dialog — user can copy multiple
        # times if they want. Close button does.
        self._copy_button.clicked.connect(self.copy_search_string)
        self._close_button.clicked.connect(self.reject)
        root.addWidget(button_box)

    # --- Public surface -----------------------------------------------------

    def search_string(self) -> str:
        """Return what the Copy button would copy. Useful for tests."""
        return self._search_field.text()

    def copy_search_string(self) -> None:
        """Copy the search string to the system clipboard.

        Also briefly updates the Copy button label so the user sees
        feedback that the action took effect. We restore it shortly
        after via QTimer so the dialog can be used again.
        """
        QGuiApplication.clipboard().setText(self._search_field.text())
        self._copy_button.setText("Copied!")
        # Reset the label after a short delay. Using Qt's single-shot
        # timer keeps the GUI thread non-blocking.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, lambda: self._copy_button.setText("Copy"))

    # --- Display string builders -------------------------------------------

    def _intro_text(self) -> str:
        return (
            f"{self._spec.display_name} needs to be installed manually. "
            "Copy the search string below and use your distro's package "
            "tooling to resolve it, then re-run the dependency check "
            "from Settings."
        )

    def _required_text(self) -> str:
        version = ".".join(str(part) for part in self._spec.min_version)
        if version == "0.0.0":
            return "any installed version"
        return f">= {version}"

    def _current_text(self) -> str:
        if not self._probe.present:
            return "not installed"
        if self._probe.version is None:
            return "installed (version unknown)"
        version = ".".join(str(part) for part in self._probe.version)
        return f"installed: {version}"

    def _why_text(self) -> str:
        # Specs that need root, a reboot, or a distro-specific install
        # path are the typical tier-(c) inhabitants. Description gives
        # the human context.
        return self._spec.description or "Requires user action."
