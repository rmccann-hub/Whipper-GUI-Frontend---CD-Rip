"""Goal presets — anchor the rip settings to user *intent*.

Deep-research lesson (docs/ux-design-principles.md #3): novices shouldn't have to
reason about abstract toggles (CTDB, re-compress, format) before they understand
the consequences. EAC's blunt "accurate results vs higher speed" choice worked
because it anchored everything else to a goal. We do the same with three presets.

A preset is just a *bundle of the existing Config fields* — it sets sane values
for a stated goal; the individual Settings controls stay editable underneath
(progressive disclosure, not a wizard that hides things). Picking a preset is a
convenience, never a new code path: the rip still reads the individual fields.

Pure module (no Qt): the Settings dialog applies a preset to its widgets and
reflects the matching preset back. Default goal == the shipping defaults, so
adopting this changed no behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from platterpus.config import Config

# Stable keys persisted in Config.rip_goal; "custom" means "doesn't match any
# preset" (the user hand-tuned the individual controls).
GOAL_FAST: str = "fast_verified"
GOAL_ARCHIVAL: str = "archival"
GOAL_PORTABLE: str = "portable"
GOAL_CUSTOM: str = "custom"


@dataclass(frozen=True)
class GoalPreset:
    """The Config fields a goal sets. Other fields are left untouched."""

    output_format: str
    ctdb_verify_after_rip: bool
    recompress_flac_after_rip: bool
    secure_rerip_matches: int


# The three goals. NOTE: GOAL_FAST equals the shipping Config defaults, so the
# default goal is "fast_verified" and adopting presets changed no behaviour.
#   * Fast verified — lossless FLAC, AccurateRip-verified, no extra network/CPU.
#   * Archival exact — also CTDB whole-disc verify + max-compression re-encode.
#   * Portable — MP3 derived from the FLAC master, for phones/players.
PRESETS: dict[str, GoalPreset] = {
    GOAL_FAST: GoalPreset(
        output_format="flac",
        ctdb_verify_after_rip=False,
        recompress_flac_after_rip=False,
        secure_rerip_matches=0,
    ),
    GOAL_ARCHIVAL: GoalPreset(
        output_format="flac",
        ctdb_verify_after_rip=True,
        recompress_flac_after_rip=True,
        secure_rerip_matches=0,
    ),
    GOAL_PORTABLE: GoalPreset(
        output_format="mp3",
        ctdb_verify_after_rip=False,
        recompress_flac_after_rip=False,
        secure_rerip_matches=0,
    ),
}

# (key, human label) in display order — the Settings combo reads this. "Custom"
# is appended by the dialog; it's not a real preset.
GOAL_LABELS: list[tuple[str, str]] = [
    (GOAL_FAST, "Fast verified — lossless, AccurateRip-checked (recommended)"),
    (GOAL_ARCHIVAL, "Archival exact — also CTDB-verify + smallest lossless files"),
    (GOAL_PORTABLE, "Portable — MP3 copy for phones/players"),
]


def apply_preset(config: Config, goal: str) -> Config:
    """Return a copy of ``config`` with ``goal``'s preset fields applied.

    Unknown/``custom`` goals return the config unchanged (nothing to apply).
    """
    preset = PRESETS.get(goal)
    if preset is None:
        return config
    return replace(
        config,
        rip_goal=goal,
        output_format=preset.output_format,
        ctdb_verify_after_rip=preset.ctdb_verify_after_rip,
        recompress_flac_after_rip=preset.recompress_flac_after_rip,
        secure_rerip_matches=preset.secure_rerip_matches,
    )


def detect_goal(config: Config) -> str:
    """Return the preset key whose fields match ``config``, else ``"custom"``.

    Lets the Settings dialog show which goal the current settings correspond to
    (and "Custom" once the user hand-tunes a control away from any preset).
    """
    for key, preset in PRESETS.items():
        if (
            config.output_format == preset.output_format
            and config.ctdb_verify_after_rip == preset.ctdb_verify_after_rip
            and config.recompress_flac_after_rip == preset.recompress_flac_after_rip
            and config.secure_rerip_matches == preset.secure_rerip_matches
        ):
            return key
    return GOAL_CUSTOM
