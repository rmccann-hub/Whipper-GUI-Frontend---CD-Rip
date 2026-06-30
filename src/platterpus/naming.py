"""File-naming schemes (presets) + a live-preview renderer.

The rip output's folder/file layout is controlled by a whipper-style path
*template* made of the tokens below. Hand-writing one is error-prone — the old
default (``%A/%d/%t - %n - %d - %A - %y``) repeated the album and artist in every
filename and tacked the full release date on the end, which looked terrible
(real-user report, 0.4.4). This module gives the Settings dialog a small set of
**named presets** that match what the popular music tools actually do, plus a
pure :func:`render_preview` so the dialog can show *exactly* what a filename will
look like before the user commits.

Why these presets — what the ecosystem converges on (researched 2026-06-30):

* **MusicBrainz Picard** default: ``AlbumArtist/Album/## Title`` (and
  ``## Artist - Title`` when the album has per-track artists).
* **beets** default (``$albumartist/$album/$track $title``) and **Plex**'s
  recommended layout (``Artist/Album/## - Title``) are the same shape.
* **Plex / Jellyfin / Kodi** for media servers like the year *in the album
  folder* — ``Album (Year)`` — never in the filename.
* **foobar2000**'s common scheme prefixes the folder with the year
  (``Year - Album``) so an artist's albums sort chronologically.

The consensus the presets encode: **per-track-variable fields go in the
filename (track number, title, and — for compilations — the track artist);
album-constant fields (album, artist, year) belong in the folder path; and the
year, when wanted, goes in the *folder*, not the filename, and never at the
end.**

Token reference (matches ``adapters/cyanrip_backend`` so a preset round-trips):
    %A = album artist   %a = track artist   %d = album (disc) title
    %t = track number   %n = track title    %y = release date

Caveat on %y: it resolves to the *full* release date the tagger has (e.g.
``1995-09-12``), not a bare year — cyanrip's scheme has no year-only token. The
year presets therefore show the full date today; :func:`render_preview` reflects
that honestly so the choice is informed.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- The token → sample-value substitution used ONLY for the preview ---------
# These mirror what cyanrip fills in at rip time. The preview is a faithful
# dry-run so the dialog can show the real result without touching a disc.

# cyanrip sanitises path-*illegal* characters inside a tag VALUE (not the
# template's own "/" separators) by swapping them for look-alike Unicode glyphs,
# so "Every Breath You Take: The Classics" lands on disk as "…∶ The Classics".
# We reproduce the two the user will actually hit, so the preview matches reality
# (the surprising ∶ in their first rip's filename is exactly this).
_VALUE_SANITISE: dict[str, str] = {
    ":": "∶",  # RATIO — cyanrip's stand-in for a colon
    "/": "∕",  # DIVISION SLASH — a "/" inside a tag value, not a separator
}


@dataclass(frozen=True)
class SampleTrack:
    """A representative track for rendering a naming preview."""

    album_artist: str
    track_artist: str
    album: str
    title: str
    track: int
    track_total: int
    date: str

    def value_for(self, token: str) -> str:
        """The sample value for a ``%X`` token (already path-sanitised).

        Unknown tokens return "" so a stray code can never crash the preview.
        """
        raw: str
        if token == "A":
            raw = self.album_artist
        elif token == "a":
            raw = self.track_artist
        elif token == "d":
            raw = self.album
        elif token == "n":
            raw = self.title
        elif token == "y":
            raw = self.date
        elif token == "t":
            # cyanrip zero-pads the track number to the disc's width (min 2).
            width = max(2, len(str(self.track_total)))
            raw = str(self.track).zfill(width)
        else:
            return ""
        return _sanitise_value(raw)


def _sanitise_value(value: str) -> str:
    """Swap path-illegal characters in a tag value for cyanrip's look-alikes."""
    for bad, good in _VALUE_SANITISE.items():
        value = value.replace(bad, good)
    return value


# A clean single-artist album (Led Zeppelin IV) and a metadata-heavy stress
# case (a compilation with a colon in the title and a featured/per-track artist)
# so the preview shows how a preset copes with the awkward cases, not just the
# easy one. These are display-only samples; nothing is ripped.
SAMPLE_EASY: SampleTrack = SampleTrack(
    album_artist="Led Zeppelin",
    track_artist="Led Zeppelin",
    album="Led Zeppelin IV",
    title="Black Dog",
    track=1,
    track_total=8,
    date="1971-11-08",
)
SAMPLE_STRESS: SampleTrack = SampleTrack(
    album_artist="Various Artists",
    track_artist="Eric Clapton feat. B.B. King",
    album="Riding with the King: Deluxe Edition",
    title="Key to the Highway",
    track=3,
    track_total=15,
    date="2020-06-12",
)


@dataclass(frozen=True)
class NamingPreset:
    """A named (track, disc) template pair shown in the Settings dropdown."""

    key: str
    label: str
    track_template: str
    disc_template: str
    note: str = ""


# The presets, in menu order. The first is the recommended default. "Custom"
# is represented by `None` (the free-text fields stay whatever the user typed).
PRESETS: tuple[NamingPreset, ...] = (
    NamingPreset(
        key="artist_album_track_title",
        label="Artist / Album / 01 - Title  (recommended)",
        track_template="%A/%d/%t - %n",
        disc_template="%A/%d/%d",
        note="The clean default used by Picard, beets and Plex. No year clutter.",
    ),
    NamingPreset(
        key="artist_album_track_title_nodash",
        label="Artist / Album / 01 Title",
        track_template="%A/%d/%t %n",
        disc_template="%A/%d/%d",
        note="Same layout without the dash separator.",
    ),
    NamingPreset(
        key="artist_album_year_track_title",
        label="Artist / Album (Year) / 01 - Title  (media servers)",
        track_template="%A/%d (%y)/%t - %n",
        disc_template="%A/%d (%y)/%d",
        note="Plex/Jellyfin style — year in the folder. (%y is the full date today.)",
    ),
    NamingPreset(
        key="artist_year_album_track_title",
        label="Artist / Year - Album / 01 - Title  (chronological)",
        track_template="%A/%y - %d/%t - %n",
        disc_template="%A/%y - %d/%d",
        note="foobar2000 style — albums sort by date. (%y is the full date today.)",
    ),
    NamingPreset(
        key="compilation",
        label="Compilation: Artist / Album / 01 - Track Artist - Title",
        track_template="%A/%d/%t - %a - %n",
        disc_template="%A/%d/%d",
        note="Keeps the per-track artist in the name — best for Various-Artists discs.",
    ),
)

DEFAULT_PRESET: NamingPreset = PRESETS[0]

# Sentinel shown in the dropdown when the templates don't match any preset
# (i.e. the user hand-edited them). Not in PRESETS so it never overwrites a
# custom template by being "selected".
CUSTOM_LABEL: str = "Custom (hand-tuned below)"


def preset_for_templates(
    track_template: str, disc_template: str
) -> NamingPreset | None:
    """Return the preset matching these templates, or None if it's custom."""
    for preset in PRESETS:
        if (
            preset.track_template == track_template
            and preset.disc_template == disc_template
        ):
            return preset
    return None


def render_preview(template: str, sample: SampleTrack) -> str:
    """Render `template` with `sample`'s values — a faithful filename preview.

    Mirrors cyanrip: ``%X`` tokens are substituted with sanitised tag values,
    a literal ``%%`` becomes ``%``, the template's own ``/`` stay as path
    separators, and ``.flac`` is appended to the final segment so the user sees
    a real filename. NEVER raises (it backs the live preview as the user types):
    an unknown ``%X`` and a trailing bare ``%`` are passed through verbatim.
    """
    out: list[str] = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        # A "%" at the very end has no token — keep it literally.
        if i + 1 >= n:
            out.append("%")
            break
        token = template[i + 1]
        if token == "%":
            out.append("%")
        else:
            value = sample.value_for(token)
            # Unknown token (value "") → pass through verbatim so a typo is
            # visible in the preview rather than silently vanishing.
            out.append(value if value else f"%{token}")
        i += 2
    return "".join(out) + ".flac"
