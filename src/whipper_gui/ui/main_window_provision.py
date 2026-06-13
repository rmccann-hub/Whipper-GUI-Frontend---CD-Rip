"""Host provisioning, AppImage integration, and uninstall for the main window.

Extracted from ``main_window`` (2026-06-13 modularization, KDD-19) as a
mixin so the "get the app and its ripping stack installed / updated /
removed" concern lives in one focused file while its methods stay reachable
as ``window._x`` (tests + Qt signal wiring rely on that). ``MainWindow``
inherits this; methods run with ``self`` being the window.

This is the GUI-facing complement to the dependency subsystem's two arms:
``deps/host_setup.py`` (bootstrap) and ``deps/host_teardown.py`` (uninstall),
plus ``appimage_integration.py`` (menu/desktop self-integration). The heavy
imports are loaded lazily inside the methods, so this module stays light and
import-cheap.

Contract this mixin expects from the host window (set in
``MainWindow.__init__``): ``self._config``, ``self._save_config``,
``self._backend``; ``self`` is a ``QWidget`` (dialog parent); and the
cross-mixin methods ``self._maybe_offer_drive_setup`` (DriveMixin),
``self.refresh_drives`` / ``self.run_dependency_check`` (assembler /
DependencyMixin) — all resolved via inheritance at call time.

Future contributors: a new install channel (e.g. a different packaging
format) plugs in at ``_maybe_offer_appimage_integration`` /
``open_host_setup_dialog``; the actual idempotent step engines live in
``deps/`` behind an injectable ``CommandRunner`` (see ``docs/architecture.md``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:  # import only for type hints — runtime import stays lazy
    from whipper_gui.deps.host_setup import HostSetup

log = logging.getLogger(__name__)


class ProvisioningMixin:
    """First-run offers, AppImage menu integration, host-setup, and uninstall."""

    def _maybe_offer_first_run_setup(self) -> None:
        """First-run offers, in dependency order.

        The host stack (whipper in its container) must exist before anything
        else works, so offer that first; only once whipper is present does the
        drive-calibration offer make sense. Deferred to the event loop, so in
        tests (no exec loop) neither fires — both are unit-tested directly.
        """
        # AppImage menu integration is independent of the host/drive state —
        # offer it first (it's a no-op on source/pipx installs and when already
        # integrated), so a double-clicked AppImage becomes a real menu app.
        self._maybe_offer_appimage_integration()
        if not self._host_stack_ready():
            self._maybe_offer_host_setup()
            return
        self._maybe_offer_drive_setup()

    def _on_add_app_shortcut(self) -> None:
        """Tools → Add app shortcut: (re)create the menu entry + desktop icon.

        Always available, so a user who dismissed the first-run offer (or whose
        menu cache went stale) can redo it. Only meaningful for the AppImage —
        source/pipx installs get their launcher from dev-setup.sh.
        """
        from whipper_gui import appimage_integration as ai

        appimage = ai.appimage_path()
        if appimage is None:
            QMessageBox.information(
                self,
                "Add app shortcut",
                "This adds a menu/desktop shortcut for the AppImage. You're not "
                "running the AppImage build, so there's nothing to add — a source "
                "or pipx install already provides a launcher.",
            )
            return
        try:
            # Same flow as the first-run offer: settle the file into
            # ~/Applications first so the shortcuts never point into
            # Downloads, then integrate from there.
            new_path = ai.relocate_to_applications(appimage)
            ai.integrate(new_path)
            self._config.appimage_integration_prompted = True
            self._save_config(self._config)
            moved = (
                f"The app file was moved to {new_path}. "
                if new_path != appimage
                else ""
            )
            QMessageBox.information(
                self,
                "Shortcut added",
                f"Added Whipper GUI to your applications menu and your Desktop. "
                f"{moved}"
                "If the Desktop icon shows as untrusted, right-click it and "
                "choose “Allow Launching” (GNOME).",
            )
        except Exception:  # noqa: BLE001 — convenience action
            log.exception("manual AppImage integration failed")
            QMessageBox.warning(
                self,
                "Couldn't add shortcut",
                "Adding the shortcut didn't work, but the app still runs from "
                "the AppImage file.",
            )

    def _maybe_offer_appimage_integration(self) -> None:
        """Offer to add a menu entry + move the file to ~/Applications.

        Re-offers for any AppImage that isn't integrated yet — so a freshly
        downloaded UPDATE (a new file, or shortcuts the user deleted) gets
        the offer again (real-user report, 2026-06-10). Declining is
        remembered per-file, so saying No silences the nag for this file
        only, not for every future version.
        """
        from whipper_gui import appimage_integration as ai

        appimage = ai.appimage_path()
        if appimage is None:  # not running from an AppImage — nothing to do
            return
        # "Integrated" alone isn't enough: an update saved over the path an
        # old menu entry pointed at matches the entry but still lives in
        # Downloads — offer anyway so it gets settled into ~/Applications
        # (real-user report, 2026-06-10).
        if ai.is_integrated(appimage) and ai.is_settled(appimage):
            return
        if self._config.integration_declined_path == str(appimage):
            return  # the user said No to this very file — don't nag
        choice = QMessageBox.question(
            self,
            "Add to your applications menu?",
            "Add Whipper GUI to your applications menu, and move this file "
            "to ~/Applications so it lives with your other apps?\n\n"
            "(Leaving it in Downloads is fragile — clearing that folder "
            "would remove the app.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            self._config.integration_declined_path = str(appimage)
            self._config.appimage_integration_prompted = True  # legacy flag
            self._save_config(self._config)
            return
        try:
            # Give the file a proper home FIRST, then point the menu entry at
            # it. The running session keeps working from the old mount; only
            # future launches (the menu entry) use the new location.
            new_path = ai.relocate_to_applications(appimage)
            ai.integrate(new_path)
            self._config.integration_declined_path = ""
            self._config.appimage_integration_prompted = True  # legacy flag
            self._save_config(self._config)
            if new_path != appimage:
                detail = (
                    f"Whipper GUI now lives at {new_path} and is in your "
                    "applications menu. Launch it from the menu from now on."
                )
            else:
                detail = "Whipper GUI is now in your applications menu."
            QMessageBox.information(self, "Added to menu", detail)
        except Exception:  # noqa: BLE001 — integration is a convenience
            log.exception("AppImage integration failed")
            QMessageBox.warning(
                self,
                "Couldn't add to menu",
                "Adding the menu entry didn't work, but the app still runs "
                "normally from this file.",
            )

    def _host_stack_ready(self) -> bool:
        """True if the whipper binary is present (the container stack is set up)."""
        return Path(self._config.whipper_path).exists()

    def _maybe_offer_host_setup(self) -> None:
        """One-time, dismissible offer to run the host-setup wizard."""
        if self._config.host_setup_prompted:
            return
        self._config.host_setup_prompted = True
        self._save_config(self._config)
        choice = QMessageBox.question(
            self,
            "Set up Whipper GUI",
            "Whipper GUI needs a one-time setup to install its ripping tool "
            "(whipper) in a small container — no terminal required. Set it up "
            "now?\n\nYou can also do this later from Tools → Set up Whipper GUI….",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.open_host_setup_dialog()

    def _build_host_setup(self) -> HostSetup:
        """The HostSetup the wizard runs, configured from the current config.

        When the cyanrip backend is selected (KDD-18), the wizard also
        installs cyanrip into the container (from its COPR — Fedora doesn't
        package it) and exports it, so switching backends never needs a
        terminal.
        """
        from whipper_gui.deps.host_setup import HostSetup, SubprocessRunner

        return HostSetup(
            runner=SubprocessRunner(),
            include_cyanrip=self._config.ripper_backend == "cyanrip",
        )

    def open_host_setup_dialog(self) -> None:
        """Open the host-setup wizard (Tools → Set up Whipper GUI…)."""
        from whipper_gui.ui.host_setup_dialog import HostSetupDialog

        dialog = HostSetupDialog(self, host_setup=self._build_host_setup())
        dialog.setup_finished.connect(self._on_host_setup_finished)
        dialog.exec()

    def open_uninstall_dialog(self) -> None:
        """Open the in-app Uninstaller (Tools → Uninstall Whipper GUI…)."""
        from whipper_gui.ui.uninstall_dialog import UninstallDialog

        dialog = UninstallDialog(self)
        dialog.uninstall_finished.connect(self._on_uninstall_finished)
        dialog.exec()

    def _on_uninstall_finished(self, complete: bool) -> None:
        """After a successful uninstall, offer to close the app right away.

        The config/log dirs are gone; anything that saves config from here
        on would recreate them, so quitting immediately is the clean path.
        """
        if not complete:
            return
        choice = QMessageBox.question(
            self,
            "Uninstall complete",
            "Whipper GUI has been removed from this computer.\n\n"
            "Close the app now? (Recommended — staying open could "
            "recreate settings files.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.close()

    def _on_host_setup_finished(self, ready: bool) -> None:
        """After the wizard runs, re-probe the world if whipper now exists."""
        if ready:
            log.info("host setup reported ready — refreshing drives + deps")
            try:
                self.refresh_drives()
                self.run_dependency_check(show_summary=False)
            except Exception:  # noqa: BLE001 — best-effort refresh
                log.exception("post-host-setup refresh failed")
