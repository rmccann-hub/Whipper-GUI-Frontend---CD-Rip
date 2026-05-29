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

- **`PLANNING.md`** — architecture, module design, key design decisions (KDD-01 through KDD-13)
- **`TASKS.md`** — active task checklist; update status (`[ ]` → `[~]` → `[x]`) as work progresses. Sections: P0 (v1 release, T01-T32), P1.1 (install/uninstall ease — highest-priority P1 subset), P1 (broader backlog), P2 (future), Out of scope.
- **`DEPENDENCIES.md`** — dep table with last release dates and replacement plans; review per the cadence stated in that file
- **`README.md`** — outward-facing project description and install instructions
- **`docs/README.md`** — index of the docs/ directory and a rebuild-from-scratch checklist
- **`docs/whipper-gui-research-brief-v2.1.md`** — the project brief; canonical for requirements and scope
- **`docs/whipper-gui-session-start.md`** — bootstrap instructions a fresh Claude Code session uses to reproduce the initial planning artifacts
- **`docs/whipper-gui-research-rerun-prompt.md`** — Research-mode prompt for refreshing tool-choice validation
- **`docs/log-format-comparison.md`** — whipper rip log vs EAC log side-by-side (referenced by KDD-11)

If `PLANNING.md` and the brief conflict, the brief wins on requirements/scope and `PLANNING.md` wins on implementation choices. If `PLANNING.md` and the research output conflict, raise it with the user — don't silently pick.

There is no `compass_artifact_*.md` in the repo; the original v1 research validation was unavailable when the project was bootstrapped, so the project proceeded against the brief alone. To refresh tool-choice research, follow `docs/whipper-gui-research-rerun-prompt.md`.

---

## Project operations

*This section grows as the project develops. Add concrete commands, paths, and operational notes as they're established. Keep entries terse.*

### Build commands

- AppImage: `bash build/build_appimage.sh` (produces `whipper-gui-x86_64.AppImage` at repo root via `python-appimage`)

### Run commands

- **Quickstart from a fresh clone:** `bash dev-setup.sh` then `source .venv/bin/activate && whipper-gui`
- **Manual:** `python3 -m venv .venv && source .venv/bin/activate && pip install --upgrade pip && pip install -e . && whipper-gui`
- **From the AppImage (once published):** `./whipper-gui-x86_64.AppImage`
- **From a `pipx` install (once published):** `whipper-gui`
- **Version check without launching the GUI:** `whipper-gui --version`

### Test commands

- `pytest` from repo root (no env vars needed — `pyproject.toml` sets `pythonpath = ["src"]`)

### Uninstall

- `bash uninstall.sh` (interactive; removes `.venv/`, GUI config, GUI logs; prompts for Picard / Distrobox / whipper.conf / host exports)
- `bash uninstall.sh --full --yes` (removes everything except music files and the cloned repo)
- `bash uninstall.sh --dry-run` (shows what would be removed)
- `bash uninstall.sh --help`

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

- **P0 status:** 31 of 32 tasks done. T32 (end-to-end smoke test) is in progress — the **rip pipeline is verified end-to-end** on real hardware (see below); only the AppImage build+launch remains before T32 closes.
- **T32 real-hardware rip (2026-05-29):** a 16-track CD-R ripped end-to-end on Bazzite + Distrobox + Pioneer BDR-209D. All Test CRCs == Copy CRCs, FLACs play, `.log`/`.cue`/`.m3u`/`.toc` written, AccurateRip correctly "not in DB". Findings + fixes (each has a test):
  - whipper refuses CD-Rs without `--cdr` → added `Config.continue_on_cdr` + Settings toggle + `RipParameters.cdr` + flag passthrough.
  - whipper `os.chdir()`s into `--working-directory` without creating it → adapter now `mkdir -p`s the working + output dirs before the rip.
  - **KDD-06 RESOLVED: libdiscid is NOT needed on the host** (whipper-in-container computes the disc ID; the GUI never calls libdiscid). The `libdiscid` registry entry stays unneeded.
  - **KDD-13 answered:** whipper writes `.cue` + `.m3u` + `.toc` next to the FLACs and fills ISRC/UPC slots (all-zero on a CD-R).
  - Unknown-disc UX: track table now shows `Track 01…NN` placeholder rows (`DiscInfo.num_tracks` salvaged from `cd info`'s partial output); status label stays live through the pre-track disc scan (`RipWorker.status` signal).
  - Path templates: two pairs picked per rip (`ui/rip_controls`). Known disc → `%A/%d/%t - %n - %d - %A - %y` (Artist/Album/`## - Title - Album - Artist - Year`); unknown disc → literal `Unknown Artist/Unknown Album/%t - Track %t` (avoids the disc-ID hash whipper puts in `%d`, so no post-rip renaming needed). All four editable in Settings; config schema v1→v2 migration upgrades untouched known templates. whipper templates are flat (no conditionals): year-less known discs get a trailing " - "; `%N` disc-number omitted from the default (add `/%N` for multi-disc).
- **Real-user testing on Bazzite (2026-05-28/29)** surfaced and fixed a series of upstream/environment issues; each has a code comment with the diagnosis:
  - `whipper` has no `-d`/`--device` flag (assumed wrong in early adapter) — `adapters/whipper_backend.py`
  - `whipper cd info` exits -1 with "unable to retrieve disc metadata" on discs not in MB/FreeDB; `--unknown` isn't accepted by `Info` even though `_CD.do()` requires it — adapter catches and returns empty DiscInfo
  - Whipper 0.10.0 imports `pkg_resources` which Python 3.14 dropped — `python3-setuptools` must be installed alongside whipper in the Distrobox container
  - On Bazzite (Atomic), Flathub is a system-level remote by default; `flatpak install --user flathub <ref>` fails with "No remote refs found for 'flathub'" — registry uses the `.flatpakref` URL instead, which auto-configures the user remote
  - `gh` isn't preinstalled on Bazzite and `sudo dnf install gh` doesn't work on immutable hosts — README recommends SSH key auth as the primary path for Bazzite/Silverblue
  - Fresh venvs ship outdated `pip` on most distros — `dev-setup.sh` runs `pip install --upgrade pip` before installing the package
- **Branch state:** all work is on `claude/lucid-babbage-JYI8c`. `main` only has `.gitattributes`. Merge to main is gated on T32 passing.
