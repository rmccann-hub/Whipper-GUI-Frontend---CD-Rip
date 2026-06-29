"""Tests for platterpus.ui.rip_progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from platterpus.ctdb.verify import CtdbVerifyResult, Verdict
from platterpus.parsers.rip_log import (
    AccurateRipResult,
    RipLog,
    TrackResult,
)
from platterpus.ui.rip_progress import (
    RipProgress,
    _ar_cell,
    _basename,
    accuraterip_verdict,
    ctdb_verdict_level,
    ctdb_verdict_line,
)

# --- Helpers --------------------------------------------------------------


class _OpenUrlSpy:
    def __init__(self) -> None:
        self.calls: list[QUrl] = []

    def __call__(self, url: QUrl) -> bool:
        self.calls.append(url)
        return True


def _track(
    number: int = 1,
    filename: str = "Artist/Album/01. Track.flac",
    status: str = "Copy OK",
    v1: AccurateRipResult | None = None,
    v2: AccurateRipResult | None = None,
) -> TrackResult:
    return TrackResult(
        number=number,
        filename=filename,
        status=status,
        accuraterip_v1=v1,
        accuraterip_v2=v2,
    )


# --- Initial state -------------------------------------------------------


def test_default_state(qapp: QApplication) -> None:
    widget = RipProgress()
    assert widget._status_label.text() == "Idle."
    assert widget._progress_bar.value() == 0
    assert widget._log_view.toPlainText() == ""
    assert widget._ar_table.rowCount() == 0
    assert widget._view_log_button.isEnabled() is False


def test_status_surfaces_have_accessible_names(qapp: QApplication) -> None:
    # Screen readers need a name on every status surface (a11y, principle #10).
    widget = RipProgress()
    assert widget._overall_bar.accessibleName()
    assert widget._progress_bar.accessibleName()
    assert widget._verdict_banner.accessibleName()
    assert widget._ar_table.accessibleName()
    assert widget._ctdb_label.accessibleName()


def test_every_verdict_level_has_a_non_color_symbol() -> None:
    # Status must be conveyed by symbol + text, never colour alone — so each
    # level's message starts with a distinct marker (✓ / ⚠ / ⓘ).
    from platterpus.parsers.rip_log import AccurateRipResult, RipLog, TrackResult

    ok, _ = accuraterip_verdict(
        RipLog(
            tracks=(TrackResult(1, accuraterip_v1=AccurateRipResult(1, confidence=9)),)
        )
    )
    warn, _ = accuraterip_verdict(
        RipLog(
            tracks=(
                TrackResult(1, accuraterip_v1=AccurateRipResult(1, confidence=9)),
                TrackResult(2, copy_crc="AAAA", accuraterip_v1=AccurateRipResult(1)),
            )
        )
    )
    neutral, _ = accuraterip_verdict(RipLog(tracks=(TrackResult(1, copy_crc="AAAA"),)))
    assert ok.startswith("✓")
    assert warn.startswith("⚠")
    assert neutral.startswith("ⓘ")


def test_verdict_confidence_floor_ignores_non_matching_zero() -> None:
    # Each track is verified via v2 (conf >= 1) while v1 is "present, no match"
    # at confidence 0. The "(confidence X+)" floor must reflect only the real
    # matches (min of 200, 50 = 50), never the misleading 0.
    log = RipLog(
        tracks=(
            TrackResult(
                1,
                accuraterip_v1=AccurateRipResult(1, confidence=0),
                accuraterip_v2=AccurateRipResult(2, confidence=200),
            ),
            TrackResult(
                2,
                accuraterip_v1=AccurateRipResult(1, confidence=0),
                accuraterip_v2=AccurateRipResult(2, confidence=50),
            ),
        )
    )
    message, level = accuraterip_verdict(log)
    assert level == "ok"
    assert "confidence 50+" in message
    assert "confidence 0+" not in message


# --- Log streaming -------------------------------------------------------


def test_append_log_line_adds_text(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.append_log_line("first")
    widget.append_log_line("second")

    text = widget._log_view.toPlainText()
    assert "first" in text
    assert "second" in text


# --- Progress updates ----------------------------------------------------


def test_set_progress_updates_both_bars_only(qapp: QApplication) -> None:
    # set_progress drives the overall + task bars; the status label is
    # owned by set_status (fed from the worker's phase signal).
    widget = RipProgress()
    before = widget._status_label.text()
    widget.set_progress(60.0, 42.0)

    assert widget._overall_bar.value() == 60
    assert widget._progress_bar.value() == 42
    assert widget._status_label.text() == before  # unchanged


def test_set_status_updates_label(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_status("All done.")
    assert widget._status_label.text() == "All done."


# --- AccurateRip table ---------------------------------------------------


def test_set_rip_log_populates_table(qapp: QApplication) -> None:
    widget = RipProgress()
    log = RipLog(
        tracks=(
            _track(
                1,
                filename="Pink Floyd/Dark Side/01. Speak to Me.flac",
                v1=AccurateRipResult(
                    version=1, result="Found, exact match", confidence=14
                ),
                v2=AccurateRipResult(
                    version=2, result="Found, exact match", confidence=11
                ),
            ),
            _track(
                2,
                filename="Pink Floyd/Dark Side/02. Breathe.flac",
                v1=AccurateRipResult(
                    version=1,
                    result="Track not present in AccurateRip database",
                    confidence=0,
                ),
                v2=None,
            ),
        )
    )

    widget.set_rip_log(log)

    assert widget._ar_table.rowCount() == 2
    assert widget._ar_table.item(0, 0).text() == "1"
    assert "Speak to Me" in widget._ar_table.item(0, 1).text()
    assert widget._ar_table.item(0, 2).text() == "Copy OK"
    assert widget._ar_table.item(0, 3).text() == "OK (14)"
    assert widget._ar_table.item(0, 4).text() == "OK (11)"
    # Track 2 — v1 not in DB, v2 missing.
    assert widget._ar_table.item(1, 3).text() == "not in DB"
    assert widget._ar_table.item(1, 4).text() == "—"


def test_set_rip_log_empty_tracks_clears_table(qapp: QApplication) -> None:
    widget = RipProgress()
    widget._ar_table.setRowCount(3)  # pretend we had results
    widget.set_rip_log(RipLog())
    assert widget._ar_table.rowCount() == 0


# --- View log button -----------------------------------------------------


def test_set_log_path_enables_button(qapp: QApplication, tmp_path: Path) -> None:
    widget = RipProgress()
    log_file = tmp_path / "rip.log"
    log_file.write_text("dummy")

    widget.set_log_path(log_file)

    assert widget._view_log_button.isEnabled() is True


def test_set_log_path_none_disables_button(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_log_path(Path("/tmp/x"))  # enable
    widget.set_log_path(None)
    assert widget._view_log_button.isEnabled() is False


def test_view_log_click_opens_url(qapp: QApplication, tmp_path: Path) -> None:
    spy = _OpenUrlSpy()
    widget = RipProgress(open_url=spy)
    log_file = tmp_path / "rip.log"
    log_file.write_text("dummy")
    widget.set_log_path(log_file)

    widget._view_log_button.click()

    assert len(spy.calls) == 1
    url = spy.calls[0]
    assert url.isLocalFile()
    assert url.toLocalFile() == str(log_file)


def test_view_log_no_op_without_path(qapp: QApplication) -> None:
    spy = _OpenUrlSpy()
    widget = RipProgress(open_url=spy)
    widget._on_view_log_clicked()  # call directly; button is disabled
    assert spy.calls == []


# --- clear() -------------------------------------------------------------


def test_clear_resets_all_state(qapp: QApplication, tmp_path: Path) -> None:
    widget = RipProgress()
    widget.append_log_line("noise")
    widget.set_progress(70.0, 90.0)
    widget.set_rip_log(RipLog(tracks=(_track(),)))
    widget.set_log_path(tmp_path / "x.log")

    widget.clear()

    assert widget._status_label.text() == "Idle."
    assert widget._overall_bar.value() == 0
    assert widget._progress_bar.value() == 0
    assert widget._log_view.toPlainText() == ""
    assert widget._ar_table.rowCount() == 0
    assert widget._view_log_button.isEnabled() is False


# --- _basename helper ----------------------------------------------------


def test_basename_strips_extension() -> None:
    assert _basename("Artist/Album/01. Title.flac") == "01. Title"


def test_basename_handles_empty() -> None:
    assert _basename("") == ""


# --- _ar_cell helper -----------------------------------------------------


def test_ar_cell_none_renders_placeholder() -> None:
    assert _ar_cell(None) == "—"


def test_ar_cell_exact_match() -> None:
    ar = AccurateRipResult(version=1, result="Found, exact match", confidence=14)
    assert _ar_cell(ar) == "OK (14)"


def test_ar_cell_not_in_db() -> None:
    ar = AccurateRipResult(
        version=2,
        result="Track not present in AccurateRip database",
        confidence=0,
    )
    assert _ar_cell(ar) == "not in DB"


# --- CTDB verdict --------------------------------------------------------


def test_ctdb_verdict_line_match_validated() -> None:
    result = CtdbVerifyResult(Verdict.MATCH, confidence=8, crc_validated=True)
    line = ctdb_verdict_line(result)
    assert "verified" in line
    assert "8" in line
    assert "EXPERIMENTAL" not in line


def test_ctdb_verdict_line_match_unvalidated_is_experimental() -> None:
    # Default crc_validated mirrors crc.CRC_VALIDATED (False today) → a match
    # must be labelled experimental, never a plain "verified".
    result = CtdbVerifyResult(Verdict.MATCH, confidence=8)
    line = ctdb_verdict_line(result)
    assert "EXPERIMENTAL" in line
    assert "verified ✓" not in line


def test_ctdb_verdict_line_other_verdicts() -> None:
    assert "no match" in ctdb_verdict_line(CtdbVerifyResult(Verdict.NO_MATCH))
    assert "database" in ctdb_verdict_line(CtdbVerifyResult(Verdict.NOT_IN_DATABASE))
    assert "flac" in ctdb_verdict_line(CtdbVerifyResult(Verdict.DECODER_UNAVAILABLE))
    assert "unavailable" in ctdb_verdict_line(CtdbVerifyResult(Verdict.LOOKUP_ERROR))


def test_ctdb_verdict_level_tracks_trust() -> None:
    # A hardware-validated match is green; an experimental match is amber
    # (never green); everything else is neutral grey.
    assert (
        ctdb_verdict_level(
            CtdbVerifyResult(Verdict.MATCH, confidence=8, crc_validated=True)
        )
        == "ok"
    )
    assert ctdb_verdict_level(CtdbVerifyResult(Verdict.MATCH, confidence=8)) == "warn"
    assert ctdb_verdict_level(CtdbVerifyResult(Verdict.NO_MATCH)) == "neutral"
    assert ctdb_verdict_level(CtdbVerifyResult(Verdict.NOT_IN_DATABASE)) == "neutral"


# --- AccurateRip verdict banner ------------------------------------------


def _ar(version: int, confidence: int | None, result: str = "Found, exact match"):
    return AccurateRipResult(version=version, result=result, confidence=confidence)


def test_accuraterip_verdict_all_verified_is_ok() -> None:
    log = RipLog(
        tracks=(
            _track(1, v1=_ar(1, 14), v2=_ar(2, 11)),
            _track(2, v1=_ar(1, 5), v2=_ar(2, 3)),
        )
    )
    message, level = accuraterip_verdict(log)
    assert level == "ok"
    assert "all 2 tracks" in message
    # Lowest confidence across all verified tracks is surfaced (the floor).
    assert "confidence 3+" in message


def test_accuraterip_verdict_partial_is_warn() -> None:
    log = RipLog(
        tracks=(
            _track(1, v1=_ar(1, 14)),
            # Not in DB: confidence None on v1, no v2.
            _track(2, v1=_ar(1, None, "Track not present in AccurateRip database")),
        )
    )
    message, level = accuraterip_verdict(log)
    assert level == "warn"
    assert "1 of 2" in message


def test_accuraterip_verdict_confidence_zero_is_not_a_match() -> None:
    # A "not present" track sometimes logs confidence 0 — that is NOT a match,
    # so it must never count toward "verified" (the honesty rule).
    log = RipLog(tracks=(_track(1, v1=_ar(1, 0, "not present")),))
    message, level = accuraterip_verdict(log)
    assert level == "neutral"
    assert "no tracks matched" in message


def test_accuraterip_verdict_none_matched_is_neutral() -> None:
    # Audio tracks present (Copy CRC) but none in the DB → neutral, not a
    # failure — this is the normal CD-R case.
    log = RipLog(tracks=(TrackResult(number=1, copy_crc="ABCD1234"),))
    _, level = accuraterip_verdict(log)
    assert level == "neutral"


def test_accuraterip_verdict_empty_is_blank() -> None:
    # No audio tracks parsed → show nothing (empty message).
    message, _ = accuraterip_verdict(RipLog())
    assert message == ""
    # A pure data track (no CRC, no AR) doesn't count as audio either.
    data_only = RipLog(tracks=(TrackResult(number=1, status="data track (skipped)"),))
    assert accuraterip_verdict(data_only)[0] == ""


def test_set_rip_log_shows_verdict_banner(qapp: QApplication) -> None:
    # isHidden() reflects the explicit setVisible() intent without needing the
    # parent shown (isVisible() is always False on an unshown widget tree).
    widget = RipProgress()
    assert widget._verdict_banner.isHidden() is True
    widget.set_rip_log(RipLog(tracks=(_track(1, v1=_ar(1, 9)),)))
    assert widget._verdict_banner.isHidden() is False
    assert "Bit-perfect" in widget._verdict_banner.text()


def test_set_rip_log_hides_banner_when_no_audio(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_rip_log(RipLog(tracks=(_track(1, v1=_ar(1, 9)),)))  # show it first
    widget.set_rip_log(RipLog())  # then a log with nothing to assert
    assert widget._verdict_banner.isHidden() is True


def test_set_ctdb_status_shows_label(qapp: QApplication) -> None:
    widget = RipProgress()
    assert widget._ctdb_label.isVisible() is False
    widget.set_ctdb_status("Verifying against CTDB…")
    assert widget._ctdb_label.text() == "Verifying against CTDB…"


def test_set_ctdb_result_renders_verdict(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_ctdb_result(CtdbVerifyResult(Verdict.NOT_IN_DATABASE))
    assert "database" in widget._ctdb_label.text()


def test_clear_hides_ctdb_label(qapp: QApplication) -> None:
    widget = RipProgress()
    widget.set_ctdb_result(CtdbVerifyResult(Verdict.NO_MATCH))
    widget.clear()
    assert widget._ctdb_label.text() == ""
    assert widget._ctdb_label.isVisible() is False
