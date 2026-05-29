# `python-appimage` recipe

This directory is the recipe consumed by
`python -m python_appimage build app .` to produce the Whipper GUI
AppImage. The actual build is driven by `../build_appimage.sh`.

## Build prerequisites

- Python 3.11+
- `python3 -m pip install --user build "python-appimage>=1.4,<2"`
- Linux x86_64 (python-appimage's manylinux2014 base is x86_64-only).
  Arm64 support requires upstream changes — out of scope for v1.

## Files

| File | Purpose |
|---|---|
| `requirements.txt` | pip deps bundled into the AppImage. The locally-built whipper-gui wheel is resolved via the `PIP_FIND_LINKS` the build script exports (a global `--find-links .` line does **not** work — python-appimage installs each line from a temp dir). Version pins use `~=` because `<`/`>` get read as shell redirections during the build. |
| `entrypoint.sh` | Launch script. AppImage runtime sets `$APPDIR`; we run `$APPDIR/opt/python*/bin/python -m whipper_gui`. **Must keep an extension** — python-appimage globs `entrypoint.*` and silently ignores a bare `entrypoint`. |
| `whipper-gui.desktop` | Desktop integration metadata. |
| `whipper-gui.png` | App icon. `build_appimage.sh` generates a placeholder if missing; replace with a real 256×256 PNG before public release. |

## Building

From the repo root:

```bash
bash build/build_appimage.sh
```

The script builds a wheel from the current source, drops it next to
`requirements.txt`, and runs `python-appimage`. The resulting
`whipper-gui-x86_64.AppImage` appears at the repo root.

### Offline / rate-limited build hosts

By default python-appimage downloads a CPython base AppImage from the
GitHub **API**, which returns HTTP 403 when the unauthenticated rate
limit is exhausted. To build anyway, pre-download the matching base
image from the
[`niess/python-appimage`](https://github.com/niess/python-appimage/releases)
releases (keep its upstream filename, e.g.
`python3.11.14-cp311-cp311-manylinux2014_x86_64.AppImage`) and point the
build at it:

```bash
WHIPPER_GUI_BASE_IMAGE=/path/to/python3.11.x-cp311-cp311-manylinux2014_x86_64.AppImage \
  bash build/build_appimage.sh
```

On a build host without FUSE (e.g. many CI containers), also export
`APPIMAGE_EXTRACT_AND_RUN=1` so the bundled appimagetool extracts itself
instead of mounting.

## Replacing the placeholder icon

Replace `whipper-gui.png` with a 256×256 PNG and rerun the build. Any
PNG of any reasonable size is technically accepted; 256×256 is the
KDE/freedesktop convention.

## Updating pinned dependency versions

When `DEPENDENCIES.md` bumps a pin, update the matching line in
`requirements.txt` in the same commit. The two files are the only
authoritative sources for runtime deps.
