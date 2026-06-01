#!/usr/bin/env bash
# install.sh — one-command, single-file installer for Whipper GUI (end users).
#
# Takes a machine from nothing to a launchable app:
#   1. Host stack: Distrobox + the `ripping` container + whipper + flac,
#      exported to ~/.local/bin (delegated to setup-host.sh --no-gui).
#   2. The GUI: downloads the published AppImage release (or uses a local /
#      freshly-built one) and parks it in ~/Applications.
#   3. Desktop integration: an app-menu entry, a Desktop icon, AND an
#      "Uninstall Whipper GUI" shortcut (delegated to install-appimage.sh).
#
# It reuses setup-host.sh and install-appimage.sh, downloading them if this
# script is run on its own (not from a checkout), so it stays a single file
# you can download and run — or pipe:
#   curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/main/install.sh | bash
#
# Usage:
#   bash install.sh                 # full install (host stack + GUI)
#   bash install.sh --yes           # assume "yes" to confirmations
#   bash install.sh --dry-run       # print actions, change nothing
#   bash install.sh --no-host       # skip the host stack; install the GUI only
#   bash install.sh --appimage PATH # use a local AppImage (skip the download)
#   bash install.sh --build         # build the AppImage from a source checkout
#   bash install.sh --container NAME --image IMAGE   # passed to setup-host.sh
#   bash install.sh --help

set -euo pipefail

# --- Config / defaults -----------------------------------------------------
OWNER_REPO="rmccann-hub/Whipper-GUI-Frontend---CD-Rip"
REPO_RAW="https://raw.githubusercontent.com/$OWNER_REPO/main"
APPIMAGE_NAME="whipper-gui-x86_64.AppImage"
APPS_DIR="$HOME/Applications"

DRY_RUN=0
ASSUME_YES=0
DO_HOST=1
DO_BUILD=0
APPIMAGE_PATH=""
CONTAINER=""
IMAGE=""

usage() {
    cat <<'HELP'
install.sh — one-command installer for Whipper GUI.

Installs everything an end user needs:
  1. Host stack  : Distrobox + the `ripping` container + whipper + flac,
                   exported to ~/.local/bin (via setup-host.sh --no-gui).
  2. GUI         : downloads the published AppImage into ~/Applications.
  3. Shortcuts   : app-menu entry, Desktop icon, and an "Uninstall Whipper
                   GUI" shortcut (via install-appimage.sh).

Usage:
  bash install.sh                 full install (host stack + GUI)
  bash install.sh --yes           assume "yes" to confirmations
  bash install.sh --dry-run       print actions, change nothing
  bash install.sh --no-host       skip the host stack; install the GUI only
  bash install.sh --appimage PATH use a local AppImage (skip the download)
  bash install.sh --build         build the AppImage from a source checkout
  bash install.sh --container NAME --image IMAGE   passed to setup-host.sh
  bash install.sh --help          this message

To remove everything later: use the "Uninstall Whipper GUI" shortcut, or run
uninstall.sh (interactive, with options).
HELP
}

# --- Parse args ------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --no-host) DO_HOST=0 ;;
        --build) DO_BUILD=1 ;;
        --appimage) shift; APPIMAGE_PATH="${1:?--appimage needs a path}" ;;
        --container) shift; CONTAINER="${1:?--container needs a value}" ;;
        --image) shift; IMAGE="${1:?--image needs a value}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
    shift
done

# --- Helpers ---------------------------------------------------------------
# run(): echo a command; execute it unless --dry-run.
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "  DRY-RUN: $*"
    else
        "$@"
    fi
}

# Where this script lives, if it's a real file (not a `curl … | bash` pipe).
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

TMP_DIR=""
# Must return 0: as an EXIT-trap, a non-zero status here would become the
# script's exit code (it does, when TMP_DIR is empty and the && short-circuits).
cleanup() { [ -n "$TMP_DIR" ] && rm -rf "$TMP_DIR"; return 0; }
trap cleanup EXIT

# fetch_script <name> — print a path to a sibling script, preferring a local
# copy (running from a checkout), else downloading it from the repo.
fetch_script() {
    local name="$1"
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/$name" ]; then
        echo "$SCRIPT_DIR/$name"
        return 0
    fi
    [ -n "$TMP_DIR" ] || TMP_DIR="$(mktemp -d)"
    curl -fsSL "$REPO_RAW/$name" -o "$TMP_DIR/$name" || return 1
    echo "$TMP_DIR/$name"
}

# download_appimage <dest> — fetch the AppImage from the newest release.
# Uses the API (not /releases/latest/download) because v0.x ships as a
# *pre-release*, which the "latest" endpoint skips.
download_appimage() {
    local dest="$1" url
    url="$(curl -fsSL "https://api.github.com/repos/$OWNER_REPO/releases" \
        | grep '"browser_download_url"' \
        | grep "$APPIMAGE_NAME\"" \
        | head -1 | cut -d'"' -f4)"
    [ -n "$url" ] || return 1
    echo "  from: $url"
    curl -fL "$url" -o "$dest"
    chmod +x "$dest"
}

# --- 1. Host stack ---------------------------------------------------------
HOST_FLAGS=()
[ "$ASSUME_YES" -eq 1 ] && HOST_FLAGS+=(--yes)
[ "$DRY_RUN" -eq 1 ] && HOST_FLAGS+=(--dry-run)
[ -n "$CONTAINER" ] && HOST_FLAGS+=(--container "$CONTAINER")
[ -n "$IMAGE" ] && HOST_FLAGS+=(--image "$IMAGE")

if [ "$DO_HOST" -eq 1 ]; then
    echo "==> 1/3 Host stack (Distrobox + ripping container + whipper)…"
    host_sh="$(fetch_script setup-host.sh)" \
        || { echo "Couldn't obtain setup-host.sh." >&2; exit 1; }
    run bash "$host_sh" --no-gui "${HOST_FLAGS[@]}"
else
    echo "==> 1/3 Skipping host stack (--no-host)."
fi

# --- 2. Obtain the AppImage ------------------------------------------------
appimage=""
if [ -n "$APPIMAGE_PATH" ]; then
    echo "==> 2/3 Using local AppImage: $APPIMAGE_PATH"
    appimage="$APPIMAGE_PATH"
elif [ "$DO_BUILD" -eq 1 ]; then
    echo "==> 2/3 Building the AppImage from source…"
    if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/build/build_appimage.sh" ]; then
        echo "--build needs a source checkout (run this script from a clone)." >&2
        exit 1
    fi
    run bash "$SCRIPT_DIR/build/build_appimage.sh"
    appimage="$SCRIPT_DIR/$APPIMAGE_NAME"
else
    echo "==> 2/3 Downloading the latest published AppImage…"
    run mkdir -p "$APPS_DIR"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "  DRY-RUN: download $APPIMAGE_NAME from the newest release into $APPS_DIR/"
    else
        download_appimage "$APPS_DIR/$APPIMAGE_NAME" || {
            echo "Couldn't download the AppImage — no published release yet?" >&2
            echo "Run from a checkout with --build, or pass --appimage PATH." >&2
            exit 1
        }
    fi
    appimage="$APPS_DIR/$APPIMAGE_NAME"
fi

# --- 3. Desktop integration (+ uninstall shortcut) -------------------------
echo "==> 3/3 Integrating into your desktop…"
ia_sh="$(fetch_script install-appimage.sh)" \
    || { echo "Couldn't obtain install-appimage.sh." >&2; exit 1; }
run bash "$ia_sh" "$appimage"

echo
echo "Done. Look for \"Whipper GUI\" in your application menu."
echo "To remove it later, use the \"Uninstall Whipper GUI\" shortcut."
