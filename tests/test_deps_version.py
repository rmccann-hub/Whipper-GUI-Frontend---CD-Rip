"""Tests for whipper_gui.deps.version."""

from __future__ import annotations

from whipper_gui.deps.version import meets_minimum, parse_version


# --- parse_version ---


def test_parse_basic_semver() -> None:
    assert parse_version("whipper 0.10.0") == (0, 10, 0)


def test_parse_two_component_when_no_patch() -> None:
    assert parse_version("flac version 1.4") == (1, 4)


def test_parse_with_label_prefix() -> None:
    assert parse_version("Version: 2.11.5") == (2, 11, 5)


def test_parse_multiline_first_match_wins() -> None:
    assert parse_version("header\nv 0.7.1 of musicbrainzngs\n") == (0, 7, 1)


def test_parse_returns_none_when_no_match() -> None:
    assert parse_version("no version here") is None


def test_parse_double_digit_components() -> None:
    # The "0.10.0" trap — naive `\d` patterns parse as (0, 1, 0).
    assert parse_version("whipper 0.10.0") == (0, 10, 0)


# --- meets_minimum ---


def test_meets_minimum_equal_versions() -> None:
    assert meets_minimum((0, 10, 0), (0, 10, 0)) is True


def test_meets_minimum_higher_version() -> None:
    assert meets_minimum((1, 0, 0), (0, 10, 0)) is True


def test_meets_minimum_lower_version() -> None:
    assert meets_minimum((0, 9, 99), (0, 10, 0)) is False


def test_meets_minimum_pads_short_version() -> None:
    # (1, 2) should satisfy >= (1, 2, 0).
    assert meets_minimum((1, 2), (1, 2, 0)) is True


def test_meets_minimum_pads_short_minimum() -> None:
    assert meets_minimum((1, 2, 0), (1, 2)) is True


def test_meets_minimum_none_version() -> None:
    assert meets_minimum(None, (0, 1, 0)) is False
