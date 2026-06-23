"""Adapter over MusicBrainz queries.

`MusicBrainzClient` is the ABC; `MusicBrainzNgsImpl` is the v1
concrete implementation backed by the `musicbrainzngs` Python library.
A future `RequestsJsonImpl` could implement the same ABC by hitting
MB's JSON REST endpoint directly with `requests` — see PLANNING.md §6
and CLAUDE.md Critical Rule #1.

The adapter exists for two reasons:
1. `musicbrainzngs` hasn't released since 2020-01-11 — wrapping it
   isolates the GUI from its eventual retirement.
2. The brief's Critical Rule #5 — every MusicBrainz lookup goes
   through this client; the GUI never lets whipper's interactive TTY
   prompt surface to the user.

The user-agent is mandatory at construction. MusicBrainz throttles
unidentified clients, and the rate-limit is applied per-client; an
unset agent makes us indistinguishable from other anonymous traffic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import musicbrainzngs

log = logging.getLogger(__name__)


class MusicBrainzQueryError(Exception):
    """Raised when a MusicBrainz query fails.

    Wraps `musicbrainzngs.WebServiceError` (and subclasses) so callers
    don't need to import the third-party exception type. The original
    exception is preserved on `.__cause__`.
    """


# --- Data types -------------------------------------------------------------


@dataclass(frozen=True)
class TocSignature:
    """Whipper-derived TOC for MusicBrainz lookup.

    `track_offsets` has length == last_track. Each value is the start
    sector of the corresponding track on the disc. MusicBrainz's TOC
    query string is `first+last+leadout+offset1+offset2+...`.
    """

    first_track: int
    last_track: int
    lead_out_sector: int
    track_offsets: tuple[int, ...]

    def to_query(self) -> str:
        """Render as the space-separated form MB expects."""
        return " ".join(
            [
                str(self.first_track),
                str(self.last_track),
                str(self.lead_out_sector),
                *(str(offset) for offset in self.track_offsets),
            ]
        )


@dataclass(frozen=True)
class TrackSummary:
    """One track on a release. Used inside `ReleaseDetail.tracks`."""

    number: int
    title: str
    artist_credit: str = ""
    length_ms: int | None = None
    isrc: str = ""  # recording ISRC, when MB has one (requires the "isrcs" include)


@dataclass(frozen=True)
class ReleaseSummary:
    """Compact release info for the picker dialog when MB returns >1 match."""

    mbid: str
    title: str
    artist_credit: str
    date: str = ""  # YYYY or YYYY-MM-DD per MB
    country: str = ""  # ISO-3166-1 alpha-2
    track_count: int | None = None
    label: str = ""
    catalog_number: str = ""
    medium_format: str = ""  # e.g. "CD"
    disambiguation: str = ""
    genre: str = ""  # top MB tag (requires the "tags" include); "" when none
    disc_number: int = 1  # this medium's position in the release
    total_discs: int = 1  # number of media in the release


@dataclass(frozen=True)
class ReleaseDetail:
    """Everything the track-editor pane needs from one release."""

    summary: ReleaseSummary
    tracks: tuple[TrackSummary, ...]


# --- Abstract base ----------------------------------------------------------


class MusicBrainzClient(ABC):
    """Abstract base for any MusicBrainz query backend."""

    @abstractmethod
    def releases_by_disc_id(self, disc_id: str) -> list[ReleaseSummary]:
        """Lookup releases by MB disc ID. Empty list when no match."""

    @abstractmethod
    def releases_by_toc(self, toc: TocSignature) -> list[ReleaseSummary]:
        """Lookup releases by TOC fingerprint. Empty list when no match."""

    @abstractmethod
    def release_by_mbid(self, mbid: str) -> ReleaseDetail:
        """Fetch full release details for one MBID."""

    @abstractmethod
    def set_user_agent(self, app: str, version: str, contact: str) -> None:
        """Re-identify the client (e.g., after a version bump)."""


# --- v1 concrete implementation --------------------------------------------


class MusicBrainzNgsImpl(MusicBrainzClient):
    """MusicBrainz client backed by the `musicbrainzngs` library."""

    def __init__(self, app: str, version: str, contact: str) -> None:
        """User-agent is mandatory; MB throttles unidentified traffic.

        Per MB's policy, `contact` should be a real email or project URL
        so a human can be reached if our client misbehaves.
        """
        self.set_user_agent(app, version, contact)

    def set_user_agent(self, app: str, version: str, contact: str) -> None:
        musicbrainzngs.set_useragent(app, version, contact)
        log.debug("MB user-agent set: %s/%s (%s)", app, version, contact)

    # --- Public ABC methods ---

    def releases_by_disc_id(self, disc_id: str) -> list[ReleaseSummary]:
        try:
            response = musicbrainzngs.get_releases_by_discid(
                disc_id,
                includes=["artists", "labels"],
                cdstubs=False,
            )
        except musicbrainzngs.ResponseError as exc:
            # MB returns 404 for "no match" — translate that to an empty list
            # rather than an exception, since the picker UI treats it as
            # "no candidates" (not an error).
            if _is_not_found(exc):
                return []
            raise MusicBrainzQueryError(f"MB disc-id lookup failed: {exc}") from exc
        except musicbrainzngs.WebServiceError as exc:
            raise MusicBrainzQueryError(f"MB disc-id lookup failed: {exc}") from exc

        return _summaries_from_disc_response(response)

    def releases_by_toc(self, toc: TocSignature) -> list[ReleaseSummary]:
        try:
            response = musicbrainzngs.get_releases_by_discid(
                "-",  # MB requires a disc-id; "-" is the documented
                # placeholder when only `toc=` is meaningful
                toc=toc.to_query(),
                includes=["artists", "labels"],
                cdstubs=False,
            )
        except musicbrainzngs.ResponseError as exc:
            if _is_not_found(exc):
                return []
            raise MusicBrainzQueryError(f"MB TOC lookup failed: {exc}") from exc
        except musicbrainzngs.WebServiceError as exc:
            raise MusicBrainzQueryError(f"MB TOC lookup failed: {exc}") from exc

        return _summaries_from_disc_response(response)

    def release_by_mbid(self, mbid: str) -> ReleaseDetail:
        try:
            response = musicbrainzngs.get_release_by_id(
                mbid,
                # "tags" → a genre (top folksonomy tag; MB has no plain "genres"
                # include in musicbrainzngs 0.7.1); "isrcs" → per-recording ISRCs.
                includes=["artists", "recordings", "labels", "media", "tags", "isrcs"],
            )
        except musicbrainzngs.WebServiceError as exc:
            raise MusicBrainzQueryError(f"MB release fetch failed: {exc}") from exc

        release = response.get("release", {})
        summary = _summary_from_release_dict(release)
        tracks = _tracks_from_release_dict(release)
        return ReleaseDetail(summary=summary, tracks=tracks)


# --- Response shape helpers (private) --------------------------------------
#
# musicbrainzngs returns nested dicts mirroring MB's XML. The helpers
# below isolate that structure so a future RequestsJsonImpl can produce
# the same dataclasses from MB's JSON response without touching the
# rest of the codebase.


def _is_not_found(exc: musicbrainzngs.ResponseError) -> bool:
    """True when MB returned a 404 (the disc/TOC isn't in the database)."""
    cause = getattr(exc, "cause", None)
    code = getattr(cause, "code", None) if cause else None
    return code == 404


def _summaries_from_disc_response(
    response: dict,
) -> list[ReleaseSummary]:
    """Extract release summaries from `get_releases_by_discid` payload."""
    disc = response.get("disc") or {}
    return [_summary_from_release_dict(r) for r in disc.get("release-list", [])]


def _summary_from_release_dict(release: dict) -> ReleaseSummary:
    """Map one MB release dict to a ReleaseSummary."""
    mbid = release.get("id", "")
    title = release.get("title", "")
    artist_credit = _artist_credit_string(release.get("artist-credit", []))
    date = release.get("date", "")
    country = release.get("country", "")
    disambiguation = release.get("disambiguation", "")

    media = release.get("medium-list", [])
    track_count = _first_medium_track_count(media)
    medium_format = _first_medium_format(media)
    disc_number, total_discs = _disc_numbering(media)

    label, catalog_number = _first_label_info(release.get("label-info-list", []))

    return ReleaseSummary(
        mbid=mbid,
        title=title,
        artist_credit=artist_credit,
        date=date,
        country=country,
        track_count=track_count,
        label=label,
        catalog_number=catalog_number,
        medium_format=medium_format,
        disambiguation=disambiguation,
        genre=_top_tag_name(release),
        disc_number=disc_number,
        total_discs=total_discs,
    )


def _tracks_from_release_dict(release: dict) -> tuple[TrackSummary, ...]:
    """Extract per-track summaries from a full release fetch."""
    media = release.get("medium-list", [])
    if not media:
        return ()
    # The brief targets audio CDs; the first medium is the one we want
    # in nearly all cases. Multi-disc handling is P1.
    first = media[0]
    tracks: list[TrackSummary] = []
    for track in first.get("track-list", []):
        recording = track.get("recording", {})
        number = _safe_int(track.get("position") or track.get("number"))
        if number is None:
            continue
        length_ms = _safe_int(recording.get("length") or track.get("length"))
        tracks.append(
            TrackSummary(
                number=number,
                title=recording.get("title", "") or track.get("title", ""),
                artist_credit=_artist_credit_string(recording.get("artist-credit", [])),
                length_ms=length_ms,
                isrc=_first_isrc(recording),
            )
        )
    return tuple(tracks)


def _artist_credit_string(credit: list) -> str:
    """Render MB's artist-credit list as a display string.

    MB returns artist credits as a list alternating dicts (with
    `artist` and `name` keys) and strings (the joining text like
    " feat. " or " & "). The display string is the concatenation.
    """
    parts: list[str] = []
    for item in credit:
        if isinstance(item, dict):
            artist = item.get("artist") or {}
            parts.append(item.get("name") or artist.get("name") or "")
        else:
            parts.append(str(item))
    return "".join(parts).strip()


def _first_medium_track_count(media: list) -> int | None:
    if not media:
        return None
    tc = media[0].get("track-count")
    return _safe_int(tc)


def _first_medium_format(media: list) -> str:
    if not media:
        return ""
    return media[0].get("format", "")


def _disc_numbering(media: list) -> tuple[int, int]:
    """Return (disc_number, total_discs) from the medium-list.

    We rip the first medium (multi-disc selection is P1), so its `position` is
    the disc number; the total is how many media the release has. Defaults to
    1/1 when the list is empty or unnumbered.
    """
    total = max(len(media), 1)
    disc_number = (_safe_int(media[0].get("position")) if media else None) or 1
    return disc_number, total


def _top_tag_name(release: dict) -> str:
    """The highest-voted folksonomy tag as a best-effort genre, or "".

    MB has no curated genre in musicbrainzngs 0.7.1's includes, so we use the
    most-applied tag (often a genre like "rock"). Empty when the release is
    untagged or the "tags" include wasn't requested.
    """
    best_name, best_count = "", -1
    for tag in release.get("tag-list", []):
        if not isinstance(tag, dict):
            continue
        name = tag.get("name", "")
        count = _safe_int(tag.get("count")) or 0
        if name and count > best_count:
            best_name, best_count = name, count
    return best_name


def _first_isrc(recording: dict) -> str:
    """First ISRC for a recording, or "". MB returns isrc-list as strings or
    `{"id": ...}` dicts depending on the response shape — handle both."""
    for item in recording.get("isrc-list", []):
        isrc = item.get("id", "") if isinstance(item, dict) else str(item)
        if isrc:
            return isrc
    return ""


def _first_label_info(infos: list) -> tuple[str, str]:
    if not infos:
        return "", ""
    info = infos[0]
    label = (info.get("label") or {}).get("name", "")
    catno = info.get("catalog-number", "")
    return label, catno


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None
