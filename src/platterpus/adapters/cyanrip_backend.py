"""cyanrip backend — the ripping engine behind the RipBackend ABC.

Why (KDD-18, docs/ripper-engine-strategy.md): cyanrip is the sole backend
because it's better in essentially every situation. It's actively maintained
(C/FFmpeg), applies the read offset itself via ``-s`` with its own paranoia (so
it has *no* >587 cd-paranoia bug — exactly the range the tested Pioneer
BDR-209D needs at +667, which the old whipper backend failed on hardware), maxes
FLAC compression, offers ``-Z`` re-rip-until-match, and does AccurateRip v1/v2 +
EAC CRC. It sits behind the RipBackend ABC and ripping routes through a
host-exported binary (Critical Rule #3).

**Implemented:** the rip argv builder, version, find-offset, a backend-
independent drive scan, and `disc_info` via ``-I -N`` (parsed by
`parsers/cyanrip_info.py` — the DiscID/CDDB ID are computed locally from the
TOC, so identification needs no network).

cyanrip CLI (from its README): ``-d`` device, ``-s`` sample offset, ``-o``
codec list (flac default), ``-r`` retries, ``-N`` disable MusicBrainz
(always passed — the GUI feeds the tags instead), ``-a``/``-t`` album/track
metadata, ``-D``/``-F`` dir/file naming schemes (``{key}`` substitution),
``-G`` disable cover-art embed, ``-I`` info-only, ``-f`` find offset, ``-V``
version.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from platterpus.adapters.rip_backend import (
    RipBackend,
    RipError,
    RipHandle,
    RipMetadata,
    run_capture,
)
from platterpus.parsers.cd_info import DiscInfo
from platterpus.parsers.cyanrip_info import parse_cyanrip_info
from platterpus.parsers.drive_list import DriveDescriptor

log = logging.getLogger(__name__)

_INFO_TIMEOUT_S: float = 120.0


class CyanripImpl(RipBackend):
    """Ripping backend that drives the `cyanrip` CLI."""

    def __init__(
        self,
        binary_path: Path | str = "cyanrip",
        working_dir: Path | None = None,
        dev_root: Path = Path("/dev"),
        sys_block: Path = Path("/sys/block"),
    ) -> None:
        self._binary: str = str(binary_path)
        self._working_dir: Path | None = working_dir
        # Injectable so list_drives() is testable without a real /dev or /sys.
        self._dev_root: Path = dev_root
        self._sys_block: Path = sys_block

    # --- Drive listing (backend-independent: scan /dev + /sys) ---

    def list_drives(self) -> list[DriveDescriptor]:
        """Enumerate optical drives by scanning ``/dev/sr*`` and reading the
        vendor/model/revision from sysfs. cyanrip has no list-drives command,
        and this is generic enough to not need one."""
        drives: list[DriveDescriptor] = []
        try:
            nodes = sorted(self._dev_root.glob("sr*"))
        except OSError:
            return drives
        for node in nodes:
            info = self._sys_block / node.name / "device"
            drives.append(
                DriveDescriptor(
                    device=str(node),
                    vendor=_read_sysfs(info / "vendor"),
                    model=_read_sysfs(info / "model"),
                    release=_read_sysfs(info / "rev"),
                )
            )
        return drives

    # --- Disc info ---

    def disc_info(self, drive: str) -> DiscInfo:
        """Identify the inserted disc via `cyanrip -I` (info-only mode).

        `-N` disables cyanrip's own MusicBrainz lookup: the DiscID and CDDB
        ID are computed locally from the TOC (cyanrip's discid.c), so disc
        identification needs no network — the GUI then does its own
        host-side MusicBrainz lookup with the returned disc ID, exactly as
        it does for whipper (Critical Rule #5).

        A failed run (no disc, bad device) prints an error instead of the
        report; the parser degrades to an empty DiscInfo, which the GUI
        already treats as "unknown disc".
        """
        args = ["-I", "-N"]
        if drive:
            args += ["-d", drive]
        out = self._run(args)
        return parse_cyanrip_info(out)

    # --- Rip ---

    def _build_rip_argv(
        self,
        drive: str,
        *,
        unknown: bool,
        cover_art: str,
        max_retries: int,
        read_offset_override: int | None,
        release_id: str = "",
        track_template: str = "",
        metadata: RipMetadata | None = None,
        secure_rerip_matches: int = 0,
        read_speed: int = 0,
    ) -> list[str]:
        """Build the cyanrip rip argv (pure — unit-tested).

        Maps the backend-neutral params to cyanrip flags. cyanrip needs the
        read offset every run (it has no whipper.conf), so we always pass
        ``-s`` when we have one — its own paranoia applies it without the
        >587 cd-paranoia bug.

        **Metadata model (KDD-18, decided 2026-06-09):** MusicBrainz is
        ALWAYS disabled (``-N``) and the GUI's already-fetched tags are fed
        in via ``-a``/``-t`` instead. The GUI looked the release up
        host-side and let the user pick + edit it; feeding that in keeps
        the rip deterministic (no wrong-release re-lookup), needs no
        in-container network (the known flaky spot on the target machine),
        and honours Critical Rule #5 — cyanrip never does its own lookup.
        """
        argv: list[str] = [self._binary]
        if drive:
            argv += ["-d", drive]
        if read_offset_override is not None:
            argv += ["-s", str(read_offset_override)]
        argv += ["-o", "flac"]
        if max_retries:
            argv += ["-r", str(max_retries)]
        # `-Z N`: re-rip each track until N reads' checksums agree, for
        # marginal/damaged discs (EAC-parity item 1; see config.py). Only
        # passed when the user enabled it (> 0) — on a clean disc it just
        # burns time, so the default rip omits it entirely.
        if secure_rerip_matches > 0:
            argv += ["-Z", str(secure_rerip_matches)]
        # `-S <speed>`: cap the drive's read speed for this pass. Only passed when
        # a positive speed is requested (> 0); 0 means "let the drive pick" (its
        # maximum), so the default fast rip omits `-S` entirely. The adaptive
        # ladder (read_speed_ladder.py) feeds progressively slower values here on
        # a re-rip of a marginal disc. Graceful fallback: if the drive/libcdio-
        # paranoia stack ignores `-S` (hardware-gated — the BDR-209D is unverified
        # here), the pass simply reads at the drive's speed — no regression.
        if read_speed > 0:
            argv += ["-S", str(read_speed)]
        # Always -N: the GUI is the single metadata source (see docstring).
        # `unknown` just means the GUI has placeholder tags instead of MB
        # ones — either way cyanrip itself stays offline.
        del unknown
        argv.append("-N")
        argv += _metadata_args(metadata, release_id)
        # Naming: translate our whipper-style templates to cyanrip schemes.
        # The directory part (before the last "/") becomes -D, the filename
        # part -F — cyanrip renders {tokens} from the -a/-t tags above and
        # sanitizes tag values, so a "/" typed IN a template still nests
        # while a "/" inside an album title doesn't.
        # Platterpus-only %Y (year-only) has no cyanrip equivalent, so we
        # pre-expand it to the literal 4-char year here (from the release date
        # the GUI fetched) BEFORE the template reaches cyanrip — otherwise the
        # folder would literally contain "%Y". Empty when there's no year (the
        # token then vanishes, same as cyanrip's own {date} on a dateless disc).
        year = ((metadata.year if metadata else "") or "")[:4]
        dir_part, _, file_part = track_template.rpartition("/")
        if dir_part:
            argv += ["-D", scheme_from_template(dir_part, year=year)]
        if file_part:
            argv += ["-F", scheme_from_template(file_part, year=year)]
        if not cover_art:
            argv.append("-G")  # disable cover-art embedding
        return argv

    def rip(
        self,
        drive: str,
        release_id: str,
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
        cover_art: str = "",
        max_retries: int = 5,
        secure_rerip_matches: int = 0,
        read_offset_override: int | None = None,
        metadata: RipMetadata | None = None,
        read_speed: int = 0,
    ) -> RipHandle:
        # disc_template is unused: cyanrip puts the log/cue in the -D folder
        # already (derived from track_template, which carries the same
        # directory part). cyanrip rips CD-Rs without a flag and continues past
        # bad tracks by design.
        del disc_template
        argv = self._build_rip_argv(
            drive,
            unknown=unknown,
            cover_art=cover_art,
            max_retries=max_retries,
            read_offset_override=read_offset_override,
            release_id=release_id,
            track_template=track_template,
            metadata=metadata,
            secure_rerip_matches=secure_rerip_matches,
            read_speed=read_speed,
        )
        # cyanrip writes under the current directory (its -D/-F schemes are
        # relative), so run it from the output dir.
        output_dir.mkdir(parents=True, exist_ok=True)
        log.info("cyanrip rip starting: %s (cwd=%s)", " ".join(argv), output_dir)
        process = subprocess.Popen(
            argv,
            cwd=str(output_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        return RipHandle(process=process)

    # --- Misc ---

    def version(self) -> str:
        return self._run(["-V"]).strip()

    def produces_max_compression_flac(self) -> bool:
        # cyanrip drives libavcodec at the maximum FLAC compression level for
        # every rip (confirmed against its README and source), so a post-rip
        # `flac -8` re-compress would only burn CPU for no size gain. Tell the
        # GUI to skip it (and the Settings toggle to grey out) for this backend.
        return True

    def native_output_formats(self) -> frozenset[str]:
        # cyanrip CAN emit WAV/MP3/WavPack (among others) natively via `-o`. We
        # advertise just the formats the GUI offers; cyanrip supports more
        # (opus/alac/…), out of scope here. Reserved seam (KDD-22): the shipped
        # feature transcodes from FLAC for both backends instead (best-practice
        # VBR MP3 + FLAC master), so this isn't consumed for the rip today.
        return frozenset({"flac", "wav", "mp3", "wavpack"})

    def find_offset(self, device: str) -> int:
        """Run cyanrip's own offset finder (``-f``) and parse the result."""
        args = ["-f"]
        if device:
            args += ["-d", device]
        out = self._run(args)
        match = re.search(r"offset[^\-0-9]*(?P<offset>-?\d+)", out, re.IGNORECASE)
        if match:
            return int(match.group("offset"))
        raise RipError(
            "cyanrip could not detect the read offset. Insert a CD that's in "
            "the AccurateRip database and try again.",
            output=out,
        )

    def _run(self, args: list[str], timeout: float = _INFO_TIMEOUT_S) -> str:
        # cyanrip's info/version probes share whipper's run-capture core; only
        # the timeout (longer here), the tool name, and closing stdin differ.
        # cyanrip never needs the exit code (its parsers degrade on bad output),
        # so we keep just the combined stdout+stderr.
        _rc, combined = run_capture(
            "cyanrip", self._binary, args, timeout=timeout, stdin_devnull=True
        )
        return combined


def _read_sysfs(path: Path) -> str:
    """Read a one-line sysfs attribute, stripped; "" if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


# --- Metadata feed (-a / -t) -------------------------------------------------


# cyanrip turns ':' into this RATIO lookalike (U+2236) when it sanitizes a tag
# value for a path — so using it ourselves for the *value* keeps the folder name
# identical to what cyanrip would produce, just without tripping its parser.
_COLON_SUBSTITUTE: str = "∶"  # ∶


def _escape_meta_value(value: str) -> str:
    """Make a tag value safe for cyanrip's ``key=value:key=value`` strings.

    The real parser is FFmpeg's ``av_dict_parse_string(.., "=", ":")`` (which
    honors ``\\`` and ``'``), BUT cyanrip first runs the string through
    ``append_missing_keys()``, which splits on ``:`` with ``av_strtok`` —
    **naively, ignoring backslash and quotes** — and *injects* a spurious key
    (``album=``/``album_artist=``/``title=``/``artist=``) in front of any ``:``
    that lands inside a value. So a backslash-escaped colon does NOT survive:
    "Every Breath You Take: The Classics" came out as the folder
    "Every Breath You Take∶album_artist= The Classics" (real-user bug,
    2026-06-27, confirmed against cyanrip's source).

    Because a literal ``:`` can't be passed safely at all, substitute the
    visually-identical U+2236 (the same character cyanrip uses when sanitizing a
    colon for a path) — folders and the cyanrip-written tag stay clean, and the
    parser can't choke. The GUI restores the real ``:`` in the FLAC tags in a
    post-rip metaflac pass. Other tokenizer-special chars (``\\ = '``) still get
    a backslash, which av_get_token honors and ``append_missing_keys`` ignores
    (it only ever splits on ``:``).
    """
    out: list[str] = []
    for ch in value:
        if ch == ":":
            out.append(_COLON_SUBSTITUTE)
            continue
        if ch in "\\='":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def restore_substituted_colons(metaflac: object, flac_files: list[Path]) -> int:
    """Put the real ``:`` back into FLAC tags that `_escape_meta_value` had to
    write as the U+2236 lookalike for cyanrip's parser.

    cyanrip can't accept a literal ``:`` in ``-a``/``-t`` (its
    ``append_missing_keys`` splits on ``:`` before honoring escapes — see
    `_escape_meta_value`), so we feed it ``∶`` and the *written tags* come out
    with ``∶`` too. This reverses that in the tags afterward, so a player shows
    "Album: Subtitle" with a real colon. The folder name keeps cyanrip's own
    ``∶`` path-sanitization — a filesystem path is a separate concern.

    Reads each file and rewrites ONLY the tags that actually contain the
    substitute, so it's a no-op for the (common) colon-free album. Best-effort
    and never raises — it matches the rest of the post-rip pipeline. ``metaflac``
    is the :class:`~platterpus.adapters.metaflac.MetaflacAdapter` (duck-typed
    here so the backend doesn't hard-depend on it). Returns how many files were
    rewritten.
    """
    from platterpus.adapters.metaflac import MetaflacError

    changed = 0
    for path in flac_files:
        try:
            tags = metaflac.read_tags(path)
            fixes = {
                key: value.replace(_COLON_SUBSTITUTE, ":")
                for key, value in tags.items()
                if _COLON_SUBSTITUTE in value
            }
            if fixes:
                metaflac.write_tags(path, fixes)
                changed += 1
        except MetaflacError:
            log.warning("colon-restore: metaflac failed on %s", path)
        except Exception:  # noqa: BLE001 — a post-rip step must never crash the GUI
            log.exception("colon-restore: unexpected failure on %s", path)
    return changed


def _metadata_args(metadata: RipMetadata | None, release_id: str) -> list[str]:
    """Build the ``-a``/``-t`` arguments from the GUI's metadata.

    Empty fields are skipped; with no usable metadata at all this returns
    [] and cyanrip just rips untagged (the unknown-disc post-tagging path
    still applies). The release MBID is recorded as a plain tag so the rip
    is traceable to the release the user picked, like whipper's output.
    """
    args: list[str] = []
    album_pairs: list[str] = []
    meta = metadata or RipMetadata()
    if meta.album_title:
        album_pairs.append(f"album={_escape_meta_value(meta.album_title)}")
    if meta.album_artist:
        album_pairs.append(f"album_artist={_escape_meta_value(meta.album_artist)}")
    if meta.year:
        album_pairs.append(f"date={_escape_meta_value(meta.year)}")
    if meta.genre:
        album_pairs.append(f"genre={_escape_meta_value(meta.genre)}")
    # FFmpeg/Vorbis `disc` tag, only for multi-disc sets ("n/total"); a plain
    # single CD gets no disc tag (no point tagging 1/1).
    if meta.total_discs > 1:
        album_pairs.append(f"disc={meta.disc_number}/{meta.total_discs}")
    if release_id:
        album_pairs.append(f"musicbrainz_albumid={_escape_meta_value(release_id)}")
    if album_pairs:
        args += ["-a", ":".join(album_pairs)]
    for track in meta.tracks:
        track_pairs: list[str] = []
        if track.title:
            track_pairs.append(f"title={_escape_meta_value(track.title)}")
        if track.artist:
            track_pairs.append(f"artist={_escape_meta_value(track.artist)}")
        if track.isrc:
            track_pairs.append(f"isrc={_escape_meta_value(track.isrc)}")
        if track_pairs:
            args += ["-t", f"{track.number}={':'.join(track_pairs)}"]
    return args


# --- whipper template → cyanrip scheme ---------------------------------------

# whipper's path-template tokens → cyanrip's {metadata_key} scheme tokens.
# (cyanrip zero-pads {track} to the disc's width itself, matching %t.)
_TOKEN_MAP: dict[str, str] = {
    "%A": "{album_artist}",
    "%a": "{artist}",
    "%d": "{album}",
    "%n": "{title}",
    "%t": "{track}",
    "%y": "{date}",
    "%N": "{disc}",
}


def scheme_from_template(template: str, *, year: str = "") -> str:
    """Translate a whipper path template into a cyanrip -D/-F scheme.

    Known %x tokens map per _TOKEN_MAP; an unrecognized %x is kept
    literally (visible in the filename beats silently vanishing). Literal
    braces are flattened to parentheses because ``{...}`` is cyanrip's own
    substitution syntax — a stray brace would otherwise be parsed as a
    (missing) tag key.

    ``%Y`` is the one Platterpus-only token: cyanrip has no year-only field, so
    we substitute the literal 4-char ``year`` right here (the caller passes the
    release year). Doing the substitution inside this single scanner — rather
    than a blind ``str.replace("%Y", …)`` upstream — keeps ``%%`` escapes intact
    (``%%Y`` stays a literal percent + "Y", never a stray year).
    """
    out: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "%" and i + 1 < len(template):
            token = template[i : i + 2]
            if token == "%Y":
                # Literal year (e.g. "1995"); "" on a dateless disc → drops out.
                out.append(year)
                i += 2
                continue
            mapped = _TOKEN_MAP.get(token)
            if mapped is not None:
                out.append(mapped)
                i += 2
                continue
            log.warning("no cyanrip mapping for whipper token %r — kept", token)
            out.append(token)
            i += 2
            continue
        if ch == "{":
            out.append("(")
        elif ch == "}":
            out.append(")")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
