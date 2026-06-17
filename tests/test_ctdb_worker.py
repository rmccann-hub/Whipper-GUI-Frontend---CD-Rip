# SPDX-License-Identifier: GPL-3.0-only
"""Tests for whipper_gui.workers.ctdb_worker.CtdbVerifyWorker.

Drives the worker's run() synchronously (Qt signals are callable without an
event loop) with an injected fake CTDB client + fake decoder/probe, so nothing
touches the network or shells out to flac/metaflac.
"""

from __future__ import annotations

import threading
import zlib
from pathlib import Path

from whipper_gui.adapters.ctdb_client import (
    CTDBClient,
    CtdbEntry,
    CtdbLookupResult,
)
from whipper_gui.ctdb.toc import DiscToc
from whipper_gui.ctdb.verify import CtdbVerifyResult, Verdict
from whipper_gui.workers.ctdb_worker import CtdbVerifyWorker


class _FakeClient(CTDBClient):
    """Returns a canned lookup result; records the TOC it was queried with."""

    def __init__(self, result: CtdbLookupResult) -> None:
        self._result = result
        self.queried_toc: DiscToc | None = None

    def lookup(self, toc: DiscToc) -> CtdbLookupResult:
        self.queried_toc = toc
        return self._result


def _make_flacs(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for i in range(1, count + 1):
        p = tmp_path / f"{i:02d} - Track.flac"
        p.write_bytes(b"")  # content is irrelevant; decoder/probe are injected
        paths.append(p)
    return paths


def _collect(worker: CtdbVerifyWorker) -> list[CtdbVerifyResult]:
    results: list[CtdbVerifyResult] = []
    worker.finished.connect(results.append)
    return results


def test_not_in_database_emits_not_in_db_verdict(tmp_path: Path) -> None:
    _make_flacs(tmp_path, 2)
    client = _FakeClient(CtdbLookupResult())  # empty → not in DB
    worker = CtdbVerifyWorker(
        client, tmp_path, samples_probe=lambda _p: 1000, decoder=lambda _p: b"x"
    )
    results = _collect(worker)

    worker.run()

    assert len(results) == 1
    assert results[0].verdict is Verdict.NOT_IN_DATABASE
    assert client.queried_toc is not None  # the lookup happened


def test_matching_crc_emits_match(tmp_path: Path) -> None:
    _make_flacs(tmp_path, 2)
    pcm = b"\x01\x02\x03\x04"
    whole_disc_crc = zlib.crc32(pcm * 2) & 0xFFFFFFFF  # two tracks concatenated
    client = _FakeClient(
        CtdbLookupResult(entries=(CtdbEntry(crc=whole_disc_crc, confidence=42),))
    )
    worker = CtdbVerifyWorker(
        client,
        tmp_path,
        samples_probe=lambda _p: 1000,
        decoder=lambda _p: pcm,
    )
    results = _collect(worker)

    worker.run()

    assert len(results) == 1
    out = results[0]
    assert out.verdict is Verdict.MATCH
    assert out.confidence == 42
    assert out.our_crc == whole_disc_crc


def test_no_flac_files_emits_lookup_error(tmp_path: Path) -> None:
    client = _FakeClient(CtdbLookupResult())
    worker = CtdbVerifyWorker(client, tmp_path)  # empty dir
    results = _collect(worker)

    worker.run()

    assert len(results) == 1
    assert results[0].verdict is Verdict.LOOKUP_ERROR
    assert "no flac" in results[0].message.lower()
    assert client.queried_toc is None  # never reached the lookup


def test_waits_for_post_rip_thread_before_verifying(tmp_path: Path) -> None:
    """When a post-rip thread is supplied, the worker joins it before decoding
    (so it never reads a FLAC while metaflac is mid-rewrite)."""
    _make_flacs(tmp_path, 1)
    release = threading.Event()
    order: list[str] = []

    def post_rip() -> None:
        release.wait(5)  # block until the test releases us
        order.append("post_rip_done")

    pr = threading.Thread(target=post_rip, daemon=True)
    pr.start()

    def decoder(_p: Path) -> bytes:
        order.append("decode")
        return b"\x00\x00\x00\x00"

    # An in-DB result so the decoder is actually reached.
    client = _FakeClient(CtdbLookupResult(entries=(CtdbEntry(crc=123, confidence=1),)))
    worker = CtdbVerifyWorker(
        client,
        tmp_path,
        samples_probe=lambda _p: 1000,
        decoder=decoder,
        wait_for=pr,
    )

    # Run the worker on its own thread so it can block on the join; then
    # release the post-rip thread and confirm the decode happened strictly
    # after the post-rip thread finished. (The finished signal is queued
    # cross-thread without an event loop here, so the verdict emission itself
    # is asserted in the direct-call tests above + the main_window test.)
    run_thread = threading.Thread(target=worker.run, daemon=True)
    run_thread.start()
    release.set()
    run_thread.join(5)

    assert order == ["post_rip_done", "decode"]  # never decode mid-rewrite
