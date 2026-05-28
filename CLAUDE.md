# CLAUDE.md — Whipper GUI Project Context

This file is loaded by Claude Code on every session in this project. It captures the persistent rules and constraints for the codebase. The **rules** section below the line is locked — do not edit it without explicit user confirmation. The **project operations** section at the bottom grows as the project develops.

---

## Project

Linux GUI front-end for the `whipper` audio-CD ripping CLI. EAC-equivalent archival quality, single-file AppImage distribution. Primary target: Bazzite Linux with KDE Plasma 6. Secondary: Fedora, Arch, Ubuntu, and other modern desktop Linux.

## Stack (locked)

- Python 3.11+
- PySide6 (Qt6) for the GUI
- `subprocess` for whipper CLI invocation
- `python-musicbrainzngs` for MusicBrainz lookups (bypasses whipper's interactive prompt)
- TOML config at `~/.config/whipper-gui/config.toml`
- `python-appimage` for AppImage builds
- `pipx` install as the secondary distribution channel

## Architecture (locked)

The GUI runs on the host. It calls the existing host-exported `~/.local/bin/whipper`, which transparently enters the Distrobox container named `ripping` to do the actual ripping work. The GUI never tries to run whipper in its own process, install whipper itself, or assume native whipper on the host. **This routing is non-negotiable** — it's how the user's system is configured and the brief disqualifies any distribution that can't reach it.

## Code conventions

- **Comments:** heavy. The maintainer has limited programming experience — comment intent, not mechanics. A reader who can read Python but doesn't deeply know Qt or whipper should understand the file.
- **Type hints:** mandatory on all function signatures, class attributes, and module-level constants.
- **Modules:** small and focused. Split when a file exceeds ~300 lines. One responsibility per module.
- **No clever metaprogramming.** Avoid decorators that mutate behavior unobviously, dynamic class creation, monkey-patching, or "magic" imports.
- **Error handling:** catch specific exceptions, never bare `except:`. Log with the `logging` module, not `print`.
- **Subprocess output parsing:** robust to whipper minor-version output changes. Use named-group regexes, not column-index splits.
- **Naming:** snake_case for functions, variables, modules; PascalCase for classes; SCREAMING_SNAKE_CASE for module-level constants.

## Critical rules

1. **Unmaintained dependencies require adapter layers.** Currently flagged as unmaintained: `whipper`, `python-musicbrainzngs`, and `appimage-builder` (if ever reached for). Every call into these MUST go through a thin adapter module so a future replacement is feasible without rewriting the GUI. Adapter modules are mandatory, not optional.

2. **`python-appimage` is the AppImage builder.** Do not use `appimage-builder` without stopping and asking first. If a build requirement cannot be expressed in `python-appimage`, describe the specific limitation in detail before reaching for any alternative. If `appimage-builder` is approved as a fallback, the recipe must stay close enough to vanilla that swapping back is cheap.

3. **Distrobox routing is sacred.** The GUI calls `~/.local/bin/whipper`. It does not call into the container directly, does not assume native whipper, does not try to install or update whipper itself.

4. **FLAC only for v1.** MP3, WAV, and other encoders are P1 backlog. When they land, they route through the same dependency self-management subsystem — no bespoke per-encoder install code.

5. **No bypass of MusicBrainz query path.** Always query MusicBrainz via the `MusicBrainzClient` adapter (currently backed by `python-musicbrainzngs`) to obtain the release ID first, then invoke whipper with `--release-id <MBID>`. Never let whipper's interactive TTY prompt surface to the user.

6. **Dependency self-management is one subsystem, not scattered checks.** All "is this dependency present and the right version" logic lives in a single module with the three-tier resolution strategy (auto-install → queued install → copyable search string). New dependencies route through it; no ad-hoc availability checks elsewhere in the codebase.

## Deviation policy

When in doubt during any session, stop and ask the user before doing the following:

**Must ask before doing:**
- Adding a dependency not listed in `DEPENDENCIES.md`
- Changing the distribution model
- Switching the GUI framework
- Skipping, reordering, or redefining a P0 feature
- Reaching for `appimage-builder`
- Bypassing the host-exported `~/.local/bin/whipper` routing
- Adding scattered dependency checks outside the self-management subsystem

**Just do it (no ask needed):**
- Renaming a function, variable, or local module
- Splitting an oversized file into focused submodules
- Small refactors for readability or to match project style
- Adjusting type hints, docstrings, or comments
- Reordering imports or reformatting per the linter

The line between these is judgment. When in doubt, the safer call is to stop and ask.

## Companion documents

Read these alongside this file when picking up a session:

- **`PLANNING.md`** — architecture, module design, key design decisions
- **`TASKS.md`** — active task checklist; update status (`[ ]` → `[~]` → `[x]`) as work progresses
- **`DEPENDENCIES.md`** — dep table with last release dates and replacement plans; review per the cadence stated in that file
- **`README.md`** — outward-facing project description
- **`whipper-gui-research-brief-v2.1.md`** (in `/docs/` once archived) — the project brief; canonical for requirements and scope
- **`compass_artifact_*.md`** (in `/docs/` once archived) — the Research validation; canonical for tool/architecture choices

If `PLANNING.md` and the brief conflict, the brief wins on requirements/scope and `PLANNING.md` wins on implementation choices. If `PLANNING.md` and the research output conflict, raise it with the user — don't silently pick.

---

## Project operations

*This section grows as the project develops. Add concrete commands, paths, and operational notes as they're established. Keep entries terse.*

### Build commands

- AppImage: `bash build/build_appimage.sh` (produces `whipper-gui-x86_64.AppImage` at repo root via `python-appimage`)

*(Build harness lands in T31; until then the script does not exist.)*

### Run commands

- From a checkout: `pip install -e .` once, then `python -m whipper_gui` (or `whipper-gui`)
- One-off from a checkout without install: `PYTHONPATH=src python -m whipper_gui`
- From the AppImage: `./whipper-gui-x86_64.AppImage`
- From a `pipx` install: `whipper-gui`

*(T01 placeholder runs and exits cleanly; the real GUI lands in T29.)*

### Test commands

- `pytest` from repo root (test scaffold lands in T30)

### Lint / format commands

*(Not yet configured. Likely additions: `ruff check .` and `ruff format .`. Add when a linting task lands.)*

### Important paths

- Source root: `src/whipper_gui/`
- User config: `~/.config/whipper-gui/config.toml`
- User logs: `~/.local/share/whipper-gui/log.txt`
- Whipper config (shared with Distrobox container): `~/.config/whipper/whipper.conf`
- Whipper binary (host-exported from Distrobox): `~/.local/bin/whipper`
- MusicBrainz Picard (Flatpak, used for auto-launch on unknown discs): `flatpak run org.musicbrainz.Picard`

### Notes for future sessions

*(add session-end notes here so context isn't lost between Claude Code sessions)*
