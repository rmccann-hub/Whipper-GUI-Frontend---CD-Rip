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
    QComboBox,
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
    detect_offset_requested = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config: Config = config

        self.setWindowTitle("Settings")
        self.setModal(True)

        root = QVBoxLayout(self)
        form = QFormLayout()

        # --- Path rows (QLineEdit + Browse button) ---
        self._output_dir_edit, output_row = self._build_dir_row(config.output_dir)
        form.addRow("Output directory:", output_row)

        self._working_dir_edit, working_row = self._build_dir_row(config.working_dir)
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
        # Two ways to set the read offset:
        #   1. The drive-setup wizard ("Re-detect…") writes it to
        #      whipper.conf — the recommended path.
        #   2. Type it here and tick "Override" to pass `--offset N` to the
        #      rip, overriding whipper.conf — so you can set it from the GUI
        #      without editing the config file (real-user request).
        # The spinbox is now editable; whether it's USED is gated by the
        # override checkbox so there's no "I typed 667 but it's ignored"
        # confusion.
        self._read_offset_spin: QSpinBox = QSpinBox(self)
        self._read_offset_spin.setRange(_OFFSET_MIN, _OFFSET_MAX)
        self._read_offset_spin.setValue(config.read_offset)
        self._read_offset_spin.setToolTip(
            "Read offset in samples (signed). Tick Override to force this "
            "value via whipper's --offset; otherwise whipper.conf wins."
        )
        self._detect_offset_button: QPushButton = QPushButton("Re-detect…", self)
        self._detect_offset_button.setToolTip(
            "Run the drive setup wizard to auto-detect the read offset "
            "and cache behaviour, and save them to whipper.conf."
        )
        self._detect_offset_button.clicked.connect(self.detect_offset_requested)
        offset_row = QHBoxLayout()
        offset_row.addWidget(self._read_offset_spin, stretch=1)
        offset_row.addWidget(self._detect_offset_button)
        form.addRow("Read offset (samples):", offset_row)

        self._override_offset_check: QCheckBox = QCheckBox(
            "Override whipper.conf with the offset above", self
        )
        self._override_offset_check.setChecked(config.override_read_offset)
        self._override_offset_check.setToolTip(
            "When on, each rip is run with --offset <the value above>, "
            "overriding whatever the drive setup wizard wrote to whipper.conf."
        )
        form.addRow("", self._override_offset_check)

        # --- Tool paths ---
        self._whipper_path_edit, whipper_row = self._build_file_row(config.whipper_path)
        form.addRow("whipper path:", whipper_row)

        self._metaflac_path_edit, metaflac_row = self._build_file_row(
            config.metaflac_path
        )
        form.addRow("metaflac path:", metaflac_row)

        # --- Ripping backend (KDD-18) ---
        # Store the raw backend id as item data ("whipper" | "cyanrip").
        self._backend_combo: QComboBox = QComboBox(self)
        for label, value in (
            ("whipper (default)", "whipper"),
            ("cyanrip (experimental)", "cyanrip"),
        ):
            self._backend_combo.addItem(label, value)
        backend_index = self._backend_combo.findData(config.ripper_backend)
        self._backend_combo.setCurrentIndex(backend_index if backend_index >= 0 else 0)
        self._backend_combo.setToolTip(
            "Which ripping tool to drive. cyanrip applies the read offset with "
            "its own paranoia, avoiding whipper's known bug at offsets over 587 "
            "(e.g. the Pioneer BDR-209D's +667). cyanrip must be installed in "
            "the container and is experimental — restart the app after changing."
        )
        form.addRow("Ripping backend:", self._backend_combo)

        # --- Toggles ---
        self._auto_picard_check: QCheckBox = QCheckBox(
            "Launch MusicBrainz Picard on unknown discs", self
        )
        self._auto_picard_check.setChecked(config.auto_launch_picard)
        form.addRow("Picard integration:", self._auto_picard_check)

        # Auto-eject the disc when a rip finishes successfully. Convenience
        # only — the manual Eject button next to the drive picker works
        # regardless of this toggle.
        self._auto_eject_check: QCheckBox = QCheckBox(
            "Eject the disc after a successful rip", self
        )
        self._auto_eject_check.setChecked(config.auto_eject_after_rip)
        self._auto_eject_check.setToolTip(
            "When a rip completes successfully, eject the disc automatically. "
            "Leave off if you rip several discs from the same tray."
        )
        form.addRow("After rip:", self._auto_eject_check)

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

        # --- EAC bit-perfect parity gaps (KDD-13) ---
        # Cover art: maps to whipper's -C/--cover-art {file,embed,complete}.
        # We store the raw whipper value as item data; "" = don't fetch.
        self._cover_art_combo: QComboBox = QComboBox(self)
        for label, value in (
            ("Don't fetch", ""),
            ("Embed in FLAC", "embed"),
            ("Save as file", "file"),
            ("Embed and save file", "complete"),
        ):
            self._cover_art_combo.addItem(label, value)
        cover_index = self._cover_art_combo.findData(config.cover_art)
        self._cover_art_combo.setCurrentIndex(cover_index if cover_index >= 0 else 0)
        self._cover_art_combo.setToolTip(
            "Fetch album cover art and embed it in the FLACs and/or save it "
            "as a file (whipper's --cover-art). EAC embeds by default."
        )
        form.addRow("Cover art:", self._cover_art_combo)

        self._force_overread_check: QCheckBox = QCheckBox(
            "Force overread into the lead-out", self
        )
        self._force_overread_check.setChecked(config.force_overread)
        self._force_overread_check.setToolTip(
            "Read into the disc's lead-out to capture the final samples "
            "(whipper's --force-overread). Off matches EAC's recommendation; "
            "few drives support it and it can slow the last track."
        )
        form.addRow("Overread:", self._force_overread_check)

        self._max_retries_spin: QSpinBox = QSpinBox(self)
        self._max_retries_spin.setRange(0, 100)
        self._max_retries_spin.setValue(config.max_retries)
        self._max_retries_spin.setToolTip(
            "How many times whipper retries a troublesome track before "
            "giving up (whipper's --max-retries). 5 is the default."
        )
        form.addRow("Max retries:", self._max_retries_spin)

        self._keep_going_check: QCheckBox = QCheckBox(
            "Keep ripping if a track fails", self
        )
        self._keep_going_check.setChecked(config.keep_going)
        self._keep_going_check.setToolTip(
            "Continue with the remaining tracks instead of aborting the whole "
            "rip when one track can't be read (whipper's --keep-going). Off "
            "by default so a failure is surfaced, not silently skipped."
        )
        form.addRow("On track failure:", self._keep_going_check)

        root.addLayout(form)

        # --- Check dependencies action ---
        # This sits between the form and the OK/Cancel row so it's
        # visually associated with the settings (which is where the
        # paths live that the dep check verifies).
        self._check_deps_button: QPushButton = QPushButton("Check dependencies", self)
        self._check_deps_button.clicked.connect(self.check_dependencies_requested)
        root.addWidget(self._check_deps_button)

        # --- OK / Cancel ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
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
            override_read_offset=self._override_offset_check.isChecked(),
            auto_launch_picard=self._auto_picard_check.isChecked(),
            auto_eject_after_rip=self._auto_eject_check.isChecked(),
            continue_on_cdr=self._continue_on_cdr_check.isChecked(),
            cover_art=self._cover_art_combo.currentData(),
            force_overread=self._force_overread_check.isChecked(),
            max_retries=self._max_retries_spin.value(),
            keep_going=self._keep_going_check.isChecked(),
            ripper_backend=self._backend_combo.currentData(),
            # Preserve fields the dialog doesn't model, so saving Settings
            # never silently resets them (these one-time "already offered"
            # flags being reset is what re-triggered the first-run prompts).
            drive_setup_prompted=self._config.drive_setup_prompted,
            host_setup_prompted=self._config.host_setup_prompted,
            appimage_integration_prompted=self._config.appimage_integration_prompted,
            schema_version=self._config.schema_version,
        )

    # --- Internals ---------------------------------------------------------

    def _build_dir_row(self, initial_path: str) -> tuple[QLineEdit, QWidget]:
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

    def _build_file_row(self, initial_path: str) -> tuple[QLineEdit, QWidget]:
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
        path = QFileDialog.getExistingDirectory(self, "Choose directory", edit.text())
        if path:
            edit.setText(path)

    def _pick_file(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose binary", edit.text())
        if path:
            edit.setText(path)
