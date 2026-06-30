"""Settings dialog — edits the Config dataclass.

The dialog is a pure view: it doesn't read or write the config file
itself. The caller passes in a `Config`, the user edits the widgets,
and the caller reads back via `to_config()` and persists through
`platterpus.config.save()`. This keeps the dialog testable without
touching `~/.config`.

A "Check dependencies" button emits the `check_dependencies_requested`
signal; the caller wires it to the DependencyManager.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from platterpus import goal_presets, naming, offset_config
from platterpus.config import Config
from platterpus.ui.dialogs.centering import CenteredDialog

# Read offset range. AccurateRip's per-drive offsets are typically in
# the low hundreds of samples; ±5000 is well outside any realistic
# value and prevents typos like "60000".
_OFFSET_MIN: int = -5000
_OFFSET_MAX: int = 5000


class SettingsDialog(CenteredDialog):
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

        # --- Goal preset (anchors the rest of the settings to intent) ---
        # First row on purpose: pick a goal and the format/verification/quality
        # controls below snap to sensible values for it (they stay editable —
        # editing one flips this to "Custom"). See goal_presets.py.
        # Guard so applying a preset (which sets the widgets) doesn't recursively
        # flip the combo back to Custom.
        self._applying_preset: bool = False
        self._goal_combo: QComboBox = QComboBox(self)
        for key, label in goal_presets.GOAL_LABELS:
            self._goal_combo.addItem(label, key)
        self._goal_combo.addItem("Custom (hand-tuned below)", goal_presets.GOAL_CUSTOM)
        self._goal_combo.setToolTip(
            "Pick what you want this rip to be and the format, verification, and "
            "quality options below snap to good values for it. You can still "
            "tweak any of them — that switches this to Custom."
        )
        form.addRow("Goal:", self._goal_combo)

        # --- Path rows (QLineEdit + Browse button) ---
        self._output_dir_edit, output_row = self._build_dir_row(config.output_dir)
        form.addRow("Output directory:", output_row)

        self._working_dir_edit, working_row = self._build_dir_row(config.working_dir)
        form.addRow("Working directory:", working_row)

        # --- Templates ---
        # A preset dropdown so the common layouts are one click instead of a
        # hand-written code string (the old default looked terrible — repeated
        # album/artist + a trailing full date). Picking a preset fills the
        # track/disc template fields below; editing those by hand flips the
        # dropdown to "Custom". A live preview shows the real resulting filename.
        self._naming_combo: QComboBox = QComboBox(self)
        self._naming_combo.setAccessibleName("File naming scheme")
        for preset in naming.PRESETS:
            self._naming_combo.addItem(preset.label, preset.key)
        self._naming_combo.addItem(naming.CUSTOM_LABEL, None)
        form.addRow("Naming scheme:", self._naming_combo)

        self._track_template_edit: QLineEdit = QLineEdit(config.track_template, self)
        self._track_template_edit.setToolTip(
            "Path for identified discs. Codes: %A artist, %d album, "
            "%t track #, %n title, %a track artist, %y date.\n"
            "Pick a preset above, or hand-edit here."
        )
        form.addRow("Track template:", self._track_template_edit)

        self._disc_template_edit: QLineEdit = QLineEdit(config.disc_template, self)
        form.addRow("Disc template (.log/.cue):", self._disc_template_edit)

        # Live preview: the selected template rendered against a metadata-heavy
        # sample (colon in the title, a featured/per-track artist) so the user
        # sees how it copes with the awkward cases before committing. Updates as
        # the preset or the template text changes.
        self._naming_preview: QLabel = QLabel("", self)
        self._naming_preview.setWordWrap(True)
        self._naming_preview.setAccessibleName("Filename preview")
        self._naming_preview.setStyleSheet("color: palette(mid);")
        form.addRow("Example:", self._naming_preview)

        # Wire up: preset → fill fields; manual edit → flip to Custom; either →
        # refresh preview. Signals are blocked while syncing to avoid a loop.
        self._naming_combo.currentIndexChanged.connect(self._on_naming_preset_chosen)
        self._track_template_edit.textChanged.connect(self._on_template_text_changed)
        self._disc_template_edit.textChanged.connect(self._on_template_text_changed)
        self._sync_naming_combo_to_templates()
        self._refresh_naming_preview()

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
        #   1. The drive-setup wizard ("Re-detect…") detects it and the GUI
        #      saves it here — the recommended path.
        #   2. Type it here and tick "Apply" so each rip uses it (cyanrip's
        #      `-s`). cyanrip needs the offset every run; it has no config file
        #      of its own, so this value is the single source.
        self._read_offset_spin: QSpinBox = QSpinBox(self)
        self._read_offset_spin.setRange(_OFFSET_MIN, _OFFSET_MAX)
        self._read_offset_spin.setValue(config.read_offset)
        self._read_offset_spin.setToolTip(
            "Read offset in samples (signed). Tick Apply to use this value for "
            "rips (cyanrip's -s). Set it once per drive via Re-detect…."
        )
        self._detect_offset_button: QPushButton = QPushButton("Re-detect…", self)
        self._detect_offset_button.setToolTip(
            "Run the drive setup wizard to auto-detect the read offset and "
            "save it to Platterpus's settings."
        )
        self._detect_offset_button.clicked.connect(self.detect_offset_requested)
        offset_row = QHBoxLayout()
        offset_row.addWidget(self._read_offset_spin, stretch=1)
        offset_row.addWidget(self._detect_offset_button)
        form.addRow("Read offset (samples):", offset_row)

        self._override_offset_check: QCheckBox = QCheckBox(
            "Apply this read offset to rips", self
        )
        self._override_offset_check.setChecked(config.override_read_offset)
        self._override_offset_check.setToolTip(
            "When on, each rip uses the offset above (cyanrip's -s). Leave it on "
            "once you've set your drive's offset — cyanrip needs it every rip to "
            "stay bit-perfect."
        )
        form.addRow("", self._override_offset_check)

        # Show any read offset found in a legacy whipper.conf, as a trust check
        # against the value above. A pre-Platterpus or hand-edited whipper.conf
        # may still hold a per-drive offset; cyanrip doesn't read it (it uses the
        # value above), but surfacing it lets the user spot a mismatch. Reading
        # this tiny file on the GUI thread is fine (bytes, not a subprocess).
        self._live_offset_label: QLabel = QLabel(
            f"Legacy whipper.conf read offset: {offset_config.describe_conf_offsets()}",
            self,
        )
        self._live_offset_label.setWordWrap(True)
        self._live_offset_label.setToolTip(
            "A read offset found in an old whipper.conf, shown for reference. "
            "cyanrip uses the value above, not this file. 'none set' is normal."
        )
        form.addRow("", self._live_offset_label)

        # --- Tool paths ---
        self._metaflac_path_edit, metaflac_row = self._build_file_row(
            config.metaflac_path
        )
        form.addRow("metaflac path:", metaflac_row)

        # --- Output format ---
        # Every rip produces FLAC (the lossless master); a non-FLAC choice is
        # derived afterwards by a post-rip ffmpeg transcode, with the FLAC kept.
        # Item data is the raw config value.
        self._format_combo: QComboBox = QComboBox(self)
        for label, value in (
            ("FLAC — lossless archival master (recommended)", "flac"),
            ("WavPack (.wv) — lossless, with tags", "wavpack"),
            ("MP3 — lossy, best-quality VBR, with tags + cover", "mp3"),
            ("WAV — raw PCM, no tags or cover art", "wav"),
        ):
            self._format_combo.addItem(label, value)
        format_index = self._format_combo.findData(config.output_format)
        self._format_combo.setCurrentIndex(format_index if format_index >= 0 else 0)
        self._format_combo.setToolTip(
            "What the rip delivers. FLAC is the lossless archival master and is "
            "always produced; for any other choice the GUI keeps that FLAC and "
            "creates the selected format alongside it (a post-rip transcode). "
            "FLAC and WavPack are lossless; MP3 is high-quality lossy (VBR ~245 "
            "kbps) for portability; WAV is raw PCM and can't store tags or art."
        )
        form.addRow("Output format:", self._format_combo)

        # WAV is the one format that can't carry tags/cover art (RIFF has no
        # tag chunk). Surface that the moment WAV is picked so it's never a
        # silent surprise — WavPack is the lossless-with-tags alternative.
        self._wav_warning_label: QLabel = QLabel(
            "⚠ WAV can't store tags or cover art. For lossless audio that keeps "
            "your metadata, choose WavPack instead.",
            self,
        )
        self._wav_warning_label.setWordWrap(True)
        form.addRow("", self._wav_warning_label)
        self._format_combo.currentIndexChanged.connect(self._update_wav_warning)
        self._update_wav_warning()

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

        # Debug logging — verbose log file for bug reports. Off by default;
        # testers turn it on, reproduce the issue, then attach the log.
        self._debug_logging_check: QCheckBox = QCheckBox(
            "Debug logging (verbose log for bug reports)", self
        )
        self._debug_logging_check.setChecked(config.debug_logging)
        self._debug_logging_check.setToolTip(
            "Record verbose detail to the log file at\n"
            "~/.local/share/platterpus/log.txt — every probe, command, and "
            "parse step. Turn this on, reproduce the problem, then attach that "
            "file to a bug report. Off keeps the log lighter."
        )
        form.addRow("Logging:", self._debug_logging_check)

        # --- EAC bit-perfect parity gaps (KDD-13) ---
        # Cover art: "" = don't fetch. With cyanrip the GUI fetches the front
        # cover from the Cover Art Archive after the rip and embeds it.
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
            "as a file. The app fetches the front cover from the Cover Art "
            "Archive once the rip finishes. EAC embeds by default."
        )
        form.addRow("Cover art:", self._cover_art_combo)

        self._max_retries_spin: QSpinBox = QSpinBox(self)
        self._max_retries_spin.setRange(0, 100)
        self._max_retries_spin.setValue(config.max_retries)
        self._max_retries_spin.setToolTip(
            "How many times the ripper retries a troublesome track before "
            "giving up (cyanrip's -r). 5 is the default."
        )
        form.addRow("Max retries:", self._max_retries_spin)

        # --- Marginal-disc convergence (cyanrip -Z N, EAC-parity item 1) ---
        # Re-rip each track until N reads' checksums agree, so a damaged disc's
        # near-miss read converges to the bit-perfect result. 0 = off.
        self._secure_rerip_spin: QSpinBox = QSpinBox(self)
        self._secure_rerip_spin.setRange(0, 10)
        self._secure_rerip_spin.setValue(config.secure_rerip_matches)
        self._secure_rerip_spin.setSpecialValueText("Off")  # shown when value is 0
        self._secure_rerip_spin.setToolTip(
            "For damaged or marginal discs: re-rip each track until this many "
            "reads produce the same checksum (cyanrip's -Z). This makes a "
            "shaky read converge to the bit-perfect result, at the cost of "
            "time. 0 (Off) is right for clean discs — the normal secure read "
            "(paranoia + retries) already handles those. Try 2 if a track "
            "won't verify against AccurateRip."
        )
        form.addRow("Re-rip until reads match:", self._secure_rerip_spin)

        # --- CTDB verification (KDD-14 Phase 1) ---
        # A second, TOC-keyed verification path alongside AccurateRip. Off by
        # default: it's a post-rip network call, and a match is currently
        # labelled "experimental" until the audio-CRC is hardware-validated.
        self._ctdb_verify_check: QCheckBox = QCheckBox(
            "Verify with CTDB after a rip (experimental)", self
        )
        self._ctdb_verify_check.setChecked(config.ctdb_verify_after_rip)
        self._ctdb_verify_check.setToolTip(
            "After a successful rip, also check it against the CUETools "
            "Database (a second verification path alongside AccurateRip). This "
            "is a network lookup and decodes the FLACs locally (needs `flac`). "
            "A match is shown as EXPERIMENTAL until the CRC algorithm is "
            "confirmed on real hardware — it can only ever under-claim, never "
            "fabricate a 'verified'. Off by default."
        )
        form.addRow("CTDB:", self._ctdb_verify_check)

        # --- FLAC encode-verify ---
        # Post-rip `flac --test` of each output FLAC (decode + MD5 check). On by
        # default — cyanrip (FFmpeg) doesn't self-verify, so this is a real check.
        self._verify_flac_check: QCheckBox = QCheckBox(
            "Verify FLAC files after a rip", self
        )
        self._verify_flac_check.setChecked(config.verify_flac_after_rip)
        self._verify_flac_check.setToolTip(
            "After a successful rip, run `flac --test` on each FLAC to confirm "
            "it decodes back to its stored checksum (catches encode or disk "
            "corruption). Needs `flac`; runs in the background and only speaks "
            "up if a file fails. On by default."
        )
        form.addRow("Verify FLACs:", self._verify_flac_check)

        # --- FLAC re-compress ---
        # Post-rip `flac -8` re-encode to shrink the output. cyanrip (the sole
        # backend) already encodes FLAC at maximum compression, so there's
        # nothing to gain — the post-rip step skips it for cyanrip. The toggle
        # is shown disabled (value kept) with a tooltip saying why, rather than
        # hidden, so the option's existence and rationale stay discoverable.
        self._recompress_flac_check: QCheckBox = QCheckBox(
            "Re-compress FLAC files after a rip (smaller files)", self
        )
        self._recompress_flac_check.setChecked(config.recompress_flac_after_rip)
        self._recompress_flac_check.setEnabled(False)
        self._recompress_flac_check.setToolTip(
            "Read-only: cyanrip already encodes FLAC at maximum compression, so "
            "re-compressing would only burn CPU for no size gain. Your value is "
            "kept either way."
        )
        form.addRow("Re-compress FLACs:", self._recompress_flac_check)

        root.addLayout(form)

        # --- Goal preset wiring (after all dependent widgets exist) ---
        self._wire_goal_presets()

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
            metaflac_path=self._metaflac_path_edit.text(),
            read_offset=self._read_offset_spin.value(),
            override_read_offset=self._override_offset_check.isChecked(),
            auto_launch_picard=self._auto_picard_check.isChecked(),
            auto_eject_after_rip=self._auto_eject_check.isChecked(),
            debug_logging=self._debug_logging_check.isChecked(),
            cover_art=self._cover_art_combo.currentData(),
            max_retries=self._max_retries_spin.value(),
            secure_rerip_matches=self._secure_rerip_spin.value(),
            ctdb_verify_after_rip=self._ctdb_verify_check.isChecked(),
            verify_flac_after_rip=self._verify_flac_check.isChecked(),
            recompress_flac_after_rip=self._recompress_flac_check.isChecked(),
            output_format=self._format_combo.currentData(),
            rip_goal=self._goal_combo.currentData(),
            # MP3 quality isn't exposed yet (fixed at the best-practice -V0);
            # preserve the stored value so saving Settings never resets it.
            mp3_vbr_quality=self._config.mp3_vbr_quality,
            # Preserve fields the dialog doesn't model, so saving Settings
            # never silently resets them (these one-time "already offered"
            # flags being reset is what re-triggered the first-run prompts).
            drive_setup_prompted=self._config.drive_setup_prompted,
            host_setup_prompted=self._config.host_setup_prompted,
            appimage_integration_prompted=self._config.appimage_integration_prompted,
            integration_declined_path=self._config.integration_declined_path,
            schema_version=self._config.schema_version,
        )

    # --- Internals ---------------------------------------------------------

    def _update_wav_warning(self) -> None:
        """Show the no-tags/art warning only when WAV is the selected format."""
        self._wav_warning_label.setVisible(self._format_combo.currentData() == "wav")

    # --- Naming presets ----------------------------------------------------

    def _on_naming_preset_chosen(self) -> None:
        """Fill the template fields from the chosen preset.

        "Custom" (data is None) leaves the fields alone — it just means the
        current templates don't match a preset. We block the edits' signals so
        setting their text doesn't immediately re-sync the combo back.
        """
        key = self._naming_combo.currentData()
        if key is None:
            return
        preset = next((p for p in naming.PRESETS if p.key == key), None)
        if preset is None:
            return
        self._track_template_edit.blockSignals(True)
        self._disc_template_edit.blockSignals(True)
        self._track_template_edit.setText(preset.track_template)
        self._disc_template_edit.setText(preset.disc_template)
        self._track_template_edit.blockSignals(False)
        self._disc_template_edit.blockSignals(False)
        self._refresh_naming_preview()

    def _on_template_text_changed(self) -> None:
        """A hand-edit of either template re-syncs the combo and the preview."""
        self._sync_naming_combo_to_templates()
        self._refresh_naming_preview()

    def _sync_naming_combo_to_templates(self) -> None:
        """Point the combo at the matching preset, or "Custom" if hand-edited.

        Combo signals are blocked so this never re-triggers preset application.
        """
        preset = naming.preset_for_templates(
            self._track_template_edit.text(), self._disc_template_edit.text()
        )
        target = preset.key if preset is not None else None
        index = self._naming_combo.findData(target)
        if index < 0:
            return
        self._naming_combo.blockSignals(True)
        self._naming_combo.setCurrentIndex(index)
        self._naming_combo.blockSignals(False)

    def _refresh_naming_preview(self) -> None:
        """Render the current track template against the stress sample."""
        example = naming.render_preview(
            self._track_template_edit.text(), naming.SAMPLE_STRESS
        )
        self._naming_preview.setText(example)

    # --- Goal presets ------------------------------------------------------

    # The controls a goal preset drives — editing any of them flips the goal to
    # "Custom" (their changed-signals are wired to _on_dependent_changed).
    def _goal_driven_widgets(self) -> list[QWidget]:
        return [
            self._format_combo,
            self._ctdb_verify_check,
            self._recompress_flac_check,
            self._secure_rerip_spin,
        ]

    def _wire_goal_presets(self) -> None:
        """Show the goal matching the incoming config, then keep combo and
        controls in sync: picking a goal sets the controls; editing a control
        flips the goal to Custom."""
        detected = goal_presets.detect_goal(self._config)
        index = self._goal_combo.findData(detected)
        self._goal_combo.setCurrentIndex(index if index >= 0 else 0)
        self._goal_combo.currentIndexChanged.connect(self._on_goal_changed)
        # A control changing means the user hand-tuned away from the preset.
        self._format_combo.currentIndexChanged.connect(self._on_dependent_changed)
        self._ctdb_verify_check.toggled.connect(self._on_dependent_changed)
        self._recompress_flac_check.toggled.connect(self._on_dependent_changed)
        self._secure_rerip_spin.valueChanged.connect(self._on_dependent_changed)

    def _on_goal_changed(self) -> None:
        """Apply the selected preset to the dependent controls."""
        goal = self._goal_combo.currentData()
        if goal == goal_presets.GOAL_CUSTOM:
            return  # Custom doesn't impose values
        preset = goal_presets.PRESETS.get(goal)
        if preset is None:
            return
        # Guard so the setValue/setChecked calls below don't re-enter
        # _on_dependent_changed and bounce the combo to Custom.
        self._applying_preset = True
        try:
            fmt_index = self._format_combo.findData(preset.output_format)
            if fmt_index >= 0:
                self._format_combo.setCurrentIndex(fmt_index)
            self._ctdb_verify_check.setChecked(preset.ctdb_verify_after_rip)
            self._recompress_flac_check.setChecked(preset.recompress_flac_after_rip)
            self._secure_rerip_spin.setValue(preset.secure_rerip_matches)
        finally:
            self._applying_preset = False

    def _on_dependent_changed(self) -> None:
        """A goal-driven control was edited by the user → switch to Custom."""
        if self._applying_preset:
            return  # we're the ones setting it, not the user
        custom_index = self._goal_combo.findData(goal_presets.GOAL_CUSTOM)
        if custom_index >= 0 and self._goal_combo.currentIndex() != custom_index:
            self._goal_combo.setCurrentIndex(custom_index)

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
