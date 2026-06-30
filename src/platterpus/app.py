"""Application entry point.

Wires the persistent-state layers (config, logging) and the running-app
layers (QApplication, adapters, workers, MainWindow) into the correct
startup order.

Order:
  1. configure_logging() — captures any startup failure
  2. config.load()       — falls back to defaults on first run
  3. QApplication        — required before any QWidget
  4. construct adapters  — WhipperHostExportedImpl, MusicBrainzNgsImpl,
                           MetaflacAdapter, DependencyManager
  5. construct MainWindow
  6. run_dependency_check(show_summary=False) — silent unless missing
  7. window.show() and refresh_drives()
  8. app.exec()
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback

from platterpus import __version__

log = logging.getLogger(__name__)


def _prefer_xwayland_on_wayland() -> None:
    """On a Wayland session, ask Qt to run via XWayland (the ``xcb`` platform)
    unless the user already chose a platform.

    Why: on KDE Plasma 6 Wayland, this app's Qt build doesn't repaint a window
    region that was covered and then re-exposed while a rip is running — the
    window goes black until you interact with it (real-user report, 2026-06-27).
    Running through XWayland fixes it (X11's expose/repaint works correctly).

    The value is a FALLBACK LIST — ``xcb;wayland`` — so if the xcb plugin can't
    load (e.g. missing libs) Qt falls straight back to native Wayland. That means
    this can never stop the app from starting; the worst case is the previous
    behaviour. Set ``QT_QPA_PLATFORM`` yourself (e.g. ``wayland``) to override and
    keep native Wayland. Must run BEFORE QApplication is constructed — Qt reads
    the variable then.
    """
    import os

    if os.environ.get("QT_QPA_PLATFORM"):
        return  # respect an explicit user choice
    on_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )
    if on_wayland:
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"
        log.info(
            "Wayland session detected — preferring XWayland "
            "(QT_QPA_PLATFORM=xcb;wayland) to avoid the Plasma 6 black-window "
            "repaint bug; set QT_QPA_PLATFORM=wayland to force native Wayland."
        )


def _show_fatal_dialog(title: str, exc: BaseException) -> None:
    """Show a last-resort error dialog so a crash is never silent.

    The window otherwise just disappears, leaving the user with nothing
    to report. We surface the exception text plus the log-file path (the
    full traceback is already in the log) so a screenshot is actionable.
    A QApplication must already exist; if the GUI itself is what failed
    to come up, this is best-effort and may no-op.
    """
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        from platterpus.paths import LOG_PATH

        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(
            f"Platterpus hit an unexpected error.\n\n{type(exc).__name__}: {exc}"
        )
        box.setDetailedText(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
        box.setInformativeText(f"Details were written to:\n{LOG_PATH}")
        box.exec()
    except Exception:  # noqa: BLE001 — the crash handler must never crash
        log.exception("failed to show the fatal-error dialog")


def _install_excepthook() -> None:
    """Route otherwise-uncaught exceptions (e.g. raised inside a Qt slot
    during the event loop) to the log file and an on-screen dialog,
    instead of letting them print to a stderr the user never sees."""

    def hook(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.error("uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        _show_fatal_dialog("Platterpus — error", exc_value)

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    """Process entry point.

    `argv` defaults to `sys.argv[1:]` for normal invocation. Tests pass
    an explicit list (typically `["--version"]` to exercise the parser
    without spinning up the full GUI).
    """
    parser = argparse.ArgumentParser(
        prog="platterpus",
        description="A secure, EAC-style CD ripper for Linux (FLAC, WAV, WavPack, MP3)",
    )
    parser.add_argument(
        "--version", action="version", version=f"platterpus {__version__}"
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="open only the uninstaller (used by the Uninstall menu entry)",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="run a first-pass check of the rip environment (no CD needed) "
        "and exit; prints a pass/fail report",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    # Logging is the first thing — any failure below this line shows up
    # in ~/.local/share/platterpus/log.txt.
    from platterpus.logging_setup import configure_logging, set_debug_logging

    configure_logging()
    log.info("platterpus %s starting", __version__)

    # Config first; both the logging path and the adapter constructors
    # depend on what the user has configured.
    from platterpus import config as config_module

    cfg = config_module.load()
    # Apply the user's debug-logging preference now that config is loaded
    # (configure_logging ran first, before config, to catch startup failures).
    set_debug_logging(cfg.debug_logging)

    # Doctor mode: a no-GUI, no-disc first-pass test of the rip environment.
    # Runs before QApplication — it's a terminal diagnostic, not a window.
    if args.doctor:
        from platterpus import preflight

        ctx = preflight.default_context(cfg)
        color = sys.stdout.isatty()
        print(f"Platterpus preflight — backend: {ctx.backend_name}\n")
        results = preflight.run_preflight(
            ctx, on_result=lambda r: print(preflight.format_line(r, color=color))
        )
        details = preflight.format_details(results)
        if details:
            print("\n" + details)
        print("\n" + preflight.format_summary(results, color=color))
        return preflight.exit_code(results)

    # QApplication MUST exist before any QWidget. Build it as early as
    # possible so the dep-check dialogs can run.
    from PySide6.QtWidgets import QApplication

    # Prefer XWayland on Wayland (fixes the Plasma 6 black-window repaint bug).
    # Must happen before QApplication reads the platform.
    _prefer_xwayland_on_wayland()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("platterpus")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("platterpus")  # affects QSettings paths
    # The app/window icon (the Platterpus logo). Best-effort: app_icon()
    # returns None if the bundled SVG or the Qt SVG plugin is unavailable, in
    # which case we simply leave the default icon rather than fail startup.
    from platterpus.app_icon import app_icon

    _icon = app_icon()
    if _icon is not None:
        app.setWindowIcon(_icon)

    # Centre every dialog (incl. QMessageBox / QFileDialog) over the window the
    # user is looking at, so a prompt never opens on a different monitor and
    # looks frozen. Parented to `app` so it lives for the whole session. No-op
    # under native Wayland (clients can't self-position). See auto_center.
    from platterpus.ui.dialogs.auto_center import DialogCenterFilter

    _dialog_center_filter = DialogCenterFilter(app)
    app.installEventFilter(_dialog_center_filter)

    # From here on, any uncaught exception (including ones raised inside a
    # Qt slot during the event loop) goes to the log + an on-screen dialog
    # rather than silently aborting the process.
    _install_excepthook()

    # Uninstaller-only mode: the "Uninstall Platterpus" menu entry launches
    # `<app> --uninstall`, so removal works without opening (or needing) the
    # main window — none of the adapters below are required for it.
    if args.uninstall:
        from platterpus.ui.uninstall_dialog import UninstallDialog

        log.info("uninstall mode requested")
        dialog = UninstallDialog()
        dialog.exec()
        return 0

    # Bringing up the adapters + window can fail (bad config path, an
    # unexpected ripper output that trips a parser, a Qt error). Guard the
    # whole bring-up so the user gets a dialog they can screenshot instead
    # of a window that flashes and disappears with nothing to report.
    try:
        # Adapter layer. Per CLAUDE.md Critical Rule #1, every external tool is
        # reached through an adapter constructed exactly once here. The cyanrip
        # backend (the sole engine since the whipper removal, KDD-18) and the
        # MusicBrainz client are built via the shared composition root so the
        # GUI and `--doctor` can never wire the adapters differently.
        from platterpus import composition
        from platterpus.adapters.ctdb_client import CtdbHttpImpl
        from platterpus.adapters.metaflac import MetaflacAdapter
        from platterpus.deps.manager import DependencyManager
        from platterpus.ui.main_window import MainWindow

        backend, _backend_name = composition.build_backend(cfg)
        mb_client = composition.build_musicbrainz_client()
        metaflac = MetaflacAdapter(binary_name=cfg.metaflac_path)

        # CTDB lookup transport (KDD-14 Phase 1) — only used when the user
        # enables "Verify with CTDB after a rip".
        ctdb_client = CtdbHttpImpl()

        dependency_manager = DependencyManager()

        window = MainWindow(
            config=cfg,
            backend=backend,
            mb_client=mb_client,
            metaflac=metaflac,
            dependency_manager=dependency_manager,
            ctdb_client=ctdb_client,
        )

        window.show()
        # The launch dependency check shells out to whipper (which enters the
        # Distrobox container — slow on a cold start), so run it OFF the GUI
        # thread: the window is responsive immediately and the probe can't
        # freeze it. Resolver dialogs for anything missing surface on the GUI
        # thread when the probe finishes. Guarded so a failure still leaves a
        # usable window.
        try:
            window.run_dependency_check_async()
        except Exception:  # noqa: BLE001 — last-resort guard
            log.exception("initial dependency check failed; continuing anyway")
        # Drive listing also shells to whipper; kept after show() so the window
        # appears immediately. (Off-threading this probe too is tracked in TASKS.)
        try:
            window.refresh_drives()
        except Exception:  # noqa: BLE001 — last-resort guard
            log.exception("initial drive refresh failed; continuing anyway")
    except Exception as exc:  # noqa: BLE001 — fatal-startup guard
        log.exception("fatal error during startup")
        _show_fatal_dialog("Platterpus — startup failed", exc)
        return 1

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
