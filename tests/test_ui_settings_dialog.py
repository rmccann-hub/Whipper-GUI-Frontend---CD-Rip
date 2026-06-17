"""Tests for whipper_gui.ui.settings_dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from whipper_gui.config import SCHEMA_VERSION, Config
from whipper_gui.ui.settings_dialog import SettingsDialog

# --- Construction --------------------------------------------------------


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
        whipper_path="/x/whipper",
        metaflac_path="/x/metaflac",
        read_offset=42,
        auto_launch_picard=True,
        continue_on_cdr=True,
    )

    dialog = SettingsDialog(config)

    assert dialog._output_dir_edit.text() == "/music"
    assert dialog._working_dir_edit.text() == "/tmp/work"
    assert dialog._track_template_edit.text() == "t/%n"
    assert dialog._disc_template_edit.text() == "d/%d"
    assert dialog._track_template_unknown_edit.text() == "unk-t"
    assert dialog._disc_template_unknown_edit.text() == "unk-d"
    assert dialog._whipper_path_edit.text() == "/x/whipper"
    assert dialog._metaflac_path_edit.text() == "/x/metaflac"
    assert dialog._read_offset_spin.value() == 42
    assert dialog._auto_picard_check.isChecked() is True
    assert dialog._continue_on_cdr_check.isChecked() is True


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
    dialog._whipper_path_edit.setText("/changed/whipper")
    dialog._metaflac_path_edit.setText("/changed/metaflac")
    dialog._read_offset_spin.setValue(-42)
    dialog._auto_picard_check.setChecked(True)
    dialog._continue_on_cdr_check.setChecked(True)

    out = dialog.to_config()

    assert out.output_dir == "/changed/output"
    assert out.working_dir == "/changed/working"
    assert out.track_template == "changed-track"
    assert out.disc_template == "changed-disc"
    assert out.track_template_unknown == "changed-unk-track"
    assert out.disc_template_unknown == "changed-unk-disc"
    assert out.whipper_path == "/changed/whipper"
    assert out.metaflac_path == "/changed/metaflac"
    assert out.read_offset == -42
    assert out.auto_launch_picard is True
    assert out.continue_on_cdr is True


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
    dialog = SettingsDialog(Config(ctdb_verify_after_rip=True))
    assert dialog._ctdb_verify_check.isChecked() is True

    # …and defaults off, with a user toggle surviving to_config().
    dialog2 = SettingsDialog(Config())
    assert dialog2._ctdb_verify_check.isChecked() is False
    dialog2._ctdb_verify_check.setChecked(True)
    assert dialog2.to_config().ctdb_verify_after_rip is True


def test_to_config_preserves_schema_version(qapp: QApplication) -> None:
    config = Config(schema_version=99)
    dialog = SettingsDialog(config)
    assert dialog.to_config().schema_version == 99


def test_backend_combo_reflects_config_and_round_trips(qapp: QApplication) -> None:
    # Default is whipper.
    assert SettingsDialog(Config()).to_config().ripper_backend == "whipper"
    # An existing cyanrip config is shown and survives to_config().
    dialog = SettingsDialog(Config(ripper_backend="cyanrip"))
    assert dialog._backend_combo.currentData() == "cyanrip"
    assert dialog.to_config().ripper_backend == "cyanrip"


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
        force_overread=True,
        max_retries=9,
        keep_going=True,
    )
    dialog = SettingsDialog(config)
    assert dialog._cover_art_combo.currentData() == "complete"
    assert dialog._force_overread_check.isChecked() is True
    assert dialog._max_retries_spin.value() == 9
    assert dialog._keep_going_check.isChecked() is True


def test_parity_gap_widgets_round_trip_through_to_config(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config())
    dialog._cover_art_combo.setCurrentIndex(dialog._cover_art_combo.findData("file"))
    dialog._force_overread_check.setChecked(True)
    dialog._max_retries_spin.setValue(3)
    dialog._keep_going_check.setChecked(True)

    out = dialog.to_config()

    assert out.cover_art == "file"
    assert out.force_overread is True
    assert out.max_retries == 3
    assert out.keep_going is True


def test_cover_art_blank_option_maps_to_empty_string(
    qapp: QApplication,
) -> None:
    dialog = SettingsDialog(Config(cover_art="embed"))
    dialog._cover_art_combo.setCurrentIndex(dialog._cover_art_combo.findData(""))
    assert dialog.to_config().cover_art == ""


# --- Backend capability gating (unified UI across backends) ---------------


def _whipper_only_widgets(dialog: SettingsDialog) -> list:
    return [w for w, _tip, _reason in dialog._whipper_only]


def test_whipper_only_options_disabled_under_cyanrip(qapp: QApplication) -> None:
    """One unified Settings page: options the selected backend doesn't
    support are read-only, with a tooltip saying why + how to re-enable."""
    dialog = SettingsDialog(Config(ripper_backend="cyanrip"))
    for widget in _whipper_only_widgets(dialog):
        assert widget.isEnabled() is False
        assert "Read-only:" in widget.toolTip()
        assert "whipper" in widget.toolTip()  # says what re-enables it


def test_whipper_only_options_enabled_under_whipper(qapp: QApplication) -> None:
    dialog = SettingsDialog(Config())  # default backend = whipper
    for widget in _whipper_only_widgets(dialog):
        assert widget.isEnabled() is True
        assert "Read-only:" not in widget.toolTip()


def test_backend_switch_updates_gating_live(qapp: QApplication) -> None:
    """Changing the backend combo re-gates immediately (before OK)."""
    dialog = SettingsDialog(Config())
    combo = dialog._backend_combo
    combo.setCurrentIndex(combo.findData("cyanrip"))
    assert dialog._continue_on_cdr_check.isEnabled() is False
    combo.setCurrentIndex(combo.findData("whipper"))
    assert dialog._continue_on_cdr_check.isEnabled() is True
    # The original tooltip is restored, not stacked.
    assert "Read-only:" not in dialog._continue_on_cdr_check.toolTip()


def test_disabled_options_keep_their_values_in_to_config(
    qapp: QApplication,
) -> None:
    """Gated ≠ lost: switching to cyanrip must not clear whipper-only
    settings — they ride along and come back when the user switches back."""
    dialog = SettingsDialog(
        Config(continue_on_cdr=True, keep_going=True, cover_art="complete")
    )
    combo = dialog._backend_combo
    combo.setCurrentIndex(combo.findData("cyanrip"))

    out = dialog.to_config()

    assert out.ripper_backend == "cyanrip"
    assert out.continue_on_cdr is True
    assert out.keep_going is True
    assert out.cover_art == "complete"


def test_cover_art_stays_editable_under_cyanrip(qapp: QApplication) -> None:
    """Cover art is backend-independent now (the GUI fetches it from the
    Cover Art Archive when the ripper doesn't) — never greyed out."""
    dialog = SettingsDialog(Config(ripper_backend="cyanrip"))
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
