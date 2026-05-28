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
from pathlib import Path

from whipper_gui import __version__


log = logging.getLogger(__name__)


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

    # Adapter layer. Per CLAUDE.md Critical Rule #1, every external
    # tool is reached through an adapter constructed exactly once here.
    from whipper_gui.adapters.metaflac import MetaflacAdapter
    from whipper_gui.adapters.musicbrainz_client import MusicBrainzNgsImpl
    from whipper_gui.adapters.whipper_backend import WhipperHostExportedImpl

    backend = WhipperHostExportedImpl(
        binary_path=Path(cfg.whipper_path),
        working_dir=Path(cfg.working_dir) if cfg.working_dir else None,
    )
    mb_client = MusicBrainzNgsImpl(
        app="whipper-gui",
        version=__version__,
        contact=(
            "https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip"
        ),
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
    # subprocess takes a moment.
    window.refresh_drives()

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
