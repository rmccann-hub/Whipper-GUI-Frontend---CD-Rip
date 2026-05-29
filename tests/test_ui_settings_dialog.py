"""Tests for whipper_gui.ui.settings_dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from whipper_gui.config import Config, SCHEMA_VERSION
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


def test_to_config_preserves_schema_version(qapp: QApplication) -> None:
    config = Config(schema_version=99)
    dialog = SettingsDialog(config)
    assert dialog.to_config().schema_version == 99


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
