#!/usr/bin/env bash
# AppRun-style entrypoint executed when the user launches the AppImage.
#
# The AppImage runtime sets $APPDIR to the mounted root of the bundled
# filesystem. python-appimage installs CPython under $APPDIR/opt/python*/
# and our console-script `whipper-gui` ends up on the bundled bin/ PATH.

set -e

# Locate the bundled Python install (manylinux base is python3.11 today;
# fall back to whatever version python-appimage embedded if that changes).
APPDIR="${APPDIR:-$(dirname "$0")}"
PYTHON_BIN="$(ls "$APPDIR"/opt/python*/bin/python* 2>/dev/null | head -1)"

if [ -z "$PYTHON_BIN" ]; then
    echo "whipper-gui: could not find bundled Python interpreter" >&2
    exit 1
fi

# Run the package as a module so we get a stable entry point regardless
# of whether the console script was installed under bin/.
exec "$PYTHON_BIN" -m whipper_gui "$@"
