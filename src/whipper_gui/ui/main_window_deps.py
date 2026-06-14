"""Dependency-check UI for the main window.

Extracted from ``main_window`` (2026-06-13 modularization, KDD-19) as a
mixin so the GUI side of the dependency self-management subsystem lives in
one focused file while its methods stay reachable as ``window._x`` (tests +
Qt signal wiring rely on that). ``MainWindow`` inherits this; methods run
with ``self`` being the window.

This is *only* the GUI glue: it builds GUI-backed resolvers (consent dialog,
the queued-install dialog, the manual-search-string dialog) and runs the
injected ``DependencyManager``'s registry through them, then shows a summary.
All the actual "is it present / what version / how to install" logic lives in
``deps/`` (Critical Rule #6) — this file must never grow an ad-hoc
``shutil.which`` check.

``_DialogQueuedResolver`` lives here too (it's the tier-(b) resolver the dep
check uses); ``main_window`` re-exports it for the test-facing API.

Contract this mixin expects from the host window (set in
``MainWindow.__init__``): ``self._config``, ``self._dependency_manager``;
``self`` is a ``QWidget`` (dialog parent); and the cross-mixin method
``self.open_host_setup_dialog`` (ProvisioningMixin).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox, QWidget

from whipper_gui.deps.resolvers import (
    AutoInstaller,
    InstallResult,
    ManualPrompt,
    MissingItem,
)
from whipper_gui.deps.version import format_version
from whipper_gui.ui.dialogs.manual_install import ManualInstallDialog
from whipper_gui.ui.dialogs.pending_installs import PendingInstallsDialog


class _DialogQueuedResolver:
    """Tier-(b) resolver for the GUI: drives `PendingInstallsDialog` with live
    per-item progress, then returns the `InstallResult`s.

    Replaces `QueuedInstaller` in the GUI path. `QueuedInstaller` installs
    *after* its dialog callback returns — which closes the dialog — so it can't
    show per-item progress. Here the dialog stays open and installs inline,
    updating each row as it goes. Duck-typed to the resolver interface the
    `DependencyManager` dispatches to (`resolve(items) -> list[InstallResult]`).
    """

    def __init__(
        self,
        parent: QWidget | None,
        install_one: Callable[[MissingItem], InstallResult],
    ) -> None:
        self._parent = parent
        self._install_one = install_one

    def resolve(self, items: list[MissingItem]) -> list[InstallResult]:
        if not items:
            return []
        dialog = PendingInstallsDialog(
            items, install_one=self._install_one, parent=self._parent
        )
        # The dialog drives the install loop itself and populates results();
        # exec() blocks until the user closes it (Close after install, or
        # Cancel → all declined). results() always has one entry per item.
        dialog.exec()
        return dialog.results()


class DependencyMixin:
    """Run the dependency subsystem with GUI-backed resolvers + summary."""

    def _maybe_offer_cyanrip_install(self, old_backend: str) -> None:
        """Offer the setup wizard when the user just switched to cyanrip
        but cyanrip isn't installed yet — otherwise the new backend would
        silently fail on the next launch with 'binary not found'."""
        from whipper_gui.deps import host_setup

        if self._config.ripper_backend != "cyanrip" or old_backend == "cyanrip":
            return
        if host_setup.cyanrip_on_host():
            return
        choice = QMessageBox.question(
            self,
            "Install cyanrip?",
            "You selected the cyanrip backend, but cyanrip isn't installed "
            "yet.\n\nRun setup now to install it into the ripping container "
            "and make it available to this app? (Restart the app afterwards "
            "for the backend change to take effect.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.open_host_setup_dialog()

    def _on_check_dependencies(self) -> None:
        """Run the dependency subsystem with GUI-backed resolvers.

        Always shows the summary popup at the end. Use
        `run_dependency_check(show_summary=False)` to suppress the
        popup when nothing's missing — that's the launch-time path.
        """
        self.run_dependency_check(show_summary=True)

    def run_dependency_check(self, show_summary: bool = True) -> None:
        """Run check_all + resolve_missing with GUI-backed resolvers, **synchronously**.

        Used by the Tools → Check dependencies menu action (the user clicked,
        so a brief block while probing is acceptable) and by tests. The
        launch-time path uses `run_dependency_check_async` instead so a
        cold-container probe can't freeze the just-shown window.
        """
        gui_manager = self._build_gui_dependency_manager()
        self._apply_dependency_report(
            gui_manager, gui_manager.check_all(), show_summary=show_summary
        )

    def run_dependency_check_async(self) -> None:
        """Launch-time dependency check that probes **off the GUI thread**.

        `check_all()` shells out per dependency, and the whipper probe enters
        the Distrobox container — slow on a cold start. Running it on the GUI
        thread at launch froze the just-shown window; here the probing runs on
        a worker and only the *result* is applied on the GUI thread (where the
        resolver dialogs must live). One check at a time.
        """
        if self._dep_check_thread is not None:  # a check is already running
            return
        from whipper_gui.workers.dependency_worker import DependencyCheckWorker

        gui_manager = self._build_gui_dependency_manager()
        self._dep_check_worker = DependencyCheckWorker(gui_manager)
        self._dep_check_thread = QThread(self)
        self._dep_check_worker.moveToThread(self._dep_check_thread)
        self._dep_check_worker.finished.connect(
            lambda report: self._on_dependency_check_done(gui_manager, report)
        )
        self._dep_check_worker.finished.connect(self._dep_check_thread.quit)
        self._dep_check_thread.finished.connect(self._dep_check_thread.deleteLater)
        self._dep_check_thread.started.connect(self._dep_check_worker.run)
        self._dep_check_thread.start()

    def _on_dependency_check_done(self, gui_manager: object, report: object) -> None:
        """Worker finished probing — apply the report on the GUI thread."""
        self._dep_check_worker = None
        self._dep_check_thread = None
        # Launch path never forces the "all good" popup (silent unless action
        # is needed); resolver dialogs still surface for genuinely-missing deps.
        self._apply_dependency_report(gui_manager, report, show_summary=False)

    def _build_gui_dependency_manager(self) -> object:
        """A DependencyManager wired with GUI-backed resolvers (consent dialog,
        queued-install dialog, manual-search dialog), reusing the injected
        manager's registry so it sees exactly the deps the app cares about."""
        from whipper_gui.deps.manager import DependencyManager

        return DependencyManager(
            auto=AutoInstaller(consent=self._gui_auto_consent),
            queued=_DialogQueuedResolver(self, self._make_install_one()),
            manual=ManualPrompt(dialog_callback=self._gui_manual_dialog),
            specs=self._dependency_manager._specs,  # type: ignore[attr-defined]
        )

    def _apply_dependency_report(
        self, gui_manager: object, report: object, show_summary: bool
    ) -> None:
        """GUI-thread half: set optional deps aside, resolve the required
        missing ones (dialogs), then show the summary. `report` is None only
        if the off-thread probe crashed — then this is a no-op (already logged)."""
        if report is None:
            return
        # Optional deps (e.g. Picard) shouldn't nag at launch or count as a
        # problem — set them aside so only required deps drive resolution.
        optional_missing = [
            item for item in report.missing if getattr(item.spec, "optional", False)
        ]
        report.missing = [
            item for item in report.missing if not getattr(item.spec, "optional", False)
        ]
        if report.missing:
            gui_manager.resolve_missing(report)

        if show_summary or report.missing:
            self._show_dep_summary(report, optional_missing=optional_missing)

    def _gui_auto_consent(self, items: list[MissingItem]) -> bool:
        if not items:
            return True
        names = ", ".join(item.spec.display_name for item in items)
        choice = QMessageBox.question(
            self,
            "Install dependencies",
            f"Install the following automatically?\n\n{names}",
        )
        return choice == QMessageBox.StandardButton.Yes

    def _make_install_one(self) -> Callable[[MissingItem], InstallResult]:
        """Build the per-item installer the PendingInstallsDialog drives.

        Reuses AutoInstaller's install machinery (subprocess run + error
        handling) with an always-yes consent — the user already consented
        per-item via the dialog's checkboxes.
        """
        installer = AutoInstaller(consent=lambda _: True)

        def install_one(item: MissingItem) -> InstallResult:
            results = installer.resolve([item])
            if results:
                return results[0]
            # AutoInstaller skips items with no install_command; a queued-tier
            # item should always have one, but never return an empty list.
            return InstallResult(
                spec=item.spec,
                success=False,
                message="no install command available",
            )

        return install_one

    def _gui_manual_dialog(self, item: MissingItem) -> None:
        dialog = ManualInstallDialog(item.spec, item.probe, self)
        dialog.exec()

    def _show_dep_summary(
        self, report: object, optional_missing: list[MissingItem] | None = None
    ) -> None:
        """Post-check summary popup with install-failure detail when present.

        The popup format:
            "<ok_count> ok, <missing_count> missing/needs-attention."
            "Installed: <name> <version>, …"      ← when any deps are OK
            "Optional (not installed): <names>"   ← only when present
            (blank line)
            "Install failures:"           ← only when failures exist
            "  - <dep>: <error message>"  ← one per failure
        """
        ok_specs = getattr(report, "ok", [])
        ok_count = len(ok_specs)
        missing_count = len(getattr(report, "missing", []))
        ok_versions = getattr(report, "ok_versions", {}) or {}
        # Collect real install failures (not user declines — those are
        # surfaced via the dialog the user already saw).
        install_results = getattr(report, "install_results", [])
        failures = [
            r
            for r in install_results
            if not r.success and not getattr(r, "user_declined", False)
        ]

        message = f"{ok_count} ok, {missing_count} missing/needs-attention."
        # Stamp the detected version next to each OK dep so the user knows
        # exactly what's installed (reproducibility), not just that it's there.
        if ok_specs:
            installed = ", ".join(
                f"{spec.display_name} {format_version(ok_versions.get(spec.dep_id))}"
                for spec in ok_specs
            )
            message += f"\nInstalled: {installed}."
        if optional_missing:
            names = ", ".join(item.spec.display_name for item in optional_missing)
            message += f"\nOptional (not installed): {names}."
        if failures:
            failure_lines = "\n".join(
                f"  • {r.spec.display_name}: {r.message}" for r in failures
            )
            message = (
                f"{message}\n\nInstall failures:\n{failure_lines}\n\n"
                f"Full output is in ~/.local/share/whipper-gui/log.txt."
            )

        QMessageBox.information(self, "Dependency check complete", message)
