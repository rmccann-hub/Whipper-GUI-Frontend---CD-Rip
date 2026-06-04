"""Tests for whipper_gui.workers.mb_worker.

We drive the worker synchronously without a real QThread or event loop
— the same approach as the rip_worker tests. The MusicBrainzClient is
replaced with a fake; we never touch the real MB API.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    MusicBrainzQueryError,
    ReleaseDetail,
    ReleaseSummary,
    TocSignature,
    TrackSummary,
)
from whipper_gui.workers.mb_worker import MusicBrainzWorker

# `qapp` fixture comes from tests/conftest.py — see test_rip_worker.py
# for the reason worker tests adopt the wider QApplication fixture.


# --- Fake client ----------------------------------------------------------


class _FakeClient(MusicBrainzClient):
    """Configurable fake MusicBrainzClient.

    Each method can be set to either return a value or raise an
    exception; tests pick the behavior they need.
    """

    def __init__(self) -> None:
        self.disc_id_calls: list[str] = []
        self.toc_calls: list[TocSignature] = []
        self.mbid_calls: list[str] = []
        self._disc_id_result: list[ReleaseSummary] = []
        self._toc_result: list[ReleaseSummary] = []
        self._mbid_result: ReleaseDetail | None = None
        self._raise: dict[str, Exception] = {}

    # Configuration helpers (not part of the ABC).
    def set_disc_id_result(self, value: list[ReleaseSummary]) -> None:
        self._disc_id_result = value

    def set_toc_result(self, value: list[ReleaseSummary]) -> None:
        self._toc_result = value

    def set_mbid_result(self, value: ReleaseDetail) -> None:
        self._mbid_result = value

    def raise_in(self, method: str, exc: Exception) -> None:
        self._raise[method] = exc

    # ABC implementations.
    def releases_by_disc_id(self, disc_id: str) -> list[ReleaseSummary]:
        self.disc_id_calls.append(disc_id)
        if "disc_id" in self._raise:
            raise self._raise["disc_id"]
        return self._disc_id_result

    def releases_by_toc(self, toc: TocSignature) -> list[ReleaseSummary]:
        self.toc_calls.append(toc)
        if "toc" in self._raise:
            raise self._raise["toc"]
        return self._toc_result

    def release_by_mbid(self, mbid: str) -> ReleaseDetail:
        self.mbid_calls.append(mbid)
        if "mbid" in self._raise:
            raise self._raise["mbid"]
        assert self._mbid_result is not None
        return self._mbid_result

    def set_user_agent(self, app: str, version: str, contact: str) -> None:
        pass


# --- Signal collector -----------------------------------------------------


class _Signals:
    def __init__(self) -> None:
        self.releases_returned: list[list[ReleaseSummary]] = []
        self.release_returned: list[ReleaseDetail] = []
        self.errors: list[str] = []

    def attach(self, worker: MusicBrainzWorker) -> None:
        worker.releases_returned.connect(self.releases_returned.append)
        worker.release_returned.connect(self.release_returned.append)
        worker.error.connect(self.errors.append)


def _summary(mbid: str = "x") -> ReleaseSummary:
    return ReleaseSummary(mbid=mbid, title="T", artist_credit="A")


def _detail() -> ReleaseDetail:
    return ReleaseDetail(
        summary=_summary(),
        tracks=(TrackSummary(number=1, title="Track 1"),),
    )


# --- lookup_disc_id -------------------------------------------------------


def test_lookup_disc_id_emits_releases(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.set_disc_id_result([_summary("a"), _summary("b")])
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.lookup_disc_id("any-disc")

    assert client.disc_id_calls == ["any-disc"]
    assert len(sigs.releases_returned) == 1
    assert [r.mbid for r in sigs.releases_returned[0]] == ["a", "b"]
    assert sigs.errors == []


def test_lookup_disc_id_emits_error_on_failure(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.raise_in("disc_id", MusicBrainzQueryError("network down"))
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.lookup_disc_id("any-disc")

    assert sigs.releases_returned == []
    assert sigs.errors == ["network down"]


def test_lookup_disc_id_empty_result_still_emits(
    qapp: QApplication,
) -> None:
    """No matches isn't an error — picker just shows empty candidates."""
    client = _FakeClient()
    client.set_disc_id_result([])
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.lookup_disc_id("nothing")

    assert sigs.releases_returned == [[]]
    assert sigs.errors == []


# --- lookup_toc -----------------------------------------------------------


def test_lookup_toc_passes_signature_through(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.set_toc_result([_summary("toc-match")])
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    toc = TocSignature(
        first_track=1,
        last_track=2,
        lead_out_sector=12345,
        track_offsets=(150, 4567),
    )
    worker.lookup_toc(toc)

    assert client.toc_calls == [toc]
    assert [r.mbid for r in sigs.releases_returned[0]] == ["toc-match"]


def test_lookup_toc_emits_error_on_failure(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.raise_in("toc", MusicBrainzQueryError("rate limited"))
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.lookup_toc(TocSignature(1, 1, 100, (150,)))

    assert sigs.errors == ["rate limited"]
    assert sigs.releases_returned == []


# --- fetch_release --------------------------------------------------------


def test_fetch_release_emits_release_detail(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.set_mbid_result(_detail())
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.fetch_release("some-mbid")

    assert client.mbid_calls == ["some-mbid"]
    assert len(sigs.release_returned) == 1
    assert sigs.release_returned[0].tracks[0].title == "Track 1"


def test_fetch_release_emits_error_on_failure(
    qapp: QApplication,
) -> None:
    client = _FakeClient()
    client.raise_in("mbid", MusicBrainzQueryError("server gone"))
    worker = MusicBrainzWorker(client)
    sigs = _Signals()
    sigs.attach(worker)

    worker.fetch_release("any-mbid")

    assert sigs.errors == ["server gone"]
    assert sigs.release_returned == []
