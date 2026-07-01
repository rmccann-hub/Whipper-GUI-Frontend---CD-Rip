"""Tests for platterpus.config.

Monkeypatches the CONFIG_PATH and CONFIG_DIR module attributes so each
test gets an isolated tmp directory and the user's real ~/.config is
never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from platterpus import config as config_module
from platterpus.config import SCHEMA_VERSION


def _redirect_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config module at tmp_path. Returns the redirected file path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_file)
    return config_file


def test_config_has_no_whipper_era_fields() -> None:
    """Regression guard for the whipper removal (KDD-18): the config dataclass
    must not carry the retired whipper-only fields. If one creeps back, some
    dead code is reading it — fail here, loudly."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(config_module.Config)}
    retired = {
        "ripper_backend",
        "whipper_path",
        "continue_on_cdr",
        "force_overread",
        "keep_going",
    }
    leaked = field_names & retired
    assert not leaked, f"retired whipper-era config field(s) reappeared: {leaked}"


def test_load_ignores_unknown_legacy_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upgrading user's config.toml still has the old whipper keys; load()
    must drop them silently rather than choke (mirrors the real 0.4.0→0.4.1
    upgrade, where the log showed 'unknown config keys ignored: …')."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        'schema_version = 1\nread_offset = 667\nripper_backend = "whipper"\n'
        'whipper_path = "/x"\nkeep_going = true\n',
        encoding="utf-8",
    )

    cfg = config_module.load()  # must not raise

    assert cfg.read_offset == 667  # the still-valid key survived
    assert not hasattr(cfg, "ripper_backend")


def test_first_load_creates_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the file is missing, load() writes defaults and returns them."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    assert not config_file.exists()

    cfg = config_module.load()

    assert config_file.exists()
    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.auto_launch_picard is False
    assert cfg.read_offset == 0


def test_save_then_load_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modifying and saving persists; the next load sees the change."""
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    cfg.read_offset = 667
    cfg.auto_launch_picard = True
    config_module.save(cfg)

    reloaded = config_module.load()
    assert reloaded.read_offset == 667
    assert reloaded.auto_launch_picard is True


def test_auto_eject_defaults_off_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    assert cfg.auto_eject_after_rip is False  # default

    cfg.auto_eject_after_rip = True
    config_module.save(cfg)
    assert config_module.load().auto_eject_after_rip is True


def test_debug_logging_defaults_off_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    assert cfg.debug_logging is False  # default off

    cfg.debug_logging = True
    config_module.save(cfg)
    assert config_module.load().debug_logging is True


def test_ctdb_verify_defaults_on_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    # On by default (0.4.5): full verification of the master for every format.
    assert cfg.ctdb_verify_after_rip is True

    cfg.ctdb_verify_after_rip = False
    config_module.save(cfg)
    assert config_module.load().ctdb_verify_after_rip is False


def test_verify_flac_defaults_on_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    assert cfg.verify_flac_after_rip is True  # default ON (archival integrity)

    cfg.verify_flac_after_rip = False
    config_module.save(cfg)
    assert config_module.load().verify_flac_after_rip is False


def test_recompress_flac_defaults_off_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    assert cfg.recompress_flac_after_rip is False  # opt-in (costs CPU/time)

    cfg.recompress_flac_after_rip = True
    config_module.save(cfg)
    assert config_module.load().recompress_flac_after_rip is True


def test_output_format_defaults_flac_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    # Default stays FLAC — the lossless archival master (Critical Rule #4);
    # WavPack/MP3/WAV are derived from it when selected (KDD-22).
    assert cfg.output_format == "flac"
    assert cfg.mp3_vbr_quality == 0

    cfg.output_format = "mp3"
    cfg.mp3_vbr_quality = 2
    config_module.save(cfg)
    reloaded = config_module.load()
    assert reloaded.output_format == "mp3"
    assert reloaded.mp3_vbr_quality == 2


def test_save_is_atomic_no_tmp_left_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file used during atomic write must not survive a successful save."""
    config_file = _redirect_config(tmp_path, monkeypatch)

    cfg = config_module.load()
    config_module.save(cfg)

    tmp_file = config_file.with_suffix(".tmp")
    assert not tmp_file.exists(), "temp file leaked after successful save"


def test_unknown_keys_are_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newer file with extra keys loads without crashing in an older binary."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    # Hand-write a config with one known key and one future key.
    config_file.write_text(
        'schema_version = 1\nread_offset = 100\nfuture_key_not_in_v1 = "value"\n'
    )

    cfg = config_module.load()

    assert cfg.read_offset == 100
    # The unknown key didn't sneak onto the dataclass.
    assert not hasattr(cfg, "future_key_not_in_v1")


def test_v1_untouched_templates_ride_chain_to_current_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v1 config still holding the v1 default templates rides the whole
    migration chain (v1→v2→v3) to the current clean Artist/Album/## - Title
    default on load."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        "schema_version = 1\n"
        'track_template = "%A - %d/%t. %a - %n"\n'
        'disc_template = "%A - %d/%A - %d"\n'
    )

    cfg = config_module.load()

    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.track_template == "%A/%d/%t - %n"
    assert cfg.disc_template == "%A/%d/%d"
    # The unknown-disc templates fill in from defaults (absent in v1).
    assert cfg.track_template_unknown.startswith("Unknown Artist/Unknown Album/")


def test_v2_cluttered_default_upgrades_to_clean_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v2 config still on the cluttered default template (repeated
    album/artist + trailing date) auto-upgrades to the clean v3 default."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        "schema_version = 2\n"
        'track_template = "%A/%d/%t - %n - %d - %A - %y"\n'
        'disc_template = "%A/%d/%d"\n'
    )

    cfg = config_module.load()

    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.track_template == "%A/%d/%t - %n"
    assert cfg.disc_template == "%A/%d/%d"


def test_migration_preserves_custom_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user who hand-edited their template keeps it through every upgrade."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text('schema_version = 1\ntrack_template = "my/custom/%t %n"\n')

    cfg = config_module.load()

    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.track_template == "my/custom/%t %n"


def test_v3_year_preset_upgrades_to_year_only_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v3 config on a year-in-folder preset (which used %y = the full date)
    auto-upgrades to the year-only %Y form introduced in v4."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        "schema_version = 3\n"
        'track_template = "%A/%d (%y)/%t - %n"\n'
        'disc_template = "%A/%d (%y)/%d"\n'
    )

    cfg = config_module.load()

    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.track_template == "%A/%d (%Y)/%t - %n"
    assert cfg.disc_template == "%A/%d (%Y)/%d"


def test_v3_year_preset_migration_leaves_custom_templates_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The v3→v4 year-token upgrade only touches an exact old preset template —
    a hand-edited one that happens to contain %y is left untouched."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text('schema_version = 3\ntrack_template = "%A - %d - %y/%t"\n')

    cfg = config_module.load()

    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.track_template == "%A - %d - %y/%t"
