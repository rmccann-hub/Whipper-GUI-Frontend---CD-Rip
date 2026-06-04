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

- [x] T01 — Repo scaffolding
      Acceptance: `pyproject.toml`, `.gitignore`, `src/whipper_gui/__init__.py` (with `__version__`), `src/whipper_gui/__main__.py` (calls `app.main`), empty `tests/`, empty `build/` directory exist. `python -m whipper_gui` runs and exits cleanly with a placeholder message.
      Phase: P0
      Done: pyproject.toml uses setuptools src-layout; `app.py` carries a placeholder `main()` so the entry point is real. Verified `PYTHONPATH=src python -m whipper_gui` exits 0 with the placeholder message on Python 3.11.15.

- [x] T02 — Paths module (`paths.py`)
      Acceptance: module-level constants `CONFIG_PATH`, `LOG_DIR`, `WHIPPER_CONFIG_PATH`, `WHIPPER_BINARY_DEFAULT` populated from XDG env vars with sane fallbacks. Used by `config.py` and `logging_setup.py`.
      Phase: P0
      Done: paths.py exports the constants above plus `APP_NAME`, `CONFIG_DIR`, `LOG_PATH`. Honors `XDG_CONFIG_HOME` and `XDG_DATA_HOME` when set; falls back to `~/.config` and `~/.local/share`. Verified: setting XDG vars to `/tmp/...` produces matching `CONFIG_PATH` and `LOG_PATH`. Note: T02 and T03 were swapped from the original ordering (logging depended on paths), so this is the original T03.

- [x] T03 — Logging setup module (`logging_setup.py`)
      Acceptance: importing and calling `configure_logging()` once produces a rotating file at `~/.local/share/whipper-gui/log.txt` plus a console handler at INFO. `logging.getLogger(__name__)` in any module writes to both.
      Phase: P0
      Done: `configure_logging()` is idempotent (sentinel attr on root logger); file handler captures DEBUG+, console handler captures INFO+ (configurable). Rotation: 5 backups of 1 MiB. Verified: three calls produce exactly two handlers, INFO+DEBUG land in the file, only INFO on stderr.

- [x] T04 — TOML config module (`config.py`)
      Acceptance: `load_config()` returns the parsed TOML as a typed dataclass, creating the file with defaults if missing. `save_config(cfg)` atomically writes (temp + rename). Schema version embedded. Unit-tested in `tests/test_config.py`.
      Phase: P0
      Done: `Config` dataclass with output dirs, rip templates, tool paths, read_offset, auto_launch_picard, and schema_version. `load()` and `save()` (renamed from `load_config`/`save_config` for brevity — caller writes `config.load()`). Atomic save via temp + os.replace. Unknown keys dropped with warning. 4 unit tests pass (defaults creation, roundtrip, atomic temp cleanup, unknown-key tolerance).

### Dependency self-management subsystem (brief P0 #11)

- [x] T05 — Version-string parsing utility (`deps/version.py`)
      Acceptance: `parse_version(text, pattern)` and `meets_minimum(version, minimum)` exist. Unit-tested.
      Phase: P0
      Done: `parse_version()` uses a named-group regex (default matches `MAJOR.MINOR[.PATCH]`) and returns an int tuple or None. `meets_minimum()` pads short tuples with zeros so `(1, 2)` >= `(1, 2, 0)`. 12 tests pass including the "0.10.0" double-digit trap. Created `src/whipper_gui/deps/__init__.py` to make the package importable.

- [x] T06 — Probe functions (`deps/checks.py`)
      Acceptance: `check_whipper()`, `check_metaflac()`, `check_libdiscid()`, `check_picard_flatpak()`, `check_python_pkg(name)` each return a `ProbeResult(present, version, location)`. No side effects.
      Phase: P0
      Done: All five probes implemented. `ProbeResult` is a frozen dataclass with `present`, `version`, `location`, `raw_output`. Subprocess probes use a 10s timeout. `check_libdiscid()` uses ctypes (no subprocess). 10 unit tests pass via monkeypatched subprocess.run/shutil.which.

- [x] T07 — DependencySpec registry (`deps/registry.py`)
      Acceptance: `SPECS: list[DependencySpec]` declaratively lists all v1 deps (whipper, metaflac, libdiscid, musicbrainzngs, Picard). Each spec names probe, min_version, tier preference, install command, and tier-(c) search string.
      Phase: P0
      Done: 4 specs registered: whipper (manual, 0.10.0+), metaflac (manual, 1.3.0+), Picard (auto via Flatpak with queued/manual fallbacks), musicbrainzngs (manual reinstall path). `libdiscid` deferred to T32 per KDD-06; when the smoke test shows we need it, one new entry lands here and nothing else changes. `Tier` is an enum with AUTO/QUEUED/MANUAL; `DependencySpec` is frozen with an optional `fallback_tiers` tuple for cascade-on-failure.

- [x] T08 — Resolver classes (`deps/resolvers.py`)
      Acceptance: `AutoInstaller`, `QueuedInstaller`, `ManualPrompt` exist with a common `resolve(specs)` shape. AutoInstaller runs pipx and `flatpak install --user`. QueuedInstaller and ManualPrompt drive UI dialogs (defer wiring until T18/T19 land).
      Phase: P0
      Done: All three resolvers share `resolve(items: list[MissingItem]) -> list[InstallResult]`. AutoInstaller runs the spec's `install_command` via subprocess after a consent callback (default refuses). QueuedInstaller reuses AutoInstaller's machinery for the actual install — the dialog callback just chooses which items to install. ManualPrompt invokes a per-item callback and returns `success=False` for every item. All callbacks have logging-only defaults; T18/T19 will inject the Qt dialogs. 8 unit tests pass. Acceptance criterion corrected: dialog wiring is T18 (manual_install) and T19 (pending_installs), not T15/T16.

- [x] T09 — DependencyManager orchestrator (`deps/manager.py`)
      Acceptance: `DependencyManager.check_all()` walks the registry, classifies, dispatches to resolvers, returns a `DependencyReport`. Idempotent. Unit-tested with mocked probes in `tests/test_dependency_manager.py`.
      Phase: P0
      Done: `DependencyManager` accepts injected resolvers and an optional spec list (defaults to `registry.SPECS`). `check_all()` is pure (no resolution); `resolve_missing(report)` dispatches by tier and cascades to `spec.fallback_tiers` on failure. `DependencyReport.all_resolved` summarizes status. 9 unit tests pass, including a no-args construction that exercises the real registry against the live system. Test file is `tests/test_deps_manager.py` (kept consistent with the test naming pattern `test_deps_*.py`).

### Parsers

- [x] T10 — Drive list parser (`parsers/drive_list.py`)
      Acceptance: `parse_drive_list(stdout)` returns `list[DriveDescriptor]`. Fixture-driven test with sample `whipper drive list` output.
      Phase: P0
      Done: `parse_drive_list()` returns `list[DriveDescriptor]` with `device`, `vendor`, `model`, `release`, `read_offset` (None if unconfigured), `cache_defeat` (None if unknown). Format verified against whipper-team/whipper master `command/drive.py`. 4 fixture files in `tests/fixtures/`; 7 tests pass. Note: T10-T15 reordered so parsers come before adapters — the adapter at T13 imports from parsers, so swapping made the dependency order match the execution order.

- [x] T11 — CD info parser (`parsers/cd_info.py`)
      Acceptance: `parse_cd_info(stdout)` returns `DiscInfo`. Fixture-driven test.
      Phase: P0
      Done: `DiscInfo(cddb_disc_id, musicbrainz_disc_id, musicbrainz_submit_url)`; missing fields default to empty strings. Three regexes (with named groups) match the inconsistent "CDDB disc id:" / "MusicBrainz disc id" (no colon!) / "MusicBrainz lookup URL" lines whipper emits per master `command/cd.py`. Tolerates surrounding log noise. 2 fixture files, 4 tests pass.

- [x] T12 — Rip log parser (`parsers/rip_log.py`)
      Acceptance: `parse_rip_log(text)` returns a `RipLog` with per-track CRCs, AccurateRip confidence, error counts. Fixture-driven test with at least one real whipper `.log`.
      Phase: P0
      Done: State-machine parser produces `RipLog{log_creator, creation_date, ripping_info, tracks, accuraterip_summary, health_status, sha256_hash}`. Each `TrackResult` holds peak_level, pre_emphasis, extraction_speed/quality, test/copy CRCs, status, and AR v1/v2 results. New `RippingInfo` sub-record (drive, extraction_engine, defeat_audio_cache, read_offset_correction, overread_lead_out, gap_detection, cd_r_detected) mirrors EAC's archival header per docs/log-format-comparison.md. **Primary fixture is the real whipper log from upstream's own test suite** (`tests/fixtures/rip_log_real_whipper_0_7.log`). My initial hand-authored fixture had a wrong track-header format and was deleted. EAC reference log (`rip_log_eac_reference.log`) stored for archival comparison only; not parsed. 18 tests pass.

### Adapters

- [x] T13 — WhipperBackend ABC + host-exported impl (`adapters/whipper_backend.py`)
      Acceptance: `WhipperBackend` ABC with all five methods from PLANNING.md §5. `WhipperHostExportedImpl` shells out to `~/.local/bin/whipper`. Tested with fixture-driven mocks in `tests/test_whipper_backend.py`.
      Phase: P0
      Done: `WhipperBackend` ABC with four methods (`list_drives`, `disc_info`, `rip`, `version`) — PLANNING.md §5 listed "five methods" inclusive of the rip-returned `RipHandle`'s methods, which now live on the handle class. `WhipperHostExportedImpl` accepts `binary_path` and optional `working_dir`, shells out to whipper, parses via `parsers.drive_list` / `parsers.cd_info`. `RipHandle` wraps the Popen, exposes `log_lines()` (generator), `wait()`, `cancel()` (SIGTERM-then-SIGKILL), and `returncode`. `WhipperError` carries the last error line for the GUI. 13 tests pass: argv construction, `--unknown` flag, working_dir presence/absence, log-line streaming, cancel cascade, post-exit cancel safety, ABC discipline, FileNotFoundError + TimeoutExpired handling.

- [x] T14 — MusicBrainzClient ABC + ngs impl (`adapters/musicbrainz_client.py`)
      Acceptance: ABC per PLANNING.md §6. `MusicBrainzNgsImpl` wraps `musicbrainzngs`. `set_user_agent` invoked at construction. Exceptions reraised as `MusicBrainzQueryError`. Tested with `musicbrainzngs` mocked.
      Phase: P0
      Done: ABC + impl with 4 methods (`releases_by_disc_id`, `releases_by_toc`, `release_by_mbid`, `set_user_agent`). Data types: `TocSignature`, `ReleaseSummary`, `TrackSummary`, `ReleaseDetail` — all frozen dataclasses. `MusicBrainzQueryError` wraps `musicbrainzngs.WebServiceError`; 404 responses on disc-id/TOC queries are translated to `[]` (since "no match" isn't an error from the picker UI's perspective). MB response shape helpers isolated as private functions so a future `RequestsJsonImpl` against MB's JSON endpoint can produce the same dataclasses. 13 tests pass, including artist-credit rendering (which interleaves dicts and joining strings like " feat. ").

- [x] T15 — Metaflac adapter (`adapters/metaflac.py`)
      Acceptance: `MetaflacAdapter.write_tags(flac_path, tags)` and `.read_tags(flac_path)` work via the `metaflac` CLI. Used by the unknown-album flow.
      Phase: P0
      Done: `MetaflacAdapter` constructor takes a `binary_name` (default "metaflac"; user can override via config). `read_tags()` uses `--export-tags-to=-` and parses `KEY=VALUE` lines (duplicate keys → last value wins, matching metaflac's own preference). `write_tags()` batches `--remove-tag=K` followed by `--set-tag=K=V` so existing values are replaced not duplicated. Empty dict is a no-op. `MetaflacError` carries the last stderr line. 9 unit tests cover all three methods plus FileNotFoundError, TimeoutExpired, and custom binary paths.

### Workers

- [x] T16 — Rip worker (`workers/rip_worker.py`)
      Acceptance: `RipWorker(QObject)` owns the rip subprocess; emits `log_line`, `progress`, `finished`, `error`. `.cancel()` terminates cleanly.
      Phase: P0
      Done: `RipWorker` QObject + frozen `RipParameters` dataclass. Signals: `log_line(str)`, `progress(int track, float percent)`, `finished(bool success, str log_path)`, `error(str)`. `start_rip` slot drives `WhipperBackend.rip()`, iterates `RipHandle.log_lines()`, emits progress when defensive regex matches. `cancel` slot is safe to call before start (just sets the flag) and after (forwards to handle). `_find_log_path()` locates the most recent `.log` under `output_dir` for the finished signal. 12 unit tests pass with a fake backend + handle. Progress regex deliberately permissive — T32 smoke test will tell us whether it needs tightening for real whipper output.

- [x] T17 — MusicBrainz worker (`workers/mb_worker.py`)
      Acceptance: `MusicBrainzWorker(QObject)` runs `MusicBrainzClient` calls on a background `QThread`; emits `releases_returned` or `error`.
      Phase: P0
      Done: `MusicBrainzWorker` exposes three slots — `lookup_disc_id(str)`, `lookup_toc(TocSignature)`, `fetch_release(str mbid)` — emitting `releases_returned(list)` for multi-result queries, `release_returned(object)` for the single-release fetch (using `object` so PySide doesn't require an explicit type registration for the ReleaseDetail dataclass), and `error(str)` on any `MusicBrainzQueryError`. One worker handles all three query types; slot serialization ensures queries don't interleave. 7 unit tests pass with a fake MusicBrainzClient covering success, error, and empty-result paths for all three slots.

### UI — dialogs first, then the main window assembles them

- [x] T18 — Manual install dialog (`ui/dialogs/manual_install.py`)
      Acceptance: `ManualInstallDialog` shows missing item, min version, reason, and a copyable read-only QLineEdit with the search string. Copy is primary, Close is secondary.
      Phase: P0
      Done: Modal `ManualInstallDialog(spec, probe)` with title "Install required: {name}", form rows for required version / current state / why-manual, a read-only QLineEdit carrying the search string, and a button box with Copy (AcceptRole, default) + Close (RejectRole). Copy writes to the system clipboard and briefly flips the button label to "Copied!" before resetting via QTimer. Display strings handle the "any version" floor `(0,0,0)` and the "installed but version unknown" probe state. 12 unit tests pass with the QApplication fixture from `tests/conftest.py` (added this commit, anticipates T30). Test environment runs with QT_QPA_PLATFORM=offscreen so a real display isn't required.

- [x] T19 — Pending installs dialog (`ui/dialogs/pending_installs.py`)
      Acceptance: `PendingInstallsDialog` displays a checkbox list with per-item progress; "Install selected" triggers the loop. Backed by `QueuedInstaller`.
      Phase: P0
      Done: Modal `PendingInstallsDialog(items)` renders one row per item (checkbox + name + min-version hint + status label). Default-checked so a "one click installs everything" flow works. `install_requested` signal fires on Install Selected click (dialog stays open during install). Caller drives the install loop and updates per-row state via `mark_in_progress(dep_id)` / `mark_result(dep_id, success, message)` (failure messages truncate to 60 chars to keep the dialog compact). `set_install_phase_active(True)` locks down the picker during installs; `show_close_button()` (idempotent) swaps the bottom row to a single Close button for dismissal. 19 unit tests cover construction, selection, signal emission, status updates, long-message truncation, lockdown, and the close-button swap.

- [x] T20 — Settings dialog (`ui/settings_dialog.py`)
      Acceptance: fields for output dir, working dir, track template, disc template, read offset, whipper/metaflac paths, auto-launch-Picard toggle. Writes through `config.py`. Includes a "Check dependencies" button that re-runs `DependencyManager.check_all()`.
      Phase: P0
      Done: Modal `SettingsDialog(config)` is a pure view — it doesn't read or write the config file. Form rows for all eight Config attributes (paths get a Browse… button; read_offset is a bounded QSpinBox; auto-launch-Picard is a checkbox). `to_config()` builds a new `Config` reflecting widget state and preserves the incoming `schema_version` (the dialog doesn't model migration). "Check dependencies" button emits `check_dependencies_requested` signal — caller wires it to `DependencyManager.check_all()`. Dialog stays open after the signal so the user can see results in a separate report and tweak settings. 11 unit tests pass. Also consolidated worker-test fixtures onto `qapp` (from conftest.py) since a process-wide QCoreApplication blocks later UI tests from creating QApplication.

- [x] T21 — Drive picker widget (`ui/drive_picker.py`)
      Acceptance: combo box populated from `WhipperBackend.list_drives()`. Emits `drive_changed(device_path)`.
      Phase: P0
      Done: `DrivePicker(backend)` is a horizontal panel: label + QComboBox + Refresh button. Construction does NOT call list_drives — the caller decides when (avoids surprise subprocess calls during widget construction). `refresh()` rebuilds the combo, preserves the prior selection if the same device is still present, falls back to the first drive otherwise. Errors from the backend show as an "(error: …)" placeholder rather than crashing — user can fix the path in Settings and refresh again. `drive_changed` emits exactly once per real selection change (signal-blocked during repopulation). 10 unit tests pass.

- [x] T22 — Disc info panel (`ui/disc_info_panel.py`)
      Acceptance: read-only panel showing TOC, MB match status, AccurateRip availability. Updates on `drive_changed`.
      Phase: P0
      Done: `DiscInfoPanel` is a pure view with five form rows: Drive, MusicBrainz disc ID, CDDB disc ID, MusicBrainz match, AccurateRip. Setter methods (`set_drive`, `set_disc_info_loading`, `set_disc_info`, `set_disc_info_error`, `set_mb_loading`, `set_mb_matches`, `set_mb_error`) — the main window orchestrates the disc_info + MB lookup workers and feeds results in. `set_drive()` clears all disc-derived fields so switching drives never leaks stale data. Value labels are mouse-selectable so users can copy disc IDs into Picard or a browser. Acceptance differs from spec in two ways flagged for review: (1) TOC isn't in `whipper cd info` output (only in the post-rip log), so the panel can't show it pre-rip — TOC display will appear in rip-progress (T26); (2) AccurateRip availability is also only checked during rip, so this panel shows a "verified during rip" placeholder and the actual results appear in T26. 15 unit tests pass.

- [x] T23 — Release picker dialog (`ui/release_picker.py`)
      Acceptance: `ReleasePickerDialog` lists MB release candidates; returns the chosen MBID. Substitutes for whipper's TTY prompt (Critical Rule #5).
      Phase: P0
      Done: Modal `ReleasePickerDialog(releases)` displays a 9-column QTableWidget (Title, Artist, Year, Country, Label, Catalog #, Tracks, Format, Notes). Row-level single selection, no in-place editing. Title and Artist columns stretch; the rest fit content. Row 0 is selected by default so a quick Enter accepts the top candidate. Double-click on a row also accepts (matches OS picker convention). `selected_mbid()` and `selected_release()` are the readback API. Empty release list is supported and returns None for both. 15 unit tests cover construction, row count, column mapping (each ReleaseSummary attribute → correct cell), missing-field rendering, non-editable cells, default selection, MBID readback, OK/Cancel/double-click acceptance paths.

- [x] T24 — Track table widget (`ui/track_table.py`)
      Acceptance: editable per-track `QTableView` with custom model. Album-level fields above the table. Validates before allowing rip start.
      Phase: P0
      Done: Composite widget with three album-level QLineEdits (artist/title/year) above a QTableView. Custom `TrackTableModel(QAbstractTableModel)` exposes 4 columns (#, Title, Artist, Length); Title and Artist are editable in-place, # and Length are read-only. Track length renders as MM:SS. `set_release(detail)` populates from MusicBrainz; `album_metadata()` and `tracks()` read back user edits (TrackSummary is frozen, so edits go through `dataclasses.replace`). `validate()` returns `(ok, message)` after checking that album artist/title aren't blank, at least one track exists, and every track has a title. `AlbumMetadata` frozen dataclass exposes the album-level edits. 22 unit tests pass (model behavior, editability flags, length formatting, set/clear/edit roundtrips, all four validate failure paths).

- [x] T25 — Rip controls widget (`ui/rip_controls.py`)
      Acceptance: Start / Cancel buttons. On Start, assembles rip parameters and emits `rip_requested(params)`.
      Phase: P0
      Done: `RipControls(config)` exposes Start + Cancel buttons. Three setter slots (`set_drive`, `set_release_id`, `set_unknown_mode`) accept state pushed in from the main window; `set_rip_active(bool)` toggles button enablement during a rip. Start enables when drive + release_id are present (or just drive in unknown mode). On Start click, assembles a `RipParameters` from current state + the injected `Config` (output_dir, templates) and emits `rip_requested(params)`. On Cancel click, emits `cancel_requested()`. 10 unit tests cover initial disabled state, enablement rules (with/without release_id, unknown mode, no drive), rip-active toggling, parameter assembly, unknown-flag passthrough, cancel signal, and state-clearing.

- [x] T26 — Rip progress widget (`ui/rip_progress.py`)
      Acceptance: live whipper stdout pane + per-track AccurateRip results table populated when the rip finishes + "View log" button.
      Phase: P0
      Done: Stacked vertical panel — status label + QProgressBar (0-100), streaming read-only QPlainTextEdit (capped at 10k scrollback lines so a long rip can't blow memory), AccurateRip results QTableWidget (5 cols: #, Title, Status, AR v1, AR v2), and "View log" button. Methods: `clear()`, `append_log_line(line)`, `set_progress(track, percent)`, `set_status(text)`, `set_rip_log(RipLog)`, `set_log_path(path|None)`. AR cells render as "OK (N)" / "not in DB" / "—" based on result+confidence. View Log button opens the log via `QDesktopServices.openUrl` (injectable for tests). 16 unit tests pass.

- [x] T27 — Unknown album helper (`ui/unknown_album.py`)
      Acceptance: triggers `--unknown` rip, applies placeholder tags via `MetaflacAdapter`, optionally invokes `flatpak run org.musicbrainz.Picard`.
      Phase: P0
      Done: Three pieces — `UnknownAlbumDialog(auto_launch_picard_default)` modal confirmation with a Picard toggle, `apply_placeholder_tags(metaflac, flac_files)` applying `Track NN` / Unknown Artist / Unknown Album / TRACKNUMBER per file (returns successes; individual failures logged but don't abort the batch), `launch_picard_for(folder)` running `flatpak run org.musicbrainz.Picard <folder>` as a detached subprocess (returns False on FileNotFoundError or OSError so the main window can surface a hint to install Picard). The actual `--unknown` rip is kicked off by the main window via `RipControls.set_unknown_mode(True)` + Start; this module is only the dialog + post-rip helpers. 11 unit tests pass.

- [x] T28 — Main window (`ui/main_window.py`)
      Acceptance: `MainWindow` lays out drive picker → disc info → track table → rip controls → progress. Menu: Settings, Check Dependencies, Quit. Wires worker signals into widget slots.
      Phase: P0
      Done: `MainWindow(config, backend, mb_client, metaflac, dependency_manager, save_config=None)` composes the entire GUI. Layout: drive picker → disc info → track table → rip controls → progress in a QVBoxLayout. Menu bar: File→Quit, Tools→Settings…, Tools→Check dependencies…. One persistent QThread holds the MusicBrainzWorker for the window's lifetime; each rip spawns a new QThread/RipWorker that auto-cleans on finish. Drive change triggers `backend.disc_info()` (sync) → panel update → MB worker `lookup_disc_id` → on result, single match fetches detail, multiple opens `ReleasePickerDialog`. Validation gate on rip start (`TrackTable.validate()`) blocks invalid metadata in non-unknown mode. Settings dialog wires its "Check dependencies" signal back to the main window's `_on_check_dependencies` so both entry points use the same code. The dep-check builds a fresh DependencyManager with GUI-backed resolvers (`QMessageBox.question` for auto-consent, `PendingInstallsDialog` for tier-b, `ManualInstallDialog` for tier-c) and runs `check_all` + `resolve_missing`. closeEvent tears down the MB thread and cancels any in-progress rip. Rip log is parsed and rendered into `RipProgress` after the rip finishes. 10 integration-flavored tests pass.

- [x] T29 — App entry point + startup sequence (`app.py`, `__main__.py`)
      Acceptance: `app.main()` builds QApplication, configures logging, runs `DependencyManager.check_all()` (showing any install dialogs first), then constructs and shows MainWindow.
      Phase: P0
      Done: `app.main(argv)` parses `--version` via argparse, configures logging, loads config, constructs QApplication (with name/version/org for QSettings), instantiates all adapter layers (`WhipperHostExportedImpl`, `MusicBrainzNgsImpl`, `MetaflacAdapter`, `DependencyManager`), creates the `MainWindow`, runs `window.run_dependency_check(show_summary=False)` for the launch-time check (silent when nothing's missing; modal dialogs surface for anything that needs attention), shows the window, and calls `refresh_drives()` after show so the user sees the window immediately even if the subprocess takes a moment. `MainWindow.run_dependency_check(show_summary)` is the refactored entry point both the launch sequence and the Tools → Check Dependencies menu use. 4 tests cover --version exit code, version string, unknown-flag error, and module importability without side effects.

### Build + smoke test

- [x] T30 — Test harness scaffold (`tests/conftest.py`, fixtures dir)
      Acceptance: `pytest` runs from repo root with no errors (even with no tests yet). conftest exposes any shared fixtures.
      Phase: P0
      Done: `tests/conftest.py` was created in T18 with the session-scoped `qapp` QApplication fixture (offscreen Qt platform set before any Qt import). This task ratifies that scaffold: adds `[tool.pytest.ini_options]` to `pyproject.toml` (testpaths=tests, pythonpath=src so PYTHONPATH no longer needs to be set manually, addopts=-q --strict-markers) and writes `tests/fixtures/README.md` documenting each fixture's provenance (notably that `rip_log_real_whipper_0_7.log` is pulled verbatim from upstream and `rip_log_eac_reference.log` exists only for the format comparison). `python3 -m pytest` from the repo root now works without any extra env vars.

- [x] T31 — python-appimage build harness (`build/build_appimage.sh`, `build/python-appimage/requirements.txt`)
      Acceptance: running `bash build/build_appimage.sh` from repo root produces `whipper-gui-x86_64.AppImage` at the repo root. Build is reproducible (no `git rev-parse`-time state baked in beyond the package version).
      Phase: P0
      Done: `build/build_appimage.sh` checks prerequisites (python3, `build`, `python-appimage`), builds a wheel from local source via `python -m build`, drops it next to the recipe so pip resolves `whipper-gui` to the local wheel rather than PyPI, generates a 16×16 placeholder icon if no real one is present (using a hand-rolled PNG generator with no external deps), and invokes `python -m python_appimage build app build/python-appimage/`. Recipe directory has `requirements.txt` (pinned to DEPENDENCIES.md), `entrypoint.sh` (executable script that runs `python -m whipper_gui` from the bundled interpreter), `whipper-gui.desktop` (KDE/freedesktop standard), and `README.md`. Build-harness unit tests verify the recipe structure, executable bits, the desktop file shape, the local-wheel self-install pattern, and that the pinned versions match DEPENDENCIES.md.
      **Build verified end-to-end 2026-05-29 (during T32), which surfaced five recipe bugs the unit tests couldn't catch — all now fixed + guarded by new regression tests:**
        1. **`--find-links .` in requirements.txt doesn't work** — python-appimage runs `pip install` once per line from a temp dir, so a standalone option line becomes its own argument-less install. Replaced with `PIP_FIND_LINKS=<recipe dir>` exported by the build script (a pip env var, so it survives pip's `-I` isolated mode).
        2. **`<`/`>` in version pins crash the build** — python-appimage's `system()` does `' '.join(args)` + `shell=True`, so `,<7` is read as a shell redirection ("cannot open 7"). Switched the bounds to the equivalent `~=` operator (`PySide6~=6.7`, `tomli-w~=1.0`).
        3. **`entrypoint` was never bundled** — python-appimage globs `entrypoint.*`, so an extensionless file is ignored and the default AppRun runs the bare interpreter (`--version` printed Python's version). Renamed to `entrypoint.sh`.
        4. **A space in the `.desktop` `Name=` field** ("Whipper GUI") breaks the unquoted appimagetool command, so the output file is silently never produced. Renamed to `Whipper-GUI`; the build script normalises the artifact to the canonical `whipper-gui-x86_64.AppImage`.
        5. **No offline/rate-limit path** — python-appimage hits the GitHub API to fetch the CPython base image, which 403s when unauthenticated-rate-limited. Added an optional `WHIPPER_GUI_BASE_IMAGE` escape hatch to feed a pre-downloaded base image and skip the API. (FUSE-less build hosts also need `APPIMAGE_EXTRACT_AND_RUN=1` for appimagetool.)

- [x] T32 — End-to-end smoke test on Bazzite
      Acceptance: built AppImage launches; dependency check passes (or correctly surfaces missing items through the three tiers); a real audio CD rips end-to-end with AccurateRip results displayed. Resolves the open question in KDD-06 (is libdiscid actually needed on the host?).
      Phase: P0
      Progress (2026-05-29): **Rip pipeline verified end-to-end** on the user's Bazzite + Distrobox + Pioneer BDR-209D with a 16-track CD-R. All tracks ripped, every Test CRC == Copy CRC, "Rip quality 100.00%", "No errors occurred"; FLACs play; `.log`/`.cue`/`.m3u`/`.toc` written; AccurateRip queried and correctly reported "not in DB" (CD-R). **KDD-06 resolved: libdiscid is NOT needed on the host** — whipper (in the container) computes the disc ID and `cd info`/the rip expose it; the GUI never touched libdiscid. **KDD-13 questions answered:** whipper writes a `.cue` (and `.m3u`/`.toc`) next to the FLACs, and captures ISRC/UPC slots (all-zero on this CD-R). Bugs found + fixed this session: CD-R guard (`--cdr`), missing working-dir mkdir, empty track table, frozen pre-track status, blank placeholder rows, default naming template. **AppImage now builds, launches, and self-initialises** (verified 2026-05-29): `bash build/build_appimage.sh` produces `whipper-gui-x86_64.AppImage`; `--version` prints `whipper-gui 0.0.1`; a headless (`QT_QPA_PLATFORM=offscreen`) launch brings up the Qt event loop with config created, the MusicBrainz adapter initialised, and the dependency manager probing all four registered deps (host-side whipper/metaflac/flatpak correctly report absent — they live on the host by design; bundled musicbrainzngs reports present). Five build-recipe bugs found + fixed getting there (see build-harness task above). **DONE 2026-05-30: a full 16-track rip completed *through the AppImage* on Bazzite** — `success=True`, every Test CRC == Copy CRC, "Health status: No errors occurred", FLAC/.cue/.m3u/.toc all written to `Unknown Artist/Unknown Album/`. That was the last acceptance criterion; T32 is complete. One AppImage-only bug surfaced and was fixed in the same pass: the bundled (manylinux) CPython ships no CA certificates, so every MusicBrainz HTTPS lookup failed with `CERTIFICATE_VERIFY_FAILED` (disc identification silently broken in the distributed build, even though the editable install worked). Fix: `entrypoint.sh` now points `SSL_CERT_FILE`/`SSL_CERT_DIR` at the host CA bundle (covers Fedora/Bazzite, Debian/Ubuntu, Arch/openSUSE, Alpine layouts); verified the bundled interpreter then completes an HTTPS request to musicbrainz.org. Also from this round of real-use feedback: two-tier progress (overall + current-task bars; the overall bar is monotonic and the pre-track disc scan now animates) and a fidelity summary on the status line ("Done — all N tracks verified, Test/Copy CRCs match") so the user can confirm a secure rip without opening the log.

---

## P1 — backlog (do not start until P0 ships)

These are fenced off so they don't accidentally interleave with P0 work. Each becomes a T## task only after P0 v1 is released.

The sub-sections below are ordered by current priority for picking up work:

1. **P1.1 — Install / uninstall ease** is the **highest priority subset** of P1. Items here unblock new contributors at the install step; finish before anything else P1.
2. **P1 — Release milestones** — gating actions for v0.1.0. Merging to main, flipping the repo public, tagging the first release, publishing to PyPI. Most other P1 items remove caveats from the README once these are done.
3. **P1 — EAC bit-perfect parity gaps** — five small Settings widgets for whipper flags we don't yet expose. Should land before the first public AppImage.
4. **P1 — UX gaps from real-user testing** — issues surfaced on Bazzite that aren't urgent but make the GUI feel less polished.
5. **P1 — Install automation** — pre-clone host bootstrap script. Blocked on the repo flipping public.
6. **P1 — Documentation backlog** — items that need real-system output from T32 to write authoritatively.

**Ranked execution order (set 2026-05-30, after the "EAC successor" research review; updated 2026-06-02 after v0.1.0 shipped):**
1. **[x] Release milestones** (merge → public → tag `v0.1.0` → publish AppImage) — **done 2026-06-01.** v0.1.0 is live with the AppImage + installers attached. *(PyPI wheel publish: workflow shipped 2026-06-02 — see below. Needs a one-time PyPI Trusted-Publisher setup + a release tag to actually land on PyPI.)*
2. **[x] Drive setup wizard** (write-enabled; PLANNING.md KDD-15) — done 2026-05-30; see P1.1.
3. **[x] Drive-access permission diagnostics** — done 2026-05-30; see P1.1.
4. **[x] EAC parity-gap Settings widgets** (cover art / force-overread / max-retries / keep-going) — done 2026-05-30; below.
5. **[~] CTDB verify (read-only)** — Phase 1 of KDD-14. Library landed 2026-06-03; awaiting hardware validation. Clean-room client + verify logic shipped: `adapters/ctdb_client.py` (lookup), `ctdb/{toc,decode,crc,verify}.py`, and a standalone validation script `scripts/ctdb_verify.py`. 35 unit tests cover the deterministic parts (TOC math, URL build, XML parse, decode wrappers, verdict logic). **Two pieces are hardware-validation-gated (KDD-16): the `toc=` wire format and the bit-exact CRC** — both isolated behind a single seam, both fail *safe* (never a false "verified"). PCM decode uses host `flac` if present (optional dep, your call 2026-06-03). **Next: run [docs/test-plan.md](docs/test-plan.md) Test 1 on a real disc; then wire the GUI (Test 1b).**
6. **[ ] CTDB repair (parity, wrap `ctdb-cli`, explicit trigger)** — Phase 2 of KDD-14; the headline EAC++ differentiator. Note: `ctdb-cli` is .NET 10 (not C), so AppImage bundling is heavy — bundle-vs-optional-install is undecided.

*Downgraded:* Test & Copy dual-pass — whipper already emits a per-track Test CRC and Copy CRC, so the guarantee is already delivered (see P2).

High-level feature backlog (not bucketed into a sub-section because each is small):

- **[x] Eject button + auto-eject toggle. Done 2026-06-02.** Manual **Eject** button on the `DrivePicker` (emits `eject_requested(device)`; MainWindow ejects off a daemon thread via the existing `drive_control.eject_drive`, mirroring the force-stop pattern). New `Config.auto_eject_after_rip` (default off) + Settings checkbox; on a *successful* rip `_on_rip_finished` auto-ejects the just-ripped drive (skipped on failure/cancel so the disc stays in for a retry). User guide updated. Tests in `test_ui_drive_picker`, `test_ui_settings_dialog`, `test_config`, `test_ui_main_window`.
- **[ ]** Multi-disc queue
- **[ ]** Live progress bars per track
- **[ ]** Multi-drive support
- **[ ]** udev-driven auto-detect on disc insert
- **[ ]** ReplayGain calculation
- **[ ]** Auto-move completed rips to a library folder
- **[ ]** Additional encoding outputs: **MP3** (via `lame`) and **WAV** (via `sox` or whipper-native). Both encoder backends MUST be detected and offered through the existing P0 #11 dependency-resolution flow — no bespoke install code.

### P1 — EAC bit-perfect parity gaps

The following whipper CLI options exist but aren't currently surfaced in our Settings dialog. Each is a small addition: a Config field, a Settings widget, a `RipParameters` field, and a flag in `WhipperHostExportedImpl.rip()`. The reference for what "should" be exposed is the EAC bit-perfect guide audit in [PLANNING.md KDD-13](PLANNING.md).

- **[x] Cover art (embed + save).** Done 2026-05-30. Whipper's `-C/--cover-art` — **actual choices are `file|embed|complete`** (the earlier `none/embedded/file` guess was wrong; confirmed against `whipper/command/cd.py`). Settings dropdown maps "Don't fetch"→`""` (flag omitted), "Embed in FLAC"→`embed`, "Save as file"→`file`, "Embed and save file"→`complete`. **Behavior change:** `Config.cover_art` defaults to `embed` for EAC parity, so a rip now fetches art over the network by default (best-effort; an unidentified disc just gets none). `RipParameters.cover_art`; flag passthrough.
- **[x] Force overread into lead-out.** Done 2026-05-30. `-x/--force-overread`, default off. `Config.force_overread` + Settings toggle + `RipParameters.force_overread` + flag.
- **[x] Max retries.** Done 2026-05-30. `-r/--max-retries N`, default 5 (whipper's own). `Config.max_retries` + Settings spinbox (0–100) + `RipParameters.max_retries`; always passed (no-op at 5).
- **[x] Keep going on track failure.** Done 2026-05-30. `-k/--keep-going`, default off (a failure should surface, not silently skip). `Config.keep_going` + Settings toggle + `RipParameters.keep_going` + flag.
- **[x] Continue on CD-R.** Whipper's `--cdr` flag. Default off (CD-Rs are usually accidents in an archival workflow). Surface as a Settings toggle. **Done 2026-05-29 (pulled forward during T32):** the user's first real-hardware test disc turned out to be a burned CD-R, and whipper aborts with "inserted disc seems to be a CD-R, --cdr not passed". Added `Config.continue_on_cdr`, a "CD-R discs" toggle in the Settings dialog, `RipParameters.cdr`, and the `--cdr` flag passthrough in `WhipperHostExportedImpl.rip()`. Also added `RipControls.set_config()` so a Settings change reaches the next rip (previously the rip controls kept their construction-time Config — latent staleness that also affected output_dir/templates).

Each is independent; do them in any order. They should land before the AppImage's first public release so the GUI matches what EAC users expect.

> **CTDB verify + repair are tracked elsewhere, not here.** They are archival-verification *features*, not parity-gap Settings widgets, so they live in the **Ranked execution order** above (items 5–6) with full rationale and decisions in the [Upstream open-source modification](#p1p2--upstream-open-source-modification-for-eac-parity-investigation-2026-06-02) section and [docs/upstream-modification-investigation.md](docs/upstream-modification-investigation.md). See also [PLANNING.md KDD-12 / KDD-14 / KDD-16](PLANNING.md).

### P1 — Release milestones

These remove most of the README's "until X happens" caveats. Done in order, they collapse Method C's friction substantially.

- **[x] Merge `claude/lucid-babbage-JYI8c` into `main`.** Done 2026-05-30 (`--allow-unrelated-histories`; main previously held only `.gitattributes`). Fresh `git clone` now lands on a working state. Removed the README dev-branch/authenticate steps and the `dev-setup.sh` branch-guard.
- **[x] Flip the GitHub repo to Public.** Done 2026-05-30 by the user. Plain `git clone https://...` now works without `gh auth login` / SSH key setup. The LICENSE decision it was gated on is also resolved: **GPL-3.0-only** (KDD-10) — `LICENSE` committed, `pyproject.toml` classifier set, README updated. Follow-up: drop the README Method-C "private repo, authenticate first" blockquote (see Documentation backlog).
- **[x] Tag `v0.1.0` and publish the AppImage as a release asset. Done 2026-06-01.** The first public release is live: [v0.1.0](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/tag/v0.1.0) with `whipper-gui-x86_64.AppImage` (+ `.sha256`), `install.sh`, and `install-appimage.sh` all attached by `release.yml`. Both CI workflows (`ci.yml`, the new `appimage.yml`) and the release workflow are confirmed green on real Actions runs. Method A (AppImage) is now the recommended path. **Note:** the GitHub release got marked as a *full* release rather than a pre-release (UI default; `release.yml` only sets `--prerelease` when it *creates* the release, and this one was created in the UI). Cosmetic — flip it in the UI if a pre-release badge is wanted; future `git tag`-driven `v0.*` releases will auto-mark correctly.
      Earlier prep notes (2026-05-31): README rewritten for a published-AppImage world, `CHANGELOG.md` added, real app icon committed, release/CI workflows authored and YAML-validated.
- **[~] Publish the wheel to PyPI.** Promotes Method B. `pipx install whipper-gui` works for any technical user. **Workflow shipped 2026-06-02** (`.github/workflows/publish-pypi.yml`): builds wheel+sdist, `twine check`s them, and publishes via **Trusted Publishing (OIDC, no stored token)** when a release is published. Separate from `release.yml` so it can't block the AppImage. **Remaining (owner-only, can't be done from CI):** (1) one-time PyPI Trusted-Publisher config — project `whipper-gui`, owner `rmccann-hub`, repo `Whipper-GUI-Frontend---CD-Rip`, workflow `publish-pypi.yml`, environment `pypi` (steps in the workflow header); (2) cut a release tag so it actually lands on PyPI. Wheel+sdist verified to build + pass `twine check` locally.

### P1 — Install automation

The host-side setup (Distrobox, container, whipper, exports) currently lives only in the README's prose. A reproducible script would catch the same pitfalls we hit walking the user through (`python3-setuptools` dep, `:latest` image pull confirmation, distrobox-export needs container entry). The post-clone side is already covered by `dev-setup.sh`.

- **[x] `setup-host.sh`.** Done 2026-05-30. Automates README Steps 1-4 (ensure Distrobox per-distro, create the `ripping` container with `--yes`, `dnf install whipper flac python3-setuptools` in-container, `distrobox-export` both binaries) **plus** clone + `dev-setup.sh` (Step 7). Idempotent (each step checks state first), with `--dry-run` (prints every command, changes nothing), `--yes`, `--no-gui`, `--container`, `--image`. Detects whether it's running inside a checkout (uses it) or piped from `curl` (clones to `~/Whipper-GUI-Frontend---CD-Rip`). 7 smoke tests (`tests/test_setup_host_script.py`). **Untested against a real Distrobox host** — verified only via `--dry-run` + smoke tests in CI; needs a real-hardware run to confirm. Deliberately excludes drive calibration (GUI wizard) and Picard (GUI dependency manager).
- **[x] Document the curl-pipe-bash pattern** in the README as the "fast path" — done. The README quickstart leads with `curl -fsSL …/install.sh | bash` (and a download-then-run alternative); the manual Steps 1-4 are kept underneath as the source of truth.

### P1.1 — Install / uninstall ease (real-user testing)

Highest-priority subset of P1, focused specifically on the friction the first-time user hits between "no GUI installed" and "GUI running with a successful rip in hand." Items here unblock new contributors and reduce abandonment at the install step.

- **[x] Drive setup wizard (write-enabled) — top first-run priority.** Done 2026-05-30. Replaces the manual hand-edit of `whipper.conf` with a guided "Detect my drive" flow. `DriveSetupDialog` (Tools → "Set up drive…", and the Settings "Re-detect…" button) runs whipper's OWN `drive analyze` (cache) + `offset find` (offset) through the host-exported `~/.local/bin/whipper` on a worker thread (`DriveSetupWorker`), so they persist to `whipper.conf` themselves; we `back_up_whipper_config()` to `whipper.conf.bak` first. New adapter methods `analyze_drive()`/`find_offset()` (optional ABC capability — `NotImplementedError` default so non-whipper backends and test fakes still construct). Per-step failure is tolerated (a failed offset-find still reports the cache verdict). Also **fixed the "misleading read-offset field"**: it's read-only with the "Re-detect…" button beside it. Design: PLANNING.md **KDD-15**. 17 new tests.
  **Follow-ups:**
  - **[x] Manual-offset fallback — done 2026-05-31.** Real-user testing showed a fresh install with only CD-Rs is hard-blocked (whipper errors "drive offset unconfigured" and `offset find` needs an AccurateRip disc). The wizard now has a manual-entry spinbox + "Save offset" (linked to AccurateRip's offset list). It does **not** hand-author `whipper.conf` (still honouring KDD-15) — it persists via the GUI's existing `--offset` override (`Config.read_offset` + `override_read_offset`), emitted as `DriveSetupDialog.manual_offset_saved` and saved by the main window.
  - **[x] First-run auto-offer — done 2026-05-31.** On launch, if no offset is configured (new `offset_config.is_offset_configured()` checks `whipper.conf` *and* the override), the GUI offers the wizard once (dismissible; `Config.drive_setup_prompted` guards against re-nagging). Reversed the earlier "discoverable entry only" call after the CD-R block proved it's needed.
  - *Live streaming output during detection* — v1 shows a busy indicator + phase status; streaming the whipper output (like the rip view) is a polish item. Still deferred.

- **[x] Drive-access permission diagnostics.** Done 2026-05-30. New pure-stdlib `drive_access.diagnose_drive_access()` (injectable probes for testing) classifies the "no drive" state on the host: `no_device` (nothing connected), `permission` (a `/dev/sr*` node exists but isn't readable — owned by a group the user isn't in → fix command `sudo usermod -aG <group> $USER`), or `ok` (node readable, so the cause is elsewhere — container/whipper). `DrivePicker` now emits `drives_unavailable` on an empty refresh; MainWindow auto-shows the diagnosis **once per session and only when it's actionable** (a permission fix) — "no device" stays quiet (nothing to do). Always available via **Tools → Diagnose drive access…**. The dialog text is selectable so the fix command can be copied. Checking the host is correct because the AppImage runs as the host user and distrobox passes `/dev` through as the same user. (This was the one transferable lesson from the EAC-successor doc's Flatpak/Snap sandboxing section — the rest is N/A since we ship AppImage + pipx to reach host whipper.) 10 new tests.

- **[x] Auto-prompt the Unknown Album dialog when MB returns 0 matches.** Done 2026-05-28. Previously the user had to find File → Rip as Unknown Album in the menu after seeing "not in MusicBrainz"; now the dialog opens automatically the first time the GUI detects an unknown disc on a given drive selection. Guarded so it doesn't re-prompt if the user already accepted in this session.

- **[x] One-command uninstall script** (`uninstall.sh`). Done 2026-05-29. Default-removes the safe stuff (`.venv/`, `~/.config/whipper-gui`, `~/.local/share/whipper-gui`). Interactive prompts (or `--full`) for the broader cleanup: Picard Flatpak, the ripping Distrobox container, whipper.conf, host-exported binaries. `--dry-run` shows planned actions without executing. Music files at `~/Music/rips` are never touched without an explicit `--remove-rips` flag plus a typed `DELETE` confirmation in interactive mode. 6 smoke tests verify the script's help, error handling, and dry-run safety.

- **[x] One-command host bootstrap script** (`setup-host.sh`). Done 2026-05-30 — see the "P1 — Install automation" entry above for details. Remaining: a real-hardware run to confirm it (only `--dry-run`-tested so far).

- **[x] Surface install failures in the GUI summary popup** (verified done 2026-06-02), not only the log file. `MainWindow._show_dep_summary` appends an "Install failures:" block listing each failed dep + `InstallResult.message` (which `AutoInstaller` fills with the failing command's last stderr/stdout line), then points at the full log. Declines are excluded (the user already saw that dialog). Covered by `test_dep_summary_does_not_show_user_declines_as_failures`.

- **[x] Stop cascading the install dialogs when the user *declines*.** Done (verified 2026-06-02). `resolve_missing` skips cascade for `InstallResult.user_declined=True` (manager.py) — only real install *failures* cascade to the next tier. Both `AutoInstaller` (consent=No) and `QueuedInstaller` (empty selection) set `user_declined`. Covered by `test_resolve_missing_does_not_cascade_when_user_declines`, `test_resolve_missing_still_cascades_on_non_decline_failure`, and `test_dep_summary_does_not_show_user_declines_as_failures`.

- **[x] Version-stamp dependencies in the dep-report. Done 2026-06-02.** The probe already reads each dep's version; `DependencyReport` now carries `ok_versions` (dep_id → detected version), `check_all` populates it, and the summary popup lists an "Installed: whipper 0.10.0, FLAC 1.4.3, …" line (a version-less-but-present probe renders as "unknown"). New `version.format_version()` helper. Tests across `test_deps_version`, `test_deps_manager`, `test_ui_main_window`. *(Not done: pinning the Picard `.flatpakref` to a fixed version — that always tracks latest by URL; left as a separate question since pinning a Flatpak ref is non-trivial and the version is now at least visible to the user.)*

### P1 — UX gaps from real-user testing

Items that surfaced when an actual user walked through the GUI on Bazzite. Each is small but each makes the first-run experience noticeably worse.

- **[x] Show placeholder track rows for an unknown disc.** Done 2026-05-29 (T32). Previously the track table stayed empty when MusicBrainz had no match, so the user couldn't see what was on the disc before an unknown-album rip. whipper reports the track count even for an unidentified disc, so the adapter salvages it from `cd info`'s partial output (`DiscInfo.num_tracks`) and the main window renders that many rows via `TrackTable.set_placeholder_tracks()` — pre-filled with `Track 01`…`Track NN` titles + `Unknown Artist`, and album fields set to `Unknown Artist` / `Unknown Album` to mirror the tags the rip writes. The no-match handler is shared by the empty-disc-ID path and the 0-result-lookup path. **Follow-up is P2 (below):** edits to those rows don't yet feed the unknown rip.

- **[x] Live status during the pre-track disc scan.** Done 2026-05-29 (T32). The status label sat on "Starting rip…" for the whole initial TOC/table read (a minute-plus) because those whipper lines carry no track number, so the GUI looked frozen. `RipWorker` now emits a `status(str)` phase signal (`_describe_activity`) recognizing the disc-scan, per-track read/verify, encode, tag, and length phases; `RipProgress.set_progress` drives the bar only while `set_status` owns the label.

- **[x] Default path template → Artist/Album folders + per-mode templates.** Done 2026-05-29 (T32). Replaced the flat v1 `Artist - Album/` layout with two template pairs, picked per rip in `ui/rip_controls`:
  - **Known disc:** `%A/%d/%t - %n - %d - %A - %y` + disc `%A/%d/%d` → `Artist/Album/01 - Title - Album - Artist - Year.flac`.
  - **Unknown disc:** literal `Unknown Artist/Unknown Album/%t - Track %t` + disc `Unknown Artist/Unknown Album/Unknown Album` → clean `Unknown Artist/Unknown Album/01 - Track 01.flac`. This is what made the "Unknown Album now" choice safe — whipper never sees `%d` (the disc-ID hash) for unknown discs, so no post-rip renaming and no broken `.cue`/`.log` references.
  - All four templates are editable in Settings. Config schema bumped to v2 with a migration that upgrades the known templates only if they still hold the v1 defaults (hand-edited templates preserved); the unknown templates fill from defaults when absent.
  - **Flat-template caveats (documented in config.py):** a known disc with no year leaves a trailing " - " (whipper can't conditionally omit an empty field); disc-number/volume (`%N`) is always present so it's left out of the default — add `/%N` for multi-disc sets.

- **[x] Highlight the current track row during a rip. Done 2026-06-02.** The track table now follows whipper track by track. Note the mechanism changed: `RipWorker.progress` was reworked to `(overall, task)` percentages and no longer carries the track number, so this added a dedicated `RipWorker.current_track(int)` signal (emitted once per new track, derived from the `"track N of M"` lines the worker already parses) wired to `TrackTable.highlight_track()` (selects + scrolls the row; out-of-range numbers ignored). Tests: `test_emits_current_track_once_per_new_track`, `test_highlight_track_selects_matching_row`, `test_highlight_track_ignores_out_of_range`.
- **[x] Read offset field in Settings is misleading.** Resolved 2026-05-30 by the drive setup wizard (P1.1 / KDD-15): the field is read-only and now sits beside a "Re-detect…" button that launches the wizard — the supported way to (re)calibrate and write the offset to `whipper.conf`. (Still open as polish: parse `whipper.conf` to *display* the live per-drive offset rather than our config's stored copy.)
- **[x] PendingInstallsDialog visual feedback during install. Done 2026-06-02** (chose option 1: the dialog drives the install loop itself). `PendingInstallsDialog` now takes an optional `install_one` callable; when supplied, clicking "Install Selected" installs each ticked item in turn, updating that row live (`installing…` → `OK`/`FAILED`) then swapping in a Close button, with `results()` exposing one `InstallResult` per item (unticked → `user_declined`, so the manager won't cascade them). A new GUI resolver `main_window._DialogQueuedResolver` replaces `QueuedInstaller` in the GUI path (QueuedInstaller installs *after* its callback returns, which closed the dialog); `QueuedInstaller` itself is untouched and still used elsewhere. Row repaint uses `widget.repaint()`, NOT `QApplication.processEvents()` — the loop runs as a slot inside the modal `exec()`, and processEvents would re-enter that loop / pump unrelated timers+threads (a crash hazard caught in testing). Passive (no-`install_one`) mode preserved for existing callers/tests. Tests in `test_ui_pending_installs_dialog` + `test_ui_main_window`.
- **[x] Declined dependencies should not cascade to the next tier.** Done (verified 2026-06-02) — see the identical item under P1.1 above. `resolve_missing` skips cascade for `user_declined`; three tests cover it.
- **[x] Picard auto-install failure mode — resolved.** Both halves are done: (1) **root cause** — the registry now installs Picard via the **`.flatpakref` URL** (`https://dl.flathub.org/repo/appstream/org.musicbrainz.Picard.flatpakref`) instead of `flathub <ref>`; the `.flatpakref` carries the remote URL so flatpak adds flathub at *user* level on first install, fixing the Bazzite "No remote refs found for 'flathub'" error (Atomic distros configure flathub as a *system* remote). See `deps/registry.py`. (2) **diagnostics** — `AutoInstaller` captures the failed command's last stderr/stdout line into `InstallResult.message`, and `_show_dep_summary` surfaces it in an "Install failures:" block (no longer debug-only). Picard is also `optional=True`, so a failure doesn't nag.

### P1 — Documentation backlog

Items that need real-system output to write authoritatively. Address as T32's smoke test on a real Bazzite system surfaces the actual output. Each is small (a paragraph or two of README) but writing them now would be guesswork.

- **[ ] Verify Step 5 end-to-end with a real CD.** As of 2026-05-28 the install instructions have been walked through up to step 5 on Bazzite, but no commercial audio CD was on hand to run `whipper drive analyze` or `whipper offset find`. The user took the manual path (AccurateRip drive offset lookup, hand-edit `whipper.conf`). Once a CD is available, run both auto commands and confirm: (a) the auto path produces the same offset as the manual lookup, (b) the auto path's `whipper.conf` output matches the hand-edited format, (c) the manual-path section-header spacing convention documented in the README actually matches what whipper accepts. *(Tracked as [docs/test-plan.md](docs/test-plan.md) Tests 3–4.)*
- **[ ] "You should see X" success indicators for `whipper drive analyze`.** Capture the verbatim output a successful run prints; add to Step 5 so users know what success looks like and can recognize a failure. *([docs/test-plan.md](docs/test-plan.md) Test 3.)*
- **[ ] Same for `whipper offset find`.** Capture the final "Read offset of drive is N samples" (or whatever it actually prints) message; add to Step 5. *([docs/test-plan.md](docs/test-plan.md) Test 4.)*
- **[x] Drop the "Method C is the only working path right now" blockquote — done.** The README now leads with Method A (AppImage, a published release asset) as the recommended path; Method B (PyPI via the new publish workflow) and Method C (source) follow. No "only working path" caveat remains.
- **[x] Remove the Method C "private repo, authenticate first" blockquote — done.** The repo is public; the README's auth section states a plain HTTPS `git clone` needs no authentication (auth only matters if you intend to *push*).
- **[x] Add a Quick Start for users who already have whipper + Distrobox set up — done 2026-06-02.** README quickstart now has an "Already have whipper + Distrobox set up?" callout pointing at `install.sh --no-host` (GUI-only), for re-installs or a second box sharing the stack.
- **[ ] Add a screenshot or two** of the GUI to the top of the README once T32 confirms it looks right on Bazzite KDE Plasma 6. *(Needs a real GUI screenshot — hardware/display; [docs/test-plan.md](docs/test-plan.md) Test 5.)*
- **[ ] Document Picard's actual auto-launch behavior** under Step 6 once T32 verifies it. The README currently says it works "if you enable the toggle"; T32 will confirm what the toggle UX actually feels like end-to-end. *([docs/test-plan.md](docs/test-plan.md) Test 6.)*
- **[x] Sanity-check the "Where things live" table — done 2026-06-02.** Added a row for the rip output folder (`Artist/Album/`) documenting that whipper writes the FLAC tracks **plus** `.log`/`.cue`/`.m3u`/`.toc` next to them — confirmed on the real 16-track T32 rip (KDD-13 findings). Output goes under the configured output dir (not the working dir).

### P1/P2 — Upstream open-source modification for EAC parity (investigation 2026-06-02)

Previously it was out of scope to modify the programs underneath us; this is the first pass at "what would modifying open-source upstream buy us toward full EAC parity?" Full write-up, with reasoning and sources, in **[docs/upstream-modification-investigation.md](docs/upstream-modification-investigation.md)**. Headline: most of EAC's *correctness* is already delivered by whipper, so the wins are additive tools (CTDB), not whipper changes. **Guardrail:** prefer wrapping a separate maintained tool → upstream PR → (last resort) a maintained fork. Do **not** fork whipper (unmaintained; successor is `cyanrip`).

**Feasible (prioritised — priority shown in bold, status with the usual marker):**
- **[~] CTDB verify (read-only)** — **HIGH.** KDD-14 Phase 1; library landed 2026-06-03 (see Ranked execution order item 5). Not a whipper change — a new pure-Python `CTDBClient` adapter built **clean-room from the LGPL `gchudov/cuetools.net` source** (NOT the GPLv2 `python-cuetoolsdb`, NOT a wrap of `ctdb-cli`). **License gate RESOLVED 2026-06-02 (KDD-16): clean-room, no port.** Concrete, LGPL-grounded protocol + CRC spec in [docs/upstream-modification-investigation.md](docs/upstream-modification-investigation.md). **One blocker remains:** the verify CRC runs over decoded FLAC audio and can only be validated against a real CD that's in CTDB — a hardware (T32-style) test ([docs/test-plan.md](docs/test-plan.md) Test 1).
- **[ ] CTDB parity repair** — **HIGH.** KDD-14 Phase 2; the one genuine "beyond EAC" everyday win. Wrap `ctdb-cli verify|repair`; depends on verify. **Correction 2026-06-02: `ctdb-cli` is C#/.NET 10, not C — bundling it in the AppImage is heavy, so bundle-vs-optional-install is an open decision** (see the investigation doc).
- **[ ] Upstream whipper bug fixes — contribute, don't fork** — **LOW–MED.** `whipper cd info` non-zero exit on unknown discs (we already work around it) and HTOA accuracy edge cases (issues #75/#82). Open upstream PRs opportunistically; never maintain a fork.
- **[ ] EAC-style signed log checksum** — **LOW.** Scene-trust feature; emit an EAC-compatible logsigner checksum *from our own code* over whipper's log. No upstream change needed.

**Non-feasible / not worth it — do NOT revisit without a rethink** (full rationale in the doc):
- **AccurateRip submission** — permanently blocked by operator policy (EAC/dBpoweramp only). Not a code problem. *Verification stays in scope and works.*
- **CTDB submission** — almost certainly the same trust-gate; shelved.
- **C2 error-pointer reading** — would require deep C-level surgery on `libcdio`/`cd-paranoia` for marginal gain (whipper is already bit-perfect via overlap + AccurateRip). Treat as build-from-scratch.
- **Literal two-full-disc-pass Test&Copy** — whipper already does per-track test+copy CRC; the whole-disc double pass adds marginal assurance at 2× time.
- **Byte-for-byte EAC log format parity** — moving, semi-proprietary target; not worth it beyond the optional checksum above.
- **Separate drive-offset/feature database** — redundant with AccurateRip's offset list (already used).
- **In-house from-scratch ripper** — out of scope; the breakage path is migrate the adapter to `cyanrip`, not rewrite.

### P1 — Install ergonomics follow-ups (2026-06-02)

- **[x] Add openSUSE / Tumbleweed (`zypper`) support to `setup-host.sh`. Done 2026-06-02.** Added `*suse*) zypper --non-interactive install …` branches to both `ensure_distrobox` and `ensure_container_backend`, so openSUSE now auto-installs Distrobox + podman (README table upgraded from ⚠️ Partial to ✅ Fully). Also made distro detection testable via an `OS_RELEASE_FILE` override; new behavioural + static smoke tests in `tests/test_setup_host_script.py`.

---

## P2 — future enhancements (post-P1)

Items that are technically achievable but represent significant effort, double the rip time, or otherwise belong after the P1 backlog has settled. Pull from here when there's a concrete user request.

- **[x] Edited track tags feed the unknown-album rip.** Done 2026-05-30. After a successful unknown-mode rip, `_on_rip_finished` now calls `run_unknown_post_processing`, which reads `TrackTable.album_metadata()` + `tracks()` (the placeholder rows plus any edits the user made) and writes them to the FLACs via the new `apply_track_tags()` — blank fields fall back to the `Track NN` / Unknown Artist / Unknown Album placeholders, and a typed year becomes a `DATE` tag. **Bug fixed in the same change:** the post-processing is scoped to the album folder whipper just wrote (the `.log`'s parent dir), not the configured output root — otherwise an `rglob("*.flac")` over `~/Music/rips` would have re-tagged every previously ripped album with this disc's metadata. (`apply_placeholder_tags` remains for the no-data path.) Note: edits only flow to **tags**, not filenames — the unknown template still names files `## - Track NN` (renaming-from-edits would be a separate feature).

- **Test & Copy dual-pass rip — DOWNGRADED (largely already delivered).** Re-evaluated 2026-05-30 during the EAC-successor research review: **whipper already performs a test read and a copy read per track and records both CRCs** (your T32 log shows `Test CRC == Copy CRC` for all 16 tracks, and `(try 2)` re-reads on mismatch). We already surface this as the fidelity summary ("all N tracks verified, Test/Copy CRCs match"). So the core guarantee EAC's Test&Copy provides is already in hand. The only delta would be EAC's literal *two separate full passes* of the whole disc — marginal extra assurance at 2× rip time. Not worth building unless a user specifically asks for the two-full-passes behavior; keep parked here.

---

## Out of scope (not in P0, P1, or P2)

Listed here for clarity so they don't sneak in:

- Replacing whipper itself
- **AccurateRip submission.** Policy-restricted, not technically impossible. AccurateRip's operators accept submissions only from EAC and dBpoweramp; any Linux tool implementing the upload protocol would have its submissions rejected. **AccurateRip *verification* IS in scope and already works** — whipper queries AccurateRip during every rip, the parser captures the v1/v2 confidence values, and the rip-progress widget renders them.
- **CTDB submission.** Likely subject to the same trust-gate as AccurateRip submission.
- Network features (NAS, Plex, Jellyfin, cloud)
- Library/catalog database
- DVD/Blu-ray support
- Windows or macOS support
