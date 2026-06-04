"""Tests for whipper_gui.adapters.musicbrainz_client.

musicbrainzngs is monkeypatched so tests run offline. The shapes of the
fake responses match what real `musicbrainzngs.get_releases_by_discid`
and `get_release_by_id` return — verified against musicbrainzngs 0.7.1
docs and the upstream return-value shapes.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import musicbrainzngs
import pytest

from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    MusicBrainzNgsImpl,
    MusicBrainzQueryError,
    ReleaseDetail,
    ReleaseSummary,
    TocSignature,
    TrackSummary,
)

# --- Sample MB response shapes --------------------------------------------


def _sample_disc_response() -> dict[str, Any]:
    """Shape returned by get_releases_by_discid for a successful lookup."""
    return {
        "disc": {
            "id": "abc-def-disc",
            "release-list": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "title": "The Dark Side of the Moon",
                    "artist-credit": [
                        {"artist": {"name": "Pink Floyd"}, "name": "Pink Floyd"},
                    ],
                    "date": "1973-03-01",
                    "country": "GB",
                    "disambiguation": "remastered",
                    "medium-list": [
                        {
                            "format": "CD",
                            "track-count": "10",
                            "track-list": [],
                        }
                    ],
                    "label-info-list": [
                        {
                            "label": {"name": "Harvest"},
                            "catalog-number": "SHVL 804",
                        }
                    ],
                },
            ],
        }
    }


def _sample_release_by_id() -> dict[str, Any]:
    """Shape returned by get_release_by_id with recordings includes."""
    return {
        "release": {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "The Dark Side of the Moon",
            "artist-credit": [
                {"artist": {"name": "Pink Floyd"}, "name": "Pink Floyd"},
            ],
            "date": "1973-03-01",
            "country": "GB",
            "medium-list": [
                {
                    "format": "CD",
                    "track-count": "2",
                    "track-list": [
                        {
                            "position": "1",
                            "length": "67000",
                            "recording": {
                                "title": "Speak to Me",
                                "length": "67000",
                                "artist-credit": [
                                    {
                                        "artist": {"name": "Pink Floyd"},
                                        "name": "Pink Floyd",
                                    },
                                ],
                            },
                        },
                        {
                            "position": "2",
                            "length": "165000",
                            "recording": {
                                "title": "Breathe",
                                "length": "165000",
                                "artist-credit": [
                                    {
                                        "artist": {"name": "Pink Floyd"},
                                        "name": "Pink Floyd",
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
            "label-info-list": [],
        }
    }


# --- Fixtures --------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> MusicBrainzNgsImpl:
    """A constructed client with `set_useragent` stubbed out."""
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        musicbrainzngs,
        "set_useragent",
        lambda app, ver, ctx: calls.append((app, ver, ctx)),
    )
    impl = MusicBrainzNgsImpl(
        app="whipper-gui", version="0.0.1", contact="test@example"
    )
    # Make the call list accessible to tests that care.
    impl._test_useragent_calls = calls  # type: ignore[attr-defined]
    return impl


# --- Construction ----------------------------------------------------------


def test_construction_sets_useragent(client: MusicBrainzNgsImpl) -> None:
    calls = client._test_useragent_calls  # type: ignore[attr-defined]
    assert calls == [("whipper-gui", "0.0.1", "test@example")]


def test_set_useragent_method_works_after_construction(
    client: MusicBrainzNgsImpl,
) -> None:
    client.set_user_agent("whipper-gui", "0.0.2", "other@example")
    calls = client._test_useragent_calls  # type: ignore[attr-defined]
    assert calls[-1] == ("whipper-gui", "0.0.2", "other@example")


# --- releases_by_disc_id ---------------------------------------------------


def test_releases_by_disc_id_parses_summary_fields(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        musicbrainzngs,
        "get_releases_by_discid",
        lambda *a, **kw: _sample_disc_response(),
    )

    results = client.releases_by_disc_id("abc-def-disc")

    assert len(results) == 1
    r = results[0]
    assert r.mbid == "11111111-1111-1111-1111-111111111111"
    assert r.title == "The Dark Side of the Moon"
    assert r.artist_credit == "Pink Floyd"
    assert r.date == "1973-03-01"
    assert r.country == "GB"
    assert r.track_count == 10
    assert r.medium_format == "CD"
    assert r.label == "Harvest"
    assert r.catalog_number == "SHVL 804"
    assert r.disambiguation == "remastered"


def test_releases_by_disc_id_returns_empty_on_404(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MB returning 404 means "no match" — not an error from the GUI's
    perspective. The picker just shows an empty candidate list."""

    class FakeCause:
        code = 404

    def boom(*a: Any, **kw: Any) -> Any:
        exc = musicbrainzngs.ResponseError("not found")
        exc.cause = FakeCause()  # type: ignore[attr-defined]
        raise exc

    monkeypatch.setattr(musicbrainzngs, "get_releases_by_discid", boom)

    assert client.releases_by_disc_id("no-match") == []


def test_releases_by_disc_id_raises_on_other_errors(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise musicbrainzngs.WebServiceError("connection refused")

    monkeypatch.setattr(musicbrainzngs, "get_releases_by_discid", boom)

    with pytest.raises(MusicBrainzQueryError) as info:
        client.releases_by_disc_id("xxx")
    assert "connection refused" in str(info.value)


# --- releases_by_toc -------------------------------------------------------


def test_releases_by_toc_passes_toc_query_string(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_call(disc_id: str, **kwargs: Any) -> Any:
        captured["disc_id"] = disc_id
        captured["kwargs"] = kwargs
        return _sample_disc_response()

    monkeypatch.setattr(musicbrainzngs, "get_releases_by_discid", fake_call)

    toc = TocSignature(
        first_track=1,
        last_track=2,
        lead_out_sector=33487,
        track_offsets=(150, 16414),
    )
    client.releases_by_toc(toc)

    assert captured["disc_id"] == "-"  # MB placeholder when only `toc` matters
    assert captured["kwargs"]["toc"] == "1 2 33487 150 16414"


# --- release_by_mbid -------------------------------------------------------


def test_release_by_mbid_returns_detail_with_tracks(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        musicbrainzngs,
        "get_release_by_id",
        lambda *a, **kw: _sample_release_by_id(),
    )

    detail = client.release_by_mbid("11111111-1111-1111-1111-111111111111")

    assert isinstance(detail, ReleaseDetail)
    assert detail.summary.title == "The Dark Side of the Moon"
    assert detail.summary.track_count == 2
    assert len(detail.tracks) == 2
    assert detail.tracks[0].number == 1
    assert detail.tracks[0].title == "Speak to Me"
    assert detail.tracks[0].length_ms == 67000
    assert detail.tracks[1].number == 2
    assert detail.tracks[1].title == "Breathe"


def test_release_by_mbid_raises_on_webservice_error(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise musicbrainzngs.WebServiceError("server down")

    monkeypatch.setattr(musicbrainzngs, "get_release_by_id", boom)

    with pytest.raises(MusicBrainzQueryError):
        client.release_by_mbid("any-mbid")


# --- TocSignature.to_query -------------------------------------------------


def test_toc_signature_renders_query_string() -> None:
    toc = TocSignature(
        first_track=1,
        last_track=3,
        lead_out_sector=50000,
        track_offsets=(150, 12345, 28900),
    )
    assert toc.to_query() == "1 3 50000 150 12345 28900"


# --- Artist credit rendering ----------------------------------------------


def test_artist_credit_handles_joining_strings(
    client: MusicBrainzNgsImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MB's artist-credit list interleaves artist dicts with joining
    strings (e.g., ' feat. '). The renderer must concatenate them."""

    response = {
        "disc": {
            "release-list": [
                {
                    "id": "x",
                    "title": "Single",
                    "artist-credit": [
                        {"artist": {"name": "Artist A"}, "name": "Artist A"},
                        " feat. ",
                        {"artist": {"name": "Artist B"}, "name": "Artist B"},
                    ],
                    "medium-list": [],
                    "label-info-list": [],
                }
            ]
        }
    }
    monkeypatch.setattr(
        musicbrainzngs, "get_releases_by_discid", lambda *a, **kw: response
    )

    summaries = client.releases_by_disc_id("x")
    assert summaries[0].artist_credit == "Artist A feat. Artist B"


# --- ABC discipline -------------------------------------------------------


def test_abstract_base_blocks_instantiation() -> None:
    with pytest.raises(TypeError):
        MusicBrainzClient()  # type: ignore[abstract]


# --- Dataclass invariants -------------------------------------------------


def test_release_summary_is_frozen() -> None:
    s = ReleaseSummary(mbid="x", title="t", artist_credit="a")
    with pytest.raises(FrozenInstanceError):
        s.title = "z"  # type: ignore[misc]


def test_track_summary_is_frozen() -> None:
    t = TrackSummary(number=1, title="x")
    with pytest.raises(FrozenInstanceError):
        t.title = "z"  # type: ignore[misc]
