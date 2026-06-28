"""Tests for platterpus.goal_presets (the rip-goal preset bundles)."""

from __future__ import annotations

from platterpus.config import Config
from platterpus.goal_presets import (
    GOAL_ARCHIVAL,
    GOAL_CUSTOM,
    GOAL_FAST,
    GOAL_PORTABLE,
    apply_preset,
    detect_goal,
)


def test_default_config_is_fast_verified() -> None:
    # The shipping defaults must equal the Fast-verified preset, so adopting
    # presets changed no behaviour and the default goal is a real preset.
    assert detect_goal(Config()) == GOAL_FAST


def test_apply_archival_sets_the_bundle() -> None:
    out = apply_preset(Config(), GOAL_ARCHIVAL)
    assert out.output_format == "flac"
    assert out.ctdb_verify_after_rip is True
    assert out.recompress_flac_after_rip is True
    assert out.rip_goal == GOAL_ARCHIVAL
    assert detect_goal(out) == GOAL_ARCHIVAL


def test_apply_portable_selects_mp3() -> None:
    out = apply_preset(Config(), GOAL_PORTABLE)
    assert out.output_format == "mp3"
    assert out.ctdb_verify_after_rip is False
    assert detect_goal(out) == GOAL_PORTABLE


def test_hand_tuned_config_detects_as_custom() -> None:
    # FLAC + CTDB on but NOT recompressed matches no preset.
    cfg = Config(
        output_format="flac",
        ctdb_verify_after_rip=True,
        recompress_flac_after_rip=False,
    )
    assert detect_goal(cfg) == GOAL_CUSTOM


def test_apply_unknown_goal_is_noop() -> None:
    cfg = Config(ctdb_verify_after_rip=True)
    assert apply_preset(cfg, GOAL_CUSTOM) is cfg  # unchanged
    assert apply_preset(cfg, "nonsense") is cfg
