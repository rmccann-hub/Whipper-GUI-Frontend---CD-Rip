"""Tests for the host-stack bootstrap (deps/host_setup.py).

Driven entirely through a fake CommandRunner, so no Distrobox/podman/sudo is
touched — the orchestration, idempotency, distro detection, dry-run, cancel,
and failure-stop behaviour are all verified offline. (The real command
execution is the hardware-gated part, validated on a target machine.)
"""

from __future__ import annotations

from pathlib import Path

from whipper_gui.deps.host_setup import (
    CYANRIP_COPR_REPO_CONTENT,
    CYANRIP_COPR_REPO_PATH,
    HostSetup,
    StepStatus,
    cyanrip_on_host,
    install_argv,
)


class _FakeRunner:
    def __init__(self) -> None:
        self.present: set[str] = set()
        self.paths: set[Path] = set()
        self.calls: list[list[str]] = []
        self.results: dict[tuple[str, ...], tuple[int, str]] = {}
        self.default: tuple[int, str] = (0, "")

    def which(self, name: str) -> bool:
        return name in self.present

    def exists(self, path: Path) -> bool:
        return path in self.paths

    def run(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        return self.results.get(tuple(argv), self.default)


def _fedora(tmp_path: Path) -> Path:
    p = tmp_path / "os-release"
    p.write_text('ID=fedora\nID_LIKE="rhel fedora"\n', encoding="utf-8")
    return p


def _setup(tmp_path: Path, runner: _FakeRunner) -> HostSetup:
    return HostSetup(
        runner=runner,
        os_release=_fedora(tmp_path),
        whipper_path=tmp_path / "whipper",
        flac_path=tmp_path / "flac",
    )


def _ids(results: list) -> list[tuple[str, str]]:
    return [(r.step_id, r.status.value) for r in results]


# --- Easy: nothing present → all five steps run --------------------------


def test_fresh_system_runs_all_steps(tmp_path: Path) -> None:
    runner = _FakeRunner()  # nothing present
    results = _setup(tmp_path, runner).run()

    assert [r.step_id for r in results] == [
        "distrobox",
        "backend",
        "container",
        "tools",
        "export",
    ]
    assert all(r.status is StepStatus.RAN for r in results)
    # The actual install/create/export commands were issued.
    flat = [" ".join(c) for c in runner.calls]
    assert any("dnf install -y distrobox" in c for c in flat)
    assert any("dnf install -y podman" in c for c in flat)
    assert any("distrobox create --yes --name ripping" in c for c in flat)
    assert any("sudo dnf install -y whipper flac python3-setuptools" in c for c in flat)
    assert any("distrobox-export --bin /usr/bin/whipper" in c for c in flat)


def test_host_root_installs_use_pkexec_not_sudo(tmp_path: Path) -> None:
    """A GUI has no TTY for sudo to prompt on, so host package installs must
    use pkexec (graphical polkit). In-container installs stay sudo (distrobox
    grants passwordless sudo)."""
    runner = _FakeRunner()  # nothing present
    _setup(tmp_path, runner).run()
    flat = [" ".join(c) for c in runner.calls]
    assert any(c.startswith("pkexec dnf install -y distrobox") for c in flat)
    assert any(c.startswith("pkexec dnf install -y podman") for c in flat)
    # The in-container tool install is still plain sudo (no host TTY needed).
    assert any("-- sudo dnf install -y whipper" in c for c in flat)
    assert not any(c.startswith("sudo ") for c in flat)


# --- Live progress: a RUNNING ping precedes each executing step ----------


def test_running_ping_emitted_before_executing_step(tmp_path: Path) -> None:
    runner = _FakeRunner()  # nothing present → every step executes
    emitted: list = []
    results = _setup(tmp_path, runner).run(progress=emitted.append)

    # For the first executing step, the UI saw RUNNING *before* RAN.
    distrobox = [r.status for r in emitted if r.step_id == "distrobox"]
    assert distrobox[0] is StepStatus.RUNNING
    assert StepStatus.RAN in distrobox
    # RUNNING is transient — it must NOT appear in the returned results list.
    assert all(r.status is not StepStatus.RUNNING for r in results)


def test_checking_ping_precedes_slow_probe_even_when_done(tmp_path: Path) -> None:
    """On an already-set-up system nothing executes, but the container-entering
    'tools' probe (a `distrobox enter` whose first run does distrobox's slow
    container init) is preceded by a transient 'checking…' ping — so the status
    line reflects current activity instead of sitting on the previous step
    (which looked like a freeze). Fast-probe steps emit no ping, and RUNNING
    never lands in the returned results."""
    runner = _FakeRunner()
    runner.present = {"distrobox", "podman"}
    runner.paths = {tmp_path / "whipper", tmp_path / "flac"}
    runner.results[("distrobox", "list")] = (0, "ripping\n")
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "whipper")
    ] = (0, "/usr/bin/whipper")
    emitted: list = []
    results = _setup(tmp_path, runner).run(progress=emitted.append)

    running = [r for r in emitted if r.status is StepStatus.RUNNING]
    # The only pings are the pre-probe 'checking' ones for container-entering
    # steps; the fast-probe steps (distrobox/backend/container/export) emit none.
    assert running, "expected a 'checking' ping before the slow container probe"
    assert all(r.step_id in {"tools", "cyanrip"} for r in running)
    assert all("checking" in r.detail for r in running)
    # RUNNING is transient — never recorded in the final results.
    assert all(r.status is not StepStatus.RUNNING for r in results)
    assert all(r.status is StepStatus.DONE for r in results)


# --- Idempotent: everything present → nothing runs -----------------------


def test_fully_set_up_system_is_all_done(tmp_path: Path) -> None:
    runner = _FakeRunner()
    runner.present = {"distrobox", "podman"}
    runner.paths = {tmp_path / "whipper", tmp_path / "flac"}
    runner.results[("distrobox", "list")] = (0, "ID | ripping | Created\n")
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "whipper")
    ] = (0, "/usr/bin/whipper")

    results = _setup(tmp_path, runner).run()

    assert all(r.status is StepStatus.DONE for r in results)
    # No mutating commands — only the read-only probes (list / command -v).
    flat = [" ".join(c) for c in runner.calls]
    assert not any("install" in c or "create" in c or "export" in c for c in flat)


# --- Hard: partial state — only the missing step runs --------------------


def test_only_export_runs_when_container_ready_but_not_exported(
    tmp_path: Path,
) -> None:
    runner = _FakeRunner()
    runner.present = {"distrobox", "podman"}
    # whipper NOT exported (paths empty).
    runner.results[("distrobox", "list")] = (0, "ripping\n")
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "whipper")
    ] = (0, "/usr/bin/whipper")

    results = _setup(tmp_path, runner).run()

    status = dict(_ids(results))
    assert status["distrobox"] == "done"
    assert status["backend"] == "done"
    assert status["container"] == "done"
    assert status["tools"] == "done"
    assert status["export"] == "ran"
    flat = [" ".join(c) for c in runner.calls]
    assert any("distrobox-export --bin /usr/bin/whipper" in c for c in flat)
    assert any("distrobox-export --bin /usr/bin/metaflac" in c for c in flat)
    # Regression (2026-06-27): the tools step installs flac (titled "whipper +
    # flac") but the export step used to omit it, so `flac --test` verification
    # and the CTDB audio check couldn't find it on the host. It must export now.
    assert any("distrobox-export --bin /usr/bin/flac" in c for c in flat)


# --- Edge / failure: a step fails → pipeline stops -----------------------


def test_failure_stops_pipeline(tmp_path: Path) -> None:
    runner = _FakeRunner()  # nothing present
    create = (
        "distrobox",
        "create",
        "--yes",
        "--name",
        "ripping",
        "--image",
        "registry.fedoraproject.org/fedora-toolbox:latest",
    )
    runner.results[create] = (1, "Error: cannot pull image")

    results = _setup(tmp_path, runner).run()
    status = dict(_ids(results))
    assert status["distrobox"] == "ran"
    assert status["backend"] == "ran"
    assert status["container"] == "failed"
    # Steps after the failure don't run.
    assert status["tools"] == "cancelled"
    assert status["export"] == "cancelled"
    # The failure detail surfaces the error line.
    failed = next(r for r in results if r.status is StepStatus.FAILED)
    assert "cannot pull image" in failed.detail


# --- Unexpected: unknown distro can't auto-install the backend -----------


def test_unknown_distro_backend_is_manual_failure(tmp_path: Path) -> None:
    osr = tmp_path / "os-release"
    osr.write_text("ID=tinycore\n", encoding="utf-8")
    runner = _FakeRunner()
    # distrobox has an upstream installer fallback, so it "runs"; podman
    # has no universal command → that step fails with a manual message.
    setup = HostSetup(runner=runner, os_release=osr, whipper_path=tmp_path / "whipper")
    results = setup.run()
    status = dict(_ids(results))
    assert status["distrobox"] == "ran"  # upstream installer fallback
    assert status["backend"] == "failed"
    backend = next(r for r in results if r.step_id == "backend")
    assert "manually" in backend.detail.lower()


# --- Dry run: nothing executes -------------------------------------------


def test_dry_run_reports_without_executing(tmp_path: Path) -> None:
    runner = _FakeRunner()  # nothing present
    results = _setup(tmp_path, runner).run(dry_run=True)

    assert all(r.status is StepStatus.WOULD_RUN for r in results)
    # No commands were actually run (the probes short-circuit when distrobox
    # isn't present, so the runner is never invoked).
    assert runner.calls == []
    # The detail shows what *would* run.
    distrobox = next(r for r in results if r.step_id == "distrobox")
    assert "dnf install -y distrobox" in distrobox.detail


# --- Cancellation --------------------------------------------------------


def test_cancel_before_first_step(tmp_path: Path) -> None:
    runner = _FakeRunner()
    results = _setup(tmp_path, runner).run(cancelled=lambda: True)
    assert all(r.status is StepStatus.CANCELLED for r in results)
    assert runner.calls == []


# --- is_ready + StepResult.ok --------------------------------------------


def test_is_ready_reflects_exported_whipper(tmp_path: Path) -> None:
    runner = _FakeRunner()
    setup = _setup(tmp_path, runner)
    assert setup.is_ready() is False
    runner.paths = {tmp_path / "whipper"}
    assert setup.is_ready() is False  # whipper alone isn't enough — flac too
    runner.paths = {tmp_path / "whipper", tmp_path / "flac"}
    assert setup.is_ready() is True


# --- cyanrip step (KDD-18: optional backend install via COPR) -------------


def _setup_cyanrip(tmp_path: Path, runner: _FakeRunner) -> HostSetup:
    return HostSetup(
        runner=runner,
        os_release=_fedora(tmp_path),
        whipper_path=tmp_path / "whipper",
        cyanrip_path=tmp_path / "cyanrip",
        flac_path=tmp_path / "flac",
        include_cyanrip=True,
    )


def _container_ready(runner: _FakeRunner) -> None:
    """Mark distrobox/podman/container/whipper-in-container as present."""
    runner.present = {"distrobox", "podman"}
    runner.results[("distrobox", "list")] = (0, "ripping\n")
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "whipper")
    ] = (0, "/usr/bin/whipper")


def test_cyanrip_step_absent_by_default(tmp_path: Path) -> None:
    """Backwards compatible: without the flag, the plan is the original five
    steps and no cyanrip command is ever issued."""
    runner = _FakeRunner()
    setup = _setup(tmp_path, runner)
    assert "cyanrip" not in setup.STEP_IDS
    setup.run()
    flat = [" ".join(c) for c in runner.calls]
    assert not any("cyanrip" in c for c in flat)


def test_cyanrip_step_ordered_between_tools_and_export(tmp_path: Path) -> None:
    setup = _setup_cyanrip(tmp_path, _FakeRunner())
    assert setup.STEP_IDS == (
        "distrobox",
        "backend",
        "container",
        "tools",
        "cyanrip",
        "export",
    )


def test_fresh_system_with_cyanrip_installs_and_exports(tmp_path: Path) -> None:
    runner = _FakeRunner()
    # The cyanrip-in-container probe must fail until installed; everything
    # else defaults to success in the fake.
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "cyanrip")
    ] = (1, "")
    results = _setup_cyanrip(tmp_path, runner).run()

    status = dict(_ids(results))
    assert status["cyanrip"] == "ran"
    assert status["export"] == "ran"
    flat = [" ".join(c) for c in runner.calls]
    assert any("sudo dnf install -y cyanrip" in c for c in flat)
    assert any("distrobox-export --bin /usr/bin/cyanrip" in c for c in flat)


def test_copr_repo_content_passed_as_data_not_spliced_into_script(
    tmp_path: Path,
) -> None:
    """The repo stanza must reach `sh` as a positional argument ("$1"), not
    be embedded in the -c script — otherwise $releasever would be expanded
    (to nothing) and the repo would break on every Fedora version."""
    runner = _FakeRunner()
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "cyanrip")
    ] = (1, "")
    _setup_cyanrip(tmp_path, runner).run()

    write = next(c for c in runner.calls if CYANRIP_COPR_REPO_CONTENT in c)
    script = write[write.index("-c") + 1]
    assert CYANRIP_COPR_REPO_PATH in script
    assert "$releasever" not in script  # stays in the data argument only
    assert write[-1] == CYANRIP_COPR_REPO_CONTENT


def test_copr_repo_stanza_is_generic_and_gpg_checked() -> None:
    """Guards against accidentally pinning a Fedora version into the baseurl
    or disabling signature verification."""
    assert "fedora-$releasever-$basearch" in CYANRIP_COPR_REPO_CONTENT
    assert "gpgcheck=1" in CYANRIP_COPR_REPO_CONTENT
    assert "gpgkey=https://" in CYANRIP_COPR_REPO_CONTENT


def test_cyanrip_already_installed_and_exported_is_all_done(tmp_path: Path) -> None:
    runner = _FakeRunner()
    _container_ready(runner)
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "cyanrip")
    ] = (0, "/usr/bin/cyanrip")
    runner.paths = {tmp_path / "whipper", tmp_path / "cyanrip", tmp_path / "flac"}

    results = _setup_cyanrip(tmp_path, runner).run()

    assert all(r.status is StepStatus.DONE for r in results)
    flat = [" ".join(c) for c in runner.calls]
    assert not any("install" in c or "export" in c for c in flat)


def test_export_reruns_when_cyanrip_not_yet_exported(tmp_path: Path) -> None:
    """whipper already exported but cyanrip not → the export step is not
    'done' and exports cyanrip too."""
    runner = _FakeRunner()
    _container_ready(runner)
    runner.results[
        ("distrobox", "enter", "ripping", "--", "command", "-v", "cyanrip")
    ] = (0, "/usr/bin/cyanrip")
    # whipper + flac exported, cyanrip missing → export reruns solely for cyanrip.
    runner.paths = {tmp_path / "whipper", tmp_path / "flac"}

    results = _setup_cyanrip(tmp_path, runner).run()

    status = dict(_ids(results))
    assert status["cyanrip"] == "done"
    assert status["export"] == "ran"
    flat = [" ".join(c) for c in runner.calls]
    assert any("distrobox-export --bin /usr/bin/cyanrip" in c for c in flat)


def test_is_ready_requires_cyanrip_only_when_included(tmp_path: Path) -> None:
    runner = _FakeRunner()
    runner.paths = {tmp_path / "whipper", tmp_path / "flac"}
    assert _setup(tmp_path, runner).is_ready() is True
    assert _setup_cyanrip(tmp_path, runner).is_ready() is False
    runner.paths.add(tmp_path / "cyanrip")
    assert _setup_cyanrip(tmp_path, runner).is_ready() is True


def test_cyanrip_on_host_checks_export_then_path(tmp_path: Path, monkeypatch) -> None:
    exported = tmp_path / "cyanrip"
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert cyanrip_on_host(exported) is False
    exported.write_text("#!/bin/sh\n", encoding="utf-8")
    assert cyanrip_on_host(exported) is True
    # Native install (on PATH) also counts.
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/cyanrip")
    assert cyanrip_on_host(tmp_path / "missing") is True


# --- install_argv distro matrix ------------------------------------------


def test_install_argv_picks_package_manager(tmp_path: Path) -> None:
    def osr(content: str) -> Path:
        p = tmp_path / f"os-{abs(hash(content))}"
        p.write_text(content, encoding="utf-8")
        return p

    assert install_argv("distrobox", osr("ID=fedora\n"))[:3] == [
        "sudo",
        "dnf",
        "install",
    ]
    assert install_argv("podman", osr('ID=ubuntu\nID_LIKE="debian"\n'))[:2] == [
        "sudo",
        "apt-get",
    ]
    assert install_argv("distrobox", osr("ID=arch\n"))[:2] == ["sudo", "pacman"]
    assert install_argv("podman", osr("ID=opensuse-leap\nID_LIKE=suse\n"))[:2] == [
        "sudo",
        "zypper",
    ]
    # Unknown distro: distrobox falls back to the upstream installer; podman
    # has no universal command.
    unknown = osr("ID=plan9\n")
    assert install_argv("distrobox", unknown)[0] == "sh"
    assert install_argv("podman", unknown) == []
