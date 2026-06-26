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

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from whipper_gui.deps.checks import (
    ProbeResult,
    check_ffmpeg,
    check_flac,
    check_metaflac,
    check_picard_flatpak,
    check_python_pkg,
    check_whipper,
)
from whipper_gui.paths import WHIPPER_BINARY_DEFAULT


class Tier(Enum):
    """Resolution tier for a missing dependency (brief P0 #11 a/b/c)."""

    AUTO = "auto"  # tier (a) — silent install after one OK
    QUEUED = "queued"  # tier (b) — Pending Installs dialog
    MANUAL = "manual"  # tier (c) — copyable search string only


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
    # When True, a missing/outdated probe is informational, not a problem:
    # the launch-time check won't nag or offer to install it, and the
    # summary lists it as "optional, not installed" rather than "missing".
    # Picard is the case in point — handy for unknown discs, not required.
    optional: bool = False


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


def _probe_flac() -> ProbeResult:
    return check_flac()


def _probe_ffmpeg() -> ProbeResult:
    return check_ffmpeg()


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
        # Install via the .flatpakref URL rather than `flathub <ref>`.
        # The .flatpakref includes the remote URL, so flatpak adds
        # flathub at user level on first install. This is necessary
        # because on Bazzite (and other Atomic distros) flathub is
        # configured as a *system* remote by default — a `--user`
        # install can't see system remotes and fails with
        # "error: No remote refs found for 'flathub'", as verified by
        # real-user testing on Bazzite (chat 2026-05-28).
        install_command=[
            "flatpak",
            "install",
            "--user",
            "-y",
            "https://dl.flathub.org/repo/appstream/org.musicbrainz.Picard.flatpakref",
        ],
        search_string=(
            "install MusicBrainz Picard Flathub user org.musicbrainz.Picard"
        ),
        description=(
            "Optional. Auto-launched on unknown discs when the "
            "'Auto-launch Picard' setting is enabled."
        ),
        fallback_tiers=(Tier.QUEUED, Tier.MANUAL),
        optional=True,  # not required — don't nag if it's absent
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
    DependencySpec(
        dep_id="flac",
        display_name="flac (FLAC decoder)",
        probe=_probe_flac,
        min_version=(1, 3, 0),
        tier=Tier.MANUAL,
        install_command=None,
        search_string="install flac decoder Bazzite Fedora host export Distrobox",
        description=(
            "Optional. Only needed for the 'Verify with CTDB after a rip' "
            "setting: the CTDB audio check decodes the FLACs back to PCM on "
            "the host. Export it from the container like whipper "
            "(distrobox-export --bin /usr/bin/flac) or install it on the host."
        ),
        optional=True,  # absent only disables the optional CTDB audio check
    ),
    DependencySpec(
        dep_id="ffmpeg",
        display_name="ffmpeg (WavPack/MP3/WAV transcoder)",
        probe=_probe_ffmpeg,
        min_version=(4, 0),
        tier=Tier.MANUAL,
        install_command=None,
        search_string="install ffmpeg Bazzite Fedora host export Distrobox",
        description=(
            "Optional. The encoder for the Output-format feature (KDD-22): "
            "transcodes the FLAC master to WavPack, MP3, or WAV when a non-FLAC "
            "output is selected. Absent only disables non-FLAC output (FLAC "
            "ripping is unaffected, and the FLAC master is always kept). Already "
            "present wherever cyanrip is installed (cyanrip is built on FFmpeg)."
        ),
        optional=True,  # absent only disables non-FLAC output (FLAC unaffected)
    ),
]
