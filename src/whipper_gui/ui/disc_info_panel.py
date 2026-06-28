"""Read-only panel showing the currently-loaded disc's identification.

The panel is a pure view — it doesn't fetch anything itself. The main
window observes `drive_changed` from the DrivePicker, runs
`WhipperBackend.disc_info()` and `MusicBrainzClient.releases_by_disc_id()`
on workers, and pushes results into this panel via the `set_*` methods.

Why a pure view: the orchestration of "fetch disc info, then look up
MusicBrainz" is two-step async work. Keeping that logic in the main
window (or a controller) means this widget stays trivially testable
and re-usable.

Fields displayed:
  Drive               — the device path of the currently-selected drive
  MusicBrainz disc ID — from `whipper cd info`
  CDDB disc ID        — same source
  MusicBrainz match   — outcome of the MB lookup (or a status message)
  AccurateRip         — blank until a rip finishes, then the real outcome
                        (how many tracks the AccurateRip database confirmed).
                        Per-track detail is in `RipProgress`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from whipper_gui.adapters.musicbrainz_client import ReleaseSummary
from whipper_gui.parsers.cd_info import DiscInfo
from whipper_gui.parsers.rip_log import track_accuraterip_verified

# Placeholder shown in fields we don't have data for yet.
_PLACEHOLDER: str = "—"


class DiscInfoPanel(QWidget):
    """Read-only panel. Pure view; no data fetching here."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Use TextSelectableByMouse on the value labels so the user
        # can copy a disc ID into Picard or a browser.
        self._drive_value: QLabel = self._value_label("(no drive)")
        self._mb_id_value: QLabel = self._value_label(_PLACEHOLDER)
        self._cddb_id_value: QLabel = self._value_label(_PLACEHOLDER)
        self._mb_match_value: QLabel = self._value_label(_PLACEHOLDER)
        # AccurateRip status is a *post-rip* fact — we can't know it until the
        # rip log lands. Start blank rather than claiming "verified" (the old
        # static text), which was misleading for any disc not in the database
        # (a CD-R, say): every track comes back "not present", which is the
        # opposite of verified. set_accuraterip_result() fills this in.
        self._accuraterip_value: QLabel = self._value_label(_PLACEHOLDER)

        form = QFormLayout(self)
        form.addRow("Drive:", self._drive_value)
        form.addRow("MusicBrainz disc ID:", self._mb_id_value)
        form.addRow("CDDB disc ID:", self._cddb_id_value)
        form.addRow("MusicBrainz match:", self._mb_match_value)
        form.addRow("AccurateRip:", self._accuraterip_value)

    # --- Drive selection -----------------------------------------------------

    def set_drive(self, device: str | None) -> None:
        """Set the drive shown at the top of the panel.

        Clears the disc-derived fields — when the user picks a new
        drive, the disc that was loaded is no longer the relevant one.
        """
        self._drive_value.setText(device or "(no drive)")
        self.clear_disc_state()

    def clear_disc_state(self) -> None:
        """Reset every disc-derived field. Called on drive change."""
        self._mb_id_value.setText(_PLACEHOLDER)
        self._cddb_id_value.setText(_PLACEHOLDER)
        self._mb_match_value.setText(_PLACEHOLDER)
        self._accuraterip_value.setText(_PLACEHOLDER)

    # --- AccurateRip outcome (from the parsed rip log) ----------------------

    def set_accuraterip_result(self, rip_log: object) -> None:
        """Show the real AccurateRip outcome after a rip finishes.

        AccurateRip can only *verify* a track when that exact pressing is in
        the database. For a CD-R — or any disc nobody has submitted — every
        track comes back "not present", which is NOT a verification. We report
        what actually happened instead of a blanket "verified".

        "Verified" uses the one shared rule (``track_accuraterip_verified``,
        confidence ≥ 1) that the results-pane verdict banner uses, so the two
        surfaces never disagree about how many tracks matched — a string check
        here would silently miss every cyanrip match ("accurately ripped,
        confidence N" has no "exact match" substring).
        """
        tracks = getattr(rip_log, "tracks", ()) or ()
        total = len(tracks)
        if total == 0:
            self._accuraterip_value.setText(_PLACEHOLDER)
            return
        matched = sum(1 for track in tracks if track_accuraterip_verified(track))
        if matched == 0:
            self._accuraterip_value.setText("not in database")
        elif matched == total:
            self._accuraterip_value.setText(f"verified — all {total} tracks matched")
        else:
            self._accuraterip_value.setText(f"{matched} of {total} tracks matched")

    # --- Disc info (from `whipper cd info`) ---------------------------------

    def set_disc_info_loading(self) -> None:
        """Show 'reading disc…' while the disc_info subprocess runs."""
        self._mb_id_value.setText("…")
        self._cddb_id_value.setText("…")
        self._mb_match_value.setText("reading disc…")

    def set_disc_info(self, info: DiscInfo) -> None:
        """Populate the MB/CDDB disc-ID fields."""
        self._mb_id_value.setText(info.musicbrainz_disc_id or _PLACEHOLDER)
        self._cddb_id_value.setText(info.cddb_disc_id or _PLACEHOLDER)

    def set_disc_info_error(self, message: str) -> None:
        """Mark the disc fields as failed and show a short error."""
        self._mb_id_value.setText(_PLACEHOLDER)
        self._cddb_id_value.setText(_PLACEHOLDER)
        self._mb_match_value.setText(f"error: {message}")

    # --- MusicBrainz match (from MusicBrainzClient) --------------------------

    def set_mb_loading(self) -> None:
        """Status while a MB lookup is in flight."""
        self._mb_match_value.setText("querying MusicBrainz…")

    def set_mb_matches(self, releases: list[ReleaseSummary]) -> None:
        """Render the count and (when unique) the matched release."""
        if not releases:
            self._mb_match_value.setText("not in MusicBrainz")
        elif len(releases) == 1:
            release = releases[0]
            artist = release.artist_credit or "Unknown Artist"
            title = release.title or "Unknown Title"
            self._mb_match_value.setText(f"1 match: {artist} — {title}")
        else:
            self._mb_match_value.setText(f"{len(releases)} matches found — pick one")

    def set_mb_error(self, message: str) -> None:
        self._mb_match_value.setText(f"MusicBrainz error: {message}")

    # --- Internals ---------------------------------------------------------

    @staticmethod
    def _value_label(text: str) -> QLabel:
        """A monospaced-by-context value label that supports copy-on-select."""
        label = QLabel(text)
        # Selecting with the mouse + Ctrl+C is the easiest way to grab
        # a disc ID into something else (Picard, a web search).
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return label
