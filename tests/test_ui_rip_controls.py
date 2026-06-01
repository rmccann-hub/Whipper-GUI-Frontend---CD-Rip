"""Tests for whipper_gui.ui.rip_controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from whipper_gui.config import Config
from whipper_gui.ui.rip_controls import RipControls
from whipper_gui.workers.rip_worker import RipParameters


def _cfg() -> Config:
    return Config(
        output_dir="/music",
        track_template="t/%n",
        disc_template="d/%d",
    )


# --- Initial state -------------------------------------------------------


def test_default_state_disables_both_buttons(qapp: QApplication) -> None:
    controls = RipControls(_cfg())
    assert controls._start_button.isEnabled() is False
    assert controls._cancel_button.isEnabled() is False


# --- Start enable logic --------------------------------------------------


def test_start_enabled_when_drive_and_release_id_set(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    assert controls.can_start() is False  # need release_id too
    controls.set_release_id("mbid")
    assert controls.can_start() is True


def test_start_enabled_in_unknown_mode_with_only_drive(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_unknown_mode(True)
    assert controls.can_start() is True


def test_start_disabled_without_drive_even_in_unknown_mode(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_unknown_mode(True)
    assert controls.can_start() is False


# --- Rip-active state ----------------------------------------------------


def test_rip_active_disables_start_enables_cancel(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    assert controls.can_start() is True

    controls.set_rip_active(True)
    assert controls._start_button.isEnabled() is False
    assert controls._cancel_button.isEnabled() is True


def test_rip_inactive_re_enables_start_when_state_ok(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    controls.set_rip_active(True)
    controls.set_rip_active(False)

    assert controls._start_button.isEnabled() is True
    assert controls._cancel_button.isEnabled() is False


# --- Signal emissions ----------------------------------------------------


def test_start_click_emits_rip_requested_with_assembled_params(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid-abc")

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert len(captured) == 1
    params = captured[0]
    assert params.drive == "/dev/sr0"
    assert params.release_id == "mbid-abc"
    assert params.output_dir == Path("/music")
    assert params.track_template == "t/%n"
    assert params.disc_template == "d/%d"
    assert params.unknown is False


def test_start_passes_continue_on_cdr_from_config(
    qapp: QApplication,
) -> None:
    """The CD-R toggle in config must reach the assembled RipParameters."""
    config = Config(output_dir="/music", continue_on_cdr=True)
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].cdr is True


def test_cdr_defaults_false_when_config_omits_it(qapp: QApplication) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].cdr is False


def test_set_config_updates_params_for_next_rip(qapp: QApplication) -> None:
    """A Settings change (new Config) must be reflected on the next rip."""
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")

    controls.set_config(Config(output_dir="/elsewhere", continue_on_cdr=True))

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].output_dir == Path("/elsewhere")
    assert captured[0].cdr is True


def test_unknown_mode_uses_unknown_templates(qapp: QApplication) -> None:
    config = Config(
        output_dir="/music",
        track_template="known-track",
        disc_template="known-disc",
        track_template_unknown="unknown-track",
        disc_template_unknown="unknown-disc",
    )
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_unknown_mode(True)

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].track_template == "unknown-track"
    assert captured[0].disc_template == "unknown-disc"


def test_known_mode_uses_known_templates(qapp: QApplication) -> None:
    config = Config(
        output_dir="/music",
        track_template="known-track",
        disc_template="known-disc",
        track_template_unknown="unknown-track",
        disc_template_unknown="unknown-disc",
    )
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].track_template == "known-track"
    assert captured[0].disc_template == "known-disc"


def test_start_in_unknown_mode_sets_unknown_flag(
    qapp: QApplication,
) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_unknown_mode(True)

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    assert captured[0].unknown is True
    # release_id is "" when not set; whipper's --unknown supersedes it.
    assert captured[0].release_id == ""


def test_cancel_click_emits_cancel_requested(qapp: QApplication) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    controls.set_rip_active(True)

    fired: list[bool] = []
    controls.cancel_requested.connect(lambda: fired.append(True))
    controls._cancel_button.click()

    assert fired == [True]


# --- Clearing state ------------------------------------------------------


def test_clearing_drive_disables_start(qapp: QApplication) -> None:
    controls = RipControls(_cfg())
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    assert controls.can_start() is True

    controls.set_drive("")

    assert controls.can_start() is False


def test_parity_gap_config_flows_into_rip_parameters(
    qapp: QApplication,
) -> None:
    config = Config(
        output_dir="/music",
        cover_art="embed",
        force_overread=True,
        max_retries=7,
        keep_going=True,
    )
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")

    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()

    p = captured[0]
    assert p.cover_art == "embed"
    assert p.force_overread is True
    assert p.max_retries == 7
    assert p.keep_going is True


def test_offset_override_flows_when_enabled(qapp: QApplication) -> None:
    config = Config(output_dir="/music", read_offset=667, override_read_offset=True)
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()
    assert captured[0].read_offset_override == 667


def test_offset_override_none_when_disabled(qapp: QApplication) -> None:
    config = Config(output_dir="/music", read_offset=667, override_read_offset=False)
    controls = RipControls(config)
    controls.set_drive("/dev/sr0")
    controls.set_release_id("mbid")
    captured: list[RipParameters] = []
    controls.rip_requested.connect(captured.append)
    controls._start_button.click()
    assert captured[0].read_offset_override is None


def test_force_stop_button_enabled_only_during_rip(qapp: QApplication) -> None:
    controls = RipControls(Config(output_dir="/music"))
    # Idle: force-stop disabled.
    assert controls._force_stop_button.isEnabled() is False
    controls.set_rip_active(True)
    assert controls._force_stop_button.isEnabled() is True
    controls.set_rip_active(False)
    assert controls._force_stop_button.isEnabled() is False


def test_force_stop_button_emits_signal(qapp: QApplication) -> None:
    controls = RipControls(Config(output_dir="/music"))
    controls.set_rip_active(True)
    fired: list[bool] = []
    controls.force_stop_requested.connect(lambda: fired.append(True))
    controls._force_stop_button.click()
    assert fired == [True]
