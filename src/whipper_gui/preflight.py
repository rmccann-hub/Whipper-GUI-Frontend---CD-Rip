# SPDX-License-Identifier: GPL-3.0-only
"""Preflight ("doctor") checks — a first-pass test of the rip environment.

Everything the rip pipeline needs is exercised here EXCEPT the disc read
itself, so the whole thing runs with **no CD in the drive**:

  * the Distrobox -> ``~/.local/bin/whipper`` routing actually reaches whipper
    (the single most failure-prone link — Critical Rule #3);
  * the optical drive is detected and accessible (a drive lists fine empty);
  * the dependency tools are present at a usable version (reusing the ONE
    dependency subsystem — Critical Rule #6);
  * the host can reach MusicBrainz / the Cover Art Archive / CTDB.

It does not, and cannot, prove a bit-perfect rip — that needs a real disc on
real hardware (the project's standing hardware gate). What it *does* is knock
out the boring environmental failure modes before you ever insert a disc, so a
real run is far more likely to work the first time.

Design notes for the next reader:
  * **Logic lives here, in the package**, so it's unit-testable with injected
    fakes; ``scripts/preflight.py`` and ``whipper-gui --doctor`` are thin CLIs
    over ``default_context()`` + ``run_preflight()``.
  * **Checks never raise.** A diagnostic that crashes is useless — every check
    catches its own failure and returns a ``CheckResult`` describing it (the
    same fail-safe ethos as the never-raise parsers).
  * **It reuses the real adapters**, it doesn't reimplement probing — so what
    it tests is what the GUI actually does.
"""

from __future__ import annotations

import enum
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whipper_gui import __version__
from whipper_gui import config as config_module
from whipper_gui.adapters.ctdb_client import CTDBClient, CtdbHttpImpl, CtdbLookupError
from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    MusicBrainzNgsImpl,
    MusicBrainzQueryError,
)
from whipper_gui.adapters.whipper_backend import (
    WhipperBackend,
    WhipperError,
    WhipperHostExportedImpl,
)
from whipper_gui.config import Config
from whipper_gui.ctdb.toc import DiscToc
from whipper_gui.deps.manager import DependencyManager
from whipper_gui.drive_access import SEVERITY_OK, diagnose_drive_access
from whipper_gui.paths import CYANRIP_BINARY_DEFAULT

# Project URL used as the MusicBrainz user-agent contact (MB policy wants a
# reachable human/URL) and the CTDB client's default. Matches app.py.
_CONTACT_URL = "https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip"

# A well-formed MusicBrainz disc id used only to prove the server answers. We
# don't care whether it matches anything: a 404 ("not in DB") still means MB
# is reachable; only a network/parse error means it isn't.
_PROBE_DISC_ID = "arIS30RPWowvwNEqsqdDnZzDGhk-"

# A synthetic, structurally-valid TOC for the CTDB reachability probe. It won't
# be in the database (that's fine) — any answer proves CTDB responded; only a
# CtdbLookupError means the host can't reach it.
_PROBE_TOC = DiscToc(track_offsets=(150, 20000, 40000), leadout=60000)

# Where to ping the Cover Art Archive. We do a plain HTTP reachability check
# here rather than going through the cover_art adapter on purpose: that adapter
# is deliberately "never raises, returns None on any failure", so it CANNOT
# distinguish "service down" from "this release simply has no art" — exactly the
# distinction a reachability probe needs.
_CAA_URL = "https://coverartarchive.org/"


class Status(enum.Enum):
    """Outcome of one check, worst-to-best for the summary verdict."""

    FAIL = "fail"  # a hard blocker — a normal rip cannot work until fixed
    WARN = "warn"  # worth attention, but not a guaranteed blocker
    SKIP = "skip"  # not run (e.g. --no-network)
    OK = "ok"


# Display glyphs and ANSI colours, kept beside the enum so the CLIs render
# consistently. SKIP/OK are quiet; WARN/FAIL stand out.
_SYMBOL: dict[Status, str] = {
    Status.OK: "✓",
    Status.WARN: "!",
    Status.FAIL: "✗",
    Status.SKIP: "–",
}
_ANSI: dict[Status, str] = {
    Status.OK: "32",  # green
    Status.WARN: "33",  # yellow
    Status.FAIL: "31",  # red
    Status.SKIP: "90",  # grey
}


@dataclass(frozen=True)
class CheckResult:
    """The outcome of a single preflight check."""

    name: str
    status: Status
    summary: str  # one-line headline
    detail: str = ""  # optional fuller explanation (multi-line ok)
    hint: str = ""  # optional "what to do about it"


@dataclass
class PreflightContext:
    """The constructed pieces a preflight run probes through.

    Built once by ``default_context()`` (mirroring app.py's composition root)
    or assembled with fakes by tests. Holding them in one object keeps
    ``run_preflight()`` free of construction concerns.
    """

    cfg: Config
    backend: WhipperBackend
    backend_name: str
    mb_client: MusicBrainzClient
    ctdb_client: CTDBClient
    dependency_manager: DependencyManager


# --- Composition root (mirrors app.py) -------------------------------------


def default_context(cfg: Config | None = None) -> PreflightContext:
    """Build the real adapters exactly as app.py does, for a live run.

    Construction does no I/O (no network, no subprocess), so this is safe to
    call before any check runs. `cfg` is injectable so tests don't touch the
    real config file.
    """
    cfg = cfg if cfg is not None else config_module.load()
    working_dir = Path(cfg.working_dir) if cfg.working_dir else None

    backend: WhipperBackend
    if cfg.ripper_backend == "cyanrip":
        from whipper_gui.adapters.cyanrip_backend import CyanripImpl

        # Prefer the host-exported absolute path; a desktop-launched process
        # has a minimal PATH (same lesson as app.py / drive_control).
        cyanrip_binary: Path | str = (
            CYANRIP_BINARY_DEFAULT if CYANRIP_BINARY_DEFAULT.exists() else "cyanrip"
        )
        backend = CyanripImpl(binary_path=cyanrip_binary, working_dir=working_dir)
        backend_name = "cyanrip"
    else:
        backend = WhipperHostExportedImpl(
            binary_path=Path(cfg.whipper_path), working_dir=working_dir
        )
        backend_name = "whipper"

    mb_client = MusicBrainzNgsImpl(
        app="whipper-gui", version=__version__, contact=_CONTACT_URL
    )
    ctdb_client = CtdbHttpImpl()
    dependency_manager = DependencyManager()

    return PreflightContext(
        cfg=cfg,
        backend=backend,
        backend_name=backend_name,
        mb_client=mb_client,
        ctdb_client=ctdb_client,
        dependency_manager=dependency_manager,
    )


# --- Individual checks (each NEVER raises) ---------------------------------


def check_settings(cfg: Config) -> CheckResult:
    """Echo back the settings that shape a rip, so the user can eyeball them."""
    offset = (
        f"{cfg.read_offset:+d} (override on)"
        if cfg.override_read_offset
        else "auto (per drive)"
    )
    detail = "\n".join(
        [
            f"backend:        {cfg.ripper_backend}",
            f"output dir:     {cfg.output_dir}",
            f"read offset:    {offset}",
            f"cover art:      {cfg.cover_art}",
            f"CTDB verify:    {'on' if cfg.ctdb_verify_after_rip else 'off'}",
        ]
    )
    return CheckResult(
        "Configuration",
        Status.OK,
        f"backend={cfg.ripper_backend}, output={cfg.output_dir}",
        detail=detail,
    )


def _is_writable(path: Path) -> bool:
    return os.access(path, os.W_OK)


def check_output_dir(
    cfg: Config, *, is_writable: Callable[[Path], bool] = _is_writable
) -> CheckResult:
    """Confirm rips can actually be written to the configured output location.

    The output dir itself may not exist yet (created on first rip); we walk up
    to the nearest existing ancestor and check *that* is writable.
    """
    target = Path(cfg.output_dir).expanduser()
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        writable = is_writable(probe)
    except OSError as exc:  # extremely unlikely, but a diagnostic never crashes
        return CheckResult(
            "Output location",
            Status.FAIL,
            f"could not test {probe}",
            detail=str(exc),
        )
    if writable:
        return CheckResult("Output location", Status.OK, f"writable ({target})")
    return CheckResult(
        "Output location",
        Status.FAIL,
        f"not writable: {probe}",
        hint="Pick a different output folder in Settings, or fix its permissions.",
    )


def _fmt_version(version: tuple[int, ...] | None) -> str:
    return ".".join(str(n) for n in version) if version else "present"


def check_dependencies(manager: DependencyManager) -> CheckResult:
    """Run the ONE dependency subsystem and summarise presence + versions."""
    try:
        report = manager.check_all()
    except Exception as exc:  # noqa: BLE001 — diagnostic must not crash
        return CheckResult(
            "Dependencies", Status.FAIL, "dependency probe failed", detail=str(exc)
        )

    ok_lines = [
        f"  ✓ {spec.display_name}: {_fmt_version(report.ok_versions.get(spec.dep_id))}"
        for spec in report.ok
    ]
    missing_required = [m for m in report.missing if not m.spec.optional]
    missing_optional = [m for m in report.missing if m.spec.optional]
    miss_lines = [
        f"  ✗ {m.spec.display_name}: MISSING"
        + ("" if not m.spec.optional else " (optional)")
        for m in report.missing
    ]
    detail = "\n".join([*ok_lines, *miss_lines])

    if missing_required:
        names = ", ".join(m.spec.display_name for m in missing_required)
        return CheckResult(
            "Dependencies",
            Status.FAIL,
            f"{len(missing_required)} required tool(s) missing: {names}",
            detail=detail,
            hint="Run the host-setup wizard (Tools → Set up Whipper GUI…) "
            "or install the missing tools, then re-run preflight.",
        )
    if missing_optional:
        names = ", ".join(m.spec.display_name for m in missing_optional)
        return CheckResult(
            "Dependencies",
            Status.WARN,
            f"all required tools present; optional missing: {names}",
            detail=detail,
            hint="Optional tools enable extras (e.g. flac for CTDB decode); "
            "rips work without them.",
        )
    return CheckResult(
        "Dependencies",
        Status.OK,
        f"all {len(report.ok)} dependencies present",
        detail=detail,
    )


def check_backend_routing(backend: WhipperBackend, *, backend_name: str) -> CheckResult:
    """THE Distrobox-routing test: can we actually reach the ripper backend?

    For whipper this runs ``~/.local/bin/whipper --version``, which enters the
    Distrobox container — so a pass proves the whole host→container→whipper
    chain works. (May take a few seconds on a cold container.)
    """
    try:
        raw = backend.version()
    except WhipperError as exc:
        return CheckResult(
            f"{backend_name} reachable",
            Status.FAIL,
            f"could not run {backend_name}",
            detail=str(exc),
            hint="Run Tools → Set up Whipper GUI…, or check that the "
            "Distrobox 'ripping' container exists and exports the binary.",
        )
    except Exception as exc:  # noqa: BLE001 — any failure is a routing failure
        return CheckResult(
            f"{backend_name} reachable",
            Status.FAIL,
            f"could not run {backend_name}",
            detail=str(exc),
            hint="Run Tools → Set up Whipper GUI… to (re)provision the backend.",
        )
    version = raw.strip().splitlines()[0] if raw.strip() else "(no version output)"
    return CheckResult(f"{backend_name} reachable", Status.OK, version)


def _fmt_offset(offset: int | None) -> str:
    return "?" if offset is None else f"{offset:+d}"


def check_drives(backend: WhipperBackend) -> CheckResult:
    """Detect optical drives (no disc required) and show their read offsets."""
    try:
        drives = backend.list_drives()
    except Exception as exc:  # noqa: BLE001 — never crash the diagnostic
        return CheckResult(
            "Optical drive detected",
            Status.WARN,
            "could not list drives",
            detail=str(exc),
        )
    if not drives:
        return CheckResult(
            "Optical drive detected",
            Status.WARN,
            "no optical drive found",
            hint="Connect/power on the drive (a disc is NOT needed for "
            "detection). If the backend check above failed, fix that first.",
        )
    lines = [
        f"  {d.device}: {d.vendor} {d.model} (offset {_fmt_offset(d.read_offset)})"
        for d in drives
    ]
    return CheckResult(
        "Optical drive detected",
        Status.OK,
        f"{len(drives)} drive(s) found",
        detail="\n".join(lines),
    )


def check_drive_access(
    *, diagnose: Callable[[], object] = diagnose_drive_access
) -> CheckResult:
    """Check the drive device node is present and readable (permissions)."""
    try:
        diag = diagnose()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "Drive access",
            Status.WARN,
            "could not diagnose drive access",
            detail=str(exc),
        )
    if getattr(diag, "severity", None) == SEVERITY_OK:
        return CheckResult("Drive access", Status.OK, getattr(diag, "summary", "ok"))
    return CheckResult(
        "Drive access",
        Status.WARN,
        getattr(diag, "summary", "drive not accessible"),
        detail=getattr(diag, "detail", ""),
        hint=getattr(diag, "fix_command", "") or "",
    )


def check_musicbrainz(
    mb_client: MusicBrainzClient, *, disc_id: str = _PROBE_DISC_ID
) -> CheckResult:
    """Prove the host can reach MusicBrainz (needed to identify discs)."""
    try:
        releases = mb_client.releases_by_disc_id(disc_id)
    except MusicBrainzQueryError as exc:
        return CheckResult(
            "MusicBrainz reachable",
            Status.WARN,
            "could not reach MusicBrainz",
            detail=str(exc),
            hint="Identified rips need MusicBrainz; unknown-disc rips still "
            "work, and the GUI tags them from this host-side lookup.",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "MusicBrainz reachable",
            Status.WARN,
            "MusicBrainz probe failed",
            detail=str(exc),
        )
    return CheckResult(
        "MusicBrainz reachable",
        Status.OK,
        f"reachable ({len(releases)} release(s) for the probe disc id)",
    )


def check_cover_art_archive(
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
    url: str = _CAA_URL,
) -> CheckResult:
    """Prove the host can reach the Cover Art Archive (embedded cover art)."""
    try:
        with opener(url, timeout=10) as resp:  # type: ignore[call-arg]
            code = getattr(resp, "status", 200)
        return CheckResult(
            "Cover Art Archive reachable", Status.OK, f"reachable (HTTP {code})"
        )
    except urllib.error.HTTPError as exc:
        # The server answered (even a 4xx/5xx) — that's "reachable".
        return CheckResult(
            "Cover Art Archive reachable", Status.OK, f"reachable (HTTP {exc.code})"
        )
    except (urllib.error.URLError, OSError) as exc:
        return CheckResult(
            "Cover Art Archive reachable",
            Status.WARN,
            "could not reach the Cover Art Archive",
            detail=str(exc),
            hint="Cover art is fetched after a rip; rips still succeed without it.",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "Cover Art Archive reachable",
            Status.WARN,
            "cover-art probe failed",
            detail=str(exc),
        )


def check_ctdb(ctdb_client: CTDBClient, *, toc: DiscToc = _PROBE_TOC) -> CheckResult:
    """Prove the host can reach CTDB (optional, experimental verification)."""
    try:
        result = ctdb_client.lookup(toc)
    except CtdbLookupError as exc:
        return CheckResult(
            "CTDB reachable",
            Status.WARN,
            "could not reach CTDB",
            detail=str(exc),
            hint="CTDB verify is optional/experimental; rips work without it.",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "CTDB reachable", Status.WARN, "CTDB probe failed", detail=str(exc)
        )
    state = "in DB" if result.in_database else "not in DB (expected for the probe)"
    return CheckResult("CTDB reachable", Status.OK, f"reachable ({state})")


# --- Orchestration ---------------------------------------------------------

# The three network checks, by name, so --no-network can emit SKIPs for them.
_NETWORK_CHECK_NAMES = (
    "MusicBrainz reachable",
    "Cover Art Archive reachable",
    "CTDB reachable",
)


def run_preflight(
    ctx: PreflightContext,
    *,
    network: bool = True,
    on_result: Callable[[CheckResult], None] | None = None,
) -> list[CheckResult]:
    """Run every check in order; return all results.

    `on_result`, if given, is called as each result lands — the CLIs use it to
    stream progress (some checks take a second or two), so the terminal never
    looks frozen.
    """
    results: list[CheckResult] = []

    def emit(result: CheckResult) -> None:
        results.append(result)
        if on_result is not None:
            on_result(result)

    emit(check_settings(ctx.cfg))
    emit(check_output_dir(ctx.cfg))
    emit(check_dependencies(ctx.dependency_manager))
    emit(check_backend_routing(ctx.backend, backend_name=ctx.backend_name))
    emit(check_drives(ctx.backend))
    emit(check_drive_access())
    if network:
        emit(check_musicbrainz(ctx.mb_client))
        emit(check_cover_art_archive())
        emit(check_ctdb(ctx.ctdb_client))
    else:
        for name in _NETWORK_CHECK_NAMES:
            emit(CheckResult(name, Status.SKIP, "skipped (--no-network)"))
    return results


def summarize(results: list[CheckResult]) -> dict[Status, int]:
    """Count results by status."""
    counts: dict[Status, int] = {s: 0 for s in Status}
    for r in results:
        counts[r.status] += 1
    return counts


def exit_code(results: list[CheckResult]) -> int:
    """0 when nothing is a hard blocker (FAIL); 1 otherwise."""
    return 1 if any(r.status is Status.FAIL for r in results) else 0


# --- Rendering -------------------------------------------------------------


def _paint(text: str, status: Status, *, color: bool) -> str:
    if not color:
        return text
    return f"\033[{_ANSI[status]}m{text}\033[0m"


def format_line(result: CheckResult, *, color: bool = False) -> str:
    """One status line: ``[✓] Name — summary``."""
    glyph = _paint(_SYMBOL[result.status], result.status, color=color)
    return f"[{glyph}] {result.name} — {result.summary}"


def format_details(results: list[CheckResult]) -> str:
    """The detail/hint blocks for any non-OK, non-SKIP result (for the footer)."""
    blocks: list[str] = []
    for r in results:
        if r.status in (Status.OK, Status.SKIP):
            continue
        lines = [f"{_SYMBOL[r.status]} {r.name}: {r.summary}"]
        if r.detail:
            lines.extend(f"    {line}" for line in r.detail.splitlines())
        if r.hint:
            lines.append(f"    → {r.hint}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_summary(results: list[CheckResult], *, color: bool = False) -> str:
    """The final verdict line."""
    counts = summarize(results)
    verdict_status = (
        Status.FAIL
        if counts[Status.FAIL]
        else Status.WARN
        if counts[Status.WARN]
        else Status.OK
    )
    verdict = (
        "NOT ready — fix the blocker(s) above"
        if counts[Status.FAIL]
        else "ready (review warnings)"
        if counts[Status.WARN]
        else "ready"
    )
    head = (
        f"{counts[Status.OK]} OK, {counts[Status.WARN]} warning(s), "
        f"{counts[Status.FAIL]} blocker(s)"
    )
    return _paint(f"Preflight: {head} — {verdict}", verdict_status, color=color)
