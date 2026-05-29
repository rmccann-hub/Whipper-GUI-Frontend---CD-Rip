"""Settings dialog — edits the Config dataclass.

The dialog is a pure view: it doesn't read or write the config file
itself. The caller passes in a `Config`, the user edits the widgets,
and the caller reads back via `to_config()` and persists through
`whipper_gui.config.save()`. This keeps the dialog testable without
touching `~/.config`.

A "Check dependencies" button emits the `check_dependencies_requested`
signal; the caller wires it to the DependencyManager.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whipper_gui.config import Config


# Read offset range. AccurateRip's per-drive offsets are typically in
# the low hundreds of samples; ±5000 is well outside any realistic
# value and prevents typos like "60000".
_OFFSET_MIN: int = -5000
_OFFSET_MAX: int = 5000


class SettingsDialog(QDialog):
    """Modal Settings dialog. Wraps an incoming Config; produces a new one."""

    check_dependencies_requested = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config: Config = config

        self.setWindowTitle("Settings")
        self.setModal(True)

        root = QVBoxLayout(self)
        form = QFormLayout()

        # --- Path rows (QLineEdit + Browse button) ---
        self._output_dir_edit, output_row = self._build_dir_row(
            config.output_dir
        )
        form.addRow("Output directory:", output_row)

        self._working_dir_edit, working_row = self._build_dir_row(
            config.working_dir
        )
        form.addRow("Working directory:", working_row)

        # --- Templates ---
        self._track_template_edit: QLineEdit = QLineEdit(config.track_template, self)
        self._track_template_edit.setToolTip(
            "Path for identified discs. Codes: %A artist, %d album, "
            "%t track #, %n title, %a track artist, %y year, %N disc #."
        )
        form.addRow("Track template:", self._track_template_edit)

        self._disc_template_edit: QLineEdit = QLineEdit(config.disc_template, self)
        form.addRow("Disc template (.log/.cue):", self._disc_template_edit)

        # Unknown-disc templates: used for the --unknown rip so the
        # disc-ID hash whipper puts in %d never reaches the path.
        self._track_template_unknown_edit: QLineEdit = QLineEdit(
            config.track_template_unknown, self
        )
        form.addRow("Track template (unknown):", self._track_template_unknown_edit)

        self._disc_template_unknown_edit: QLineEdit = QLineEdit(
            config.disc_template_unknown, self
        )
        form.addRow("Disc template (unknown):", self._disc_template_unknown_edit)

        # --- Read offset ---
        # Per the brief: whipper.conf is authoritative for the read
        # offset. This field is informational; setting it here does
        # NOT (yet) override what's in whipper.conf. Surfaced clearly
        # in the label + tooltip to avoid the "I set 667 here but my
        # rip is still using 0" confusion real-user testing surfaced.
        self._read_offset_spin: QSpinBox = QSpinBox(self)
        self._read_offset_spin.setRange(_OFFSET_MIN, _OFFSET_MAX)
        self._read_offset_spin.setValue(config.read_offset)
        self._read_offset_spin.setReadOnly(True)
        # Tooltip on the spinbox + the field label so hover-help works
        # regardless of which the user mouses over.
        tooltip = (
            "Informational only — whipper.conf is the authoritative "
            "source. Edit your drive's [drive:VENDOR :MODEL:RELEASE] "
            "section in ~/.config/whipper/whipper.conf to change."
        )
        self._read_offset_spin.setToolTip(tooltip)
        offset_label = "Read offset (informational, see whipper.conf):"
        form.addRow(offset_label, self._read_offset_spin)

        # --- Tool paths ---
        self._whipper_path_edit, whipper_row = self._build_file_row(
            config.whipper_path
        )
        form.addRow("whipper path:", whipper_row)

        self._metaflac_path_edit, metaflac_row = self._build_file_row(
            config.metaflac_path
        )
        form.addRow("metaflac path:", metaflac_row)

        # --- Toggles ---
        self._auto_picard_check: QCheckBox = QCheckBox(
            "Launch MusicBrainz Picard on unknown discs", self
        )
        self._auto_picard_check.setChecked(config.auto_launch_picard)
        form.addRow("Picard integration:", self._auto_picard_check)

        # Continue on CD-R. Whipper refuses burned discs by default; this
        # opts into ripping them anyway (passes whipper's --cdr flag).
        self._continue_on_cdr_check: QCheckBox = QCheckBox(
            "Allow ripping burned CD-R discs", self
        )
        self._continue_on_cdr_check.setChecked(config.continue_on_cdr)
        self._continue_on_cdr_check.setToolTip(
            "Whipper refuses to rip a burned CD-R unless this is enabled "
            "(it passes whipper's --cdr flag). Leave off for pressed "
            "commercial discs; turn on to archive a home-burned disc."
        )
        form.addRow("CD-R discs:", self._continue_on_cdr_check)

        root.addLayout(form)

        # --- Check dependencies action ---
        # This sits between the form and the OK/Cancel row so it's
        # visually associated with the settings (which is where the
        # paths live that the dep check verifies).
        self._check_deps_button: QPushButton = QPushButton(
            "Check dependencies", self
        )
        self._check_deps_button.clicked.connect(
            self.check_dependencies_requested
        )
        root.addWidget(self._check_deps_button)

        # --- OK / Cancel ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    # --- Public surface -----------------------------------------------------

    def to_config(self) -> Config:
        """Build a new Config reflecting the current widget state.

        Preserves the schema_version from the source Config (since the
        dialog doesn't model that field — bumping it is migration
        plumbing's job, not the user's).
        """
        return Config(
            output_dir=self._output_dir_edit.text(),
            working_dir=self._working_dir_edit.text(),
            track_template=self._track_template_edit.text(),
            disc_template=self._disc_template_edit.text(),
            track_template_unknown=self._track_template_unknown_edit.text(),
            disc_template_unknown=self._disc_template_unknown_edit.text(),
            whipper_path=self._whipper_path_edit.text(),
            metaflac_path=self._metaflac_path_edit.text(),
            read_offset=self._read_offset_spin.value(),
            auto_launch_picard=self._auto_picard_check.isChecked(),
            continue_on_cdr=self._continue_on_cdr_check.isChecked(),
            schema_version=self._config.schema_version,
        )

    # --- Internals ---------------------------------------------------------

    def _build_dir_row(
        self, initial_path: str
    ) -> tuple[QLineEdit, QWidget]:
        """Build a row: QLineEdit + 'Browse…' button (for directories)."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(initial_path, row)
        button = QPushButton("Browse…", row)
        button.clicked.connect(lambda: self._pick_directory(edit))

        layout.addWidget(edit, stretch=1)
        layout.addWidget(button)
        return edit, row

    def _build_file_row(
        self, initial_path: str
    ) -> tuple[QLineEdit, QWidget]:
        """Build a row: QLineEdit + 'Browse…' button (for an executable)."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(initial_path, row)
        button = QPushButton("Browse…", row)
        button.clicked.connect(lambda: self._pick_file(edit))

        layout.addWidget(edit, stretch=1)
        layout.addWidget(button)
        return edit, row

    def _pick_directory(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose directory", edit.text()
        )
        if path:
            edit.setText(path)

    def _pick_file(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose binary", edit.text()
        )
        if path:
            edit.setText(path)
