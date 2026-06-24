# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the optional post-rip FLAC re-compression adapter.

The `flac` subprocess is injected (a fake runner), so these run with no real
binary. The contract mirrors flac_verify: never raise; distinguish "couldn't
run at all" (error) from "a file failed" (failures); and the atomic swap-in
must leave the original untouched whenever a file isn't successfully rewritten.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whipper_gui.adapters import flac_recompress
from whipper_gui.adapters.flac_recompress import (
    RecompressResult,
    recompress_flac_files,
)


def _make_flac(path: Path, content: bytes = b"original") -> Path:
    path.write_bytes(content)
    return path


def test_all_reencoded_swaps_in_the_temp(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac")
    b = _make_flac(tmp_path / "02.flac")
    seen: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        # Stand in for flac: write the (smaller) re-encoded output to the temp
        # path so the adapter has something to atomically swap in.
        seen.append(argv)
        Path(argv[-2]).write_bytes(b"smaller")  # argv[-2] is the `-o <tmp>` arg
        return 0

    result = recompress_flac_files([a, b], binary="flac", runner=runner)

    assert result.ok and result.ran
    assert result.reencoded == 2
    assert result.failures == ()
    # Each invocation is `flac -8 -e -p --verify --silent -f -o <tmp> <orig>`
    # (`-e -p` = exhaustive search: max compression, lossless, no decode cost).
    assert seen[0][:8] == [
        "flac",
        "-8",
        "-e",
        "-p",
        "--verify",
        "--silent",
        "-f",
        "-o",
    ]
    assert seen[0][-1] == str(a)
    # The originals were replaced with the re-encoded bytes; no temp left behind.
    assert a.read_bytes() == b"smaller"
    assert b.read_bytes() == b"smaller"
    assert not (tmp_path / "01.flac.recompress.tmp").exists()
    assert not (tmp_path / "02.flac.recompress.tmp").exists()


def test_nonzero_rc_leaves_original_untouched(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac", b"keep-me")

    def runner(argv: list[str]) -> int:
        # Pretend flac wrote a temp but then failed (nonzero exit). The original
        # must survive and the temp must be cleaned up — never swapped in.
        Path(argv[-2]).write_bytes(b"half-written")
        return 1

    result = recompress_flac_files([a], runner=runner)

    assert result.ran and not result.ok
    assert result.reencoded == 0
    assert result.failures == (a,)
    assert a.read_bytes() == b"keep-me"  # untouched
    assert not (tmp_path / "01.flac.recompress.tmp").exists()


def test_missing_temp_output_is_a_failure(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac", b"keep-me")

    def runner(argv: list[str]) -> int:
        return 0  # claims success but never wrote the temp file

    result = recompress_flac_files([a], runner=runner)

    assert result.failures == (a,)
    assert a.read_bytes() == b"keep-me"


def test_missing_binary_is_an_error_not_a_failure(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac")

    def runner(argv: list[str]) -> int:
        raise FileNotFoundError("flac")

    result = recompress_flac_files([a], runner=runner)

    assert not result.ran  # couldn't even run → error, not a per-file failure
    assert not result.ok
    assert result.failures == ()
    assert "not found" in result.error


def test_timeout_marks_the_file_failed_and_continues(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac", b"a-orig")
    b = _make_flac(tmp_path / "02.flac")

    def runner(argv: list[str]) -> int:
        if argv[-1].endswith("01.flac"):
            # Simulate flac leaving a partial temp behind, then timing out.
            Path(argv[-2]).write_bytes(b"partial")
            raise subprocess.TimeoutExpired(cmd="flac", timeout=300)
        Path(argv[-2]).write_bytes(b"smaller")
        return 0

    result = recompress_flac_files([a, b], runner=runner)

    assert result.ran  # a timeout is a per-file failure, not a hard abort
    assert result.reencoded == 1  # the second file still succeeded
    assert result.failures == (a,)
    assert a.read_bytes() == b"a-orig"  # untouched
    assert not (tmp_path / "01.flac.recompress.tmp").exists()  # partial cleaned up


def test_oserror_aborts_with_error(tmp_path: Path) -> None:
    a = _make_flac(tmp_path / "01.flac")

    def runner(argv: list[str]) -> int:
        raise OSError("permission denied")

    result = recompress_flac_files([a], runner=runner)

    assert not result.ran
    assert "could not run" in result.error


def test_failed_atomic_swap_leaves_original_and_marks_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _make_flac(tmp_path / "01.flac", b"keep-me")

    def runner(argv: list[str]) -> int:
        Path(argv[-2]).write_bytes(b"smaller")  # a good re-encode…
        return 0

    # …but the atomic swap-in fails (e.g. cross-device, permissions). The
    # original must survive and the file is reported failed, not lost.
    def boom(_src: object, _dst: object) -> None:
        raise OSError("EXDEV")

    monkeypatch.setattr(flac_recompress.os, "replace", boom)

    result = recompress_flac_files([a], runner=runner)

    assert result.ran and not result.ok
    assert result.failures == (a,)
    assert a.read_bytes() == b"keep-me"
    assert not (tmp_path / "01.flac.recompress.tmp").exists()  # temp cleaned up


def test_empty_input_is_a_clean_noop() -> None:
    result = recompress_flac_files([], runner=lambda argv: 0)
    assert result.ran and result.ok
    assert result.reencoded == 0
    assert result.failures == ()


def test_result_properties() -> None:
    assert RecompressResult().ran and RecompressResult().ok
    assert RecompressResult(reencoded=3).ok
    assert not RecompressResult(failures=(Path("x"),)).ok
    assert RecompressResult(failures=(Path("x"),)).ran  # ran, just had a failure
    assert not RecompressResult(error="boom").ran
    assert not RecompressResult(error="boom").ok
