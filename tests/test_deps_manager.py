"""Tests for whipper_gui.deps.manager.

The manager is constructed with a custom spec list and fake resolvers
so each test isolates one orchestration path.
"""

from __future__ import annotations

from typing import Callable

from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.manager import DependencyManager, DependencyReport
from whipper_gui.deps.registry import DependencySpec, Tier
from whipper_gui.deps.resolvers import (
    AutoInstaller,
    InstallResult,
    ManualPrompt,
    MissingItem,
    QueuedInstaller,
)


# --- Spec/probe factories -------------------------------------------------


def _spec(
    dep_id: str,
    probe: Callable[[], ProbeResult],
    tier: Tier = Tier.AUTO,
    min_version: tuple[int, ...] = (0, 0, 0),
    install_command: list[str] | None = None,
    fallback_tiers: tuple[Tier, ...] = (),
) -> DependencySpec:
    return DependencySpec(
        dep_id=dep_id,
        display_name=dep_id,
        probe=probe,
        min_version=min_version,
        tier=tier,
        install_command=install_command,
        search_string=f"install {dep_id}",
        fallback_tiers=fallback_tiers,
    )


def _present(version: tuple[int, ...] = (1, 0, 0)) -> Callable[[], ProbeResult]:
    return lambda: ProbeResult(present=True, version=version, location="/x")


def _absent() -> Callable[[], ProbeResult]:
    return lambda: ProbeResult(present=False, version=None, location=None)


# --- check_all ------------------------------------------------------------


def test_check_all_classifies_present_and_missing() -> None:
    specs = [
        _spec("present", _present()),
        _spec("missing", _absent()),
    ]
    mgr = DependencyManager(specs=specs)

    report = mgr.check_all()

    assert [s.dep_id for s in report.ok] == ["present"]
    assert [m.spec.dep_id for m in report.missing] == ["missing"]


def test_check_all_records_ok_versions() -> None:
    specs = [
        _spec("present", _present(version=(0, 10, 0))),
        _spec("missing", _absent()),
    ]
    mgr = DependencyManager(specs=specs)

    report = mgr.check_all()

    # The OK dep's detected version is stamped; the missing one is absent.
    assert report.ok_versions == {"present": (0, 10, 0)}


def test_check_all_treats_too_old_as_missing() -> None:
    specs = [
        _spec(
            "old",
            probe=lambda: ProbeResult(
                present=True, version=(0, 9, 0), location="/x"
            ),
            min_version=(1, 0, 0),
        ),
    ]
    mgr = DependencyManager(specs=specs)

    report = mgr.check_all()

    assert report.ok == []
    assert len(report.missing) == 1
    assert report.missing[0].spec.dep_id == "old"


def test_check_all_is_idempotent() -> None:
    specs = [_spec("x", _present()), _spec("y", _absent())]
    mgr = DependencyManager(specs=specs)

    r1 = mgr.check_all()
    r2 = mgr.check_all()

    assert [s.dep_id for s in r1.ok] == [s.dep_id for s in r2.ok]
    assert [m.spec.dep_id for m in r1.missing] == [
        m.spec.dep_id for m in r2.missing
    ]


# --- resolve_missing ------------------------------------------------------


def test_resolve_missing_dispatches_to_auto_for_auto_tier() -> None:
    spec = _spec(
        "picard",
        _absent(),
        tier=Tier.AUTO,
        install_command=["flatpak", "install"],
    )
    mgr = DependencyManager(
        auto=AutoInstaller(consent=lambda _: True),
        specs=[spec],
    )

    # Stub the install_one path by injecting a custom AutoInstaller
    # whose subprocess wouldn't actually run — easier: bypass with a
    # fake resolver.
    class FakeAuto:
        def __init__(self) -> None:
            self.called_with: list[MissingItem] = []

        def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
            self.called_with = items
            return [
                InstallResult(spec=item.spec, success=True, message="installed")
                for item in items
            ]

    fake_auto = FakeAuto()
    mgr._auto = fake_auto  # type: ignore[assignment]

    report = mgr.check_all()
    mgr.resolve_missing(report)

    assert len(fake_auto.called_with) == 1
    assert fake_auto.called_with[0].spec.dep_id == "picard"
    assert report.all_resolved is True


def test_resolve_missing_dispatches_to_manual_for_manual_tier() -> None:
    spec = _spec("whipper", _absent(), tier=Tier.MANUAL)

    seen: list[str] = []

    def record(item: MissingItem) -> None:
        seen.append(item.spec.dep_id)

    mgr = DependencyManager(
        manual=ManualPrompt(dialog_callback=record), specs=[spec]
    )

    report = mgr.check_all()
    mgr.resolve_missing(report)

    assert seen == ["whipper"]
    # Manual resolution never installs, so the report stays unresolved.
    assert report.all_resolved is False


def test_resolve_missing_cascades_to_fallback_on_failure() -> None:
    # Picard-style spec: AUTO preferred, MANUAL fallback.
    spec = _spec(
        "picard",
        _absent(),
        tier=Tier.AUTO,
        install_command=["flatpak", "install"],
        fallback_tiers=(Tier.MANUAL,),
    )

    class FailingAuto:
        def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
            return [
                InstallResult(
                    spec=item.spec, success=False, message="boom"
                )
                for item in items
            ]

    manual_seen: list[str] = []

    def record_manual(item: MissingItem) -> None:
        manual_seen.append(item.spec.dep_id)

    mgr = DependencyManager(
        manual=ManualPrompt(dialog_callback=record_manual), specs=[spec]
    )
    mgr._auto = FailingAuto()  # type: ignore[assignment]

    report = mgr.check_all()
    mgr.resolve_missing(report)

    # Both tiers ran: AUTO failed, MANUAL was invoked.
    assert manual_seen == ["picard"]
    # Two install_results: one from AUTO (fail), one from MANUAL (also
    # records as unsuccessful since manual never installs).
    assert len(report.install_results) == 2
    assert report.install_results[0].success is False
    assert report.install_results[1].success is False


def test_resolve_missing_does_not_cascade_when_user_declines() -> None:
    """User decline at AUTO tier should NOT cascade to QUEUED/MANUAL.

    Real-user testing on Bazzite hit the previous behavior where
    declining Picard's AUTO-tier consent dialog produced two more
    dialogs (QUEUED, then MANUAL). The user clicked No once and got
    three "dismiss this" prompts. Decline must short-circuit the
    cascade; only install failures (non-decline) should cascade.
    """
    spec = _spec(
        "picard",
        _absent(),
        tier=Tier.AUTO,
        install_command=["flatpak", "install"],
        fallback_tiers=(Tier.QUEUED, Tier.MANUAL),
    )

    class DecliningAuto:
        def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
            return [
                InstallResult(
                    spec=item.spec,
                    success=False,
                    message="user declined auto-install",
                    user_declined=True,
                )
                for item in items
            ]

    queued_dialog_calls: list[list[MissingItem]] = []
    manual_dialog_calls: list[str] = []

    def record_queued(items: list[MissingItem]) -> list[MissingItem]:
        queued_dialog_calls.append(items)
        return []

    def record_manual(item: MissingItem) -> None:
        manual_dialog_calls.append(item.spec.dep_id)

    mgr = DependencyManager(
        queued=QueuedInstaller(dialog_callback=record_queued),
        manual=ManualPrompt(dialog_callback=record_manual),
        specs=[spec],
    )
    mgr._auto = DecliningAuto()  # type: ignore[assignment]

    report = mgr.check_all()
    mgr.resolve_missing(report)

    # Only the AUTO tier ran. Decline short-circuited the cascade.
    assert queued_dialog_calls == []
    assert manual_dialog_calls == []
    # Exactly one install_result: the AUTO decline.
    assert len(report.install_results) == 1
    assert report.install_results[0].user_declined is True


def test_resolve_missing_still_cascades_on_non_decline_failure() -> None:
    """Verify the cascade fix didn't break the failure path.

    When AUTO fails for reasons OTHER than user decline (network,
    permission, missing tool), the cascade SHOULD still fire so the
    user can pick another install path.
    """
    spec = _spec(
        "picard",
        _absent(),
        tier=Tier.AUTO,
        install_command=["flatpak", "install"],
        fallback_tiers=(Tier.MANUAL,),
    )

    class NetworkFailingAuto:
        def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
            return [
                InstallResult(
                    spec=item.spec,
                    success=False,
                    message="install failed: connection refused",
                    user_declined=False,
                )
                for item in items
            ]

    manual_seen: list[str] = []

    def record_manual(item: MissingItem) -> None:
        manual_seen.append(item.spec.dep_id)

    mgr = DependencyManager(
        manual=ManualPrompt(dialog_callback=record_manual), specs=[spec]
    )
    mgr._auto = NetworkFailingAuto()  # type: ignore[assignment]

    report = mgr.check_all()
    mgr.resolve_missing(report)

    # Manual tier WAS invoked because the failure wasn't a decline.
    assert manual_seen == ["picard"]


def test_all_resolved_true_when_everything_probes_ok() -> None:
    specs = [_spec("a", _present()), _spec("b", _present())]
    mgr = DependencyManager(specs=specs)

    report = mgr.check_all()

    assert report.all_resolved is True


def test_all_resolved_false_when_missing_and_no_resolve_attempt() -> None:
    specs = [_spec("a", _absent())]
    mgr = DependencyManager(specs=specs)

    report = mgr.check_all()

    assert report.all_resolved is False


# --- Manager constructs cleanly with no args (production path) ------------


def test_manager_constructs_with_default_registry() -> None:
    """The no-args constructor must work — it's what app.py uses."""
    mgr = DependencyManager()
    # Real probes shell out and may take a moment, but they shouldn't
    # crash. We don't assert on the result; we just confirm the call
    # path doesn't blow up.
    report = mgr.check_all()
    assert isinstance(report, DependencyReport)
