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
import shutil
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

from platterpus.paths import (
    CONFIG_DIR,
    CONFIG_PATH,
    LEGACY_CONFIG_DIR,
    WHIPPER_BINARY_DEFAULT,
)

# Bump this when the schema grows new keys or changes defaults that we
# want to migrate. Migration logic lives in _migrate() below.
SCHEMA_VERSION: int = 2

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
#   * Known disc  → rich tags: "Artist/Album/## - Title - Album - Artist - Year".
#     A disc with no year leaves a trailing " - " (whipper templates are
#     flat — they can't conditionally drop an empty field). Multi-disc
#     sets: add "/%N" to the folder portion yourself.
#   * Unknown disc → literal "Unknown Artist/Unknown Album/## - Track NN".
#     We deliberately do NOT use %d here: for a disc MusicBrainz can't
#     identify, whipper fills %d with the raw disc-ID hash, so a literal
#     path keeps unknown rips tidy (and matches the placeholder tags).
_DEFAULT_TRACK_TEMPLATE: str = "%A/%d/%t - %n - %d - %A - %y"
_DEFAULT_DISC_TEMPLATE: str = "%A/%d/%d"
_DEFAULT_TRACK_TEMPLATE_UNKNOWN: str = "Unknown Artist/Unknown Album/%t - Track %t"
_DEFAULT_DISC_TEMPLATE_UNKNOWN: str = "Unknown Artist/Unknown Album/Unknown Album"

# The v1 defaults, kept so the v1→v2 migration can recognise an
# untouched template and upgrade it without clobbering a custom one.
_V1_TRACK_TEMPLATE: str = "%A - %d/%t. %a - %n"
_V1_DISC_TEMPLATE: str = "%A - %d/%A - %d"

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
    # User can re-point these in Settings if the defaults are wrong.
    whipper_path: str = field(default_factory=lambda: str(WHIPPER_BINARY_DEFAULT))
    metaflac_path: str = "metaflac"  # relies on PATH by default

    # Which ripping backend to drive. "whipper" (default) or "cyanrip" — the
    # actively-maintained successor whose paranoia avoids whipper's >587
    # read-offset bug (KDD-18). Selectable here so swapping is a config change,
    # not a code change; the GUI exposes it once the cyanrip impl is complete.
    ripper_backend: str = "whipper"

    # --- Rip parameters ---
    # Informational only; whipper.conf is authoritative per the brief.
    # Surfaced here so Settings can display what the GUI thinks is in
    # effect. read_offset is in samples, signed.
    read_offset: int = 0
    # When True, pass `--offset <read_offset>` to each rip, overriding
    # whatever whipper.conf holds. Lets the user set the offset from the
    # GUI without editing whipper.conf. Off by default — the drive-setup
    # wizard (which writes whipper.conf) is the primary path.
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

    # Continue ripping a CD-R (burned disc). Whipper refuses by default
    # ("inserted disc seems to be a CD-R, --cdr not passed") because in an
    # archival workflow a burned disc is usually an accident. Off by
    # default to match that safety stance; the user opts in per the EAC
    # parity audit (KDD-13). When True we pass whipper's `--cdr` flag.
    continue_on_cdr: bool = False

    # --- EAC bit-perfect parity gaps (KDD-13) ---
    # Each maps to a whipper `cd rip` flag we now surface in Settings.
    #
    # Cover art: whipper's `-C/--cover-art {file,embed,complete}`. Empty
    # string means "don't pass the flag" (whipper's own default: no art).
    # We default to "embed" for parity with EAC, which embeds by default —
    # note this makes a rip fetch art over the network (best-effort; a
    # disc MusicBrainz can't identify just gets none).
    cover_art: str = "embed"
    # `-x/--force-overread`: read into the lead-out to capture the last
    # samples. Off by default (matches EAC's own recommendation).
    force_overread: bool = False
    # `-r/--max-retries N`: rip attempts before giving up on a track.
    # 5 is whipper's own default.
    max_retries: int = 5
    # `-k/--keep-going`: rip remaining tracks instead of aborting when one
    # track fails. Off by default — a failure should be surfaced, not
    # silently skipped, in an archival workflow.
    keep_going: bool = False

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
    ctdb_verify_after_rip: bool = False

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


def migrate_legacy_config_dir() -> bool:
    """Adopt a pre-rename settings dir (~/.config/whipper-gui) after the
    rename to Platterpus, so existing users keep their settings.

    One-time and conservative: only copies when the NEW dir
    (``~/.config/platterpus``) doesn't exist yet AND the legacy one does — so it
    never clobbers a fresh Platterpus config and never runs twice. The legacy
    dir is *copied*, not moved, so an older build (or the user) still finds it.
    Best-effort: any error is logged and treated as "no migration". Returns
    True only when settings were actually carried over.
    """
    try:
        if CONFIG_DIR.exists() or not LEGACY_CONFIG_DIR.is_dir():
            return False
        shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR)
        log.info(
            "migrated settings from %s to %s (post-rename)",
            LEGACY_CONFIG_DIR,
            CONFIG_DIR,
        )
        return True
    except OSError:
        log.warning("legacy config migration failed", exc_info=True)
        return False


def load() -> Config:
    """Return the current config, creating it with defaults if missing.

    On first run this writes the defaults file before returning so the
    user has something to edit in Settings.
    """
    # Before anything reads CONFIG_PATH, adopt a pre-rename ~/.config/whipper-gui
    # if present (no-op once ~/.config/platterpus exists).
    migrate_legacy_config_dir()

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
        if raw.get("track_template") == _V1_TRACK_TEMPLATE:
            raw["track_template"] = _DEFAULT_TRACK_TEMPLATE
        if raw.get("disc_template") == _V1_DISC_TEMPLATE:
            raw["disc_template"] = _DEFAULT_DISC_TEMPLATE
        raw["schema_version"] = 2
        version = 2

    if version == 2:
        return raw

    # Unknown future versions get a warning and current-version
    # treatment — better than crashing the GUI.
    log.warning("unknown schema_version=%s; treating as v%s", version, SCHEMA_VERSION)
    return raw
