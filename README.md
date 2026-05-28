# Whipper GUI

A Linux GUI front-end for the [`whipper`](https://github.com/whipper-team/whipper) audio-CD ripping CLI. Aims for EAC-equivalent (Exact Audio Copy) archival quality on Linux, packaged as a single-file AppImage.

## System requirements

**Primary target:** Bazzite Linux with KDE Plasma 6.
**Secondary:** Fedora, Arch, Ubuntu, and other modern desktop Linux running Qt 6.

Required on the user's system before launching the GUI:

- An optical drive at `/dev/sr0` (or another path the user configures in Settings).
- `whipper` callable as `~/.local/bin/whipper`. The expected setup is whipper installed inside a [Distrobox](https://distrobox.it) container and exported to the host via `distrobox-export`. The GUI does **not** install whipper itself.
- `metaflac` callable on `PATH` (same Distrobox export route is fine).
- MusicBrainz Picard as a Flatpak: `flatpak install --user flathub org.musicbrainz.Picard`. The GUI will offer to install this for you if it's missing.

On first launch the GUI runs a dependency check and walks you through anything missing. See [`PLANNING.md`](PLANNING.md) §4 for how that check works.

## Install

**AppImage (primary):**

```bash
chmod +x whipper-gui-x86_64.AppImage
./whipper-gui-x86_64.AppImage
```

*The AppImage is not yet published. See `build/build_appimage.sh` to build it from source.*

**pipx (secondary):**

```bash
pipx install whipper-gui
```

*The wheel is not yet published. From a local checkout: `pipx install .`*

## Run

```bash
whipper-gui                  # if installed via pipx
./whipper-gui-x86_64.AppImage   # if using the AppImage
```

Or directly from a checkout:

```bash
python -m whipper_gui
```

## Build

To build the AppImage locally:

```bash
bash build/build_appimage.sh
```

This produces `whipper-gui-x86_64.AppImage` at the repo root. See `build/python-appimage/README.md` for build-time prerequisites.

## Documentation for contributors

- [`PLANNING.md`](PLANNING.md) — architecture, module design, design decisions
- [`TASKS.md`](TASKS.md) — active task checklist
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — dependency table, last release dates, replacement plans
- [`CLAUDE.md`](CLAUDE.md) — project rules and conventions (read before contributing)

## License

TBD. The project is in early bootstrap and a license has not been chosen yet. PySide6 is LGPL-3.0, which makes MIT, Apache-2.0, BSD, or GPL-3.0 all viable for the project's own code.

## Status

Pre-alpha. Bootstrap files are in place; implementation has not begun. See `TASKS.md` for what's next.
