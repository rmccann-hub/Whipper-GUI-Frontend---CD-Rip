#!/usr/bin/env bash
# Post-clone setup for Whipper GUI development.
#
# Run this once after cloning the repo. It creates a Python virtual
# environment in .venv/, upgrades pip, and installs the package in
# editable mode so changes to src/whipper_gui/ are picked up live.
#
# Usage:
#   bash dev-setup.sh             # set up venv + install runtime deps
#   bash dev-setup.sh --dev       # also install pytest (for running tests)
#
# Re-running is safe — uses an existing .venv if present.

set -euo pipefail

cd "$(dirname "$0")"

# --- Parse args ---
INSTALL_DEV=0
for arg in "$@"; do
    case "$arg" in
        --dev)  INSTALL_DEV=1 ;;
        -h|--help)
            sed -n 's/^# \?//p' "$0" | head -15
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Use --help for usage." >&2
            exit 1
            ;;
    esac
done

# --- Create venv if missing ---
if [ ! -d .venv ]; then
    echo "Creating virtual environment in .venv/..."
    python3 -m venv .venv
else
    echo "Reusing existing .venv/"
fi

# --- Source and upgrade pip ---
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Upgrading pip in the venv..."
pip install --upgrade pip --quiet

# --- Install the package ---
if [ "$INSTALL_DEV" -eq 1 ]; then
    echo "Installing whipper-gui in editable mode (with dev extras: pytest)..."
    pip install -e ".[dev]"
else
    echo "Installing whipper-gui in editable mode..."
    pip install -e .
fi

# --- Desktop entry ---
# Install a launcher into the user's app menu so the GUI is reachable
# without a terminal. Points Exec at the venv's whipper-gui (absolute
# path, so it works from the menu regardless of cwd). Uses the stock
# `media-optical` icon name — present in essentially every icon theme —
# so we don't need to ship a bitmap. uninstall.sh removes this file.
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/whipper-gui.desktop"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Whipper GUI
GenericName=CD Audio Ripper
Comment=Rip audio CDs to FLAC with whipper
Exec=$REPO_ROOT/.venv/bin/whipper-gui
Icon=media-optical
Terminal=false
Categories=AudioVideo;Audio;DiscBurning;
Keywords=cd;rip;flac;audio;whipper;musicbrainz;
DESKTOP
# Refresh the desktop caches so the entry shows up without a re-login.
# update-desktop-database handles the freedesktop MIME cache, but KDE
# Plasma's application launcher reads its own ksycoca cache — so on KDE
# (the project's primary target) we must also run kbuildsycoca, or the
# entry won't appear until the next login. All best-effort + quiet.
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
for _kbs in kbuildsycoca6 kbuildsycoca5; do
    if command -v "$_kbs" >/dev/null 2>&1; then
        "$_kbs" >/dev/null 2>&1 || true
        break
    fi
done
echo "Installed desktop entry: $DESKTOP_FILE"
echo "(If it doesn't appear in the menu immediately, log out and back in.)"

# --- Done ---
cat <<EOF

----------------------------------------
Setup complete.

A "Whipper GUI" entry has been added to your application menu.

To launch the GUI:
    source .venv/bin/activate
    whipper-gui

Or in one shot, no activation needed:
    .venv/bin/whipper-gui

EOF

if [ "$INSTALL_DEV" -eq 1 ]; then
    cat <<EOF
To run tests:
    source .venv/bin/activate
    pytest

EOF
fi

cat <<EOF
The venv is in .venv/ — to leave it after activation, run \`deactivate\`.
----------------------------------------
EOF
