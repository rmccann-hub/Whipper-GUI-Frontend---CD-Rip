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
      Done: `build/build_appimage.sh` checks prerequisites (python3, `build`, `python-appimage`), builds a wheel from local source via `python -m build`, drops it next to the recipe so pip's `--find-links .` resolves `whipper-gui` to the local wheel rather than PyPI, generates a 16×16 placeholder icon if no real one is present (using a hand-rolled PNG generator with no external deps), and invokes `python -m python_appimage build app build/python-appimage/`. Recipe directory has `requirements.txt` (pinned to DEPENDENCIES.md), `entrypoint` (executable script that runs `python -m whipper_gui` from the bundled interpreter), `whipper-gui.desktop` (KDE/freedesktop standard), and `README.md` (build prerequisites + icon-replacement note). 7 unit tests verify the recipe structure, the executable bit on both scripts, the desktop file shape, the `--find-links .` self-install pattern, and that the pinned versions match DEPENDENCIES.md. The actual end-to-end build needs Linux + python-appimage installed and gets verified in T32.

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
- **CTDB verification (read-only).** The CUETools Database operates an open-source server (LGPL) with no public HTTP API documentation, but the reference server and client code is public — the protocol is derivable from it. A Python client modeled on that reference would let us add a "Verify with CTDB" button to the rip-progress widget that runs after each rip finishes. No submission — same trust-gate as AccurateRip likely applies. Moderate effort (~200-400 lines for the client + UI hookup). Adds a second archival-verification path complementing the AccurateRip data whipper already provides. See [PLANNING.md KDD-12](PLANNING.md) for the reasoning behind moving this from "out of scope" to P1.

---

## Out of scope (not in P0, not in P1)

Listed here for clarity so they don't sneak in:

- Replacing whipper itself
- **AccurateRip submission.** Policy-restricted, not technically impossible. AccurateRip's operators accept submissions only from EAC and dBpoweramp; any Linux tool implementing the upload protocol would have its submissions rejected. **AccurateRip *verification* IS in scope and already works** — whipper queries AccurateRip during every rip, the parser captures the v1/v2 confidence values, and the rip-progress widget renders them.
- **CTDB submission.** Likely subject to the same trust-gate as AccurateRip submission.
- "Test & Copy" dual-pass
- Network features (NAS, Plex, Jellyfin, cloud)
- Library/catalog database
- DVD/Blu-ray support
- Windows or macOS support
