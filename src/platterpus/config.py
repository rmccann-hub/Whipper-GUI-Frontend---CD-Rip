"""TOML config persistence for the GUI.

Reads `~/.config/platterpus/config.toml` via stdlib `tomllib`; writes
via the `tomli-w` package (stdlib is read-only). Uses a typed dataclass
so callers see attribute access (`cfg.output_dir`) instead of dict
lookups, and so the schema lives in one place.

- The first `load()` call creates the file with defaults if missing.
- `save()` writes atomically (temp file + rename) so a crash mid-save
  can't corrupt the user's settings.
- Unknown keys in an older binary loading a newer file are logged and
  dropped, not crashed on. This keeps forward compatibility cheap.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

from platterpus.paths import (
    CONFIG_DIR,
    CONFIG_PATH,
)

# Bump this when the schema grows new keys or changes defaults that we
# want to migrate. Migration logic lives in _migrate() below.
SCHEMA_VERSION: int = 4

# Computed once at import time. If the user's HOME changes mid-process,
# the GUI needs a restart — same as every other XDG-aware application.
_DEFAULT_OUTPUT_DIR: Path = Path.home() / "Music" / "rips"
_DEFAULT_WORKING_DIR: Path = Path.home() / ".cache" / "platterpus"

# Whipper path templates (see `whipper cd rip --help`). Format codes:
#   %A = release artist   %d = release title (album)   %a = track artist
#   %t = track number      %n = track title             %y = release year
#   %N = disc number        %M = total discs
#
# We keep TWO template pairs and pick per rip (see ui/rip_controls):
#
#   * Known disc  → the clean "Artist/Album/## - Title" layout (the
#     `naming.DEFAULT_PRESET`; matches Picard/beets/Plex). The old v2 default
#     repeated the album and artist in every filename and put the full date
#     on the end — replaced in v3 (see migrate(); a real-user report, 0.4.4).
#     The Settings dialog offers more presets (year-in-folder, compilation)
#     and a live preview — see `naming.py`. Multi-disc folders aren't expressible
#     (cyanrip's scheme has no disc-number token).
#   * Unknown disc → literal "Unknown Artist/Unknown Album/## - Track NN".
#     We deliberately do NOT use %d here: for a disc MusicBrainz can't
#     identify, whipper fills %d with the raw disc-ID hash, so a literal
#     path keeps unknown rips tidy (and matches the placeholder tags).
_DEFAULT_TRACK_TEMPLATE: str = "%A/%d/%t - %n"
_DEFAULT_DISC_TEMPLATE: str = "%A/%d/%d"
_DEFAULT_TRACK_TEMPLATE_UNKNOWN: str = "Unknown Artist/Unknown Album/%t - Track %t"
_DEFAULT_DISC_TEMPLATE_UNKNOWN: str = "Unknown Artist/Unknown Album/Unknown Album"

# The v1 defaults, kept so the v1→v2 migration can recognise an
# untouched template and upgrade it without clobbering a custom one.
_V1_TRACK_TEMPLATE: str = "%A - %d/%t. %a - %n"
_V1_DISC_TEMPLATE: str = "%A - %d/%A - %d"

# The v2 defaults (the cluttered "## - Title - Album - Artist - Year" layout),
# kept so the v2→v3 migration can recognise an untouched template and upgrade
# it to the clean v3 default without clobbering a hand-edited one.
_V2_TRACK_TEMPLATE: str = "%A/%d/%t - %n - %d - %A - %y"
_V2_DISC_TEMPLATE: str = "%A/%d/%d"

# The v3 "year in the folder" preset templates, which used %y (the FULL release
# date, e.g. "1995-09-12"). v4 introduced the year-only %Y token and switched
# these presets to it, so the v3→v4 migration carries an untouched year-preset
# config forward to the cleaner 4-digit-year form. Keyed old→new; a hand-edited
# template matches nothing here and is left untouched. Order pairs each track
# template with its disc template so both migrate together.
_V3_TO_V4_TEMPLATES: dict[str, str] = {
    "%A/%d (%y)/%t - %n": "%A/%d (%Y)/%t - %n",  # "Artist / Album (Year) / …"
    "%A/%d (%y)/%d": "%A/%d (%Y)/%d",
    "%A/%y - %d/%t - %n": "%A/%Y - %d/%t - %n",  # "Artist / Year - Album / …"
    "%A/%y - %d/%d": "%A/%Y - %d/%d",
}

log = logging.getLogger(__name__)


@dataclass
class Config:
    """The persisted user configuration. Attributes mirror TOML keys 1:1."""

    # --- Output locations ---
    output_dir: str = field(default_factory=lambda: str(_DEFAULT_OUTPUT_DIR))
    working_dir: str = field(default_factory=lambda: str(_DEFAULT_WORKING_DIR))

    # --- Whipper rip templates ---
    # Used for discs MusicBrainz identifies (rich, tag-driven names).
    track_template: str = _DEFAULT_TRACK_TEMPLATE
    disc_template: str = _DEFAULT_DISC_TEMPLATE
    # Used for the --unknown rip (literal "Unknown Album" path, no hash).
    track_template_unknown: str = _DEFAULT_TRACK_TEMPLATE_UNKNOWN
    disc_template_unknown: str = _DEFAULT_DISC_TEMPLATE_UNKNOWN

    # --- Tool paths (overrides for the dependency subsystem) ---
    # User can re-point this in Settings if the default is wrong.
    metaflac_path: str = "metaflac"  # relies on PATH by default

    # --- Rip parameters ---
    # read_offset is in samples, signed. cyanrip (the sole backend) is fed this
    # value as `-s` for every rip when override_read_offset is on; it does not
    # read any external config file.
    read_offset: int = 0
    # When True, the GUI applies `read_offset` to each rip (cyanrip's `-s`).
    # The drive-setup wizard turns this on when it detects or you enter an
    # offset; legacy whipper.conf values are still read for the trust display
    # (offset_config.py) but cyanrip is driven from this value.
    override_read_offset: bool = False

    # --- UI toggles ---
    auto_launch_picard: bool = False

    # Eject the disc automatically when a rip finishes successfully. Off by
    # default — some users rip several discs in a row from the same tray and
    # an auto-eject would be in the way. Purely a convenience; the manual
    # Eject button works regardless of this setting.
    auto_eject_after_rip: bool = False

    # Set once we've auto-offered the drive-setup wizard on first run (when no
    # read offset was configured). Keeps the offer to a single, dismissible
    # prompt — afterwards the user runs it from Tools → Set up drive…. Pure UI
    # bookkeeping, not a rip parameter.
    drive_setup_prompted: bool = False

    # Set once we've auto-offered the host-setup wizard on first run (when the
    # whipper binary isn't present — the container stack isn't installed yet).
    # Same one-time, dismissible model as drive_setup_prompted; afterwards it
    # lives on Tools → Set up Platterpus….
    host_setup_prompted: bool = False

    # Set once we've offered (on first AppImage run) to add Platterpus to the
    # applications menu. One-time + dismissible; no-op on source/pipx installs.
    # NOTE (2026-06-10): no longer consulted by the offer logic — it suppressed
    # the offer FOREVER, so a freshly downloaded update never re-offered its
    # menu entry (real-user report). Kept so old configs load cleanly.
    appimage_integration_prompted: bool = False

    # The exact AppImage path the user declined to integrate ("" = never
    # declined). Replaces the boolean above for offer decisions: declining
    # silences the offer for THAT file only, so a new download/version offers
    # again — exactly the update case where re-offering is wanted.
    integration_declined_path: str = ""

    # Debug logging: when True, the log file at ~/.local/share/platterpus/
    # log.txt records verbose DEBUG detail (every probe, subprocess argv,
    # parser step) instead of the default INFO. Off by default — a tester
    # turns it on in Settings to capture a full log for a bug report, then
    # reproduces the issue. Applied at startup and immediately on toggle.
    debug_logging: bool = False

    # --- EAC bit-perfect parity gaps (KDD-13) ---
    #
    # Cover art: empty string means "don't fetch art". We default to "embed"
    # for parity with EAC, which embeds by default. With cyanrip the GUI
    # fetches the front cover from the Cover Art Archive after the rip and
    # embeds it (cyanrip itself is run offline).
    cover_art: str = "embed"
    # Rip attempts before giving up on a track (cyanrip's `-r`).
    max_retries: int = 5

    # --- Marginal-disc convergence (cyanrip -Z N, EAC-parity item 1) ---
    # cyanrip's `-Z <int>`: "rip tracks until their checksums match <int>
    # number of times" — for damaged/marginal discs whose first read is a
    # near-miss against the AccurateRip consensus (the Track-3-class gap in
    # docs/eac-parity-investigation.md). It re-rips a track until N reads
    # agree, so transient read errors converge to the bit-perfect result.
    # 0 = OFF (don't pass -Z); the normal secure path (paranoia + retries)
    # is enough for a clean disc and this only costs time on a good one.
    # 2 is the useful floor when enabled (two agreeing reads). **cyanrip
    # ONLY** — whipper has no equivalent flag, so the backend ignores it and
    # Settings greys the control out for whipper (same pattern as the
    # FLAC re-compress / verify toggles).
    secure_rerip_matches: int = 0

    # --- CTDB verification (KDD-14 Phase 1) ---
    # After a successful rip, verify the result against the CUETools Database
    # (a second, TOC-keyed verification path alongside AccurateRip). Off by
    # default: it's a network call, and — until the audio-CRC algorithm is
    # confirmed bit-exact on real hardware (KDD-16, crc.CRC_VALIDATED) — a
    # match is only "experimental" and is labelled as such in the UI. The
    # verify fails *safe*: a wrong CRC can only ever under-claim (NO_MATCH),
    # never fabricate a "verified".
    # On by default (0.4.5): the maintainer's bar is "verification is paramount
    # for every format", so a fresh install runs the full verification suite
    # (AccurateRip + CTDB + FLAC-integrity) on the master before any transcode.
    # The cost is a network lookup + a FLAC decode per rip; it fails safe and
    # off-thread, and the user can still turn it off. (An existing config keeps
    # whatever value it saved — defaults only fill an absent field.)
    ctdb_verify_after_rip: bool = True

    # --- FLAC encode-verify ---
    # After a successful rip, run `flac --test` on each output FLAC to confirm it
    # decodes back to its stored MD5 (catches encode/disk corruption). On by
    # default. whipper already does this during the rip (`flac --verify`), so
    # this only actually runs for a backend that doesn't self-verify (cyanrip);
    # the Settings widget greys it out for whipper. Best-effort, off the GUI
    # thread, surfaces only a one-line outcome (loud on failure).
    verify_flac_after_rip: bool = True

    # --- FLAC re-compression ---
    # After a successful rip, re-encode each output FLAC at the maximum level
    # (`flac -8`, with `--verify`) to shrink the files. Opt-in, OFF by default:
    # it's lossless and provably bit-identical, but it costs CPU/time and the
    # space saved over whipper's default `-5` is modest. Only meaningful for a
    # backend that *doesn't* already max compression — cyanrip encodes at the
    # ceiling already, so the GUI skips it there (and Settings greys it out).
    # Best-effort, off the GUI thread; each file is swapped in atomically so a
    # failure leaves the original untouched.
    recompress_flac_after_rip: bool = False

    # --- Output format (Settings → Output format) ---
    # Which audio format the rip delivers. "flac" (default, the lossless
    # archival master) | "wavpack" (.wv, lossless, with tags) | "mp3" (lossy,
    # best-practice VBR, with tags + cover) | "wav" (raw PCM, no tags/art).
    # Both backends always rip to FLAC; for a non-FLAC choice the GUI keeps that
    # FLAC as the master and derives the chosen format with a post-rip ffmpeg
    # transcode (adapters/transcode.py). See docs/mp3-wav-support.md.
    output_format: str = "flac"
    # MP3 VBR quality for libmp3lame when output_format == "mp3": ffmpeg
    # `-q:a N` == lame `-V N` (0 = best/~245kbps, 9 = smallest). Fixed at 0
    # (best-practice VBR) for now — the field exists for a future Settings
    # exposure. The LAME `-q4` noise-shaping bug is CBR/ABR-only, so VBR is
    # unaffected (docs/mp3-wav-support.md §3). Ignored unless MP3 is selected.
    mp3_vbr_quality: int = 0

    # --- Goal preset (Settings → Goal) ---
    # Which goal preset the rip settings correspond to: "fast_verified"
    # (default; == the shipping field defaults), "archival", "portable", or
    # "custom" (hand-tuned). It's a convenience anchor — the rip reads the
    # individual fields, not this. See goal_presets.py.
    rip_goal: str = "fast_verified"

    # --- Schema bookkeeping ---
    schema_version: int = SCHEMA_VERSION


def load() -> Config:
    """Return the current config, creating it with defaults if missing.

    On first run this writes the defaults file before returning so the
    user has something to edit in Settings.
    """
    if not CONFIG_PATH.exists():
        log.info("config file missing; creating defaults at %s", CONFIG_PATH)
        cfg = Config()
        save(cfg)
        return cfg

    with CONFIG_PATH.open("rb") as f:
        raw = tomllib.load(f)

    raw = _migrate(raw)

    # Drop unknown keys so an older binary reading a newer file doesn't
    # crash. Log so we know it happened — silent drops would be worse.
    known = {f.name for f in Config.__dataclass_fields__.values()}
    unknown = set(raw) - known
    if unknown:
        log.warning("unknown config keys ignored: %s", sorted(unknown))
    filtered = {k: v for k, v in raw.items() if k in known}

    return Config(**filtered)


def save(cfg: Config) -> None:
    """Atomically write `cfg` to CONFIG_PATH.

    Atomicity matters: a SIGKILL or power loss between `open` and
    `close` of the real file would otherwise leave a half-written TOML.
    We write to a sibling temp file and rename — `os.replace` is atomic
    on POSIX.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    tmp = CONFIG_PATH.with_suffix(".tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)
    os.replace(tmp, CONFIG_PATH)
    log.debug("config saved to %s", CONFIG_PATH)


def _migrate(raw: dict) -> dict:
    """Apply schema migrations in-place, returning the upgraded dict.

    Each step reads `raw["schema_version"]`, transforms `raw`, and bumps
    the version. Keep individual steps small so they're easy to review.
    """
    version = int(raw.get("schema_version", 1))

    if version < 2:
        # v1→v2: the default path templates changed to an Artist/Album
        # folder layout with "## - Title" filenames. Only rewrite a
        # template the user never customized (still the v1 default) so we
        # never clobber a hand-edited one. A template that's absent stays
        # absent — load() will fall back to the v2 default.
        # Upgrade to the *v2* default here; the v2→v3 step below then carries it
        # forward to the current clean default. (Stepwise so each migration is
        # self-consistent and an untouched template rides the whole chain.)
        if raw.get("track_template") == _V1_TRACK_TEMPLATE:
            raw["track_template"] = _V2_TRACK_TEMPLATE
        if raw.get("disc_template") == _V1_DISC_TEMPLATE:
            raw["disc_template"] = _V2_DISC_TEMPLATE
        raw["schema_version"] = 2
        version = 2

    if version < 3:
        # v2→v3: the cluttered default template ("## - Title - Album - Artist -
        # Year", which repeated the album/artist and tacked the full date on the
        # end) was replaced by the clean "Artist/Album/## - Title". Only upgrade a
        # template the user never customized (still the exact v2 default) so a
        # hand-edited one is never clobbered. Absent stays absent → load() falls
        # back to the v3 default.
        if raw.get("track_template") == _V2_TRACK_TEMPLATE:
            raw["track_template"] = _DEFAULT_TRACK_TEMPLATE
        if raw.get("disc_template") == _V2_DISC_TEMPLATE:
            raw["disc_template"] = _DEFAULT_DISC_TEMPLATE
        raw["schema_version"] = 3
        version = 3

    if version < 4:
        # v3→v4: the year-in-folder presets switched from %y (the full release
        # date) to the new year-only %Y token. Upgrade a config still holding an
        # untouched v3 year-preset template to its %Y form so "Album (1995-09-12)"
        # becomes "Album (1995)". A hand-edited template matches nothing in the
        # map and is left alone. Only the "known disc" templates carry a year
        # preset; the unknown-disc templates never do.
        for field_name in ("track_template", "disc_template"):
            upgraded = _V3_TO_V4_TEMPLATES.get(raw.get(field_name))
            if upgraded is not None:
                raw[field_name] = upgraded
        raw["schema_version"] = 4
        version = 4

    if version == SCHEMA_VERSION:
        return raw

    # Unknown future versions get a warning and current-version
    # treatment — better than crashing the GUI.
    log.warning("unknown schema_version=%s; treating as v%s", version, SCHEMA_VERSION)
    return raw
