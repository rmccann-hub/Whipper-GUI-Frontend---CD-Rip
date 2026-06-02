"""TOML config persistence for the GUI.

Reads `~/.config/whipper-gui/config.toml` via stdlib `tomllib`; writes
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

from whipper_gui.paths import CONFIG_DIR, CONFIG_PATH, WHIPPER_BINARY_DEFAULT

# Bump this when the schema grows new keys or changes defaults that we
# want to migrate. Migration logic lives in _migrate() below.
SCHEMA_VERSION: int = 2

# Computed once at import time. If the user's HOME changes mid-process,
# the GUI needs a restart — same as every other XDG-aware application.
_DEFAULT_OUTPUT_DIR: Path = Path.home() / "Music" / "rips"
_DEFAULT_WORKING_DIR: Path = Path.home() / ".cache" / "whipper-gui"

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
