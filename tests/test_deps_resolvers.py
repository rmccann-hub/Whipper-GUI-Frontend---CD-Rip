"""Tests for whipper_gui.deps.resolvers.

Each resolver gets driven with fake callbacks and a fake subprocess.run
so we exercise the control flow without needing flatpak or any real
install machinery on the test host.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from whipper_gui.deps import resolvers as resolvers_module
from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.registry import DependencySpec, Tier
from whipper_gui.deps.resolvers import (
    AutoInstaller,
    ManualPrompt,
    MissingItem,
    QueuedInstaller,
)

# --- Helpers --------------------------------------------------------------


def _absent_probe() -> ProbeResult:
    return ProbeResult(present=False, version=None, location=None)


def _spec(
    dep_id: str,
    tier: Tier = Tier.AUTO,
    install_command: list[str] | None = None,
) -> DependencySpec:
    return DependencySpec(
        dep_id=dep_id,
        display_name=dep_id,
        probe=lambda: ProbeResult(present=True, version=(1, 0, 0), location=""),
        min_version=(0, 0, 0),
        tier=tier,
        install_command=install_command,
        search_string=f"install {dep_id}",
    )


def _ok_run(*a: Any, **kw: Any) -> Any:
    return SimpleNamespace(stdout="ok\n", stderr="", returncode=0)


def _fail_run(*a: Any, **kw: Any) -> Any:
    return SimpleNamespace(stdout="", stderr="error: nope\n", returncode=1)


# --- AutoInstaller --------------------------------------------------------


def test_auto_installer_declines_when_consent_says_no() -> None:
    spec = _spec("picard", Tier.AUTO, install_command=["flatpak", "install"])
    item = MissingItem(spec=spec, probe=_absent_probe())

    installer = AutoInstaller(consent=lambda _: False)
    results = installer.resolve([item])

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].user_declined is True


def test_auto_installer_runs_command_when_consent_says_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("picard", Tier.AUTO, install_command=["flatpak", "install"])
    item = MissingItem(spec=spec, probe=_absent_probe())

    monkeypatch.setattr(resolvers_module.subprocess, "run", _ok_run)

    installer = AutoInstaller(consent=lambda _: True)
    results = installer.resolve([item])

    assert results[0].success is True
    assert results[0].message == "installed"


def test_auto_installer_reports_command_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("picard", Tier.AUTO, install_command=["flatpak", "install"])
    item = MissingItem(spec=spec, probe=_absent_probe())

    monkeypatch.setattr(resolvers_module.subprocess, "run", _fail_run)

    installer = AutoInstaller(consent=lambda _: True)
    results = installer.resolve([item])

    assert results[0].success is False
    assert "error" in results[0].message.lower()


def test_auto_installer_handles_missing_install_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("picard", Tier.AUTO, install_command=["nonexistent-tool"])
    item = MissingItem(spec=spec, probe=_absent_probe())

    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError("/usr/bin/nonexistent-tool")

    monkeypatch.setattr(resolvers_module.subprocess, "run", not_found)

    installer = AutoInstaller(consent=lambda _: True)
    results = installer.resolve([item])

    assert results[0].success is False
    assert "not found" in results[0].message


def test_auto_installer_skips_items_with_no_install_command() -> None:
    spec = _spec("whipper", Tier.AUTO, install_command=None)
    item = MissingItem(spec=spec, probe=_absent_probe())

    installer = AutoInstaller(consent=lambda _: True)
    results = installer.resolve([item])

    # An item without an install_command isn't actionable for the
    # AutoInstaller — silently drops out of the list.
    assert results == []


# --- QueuedInstaller ------------------------------------------------------


def test_queued_installer_passes_dialog_selection_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_a = _spec("picard", install_command=["flatpak", "install"])
    spec_b = _spec("other", install_command=["other-installer"])
    items = [
        MissingItem(spec=spec_a, probe=_absent_probe()),
        MissingItem(spec=spec_b, probe=_absent_probe()),
    ]

    # User picks only the first.
    def pick_first(input_items: list[MissingItem]) -> list[MissingItem]:
        return [input_items[0]]

    monkeypatch.setattr(resolvers_module.subprocess, "run", _ok_run)

    installer = QueuedInstaller(dialog_callback=pick_first)
    results = installer.resolve(items)

    # One result for the approved item, one for the declined item.
    assert len(results) == 1
    assert results[0].spec.dep_id == "picard"
    assert results[0].success is True


def test_queued_installer_empty_selection_declines_all() -> None:
    spec = _spec("picard", install_command=["flatpak", "install"])
    item = MissingItem(spec=spec, probe=_absent_probe())

    installer = QueuedInstaller(dialog_callback=lambda items: [])
    results = installer.resolve([item])

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].user_declined is True


# --- ManualPrompt ---------------------------------------------------------


def test_manual_prompt_invokes_dialog_per_item() -> None:
    spec_a = _spec("whipper", Tier.MANUAL)
    spec_b = _spec("metaflac", Tier.MANUAL)
    items = [
        MissingItem(spec=spec_a, probe=_absent_probe()),
        MissingItem(spec=spec_b, probe=_absent_probe()),
    ]

    seen: list[str] = []

    def record(item: MissingItem) -> None:
        seen.append(item.spec.dep_id)

    prompt = ManualPrompt(dialog_callback=record)
    results = prompt.resolve(items)

    assert seen == ["whipper", "metaflac"]
    assert all(not r.success for r in results)
    assert all("manual install required" in r.message for r in results)
