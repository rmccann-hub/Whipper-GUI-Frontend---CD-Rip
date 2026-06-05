"""Tests for the AccurateRip drive-offset lookup adapter.

Cases span the five tiers (easy/medium/hard/edge/unexpected per
docs/testing.md), plus CSV-overlay behaviour, a never-raises property
test, and a regression test pinning the user's real drive (Pioneer
BDR-209D → +667) through the exact double-spaced string whipper emits.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from whipper_gui.adapters.accuraterip_offsets import (
    OffsetDatabase,
    _load_user_csv,
    normalize_drive_name,
)

# A small explicit table so lookup tests don't depend on the curated
# contents (which grow over time).
_ENTRIES = {
    "PIONEER BD-RW BDR-209D": 667,
    "PLEXTOR CD-R PREMIUM": 30,
    "HL-DT-ST DVDRAM GH24NSD1": 6,
}


def _db() -> OffsetDatabase:
    return OffsetDatabase(_ENTRIES)


# --- normalize_drive_name -------------------------------------------------


def test_normalize_combines_and_uppercases() -> None:  # easy
    assert normalize_drive_name("PIONEER", "BDR-209D") == "PIONEER BDR-209D"


def test_normalize_collapses_double_space() -> None:  # medium — whipper's real output
    # whipper prints "BD-RW  BDR-209D" (two spaces).
    assert (
        normalize_drive_name("PIONEER", "BD-RW  BDR-209D") == "PIONEER BD-RW BDR-209D"
    )


def test_normalize_is_case_insensitive() -> None:  # medium
    assert normalize_drive_name("pioneer", "bdr-209d") == "PIONEER BDR-209D"


def test_normalize_strips_atapi_prefix() -> None:  # hard
    assert normalize_drive_name("ATAPI", "iHAS124   B") == "IHAS124 B"


def test_normalize_handles_empty() -> None:  # edge
    assert normalize_drive_name("", "") == ""


# --- lookup ---------------------------------------------------------------


def test_lookup_exact_match() -> None:  # easy
    assert _db().lookup("PIONEER", "BDR-209D") == 667


def test_lookup_normalizes_before_matching() -> None:  # medium
    assert _db().lookup("pioneer", "BD-RW  BDR-209D") == 667


def test_lookup_unknown_drive_returns_none() -> None:  # edge
    assert _db().lookup("ACME", "Frobnicator 9000") is None


def test_lookup_empty_returns_none() -> None:  # edge
    assert _db().lookup("", "") is None


def test_lookup_model_only_fallback_single_hit() -> None:  # hard
    # Vendor omitted, but the model tail uniquely identifies one entry.
    assert _db().lookup("", "BDR-209D") == 667


def test_lookup_model_only_fallback_is_ambiguous_returns_none() -> None:  # unexpected
    # Two different drives, same offset value but distinct entries: a bare
    # model that matches neither key's tail must not guess.
    db = OffsetDatabase(
        {
            "VENDORA SUPERDRIVE X": 100,
            "VENDORB SUPERDRIVE X": 200,
        }
    )
    # "SUPERDRIVE X" is the tail of BOTH keys → ambiguous → None.
    assert db.lookup("", "SUPERDRIVE X") is None


def test_lookup_garbage_returns_none() -> None:  # unexpected
    assert _db().lookup("\x00\n\t", "%%%%") is None


# --- CSV overlay ----------------------------------------------------------


def test_user_csv_extends_and_overrides(tmp_path: Path) -> None:
    csv = tmp_path / "drive_offsets.csv"
    csv.write_text(
        "# user additions\n"
        "name,offset\n"  # header row, skipped
        "ACME Frobnicator 9000, -12\n"
        "PIONEER BD-RW BDR-209D, 999\n",  # overrides curated/explicit
        encoding="utf-8",
    )
    db = OffsetDatabase.load_default(user_path=csv)
    assert db.lookup("ACME", "Frobnicator 9000") == -12
    # The user file wins on conflicts.
    assert db.lookup("PIONEER", "BD-RW  BDR-209D") == 999


def test_user_csv_missing_file_is_curated_only() -> None:
    db = OffsetDatabase.load_default(user_path=Path("/nonexistent/nope.csv"))
    # Curated seed still present.
    assert db.lookup("PIONEER", "BD-RW  BDR-209D") == 667


def test_load_user_csv_skips_malformed_lines(tmp_path: Path) -> None:
    csv = tmp_path / "x.csv"
    csv.write_text(
        "good drive, 10\n"
        "this line has no offset\n"
        "bad, not-a-number\n"
        "\n"
        "# comment\n"
        "another, -5\n",
        encoding="utf-8",
    )
    entries = _load_user_csv(csv)
    assert entries == {"GOOD DRIVE": 10, "ANOTHER": -5}


# --- Regression: the user's real drive ------------------------------------


def test_default_db_knows_user_pioneer_bdr209d() -> None:
    """Regression: the exact double-spaced string `whipper drive list`
    emits for the tested Pioneer must resolve to +667 from the shipped
    table, with no user CSV."""
    db = OffsetDatabase.load_default(user_path=Path("/nonexistent.csv"))
    assert db.lookup("PIONEER", "BD-RW  BDR-209D") == 667


# --- Property: lookup never raises ----------------------------------------


@settings(max_examples=200, deadline=None)
@given(vendor=st.text(max_size=60), model=st.text(max_size=60))
def test_lookup_never_raises(vendor: str, model: str) -> None:
    result = _db().lookup(vendor, model)
    assert result is None or isinstance(result, int)
