"""cyanrip backend — a second ripping backend behind the WhipperBackend ABC.

Why (KDD-18, docs/archive/ecosystem-audit-2026-06.md): whipper is stalled (last release
2021) and its cd-paranoia has a real bug at read offsets > 587 — exactly the
range the tested Pioneer BDR-209D needs (+667), which fails tracks on hardware.
**cyanrip** is actively maintained (C/FFmpeg), applies the offset itself via
``-s`` with its own paranoia (no >587 bug), and does AccurateRip v1/v2 + EAC
CRC. We slot it behind the existing ABC so it's a config-selectable backend and
ripping still routes through a host-exported binary (Critical Rule #3).

**Implemented:** the rip argv builder, version, find-offset, a backend-
independent drive scan, and `disc_info` via ``-I -N`` (parsed by
`parsers/cyanrip_info.py` — the DiscID/CDDB ID are computed locally from the
TOC, so identification needs no network). Still tracked in the ecosystem
audit: whipper-only rip params (release_id, track/disc templates, cdr,
keep_going, force_overread) don't map 1:1 to cyanrip and are documented, not
forced.

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

from whipper_gui.adapters.whipper_backend import (
    RipHandle,
    RipMetadata,
    WhipperBackend,
    WhipperError,
)
from whipper_gui.parsers.cd_info import DiscInfo
from whipper_gui.parsers.cyanrip_info import parse_cyanrip_info
from whipper_gui.parsers.drive_list import DriveDescriptor

log = logging.getLogger(__name__)

_INFO_TIMEOUT_S: float = 120.0


class CyanripImpl(WhipperBackend):
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
        dir_part, _, file_part = track_template.rpartition("/")
        if dir_part:
            argv += ["-D", scheme_from_template(dir_part)]
        if file_part:
            argv += ["-F", scheme_from_template(file_part)]
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
        cdr: bool = False,
        cover_art: str = "",
        force_overread: bool = False,
        max_retries: int = 5,
        keep_going: bool = False,
        read_offset_override: int | None = None,
        metadata: RipMetadata | None = None,
    ) -> RipHandle:
        # disc_template is unused: cyanrip puts the log/cue in the -D folder
        # already (derived from track_template, which carries the same
        # directory part). cdr / keep_going / force_overread are whipper-isms
        # with no 1:1 cyanrip flag — cyanrip rips CD-Rs without a flag and
        # continues past bad tracks by design.
        del disc_template, cdr, force_overread, keep_going
        argv = self._build_rip_argv(
            drive,
            unknown=unknown,
            cover_art=cover_art,
            max_retries=max_retries,
            read_offset_override=read_offset_override,
            release_id=release_id,
            track_template=track_template,
            metadata=metadata,
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

    def find_offset(self, device: str) -> int:
        """Run cyanrip's own offset finder (``-f``) and parse the result."""
        args = ["-f"]
        if device:
            args += ["-d", device]
        out = self._run(args)
        match = re.search(r"offset[^\-0-9]*(?P<offset>-?\d+)", out, re.IGNORECASE)
        if match:
            return int(match.group("offset"))
        raise WhipperError(
            "cyanrip could not detect the read offset. Insert a CD that's in "
            "the AccurateRip database and try again.",
            output=out,
        )

    def _run(self, args: list[str], timeout: float = _INFO_TIMEOUT_S) -> str:
        argv = [self._binary, *args]
        log.debug("cyanrip: %s", " ".join(argv))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise WhipperError(f"cyanrip binary not found at {self._binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise WhipperError(f"cyanrip timed out after {timeout:.0f}s") from exc
        return (proc.stdout or "") + (proc.stderr or "")


def _read_sysfs(path: Path) -> str:
    """Read a one-line sysfs attribute, stripped; "" if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


# --- Metadata feed (-a / -t) -------------------------------------------------


def _escape_meta_value(value: str) -> str:
    """Escape a tag value for cyanrip's ``key=value:key=value`` strings.

    cyanrip parses -a/-t with FFmpeg's ``av_dict_parse_string(.., "=", ":")``,
    whose tokenizer treats ``\\`` as an escape and ``'`` as a quote char —
    so backslash-escaping ``\\ : = '`` makes any title safe (e.g.
    "Live: At The Met").
    """
    out: list[str] = []
    for ch in value:
        if ch in "\\:='":
            out.append("\\")
        out.append(ch)
    return "".join(out)


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
    if release_id:
        album_pairs.append(f"musicbrainz_albumid={_escape_meta_value(release_id)}")
    if album_pairs:
        args += ["-a", ":".join(album_pairs)]
    for number, title, artist in meta.tracks:
        track_pairs: list[str] = []
        if title:
            track_pairs.append(f"title={_escape_meta_value(title)}")
        if artist:
            track_pairs.append(f"artist={_escape_meta_value(artist)}")
        if track_pairs:
            args += ["-t", f"{number}={':'.join(track_pairs)}"]
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


def scheme_from_template(template: str) -> str:
    """Translate a whipper path template into a cyanrip -D/-F scheme.

    Known %x tokens map per _TOKEN_MAP; an unrecognized %x is kept
    literally (visible in the filename beats silently vanishing). Literal
    braces are flattened to parentheses because ``{...}`` is cyanrip's own
    substitution syntax — a stray brace would otherwise be parsed as a
    (missing) tag key.
    """
    out: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "%" and i + 1 < len(template):
            token = template[i : i + 2]
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
