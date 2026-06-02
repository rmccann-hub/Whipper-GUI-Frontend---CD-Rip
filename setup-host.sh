#!/usr/bin/env bash
# setup-host.sh — one-command host bootstrap for Whipper GUI.
#
# Automates README Steps 1-4 (the host stack that lives outside the GUI)
# and then the GUI install, so a new user goes from nothing to a launchable
# app in one command:
#
#   1. Ensure Distrobox + a container backend (podman/docker) are installed.
#   2. Create the `ripping` Distrobox container (Fedora-based).
#   3. Install whipper + flac + python3-setuptools inside it.
#   4. Export the whipper/metaflac binaries to ~/.local/bin on the host.
#   5. Clone the repo (if not already inside it) and run dev-setup.sh
#      (venv + editable install + desktop launcher).
#
# It does NOT calibrate the drive (Step 5) — that's the in-GUI drive setup
# wizard (Tools -> Set up drive…) — and it does NOT install Picard (Step 6),
# which the GUI's dependency manager offers on first run.
#
# Safe to re-run: every step checks current state first (idempotent).
#
# Usage:
#   bash setup-host.sh                 # interactive-ish; sane defaults
#   bash setup-host.sh --yes           # assume yes to confirmations
#   bash setup-host.sh --dry-run       # print every command, change nothing
#   bash setup-host.sh --no-gui        # host stack only; skip clone + dev-setup
#   bash setup-host.sh --container NAME --image IMAGE
#   bash setup-host.sh --help
#
# One-liner (the repo is public):
#   curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/main/setup-host.sh | bash

set -euo pipefail

# --- Defaults --------------------------------------------------------------
CONTAINER="ripping"
IMAGE="registry.fedoraproject.org/fedora-toolbox:latest"
DRY_RUN=0
ASSUME_YES=0
DO_GUI=1
REPO_URL="https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git"
# Where to clone if we're not already inside a checkout.
CLONE_DIR="${WHIPPER_GUI_CLONE_DIR:-$HOME/Whipper-GUI-Frontend---CD-Rip}"

usage() {
    cat <<'HELP'
setup-host.sh — one-command host bootstrap for Whipper GUI.

Automates README Steps 1-4 (Distrobox, the `ripping` container, whipper +
flac install, binary export) and then clones + installs the GUI.

Steps performed:
  1. Ensure Distrobox + a container backend (podman/docker) are installed.
  2. Create the `ripping` container (Fedora-based).
  3. Install whipper + flac + python3-setuptools inside it.
  4. Export whipper/metaflac to ~/.local/bin on the host.
  5. Clone the repo (if needed) and run dev-setup.sh.

Not done here: drive calibration (use the GUI's drive setup wizard) and
Picard (the GUI offers it on first run).

Idempotent: re-running skips work that's already done.

Usage:
  bash setup-host.sh                 sane defaults
  bash setup-host.sh --yes           assume "yes" to confirmations
  bash setup-host.sh --dry-run       print every command, change nothing
  bash setup-host.sh --no-gui        host stack only; skip clone + dev-setup
  bash setup-host.sh --container NAME --image IMAGE
  bash setup-host.sh --help
HELP
}

# --- Arg parsing -----------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --no-gui) DO_GUI=0 ;;
        --container) shift; CONTAINER="${1:?--container needs a value}" ;;
        --image) shift; IMAGE="${1:?--image needs a value}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# --- Helpers ---------------------------------------------------------------
# run(): echo a command; execute it unless --dry-run.
#
# CRITICAL: every command runs with stdin redirected from /dev/null. When
# this script is invoked as `curl … | bash`, the script itself IS bash's
# stdin — and any command that reads stdin (notably `distrobox enter`)
# would otherwise swallow the rest of the script, so execution silently
# stops partway. None of our commands need real stdin, so </dev/null is
# both safe and the fix. (User-facing prompts use /dev/tty via confirm().)
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "DRY-RUN: $*"
    else
        echo "+ $*"
        "$@" </dev/null
    fi
}

# confirm(): yes/no prompt. Auto-yes with --yes; auto-yes in dry-run (we're
# not changing anything anyway). Reads from /dev/tty, not stdin, so it works
# under `curl … | bash` (where stdin is the script) and never consumes it.
confirm() {
    local prompt="$1"
    if [ "$ASSUME_YES" -eq 1 ] || [ "$DRY_RUN" -eq 1 ]; then
        return 0
    fi
    if [ ! -r /dev/tty ]; then
        echo "No terminal to confirm on; re-run with --yes if you meant to." >&2
        return 1
    fi
    read -r -p "$prompt [y/N] " reply </dev/tty
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

have() { command -v "$1" >/dev/null 2>&1; }

step() { echo; echo "=== $* ==="; }

die() { echo "ERROR: $*" >&2; exit 1; }

# distrobox runs a command inside the container and returns.
in_container() { run distrobox enter "$CONTAINER" -- "$@"; }

# --- Step 1: Distrobox -----------------------------------------------------
ensure_distrobox() {
    step "Step 1/5 — Distrobox"
    if have distrobox; then
        echo "Distrobox already installed: $(distrobox --version 2>/dev/null || echo present)"
        return
    fi
    echo "Distrobox not found. It's preinstalled on Bazzite/Silverblue; on"
    echo "other distros it needs installing."
    if ! confirm "Install Distrobox now?"; then
        die "Distrobox is required. Install it and re-run (see README Step 1)."
    fi
    # Pick the host package manager from /etc/os-release (OS_RELEASE_FILE
    # lets tests point this at a fixture).
    local id_like=""
    local os_release="${OS_RELEASE_FILE:-/etc/os-release}"
    [ -r "$os_release" ] && id_like="$(. "$os_release"; echo "${ID:-} ${ID_LIKE:-}")"
    case "$id_like" in
        *fedora*|*rhel*|*centos*) run sudo dnf install -y distrobox ;;
        *debian*|*ubuntu*)        run sudo apt-get install -y distrobox ;;
        *arch*)                   run sudo pacman -S --noconfirm distrobox ;;
        *suse*)                   run sudo zypper --non-interactive install distrobox ;;
        *)
            echo "Unknown distro; using the upstream installer."
            run sh -c 'curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh'
            ;;
    esac
    if [ "$DRY_RUN" -eq 0 ] && ! have distrobox; then
        die "Distrobox install did not succeed. See README Step 1."
    fi
}

# --- Step 1.5: container backend (podman/docker) ---------------------------
# Distrobox is only a front-end; it needs podman or docker to actually create
# containers. On Bazzite/Silverblue podman is preinstalled, but on Ubuntu/Debian
# `apt install distrobox` does NOT reliably pull a backend (podman is only a
# Recommends, which `--no-install-recommends` setups skip), and the upstream
# installer ships no backend at all. Without one, `distrobox create` fails with
# "Cannot find a container manager." Ensure podman is present; it's the
# Distrobox default and is in every target distro's repos.
ensure_container_backend() {
    step "Step 1.5/5 — container backend (podman/docker)"
    if have podman; then
        echo "Found podman: $(podman --version 2>/dev/null || echo present)"
        return
    fi
    if have docker; then
        echo "Found docker — Distrobox can use it."
        return
    fi
    echo "No container backend (podman/docker) found. Distrobox needs one."
    if ! confirm "Install podman now?"; then
        die "A container backend is required. Install podman or docker and re-run."
    fi
    local id_like=""
    local os_release="${OS_RELEASE_FILE:-/etc/os-release}"
    [ -r "$os_release" ] && id_like="$(. "$os_release"; echo "${ID:-} ${ID_LIKE:-}")"
    case "$id_like" in
        *fedora*|*rhel*|*centos*) run sudo dnf install -y podman ;;
        *debian*|*ubuntu*)        run sudo apt-get install -y podman ;;
        *arch*)                   run sudo pacman -S --noconfirm podman ;;
        *suse*)                   run sudo zypper --non-interactive install podman ;;
        *)                        die "Unknown distro; install podman or docker manually and re-run." ;;
    esac
    if [ "$DRY_RUN" -eq 0 ] && ! have podman; then
        die "podman install did not succeed. Install podman or docker and re-run."
    fi
}

# --- Step 2: container -----------------------------------------------------
container_exists() {
    have distrobox || return 1
    distrobox list 2>/dev/null | grep -qw "$CONTAINER"
}

ensure_container() {
    step "Step 2/5 — '$CONTAINER' container"
    if container_exists; then
        echo "Container '$CONTAINER' already exists — leaving it as is."
        return
    fi
    echo "Creating container '$CONTAINER' from $IMAGE"
    # --yes auto-confirms the image pull (the ':latest' pull prompt bit a
    # real user during testing).
    run distrobox create --yes --name "$CONTAINER" --image "$IMAGE"
}

# --- Step 3: whipper + metaflac --------------------------------------------
install_tools() {
    step "Step 3/5 — whipper + flac + python3-setuptools (in container)"
    # python3-setuptools is required because whipper 0.10 imports
    # pkg_resources, which modern Python no longer bundles.
    in_container sudo dnf install -y whipper flac python3-setuptools
}

# --- Step 4: export to host ------------------------------------------------
export_binaries() {
    step "Step 4/5 — export whipper + metaflac to ~/.local/bin"
    in_container distrobox-export --bin /usr/bin/whipper
    in_container distrobox-export --bin /usr/bin/metaflac
    if [ "$DRY_RUN" -eq 0 ]; then
        if [ -x "$HOME/.local/bin/whipper" ]; then
            echo "Exported: $HOME/.local/bin/whipper"
        else
            die "Export did not create ~/.local/bin/whipper — see README Step 4."
        fi
        case ":$PATH:" in
            *":$HOME/.local/bin:"*) ;;
            *) echo "NOTE: ~/.local/bin is not on your PATH; add it for terminal use." ;;
        esac
    fi
}

# --- Step 5: clone + GUI ---------------------------------------------------
# Locate this script's directory; if it sits in a checkout (dev-setup.sh +
# pyproject.toml next to it), use that. Otherwise we were piped from curl and
# need to clone.
script_repo_dir() {
    local src="${BASH_SOURCE[0]:-}"
    [ -n "$src" ] || return 1
    local dir
    dir="$(cd "$(dirname "$src")" 2>/dev/null && pwd)" || return 1
    if [ -f "$dir/dev-setup.sh" ] && [ -f "$dir/pyproject.toml" ]; then
        echo "$dir"
        return 0
    fi
    return 1
}

install_gui() {
    step "Step 5/5 — clone + install the GUI"
    local repo_dir
    if repo_dir="$(script_repo_dir)"; then
        echo "Running from a checkout: $repo_dir"
    else
        if [ -d "$CLONE_DIR/.git" ]; then
            echo "Reusing existing clone at $CLONE_DIR"
        else
            run git clone "$REPO_URL" "$CLONE_DIR"
        fi
        repo_dir="$CLONE_DIR"
    fi
    run bash "$repo_dir/dev-setup.sh"
    echo
    echo "GUI installed. Launch it from your app menu (\"Whipper GUI\") or:"
    echo "    source \"$repo_dir/.venv/bin/activate\" && whipper-gui"
}

# --- Main ------------------------------------------------------------------
echo "Whipper GUI host setup"
[ "$DRY_RUN" -eq 1 ] && echo "(DRY RUN — no changes will be made)"

have git || die "git is required (to clone the repo). Install git and re-run."

ensure_distrobox
ensure_container_backend
ensure_container
install_tools
export_binaries
if [ "$DO_GUI" -eq 1 ]; then
    install_gui
else
    step "Step 5/5 — skipped (--no-gui)"
fi

echo
echo "Done. Next: open Whipper GUI, then Tools -> Set up drive… to calibrate"
echo "your drive (insert a popular CD), and rip."
