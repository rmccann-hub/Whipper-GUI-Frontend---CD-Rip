# SPDX-License-Identifier: GPL-3.0-only
"""Tests for platterpus.adapters.ctdb_client — URL build + XML parse + lookup."""

from __future__ import annotations

import pytest

from platterpus.adapters.ctdb_client import (
    CtdbHttpImpl,
    CtdbLookupError,
    CtdbLookupResult,
    parse_lookup_response,
)
from platterpus.ctdb.toc import DiscToc

_TOC = DiscToc(track_offsets=(150, 18172), leadout=295716)


def test_build_url_has_expected_params() -> None:
    url = CtdbHttpImpl().build_url(_TOC)
    # HTTP, not HTTPS: the host has no valid TLS cert and the reference client
    # uses http:// (see CTDB_SCHEME note in ctdb_client). KDD-16 / hardware.
    assert url.startswith("http://db.cuetools.net/lookup2.php?")
    assert "version=3" in url
    assert "ctdb=1" in url
    assert "toc=150%3A18172%3A295716" in url  # ':' is URL-encoded


def test_parse_empty_response_means_not_in_db() -> None:
    result = parse_lookup_response(b"<ctdb></ctdb>")
    assert isinstance(result, CtdbLookupResult)
    assert result.in_database is False
    assert result.entries == ()


def test_parse_entry_hex_crc_and_fields() -> None:
    xml = (
        b'<ctdb><entry crc="a1b2c3d4" confidence="7" npar="8" id="abc" '
        b'hasParity="1" trackcrcs="0011 22ff"/></ctdb>'
    )
    result = parse_lookup_response(xml)
    assert result.in_database is True
    (entry,) = result.entries
    assert entry.crc == 0xA1B2C3D4
    assert entry.confidence == 7
    assert entry.npar == 8
    assert entry.has_parity is True
    assert entry.entry_id == "abc"
    assert entry.track_crcs == (0x0011, 0x22FF)


def test_parse_tolerates_missing_attributes() -> None:
    result = parse_lookup_response(b"<ctdb><entry/></ctdb>")
    (entry,) = result.entries
    assert entry.crc is None
    assert entry.confidence == 0
    assert entry.has_parity is False


def test_parse_bad_xml_raises_lookup_error() -> None:
    with pytest.raises(CtdbLookupError):
        parse_lookup_response(b"<not closed")


def test_lookup_uses_injected_fetcher() -> None:
    canned = b'<ctdb><entry crc="00000001" confidence="2"/></ctdb>'
    seen: list[str] = []

    def fake_fetch(url: str) -> bytes:
        seen.append(url)
        return canned

    client = CtdbHttpImpl(fetcher=fake_fetch)
    result = client.lookup(_TOC)
    assert seen and seen[0].startswith("http://db.cuetools.net/")
    assert result.entries[0].crc == 1
    assert result.entries[0].confidence == 2


def test_lookup_wraps_transport_errors() -> None:
    def boom(url: str) -> bytes:
        raise OSError("network down")

    with pytest.raises(CtdbLookupError):
        CtdbHttpImpl(fetcher=boom).lookup(_TOC)
