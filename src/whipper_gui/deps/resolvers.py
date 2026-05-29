"""Resolver classes for the three tiers in brief P0 #11.

Each resolver has the same `resolve(items)` shape so the manager can
dispatch uniformly:

- `AutoInstaller` runs the install commands itself (after one consent
  callback) — tier (a).
- `QueuedInstaller` defers to a UI dialog the user drives one click
  at a time — tier (b).
- `ManualPrompt` shows a copyable search string and gives up on
  installing — tier (c).

The UI dialogs (T18, T19) don't exist yet, so QueuedInstaller and
ManualPrompt accept callbacks. The default callbacks log only — they
do nothing visible. When the dialog tasks land, the callers wire real
QDialog show functions in their place.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Callable

from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.registry import DependencySpec

log = logging.getLogger(__name__)

# Generous timeout for install commands. `flatpak install` for Picard
# typically completes in seconds; the 300s cap is just so a stalled
# install doesn't wedge the GUI forever.
_INSTALL_TIMEOUT_S: float = 300.0


@dataclass(frozen=True)
class MissingItem:
    """A spec the probe says we don't have at a usable version."""

    spec: DependencySpec
    probe: ProbeResult


@dataclass(frozen=True)
class InstallResult:
    """Outcome of trying to resolve a single MissingItem."""

    spec: DependencySpec
    success: bool
    message: str  # short, human-readable
    user_declined: bool = False  # True if user said no to the consent dialog


# Type aliases for the callbacks. Defining them here keeps the resolver
# signatures readable; T18/T19 implement the Qt versions.

# Consent callback for AutoInstaller — given the list of items about to
# be installed, return True to proceed.
ConsentCallback = Callable[[list[MissingItem]], bool]

# Dialog callback for QueuedInstaller. Receives the items and is
# expected to interact with the user, then return a list of items the
# user actually approved to install (subset of input).
QueuedDialogCallback = Callable[[list[MissingItem]], list[MissingItem]]

# Dialog callback for ManualPrompt. Returns nothing — it's purely
# informational from the resolver's perspective.
ManualDialogCallback = Callable[[MissingItem], None]


def _default_consent(items: list[MissingItem]) -> bool:
    """No-GUI default: refuse. Real GUI passes a QMessageBox callback."""
    log.info(
        "auto-install consent requested for %d item(s), no callback wired "
        "— treating as decline",
        len(items),
    )
    return False


def _default_queued_dialog(items: list[MissingItem]) -> list[MissingItem]:
    """No-GUI default: empty selection."""
    log.info(
        "queued-install dialog requested for %d item(s), no callback wired",
        len(items),
    )
    return []


def _default_manual_dialog(item: MissingItem) -> None:
    """No-GUI default: log the search string."""
    log.info(
        "manual install needed: %s (need >= %s) — search: %s",
        item.spec.display_name,
        item.spec.min_version,
        item.spec.search_string,
    )


class AutoInstaller:
    """Tier (a): runs `install_command` for each item after one OK."""

    def __init__(self, consent: ConsentCallback = _default_consent) -> None:
        self._consent = consent

    def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
        # Filter to items that actually have an install_command — a
        # tier-(a) spec without one is a programming error.
        actionable: list[MissingItem] = [
            item for item in items if item.spec.install_command is not None
        ]
        if not actionable:
            return []

        if not self._consent(actionable):
            return [
                InstallResult(
                    spec=item.spec,
                    success=False,
                    message="user declined auto-install",
                    user_declined=True,
                )
                for item in actionable
            ]

        return [self._install_one(item) for item in actionable]

    def _install_one(self, item: MissingItem) -> InstallResult:
        """Run a single install command via subprocess."""
        assert item.spec.install_command is not None
        command: list[str] = item.spec.install_command
        log.info("auto-installing %s via %r", item.spec.dep_id, command)
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_INSTALL_TIMEOUT_S,
            )
        except FileNotFoundError as exc:
            msg = f"install tool not found: {exc.filename}"
            log.warning("auto-install %s failed: %s", item.spec.dep_id, msg)
            return InstallResult(
                spec=item.spec,
                success=False,
                message=msg,
            )
        except subprocess.TimeoutExpired:
            msg = f"install timed out after {_INSTALL_TIMEOUT_S:.0f}s"
            log.warning("auto-install %s failed: %s", item.spec.dep_id, msg)
            return InstallResult(
                spec=item.spec,
                success=False,
                message=msg,
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            last_line = tail[-1] if tail else f"rc={proc.returncode}"
            full_output = (
                (proc.stdout or "").strip() + "\n" +
                (proc.stderr or "").strip()
            ).strip()
            log.warning(
                "auto-install %s failed (rc=%d): %s\nFull output:\n%s",
                item.spec.dep_id, proc.returncode, last_line, full_output,
            )
            return InstallResult(
                spec=item.spec,
                success=False,
                message=f"install failed: {last_line}",
            )

        log.info("auto-install %s succeeded", item.spec.dep_id)
        return InstallResult(
            spec=item.spec, success=True, message="installed"
        )


class QueuedInstaller:
    """Tier (b): defers item-by-item to a dialog the user drives.

    The dialog callback returns the subset of items the user clicked
    "Install" on. We run those through the AutoInstaller's machinery
    for the actual subprocess work — same install command, same error
    handling, no per-resolver duplication.
    """

    def __init__(
        self,
        dialog_callback: QueuedDialogCallback = _default_queued_dialog,
        auto_installer: AutoInstaller | None = None,
    ) -> None:
        self._dialog = dialog_callback
        # Reuse AutoInstaller's _install_one for consistency. We pass a
        # consent that always-approves because the user already approved
        # per-item in the dialog.
        self._installer = auto_installer or AutoInstaller(
            consent=lambda _: True
        )

    def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
        approved = self._dialog(items)
        if not approved:
            return [
                InstallResult(
                    spec=item.spec,
                    success=False,
                    message="not selected for install",
                    user_declined=True,
                )
                for item in items
            ]
        return self._installer.resolve(approved)


class ManualPrompt:
    """Tier (c): no install at all — just show a copyable search string.

    Every item returns `success=False` because nothing was installed.
    The user is expected to follow the search string to resolve manually
    and re-run the dependency check.
    """

    def __init__(
        self, dialog_callback: ManualDialogCallback = _default_manual_dialog
    ) -> None:
        self._dialog = dialog_callback

    def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
        results: list[InstallResult] = []
        for item in items:
            self._dialog(item)
            results.append(
                InstallResult(
                    spec=item.spec,
                    success=False,
                    message=(
                        f"manual install required — search: "
                        f"{item.spec.search_string}"
                    ),
                )
            )
        return results
