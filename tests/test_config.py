"""Tests for whipper_gui.config.

Monkeypatches the CONFIG_PATH and CONFIG_DIR module attributes so each
test gets an isolated tmp directory and the user's real ~/.config is
never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whipper_gui import config as config_module
from whipper_gui.config import SCHEMA_VERSION


def _redirect_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the config module at tmp_path. Returns the redirected file path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_file)
    return config_file


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
        'schema_version = 1\n'
        'read_offset = 100\n'
        'future_key_not_in_v1 = "value"\n'
    )

    cfg = config_module.load()

    assert cfg.read_offset == 100
    # The unknown key didn't sneak onto the dataclass.
    assert not hasattr(cfg, "future_key_not_in_v1")


def test_v1_to_v2_upgrades_untouched_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A v1 config still holding the v1 default templates auto-upgrades
    to the v2 Artist/Album layout on load."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        'schema_version = 1\n'
        'track_template = "%A - %d/%t. %a - %n"\n'
        'disc_template = "%A - %d/%A - %d"\n'
    )

    cfg = config_module.load()

    assert cfg.schema_version == 2
    assert cfg.track_template == "%A/%d/%t - %n - %d - %A - %y"
    assert cfg.disc_template == "%A/%d/%d"
    # The unknown-disc templates fill in from defaults (absent in v1).
    assert cfg.track_template_unknown.startswith("Unknown Artist/Unknown Album/")


def test_v1_to_v2_preserves_custom_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user who hand-edited their template keeps it through the upgrade."""
    config_file = _redirect_config(tmp_path, monkeypatch)
    config_file.write_text(
        'schema_version = 1\n'
        'track_template = "my/custom/%t %n"\n'
    )

    cfg = config_module.load()

    assert cfg.schema_version == 2
    assert cfg.track_template == "my/custom/%t %n"
