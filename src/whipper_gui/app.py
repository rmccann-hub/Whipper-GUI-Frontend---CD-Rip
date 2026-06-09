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
from pathlib import Path

from whipper_gui import __version__

log = logging.getLogger(__name__)


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

        from whipper_gui.paths import LOG_PATH

        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(
            f"Whipper GUI hit an unexpected error.\n\n{type(exc).__name__}: {exc}"
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
        _show_fatal_dialog("Whipper GUI — error", exc_value)

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    """Process entry point.

    `argv` defaults to `sys.argv[1:]` for normal invocation. Tests pass
    an explicit list (typically `["--version"]` to exercise the parser
    without spinning up the full GUI).
    """
    parser = argparse.ArgumentParser(
        prog="whipper-gui",
        description="GUI front-end for the whipper audio-CD ripping CLI",
    )
    parser.add_argument(
        "--version", action="version", version=f"whipper-gui {__version__}"
    )
    parser.parse_args(argv if argv is not None else sys.argv[1:])

    # Logging is the first thing — any failure below this line shows up
    # in ~/.local/share/whipper-gui/log.txt.
    from whipper_gui.logging_setup import configure_logging

    configure_logging()
    log.info("whipper-gui %s starting", __version__)

    # Config first; both the logging path and the adapter constructors
    # depend on what the user has configured.
    from whipper_gui import config as config_module

    cfg = config_module.load()

    # QApplication MUST exist before any QWidget. Build it as early as
    # possible so the dep-check dialogs can run.
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("whipper-gui")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("whipper-gui")  # affects QSettings paths

    # From here on, any uncaught exception (including ones raised inside a
    # Qt slot during the event loop) goes to the log + an on-screen dialog
    # rather than silently aborting the process.
    _install_excepthook()

    # Bringing up the adapters + window can fail (bad config path, an
    # unexpected whipper output that trips a parser, a Qt error). Guard the
    # whole bring-up so the user gets a dialog they can screenshot instead
    # of a window that flashes and disappears with nothing to report.
    try:
        # Adapter layer. Per CLAUDE.md Critical Rule #1, every external
        # tool is reached through an adapter constructed exactly once here.
        from whipper_gui.adapters.metaflac import MetaflacAdapter
        from whipper_gui.adapters.musicbrainz_client import MusicBrainzNgsImpl
        from whipper_gui.adapters.whipper_backend import (
            WhipperBackend,
            WhipperHostExportedImpl,
        )

        # Ripping backend is config-selectable (KDD-18): whipper (default) or
        # cyanrip. Both implement the same ABC, so the rest of the app is
        # backend-agnostic.
        backend: WhipperBackend
        if cfg.ripper_backend == "cyanrip":
            from whipper_gui.adapters.cyanrip_backend import CyanripImpl
            from whipper_gui.paths import CYANRIP_BINARY_DEFAULT

            # Prefer the host-exported absolute path: a desktop-launched GUI
            # has a minimal PATH that may not include ~/.local/bin (same
            # lesson as drive_control's absolute-path resolution). Fall back
            # to a PATH lookup for users with a native cyanrip install.
            cyanrip_binary: Path | str = (
                CYANRIP_BINARY_DEFAULT if CYANRIP_BINARY_DEFAULT.exists() else "cyanrip"
            )
            backend = CyanripImpl(
                binary_path=cyanrip_binary,
                working_dir=Path(cfg.working_dir) if cfg.working_dir else None,
            )
            log.info("using cyanrip backend (%s)", cyanrip_binary)
        else:
            backend = WhipperHostExportedImpl(
                binary_path=Path(cfg.whipper_path),
                working_dir=Path(cfg.working_dir) if cfg.working_dir else None,
            )
        mb_client = MusicBrainzNgsImpl(
            app="whipper-gui",
            version=__version__,
            contact=("https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip"),
        )
        metaflac = MetaflacAdapter(binary_name=cfg.metaflac_path)

        from whipper_gui.deps.manager import DependencyManager

        dependency_manager = DependencyManager()

        from whipper_gui.ui.main_window import MainWindow

        window = MainWindow(
            config=cfg,
            backend=backend,
            mb_client=mb_client,
            metaflac=metaflac,
            dependency_manager=dependency_manager,
        )

        # Launch-time dependency check. Silent unless something needs the
        # user's attention; the menu's "Check dependencies" action always
        # surfaces a summary.
        try:
            window.run_dependency_check(show_summary=False)
        except Exception:  # noqa: BLE001 — last-resort guard
            log.exception("initial dependency check failed; continuing anyway")

        window.show()
        # Populating the drive list shells out to whipper. Do it after
        # show() so the user sees the window immediately, even if the
        # subprocess takes a moment. Guarded separately so a drive-listing
        # problem leaves a usable window (the user can fix it in Settings)
        # rather than taking the whole app down.
        try:
            window.refresh_drives()
        except Exception:  # noqa: BLE001 — last-resort guard
            log.exception("initial drive refresh failed; continuing anyway")
    except Exception as exc:  # noqa: BLE001 — fatal-startup guard
        log.exception("fatal error during startup")
        _show_fatal_dialog("Whipper GUI — startup failed", exc)
        return 1

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
