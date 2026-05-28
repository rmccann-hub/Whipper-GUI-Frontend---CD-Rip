"""Application entry point. Eventually builds the QApplication, runs the
dependency manager, and shows the MainWindow.

This is the T01 scaffolding placeholder. Subsequent tasks fill in:
  - T02: logging configuration (configure_logging() called first)
  - T09: DependencyManager.check_all() before window construction
  - T28/T29: MainWindow construction and event loop

Right now `main()` just prints a status message and exits cleanly so
`python -m whipper_gui` succeeds and T01's acceptance check passes.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Process entry point. Returns the exit code.

    `argv` defaults to `sys.argv[1:]` when invoked normally; callers in
    tests can pass an explicit list.
    """
    # argv is unused at T01 but parsed here to lock in the signature
    # that later tasks will populate (e.g., `--version`, `--check-deps`).
    _ = argv if argv is not None else sys.argv[1:]

    print("whipper-gui: scaffolding placeholder (T01).")
    print("The GUI is not yet implemented — see TASKS.md for status.")
    return 0
