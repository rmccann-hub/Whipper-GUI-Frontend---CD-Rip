"""Host-stack bootstrap — the GUI-driven equivalent of ``setup-host.sh``.

This is the **bootstrap arm of the dependency self-management subsystem**
(Critical Rule #6 / KDD-17): it owns the multi-step, stateful host stack that
lives *outside* the GUI — Distrobox + a container backend + the ``ripping``
container + whipper exported to ``~/.local/bin`` — so a non-technical user
never has to open a terminal. The GUI's runtime-tool *presence* checks
(whipper/metaflac/Picard) stay in ``registry.py``; this module sets up the
container those tools come from.

Everything runs through an injected :class:`CommandRunner`, so the
orchestration is fully unit-testable and supports a dry-run (commands are
reported, never executed). The real runner (:class:`SubprocessRunner`) shells
out; tests pass a fake. Steps are **idempotent** — each checks current state
first and is skipped when already satisfied — mirroring ``setup-host.sh``.

Note on routing: this is host *setup*, not ripping. Ripping still goes through
the host-exported ``~/.local/bin/whipper`` (Critical Rule #3); creating the
container and installing whipper into it is exactly the bootstrap KDD-17
sanctions doing from the GUI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from whipper_gui.deps.step_engine import (
    CommandRunner,
    StepResult,
    StepStatus,
)
from whipper_gui.paths import (
    CYANRIP_BINARY_DEFAULT,
    FLAC_BINARY_DEFAULT,
    WHIPPER_BINARY_DEFAULT,
)

log = logging.getLogger(__name__)

DEFAULT_CONTAINER: str = "ripping"
DEFAULT_IMAGE: str = "registry.fedoraproject.org/fedora-toolbox:latest"
_OS_RELEASE: Path = Path("/etc/os-release")

# Steps whose "is this already done?" probe ENTERS the container
# (`distrobox enter`). The FIRST enter after creating the container triggers
# distrobox's multi-minute one-time container init (it installs base packages),
# so the probe itself can be slow. We emit a "checking…" ping BEFORE these
# probes so the status line reflects what's happening instead of sitting on the
# previous step's text — which looked like a freeze (real-user report
# 2026-06-26: the wizard appeared stuck at "'ripping' container — working…").
_SLOW_PROBE_STEPS: frozenset[str] = frozenset({"tools", "cyanrip"})

# --- cyanrip packaging (KDD-18) ---------------------------------------------
# Fedora does NOT package cyanrip (verified 2026-06-09: no result in the
# official repos or RPM Fusion; cyanrip's own README lists Debian/openSUSE/
# Alpine/Void/Nix but not Fedora). The one prebuilt source for our
# fedora-toolbox container is the COPR `barsnick/non-fed` (a Fedora
# contributor's "not-in-Fedora" repo), which has succeeded cyanrip builds
# for Fedora 42/43/44 + rawhide on x86_64, GPG-signed. The fallback, if that
# COPR ever disappears, is a meson source build (all build deps ARE in
# Fedora: ffmpeg-free-devel, libcdio-paranoia-devel, libmusicbrainz5-devel,
# libcurl-devel) — see docs/archive/ecosystem-audit-2026-06.md.
#
# We write the standard COPR repo stanza ourselves instead of running
# `dnf copr enable` because the copr plugin isn't guaranteed to be in the
# container image (dnf4 vs dnf5 ship it differently), while a .repo file
# works everywhere. The content below is exactly what `dnf copr enable`
# would write: $releasever/$basearch keep it valid across Fedora versions,
# and gpgcheck=1 + the COPR-published key keep the packages verified.
CYANRIP_COPR_REPO_PATH: str = "/etc/yum.repos.d/copr-barsnick-non-fed.repo"
CYANRIP_COPR_REPO_CONTENT: str = """\
[copr:copr.fedorainfracloud.org:barsnick:non-fed]
name=Copr repo for non-fed owned by barsnick (provides cyanrip)
baseurl=https://download.copr.fedorainfracloud.org/results/barsnick/non-fed/fedora-$releasever-$basearch/
type=rpm-md
gpgcheck=1
gpgkey=https://download.copr.fedorainfracloud.org/results/barsnick/non-fed/pubkey.gpg
repo_gpgcheck=0
skip_if_unavailable=True
enabled=1
"""

# The step-engine vocabulary (StepStatus / StepResult / CommandRunner /
# SubprocessRunner) lives in deps/step_engine.py, shared with host_teardown.py;
# it is imported above for this module's own use.

# --- Distro detection -------------------------------------------------------


def _os_release_ids(os_release: Path) -> str:
    """Return a lowercase "ID ID_LIKE" string from os-release, or ""."""
    try:
        text = os_release.read_text(encoding="utf-8")
    except OSError:
        return ""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if value:
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}".lower()


def install_argv(
    tool: str, os_release: Path = _OS_RELEASE, elevate: str = "sudo"
) -> list[str]:
    """The host package-manager argv to install `tool` (distrobox/podman).

    Mirrors setup-host.sh's distro `case`. `elevate` is the privilege-
    escalation command prefixed to the install: the shell script uses
    ``sudo`` (it has a TTY), but the GUI path uses ``pkexec`` so root is
    obtained via a graphical polkit prompt — a GUI subprocess has no
    terminal for ``sudo`` to read a password from. Falls back to the
    upstream Distrobox installer for an unknown distro when installing
    distrobox; for podman on an unknown distro there's no safe universal
    command, so the caller surfaces a manual message (we return []).
    """
    ids = _os_release_ids(os_release)
    if any(d in ids for d in ("fedora", "rhel", "centos")):
        return [elevate, "dnf", "install", "-y", tool]
    if any(d in ids for d in ("debian", "ubuntu")):
        return [elevate, "apt-get", "install", "-y", tool]
    if "arch" in ids:
        return [elevate, "pacman", "-S", "--noconfirm", tool]
    if "suse" in ids:
        return [elevate, "zypper", "--non-interactive", "install", tool]
    # Unknown distro.
    if tool == "distrobox":
        return [
            "sh",
            "-c",
            "curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh",
        ]
    return []  # podman on an unknown distro → manual


# --- Orchestrator -----------------------------------------------------------


@dataclass
class HostSetup:
    """Plans and runs the host-stack bootstrap (idempotently)."""

    runner: CommandRunner
    container: str = DEFAULT_CONTAINER
    image: str = DEFAULT_IMAGE
    os_release: Path = _OS_RELEASE
    whipper_path: Path = WHIPPER_BINARY_DEFAULT
    cyanrip_path: Path = CYANRIP_BINARY_DEFAULT
    flac_path: Path = FLAC_BINARY_DEFAULT
    # Privilege escalation for host-root installs. "pkexec" (the default)
    # shows a graphical polkit prompt — correct for a GUI with no TTY. On
    # Bazzite/Silverblue distrobox+podman are preinstalled, so these steps
    # are skipped and no prompt appears at all.
    elevate: str = "pkexec"
    # Also install + export the cyanrip backend (KDD-18). Off by default —
    # whipper is the default backend; the main window turns this on when
    # `Config.ripper_backend == "cyanrip"`.
    include_cyanrip: bool = False
    # Ordered step ids, exposed for the dialog/tests. Computed in
    # __post_init__ because the cyanrip step is optional.
    STEP_IDS: tuple[str, ...] = field(default=(), init=False)

    def __post_init__(self) -> None:
        steps = ["distrobox", "backend", "container", "tools"]
        if self.include_cyanrip:
            steps.append("cyanrip")
        steps.append("export")
        self.STEP_IDS = tuple(steps)

    # --- State probes (each "is this step already done?") ---

    def distrobox_present(self) -> bool:
        return self.runner.which("distrobox")

    def backend_present(self) -> bool:
        return self.runner.which("podman") or self.runner.which("docker")

    def container_exists(self) -> bool:
        if not self.distrobox_present():
            return False
        rc, out = self.runner.run(["distrobox", "list"])
        if rc != 0:
            return False
        # `distrobox list` prints a table; match the name as a whole word.
        return any(self.container in line.split() for line in out.splitlines())

    def whipper_in_container(self) -> bool:
        if not self.container_exists():
            return False
        rc, _ = self.runner.run(
            ["distrobox", "enter", self.container, "--", "command", "-v", "whipper"]
        )
        return rc == 0

    def whipper_exported(self) -> bool:
        return self.runner.exists(self.whipper_path)

    def cyanrip_in_container(self) -> bool:
        if not self.container_exists():
            return False
        rc, _ = self.runner.run(
            ["distrobox", "enter", self.container, "--", "command", "-v", "cyanrip"]
        )
        return rc == 0

    def cyanrip_exported(self) -> bool:
        return self.runner.exists(self.cyanrip_path)

    def flac_exported(self) -> bool:
        return self.runner.exists(self.flac_path)

    def _export_done(self) -> bool:
        """The export step is satisfied when every requested binary is on host.

        `flac` is checked alongside whipper because the tools step installs it
        (titled "whipper + flac") and `flac --test` needs it on the host to
        verify rips a backend didn't self-verify (cyanrip) and to decode for
        the CTDB cross-check. It was historically installed-but-not-exported,
        so checking it here makes a wizard re-run repair an existing setup.
        """
        if not self.whipper_exported():
            return False
        if not self.flac_exported():
            return False
        return (not self.include_cyanrip) or self.cyanrip_exported()

    def is_ready(self) -> bool:
        """True when the whole stack is in place (ripper reachable on host)."""
        return self._export_done()

    # --- The plan ---

    def _commands_for(self, step_id: str) -> list[list[str]]:
        """The argv list a step runs when it's NOT already done."""
        if step_id == "distrobox":
            return [install_argv("distrobox", self.os_release, self.elevate)]
        if step_id == "backend":
            return [install_argv("podman", self.os_release, self.elevate)]
        if step_id == "container":
            return [
                [
                    "distrobox",
                    "create",
                    "--yes",
                    "--name",
                    self.container,
                    "--image",
                    self.image,
                ]
            ]
        if step_id == "tools":
            return [
                [
                    "distrobox",
                    "enter",
                    self.container,
                    "--",
                    "sudo",
                    "dnf",
                    "install",
                    "-y",
                    "whipper",
                    "flac",
                    "python3-setuptools",
                ]
            ]
        if step_id == "cyanrip":
            return [
                # Drop the COPR repo file. The stanza is passed as its own
                # argv element ("$1"), NOT spliced into the script string, so
                # nothing in it (e.g. $releasever) is shell-expanded.
                [
                    "distrobox",
                    "enter",
                    self.container,
                    "--",
                    "sudo",
                    "sh",
                    "-c",
                    f'printf %s "$1" > {CYANRIP_COPR_REPO_PATH}',
                    "write-copr-repo",
                    CYANRIP_COPR_REPO_CONTENT,
                ],
                [
                    "distrobox",
                    "enter",
                    self.container,
                    "--",
                    "sudo",
                    "dnf",
                    "install",
                    "-y",
                    "cyanrip",
                ],
            ]
        if step_id == "export":
            # distrobox-export is idempotent (re-exporting overwrites the
            # wrapper), so re-running already-exported binaries is harmless.
            # flac (the decoder) must be exported too — the tools step installs
            # it but a past version forgot to export it, leaving `flac --test`
            # verification and the CTDB audio check unable to find it.
            binaries = ["/usr/bin/whipper", "/usr/bin/metaflac", "/usr/bin/flac"]
            if self.include_cyanrip:
                binaries.append("/usr/bin/cyanrip")
            return [
                [
                    "distrobox",
                    "enter",
                    self.container,
                    "--",
                    "distrobox-export",
                    "--bin",
                    b,
                ]
                for b in binaries
            ]
        raise ValueError(f"unknown step: {step_id}")  # pragma: no cover

    def _is_done(self, step_id: str) -> bool:
        return {
            "distrobox": self.distrobox_present,
            "backend": self.backend_present,
            "container": self.container_exists,
            "tools": self.whipper_in_container,
            "cyanrip": self.cyanrip_in_container,
            "export": self._export_done,
        }[step_id]()

    _TITLES: dict[str, str] = field(
        default_factory=lambda: {
            "distrobox": "Distrobox",
            "backend": "Container backend (podman)",
            "container": f"'{DEFAULT_CONTAINER}' container",
            "tools": "whipper + flac (in container)",
            "cyanrip": "cyanrip backend (in container)",
            "export": "Export tools to ~/.local/bin",
        },
        init=False,
    )

    def run(
        self,
        progress: Callable[[StepResult], None] | None = None,
        dry_run: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[StepResult]:
        """Run the bootstrap. Returns one StepResult per step.

        Stops at the first failed step (later steps depend on it) and marks
        the remainder CANCELLED. `cancelled()` is polled between steps so the
        dialog can abort cleanly. `dry_run` reports WOULD_RUN without
        executing anything that's not already done.
        """
        results: list[StepResult] = []

        def notify(r: StepResult) -> None:
            """Push a status update to the UI without recording it as a final
            result (used for the transient RUNNING ping)."""
            if progress is not None:
                progress(r)

        def record(r: StepResult) -> None:
            results.append(r)
            notify(r)

        stop = False
        for step_id in self.STEP_IDS:
            title = self._TITLES[step_id]
            if stop:
                record(StepResult(step_id, title, StepStatus.CANCELLED))
                continue
            if cancelled is not None and cancelled():
                record(StepResult(step_id, title, StepStatus.CANCELLED))
                stop = True
                continue
            # Steps whose probe enters the container can be slow (the first
            # `distrobox enter` runs distrobox's container init); ping BEFORE the
            # probe so the UI shows current activity, not a stale prior step.
            if step_id in _SLOW_PROBE_STEPS:
                notify(
                    StepResult(
                        step_id,
                        title,
                        StepStatus.RUNNING,
                        "checking the container — the first start after setup "
                        "can take a minute…",
                    )
                )
            if self._is_done(step_id):
                record(StepResult(step_id, title, StepStatus.DONE, "already present"))
                continue
            commands = [c for c in self._commands_for(step_id) if c]
            if not commands:
                record(
                    StepResult(
                        step_id,
                        title,
                        StepStatus.FAILED,
                        "no automatic install available for this system — "
                        "install it manually and retry",
                    )
                )
                stop = True
                continue
            if dry_run:
                detail = "; ".join(" ".join(c) for c in commands)
                record(StepResult(step_id, title, StepStatus.WOULD_RUN, detail))
                continue
            # Live "currently working" ping BEFORE the (often slow) command, so
            # the UI shows what's happening instead of freezing during a multi-
            # minute image pull or dnf install.
            notify(
                StepResult(
                    step_id, title, StepStatus.RUNNING, self._running_hint(step_id)
                )
            )
            ok, detail = self._run_commands(commands)
            if ok:
                record(StepResult(step_id, title, StepStatus.RAN, detail))
            else:
                record(StepResult(step_id, title, StepStatus.FAILED, detail))
                stop = True
        return results

    @staticmethod
    def _running_hint(step_id: str) -> str:
        """Reassuring sub-text for a step that's actively running.

        For the download-heavy steps, set an explicit time expectation: a
        real-user gave up ~4 minutes into the in-container `dnf install`
        (2026-06-26), quitting before the final export step — so the rip tool
        ended up installed in the container but not exported to the host. Saying
        "SEVERAL MINUTES" up front (not just "a few") keeps the user waiting.
        """
        if step_id == "container":
            return (
                "downloading the container image — this can take SEVERAL MINUTES "
                "the first time. The window stays usable; please don't close it."
            )
        if step_id in ("tools", "cyanrip"):
            return (
                "installing into the container — downloading packages, this can "
                "take SEVERAL MINUTES the first time. Please wait; don't close it."
            )
        return "working…"

    def _run_commands(self, commands: list[list[str]]) -> tuple[bool, str]:
        """Run each argv in order; stop at the first non-zero exit."""
        for argv in commands:
            rc, out = self.runner.run(argv)
            if rc != 0:
                return False, _last_meaningful_line(out) or f"exit {rc}"
        return True, "installed"


def cyanrip_on_host(cyanrip_path: Path = CYANRIP_BINARY_DEFAULT) -> bool:
    """True if cyanrip is reachable from the host.

    Either host-exported by the wizard (the canonical route, mirroring
    whipper) or installed natively and on PATH. Lives here — not in the UI —
    so dependency-presence logic stays inside the self-management subsystem
    (Critical Rule #6).
    """
    import shutil

    return cyanrip_path.exists() or shutil.which("cyanrip") is not None


def _last_meaningful_line(output: str) -> str:
    for line in reversed(output.strip().splitlines()):
        if line.strip():
            return line.strip()
    return ""
