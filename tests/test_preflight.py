"""Tests for the preflight ("doctor") checks.

Every check is exercised with a passing and a failing input via injected fakes,
plus the orchestration, the exit-code/summary logic, the rendering helpers, the
real-adapter composition root, and the `whipper-gui --doctor` CLI path.
"""

from __future__ import annotations

import urllib.error
from types import SimpleNamespace

from whipper_gui import preflight
from whipper_gui.adapters.ctdb_client import CtdbLookupError, CtdbLookupResult
from whipper_gui.adapters.musicbrainz_client import MusicBrainzQueryError
from whipper_gui.adapters.whipper_backend import WhipperError
from whipper_gui.config import Config
from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.manager import DependencyManager
from whipper_gui.deps.registry import DependencySpec, Tier
from whipper_gui.drive_access import (
    SEVERITY_OK,
    SEVERITY_PERMISSION,
    DriveAccessDiagnosis,
)
from whipper_gui.parsers.drive_list import DriveDescriptor
from whipper_gui.preflight import CheckResult, Status

# --- helpers / fakes -------------------------------------------------------


def _spec(dep_id: str, *, optional: bool = False) -> DependencySpec:
    """A minimal DependencySpec whose probe we'll set per test."""
    return DependencySpec(
        dep_id=dep_id,
        display_name=dep_id,
        probe=lambda: ProbeResult(present=True, version=(1, 0), location="/x"),
        min_version=(),
        tier=Tier.MANUAL,
        install_command=None,
        search_string=f"install {dep_id}",
        optional=optional,
    )


def _manager_with(probes: dict[str, ProbeResult]) -> DependencyManager:
    """A real DependencyManager over custom specs with fixed probe outcomes."""
    specs = []
    for dep_id, result in probes.items():
        spec = _spec(dep_id, optional=result.location == "optional")
        spec = DependencySpec(  # rebuild with the desired probe
            dep_id=spec.dep_id,
            display_name=spec.display_name,
            probe=lambda r=result: r,
            min_version=(),
            tier=spec.tier,
            install_command=None,
            search_string=spec.search_string,
            optional=spec.optional,
        )
        specs.append(spec)
    return DependencyManager(specs=specs)


class _FakeBackend:
    def __init__(self, *, version="whipper 0.10.0", drives=None, raises=None):
        self._version = version
        self._drives = drives if drives is not None else []
        self._raises = raises

    def version(self):
        if self._raises:
            raise self._raises
        return self._version

    def list_drives(self):
        if isinstance(self._drives, Exception):
            raise self._drives
        return self._drives


class _FakeMB:
    def __init__(self, *, releases=None, raises=None):
        self._releases = releases or []
        self._raises = raises

    def releases_by_disc_id(self, disc_id):
        if self._raises:
            raise self._raises
        return self._releases


class _FakeCtdb:
    def __init__(self, *, result=None, raises=None):
        self._result = result if result is not None else CtdbLookupResult()
        self._raises = raises

    def lookup(self, toc):
        if self._raises:
            raise self._raises
        return self._result


class _FakeResp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- check_settings / check_output_dir -------------------------------------


def test_check_settings_reports_key_fields():
    res = preflight.check_settings(Config(ripper_backend="cyanrip"))
    assert res.status is Status.OK
    assert "cyanrip" in res.summary
    assert "backend:" in res.detail


def test_check_output_dir_writable(tmp_path):
    res = preflight.check_output_dir(Config(output_dir=str(tmp_path)))
    assert res.status is Status.OK
    assert "writable" in res.summary


def test_check_output_dir_not_writable(tmp_path):
    res = preflight.check_output_dir(
        Config(output_dir=str(tmp_path)), is_writable=lambda p: False
    )
    assert res.status is Status.FAIL
    assert res.hint


def test_check_output_dir_probe_oserror(tmp_path):
    def boom(_p):
        raise OSError("nope")

    res = preflight.check_output_dir(Config(output_dir=str(tmp_path)), is_writable=boom)
    assert res.status is Status.FAIL


# --- check_dependencies ----------------------------------------------------


def test_check_dependencies_all_present():
    mgr = _manager_with(
        {"whipper": ProbeResult(present=True, version=(0, 10), location="/x")}
    )
    res = preflight.check_dependencies(mgr)
    assert res.status is Status.OK
    assert "whipper" in res.detail


def test_check_dependencies_required_missing_fails():
    mgr = _manager_with(
        {"whipper": ProbeResult(present=False, version=None, location=None)}
    )
    res = preflight.check_dependencies(mgr)
    assert res.status is Status.FAIL
    assert "whipper" in res.summary


def test_check_dependencies_optional_missing_warns():
    # location="optional" is the sentinel _manager_with uses to mark it optional.
    mgr = _manager_with(
        {"flac": ProbeResult(present=False, version=None, location="optional")}
    )
    res = preflight.check_dependencies(mgr)
    assert res.status is Status.WARN


def test_check_dependencies_probe_crash_is_caught():
    class _Boom:
        def check_all(self):
            raise RuntimeError("kaboom")

    res = preflight.check_dependencies(_Boom())
    assert res.status is Status.FAIL


# --- check_backend_routing -------------------------------------------------


def test_check_backend_routing_ok():
    res = preflight.check_backend_routing(
        _FakeBackend(version="whipper 0.10.0\nextra"), backend_name="whipper"
    )
    assert res.status is Status.OK
    assert res.summary == "whipper 0.10.0"


def test_check_backend_routing_whippererror_fails():
    res = preflight.check_backend_routing(
        _FakeBackend(raises=WhipperError("container down")), backend_name="whipper"
    )
    assert res.status is Status.FAIL
    assert res.hint


def test_check_backend_routing_unexpected_error_fails():
    res = preflight.check_backend_routing(
        _FakeBackend(raises=OSError("no binary")), backend_name="whipper"
    )
    assert res.status is Status.FAIL


def test_check_backend_routing_empty_version():
    res = preflight.check_backend_routing(
        _FakeBackend(version="   "), backend_name="cyanrip"
    )
    assert res.status is Status.OK
    assert "no version" in res.summary


# --- check_drives ----------------------------------------------------------


def test_check_drives_found():
    drive = DriveDescriptor(
        device="/dev/sr0",
        vendor="PIONEER",
        model="BD-RW BDR-209D",
        release="1.0",
        read_offset=667,
    )
    res = preflight.check_drives(_FakeBackend(drives=[drive]))
    assert res.status is Status.OK
    assert "/dev/sr0" in res.detail
    assert "+667" in res.detail


def test_check_drives_none():
    res = preflight.check_drives(_FakeBackend(drives=[]))
    assert res.status is Status.WARN


def test_check_drives_error():
    res = preflight.check_drives(_FakeBackend(drives=RuntimeError("boom")))
    assert res.status is Status.WARN


def test_check_drives_offset_unknown():
    drive = DriveDescriptor(
        device="/dev/sr0", vendor="V", model="M", release="", read_offset=None
    )
    res = preflight.check_drives(_FakeBackend(drives=[drive]))
    assert "offset ?" in res.detail


# --- check_drive_access ----------------------------------------------------


def test_check_drive_access_ok():
    diag = DriveAccessDiagnosis(severity=SEVERITY_OK, summary="ok", detail="")
    res = preflight.check_drive_access(diagnose=lambda: diag)
    assert res.status is Status.OK


def test_check_drive_access_permission_warns():
    diag = DriveAccessDiagnosis(
        severity=SEVERITY_PERMISSION,
        summary="not in cdrom group",
        detail="add yourself",
        fix_command="sudo usermod -aG cdrom you",
    )
    res = preflight.check_drive_access(diagnose=lambda: diag)
    assert res.status is Status.WARN
    assert res.hint == "sudo usermod -aG cdrom you"


def test_check_drive_access_crash_is_caught():
    def boom():
        raise RuntimeError("x")

    res = preflight.check_drive_access(diagnose=boom)
    assert res.status is Status.WARN


# --- network checks --------------------------------------------------------


def test_check_musicbrainz_ok():
    res = preflight.check_musicbrainz(_FakeMB(releases=["a", "b"]))
    assert res.status is Status.OK
    assert "2 release" in res.summary


def test_check_musicbrainz_unreachable_warns():
    res = preflight.check_musicbrainz(_FakeMB(raises=MusicBrainzQueryError("offline")))
    assert res.status is Status.WARN


def test_check_musicbrainz_unexpected_warns():
    res = preflight.check_musicbrainz(_FakeMB(raises=ValueError("weird")))
    assert res.status is Status.WARN


def test_check_cover_art_ok():
    res = preflight.check_cover_art_archive(opener=lambda url, timeout: _FakeResp(200))
    assert res.status is Status.OK


def test_check_cover_art_httperror_is_reachable():
    def opener(url, timeout):
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    res = preflight.check_cover_art_archive(opener=opener)
    assert res.status is Status.OK
    assert "404" in res.summary


def test_check_cover_art_urlerror_warns():
    def opener(url, timeout):
        raise urllib.error.URLError("down")

    res = preflight.check_cover_art_archive(opener=opener)
    assert res.status is Status.WARN


def test_check_cover_art_unexpected_warns():
    def opener(url, timeout):
        raise ValueError("weird")

    res = preflight.check_cover_art_archive(opener=opener)
    assert res.status is Status.WARN


def test_check_ctdb_ok_not_in_db():
    res = preflight.check_ctdb(_FakeCtdb(result=CtdbLookupResult()))
    assert res.status is Status.OK
    assert "not in DB" in res.summary


def test_check_ctdb_unreachable_warns():
    res = preflight.check_ctdb(_FakeCtdb(raises=CtdbLookupError("timeout")))
    assert res.status is Status.WARN


def test_check_ctdb_unexpected_warns():
    res = preflight.check_ctdb(_FakeCtdb(raises=RuntimeError("x")))
    assert res.status is Status.WARN


# --- orchestration ---------------------------------------------------------


def _ctx(**over) -> preflight.PreflightContext:
    return preflight.PreflightContext(
        cfg=over.get("cfg", Config()),
        backend=over.get("backend", _FakeBackend(drives=[])),
        backend_name=over.get("backend_name", "whipper"),
        mb_client=over.get("mb_client", _FakeMB(releases=[])),
        ctdb_client=over.get("ctdb_client", _FakeCtdb()),
        dependency_manager=over.get(
            "dependency_manager",
            _manager_with(
                {"whipper": ProbeResult(present=True, version=(1,), location="/x")}
            ),
        ),
    )


def test_run_preflight_with_network_runs_all(tmp_path):
    ctx = _ctx(cfg=Config(output_dir=str(tmp_path)))
    seen: list[CheckResult] = []
    results = preflight.run_preflight(ctx, network=True, on_result=seen.append)
    names = [r.name for r in results]
    assert "MusicBrainz reachable" in names
    assert "CTDB reachable" in names
    assert seen == results  # on_result fired for each, in order


def test_run_preflight_no_network_skips(tmp_path):
    ctx = _ctx(cfg=Config(output_dir=str(tmp_path)))
    results = preflight.run_preflight(ctx, network=False)
    network = [r for r in results if r.name in preflight._NETWORK_CHECK_NAMES]
    assert network and all(r.status is Status.SKIP for r in network)


def test_exit_code_and_summarize():
    ok = CheckResult("a", Status.OK, "fine")
    warn = CheckResult("b", Status.WARN, "hmm")
    fail = CheckResult("c", Status.FAIL, "bad")
    assert preflight.exit_code([ok, warn]) == 0
    assert preflight.exit_code([ok, fail]) == 1
    counts = preflight.summarize([ok, warn, fail])
    assert counts[Status.OK] == 1
    assert counts[Status.FAIL] == 1


# --- rendering -------------------------------------------------------------


def test_format_line_plain_and_color():
    r = CheckResult("Backend", Status.OK, "reachable")
    plain = preflight.format_line(r, color=False)
    assert "Backend" in plain and "reachable" in plain and "\033[" not in plain
    colored = preflight.format_line(r, color=True)
    assert "\033[" in colored


def test_format_details_skips_ok():
    results = [
        CheckResult("Healthy", Status.OK, "all-fine-here"),
        CheckResult("bad", Status.FAIL, "broke", detail="line1", hint="fix it"),
    ]
    out = preflight.format_details(results)
    assert "bad" in out and "line1" in out and "→ fix it" in out
    # The OK result contributes nothing to the details footer.
    assert "all-fine-here" not in out and "Healthy" not in out


def test_format_summary_verdicts():
    assert "ready" in preflight.format_summary([CheckResult("a", Status.OK, "x")])
    assert "NOT ready" in preflight.format_summary([CheckResult("a", Status.FAIL, "x")])
    assert "review warnings" in preflight.format_summary(
        [CheckResult("a", Status.WARN, "x")]
    )


# --- default_context (real composition root) -------------------------------


def test_default_context_whipper():
    ctx = preflight.default_context(Config())
    assert ctx.backend_name == "whipper"
    assert ctx.backend.__class__.__name__ == "WhipperHostExportedImpl"


def test_default_context_cyanrip():
    ctx = preflight.default_context(Config(ripper_backend="cyanrip"))
    assert ctx.backend_name == "cyanrip"
    assert ctx.backend.__class__.__name__ == "CyanripImpl"


# --- the `whipper-gui --doctor` CLI path -----------------------------------


def test_app_doctor_path_runs_and_returns_exit_code(monkeypatch, capsys):
    from whipper_gui import app as app_module

    monkeypatch.setattr(
        "whipper_gui.logging_setup.configure_logging", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "whipper_gui.logging_setup.set_debug_logging", lambda *a, **k: None
    )
    monkeypatch.setattr("whipper_gui.config.load", lambda: Config())
    monkeypatch.setattr(
        preflight,
        "default_context",
        lambda cfg: SimpleNamespace(backend_name="whipper"),
    )
    canned = [CheckResult("Backend", Status.FAIL, "down", hint="fix")]
    monkeypatch.setattr(preflight, "run_preflight", lambda ctx, **k: canned)

    rc = app_module.main(["--doctor"])
    assert rc == 1  # a FAIL → non-zero
    out = capsys.readouterr().out
    assert "preflight" in out.lower()
    assert "Backend" in out
