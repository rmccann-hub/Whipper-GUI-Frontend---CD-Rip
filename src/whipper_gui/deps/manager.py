"""The DependencyManager — single orchestrator for brief P0 #11.

Walks the registry, runs each spec's probe, classifies missing items
into tiers, and dispatches to the appropriate resolver. Returns a
`DependencyReport` for UI display.

The manager itself is GUI-unaware: every callback that needs the GUI
(consent dialogs, install dialogs, manual prompts) is injected via the
three resolver instances passed to `__init__`. That keeps the
subsystem unit-testable without Qt and lets the app.py wiring be the
only place that knows about both halves.

`check_all()` is idempotent: calling it twice with no system changes
produces an identical report. Calling it after a successful resolution
reflects the new state of the world immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from whipper_gui.deps.registry import SPECS, DependencySpec, Tier
from whipper_gui.deps.resolvers import (
    AutoInstaller,
    InstallResult,
    ManualPrompt,
    MissingItem,
    QueuedInstaller,
)
from whipper_gui.deps.version import meets_minimum

log = logging.getLogger(__name__)


@dataclass
class DependencyReport:
    """Result of a check_all() pass.

    - `ok`: specs that probed present and met the minimum version.
    - `missing`: items that didn't, with the probe attached.
    - `ok_versions`: dep_id → detected version (or None) for the `ok`
      specs, so the report can tell the user *which* version they have,
      not just that the dep is present.
    - `install_results`: outcomes from any resolution attempts during
      this run (empty after a pure check that didn't try to resolve).
    """

    ok: list[DependencySpec] = field(default_factory=list)
    missing: list[MissingItem] = field(default_factory=list)
    ok_versions: dict[str, tuple[int, ...] | None] = field(default_factory=dict)
    install_results: list[InstallResult] = field(default_factory=list)

    @property
    def all_resolved(self) -> bool:
        """True if everything probed OK or was successfully installed."""
        if self.missing == [] and self.install_results == []:
            return True
        # When resolution happened, success requires every previously-
        # missing item to have a matching success in install_results.
        installed_ok = {
            r.spec.dep_id for r in self.install_results if r.success
        }
        return all(item.spec.dep_id in installed_ok for item in self.missing)


class DependencyManager:
    """Single entry point for "are all my dependencies good?"."""

    def __init__(
        self,
        auto: AutoInstaller | None = None,
        queued: QueuedInstaller | None = None,
        manual: ManualPrompt | None = None,
        specs: list[DependencySpec] | None = None,
    ) -> None:
        """Construct with optional injected resolvers and a custom spec list.

        Tests pass their own resolvers (with fake callbacks) and their
        own spec list (so they don't depend on the real registry). In
        production, `app.py` constructs the manager with the real
        resolver instances; `specs=None` then picks up `registry.SPECS`.
        """
        self._auto = auto or AutoInstaller()
        self._queued = queued or QueuedInstaller()
        self._manual = manual or ManualPrompt()
        self._specs = specs if specs is not None else SPECS

    def check_all(self) -> DependencyReport:
        """Probe every registered dependency. Pure check — no installs."""
        report = DependencyReport()
        for spec in self._specs:
            probe = spec.probe()
            log.debug(
                "probe %s: present=%s version=%s",
                spec.dep_id, probe.present, probe.version,
            )
            if probe.present and meets_minimum(probe.version, spec.min_version):
                report.ok.append(spec)
                report.ok_versions[spec.dep_id] = probe.version
            else:
                report.missing.append(MissingItem(spec=spec, probe=probe))
        return report

    def resolve_missing(self, report: DependencyReport) -> DependencyReport:
        """Dispatch each missing item to the resolver for its preferred tier.

        Items whose primary tier resolver fails cascade through
        `spec.fallback_tiers` in order. Final outcomes — success or not
        — land in `report.install_results`.
        """
        # Group missing items by their CURRENT (first-attempt) tier.
        by_tier: dict[Tier, list[MissingItem]] = {t: [] for t in Tier}
        for item in report.missing:
            by_tier[item.spec.tier].append(item)

        # Run each tier's batch through its resolver. Failed items
        # cascade into the next fallback tier for their spec.
        cascade: list[MissingItem] = []

        for tier in (Tier.AUTO, Tier.QUEUED, Tier.MANUAL):
            batch = by_tier[tier] + [
                item for item in cascade if self._next_tier(item) == tier
            ]
            # Remove cascaded items we just queued.
            cascade = [
                item for item in cascade if self._next_tier(item) != tier
            ]
            if not batch:
                continue

            results = self._dispatch(tier, batch)
            report.install_results.extend(results)

            # Failures cascade to the next fallback tier (if any).
            # Declines do NOT cascade — when a user explicitly says No
            # at a given tier, surfacing the next-tier dialog for the
            # same dep would just be the same question with different
            # phrasing. Real install failures (network, permission,
            # etc.) DO cascade because the user hasn't said no to the
            # dep itself, just to the current install method.
            for item, result in zip(batch, results):
                if result.success:
                    continue
                if result.user_declined:
                    log.info(
                        "%s declined at tier %s — not cascading",
                        item.spec.dep_id, tier.value,
                    )
                    continue
                if not item.spec.fallback_tiers:
                    continue
                # Already-tried tiers are the ones at or above `tier` in
                # this loop's order. The next fallback is the first one
                # in spec.fallback_tiers we haven't visited yet.
                remaining = [
                    t for t in item.spec.fallback_tiers if t.value != tier.value
                ]
                if remaining:
                    # Re-attach with updated effective tier so cascade
                    # routing in subsequent loop iterations works.
                    cascade.append(
                        MissingItem(
                            spec=_clone_with_tier(item.spec, remaining[0]),
                            probe=item.probe,
                        )
                    )

        return report

    def _dispatch(
        self, tier: Tier, items: list[MissingItem]
    ) -> list[InstallResult]:
        if tier == Tier.AUTO:
            return self._auto.resolve(items)
        if tier == Tier.QUEUED:
            return self._queued.resolve(items)
        return self._manual.resolve(items)

    @staticmethod
    def _next_tier(item: MissingItem) -> Tier:
        """Effective current tier — the spec's `tier`, possibly cloned-
        over during cascade."""
        return item.spec.tier


def _clone_with_tier(spec: DependencySpec, tier: Tier) -> DependencySpec:
    """Return a copy of `spec` with `tier` overridden.

    DependencySpec is frozen, so we can't just assign. dataclasses
    provides `replace()` for exactly this. Kept private to the manager
    because cascade is an internal concern.
    """
    from dataclasses import replace
    return replace(spec, tier=tier)
