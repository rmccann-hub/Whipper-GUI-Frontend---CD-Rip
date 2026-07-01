"""Machine-readable (JSON) rip report — the structured companion to the log.

Deep-research lesson (docs/ux-design-principles.md #2, "two outputs every
time"): a trustworthy tool should emit both a human-readable narrative *and* a
machine-readable structure, so the result can be re-verified, fed to QA/repair
tooling, or attached to a support thread later. Platterpus already has the human
log (the backend's `.log`); this adds the JSON.

`build_report` is pure and **never raises** (mirrors the parser/renderer
discipline): a malformed or partial ``RipLog`` yields a best-effort report with
a valid envelope rather than blowing up the post-rip path. The whole-disc
verdict reuses :func:`platterpus.verdict.accuraterip_verdict` and the per-track
flag reuses :func:`track_accuraterip_verified`, so the JSON can never disagree
with the on-screen banner about what "verified" means.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from platterpus import __version__
from platterpus.parsers.rip_log import track_accuraterip_verified
from platterpus.verdict import accuraterip_verdict

log = logging.getLogger(__name__)

# Bump when the JSON shape changes in a way a consumer must notice.
# v2 (0.4.5): added the `verification` block (FLAC-integrity + transcode outcomes
# beside CTDB) and per-file `checksums` — the maintainer's "one debug file" rule
# means everything extra lives here, not in extra sidecars.
REPORT_SCHEMA_VERSION: int = 2

# Cap on how many session-log lines the report embeds. A normal session is a few
# hundred lines (negligible); but the in-memory buffer is bounded at tens of
# thousands, and embedding all of those would make the report a multi-MB file
# that's also re-serialized on the GUI thread on every CTDB re-write (~100ms /
# ~5MB in the worst case — measured). We keep the most RECENT lines (closest to
# this rip) and point at log.txt for the complete history. Plenty for a report.
_MAX_EMBEDDED_LOG_LINES: int = 2000


def build_report(
    rip_log: object,
    *,
    ctdb_result: object | None = None,
    flac_verify_result: object | None = None,
    transcode_result: object | None = None,
    checksums: dict | None = None,
    generated_at: str = "",
    timing: dict | None = None,
    debug_log: dict | None = None,
) -> dict:
    """Return a structured, versioned summary of a rip as a plain dict.

    ``generated_at`` is supplied by the caller (an ISO-8601 timestamp) so this
    stays pure and deterministic. ``ctdb_result`` is an optional
    :class:`~platterpus.ctdb.verify.CtdbVerifyResult`. ``flac_verify_result`` is
    an optional :class:`~platterpus.adapters.flac_verify.FlacVerifyResult` and
    ``transcode_result`` an optional
    :class:`~platterpus.adapters.transcode.TranscodeResult` — together they form
    the report's ``verification`` block alongside CTDB. ``checksums`` is an
    optional ``{relpath: sha256}`` map (see :mod:`platterpus.checksums`).
    ``timing`` / ``debug_log`` are as in :func:`build_timing` /
    :func:`build_debug_log`. Never raises.
    """
    try:
        return _build(
            rip_log,
            ctdb_result,
            generated_at,
            timing,
            debug_log,
            flac_verify_result,
            transcode_result,
            checksums,
        )
    except Exception:  # noqa: BLE001 — a report builder must never crash a rip
        log.exception("rip-report build failed; emitting minimal envelope")
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generator": {"name": "platterpus", "version": __version__},
            "error": "report could not be built",
        }


def build_timing(
    elapsed_seconds: float | None,
    *,
    estimated_seconds: int | None = None,
    started_at: str = "",
    finished_at: str = "",
) -> dict:
    """Build the ``timing`` section: actual elapsed vs the ripper's estimate.

    Pure and never raises. ``elapsed_seconds`` is the GUI-measured wall-clock
    (cyanrip's log records the disc's audio length and a finish timestamp, but
    never its own run time). ``estimated_seconds`` is cyanrip's first ETA — kept
    alongside the actual time precisely because it is unreliable on marginal
    discs (it ignores secure re-read passes), so the gap is auditable.
    """
    from platterpus.rip_timing import format_duration

    timing: dict = {
        "elapsed_seconds": (
            round(elapsed_seconds) if isinstance(elapsed_seconds, int | float) else None
        ),
        "elapsed_human": format_duration(elapsed_seconds),
        "started_at": started_at or None,
        "finished_at": finished_at or None,
    }
    if estimated_seconds is not None:
        timing["estimated_seconds"] = estimated_seconds
        timing["estimated_human"] = format_duration(estimated_seconds)
        timing["estimate_source"] = (
            "cyanrip ETA — excludes secure re-read passes, so it under-estimates "
            "marginal discs"
        )
    return timing


def build_debug_log(lines: list[str], *, truncated: bool = False) -> dict:
    """Wrap captured session log lines for the report's ``debug`` section.

    ``lines`` is this session's log (everything since launch) with other albums'
    rips already filtered out by the caller; ``truncated`` is True if the
    in-memory buffer already dropped its oldest lines. Embeds at most
    ``_MAX_EMBEDDED_LOG_LINES`` (keeping the most recent — closest to this rip),
    so the report stays small and fast to (re)serialize on the GUI thread no
    matter how long the session ran; the full history is always in log.txt.
    Pure; never raises.
    """
    embedded = list(lines)
    capped = len(embedded) > _MAX_EMBEDDED_LOG_LINES
    if capped:
        embedded = embedded[-_MAX_EMBEDDED_LOG_LINES:]
    return {
        "scope": "this session since launch, excluding other albums' rips",
        # True if EITHER the in-memory buffer dropped lines OR we capped here;
        # in both cases log.txt has the complete record.
        "truncated": bool(truncated) or capped,
        "lines": embedded,
    }


def _build(
    rip_log: object,
    ctdb_result: object | None,
    generated_at: str,
    timing: dict | None = None,
    debug_log: dict | None = None,
    flac_verify_result: object | None = None,
    transcode_result: object | None = None,
    checksums: dict | None = None,
) -> dict:
    message, level = accuraterip_verdict(rip_log)
    info = getattr(rip_log, "ripping_info", None)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generator": {"name": "platterpus", "version": __version__},
        "generated_at": generated_at or None,
        "timing": timing,
        "log_creator": getattr(rip_log, "log_creator", "") or None,
        "verdict": {"level": level, "message": message or None},
        "rip": {
            "drive": getattr(info, "drive", "") or None,
            "extraction_engine": getattr(info, "extraction_engine", "") or None,
            "read_offset_correction": getattr(info, "read_offset_correction", None),
            "defeat_audio_cache": getattr(info, "defeat_audio_cache", None),
            "overread_lead_out": getattr(info, "overread_lead_out", None),
            "gap_detection": getattr(info, "gap_detection", "") or None,
            "cd_r_detected": getattr(info, "cd_r_detected", None),
            "creation_date": getattr(rip_log, "creation_date", "") or None,
        },
        "accuraterip_summary": getattr(rip_log, "accuraterip_summary", "") or None,
        "partially_accurate_summary": (
            getattr(rip_log, "partially_accurate_summary", "") or None
        ),
        "disc_duration": getattr(rip_log, "disc_duration", "") or None,
        "paranoia_counts": dict(getattr(rip_log, "paranoia_counts", {}) or {}) or None,
        "health_status": getattr(rip_log, "health_status", "") or None,
        "sha256_hash": getattr(rip_log, "sha256_hash", "") or None,
        "tracks": [_track(t) for t in (getattr(rip_log, "tracks", ()) or ())],
        "ctdb": _ctdb(ctdb_result),
        # The full post-rip verification suite in one place: AccurateRip lives in
        # `verdict`/`tracks`, CTDB stays at `ctdb` (back-compat), and this block
        # adds the FLAC-integrity decode + the transcode outcome so a reader sees
        # every check the master (and any derived files) passed.
        "verification": {
            "flac_integrity": _flac_verify(flac_verify_result),
            "transcode": _transcode(transcode_result),
        },
        # Per-file SHA256 for long-term integrity checking (bit-rot). Embedded
        # here rather than a separate checksums.sha256 sidecar — one debug file.
        "checksums": (dict(checksums) if checksums else None),
        # Bulky, so it sits last: the embedded session log that makes this
        # report a self-contained debug record (None when not captured).
        "debug": debug_log,
    }


def _track(track: object) -> dict:
    return {
        "number": getattr(track, "number", None),
        "filename": getattr(track, "filename", "") or None,
        "test_crc": getattr(track, "test_crc", "") or None,
        "copy_crc": getattr(track, "copy_crc", "") or None,
        "status": getattr(track, "status", "") or None,
        # How many read passes cyanrip needed (its "(after N rips)"); None for
        # whipper logs / a clean single-pass cyanrip track.
        "rip_count": getattr(track, "rip_count", None),
        # The shared confidence>=1 rule — same as the banner and disc panel.
        "accuraterip_verified": track_accuraterip_verified(track),
        "accuraterip": {
            "v1": _ar(getattr(track, "accuraterip_v1", None)),
            "v2": _ar(getattr(track, "accuraterip_v2", None)),
            # The +450-frame offset-pressing variant ("partially accurately
            # ripped"). Surfaced as data; NOT counted as a plain verified match.
            "offset_450": _ar(getattr(track, "accuraterip_offset", None)),
        },
    }


def _ar(ar: object) -> dict | None:
    if ar is None:
        return None
    return {
        "result": getattr(ar, "result", "") or None,
        "confidence": getattr(ar, "confidence", None),
        "local_crc": getattr(ar, "local_crc", None),
        "remote_crc": getattr(ar, "remote_crc", None),
    }


def _hex_crc(value: object) -> str | None:
    """Render a CTDB integer CRC as 8-digit uppercase hex (matches the
    AccurateRip CRC style elsewhere in the report); None passes through."""
    if isinstance(value, int):
        return f"{value:08X}"
    return None


def _flac_verify(result: object | None) -> dict | None:
    """Serialize a FlacVerifyResult (decode==stored-MD5 test of the masters).

    ``ran`` distinguishes "verified and passed/failed" from "couldn't run"
    (e.g. the ``flac`` binary is absent); ``failures`` lists any files that
    failed the decode test. None when no verify was attempted.
    """
    if result is None:
        return None
    failures = getattr(result, "failures", ()) or ()
    return {
        "ran": bool(getattr(result, "ran", False)),
        "ok": bool(getattr(result, "ok", False)),
        "checked": getattr(result, "checked", 0),
        "failures": [str(p) for p in failures],
        "error": getattr(result, "error", "") or None,
    }


def _transcode(result: object | None) -> dict | None:
    """Serialize a TranscodeResult (deriving MP3/WavPack/WAV from the master).

    None when the rip was FLAC-only (no transcode happened)."""
    if result is None:
        return None
    failures = getattr(result, "failures", ()) or ()
    return {
        "ran": bool(getattr(result, "ran", False)),
        "ok": bool(getattr(result, "ok", False)),
        "transcoded": getattr(result, "transcoded", 0),
        "failures": [str(p) for p in failures],
        "error": getattr(result, "error", "") or None,
    }


def _ctdb(result: object | None) -> dict | None:
    if result is None:
        return None
    verdict = getattr(getattr(result, "verdict", None), "value", None)
    return {
        "verdict": verdict,
        "confidence": getattr(result, "confidence", None),
        "trustworthy": getattr(result, "trustworthy", None),
        "crc_validated": getattr(result, "crc_validated", None),
        # Include the CRCs + message so a consumer can audit a match, not just
        # see the verdict (hex to match the per-track AccurateRip CRC style).
        "our_crc": _hex_crc(getattr(result, "our_crc", None)),
        "matched_crc": _hex_crc(getattr(result, "matched_crc", None)),
        "message": getattr(result, "message", "") or None,
    }


def report_to_json(report: dict) -> str:
    """Serialize a report dict to pretty UTF-8 JSON (trailing newline).

    ``default=str`` is a belt for the never-raises contract: any stray
    non-JSON-native value (a Path/enum a future field might carry) degrades to
    its string form instead of raising ``TypeError`` mid-rip.
    """
    return (
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        + "\n"
    )


def report_path_for(log_file: Path) -> Path:
    """The JSON report path that sits beside a rip log (`X.log` → `X.platterpus.json`)."""
    return log_file.parent / f"{log_file.stem}.platterpus.json"


def write_report(
    rip_log: object,
    log_file: Path,
    *,
    ctdb_result: object | None = None,
    flac_verify_result: object | None = None,
    transcode_result: object | None = None,
    checksums: dict | None = None,
    generated_at: str = "",
    timing: dict | None = None,
    debug_log: dict | None = None,
) -> Path | None:
    """Build and write the JSON report beside ``log_file``. Best-effort.

    Returns the path written, or None on any failure (the report is a nice-to-
    have; it must never break the post-rip flow). Writing a small JSON file is
    cheap, so this is safe to call on the GUI thread. (Computing ``checksums``
    is NOT — that's done off-thread by the caller and passed in here.)
    """
    target = report_path_for(log_file)
    try:
        report = build_report(
            rip_log,
            ctdb_result=ctdb_result,
            flac_verify_result=flac_verify_result,
            transcode_result=transcode_result,
            checksums=checksums,
            generated_at=generated_at,
            timing=timing,
            debug_log=debug_log,
        )
        # Catch serialization errors (TypeError/ValueError from json.dumps on an
        # exotic future value) as well as write errors (OSError) — the report is
        # best-effort and must never break the post-rip flow. report_to_json
        # also uses default=str as a second line of defence.
        target.write_text(report_to_json(report), encoding="utf-8")
        return target
    except (OSError, TypeError, ValueError):
        log.warning("could not write rip report to %s", target, exc_info=True)
        return None
