"""Parse whipper's rip `.log` file into a RipLog dataclass.

Format verified against a real whipper 0.7.4+ log from whipper-team's
own test fixtures (tests/fixtures/rip_log_real_whipper_0_7.log).

Structure (YAML-style indented mapping):

    Log created by: whipper X.Y.Z (...)
    Log creation date: YYYY-MM-DDThh:mm:ssZ

    Ripping phase information:
      Drive: <vendor> <model> (revision <rev>)
      Extraction engine: ...
      Defeat audio cache: true|false
      Read offset correction: <int>
      Overread into lead-out: true|false
      Gap detection: ...
      CD-R detected: true|false

    CD metadata:
      Release:
        Artist: ...
        Title: ...
      CDDB Disc ID: ...
      MusicBrainz Disc ID: ...
      MusicBrainz lookup URL: ...

    TOC:
      1:
        Start: ...
        Length: ...
        Start sector: ...
        End sector: ...

    Tracks:
      1:
        Filename: <path>
        Peak level: 0.xxxxxx
        Pre-emphasis: <empty>|yes|no
        Extraction speed: N.N X
        Extraction quality: NN.NN %
        Test CRC: XXXXXXXX
        Copy CRC: XXXXXXXX
        AccurateRip v1:
          Result: Found, exact match | Track not present in AccurateRip database | ...
          Confidence: N
          Local CRC: XXXXXXXX
          Remote CRC: XXXXXXXX
        AccurateRip v2:
          (same fields)
        Status: Copy OK

    Conclusive status report:
      AccurateRip summary: ...
      Health status: ...
      EOF: End of status report

    SHA-256 hash: <hex>

We don't pull in a YAML parser — the format is regular enough that a
state-machine with named-group regexes handles it cleanly. Per
CLAUDE.md, the parser degrades gracefully on unexpected input rather
than crashing.

The captured `RippingInfo` block intentionally mirrors what EAC's log
captures (drive, read offset, cache defeat, gap detection) so the GUI
can surface an archival summary comparable to EAC's. See
docs/log-format-comparison.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RippingInfo:
    """Drive and rip-engine settings captured at the time of rip.

    Mirrors EAC's "Used drive" / "Read offset correction" / "Defeat
    audio cache" archival block — the fields most relevant to whether
    a rip is bit-perfect and reproducible.
    """

    drive: str = ""
    extraction_engine: str = ""
    defeat_audio_cache: bool | None = None
    read_offset_correction: int | None = None
    overread_lead_out: bool | None = None
    gap_detection: str = ""
    cd_r_detected: bool | None = None


@dataclass(frozen=True)
class AccurateRipResult:
    """One of the two AccurateRip checks per track (v1 or v2)."""

    version: int
    result: str = ""              # "Found, exact match" / etc.
    confidence: int | None = None
    local_crc: str | None = None  # uppercase hex
    remote_crc: str | None = None # uppercase hex


@dataclass(frozen=True)
class TrackResult:
    """One track's results from the rip log."""

    number: int
    filename: str = ""
    peak_level: float | None = None
    pre_emphasis: bool | None = None
    extraction_speed: float | None = None     # in X (drive multiplier)
    extraction_quality: float | None = None   # percentage 0..100
    test_crc: str = ""
    copy_crc: str = ""
    status: str = ""
    accuraterip_v1: AccurateRipResult | None = None
    accuraterip_v2: AccurateRipResult | None = None


@dataclass(frozen=True)
class RipLog:
    """The full parsed log."""

    log_creator: str = ""
    creation_date: str = ""
    ripping_info: RippingInfo = field(default_factory=RippingInfo)
    tracks: tuple[TrackResult, ...] = ()
    accuraterip_summary: str = ""
    health_status: str = ""
    sha256_hash: str = ""


# --- Line-level regexes -----------------------------------------------------

# Top-level section line, e.g. "Tracks:" or "Conclusive status report:".
_TOP_LEVEL_SECTION = re.compile(r"^(?P<name>\w[\w\s]*?):\s*$")

# A track header is JUST a number and a colon, indented. The colon must
# be followed by nothing but whitespace — that's how it differs from a
# normal field line.
_TRACK_HEADER = re.compile(r"^\s+(?P<number>\d+):\s*$")

# AccurateRip v1/v2 sub-section header. Same "nothing after the colon"
# discipline.
_AR_HEADER = re.compile(r"^\s+AccurateRip v(?P<version>\d+):\s*$")

# A general "Key: value" line. `value` may be empty (some fields like
# Pre-emphasis are emitted with an empty value).
_FIELD = re.compile(
    r"^(?P<indent>\s+)(?P<key>[\w][\w\s\-]*?):\s*(?P<value>.*?)\s*$"
)

_SPEED = re.compile(r"^(?P<value>-?\d+(?:\.\d+)?)\s*X\s*$")
_QUALITY = re.compile(r"^(?P<value>-?\d+(?:\.\d+)?)\s*%\s*$")

# Mapping from section name (as it appears in the log) to internal state.
_SECTION_NAMES: dict[str, str] = {
    "Ripping phase information": "ripping",
    "CD metadata": "metadata",
    "TOC": "toc",
    "Tracks": "tracks",
    "Conclusive status report": "status",
}


def parse_rip_log(text: str) -> RipLog:
    """Parse the full text of a whipper `.log` file.

    Tolerates absent fields and unexpected lines. Returns a RipLog with
    whatever could be extracted; never raises on malformed input.
    """
    log_creator = ""
    creation_date = ""
    sha256 = ""

    ripping_data: dict[str, str] = {}
    status_data: dict[str, str] = {}

    tracks: list[TrackResult] = []
    current_track: _MutableTrack | None = None
    current_ar: int | None = None

    section: str | None = None  # one of _SECTION_NAMES values, or None.

    for line in text.splitlines():
        # Top-of-file metadata: simple "Key: value" lines at column 0.
        if line.startswith("Log created by:"):
            log_creator = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Log creation date:"):
            creation_date = line.split(":", 1)[1].strip()
            continue
        if line.startswith("SHA-256 hash:"):
            sha256 = line.split(":", 1)[1].strip()
            continue

        # Top-level section header switches state. Note: track headers
        # like "  1:" are indented and won't match this column-0 regex.
        top = _TOP_LEVEL_SECTION.match(line)
        if top and not line.startswith(" "):
            name = top.group("name").strip()
            # Flush in-flight track when leaving the tracks section.
            if section == "tracks" and current_track is not None:
                tracks.append(current_track.build())
                current_track = None
            section = _SECTION_NAMES.get(name)
            current_ar = None
            continue

        if section == "ripping":
            field_match = _FIELD.match(line)
            if field_match:
                ripping_data[field_match.group("key").strip()] = (
                    field_match.group("value").strip()
                )
            continue

        if section == "status":
            field_match = _FIELD.match(line)
            if field_match:
                status_data[field_match.group("key").strip()] = (
                    field_match.group("value").strip()
                )
            continue

        if section == "tracks":
            # Track header is just "  N:" with nothing after.
            header = _TRACK_HEADER.match(line)
            if header:
                if current_track is not None:
                    tracks.append(current_track.build())
                current_track = _MutableTrack(
                    number=int(header.group("number"))
                )
                current_ar = None
                continue

            ar = _AR_HEADER.match(line)
            if ar and current_track is not None:
                current_ar = int(ar.group("version"))
                current_track.ar[current_ar] = {}
                continue

            field_match = _FIELD.match(line)
            if field_match and current_track is not None:
                key = field_match.group("key").strip()
                value = field_match.group("value").strip()
                indent = len(field_match.group("indent"))
                # AR sub-fields are indented further than track-level
                # ones (6 spaces vs 4). Once we see a 4-indent field
                # after AR fields, we've left the AR block.
                if current_ar is not None and indent >= 6:
                    current_track.ar[current_ar][key] = value
                else:
                    current_track.fields[key] = value
                    current_ar = None
                continue

        # CD metadata and TOC sections are not used by the GUI; ignore.

    # Flush a track that wasn't followed by a status section.
    if current_track is not None:
        tracks.append(current_track.build())

    return RipLog(
        log_creator=log_creator,
        creation_date=creation_date,
        ripping_info=_build_ripping_info(ripping_data),
        tracks=tuple(tracks),
        accuraterip_summary=status_data.get("AccurateRip summary", ""),
        health_status=status_data.get("Health status", ""),
        sha256_hash=sha256,
    )


# --- In-flight track accumulator -------------------------------------------


class _MutableTrack:
    """Mutable scratch struct used while a track section is being parsed.

    Lives only inside parse_rip_log(); the final immutable record is
    produced by .build() at flush time.
    """

    def __init__(self, number: int) -> None:
        self.number: int = number
        self.fields: dict[str, str] = {}
        # ar[version] -> {Result, Confidence, Local CRC, Remote CRC}
        self.ar: dict[int, dict[str, str]] = {}

    def build(self) -> TrackResult:
        return TrackResult(
            number=self.number,
            filename=self.fields.get("Filename", ""),
            peak_level=_parse_float(self.fields.get("Peak level")),
            pre_emphasis=_parse_yes_no(self.fields.get("Pre-emphasis")),
            extraction_speed=_parse_with_pattern(
                self.fields.get("Extraction speed"), _SPEED
            ),
            extraction_quality=_parse_with_pattern(
                self.fields.get("Extraction quality"), _QUALITY
            ),
            test_crc=self.fields.get("Test CRC", ""),
            copy_crc=self.fields.get("Copy CRC", ""),
            status=self.fields.get("Status", ""),
            accuraterip_v1=_build_ar(1, self.ar.get(1)),
            accuraterip_v2=_build_ar(2, self.ar.get(2)),
        )


def _build_ar(
    version: int, raw: dict[str, str] | None
) -> AccurateRipResult | None:
    if raw is None:
        return None
    return AccurateRipResult(
        version=version,
        result=raw.get("Result", ""),
        confidence=_parse_int(raw.get("Confidence")),
        local_crc=raw.get("Local CRC") or None,
        remote_crc=raw.get("Remote CRC") or None,
    )


def _build_ripping_info(data: dict[str, str]) -> RippingInfo:
    return RippingInfo(
        drive=data.get("Drive", ""),
        extraction_engine=data.get("Extraction engine", ""),
        defeat_audio_cache=_parse_yes_no(data.get("Defeat audio cache")),
        read_offset_correction=_parse_int(data.get("Read offset correction")),
        overread_lead_out=_parse_yes_no(data.get("Overread into lead-out")),
        gap_detection=data.get("Gap detection", ""),
        cd_r_detected=_parse_yes_no(data.get("CD-R detected")),
    )


# --- Tiny value parsers -----------------------------------------------------


def _parse_int(s: str | None) -> int | None:
    if s is None or not s.strip():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_float(s: str | None) -> float | None:
    if s is None or not s.strip():
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_yes_no(s: str | None) -> bool | None:
    """Recognize Yes/No, True/False, true/false. Empty/unknown → None."""
    if s is None:
        return None
    normalized = s.strip().lower()
    if normalized in ("yes", "true"):
        return True
    if normalized in ("no", "false"):
        return False
    return None


def _parse_with_pattern(
    s: str | None, pattern: re.Pattern[str]
) -> float | None:
    """Extract the float `value` named-group from `pattern` applied to `s`."""
    if s is None:
        return None
    match = pattern.match(s.strip())
    if not match:
        return None
    return float(match.group("value"))
