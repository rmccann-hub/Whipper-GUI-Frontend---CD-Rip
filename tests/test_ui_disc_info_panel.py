"""Tests for whipper_gui.ui.disc_info_panel."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.musicbrainz_client import ReleaseSummary
from whipper_gui.parsers.cd_info import DiscInfo
from whipper_gui.parsers.rip_log import AccurateRipResult, RipLog, TrackResult
from whipper_gui.ui.disc_info_panel import DiscInfoPanel


def _track(number: int, *, matched: bool) -> TrackResult:
    """A TrackResult whose AccurateRip v1 either matched or wasn't in the DB.

    A real match always carries a confidence ≥ 1 (how many submitted rips
    share the CRC); a "not present" track has no confidence — mirror that so
    the fixture exercises the real confidence-based verification rule.
    """
    if matched:
        ar = AccurateRipResult(version=1, result="Found, exact match", confidence=12)
    else:
        ar = AccurateRipResult(
            version=1, result="Track not present in AccurateRip database"
        )
    return TrackResult(number=number, accuraterip_v1=ar)


def _release(
    mbid: str = "x",
    title: str = "Album",
    artist: str = "Artist",
) -> ReleaseSummary:
    return ReleaseSummary(mbid=mbid, title=title, artist_credit=artist)


# --- Initial state -------------------------------------------------------


def test_default_state_shows_placeholders(qapp: QApplication) -> None:
    panel = DiscInfoPanel()

    assert panel._drive_value.text() == "(no drive)"
    assert panel._mb_id_value.text() == "—"
    assert panel._cddb_id_value.text() == "—"
    assert panel._mb_match_value.text() == "—"
    # AccurateRip is a post-rip fact — blank until a rip log lands, never a
    # premature "verified".
    assert panel._accuraterip_value.text() == "—"


# --- Drive selection -----------------------------------------------------


def test_set_drive_updates_label(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_drive("/dev/sr0")
    assert panel._drive_value.text() == "/dev/sr0"


def test_set_drive_none_shows_placeholder(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_drive("/dev/sr0")
    panel.set_drive(None)
    assert panel._drive_value.text() == "(no drive)"


def test_set_drive_clears_disc_fields(qapp: QApplication) -> None:
    """Switching drives must wipe the previously-loaded disc's info."""
    panel = DiscInfoPanel()
    panel.set_disc_info(
        DiscInfo(
            cddb_disc_id="abc",
            musicbrainz_disc_id="mb-id",
            musicbrainz_submit_url="",
        )
    )
    panel.set_mb_matches([_release()])

    panel.set_drive("/dev/sr1")

    assert panel._mb_id_value.text() == "—"
    assert panel._cddb_id_value.text() == "—"
    assert panel._mb_match_value.text() == "—"


# --- Disc info -----------------------------------------------------------


def test_set_disc_info_loading_shows_status(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_disc_info_loading()

    assert panel._mb_id_value.text() == "…"
    assert panel._cddb_id_value.text() == "…"
    assert panel._mb_match_value.text() == "reading disc…"


def test_set_disc_info_populates_ids(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    info = DiscInfo(
        cddb_disc_id="940A6A0B",
        musicbrainz_disc_id="wzr8h2ssXg4F2.x8L3KqB9PHevc-",
        musicbrainz_submit_url="https://example",
    )
    panel.set_disc_info(info)

    assert panel._mb_id_value.text() == "wzr8h2ssXg4F2.x8L3KqB9PHevc-"
    assert panel._cddb_id_value.text() == "940A6A0B"


def test_set_disc_info_empty_ids_show_placeholder(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    info = DiscInfo()
    panel.set_disc_info(info)

    assert panel._mb_id_value.text() == "—"
    assert panel._cddb_id_value.text() == "—"


def test_set_disc_info_error_shows_message(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_disc_info_error("disc not present")
    assert "disc not present" in panel._mb_match_value.text()


# --- MusicBrainz match ---------------------------------------------------


def test_set_mb_loading_shows_status(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_loading()
    assert panel._mb_match_value.text() == "querying MusicBrainz…"


def test_set_mb_matches_empty_shows_not_in_database(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_matches([])
    assert panel._mb_match_value.text() == "not in MusicBrainz"


def test_set_mb_matches_single_shows_release_name(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_matches([_release(artist="Pink Floyd", title="Dark Side")])

    text = panel._mb_match_value.text()
    assert "1 match" in text
    assert "Pink Floyd" in text
    assert "Dark Side" in text


def test_set_mb_matches_multiple_shows_count_and_hint(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_matches([_release(), _release(mbid="y"), _release(mbid="z")])
    text = panel._mb_match_value.text()
    assert "3 matches" in text
    assert "pick" in text.lower()


def test_set_mb_matches_handles_missing_metadata(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_matches([_release(title="", artist="")])
    text = panel._mb_match_value.text()
    assert "Unknown Title" in text
    assert "Unknown Artist" in text


def test_set_mb_error_shows_message(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_mb_error("network down")
    text = panel._mb_match_value.text()
    assert "network down" in text


# --- AccurateRip outcome -------------------------------------------------


def test_accuraterip_none_matched_reports_not_in_database(
    qapp: QApplication,
) -> None:
    """A CD-R (nothing in the DB) must NOT read as 'verified'."""
    panel = DiscInfoPanel()
    rip_log = RipLog(tracks=tuple(_track(n, matched=False) for n in range(1, 17)))
    panel.set_accuraterip_result(rip_log)
    assert panel._accuraterip_value.text() == "not in database"


def test_accuraterip_all_matched_reports_verified(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    rip_log = RipLog(tracks=tuple(_track(n, matched=True) for n in range(1, 4)))
    panel.set_accuraterip_result(rip_log)
    text = panel._accuraterip_value.text()
    assert "verified" in text
    assert "3" in text


def test_accuraterip_partial_match_reports_fraction(
    qapp: QApplication,
) -> None:
    panel = DiscInfoPanel()
    rip_log = RipLog(
        tracks=(
            _track(1, matched=True),
            _track(2, matched=False),
            _track(3, matched=True),
        )
    )
    panel.set_accuraterip_result(rip_log)
    assert panel._accuraterip_value.text() == "2 of 3 tracks matched"


def test_accuraterip_no_tracks_stays_placeholder(qapp: QApplication) -> None:
    panel = DiscInfoPanel()
    panel.set_accuraterip_result(RipLog(tracks=()))
    assert panel._accuraterip_value.text() == "—"


def test_accuraterip_confidence_zero_exact_match_is_not_verified(
    qapp: QApplication,
) -> None:
    """Regression: a confidence-0 'exact match' must NOT read as verified.

    The old string-only check ("exact match" in result) counted this as a
    match while the results-pane banner did not — two surfaces disagreeing on
    the same screen. Both now share the confidence ≥ 1 rule.
    """
    panel = DiscInfoPanel()
    rip_log = RipLog(
        tracks=(
            TrackResult(
                number=1,
                copy_crc="ABCD1234",
                accuraterip_v1=AccurateRipResult(
                    version=1, result="Found, exact match", confidence=0
                ),
            ),
        )
    )
    panel.set_accuraterip_result(rip_log)
    assert panel._accuraterip_value.text() == "not in database"


def test_accuraterip_counts_cyanrip_style_match(qapp: QApplication) -> None:
    """Regression: cyanrip writes 'accurately ripped, confidence N' — no
    'exact match' substring — so the old string check missed EVERY cyanrip
    verification. The confidence-based rule counts it correctly."""
    panel = DiscInfoPanel()
    rip_log = RipLog(
        tracks=(
            TrackResult(
                number=1,
                accuraterip_v1=AccurateRipResult(
                    version=1, result="accurately ripped, confidence 3", confidence=3
                ),
            ),
        )
    )
    panel.set_accuraterip_result(rip_log)
    assert "verified" in panel._accuraterip_value.text()


def test_set_drive_clears_accuraterip_result(qapp: QApplication) -> None:
    """A new disc means the old AccurateRip verdict no longer applies."""
    panel = DiscInfoPanel()
    panel.set_accuraterip_result(RipLog(tracks=(_track(1, matched=True),)))
    panel.set_drive("/dev/sr1")
    assert panel._accuraterip_value.text() == "—"


# --- Lifecycle: drive change after data ----------------------------------


def test_set_drive_called_twice_resets_in_between(
    qapp: QApplication,
) -> None:
    """A user changing drives mid-flow must always see a clean panel."""
    panel = DiscInfoPanel()
    panel.set_drive("/dev/sr0")
    panel.set_disc_info(DiscInfo(cddb_disc_id="aaa", musicbrainz_disc_id="bbb"))
    panel.set_drive("/dev/sr1")
    panel.set_disc_info_loading()

    # The previous disc's IDs must not leak.
    assert "aaa" not in panel._cddb_id_value.text()
    assert "bbb" not in panel._mb_id_value.text()
