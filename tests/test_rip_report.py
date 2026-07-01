"""Tests for platterpus.rip_report (the machine-readable JSON rip report)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from platterpus.ctdb.verify import CtdbVerifyResult, Verdict
from platterpus.parsers.rip_log import (
    AccurateRipResult,
    RipLog,
    RippingInfo,
    TrackResult,
)
from platterpus.rip_report import (
    REPORT_SCHEMA_VERSION,
    build_debug_log,
    build_report,
    build_timing,
    report_path_for,
    report_to_json,
    write_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CYANRIP_REFERENCE = (
    _REPO_ROOT
    / "output_reference"
    / "cyanrip_flac"
    / "cyanrip_flac_police_classics.log"
)


def _sample_log() -> RipLog:
    return RipLog(
        log_creator="cyanrip 0.9.3",
        creation_date="2026-06-28",
        ripping_info=RippingInfo(
            drive="PIONEER BD-RW BDR-209D",
            defeat_audio_cache=True,
            read_offset_correction=667,
        ),
        tracks=(
            TrackResult(
                number=1,
                filename="01 - Roxanne.flac",
                test_crc="B0D122E7",
                copy_crc="B0D122E7",
                status="ripped successfully",
                accuraterip_v2=AccurateRipResult(
                    version=2,
                    result="accurately ripped",
                    confidence=200,
                    local_crc="22B9924D",
                ),
            ),
            TrackResult(number=2, copy_crc="DEADBEEF", status="ripped successfully"),
        ),
        accuraterip_summary="1/2 tracks ripped accurately (AccurateRip)",
        health_status="No errors occurred",
    )


def test_report_envelope_and_verdict() -> None:
    report = build_report(_sample_log(), generated_at="2026-06-28T12:00:00")
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["generator"]["name"] == "platterpus"
    assert report["generated_at"] == "2026-06-28T12:00:00"
    # Verdict reuses the shared rule: 1 of 2 verified → "warn".
    assert report["verdict"]["level"] == "warn"
    assert "1 of 2" in report["verdict"]["message"]
    assert report["rip"]["read_offset_correction"] == 667


def test_per_track_fields_use_shared_verified_rule() -> None:
    report = build_report(_sample_log())
    t1, t2 = report["tracks"]
    assert t1["number"] == 1
    assert t1["copy_crc"] == "B0D122E7"
    assert t1["accuraterip_verified"] is True  # confidence 200
    assert t1["accuraterip"]["v2"]["confidence"] == 200
    # Track 2 has a Copy CRC but no AccurateRip match → not verified.
    assert t2["accuraterip_verified"] is False
    assert t2["accuraterip"]["v1"] is None


def test_timing_section_absent_by_default() -> None:
    # No timing passed → the key is present but null (a consumer can rely on
    # the key always existing).
    report = build_report(_sample_log())
    assert report["timing"] is None


def test_timing_section_records_actual_and_estimate() -> None:
    timing = build_timing(
        9896,  # the real 2h44m56s rip
        estimated_seconds=2100,  # cyanrip's "~35m" ETA
        started_at="2026-06-29T18:51:44",
        finished_at="2026-06-29T21:36:40",
    )
    report = build_report(_sample_log(), timing=timing)
    t = report["timing"]
    assert t["elapsed_seconds"] == 9896
    assert t["elapsed_human"] == "2h 44m 56s"
    assert t["estimated_seconds"] == 2100
    assert t["estimated_human"] == "35m 0s"
    assert t["started_at"] == "2026-06-29T18:51:44"
    assert t["finished_at"] == "2026-06-29T21:36:40"
    assert "re-read" in t["estimate_source"]


def test_timing_omits_estimate_when_unknown() -> None:
    # A rip with no ETA seen (e.g. cancelled early) still records the actual
    # elapsed, but carries no estimate keys.
    timing = build_timing(120, estimated_seconds=None)
    assert timing["elapsed_seconds"] == 120
    assert timing["elapsed_human"] == "2m 0s"
    assert "estimated_seconds" not in timing
    assert "estimate_source" not in timing


def test_timing_handles_missing_elapsed() -> None:
    # Defensive: a None elapsed degrades to "unknown" rather than raising.
    timing = build_timing(None)
    assert timing["elapsed_seconds"] is None
    assert timing["elapsed_human"] == "unknown"


def test_debug_section_absent_by_default() -> None:
    report = build_report(_sample_log())
    assert report["debug"] is None


def test_debug_section_embeds_session_log() -> None:
    debug = build_debug_log(["line one", "line two"], truncated=False)
    report = build_report(_sample_log(), debug_log=debug)
    assert report["debug"]["lines"] == ["line one", "line two"]
    assert report["debug"]["truncated"] is False
    assert "excluding other albums" in report["debug"]["scope"]


def test_debug_section_notes_truncation() -> None:
    debug = build_debug_log(["kept"], truncated=True)
    assert build_report(_sample_log(), debug_log=debug)["debug"]["truncated"] is True


# --- Verification block + checksums (0.4.5, schema v2) -------------------


def test_verification_block_present_but_empty_by_default() -> None:
    report = build_report(_sample_log())
    assert report["verification"] == {"flac_integrity": None, "transcode": None}
    assert report["checksums"] is None


def test_flac_integrity_result_serialized() -> None:
    from platterpus.adapters.flac_verify import FlacVerifyResult

    report = build_report(
        _sample_log(), flac_verify_result=FlacVerifyResult(checked=14)
    )
    fi = report["verification"]["flac_integrity"]
    assert fi["ran"] is True and fi["ok"] is True and fi["checked"] == 14
    assert fi["failures"] == [] and fi["error"] is None


def test_flac_integrity_failure_serialized() -> None:
    from platterpus.adapters.flac_verify import FlacVerifyResult

    result = FlacVerifyResult(checked=14, failures=(Path("bad.flac"),))
    fi = build_report(_sample_log(), flac_verify_result=result)["verification"][
        "flac_integrity"
    ]
    assert fi["ok"] is False and fi["failures"] == ["bad.flac"]


def test_transcode_result_serialized() -> None:
    from platterpus.adapters.transcode import TranscodeResult

    report = build_report(
        _sample_log(), transcode_result=TranscodeResult(transcoded=14)
    )
    tc = report["verification"]["transcode"]
    assert tc["ran"] is True and tc["ok"] is True and tc["transcoded"] == 14


def test_checksums_embedded_in_report() -> None:
    sums = {"01 - A.flac": "abc123", "01 - A.mp3": "def456"}
    report = build_report(_sample_log(), checksums=sums)
    assert report["checksums"] == sums


def test_schema_version_is_v2() -> None:
    assert REPORT_SCHEMA_VERSION == 2
    assert build_report(_sample_log())["schema_version"] == 2


def test_debug_section_caps_embedded_lines_and_keeps_most_recent() -> None:
    """A marathon session must not bloat the report (or its on-GUI-thread
    re-serialization): the embedded log is capped to the most-recent lines and
    marked truncated; log.txt keeps the full history."""
    from platterpus.rip_report import _MAX_EMBEDDED_LOG_LINES

    lines = [f"line {i}" for i in range(_MAX_EMBEDDED_LOG_LINES + 500)]
    debug = build_debug_log(lines)
    assert len(debug["lines"]) == _MAX_EMBEDDED_LOG_LINES
    assert debug["truncated"] is True
    # The most RECENT lines are kept (closest to the just-finished rip).
    assert debug["lines"][-1] == lines[-1]
    assert debug["lines"][0] == lines[500]


def test_ctdb_section_serialized_when_present() -> None:
    result = CtdbVerifyResult(
        Verdict.MATCH,
        confidence=8,
        our_crc=0x22B9924D,
        matched_crc=0x22B9924D,
        message="verified against CTDB (confidence 8)",
        crc_validated=False,
    )
    report = build_report(_sample_log(), ctdb_result=result)
    assert report["ctdb"]["verdict"] == "match"
    assert report["ctdb"]["confidence"] == 8
    # An unvalidated match is honestly NOT trustworthy yet (KDD-16).
    assert report["ctdb"]["trustworthy"] is False
    # CRCs are auditable (hex, matching the per-track AccurateRip CRC style).
    assert report["ctdb"]["our_crc"] == "22B9924D"
    assert report["ctdb"]["matched_crc"] == "22B9924D"
    assert "confidence 8" in report["ctdb"]["message"]
    # Absent CTDB → null section.
    assert build_report(_sample_log())["ctdb"] is None


def test_rewrite_adds_ctdb_section_to_same_file(tmp_path: Path) -> None:
    # Mirrors the GUI: write the report at rip-finish (no CTDB), then re-write
    # the SAME file once the async CTDB verify lands. The final file carries it.
    log_file = tmp_path / "Album.log"
    log_file.write_text("(human log)")
    out = write_report(_sample_log(), log_file)
    assert json.loads(out.read_text())["ctdb"] is None

    result = CtdbVerifyResult(Verdict.MATCH, confidence=8)
    again = write_report(_sample_log(), log_file, ctdb_result=result)
    assert again == out  # same path, overwritten
    assert json.loads(out.read_text())["ctdb"]["verdict"] == "match"


def test_report_is_valid_json_roundtrip() -> None:
    text = report_to_json(build_report(_sample_log()))
    parsed = json.loads(text)
    assert parsed["tracks"][0]["copy_crc"] == "B0D122E7"
    assert text.endswith("\n")


def test_build_never_raises_on_empty_or_garbage() -> None:
    assert build_report(RipLog())["schema_version"] == REPORT_SCHEMA_VERSION
    assert (
        build_report(object())["schema_version"] == REPORT_SCHEMA_VERSION
    )  # any shape


def test_build_returns_minimal_envelope_if_internals_raise(monkeypatch) -> None:
    # Force the inner build to blow up; the report must still come back as a
    # valid minimal envelope, never propagate the error into the rip path.
    import platterpus.rip_report as mod

    def boom(*_a, **_k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(mod, "_build", boom)
    report = build_report(_sample_log())
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["error"] == "report could not be built"


def test_write_report_returns_none_on_oserror(tmp_path: Path) -> None:
    # Parent dir doesn't exist → OSError → returns None (best-effort, no raise).
    missing = tmp_path / "nope" / "Album.log"
    assert write_report(_sample_log(), missing) is None


def test_write_report_writes_beside_the_log(tmp_path: Path) -> None:
    log_file = tmp_path / "Album.log"
    log_file.write_text("(human log)")
    out = write_report(_sample_log(), log_file)
    assert out == report_path_for(log_file) == tmp_path / "Album.platterpus.json"
    assert out.is_file()
    assert json.loads(out.read_text())["generator"]["name"] == "platterpus"


# --- CLI: scripts/rip_report.py -------------------------------------------


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "rip_report_cli", _REPO_ROOT / "scripts" / "rip_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_emits_json_for_committed_cyanrip_log(capsys) -> None:
    cli = _load_cli()
    rc = cli.main([str(_CYANRIP_REFERENCE)])
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)
    assert parsed["generator"]["name"] == "platterpus"
    assert len(parsed["tracks"]) == 14  # the Police disc


def test_cli_missing_file_returns_2(tmp_path: Path) -> None:
    cli = _load_cli()
    assert cli.main([str(tmp_path / "nope.log")]) == 2


def test_cli_refuses_an_eac_log(tmp_path: Path, capsys) -> None:
    # An EAC log fed here would otherwise parse to an empty whipper RipLog and
    # silently emit a 0-track report with exit 0 — refuse with a clear message.
    cli = _load_cli()
    eac = tmp_path / "eac.log"
    eac.write_text(
        "Exact Audio Copy V1.8\n\nTrack  1\n\n     Copy CRC B0D122E7\n",
        encoding="utf-8",
    )
    rc = cli.main([str(eac)])
    assert rc == 2
    assert "EAC log" in capsys.readouterr().err
