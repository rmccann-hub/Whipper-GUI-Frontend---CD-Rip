"""Declarative dependency registry.

Every dependency the GUI needs is a `DependencySpec` in `SPECS` below.
The `DependencyManager` iterates `SPECS` to decide what to probe and how
to resolve. Per CLAUDE.md Critical Rule #6, this is the only place
dependencies are enumerated — adding a new dep (an MP3 encoder in P1,
say) is one entry here, no other code changes.

Tier preference per spec is a single choice today; the manager itself
handles cascade-on-failure (tier (a) failures spill to (b), etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from whipper_gui.deps.checks import (
    ProbeResult,
    check_metaflac,
    check_picard_flatpak,
    check_python_pkg,
    check_whipper,
)
from whipper_gui.paths import WHIPPER_BINARY_DEFAULT


class Tier(Enum):
    """Resolution tier for a missing dependency (brief P0 #11 a/b/c)."""

    AUTO = "auto"           # tier (a) — silent install after one OK
    QUEUED = "queued"       # tier (b) — Pending Installs dialog
    MANUAL = "manual"       # tier (c) — copyable search string only


@dataclass(frozen=True)
class DependencySpec:
    """One dependency the GUI needs.

    - `dep_id`: short stable identifier (used in logs and reports).
    - `display_name`: human-readable name shown in dialogs.
    - `probe`: a zero-argument callable returning a ProbeResult. Bind
      arguments at spec-construction time (`functools.partial`) so the
      manager can call every probe uniformly.
    - `min_version`: tuple version floor. `(0, 0, 0)` means "any version".
    - `tier`: preferred resolution tier. The manager handles fallback
      to the next tier if a higher one fails.
    - `install_command`: argv for the install command (used by AutoInstaller
      and QueuedInstaller). None for manual-only deps.
    - `search_string`: copyable text for the tier (c) dialog. Phrased
      as a Google-search-friendly query.
    - `description`: one-line explanation shown in the dialog body.
    """

    dep_id: str
    display_name: str
    probe: Callable[[], ProbeResult]
    min_version: tuple[int, ...]
    tier: Tier
    install_command: list[str] | None
    search_string: str
    description: str = ""
    # Optional list of fallback tiers in order. Manager walks this on
    # failure of the primary tier. Defaults to "no fallback".
    fallback_tiers: tuple[Tier, ...] = field(default_factory=tuple)


# --- Bound probes -----------------------------------------------------------
#
# Each spec's `probe` field needs to be a zero-arg callable. For probes
# that take parameters (`check_whipper` wants a path) we use a closure.
# Defining the closures here keeps SPECS readable.


def _probe_whipper() -> ProbeResult:
    return check_whipper(WHIPPER_BINARY_DEFAULT)


def _probe_metaflac() -> ProbeResult:
    return check_metaflac()


def _probe_picard() -> ProbeResult:
    return check_picard_flatpak()


def _probe_musicbrainzngs() -> ProbeResult:
    return check_python_pkg("musicbrainzngs")


# --- The registry ----------------------------------------------------------

SPECS: list[DependencySpec] = [
    DependencySpec(
        dep_id="whipper",
        display_name="whipper",
        probe=_probe_whipper,
        min_version=(0, 10, 0),
        tier=Tier.MANUAL,  # Distrobox-routed; not auto-installable
        install_command=None,
        search_string="install whipper Bazzite Fedora Distrobox",
        description=(
            "The whipper CD ripping CLI, exported from the Distrobox "
            "container `ripping` to ~/.local/bin/whipper."
        ),
    ),
    DependencySpec(
        dep_id="metaflac",
        display_name="metaflac (FLAC tag editor)",
        probe=_probe_metaflac,
        min_version=(1, 3, 0),
        tier=Tier.MANUAL,
        install_command=None,
        search_string="install metaflac flac Bazzite Fedora Distrobox",
        description=(
            "Part of the FLAC reference encoder package. Used to apply "
            "tags after a rip and to add placeholders for unknown discs."
        ),
    ),
    DependencySpec(
        dep_id="picard",
        display_name="MusicBrainz Picard (Flatpak)",
        probe=_probe_picard,
        min_version=(0, 0, 0),  # any installed version is fine
        tier=Tier.AUTO,
        install_command=[
            "flatpak", "install", "--user", "-y",
            "flathub", "org.musicbrainz.Picard",
        ],
        search_string=(
            "install MusicBrainz Picard Flathub user "
            "org.musicbrainz.Picard"
        ),
        description=(
            "Optional. Auto-launched on unknown discs when the "
            "'Auto-launch Picard' setting is enabled."
        ),
        fallback_tiers=(Tier.QUEUED, Tier.MANUAL),
    ),
    DependencySpec(
        dep_id="musicbrainzngs",
        display_name="musicbrainzngs (Python package)",
        probe=_probe_musicbrainzngs,
        min_version=(0, 7, 1),
        tier=Tier.MANUAL,  # bundled in the AppImage; if missing the
                           # AppImage is broken — point user at reinstall
        install_command=None,
        search_string="reinstall whipper-gui AppImage musicbrainzngs",
        description=(
            "Python MusicBrainz client. Bundled into the AppImage at "
            "build time; if missing, the AppImage build is incomplete."
        ),
    ),
]
