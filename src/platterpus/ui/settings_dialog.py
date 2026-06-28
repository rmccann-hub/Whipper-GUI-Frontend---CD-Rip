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
    QDialog,
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

from platterpus import goal_presets, offset_config
from platterpus.config import Config

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

        # Show the offset whipper will ACTUALLY apply, read live from
        # whipper.conf — not the GUI's stored copy above. These can drift (the
        # wizard or a hand-edit writes whipper.conf; the spinbox is our cache),
        # and a wrong offset silently corrupts every rip, so surfacing the
        # authoritative value is a real trust check. Reading this tiny file on
        # the GUI thread is fine (it's bytes, not a subprocess/network call).
        self._live_offset_label: QLabel = QLabel(
            f"whipper.conf read offset: {offset_config.describe_conf_offsets()}",
            self,
        )
        self._live_offset_label.setWordWrap(True)
        self._live_offset_label.setToolTip(
            "What whipper will use when Override is off (it's authoritative "
            "then). With Override on, the value above is used instead. "
            "'none set' means whipper will refuse to rip until you run "
            "Re-detect…."
        )
        form.addRow("", self._live_offset_label)

        # --- Tool paths ---
        self._whipper_path_edit, whipper_row = self._build_file_row(config.whipper_path)
        self._whipper_path_row: QWidget = whipper_row
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

        # --- Output format ---
        # Both backends rip to FLAC (the lossless master); a non-FLAC choice is
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
            "as a file. With the whipper backend whipper fetches it itself "
            "(--cover-art); with cyanrip (and after a no-network re-rip) "
            "this app fetches it from the Cover Art Archive once the rip "
            "finishes. EAC embeds by default."
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

        # --- Marginal-disc convergence (cyanrip -Z N, EAC-parity item 1) ---
        # Re-rip each track until N reads' checksums agree, so a damaged disc's
        # near-miss read converges to the bit-perfect result. cyanrip-only
        # (whipper has no equivalent) — greyed out below for whipper. 0 = off.
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
        # default. Greyed out for whipper, which already verifies during the rip.
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
        # Post-rip `flac -8` re-encode of each output FLAC to shrink it. Opt-in,
        # OFF by default. Greyed out for cyanrip, which already maxes compression.
        self._recompress_flac_check: QCheckBox = QCheckBox(
            "Re-compress FLAC files after a rip (smaller files)", self
        )
        self._recompress_flac_check.setChecked(config.recompress_flac_after_rip)
        self._recompress_flac_check.setToolTip(
            "After a successful rip, re-encode each FLAC at maximum effort "
            "(`flac -8 -e -p`) to shrink it as far as flac can. Lossless and "
            "verified — the audio stays bit-identical and the tags and cover art "
            "are preserved. Needs `flac`; runs in the background (the exhaustive "
            "encode is slow, but that's encode time only). Off by default: the "
            "smaller file uses a higher prediction order, so it costs a little "
            "more CPU/battery to DECODE on playback — negligible on a phone or PC "
            "today, but if you play on low-power portable players, leaving this "
            "off (whipper's default level) is the lighter choice."
        )
        form.addRow("Re-compress FLACs:", self._recompress_flac_check)

        root.addLayout(form)

        # --- Backend capability gating (one UI for both backends) ---
        # The dialog shows the SAME options whichever backend is selected;
        # options a backend doesn't support are greyed out (values kept,
        # never cleared) with a tooltip saying why and how to re-enable.
        # The frontend's job is to hide backend differences, not mirror them.
        self._whipper_only: list[tuple[QWidget, str, str]] = [
            (
                widget,
                widget.toolTip(),
                reason,
            )
            for widget, reason in (
                (
                    self._continue_on_cdr_check,
                    "cyanrip rips burned CD-Rs without needing a switch, so "
                    "there is nothing to configure.",
                ),
                # Cover art is deliberately NOT in this list (2026-06-13):
                # it's backend-independent now — with cyanrip the GUI
                # fetches the front cover from the Cover Art Archive itself
                # after the rip, so the setting stays editable everywhere.
                (
                    self._force_overread_check,
                    "Overread control isn't wired to the cyanrip backend yet.",
                ),
                (
                    self._keep_going_check,
                    "cyanrip always continues past an unreadable track, so "
                    "this is effectively always on.",
                ),
                (
                    self._whipper_path_row,
                    "Only the whipper backend uses this path. cyanrip is "
                    "found automatically (~/.local/bin/cyanrip, installed by "
                    "Tools → Set up Platterpus…).",
                ),
                (
                    self._recompress_flac_check,
                    "cyanrip already encodes FLAC at maximum compression, so "
                    "there is nothing to re-compress.",
                ),
            )
        ]
        # The inverse: options that only make sense for cyanrip, greyed out for
        # whipper (kept editable, value preserved — same contract as above).
        self._cyanrip_only: list[tuple[QWidget, str, str]] = [
            (
                self._verify_flac_check,
                self._verify_flac_check.toolTip(),
                "whipper already verifies every file during the rip "
                "(`flac --verify`), so a separate post-rip check is redundant.",
            ),
            (
                self._secure_rerip_spin,
                self._secure_rerip_spin.toolTip(),
                "Re-rip-until-reads-match is a cyanrip feature (-Z); whipper "
                "has no equivalent flag.",
            ),
        ]
        self._backend_combo.currentIndexChanged.connect(
            self._apply_backend_capabilities
        )
        self._apply_backend_capabilities()

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
            whipper_path=self._whipper_path_edit.text(),
            metaflac_path=self._metaflac_path_edit.text(),
            read_offset=self._read_offset_spin.value(),
            override_read_offset=self._override_offset_check.isChecked(),
            auto_launch_picard=self._auto_picard_check.isChecked(),
            auto_eject_after_rip=self._auto_eject_check.isChecked(),
            debug_logging=self._debug_logging_check.isChecked(),
            continue_on_cdr=self._continue_on_cdr_check.isChecked(),
            cover_art=self._cover_art_combo.currentData(),
            force_overread=self._force_overread_check.isChecked(),
            max_retries=self._max_retries_spin.value(),
            keep_going=self._keep_going_check.isChecked(),
            secure_rerip_matches=self._secure_rerip_spin.value(),
            ctdb_verify_after_rip=self._ctdb_verify_check.isChecked(),
            verify_flac_after_rip=self._verify_flac_check.isChecked(),
            recompress_flac_after_rip=self._recompress_flac_check.isChecked(),
            ripper_backend=self._backend_combo.currentData(),
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

    def _apply_backend_capabilities(self) -> None:
        """Enable/disable per-backend options to match the selected backend.

        Disabled widgets keep their values (to_config still reads them, so
        switching backends never loses settings); the tooltip gains a
        "Read-only:" paragraph explaining why and how to make it editable
        again. Runs at construction and on every backend-combo change so
        the dialog reacts live, before OK is even pressed.
        """
        on_whipper = self._backend_combo.currentData() == "whipper"
        for widget, base_tooltip, reason in self._whipper_only:
            widget.setEnabled(on_whipper)
            if on_whipper:
                widget.setToolTip(base_tooltip)
            else:
                prefix = f"{base_tooltip}\n\n" if base_tooltip else ""
                widget.setToolTip(
                    f"{prefix}Read-only: {reason}\n"
                    "Switch “Ripping backend” to whipper to edit this. "
                    "Your value is kept either way."
                )
        # cyanrip-only options: the mirror image — editable on cyanrip, greyed
        # (value kept) on whipper.
        for widget, base_tooltip, reason in self._cyanrip_only:
            widget.setEnabled(not on_whipper)
            if not on_whipper:
                widget.setToolTip(base_tooltip)
            else:
                prefix = f"{base_tooltip}\n\n" if base_tooltip else ""
                widget.setToolTip(
                    f"{prefix}Read-only: {reason}\n"
                    "Switch “Ripping backend” to cyanrip to edit this. "
                    "Your value is kept either way."
                )

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
