# TASKS.md — Whipper GUI Active Task Checklist

Single source of truth for what's being worked on next. Update status as work progresses:

- `[ ]` not started
- `[~]` in progress
- `[x]` complete
- `[?]` blocked (add a one-line note about what's blocking)

Execute P0 tasks in order — they're ordered by dependency. P1 is the backlog and is **not** to be started until P0 is shipped.

When a task changes status, update it here in the same commit as the code change. When a task uncovers a new sub-task, add it to this file; don't let it live only in chat.

---

## P0 — v1 release

### Foundation

- [ ] T01 — Repo scaffolding
      Acceptance: `pyproject.toml`, `.gitignore`, `src/whipper_gui/__init__.py` (with `__version__`), `src/whipper_gui/__main__.py` (calls `app.main`), empty `tests/`, empty `build/` directory exist. `python -m whipper_gui` runs and exits cleanly with a placeholder message.
      Phase: P0

- [ ] T02 — Logging setup module (`logging_setup.py`)
      Acceptance: importing and calling `configure_logging()` once produces a rotating file at `~/.local/share/whipper-gui/log.txt` plus a console handler at INFO. `logging.getLogger(__name__)` in any module writes to both.
      Phase: P0

- [ ] T03 — Paths module (`paths.py`)
      Acceptance: module-level constants `CONFIG_PATH`, `LOG_DIR`, `WHIPPER_CONFIG_PATH`, `WHIPPER_BINARY_DEFAULT` populated from XDG env vars with sane fallbacks. Used by `config.py` and `logging_setup.py`.
      Phase: P0

- [ ] T04 — TOML config module (`config.py`)
      Acceptance: `load_config()` returns the parsed TOML as a typed dataclass, creating the file with defaults if missing. `save_config(cfg)` atomically writes (temp + rename). Schema version embedded. Unit-tested in `tests/test_config.py`.
      Phase: P0

### Dependency self-management subsystem (brief P0 #11)

- [ ] T05 — Version-string parsing utility (`deps/version.py`)
      Acceptance: `parse_version(text, pattern)` and `meets_minimum(version, minimum)` exist. Unit-tested.
      Phase: P0

- [ ] T06 — Probe functions (`deps/checks.py`)
      Acceptance: `check_whipper()`, `check_metaflac()`, `check_libdiscid()`, `check_picard_flatpak()`, `check_python_pkg(name)` each return a `ProbeResult(present, version, location)`. No side effects.
      Phase: P0

- [ ] T07 — DependencySpec registry (`deps/registry.py`)
      Acceptance: `SPECS: list[DependencySpec]` declaratively lists all v1 deps (whipper, metaflac, libdiscid, musicbrainzngs, Picard). Each spec names probe, min_version, tier preference, install command, and tier-(c) search string.
      Phase: P0

- [ ] T08 — Resolver classes (`deps/resolvers.py`)
      Acceptance: `AutoInstaller`, `QueuedInstaller`, `ManualPrompt` exist with a common `resolve(specs)` shape. AutoInstaller runs pipx and `flatpak install --user`. QueuedInstaller and ManualPrompt drive UI dialogs (defer wiring until T15/T16 land).
      Phase: P0

- [ ] T09 — DependencyManager orchestrator (`deps/manager.py`)
      Acceptance: `DependencyManager.check_all()` walks the registry, classifies, dispatches to resolvers, returns a `DependencyReport`. Idempotent. Unit-tested with mocked probes in `tests/test_dependency_manager.py`.
      Phase: P0

### Adapters

- [ ] T10 — WhipperBackend ABC + host-exported impl (`adapters/whipper_backend.py`)
      Acceptance: `WhipperBackend` ABC with all five methods from PLANNING.md §5. `WhipperHostExportedImpl` shells out to `~/.local/bin/whipper`. Tested with fixture-driven mocks in `tests/test_whipper_backend.py`.
      Phase: P0

- [ ] T11 — MusicBrainzClient ABC + ngs impl (`adapters/musicbrainz_client.py`)
      Acceptance: ABC per PLANNING.md §6. `MusicBrainzNgsImpl` wraps `musicbrainzngs`. `set_user_agent` invoked at construction. Exceptions reraised as `MusicBrainzQueryError`. Tested with `musicbrainzngs` mocked.
      Phase: P0

- [ ] T12 — Metaflac adapter (`adapters/metaflac.py`)
      Acceptance: `MetaflacAdapter.write_tags(flac_path, tags)` and `.read_tags(flac_path)` work via the `metaflac` CLI. Used by the unknown-album flow.
      Phase: P0

### Parsers

- [ ] T13 — Drive list parser (`parsers/drive_list.py`)
      Acceptance: `parse_drive_list(stdout)` returns `list[DriveDescriptor]`. Fixture-driven test with sample `whipper drive list` output.
      Phase: P0

- [ ] T14 — CD info parser (`parsers/cd_info.py`)
      Acceptance: `parse_cd_info(stdout)` returns `DiscInfo`. Fixture-driven test.
      Phase: P0

- [ ] T15 — Rip log parser (`parsers/rip_log.py`)
      Acceptance: `parse_rip_log(text)` returns a `RipLog` with per-track CRCs, AccurateRip confidence, error counts. Fixture-driven test with at least one real whipper `.log`.
      Phase: P0

### Workers

- [ ] T16 — Rip worker (`workers/rip_worker.py`)
      Acceptance: `RipWorker(QObject)` owns the rip subprocess; emits `log_line`, `progress`, `finished`, `error`. `.cancel()` terminates cleanly.
      Phase: P0

- [ ] T17 — MusicBrainz worker (`workers/mb_worker.py`)
      Acceptance: `MusicBrainzWorker(QObject)` runs `MusicBrainzClient` calls on a background `QThread`; emits `releases_returned` or `error`.
      Phase: P0

### UI — dialogs first, then the main window assembles them

- [ ] T18 — Manual install dialog (`ui/dialogs/manual_install.py`)
      Acceptance: `ManualInstallDialog` shows missing item, min version, reason, and a copyable read-only QLineEdit with the search string. Copy is primary, Close is secondary.
      Phase: P0

- [ ] T19 — Pending installs dialog (`ui/dialogs/pending_installs.py`)
      Acceptance: `PendingInstallsDialog` displays a checkbox list with per-item progress; "Install selected" triggers the loop. Backed by `QueuedInstaller`.
      Phase: P0

- [ ] T20 — Settings dialog (`ui/settings_dialog.py`)
      Acceptance: fields for output dir, working dir, track template, disc template, read offset, whipper/metaflac paths, auto-launch-Picard toggle. Writes through `config.py`. Includes a "Check dependencies" button that re-runs `DependencyManager.check_all()`.
      Phase: P0

- [ ] T21 — Drive picker widget (`ui/drive_picker.py`)
      Acceptance: combo box populated from `WhipperBackend.list_drives()`. Emits `drive_changed(device_path)`.
      Phase: P0

- [ ] T22 — Disc info panel (`ui/disc_info_panel.py`)
      Acceptance: read-only panel showing TOC, MB match status, AccurateRip availability. Updates on `drive_changed`.
      Phase: P0

- [ ] T23 — Release picker dialog (`ui/release_picker.py`)
      Acceptance: `ReleasePickerDialog` lists MB release candidates; returns the chosen MBID. Substitutes for whipper's TTY prompt (Critical Rule #5).
      Phase: P0

- [ ] T24 — Track table widget (`ui/track_table.py`)
      Acceptance: editable per-track `QTableView` with custom model. Album-level fields above the table. Validates before allowing rip start.
      Phase: P0

- [ ] T25 — Rip controls widget (`ui/rip_controls.py`)
      Acceptance: Start / Cancel buttons. On Start, assembles rip parameters and emits `rip_requested(params)`.
      Phase: P0

- [ ] T26 — Rip progress widget (`ui/rip_progress.py`)
      Acceptance: live whipper stdout pane + per-track AccurateRip results table populated when the rip finishes + "View log" button.
      Phase: P0

- [ ] T27 — Unknown album helper (`ui/unknown_album.py`)
      Acceptance: triggers `--unknown` rip, applies placeholder tags via `MetaflacAdapter`, optionally invokes `flatpak run org.musicbrainz.Picard`.
      Phase: P0

- [ ] T28 — Main window (`ui/main_window.py`)
      Acceptance: `MainWindow` lays out drive picker → disc info → track table → rip controls → progress. Menu: Settings, Check Dependencies, Quit. Wires worker signals into widget slots.
      Phase: P0

- [ ] T29 — App entry point + startup sequence (`app.py`, `__main__.py`)
      Acceptance: `app.main()` builds QApplication, configures logging, runs `DependencyManager.check_all()` (showing any install dialogs first), then constructs and shows MainWindow.
      Phase: P0

### Build + smoke test

- [ ] T30 — Test harness scaffold (`tests/conftest.py`, fixtures dir)
      Acceptance: `pytest` runs from repo root with no errors (even with no tests yet). conftest exposes any shared fixtures.
      Phase: P0

- [ ] T31 — python-appimage build harness (`build/build_appimage.sh`, `build/python-appimage/requirements.txt`)
      Acceptance: running `bash build/build_appimage.sh` from repo root produces `whipper-gui-x86_64.AppImage` at the repo root. Build is reproducible (no `git rev-parse`-time state baked in beyond the package version).
      Phase: P0

- [ ] T32 — End-to-end smoke test on Bazzite
      Acceptance: built AppImage launches; dependency check passes (or correctly surfaces missing items through the three tiers); a real audio CD rips end-to-end with AccurateRip results displayed. Resolves the open question in KDD-06 (is libdiscid actually needed on the host?).
      Phase: P0

---

## P1 — backlog (do not start until P0 ships)

These are fenced off so they don't accidentally interleave with P0 work. Each becomes a T## task only after P0 v1 is released.

- Eject button + auto-eject toggle
- Multi-disc queue
- Live progress bars per track
- Multi-drive support
- udev-driven auto-detect on disc insert
- ReplayGain calculation
- Auto-move completed rips to a library folder
- Additional encoding outputs: **MP3** (via `lame`) and **WAV** (via `sox` or whipper-native). Both encoder backends MUST be detected and offered through the existing P0 #11 dependency-resolution flow — no bespoke install code.

---

## Out of scope (not in P0, not in P1)

From the brief — listed here for clarity so they don't sneak in:

- Replacing whipper itself
- AccurateRip submission (confirmed Linux ecosystem gap)
- CTDB verification (confirmed Linux ecosystem gap)
- "Test & Copy" dual-pass
- Network features (NAS, Plex, Jellyfin, cloud)
- Library/catalog database
- DVD/Blu-ray support
- Windows or macOS support
