"""Tests for platterpus.ui.settings_dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from platterpus import naming
from platterpus.config import SCHEMA_VERSION, Config
from platterpus.goal_presets import GOAL_ARCHIVAL, GOAL_CUSTOM, GOAL_FAST
from platterpus.ui.settings_dialog import SettingsDialog

# --- Construction --------------------------------------------------------


# --- Naming presets ------------------------------------------------------


def test_naming_combo_reflects_default_template(qapp: QApplication) -> None:
    # A fresh config uses the recommended preset, so the combo shows it (not
    # "Custom") and the preview is populated.
    dialog = SettingsDialog(Config())
    assert dialog._naming_combo.currentData() == naming.DEFAULT_PRESET.key
    assert dialog._naming_preview.text().endswith(".flac")


def test_choosing_naming_preset_fills_template_fields(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    year_preset = next(p for p in naming.PRESETS if "(%Y)" in p.track_template)
    index = dialog._naming_combo.findData(year_preset.key)
    dialog._naming_combo.setCurrentIndex(index)
    assert dialog._track_template_edit.text() == year_preset.track_template
    assert dialog._disc_template_edit.text() == year_preset.disc_template
    assert dialog.to_config().track_template == year_preset.track_template


def test_hand_editing_template_flips_combo_to_custom(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    dialog._track_template_edit.setText("my/own/%t %n")
    # Custom is the entry whose data is None — it must not overwrite the text.
    assert dialog._naming_combo.currentData() is None
    assert dialog.to_config().track_template == "my/own/%t %n"


def test_window_title_and_modality(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    assert dialog.windowTitle() == "Settings"
    assert dialog.isModal() is True


def test_initial_widget_state_matches_input_config(
    qapp: QApplication,
) -> None:
    config = Config(
        output_dir="/music",
        working_dir="/tmp/work",
        track_template="t/%n",
        disc_template="d/%d",
        track_template_unknown="unk-t",
        disc_template_unknown="unk-d",
        metaflac_path="/x/metaflac",
        read_offset=42,
        auto_launch_picard=True,
    )

    dialog = SettingsDialog(config)

    assert dialog._output_dir_edit.text() == "/music"
    assert dialog._working_dir_edit.text() == "/tmp/work"
    assert dialog._track_template_edit.text() == "t/%n"
    assert dialog._disc_template_edit.text() == "d/%d"
    assert dialog._track_template_unknown_edit.text() == "unk-t"
    assert dialog._disc_template_unknown_edit.text() == "unk-d"
    assert dialog._metaflac_path_edit.text() == "/x/metaflac"
    assert dialog._read_offset_spin.value() == 42
    assert dialog._auto_picard_check.isChecked() is True


def test_read_offset_range_bounds(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    assert dialog._read_offset_spin.minimum() <= -1000
    assert dialog._read_offset_spin.maximum() >= 1000


# --- to_config -----------------------------------------------------------


def test_to_config_returns_unchanged_when_no_edits(
    qapp: QApplication,
) -> None:
    config = Config(read_offset=667, auto_launch_picard=True)
    dialog = SettingsDialog(config)

    out = dialog.to_config()

    assert out.read_offset == 667
    assert out.auto_launch_picard is True


def test_to_config_reflects_user_edits(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())

    dialog._output_dir_edit.setText("/changed/output")
    dialog._working_dir_edit.setText("/changed/working")
    dialog._track_template_edit.setText("changed-track")
    dialog._disc_template_edit.setText("changed-disc")
    dialog._track_template_unknown_edit.setText("changed-unk-track")
    dialog._disc_template_unknown_edit.setText("changed-unk-disc")
    dialog._metaflac_path_edit.setText("/changed/metaflac")
    dialog._read_offset_spin.setValue(-42)
    dialog._auto_picard_check.setChecked(True)

    out = dialog.to_config()

    assert out.output_dir == "/changed/output"
    assert out.working_dir == "/changed/working"
    assert out.track_template == "changed-track"
    assert out.disc_template == "changed-disc"
    assert out.track_template_unknown == "changed-unk-track"
    assert out.disc_template_unknown == "changed-unk-disc"
    assert out.metaflac_path == "/changed/metaflac"
    assert out.read_offset == -42
    assert out.auto_launch_picard is True


def test_auto_eject_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Reflects the incoming config…
    dialog = SettingsDialog(Config(auto_eject_after_rip=True))
    assert dialog._auto_eject_check.isChecked() is True

    # …and a user toggle survives to_config().
    dialog2 = SettingsDialog(Config())
    assert dialog2._auto_eject_check.isChecked() is False
    dialog2._auto_eject_check.setChecked(True)
    assert dialog2.to_config().auto_eject_after_rip is True


def test_ctdb_verify_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Reflects the incoming config…
    dialog = SettingsDialog(Config(ctdb_verify_after_rip=False))
    assert dialog._ctdb_verify_check.isChecked() is False

    # …and defaults ON (0.4.5: full verification), with a user toggle-off
    # surviving to_config().
    dialog2 = SettingsDialog(Config())
    assert dialog2._ctdb_verify_check.isChecked() is True
    dialog2._ctdb_verify_check.setChecked(False)
    assert dialog2.to_config().ctdb_verify_after_rip is False


def test_verify_flac_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Defaults ON and reflects the incoming config…
    dialog = SettingsDialog(Config())
    assert dialog._verify_flac_check.isChecked() is True

    # …and a user toggle-off survives to_config().
    dialog2 = SettingsDialog(Config(verify_flac_after_rip=False))
    assert dialog2._verify_flac_check.isChecked() is False
    dialog2._verify_flac_check.setChecked(True)
    assert dialog2.to_config().verify_flac_after_rip is True


def test_verify_flac_editable(qapp: QApplication) -> None:
    # cyanrip (the sole backend) doesn't self-verify, so the toggle is editable.
    dialog = SettingsDialog(Config())
    assert dialog._verify_flac_check.isEnabled() is True


def test_recompress_flac_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Defaults OFF (opt-in) and reflects the incoming config…
    dialog = SettingsDialog(Config())
    assert dialog._recompress_flac_check.isChecked() is False

    # …and a user toggle-on survives to_config().
    dialog2 = SettingsDialog(Config(recompress_flac_after_rip=True))
    assert dialog2._recompress_flac_check.isChecked() is True
    dialog2._recompress_flac_check.setChecked(False)
    assert dialog2.to_config().recompress_flac_after_rip is False


def test_recompress_flac_greyed_under_cyanrip(qapp: QApplication) -> None:
    # cyanrip (the sole backend) already maxes compression, so the toggle is
    # permanently read-only (its value is still kept).
    dialog = SettingsDialog(Config())
    assert dialog._recompress_flac_check.isEnabled() is False


def test_secure_rerip_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Defaults OFF (0) and reflects the incoming config…
    dialog = SettingsDialog(Config())
    assert dialog._secure_rerip_spin.value() == 0

    # …and a user value survives to_config().
    dialog2 = SettingsDialog(Config(secure_rerip_matches=2))
    assert dialog2._secure_rerip_spin.value() == 2
    dialog2._secure_rerip_spin.setValue(3)
    assert dialog2.to_config().secure_rerip_matches == 3


def test_secure_rerip_editable(qapp: QApplication) -> None:
    # -Z is cyanrip's (the sole backend) feature → editable.
    dialog = SettingsDialog(Config())
    assert dialog._secure_rerip_spin.isEnabled() is True


def test_goal_combo_reflects_the_incoming_config(qapp: QApplication) -> None:
    # Default config == Fast-verified preset.
    assert SettingsDialog(Config())._goal_combo.currentData() == GOAL_FAST
    # An archival-shaped config shows Archival.
    archival = Config(
        output_format="flac",
        ctdb_verify_after_rip=True,
        recompress_flac_after_rip=True,
    )
    assert SettingsDialog(archival)._goal_combo.currentData() == GOAL_ARCHIVAL


def test_selecting_goal_applies_the_preset_to_controls(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())  # starts Fast-verified (ctdb off)
    idx = dialog._goal_combo.findData(GOAL_ARCHIVAL)
    dialog._goal_combo.setCurrentIndex(idx)
    # The dependent controls snapped to the archival bundle…
    assert dialog._ctdb_verify_check.isChecked() is True
    assert dialog._recompress_flac_check.isChecked() is True
    assert dialog._format_combo.currentData() == "flac"
    # …and to_config carries the goal + the applied fields.
    out = dialog.to_config()
    assert out.rip_goal == GOAL_ARCHIVAL
    assert out.ctdb_verify_after_rip is True


def test_editing_a_control_flips_goal_to_custom(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    assert dialog._goal_combo.currentData() == GOAL_FAST
    # Every preset verifies, so hand-toggling CTDB OFF matches none → Custom.
    dialog._ctdb_verify_check.setChecked(False)
    assert dialog._goal_combo.currentData() == GOAL_CUSTOM
    assert dialog.to_config().rip_goal == GOAL_CUSTOM


def test_to_config_preserves_schema_version(qapp: QApplication) -> None:
    config = Config(schema_version=99)
    dialog = SettingsDialog(config)
    assert dialog.to_config().schema_version == 99


# --- Output format -------------------------------------------------------


def test_output_format_defaults_to_flac(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    assert dialog._format_combo.currentData() == "flac"
    assert dialog.to_config().output_format == "flac"


def test_output_format_reflects_config_and_round_trips(qapp: QApplication) -> None:
    for fmt in ("wavpack", "mp3", "wav"):
        dialog = SettingsDialog(Config(output_format=fmt))
        assert dialog._format_combo.currentData() == fmt
        assert dialog.to_config().output_format == fmt


def test_output_format_user_change_survives_to_config(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())  # starts on flac
    dialog._format_combo.setCurrentIndex(dialog._format_combo.findData("wavpack"))
    assert dialog.to_config().output_format == "wavpack"


def test_saving_settings_preserves_mp3_quality(qapp: QApplication) -> None:
    # mp3_vbr_quality isn't a widget yet; saving must not reset it from a
    # non-default stored value.
    out = SettingsDialog(Config(mp3_vbr_quality=2)).to_config()
    assert out.mp3_vbr_quality == 2


def test_wav_warning_only_visible_for_wav(qapp: QApplication) -> None:
    # Hidden for the formats that DO carry tags/art…
    for fmt in ("flac", "wavpack", "mp3"):
        dialog = SettingsDialog(Config(output_format=fmt))
        assert dialog._wav_warning_label.isVisibleTo(dialog) is False
    # …and shown the moment WAV is selected (live, before OK).
    dialog = SettingsDialog(Config())
    dialog._format_combo.setCurrentIndex(dialog._format_combo.findData("wav"))
    assert dialog._wav_warning_label.isVisibleTo(dialog) is True


def test_to_config_preserves_one_time_prompt_flags(qapp: QApplication) -> None:
    """Saving Settings must NOT reset the 'already offered' flags (doing so
    re-triggered the first-run prompts)."""
    config = Config(
        drive_setup_prompted=True,
        host_setup_prompted=True,
        appimage_integration_prompted=True,
    )
    out = SettingsDialog(config).to_config()
    assert out.drive_setup_prompted is True
    assert out.host_setup_prompted is True
    assert out.appimage_integration_prompted is True


def test_to_config_uses_current_default_for_fresh_config(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config())
    assert dialog.to_config().schema_version == SCHEMA_VERSION


# --- Check dependencies button ------------------------------------------


def test_check_dependencies_signal_fires(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    fired: list[bool] = []
    dialog.check_dependencies_requested.connect(lambda: fired.append(True))

    dialog._check_deps_button.click()

    assert fired == [True]


def test_check_dependencies_does_not_close_dialog(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config())
    dialog._check_deps_button.click()
    assert dialog.result() == 0  # neither accepted nor rejected


# --- Accept / Cancel -----------------------------------------------------


def _button_box(dialog: SettingsDialog) -> QDialogButtonBox:
    """Find the OK/Cancel QDialogButtonBox in the dialog."""
    for child in dialog.findChildren(QDialogButtonBox):
        if child is not None:
            return child
    raise AssertionError("no QDialogButtonBox found")


def test_ok_accepts_dialog(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    box = _button_box(dialog)
    box.button(QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == int(dialog.DialogCode.Accepted)


def test_cancel_rejects_dialog(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    box = _button_box(dialog)
    box.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert dialog.result() == int(dialog.DialogCode.Rejected)


def test_redetect_button_emits_signal(qapp: QApplication) -> None:
    """The Re-detect… button next to the read-offset field asks MainWindow
    to open the drive-setup wizard."""
    dialog = SettingsDialog(Config())
    fired: list[bool] = []
    dialog.detect_offset_requested.connect(lambda: fired.append(True))

    dialog._detect_offset_button.click()

    assert fired == [True]


def test_read_offset_editable_with_override(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config(read_offset=667, override_read_offset=True))
    # Editable now (was read-only before the manual-offset feature).
    assert dialog._read_offset_spin.isReadOnly() is False
    assert dialog._read_offset_spin.value() == 667
    assert dialog._override_offset_check.isChecked() is True


def test_override_offset_round_trips(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())
    dialog._read_offset_spin.setValue(-12)
    dialog._override_offset_check.setChecked(True)
    out = dialog.to_config()
    assert out.read_offset == -12
    assert out.override_read_offset is True


# --- EAC parity-gap widgets ----------------------------------------------


def test_parity_gap_widgets_reflect_config(qapp: QApplication) -> None:
    config = Config(
        cover_art="complete",
        max_retries=9,
    )
    dialog = SettingsDialog(config)
    assert dialog._cover_art_combo.currentData() == "complete"
    assert dialog._max_retries_spin.value() == 9


def test_parity_gap_widgets_round_trip_through_to_config(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config())
    dialog._cover_art_combo.setCurrentIndex(dialog._cover_art_combo.findData("file"))
    dialog._max_retries_spin.setValue(3)

    out = dialog.to_config()

    assert out.cover_art == "file"
    assert out.max_retries == 3


def test_cover_art_blank_option_maps_to_empty_string(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config(cover_art="embed"))
    dialog._cover_art_combo.setCurrentIndex(dialog._cover_art_combo.findData(""))
    assert dialog.to_config().cover_art == ""


def test_cover_art_editable(qapp: QApplication) -> None:
    """Cover art is backend-independent (the GUI fetches it from the Cover Art
    Archive after the rip) — always editable."""
    dialog = SettingsDialog(Config())
    assert dialog._cover_art_combo.isEnabled() is True
    assert "Read-only:" not in dialog._cover_art_combo.toolTip()


def test_debug_logging_reflects_config_and_round_trips(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config(debug_logging=True))
    assert dialog._debug_logging_check.isChecked() is True
    assert dialog.to_config().debug_logging is True
    # Off by default.
    default_dialog = SettingsDialog(Config())
    assert default_dialog._debug_logging_check.isChecked() is False
    assert default_dialog.to_config().debug_logging is False
