#!/usr/bin/env bash
# Build the Whipper GUI AppImage via python-appimage.
#
# What this script does:
#   1. Verifies the build prerequisites (python3 ≥ 3.11, `build`,
#      `python-appimage`) are installed; offers a hint if not.
#   2. Builds a wheel from the local source via `python -m build`.
#   3. Places the wheel under build/python-appimage/ where
#      python-appimage's requirements.txt picks it up via --find-links.
#   4. Drops in a placeholder icon if no real one is present yet.
#   5. Invokes `python -m python_appimage build app …` to bundle the
#      Python interpreter + the wheel + its deps into a single .AppImage
#      at the repo root.
#
# The build is reproducible to a first approximation: the wheel is
# rebuilt every run from the current source, and python-appimage pins
# a CPython tag (manylinux2014). Reproducibility in the strict sense
# (bit-identical output) requires SOURCE_DATE_EPOCH discipline that
# we don't enforce here — sufficient for v1.

set -euo pipefail

# --- Resolve paths ---------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RECIPE_DIR="$SCRIPT_DIR/python-appimage"

cd "$REPO_ROOT"

# --- Prereq check ----------------------------------------------------------
require_python_module() {
    local module="$1"
    local pip_name="$2"
    if ! python3 -c "import ${module}" >/dev/null 2>&1; then
        echo "Missing Python module: ${module}"
        echo "Install with: python3 -m pip install --user ${pip_name}"
        exit 1
    fi
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but not on PATH."
    exit 1
fi

require_python_module build build
require_python_module python_appimage 'python-appimage>=1.4,<2'

# --- Build the wheel -------------------------------------------------------
echo "[1/3] Building wheel from local source…"
rm -f "$RECIPE_DIR"/whipper_gui-*.whl
python3 -m build --wheel --outdir "$RECIPE_DIR"
ls -1 "$RECIPE_DIR"/whipper_gui-*.whl

# --- Icon ------------------------------------------------------------------
# python-appimage's "build app" recipe requires <name>.png in the recipe
# directory. The real icon (build/python-appimage/whipper-gui.png, produced
# by build/make_icon.py) is committed, so this fallback normally does nothing
# — it only fires if that file has been deleted, dropping a 16×16 grey square
# so the build still succeeds.
if [ ! -f "$RECIPE_DIR/whipper-gui.png" ]; then
    echo "Note: no whipper-gui.png in recipe; generating placeholder."
    python3 - <<'PY'
import struct
import zlib
from pathlib import Path

# Hand-rolled 16x16 RGBA PNG with a uniform mid-grey. Stays under
# 200 bytes; replace with a real icon before release.
width = height = 16
pixels = bytes((40, 40, 40, 255) * width)
raw = b"".join(b"\x00" + pixels for _ in range(height))
compressed = zlib.compress(raw, 9)

def chunk(tag, data):
    crc = zlib.crc32(tag + data) & 0xffffffff
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", ihdr)
    + chunk(b"IDAT", compressed)
    + chunk(b"IEND", b"")
)
Path("build/python-appimage/whipper-gui.png").write_bytes(png)
PY
fi

# --- Build the AppImage ----------------------------------------------------
echo "[2/3] Building AppImage via python-appimage…"

# Tell pip where to find the locally-built whipper_gui wheel. python-appimage
# installs each requirements.txt line from a temporary directory, so a
# relative `--find-links .` in the recipe can't work; PIP_FIND_LINKS is a pip
# environment variable (not a PYTHON* one), so it survives pip's `-I` isolated
# mode and applies to every per-line install.
export PIP_FIND_LINKS="$RECIPE_DIR"

# Optional offline / rate-limit escape hatch: by default python-appimage hits
# the GitHub API to discover and download a CPython base AppImage. On a host
# where api.github.com is unreachable or rate-limited (HTTP 403), pre-download
# the matching base image (from github.com/niess/python-appimage releases) and
# point WHIPPER_GUI_BASE_IMAGE at it to skip the API entirely. The filename
# must keep its upstream form, e.g.
#   python3.11.14-cp311-cp311-manylinux2014_x86_64.AppImage
if [ -n "${WHIPPER_GUI_BASE_IMAGE:-}" ]; then
    if [ ! -f "$WHIPPER_GUI_BASE_IMAGE" ]; then
        echo "WHIPPER_GUI_BASE_IMAGE is set but not a file: $WHIPPER_GUI_BASE_IMAGE"
        exit 1
    fi
    echo "Using pre-downloaded base image: $WHIPPER_GUI_BASE_IMAGE"
    python3 -m python_appimage build app "$RECIPE_DIR" \
        --base-image "$WHIPPER_GUI_BASE_IMAGE"
else
    python3 -m python_appimage build app "$RECIPE_DIR"
fi

# python-appimage emits the AppImage at the current directory, named after
# the .desktop "Name=" field (e.g. "Whipper-GUI-x86_64.AppImage"). Note:
# python-appimage builds the appimagetool command unquoted, so the Name must
# not contain spaces or the output file is silently never produced. We
# normalise the result to the canonical artifact name the rest of the project
# (README, CLAUDE.md) refers to.
echo "[3/3] Normalising AppImage name…"
desktop_name="$(sed -n 's/^Name=//p' "$RECIPE_DIR/whipper-gui.desktop" | head -1)"
arch="$(uname -m)"
produced="$REPO_ROOT/${desktop_name}-${arch}.AppImage"
canonical="$REPO_ROOT/whipper-gui-${arch}.AppImage"
if [ -f "$produced" ] && [ "$produced" != "$canonical" ]; then
    mv -f "$produced" "$canonical"
fi
if [ -f "$canonical" ]; then
    ls -lh "$canonical"
else
    echo "No AppImage produced at $canonical. Check python-appimage output above."
    exit 1
fi

# --- Embed AppImage update-information (KDD-17b) -----------------------------
# python-appimage hardcodes its appimagetool invocation (no -u support), so we
# re-pack the finished AppImage ourselves to embed the standard zsync
# update-information. Any AppImageUpdate-compatible tool can then discover the
# newest GitHub release and download only the changed blocks, verified.
# Re-packing also emits whipper-gui-<arch>.AppImage.zsync (when `zsyncmake` is
# installed — package "zsync") which release.yml uploads beside the AppImage.
# This runs BEFORE the release workflow's checksum step, so the .sha256 always
# covers the final, update-info-embedded file.
UPDATE_INFO="gh-releases-zsync|rmccann-hub|Whipper-GUI-Frontend---CD-Rip|latest|whipper-gui-${arch}.AppImage.zsync"

find_appimagetool() {
    # A system appimagetool wins; otherwise reuse the copy python-appimage
    # just cached for its own build (~/.cache/python-appimage/bin).
    command -v appimagetool 2>/dev/null && return 0
    local candidate
    # NOTE: python-appimage caches the tool in a DOT-prefixed directory
    # (.appimagetool-<ver>.appdir/AppRun), which a plain * glob skips —
    # that exact miss broke the v0.2.0 release upload. Match both forms.
    for candidate in "$HOME/.cache/python-appimage/bin"/.appimagetool*/AppRun \
                     "$HOME/.cache/python-appimage/bin"/*appimagetool*/AppRun \
                     "$HOME/.cache/python-appimage/bin"/*appimagetool*; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

echo "[4/4] Embedding zsync update-information…"
if tool="$(find_appimagetool)"; then
    chmod +x "$canonical"
    workdir="$(mktemp -d)"
    (
        cd "$workdir"
        # Extract-and-repack keeps working on FUSE-less hosts (CI).
        APPIMAGE_EXTRACT_AND_RUN=1 "$canonical" --appimage-extract >/dev/null
        ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream \
            -u "$UPDATE_INFO" squashfs-root "$canonical"
    )
    # appimagetool drops the .zsync in its working directory; move it home.
    zsync_name="whipper-gui-${arch}.AppImage.zsync"
    if [ -f "$workdir/$zsync_name" ]; then
        mv -f "$workdir/$zsync_name" "$REPO_ROOT/$zsync_name"
    fi
    rm -rf "$workdir"
    if [ -f "$REPO_ROOT/$zsync_name" ]; then
        echo "Wrote $zsync_name (delta updates enabled)"
    else
        echo "NOTE: no .zsync produced — install 'zsync' (zsyncmake) for delta"
        echo "      update files; the update-information is embedded regardless."
    fi
else
    echo "NOTE: appimagetool not found — skipped update-information embed."
    echo "      (Run the build once so python-appimage caches it, or install"
    echo "      appimagetool on PATH.)"
fi
