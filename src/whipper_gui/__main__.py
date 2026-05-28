"""Entry point for `python -m whipper_gui` and the `whipper-gui` console script.

Kept deliberately tiny so packaging tools (pipx, python-appimage) and the
AppImage's AppRun script have a single stable target to invoke. All real
startup logic lives in `whipper_gui.app.main`.
"""

from whipper_gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
