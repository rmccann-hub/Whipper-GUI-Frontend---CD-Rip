# PLANNING.md — Whipper GUI Architecture and Design

This is the architecture document. It captures *how* the GUI is built. For *what* to build, see the brief at `docs/whipper-gui-research-brief-v2.1.md`. For *which sessions are working on which slice*, see `TASKS.md`. For *which deps are pinned and why*, see `DEPENDENCIES.md`. For *how to rebuild from scratch*, see `docs/README.md`.

This file is **living**. When an architectural decision is made or revisited, update the relevant section here. The Key Design Decisions section at the bottom is the changelog of architectural intent — future-you reads it to understand "why is it like this?"

---

## 1. Directory tree

Every file the project intends to create. New files added during a task should be reflected back here when the task completes.

```
Whipper-GUI-Frontend---CD-Rip/
├── CLAUDE.md                            # persistent project context (locked rules)
├── PLANNING.md                          # this file — architecture and design
├── TASKS.md                             # active task checklist (P0/P1.1/P1/P2)
├── DEPENDENCIES.md                      # dep table with release dates + replacement plans
├── README.md                            # outward-facing description + install instructions
├── CHANGELOG.md                         # Keep-a-Changelog release notes
├── LICENSE                              # GPL-3.0-only
├── pyproject.toml                       # package metadata + pinned deps + entry points + pytest/ruff config
├── dev-setup.sh                         # one-command post-clone bootstrap (venv + pip + editable install)
├── setup-host.sh                        # host bootstrap (Distrobox + ripping container + whipper + exports)
├── install.sh                           # end-user installer (host stack + download AppImage + desktop integration)
├── install-appimage.sh                  # desktop integration for a downloaded AppImage (+ uninstall launcher)
├── uninstall.sh                         # comprehensive tear-down for both install paths
├── .gitignore
├── .gitattributes
│
├── .github/workflows/                   # CI + release automation
│   ├── ci.yml                           # pytest + ruff (lint/format) on push to main + PRs
│   ├── appimage.yml                     # build + smoke-test the AppImage (push to main; on-demand per branch)
│   ├── release.yml                      # tag-driven: build AppImage + attach to a GitHub Release
│   └── publish-pypi.yml                 # publish wheel+sdist to PyPI via Trusted Publishing on release
│
├── docs/                                # source docs + reference material
│   ├── README.md                        # index of docs/ contents + rebuild-from-scratch checklist
│   ├── whipper-gui-research-brief-v2.1.md   # canonical project brief (authority on scope)
│   ├── whipper-gui-session-start.md     # bootstrap instructions (incl. optional research-rerun prompt)
│   ├── architecture.md                  # architecture & contributor guide (patterns, recipes, packaging)
│   ├── log-format-comparison.md         # whipper rip log vs EAC log side-by-side (KDD-11)
│   ├── appimage-testing.md              # how the AppImage is built + tested
│   ├── test-plan.md                     # manual & release testing (acceptance run + gated cases)
│   ├── testing.md                       # testing strategy & standards (trophy + hardware gate)
│   ├── session-log.md                   # chronological session history (newest first)
│   ├── archive/                         # retired point-in-time investigations (see archive/README.md)
│   │   ├── ecosystem-audit-2026-06.md   # whipper-stalled / cyanrip-successor audit (KDD-18)
│   │   ├── offset-investigation-2026-06.md # read-offset → offset-by-drive-model lookup
│   │   └── upstream-modification-investigation.md # EAC-parity investigation (CTDB, whipper)
│   └── (compass_artifact_*.md if/when produced — see docs/README.md)
│
├── scripts/                             # standalone (non-packaged) helper scripts
│   ├── ctdb_verify.py                   # CTDB verify hardware-validation runner (KDD-16)
│   └── update_drive_offsets.py          # re-import AccurateRip DriveOffsets.bin (sentinel-guarded)
│
├── build/                               # everything related to producing the AppImage
│   ├── build_appimage.sh                # one-shot build script (calls python-appimage)
│   ├── make_icon.py                     # regenerate the committed app icon (needs Pillow)
│   └── python-appimage/
│       ├── requirements.txt             # pip deps bundled into the AppImage
│       ├── entrypoint.sh                # executable AppRun script (needs .sh extension — T31)
│       ├── whipper-gui.desktop          # desktop integration
│       ├── whipper-gui.png              # committed app icon
│       └── README.md                    # build-time prerequisites and gotchas
│
├── tests/                               # pytest test tree (runs offscreen, no real hardware/network)
│   ├── conftest.py                      # session-scoped QApplication fixture; QT_QPA_PLATFORM=offscreen
│   ├── test_*.py                        # one suite per module (run `ls tests/`), incl.
│   │                                    #   test_ctdb_{toc,decode,crc,client,verify}.py, the deps/parsers/
│   │                                    #   ui/workers suites, and *_script.py smoke tests for the installers
│   └── fixtures/                        # whipper cd-info / drive-list / rip-log sample data (+ README)
│
└── src/
    └── whipper_gui/
        ├── __init__.py                  # package version + metadata
        ├── __main__.py                  # `python -m whipper_gui` entry point
        ├── app.py                       # QApplication construction + startup sequence
        ├── composition.py               # composition root: build adapters from config (shared by app + preflight)
        ├── config.py                    # TOML config load/save + defaults + schema
        ├── logging_setup.py             # logging configuration (rotating file + console)
        ├── paths.py                     # user dirs, config path, log path constants
        ├── offset_config.py             # read/detect whipper.conf read-offset state
        ├── preflight.py                 # --doctor checks (mirrors the composition root; never-raise)
        ├── parity.py                    # compare a rip's Copy CRCs against an EAC baseline
        ├── update_check.py              # "is a newer release published?" (self-update, KDD-17b)
        ├── update_install.py            # download + checksum-verify + atomic self-install (KDD-17b)
        ├── drive_access.py              # diagnose no-drive cause (no_device / permission / ok)
        ├── drive_control.py             # eject + force-stop a runaway drive on cancel (Critical Rule #3)
        ├── help_content.py              # in-code User Guide markdown (avoids AppImage package-data)
        ├── appimage_integration.py      # first-run "add me to the app menu" self-integration (KDD-17a)
        │
        ├── adapters/                    # ALL calls into external tools/services go through here
        │   ├── __init__.py
        │   ├── whipper_backend.py       # WhipperBackend ABC (+ RipMetadata) + WhipperHostExportedImpl
        │   ├── cyanrip_backend.py       # CyanripImpl — config-selectable successor backend (KDD-18)
        │   ├── musicbrainz_client.py    # MusicBrainzClient ABC + MusicBrainzNgsImpl
        │   ├── metaflac.py              # MetaflacAdapter (tag write-back + embed_picture)
        │   ├── cover_art.py             # Cover Art Archive front-cover fetch + embed/save (backend-independent)
        │   ├── accuraterip_offsets.py   # read-offset lookup by drive model (AccurateRip list)
        │   ├── accuraterip_offsets_data.py # bundled DriveOffsets.bin (~4,800 drives, gzip+base64)
        │   └── ctdb_client.py           # CTDBClient ABC + CtdbHttpImpl (CUETools DB lookup; KDD-16)
        │
        ├── ctdb/                        # CTDB verify library (clean-room; KDD-16; GUI-wired, experimental until CRC hardware-validated)
        │   ├── __init__.py
        │   ├── toc.py                   # DiscToc + `toc=` wire string + disc-TOC math
        │   ├── decode.py                # host flac→PCM + metaflac sample-count probe
        │   ├── crc.py                   # the audio CRC (hardware-validation-gated; CRC_VALIDATED=False)
        │   └── verify.py                # verify_rip() orchestration + Verdict enum
        │
        ├── deps/                        # dependency self-management subsystem (brief P0 #11)
        │   ├── __init__.py
        │   ├── manager.py               # DependencyManager — single orchestrator
        │   ├── registry.py              # declarative DependencySpec list
        │   ├── checks.py                # probe functions (present? version?)
        │   ├── resolvers.py             # AutoInstaller, QueuedInstaller, ManualPrompt
        │   ├── host_setup.py            # bootstrap arm: Distrobox/container/whipper/cyanrip install + export (KDD-17c)
        │   ├── host_teardown.py         # teardown arm: the in-app Uninstaller's engine (keeps distrobox/podman + music)
        │   ├── step_engine.py           # shared step-engine vocabulary (StepStatus/StepResult/CommandRunner/SubprocessRunner/StepEngine)
        │   └── version.py               # version-string parsing utility
        │
        ├── parsers/                     # whipper/cyanrip/EAC stdout+log parsing (named-group regexes)
        │   ├── __init__.py
        │   ├── rip_log.py               # parse the `.log` file whipper writes per rip
        │   ├── drive_list.py            # parse `whipper drive list`
        │   ├── cd_info.py               # parse `whipper cd info` (defines the shared DiscInfo)
        │   ├── cyanrip_info.py          # parse `cyanrip -I` into the same DiscInfo (KDD-18)
        │   ├── cyanrip_log.py           # parse cyanrip's per-album log into the shared RipLog (KDD-18)
        │   └── eac_log.py               # parse EAC rip logs (per-track Copy CRCs; the parity baseline)
        │
        ├── ui/
        │   ├── __init__.py
        │   ├── main_window.py           # MainWindow assembler — layout, menus, signal wiring, MB slots
        │   ├── main_window_helpers.py   # pure free fns (safe_path_segment, fidelity_summary, …)
        │   ├── main_window_update.py    # UpdateMixin — Help → Check for updates / download / install / restart
        │   ├── main_window_rip.py       # RipMixin — rip lifecycle, force-stop, eject, cover art, post-processing
        │   ├── main_window_provision.py # ProvisioningMixin — host setup / AppImage integration / uninstall
        │   ├── main_window_drive.py     # DriveMixin — drive setup / read-offset / access diagnostics
        │   ├── main_window_deps.py      # DependencyMixin (+ _DialogQueuedResolver) — dependency-check UI
        │   ├── drive_picker.py          # drive dropdown widget
        │   ├── disc_info_panel.py       # TOC / MB match / AccurateRip availability
        │   ├── release_picker.py        # modal: pick from multiple MB matches
        │   ├── track_table.py           # editable per-track table pre-rip
        │   ├── rip_controls.py          # Start/Cancel buttons + parameter assembly
        │   ├── rip_progress.py          # live progress + AccurateRip results + log viewer
        │   ├── settings_dialog.py       # settings page
        │   ├── unknown_album.py         # unknown-album helper flow
        │   ├── drive_setup_dialog.py    # drive-setup wizard (analyze + offset find; KDD-15)
        │   ├── host_setup_dialog.py     # host-setup wizard (no-terminal setup-host.sh; KDD-17c)
        │   ├── uninstall_dialog.py      # in-app Uninstaller (no-terminal uninstall.sh)
        │   ├── help_dialogs.py          # Help → About + User Guide dialogs
        │   └── dialogs/
        │       ├── __init__.py
        │       ├── pending_installs.py  # tier (b) queued installs dialog
        │       └── manual_install.py    # tier (c) copyable search string dialog
        │
        └── workers/                     # long-running operations off the GUI thread
            ├── __init__.py              # start_worker_thread() — the shared one-shot QThread lifecycle wiring
            ├── rip_worker.py            # drives the rip subprocess (whipper or cyanrip)
            ├── mb_worker.py             # drives MusicBrainz queries
            ├── drive_setup_worker.py    # drives drive analyze / offset find off-thread
            ├── host_setup_worker.py     # drives the setup AND teardown engines off-thread (StepEngine)
            ├── drive_list_worker.py     # drives list_drives() off-thread (cold-container probe)
            ├── disc_info_worker.py      # drives disc_info() off-thread
            ├── dependency_worker.py     # drives the launch-time dependency probe off-thread
            ├── update_worker.py         # drives the release check + the download/verify/install off-thread
            └── ctdb_worker.py           # drives CTDB verify for a finished rip off-thread (KDD-14)
```

---

## 2. Per-module responsibility

One paragraph per module, no more. If a module's paragraph creeps beyond a few sentences, the module is probably doing too much.

### Top-level

- **`__init__.py`** — exposes package version (read by `pyproject.toml` and `--version` CLI). No runtime logic.
- **`__main__.py`** — invoked by `python -m whipper_gui`. Imports and calls `app.main()`. Stays tiny so packaging tools and AppImage entry points have a stable target.
- **`app.py`** — builds the `QApplication`, constructs the adapters via `composition` (the shared composition root), instantiates the `DependencyManager` and runs its initial check (which may show install dialogs before the main window appears), then constructs and shows the `MainWindow`. Wires logging early so any failure during startup is captured.
- **`composition.py`** — the composition root: `build_backend(cfg)` (whipper/cyanrip selection + the host-exported-path fallback) and `build_musicbrainz_client()` plus the shared `CONTACT_URL`. Both `app.py` (the GUI) and `preflight.default_context()` (the `--doctor` diagnostic) build their adapters here, so the two can never wire them differently. Construction does no I/O. (KDD-21.)
- **`config.py`** — pure-Python TOML config loader/saver. Reads `~/.config/whipper-gui/config.toml` via `tomllib` (stdlib in 3.11+), writes via `tomli-w`. Defines the default config dict and a schema version. Atomic writes (temp file + rename) so a crash mid-save doesn't corrupt the file.
- **`logging_setup.py`** — configures Python's `logging` module once at startup. Rotating file handler at `~/.local/share/whipper-gui/log.txt`, plus a console handler at INFO. Project modules use `logging.getLogger(__name__)` everywhere; no module configures handlers itself.
- **`paths.py`** — module-level constants for the user config dir, log dir, and any other path computed from `XDG_*` env vars or hard-coded fallbacks. Single source of truth so paths aren't recomputed at call sites.
- **`offset_config.py`** — reads `whipper.conf` (and the GUI's `--offset` override) to tell whether a read offset is configured; backs the drive-setup wizard's first-run auto-offer. One shared section scanner (`_iter_conf_offsets`) + one file reader (`_read_conf_text`) feed both the "any offset set?" check and the per-drive read-out, so the two filters can't drift.
- **`preflight.py`** — the `--doctor`/`scripts/preflight.py` checks: a no-disc, never-raise first-pass test of the rip environment (backend routing, drives, dependencies, network reachability). `default_context()` mirrors `app.py`'s composition via the shared `composition` root.
- **`parity.py`** — compares a rip's per-track Copy CRCs against an EAC baseline log (`output_reference/`, `docs/test-plan.md`); the bit-perfect-equivalence check.
- **`update_check.py`** — "is a newer release published?" against the GitHub releases API (self-update, KDD-17b). Delivery is handled by `update_install.py`.
- **`update_install.py`** — download → checksum-verify → atomic self-install of an AppImage update (KDD-17b amendment), off-thread via `workers/update_worker.py`.
- **`drive_access.py`** — pure-stdlib `diagnose_drive_access()` classifying the no-drive case as `no_device` / `permission` (gives the `usermod -aG` fix) / `ok`. Probes are injectable for testing.
- **`drive_control.py`** — host-first best-effort `eject_drive()` and `force_stop_drive()` for a runaway drive on cancel. This is the one approved exception to Critical Rule #3 (force-stop only; see CLAUDE.md).
- **`help_content.py`** — the User Guide Markdown kept *in code* (not packaged data, to dodge AppImage package-data pitfalls); rendered by the Help dialogs.
- **`appimage_integration.py`** — first-AppImage-run self-integration (KDD-17a): one-time, dismissible offer to write the app's own `.desktop` + icon into the user's menu and set the AppImage executable. No-op for source/pipx installs (detected via `$APPIMAGE`).

### Adapters (`adapters/`)

Every call into an external tool goes through this layer. CLAUDE.md Critical Rule #1 makes adapter layers mandatory for unmaintained deps; we apply the same pattern to `metaflac` for consistency.

- **`whipper_backend.py`** — defines `WhipperBackend`, an abstract base class with the methods the GUI needs (`list_drives()`, `disc_info(drive)`, `rip(...)`, `version()`, plus the optional `analyze_drive()`/`find_offset()` used by the drive-setup wizard — these default to `NotImplementedError` so other backends and test fakes still construct). `rip()` also takes an optional `RipMetadata` (the GUI's track-table snapshot) that metadata-fed backends consume. The returned `RipHandle` carries `log_lines()`, `wait()`, `cancel()`, `returncode`. The original concrete implementation is `WhipperHostExportedImpl`, which `subprocess`-invokes `~/.local/bin/whipper` and ignores `RipMetadata` (whipper tags itself from `--release-id`).
- **`cyanrip_backend.py`** — `CyanripImpl` (KDD-18), the config-selectable successor backend (`Config.ripper_backend`). Always runs cyanrip offline (`-N`) and feeds it the GUI's `RipMetadata` via `-a`/`-t` (values escaped for FFmpeg's `av_dict_parse_string`); translates whipper `%`-templates to cyanrip `-D`/`-F` `{…}` schemes (`scheme_from_template`); `disc_info` parses `cyanrip -I -N` via `parsers/cyanrip_info.py`. Drive listing is a backend-independent `/dev/sr*` + sysfs scan.
- **`accuraterip_offsets.py`** (+ **`accuraterip_offsets_data.py`**) — read-offset lookup by drive vendor/model the way EAC/dBpoweramp do it, against the full bundled AccurateRip `DriveOffsets.bin` list (~4,800 drives, stored in-code as gzip+base64; regenerated by `scripts/update_drive_offsets.py`, which refuses to write unless the BDR-209D=+667 sentinel passes). Layered: user CSV > curated overrides > bundled list. Only ever *suggests* — a human confirms before anything is saved.
- **`musicbrainz_client.py`** — defines `MusicBrainzClient` ABC with `releases_by_disc_id(disc_id)`, `releases_by_toc(toc)`, `release_by_mbid(mbid)`, `set_user_agent(...)`. v1 implementation `MusicBrainzNgsImpl` wraps `musicbrainzngs`. A `RequestsJsonImpl` is reserved for the day `musicbrainzngs` finally bitrots — it would hit `https://musicbrainz.org/ws/2/...?fmt=json` directly with `requests`.
- **`metaflac.py`** — `MetaflacAdapter` wrapping the `metaflac` CLI. Used by the Unknown Album helper to apply `Track NN` placeholder tags after a `--unknown` rip; `embed_picture()` (replace-then-import, so re-rips don't stack covers) backs the cover-art feature.
- **`cover_art.py`** — backend-independent cover art (2026-06-13). `fetch_front_cover(release_id)` GETs the Cover Art Archive `/front` image (stdlib urllib, injectable fetcher, magic-byte sniff, every failure → `None`); `plan_actions(mode, ripper_fetches_art, release_id)` is the pure gate (no-op when the ripper fetches its own art or the disc was never identified); `apply_cover_art(...)` writes `cover.<ext>` and/or embeds via `MetaflacAdapter.embed_picture`. Closes the gap where cyanrip rips and whipper `--unknown` heals had no art (they bypass the ripper's own MB/CAA lookup). Honors Critical Rule #5 — the GUI queries, never the ripper.
- **`ctdb_client.py`** — `CTDBClient` ABC + `CtdbHttpImpl` for CUETools-DB lookups (`db.cuetools.net/lookup2.php`). Clean-room per Critical Rule #1 and KDD-16; the injectable fetcher keeps the transport swappable and unit-testable. Backs the `ctdb/` verify library.

### CTDB verify library (`ctdb/`)

Clean-room CTDB verify support (KDD-16), kept as a standalone library so the deterministic parts are unit-tested while the two hardware-validation-gated pieces (the `toc=` wire format and the audio CRC) stay isolated behind a single seam. **Wired into the GUI 2026-06-17** (opt-in `Config.ctdb_verify_after_rip` → `workers/ctdb_worker.py` off-thread → verdict in `ui/rip_progress.py`), but kept behind the safety seam: while `CRC_VALIDATED=False` a match is shown as **experimental**, never "verified". Flipping that flag after `docs/test-plan.md` Test 1 (hardware) is all that's left.

- **`toc.py`** — `DiscToc` value object, the `toc=` query string, and the disc-TOC math (MSF/sector helpers, build-from-files via `metaflac` sample counts).
- **`decode.py`** — host `flac`→raw-PCM decode + `metaflac` sample-count probe (best-effort, optional `flac` dependency; degrades to `DecoderUnavailable`). Injectable runners.
- **`crc.py`** — the CTDB audio CRC. ⚠️ Placeholder zlib CRC-32 with `CRC_VALIDATED=False`; the bit-exact variant + ±2939 offset sweep is the hardware task. Fails safe (a wrong CRC yields `NO_MATCH`, never a false "verified").
- **`verify.py`** — `verify_rip()` orchestration tying lookup + decode + CRC into a single `CtdbVerifyResult`/`Verdict`; every expected failure is a verdict, not a raise.

### Dependency self-management subsystem (`deps/`)

Implements brief P0 #11. **All** dependency checks live here. CLAUDE.md Critical Rule #6 forbids ad-hoc `shutil.which()` calls anywhere else.

- **`manager.py`** — `DependencyManager`. Single entry point `check_all()` invoked at app launch and from the Settings "Check dependencies" button. Walks the registry, runs each probe, classifies missing items into tiers (a)/(b)/(c), and drives the appropriate resolver. Returns a `DependencyReport` for UI display.
- **`registry.py`** — declarative list of `DependencySpec` dataclasses. Each spec names: dependency id, human-readable name, probe function (from `checks.py`), minimum version, eligible install tier(s), install command template (e.g. `flatpak install --user flathub org.musicbrainz.Picard`), and a copyable search string for tier (c) fallback. New dependencies are added here, nowhere else.
- **`checks.py`** — probe functions. One per dependency: `check_whipper()`, `check_metaflac()`, `check_libdiscid()`, `check_picard_flatpak()`, `check_python_pkg(name)`. Each returns a `ProbeResult` (present: bool, version: str | None, location: str | None).
- **`resolvers.py`** — three resolver classes corresponding to the three tiers. `AutoInstaller` runs silent installs after one confirmation dialog (pipx, `flatpak install --user`). `QueuedInstaller` drives `ui.dialogs.pending_installs`. `ManualPrompt` drives `ui.dialogs.manual_install`. The resolvers are dumb about which tier a dep belongs to — that's the registry's job; resolvers just execute.
- **`version.py`** — small helper: parse a version string out of CLI output using a named-group regex, compare semver-ish strings against a minimum. Tiny, well-tested.
- **`step_engine.py`** — the shared vocabulary both host step-engines speak: `StepStatus`/`StepResult` (per-step outcome), the injectable `CommandRunner` Protocol + its real `SubprocessRunner`, and the `StepEngine` Protocol one worker drives both arms through. Lives here (not in `host_setup`) so the teardown engine doesn't depend on the setup engine for its core types (KDD-21).
- **`host_teardown.py`** — the **teardown arm** (the in-app Uninstaller's engine): idempotent steps removing shortcuts → host exports → the `ripping` container → optionally `whipper.conf` and the running AppImage → the GUI's own settings + logs LAST (so the log survives a failed step). Injectable runner + file/tree removers, dry-run, per-step `StepResult`s (from `step_engine`). The keep-contract is test-pinned: the only mutating command it can issue is `distrobox rm --force ripping` — Distrobox/podman and music are never targets.
- **`host_setup.py`** — the **bootstrap arm** of this subsystem (KDD-17c): an idempotent step engine (Distrobox → container backend → `ripping` container → whipper-in-container → optional cyanrip-from-COPR → host export) behind an injectable `CommandRunner` (from `step_engine`), so the orchestration is fully unit-testable and supports dry-run. Host-root installs use `pkexec` (graphical polkit — a GUI has no TTY for sudo); in-container installs stay `sudo`. Also home to `cyanrip_on_host()` so presence checks don't scatter (Critical Rule #6).

### Whipper output parsers (`parsers/`)

Subprocess output parsing per CLAUDE.md (named-group regexes, robust to minor-version drift).

- **`rip_log.py`** — parses whipper's per-rip `.log` file into a structured `RipLog` dataclass: per-track CRCs, AccurateRip match status, AccurateRip confidence, read offset confirmation, total error count.
- **`drive_list.py`** — parses stdout of `whipper drive list` into a list of `DriveDescriptor` (vendor, model, firmware, device path).
- **`cd_info.py`** — parses stdout of `whipper cd info` into a `DiscInfo` (TOC, MusicBrainz disc ID, MB match status, AccurateRip availability). `DiscInfo` is deliberately backend-neutral — both backends produce it.
- **`cyanrip_info.py`** — parses the `cyanrip -I` start report into the same `DiscInfo` (Disc tracks / DiscID / CDDB ID / the MusicBrainz URL printed on the line after its label). Labels verified against cyanrip master's `cyanrip_log_start_report`.

### UI (`ui/`)

PySide6 widgets and dialogs. Each module is one screen or one widget; nothing here knows about subprocess details — that's the workers and adapters.

- **`main_window.py`** — `MainWindow(QMainWindow, RipMixin, UpdateMixin, ProvisioningMixin, DriveMixin, DependencyMixin)`, the **assembler** (~460 lines, down from a 1707-line god-object). Central widget is a vertical stack of: `DrivePicker`, `DiscInfoPanel`, `TrackTable`, `RipControls`, `RipProgress`. Owns construction, menus, signal wiring, the MusicBrainz slots, and Settings. Cohesive concern-groups are factored into the mixins it inherits (KDD-19) so this file stays focused on wiring; the mixins' methods run with `self` being the window.
- **`main_window_helpers.py`** — pure free functions with no Qt/widget dependence: `safe_path_segment` (sanitize a user string for a whipper template), `friendly_disc_scan_error` (map known scan failures to plain language), `fidelity_summary` (one-line rip-quality verdict, worded per backend). Trivially unit-testable; `main_window` re-exports them under their old `_`-prefixed names for the test-facing API.
- **`main_window_update.py`** — `UpdateMixin`: Help → Check for updates and the download/verify/install/restart UI (KDD-17b). GUI orchestration only; the work is in `update_install.py` + `workers/update_worker.py`.
- **`main_window_rip.py`** — `RipMixin`: the rip lifecycle (validate → start worker, cancel → force-stop escalation, eject, the finish handler with fidelity verdict + auto-heal + auto-eject), the unknown-album flow, post-rip tagging, and the backend-independent cover-art fetch. The largest concern; mixin docstring states the `self.` attributes it expects `MainWindow.__init__` to have set.
- **`main_window_provision.py`** — `ProvisioningMixin`: first-run offers, AppImage menu self-integration (`_maybe_offer_appimage_integration` / `_on_add_app_shortcut`), the host-setup wizard entry points, and the in-app uninstaller. GUI-facing complement to `deps/host_setup.py` + `deps/host_teardown.py` + `appimage_integration.py`; heavy deps lazy-imported inside methods.
- **`main_window_drive.py`** — `DriveMixin`: the drive-setup wizard entry, read-offset auto-apply-by-drive-model / hand-entered override (the single place that records "offset configured", KDD-15), and the drive-access (permission/no-device) diagnostics.
- **`main_window_deps.py`** — `DependencyMixin` (+ the `_DialogQueuedResolver` tier-(b) resolver): the GUI side of the dependency subsystem — builds GUI-backed resolvers, runs the injected `DependencyManager`'s registry, shows the summary, and offers the cyanrip install when the backend is switched. All detection logic stays in `deps/` (Critical Rule #6).
- **`drive_picker.py`** — `DrivePicker(QWidget)`. Combo box over drives discovered via `WhipperBackend.list_drives()`. Emits `drive_changed(device_path)`.
- **`disc_info_panel.py`** — read-only panel. Updates when a drive is selected or a disc is detected. Shows TOC, MB match status, AccurateRip availability.
- **`release_picker.py`** — `ReleasePickerDialog(QDialog)`. Shown only when `MusicBrainzClient` returns >1 candidate for the inserted disc. List of releases with year, label, country, track count. Returns the chosen MBID. **This is the v1 substitute for whipper's TTY prompt** — Critical Rule #5.
- **`track_table.py`** — `TrackTable(QTableView)` with a custom `QAbstractTableModel`. Editable per-track tags + album-level fields above the table. Validates before allowing the rip to start.
- **`rip_controls.py`** — Start / Cancel buttons. On Start, assembles rip parameters (drive, MBID, output dir from config, template, edited tags) and emits `rip_requested(params)`.
- **`rip_progress.py`** — three panes: live whipper stdout (read-only), per-track AccurateRip results table (populated when the rip log is parsed at the end), and a "View log" button that opens the saved `.log` file in the default text viewer.
- **`settings_dialog.py`** — `SettingsDialog(QDialog)`. One unified page across backends: output/working dirs, track/disc templates, read-offset override, whipper/metaflac paths, ripper-backend toggle (whipper | cyanrip), cover art, force-overread, max-retries, keep-going, CD-R, auto-launch-Picard, auto-eject. `_apply_backend_capabilities` greys out options the selected backend doesn't support with a why+how-to-re-enable tooltip, and `to_config()` still reads disabled widgets so switching backends never loses a value. Persists through `config.py`.
- **`unknown_album.py`** — `UnknownAlbumDialog(QDialog)` + helper functions. Triggers a `whipper cd rip --unknown`, applies placeholder tags via `MetaflacAdapter`, optionally invokes `flatpak run org.musicbrainz.Picard <output_folder>`.
- **`drive_setup_dialog.py`** — `DriveSetupDialog`, the drive-setup wizard (KDD-15). Runs whipper's own `drive analyze` + `offset find` off-thread via `DriveSetupWorker` (they persist to `whipper.conf`), with a manual-offset fallback that uses the GUI's `--offset` override and a pre-filled offset when the drive model is in the bundled AccurateRip list.
- **`host_setup_dialog.py`** — `HostSetupDialog`, the no-terminal host-setup wizard (KDD-17c). Drives `deps/host_setup.py` off-thread via `HostSetupWorker` with live per-step progress; offered on first launch when whipper is absent and on Tools → Set up Whipper GUI…. Installs the cyanrip backend too when it's the selected backend.
- **`uninstall_dialog.py`** — `UninstallDialog`, the in-app Uninstaller (Tools → Uninstall Whipper GUI…, also launched directly by `whipper-gui --uninstall` from the menu entry). Confirmation gate + per-piece checkboxes (container, whipper.conf; the AppImage step appears only when running as one); drives `deps/host_teardown.py` via the shared worker; on success the main window offers to close itself (its settings no longer exist on disk).
- **`help_dialogs.py`** — `AboutDialog` (version + Python/Qt/PySide6 versions + config/log/whipper paths) and `HelpDialog` (renders `help_content.USER_GUIDE`).
- **`dialogs/pending_installs.py`** — `PendingInstallsDialog(QDialog)`. Tier (b) UI: per-item checkboxes, "Install selected" button, per-item progress feedback. Backed by `QueuedInstaller`.
- **`dialogs/manual_install.py`** — `ManualInstallDialog(QDialog)`. Tier (c) UI: shows missing item, minimum version, why it can't auto-install, copyable search string in a read-only `QLineEdit`. Primary action: Copy. Secondary: Close.

### Workers (`workers/`)

Long-running operations on background `QThread`s so the GUI stays responsive. The
package `__init__` provides `start_worker_thread(worker, thread, on_started, *, also_quit_on=())`,
the one-shot lifecycle wiring (moveToThread → `finished`→`quit` → `thread.finished`→`deleteLater`
→ start) every call site shares; the caller still creates the thread (so test patches of a
module's `QThread` keep working) and connects its own result slots first.

- **`rip_worker.py`** — `RipWorker(QObject)` moved to a `QThread`. Owns the rip subprocess. Emits `log_line(str)` for each line of whipper output, `progress(...)` for parseable progress events, `finished(success, rip_log_path)` on exit, `error(message)` on failure. Supports cancel via subprocess terminate + child-process cleanup.
- **`mb_worker.py`** — `MusicBrainzWorker(QObject)` moved to a `QThread`. Drives `MusicBrainzClient` calls (which can take a few seconds and shouldn't block input). Emits `releases_returned(list)` or `error(message)`. The one *persistent* worker (window lifetime), so it's wired by hand rather than via `start_worker_thread`.
- **`drive_setup_worker.py`** — `DriveSetupWorker(QObject)` moved to a `QThread`. Runs the wizard's `drive analyze` / `offset find` via cancellable `Popen` so closing the dialog mid-detection can't orphan a running process or strand the drive.
- **`host_setup_worker.py`** — `HostSetupWorker(QObject)` moved to a `QThread`. Runs any `StepEngine` (a Protocol in `deps/step_engine.py` that both `HostSetup` and `HostTeardown` satisfy — one worker drives setup and uninstall) off the GUI thread, relaying per-step `StepResult`s as signals; supports cancel at step boundaries.
- **`drive_list_worker.py` / `disc_info_worker.py`** — run `list_drives()` / `disc_info()` off-thread (both shell out to the backend, slow on a cold container); emit `finished`/`failed`.
- **`dependency_worker.py`** — runs `DependencyManager.check_all()` (the launch-time probe) off-thread; emits `finished(report)`.
- **`update_worker.py`** — `UpdateCheckWorker` (release lookup) + `UpdateInstallWorker` (download/verify/install with progress) off-thread.
- **`ctdb_worker.py`** — runs CTDB verify for a finished rip off-thread on a daemon thread (KDD-14 Phase 1; it can outlive any sane `wait()`, see architecture.md §3.2).

---

## 3. Pinned dependency list

**Canonical home: [`DEPENDENCIES.md`](DEPENDENCIES.md)** — the full table (pins,
last-upstream-release dates, licenses, status, replacement plans, the
retirement-review log, and the system tools surfaced via the dependency
subsystem). It is the single source; this section does not reproduce it.

The one architectural point that belongs here, not there: the unmaintained pins
(`musicbrainzngs==0.7.1`, and `whipper` itself) are each isolated behind an
adapter ABC (§5–§6), so an exact pin is safe — the adapter, not the GUI, owns
the assumption about that dependency's output shape, and a future swap is a
one-file change.

---

## 4. Dependency self-management subsystem (brief P0 #11)

Single subsystem, three resolution tiers. CLAUDE.md Critical Rule #6.

### Decision tree

```
DependencyManager.check_all()
│
├── for each spec in registry.SPECS:
│       probe = spec.check()              # ProbeResult(present, version, location)
│       if probe.present and probe.version >= spec.min_version:
│           report.ok.append(spec)
│       else:
│           report.missing.append((spec, probe))
│
├── classify report.missing by spec.tier_preference:
│       tier_a = [...]   # auto-install eligible
│       tier_b = [...]   # queued-install eligible
│       tier_c = [...]   # manual-prompt only
│
├── if tier_a:
│       show consent dialog listing the auto-installable items
│       on OK: AutoInstaller.install_all(tier_a)
│       failed items spill down into tier_b for retry
│
├── if tier_b:
│       PendingInstallsDialog(items=tier_b) → user clicks Install Selected
│       QueuedInstaller drives the loop
│       failed items spill down into tier_c
│
├── if tier_c:
│       for item in tier_c:
│           ManualInstallDialog(spec=item.spec, probe=item.probe)
│       user copies the search string; closes the dialog
│
└── return final DependencyReport (renders in Settings → Check Dependencies)
```

### Key properties

- **One registry, no scattered checks.** Adding MP3 (lame) or WAV (sox) support in P1 means appending a `DependencySpec` to `registry.py` — no other code change in `deps/`.
- **Tier eligibility is declared, not computed at call time.** Each spec names its preferred tier. The resolver itself doesn't decide tiers — it just executes.
- **Failures cascade downward.** If tier (a) fails (network blip, pipx missing), the item moves to tier (b). If tier (b) also fails, it falls to tier (c). The user always ends up at a working install path or a copyable search string.
- **No surfaced terminal commands** at tier (a) or (b). The subsystem runs them internally and shows progress. Tier (c) is the only place the user sees a literal command — and only inside the copyable text field, never as instructions to paste.
- **Idempotent.** Running `check_all()` twice in a row with no system changes produces an identical report; running it after the user has installed a missing dep reflects that immediately.

---

## 5. `WhipperBackend` adapter design

ABC plus one concrete implementation. The whole point is that v1 doesn't have to know whipper might be replaced.

### Interface

```python
class WhipperBackend(ABC):
    @abstractmethod
    def list_drives(self) -> list[DriveDescriptor]: ...

    @abstractmethod
    def disc_info(self, drive: str) -> DiscInfo: ...

    @abstractmethod
    def rip(
        self,
        drive: str,
        release_id: str,           # MBID — never an interactive prompt
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
    ) -> RipHandle: ...            # handle exposes cancel() and yields log lines

    @abstractmethod
    def version(self) -> str: ...
```

### v1 implementation: `WhipperHostExportedImpl`

- Holds a configurable path to the `whipper` binary (default `~/.local/bin/whipper`, overridable in settings).
- Each method shells out via `subprocess.run` (for one-shot info commands) or `subprocess.Popen` (for the streaming rip).
- Output is fed through the `parsers/` module — never parsed inline in the adapter.
- `rip()` returns a `RipHandle` with `.log_lines()` (iterator), `.cancel()`, `.wait() -> int`.

### `CyanripImpl` — implemented (KDD-18, 2026-06-08/09)

*(Superseded: this section originally reserved the slot without building it — KDD-08.
Built once whipper's cd-paranoia >587-offset bug failed real tracks on the BDR-209D.)*

- Implements the same ABC; selected by `Config.ripper_backend` (`"whipper"` default | `"cyanrip"`), read by `app.py` at startup.
- `list_drives()` scans `/dev/sr*` + sysfs (cyanrip has no list command; the scan is backend-independent).
- `disc_info()` runs `cyanrip -I -N` (offline — DiscID/CDDB are computed locally from the TOC) parsed by `parsers/cyanrip_info.py`.
- `rip()` does **not** use `cyanrip -R` (the originally sketched shape): cyanrip always gets `-N` and is fed the GUI's `RipMetadata` via `-a`/`-t` instead — deterministic release, no in-container network, Critical Rule #5 intact. Naming templates translate to `-D`/`-F` schemes.
- Still open: stdout progress parsing and cyanrip-log fidelity parsing (see TASKS).

---

## 6. `MusicBrainzClient` adapter design

ABC plus one concrete implementation. Same pattern: isolate the GUI from `musicbrainzngs`'s eventual retirement.

### Interface

```python
class MusicBrainzClient(ABC):
    @abstractmethod
    def releases_by_disc_id(self, disc_id: str) -> list[ReleaseSummary]: ...

    @abstractmethod
    def releases_by_toc(self, toc: TocSignature) -> list[ReleaseSummary]: ...

    @abstractmethod
    def release_by_mbid(self, mbid: str) -> ReleaseDetail: ...

    @abstractmethod
    def set_user_agent(self, app: str, version: str, contact: str) -> None: ...
```

`set_user_agent` is mandatory — MusicBrainz rate-limits unidentified clients.

### v1 implementation: `MusicBrainzNgsImpl`

- Wraps `musicbrainzngs`. Calls `musicbrainzngs.set_useragent(...)` at construction.
- Each query catches `musicbrainzngs.WebServiceError` and reraises as a project exception (`MusicBrainzQueryError`) so callers don't import the third-party exception type.
- Honors MB's 1 req/sec rate limit by relying on `musicbrainzngs`'s built-in throttling.

### Future: `RequestsJsonImpl`

For when `musicbrainzngs` finally bitrots. Same ABC, backed by `requests` against `https://musicbrainz.org/ws/2/...?fmt=json`. The risk is rate-limit handling — `musicbrainzngs` does it for us; with raw `requests` we'd add our own token-bucket. This is well-known territory.

---

## 7. Distribution strategy

### Primary: AppImage via `python-appimage`

CLAUDE.md Critical Rule #2: `python-appimage` is the builder. `appimage-builder` requires an explicit user OK to even consider.

#### What the AppImage contains

- A CPython 3.11 interpreter (provided by `python-appimage`'s manylinux base).
- All Python runtime deps from `build/python-appimage/requirements.txt` (PySide6, musicbrainzngs, tomli-w).
- The `whipper_gui` package source.
- Desktop integration metadata (`.desktop` file, icon).

#### What the AppImage does NOT contain

- `whipper` itself, `metaflac`, `libdiscid` — these are user-system deps, surfaced through the dependency subsystem.
- The Distrobox container — that's the user's responsibility, documented in `README.md`.

#### Build script shape

`build/build_appimage.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Run from the repo root.
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# Install python-appimage if not already present (dev tooling only).
python3 -m pip install --user "python-appimage>=1.4,<2"

# python-appimage's "build app" mode reads a small recipe directory
# (build/python-appimage/) plus our package source.
python3 -m python_appimage build app \
    --python-version 3.11 \
    --linux-tag manylinux2014_x86_64 \
    --name whipper-gui \
    build/python-appimage

# Output: ./whipper-gui-x86_64.AppImage at repo root.
```

`build/python-appimage/requirements.txt` is the exact pip-resolvable list for the bundle (locked versions per `DEPENDENCIES.md`).

`build/python-appimage/entrypoint.sh` (if needed) is the AppImage's `AppRun` script, kept as close to the python-appimage default as possible.

### Secondary: `pipx`-installable wheel

`pyproject.toml` declares the package with a `whipper-gui = "whipper_gui.__main__:main"` console-script entry point. Users on distros where AppImage is awkward can do:

```
pipx install whipper-gui
```

(This requires building and uploading the wheel — out of scope for v1's "ship something runnable" milestone; the entry point is still present so `pipx install ./` from a local checkout works.)

### Not in scope (yet)

- Flatpak: disqualified by the brief — sandbox cannot reliably reach `~/.local/bin/whipper`.
- Snap: same sandbox concerns; not worth the cost.
- Native RPM/DEB: out of scope per brief; revisit only if users demand it.

---

## 8. Key design decisions and rationale

The "why is it like this?" changelog. Read this before changing architecture.

### KDD-01 — PySide6, not PyQt6

PySide6 is LGPL-3.0; PyQt6 is GPL-3.0 (or paid commercial). PySide6 lets the project stay license-flexible — it can be redistributed inside an AppImage without forcing the whole codebase to GPL. PySide6 is the official Qt-for-Python binding (maintained by The Qt Company), which means release cadence tracks Qt itself. Brief Appendix A also names PySide6.

### KDD-02 — Bypass whipper's TTY prompt, never drive it with pexpect

Critical Rule #5. We obtain the MBID via `MusicBrainzClient` (a real adapter, with the option to swap the implementation), then invoke `whipper cd rip --release-id <MBID>`. Whipper sees a single deterministic answer and never opens a prompt. pexpect would couple us to whipper's prompt text, which is exactly the kind of "subprocess output detail" CLAUDE.md tells us not to depend on.

### KDD-03 — One DependencyManager, not scattered `shutil.which()` calls

Critical Rule #6. Every dependency check, install path, and minimum-version constraint lives in `deps/registry.py` as a declarative `DependencySpec`. Adding a new dep (MP3 encoder later, or anything else) is one entry in the registry — no other code changes. This survives drive-by edits and prevents the "the second place I needed it I just added a `which` call" drift.

### KDD-04 — `QThread`s, not asyncio

PySide6 has Qt's QThread/signal/slot model built in. Mixing asyncio with Qt's event loop requires `qasync` and adds another non-stdlib runtime concern. For an app with two background operations (rip, MB query), explicit `QThread`s are simpler and more readable for the project's stated maintainer profile.

### KDD-05 — `tomllib` for reads, `tomli-w` for writes

Python 3.11+ has `tomllib` in stdlib but it's read-only. `tomli-w` is the minimal, MIT-licensed companion writer. Avoids `tomlkit` (heavier, designed to preserve comments — overkill for a small config we own).

### KDD-06 — `libdiscid` may not be needed on the host

`musicbrainzngs` *can* compute a disc ID from `/dev/sr0` directly via `libdiscid`, but our flow doesn't need that: whipper (inside the Distrobox container) already computes the disc ID and exposes it via `whipper cd info`. We pass that disc ID into `MusicBrainzClient.releases_by_disc_id(...)`, which is a pure HTTP call — no `libdiscid` required on the host.

If this assumption holds, the dependency subsystem can downgrade `libdiscid` from tier (c) to "not actually required." Confirm during the first end-to-end smoke test (T21). If it turns out we do need it, it stays in tier (c) — `rpm-ostree install + reboot` is genuinely user-judgment territory and that's exactly what tier (c) exists for.

**RESOLVED (T32, 2026-05-29):** the assumption holds. A full real-hardware rip on Bazzite ran start-to-finish with **no libdiscid on the host** — whipper (inside the `ripping` container) computed the disc ID, the GUI read it from `whipper cd info` (and salvaged it from the partial output on unknown discs), and passed it to MusicBrainz over plain HTTP. `libdiscid` is **not** a host requirement and was never added to the registry.

### KDD-07 — AppImage carries the GUI only, not whipper

AppImages are unsandboxed, so calling `~/.local/bin/whipper` from inside one works. But bundling whipper into the AppImage would (a) duplicate what's already installed via Distrobox, (b) silently sidestep the host-exported binary the user has configured, and (c) violate Critical Rule #3 ("does not try to install or update whipper itself"). The AppImage ships the GUI; the user's existing Distrobox `ripping` container ships whipper. The README spells this out as a prerequisite.

### KDD-08 — Reserve, don't pre-build, the alternate adapter implementations

`WhipperBackend` and `MusicBrainzClient` are ABCs, and the brief calls out future alternatives (`cyanrip`, raw `requests`). v1 did not create empty `CyanripImpl` or `RequestsJsonImpl` skeletons — they would have been dead code. The ABC shapes are documented above so when retirement happens, the new impl can be added in focused PRs. CLAUDE.md's "no half-finished implementations" rule. *(This played out as designed: `CyanripImpl` was added post-v0.1.0 once a real whipper bug created the need — KDD-18 — without touching the GUI layer. `RequestsJsonImpl` remains reserved.)*

### KDD-09 — Tests live alongside the package, not inside it

`tests/` at repo root, not `src/whipper_gui/tests/`. The package shipped to end-users contains no test code or fixtures. pytest discovers via `tests/` directly.

### KDD-10 — License: GPL-3.0-only (decided 2026-05-30)

**Resolved.** The project is licensed **GPL-3.0-only** (canonical text in `LICENSE`).

Rationale: it's the natural fit for a Linux EAC successor — it aligns with the GPL CD-ripping ecosystem we build on (whipper GPL-3, cdparanoia, CUETools) and keeps the tool and any forks free software. No dependency forced the choice (it was a values call): PySide6 is imported under its LGPL-3 option, `musicbrainzngs` is BSD-2-Clause, `tomli-w` is MIT, and whipper / the future `ctdb-cli` are invoked as **subprocesses** (no linking), so their GPL never reaches into our code. `python-appimage` is GPL-3 but is a build tool, not part of the shipped runtime.

Metadata: signalled via the OSI classifier in `pyproject.toml` (the build-robust choice — PEP 639's SPDX `license` string needs setuptools ≥77 and clashes with the classifier on newer versions). setuptools auto-bundles the root `LICENSE` into the wheel.

### KDD-11 — Rip log: EAC-equivalent archival content, weaker integrity

Whipper's YAML-structured rip log captures every field EAC captures that bears on archival quality (drive, read offset, cache defeat, per-track CRCs, AccurateRip v1+v2 confidence). The `RippingInfo` sub-record on `RipLog` is shaped specifically to mirror EAC's archival header so the GUI can render the same "Rip details" panel a user gets from EAC.

The one real gap is **log integrity**: EAC signs its log with a checksum that CTDB and forum communities recognize as a tamper-evidence signal. Whipper writes a plain SHA-256 of the file contents, which is weaker forensically. This is not actionable from the GUI side — closing it would require whipper itself to implement an EAC-equivalent scheme. Documented for users in `docs/log-format-comparison.md`.

See `docs/log-format-comparison.md` for the full side-by-side. The comparison is anchored on a real upstream whipper test fixture (`tests/fixtures/rip_log_real_whipper_0_7.log`) and a representative EAC v1.6 log (`tests/fixtures/rip_log_eac_reference.log`, hand-authored to match Hydrogenaudio/CueTools documentation).

### KDD-12 — AccurateRip + CTDB scope, corrected from the brief

The brief lists "AccurateRip submission" and "CTDB verification" as confirmed Linux ecosystem gaps and pushes both out of scope. After researching the current state (chat log 2026-05-28), the framing was sharpened — the original wording was both too pessimistic about what's actually possible and conflated technical and policy constraints.

- **AccurateRip verification (reading):** supported on Linux today and **already a delivered feature of this project**. Whipper queries AccurateRip during every rip; the rip log carries per-track v1/v2 confidence; our `parsers/rip_log.py` extracts them; `ui/rip_progress.py` renders them. Cyanrip, fre:ac, and Python Audio Tools also support reading. Not a gap.

- **AccurateRip submission (writing):** technically possible, but the AccurateRip operators accept submissions only from EAC and dBpoweramp (community-trust gate to prevent database pollution). A Linux tool implementing the upload protocol would have its entries rejected. Stays out of scope — but for *policy* reasons, not technical ones.

- **CTDB verification (reading):** technically possible on Linux but unimplemented anywhere. The CueTools Database server is LGPL'd; the reference client is on GitHub (`gchudov/cuetools.net`). The protocol is derivable from that code. CueTools.net itself is Windows-only (.NET Framework 4.7, no Mono support documented), but the protocol it speaks isn't. **Moved from "out of scope" to P1 backlog** as a real but bounded engineering opportunity (~200-400 lines for a Python client + UI hookup).

- **CTDB submission:** likely subject to the same trust-gate as AccurateRip submission. Stays out of scope.

- **CTDB repair (parity):** confirmed **in scope** (user request, 2026-05-30). The unique capability beyond verification — reconstructing corrupted samples in a damaged rip from a downloaded recovery record. See **KDD-14** for the phased plan and the decision to *wrap* `ctdb-cli` rather than reimplement the erasure coding.

The practical takeaway: archival verification on Linux is already solid — AccurateRip is wired through and visible in the GUI. Adding CTDB as a second verification path is post-v1 work whose cost is manageable.

### KDD-13 — EAC bit-perfect settings audit

We benchmark our defaults and exposed settings against the widely-cited "Perfect CD ripping to FLAC with Exact Audio Copy" guide (flemmingss.com), which represents the community gold standard for bit-perfect archival rips on Windows.

**Matches (already in scope or delivered):**

| EAC setting | Our path |
|---|---|
| Secure mode + Accurate Stream | cdparanoia paranoia mode is whipper's default |
| Drive caches audio data → defeat | `defeats_cache = True` in whipper.conf (set per drive) |
| Read offset calibration | `whipper drive analyze` + `whipper offset find` (README step 5) |
| Use AccurateRip | whipper queries AR every rip; we render results in rip-progress (KDD-12) |
| Error recovery quality: High | cdparanoia is always at maximum |
| No normalize | whipper does not normalize; bit-perfect intact |
| FLAC `--verify` | whipper passes `--verify`, proves bit-perfect reversibility |
| Status report (.log) after rip | whipper writes; our parser captures |
| Checksum on status report | SHA-256 (caveat: weaker than EAC's signed checksum; KDD-11) |
| Gap detection (Secure) | whipper uses cdrdao for gap detection |
| Track/Disc filename template | configurable in Settings dialog |
| Detect drive features auto-test | `whipper drive analyze` |
| CUETools DB metadata plugin | We use MusicBrainz; CTDB verify (P1) + parity repair (in scope) — KDD-12, KDD-14 |

**Upstream-locked (whipper hardcodes, can't expose from our GUI):**

- **FLAC compression level.** EAC guide specifies `-8 --best`; whipper hardcodes `flac --silent --verify -o … -f …` with no compression flag, so flac defaults to `-5`. Compression level is purely a file-size tradeoff — archival quality is identical at any level because of `--verify`. README documents the post-rip re-encode workaround.

**Linux ecosystem gaps (not actionable):**

- **C2 error pointers.** Whipper does not use them; cdparanoia is the Linux secure-read primitive instead. The original brief flags this as a known Linux gap.
- **EAC-style signed log checksum.** SHA-256 is weaker as a forensic signal; KDD-11 covers this.
- **CUETools DB metadata plugin** (write side of CTDB). KDD-12 puts CTDB *verification* in P1; submission stays out of scope.
- **AccurateRip submission.** Policy-blocked by AR's operators; KDD-12.

**Surfacing gaps (added to P1 backlog):**

EAC exposes a handful of toggles that whipper *also* supports via CLI flags but that we hadn't surfaced. The audit identified five — each is a small Config field + Settings widget + `RipParameters` plumb-through:

1. Cover art mode (`-C`)
2. Force overread (`-x`)
3. Max retries (`-r`)
4. Keep going on track failure (`-k`)
5. Continue on CD-R (`--cdr`)

These are listed in TASKS.md under "P1 — EAC bit-perfect parity gaps" and should land before the AppImage's first public release so users coming from EAC find the controls they expect.

**Verification needed — ANSWERED by T32 (2026-05-29):**

- **Does whipper emit a `.cue` sheet alongside the FLACs?** Yes. A real rip wrote `<disc>.cue`, `<disc>.m3u`, and `<disc>.toc` next to the FLACs (plus the `.log`). The `.cue` carries `REM DISCID`, per-track `INDEX`/`ISRC`, and the gap (`INDEX 00`) data. Surfacing the `.cue` in the rip-progress widget the way we surface the `.log` is a small P1 addition.
- **Does whipper capture per-track ISRC and disc UPC?** The slots exist — the `.cue` has `CATALOG` (UPC) and per-track `ISRC` lines, and the `.toc` has `ISRC` per track — but on the CD-R tested they were all zeros (`CATALOG 0000000000000`, `ISRC 000000000000`) because the disc carries no subchannel ISRC/UPC. A pressed commercial disc would populate them; capturing them into our `RipLog`/UI is a P1 evaluation once a disc with real ISRCs is on hand.

### KDD-14 — CTDB integration: verify (Python), then repair (wrap `ctdb-cli`; shipping TBD)

The CUETools Database adds two capabilities beyond AccurateRip: a second cryptographic *verification* path, and — uniquely — *active parity repair* that reconstructs corrupted samples in a damaged rip from a downloaded whole-CD recovery record. Both are confirmed in scope (user request, 2026-05-30). Sequenced as two phases sharing one `CTDBClient` adapter:

- **Phase 1 — verify (read-only).** *Library landed 2026-06-03* (`adapters/ctdb_client.py` + `whipper_gui/ctdb/`, with `scripts/ctdb_verify.py` and 35 unit tests). Pure-Python client (same shape as `MusicBrainzClient`): compute the disc CRC over the decoded audio, query CTDB by TOC, render confidence next to the AccurateRip result. No new system dependency; bundles in the AppImage trivially. Built **clean-room from the LGPL reference** (`gchudov/cuetools.net`) per KDD-16 — we deliberately did **not** read or port the GPL-2.0-only `python-cuetoolsdb`. This is the existing P1 "CTDB verification" item (KDD-12). **Concrete spec + open issues: [docs/archive/upstream-modification-investigation.md](docs/archive/upstream-modification-investigation.md).** *GUI wiring landed 2026-06-17* (opt-in Settings toggle → off-thread `workers/ctdb_worker.py` → verdict under the AccurateRip table), kept behind the safety seam so a match reads **experimental** while unvalidated. Two pieces remain gated on a real CD that's in CTDB — the `toc=` wire format and the bit-exact CRC (`crc.CRC_VALIDATED=False`, fails safe); see [docs/test-plan.md](docs/test-plan.md) Test 1. Flipping `CRC_VALIDATED` after that is the only remaining step.

- **Phase 2 — repair (parity).** Download the recovery record (~180 KB, parity is whole-CD, not per-track), reconstruct corrupted samples via erasure coding, then re-verify. **Decision: Option A — wrap the existing `ctdb-cli` tool** (`github.com/Masterisk-F/ctdb-cli`; builds with `./configure && make`), NOT a pure-Python port of `CUETools.Parity`. Rationale: this is the same "orchestrate a trusted tool, don't reimplement forensic math" thesis that made us delegate extraction to whipper rather than to libcdio directly. A Python Galois-field Reed-Solomon port would have to bit-match CUETools' format exactly — high risk for no architectural gain. **CORRECTION (2026-06-02): `ctdb-cli` is C#/.NET 10, NOT a C tool** (an earlier research note had this backwards). It is therefore **not cheap to vendor** — bundling it pulls in the .NET runtime. Re-decide bundling vs. optional-install when Phase 2 starts; see the investigation doc.

Implementation decisions (all 2026-05-30; vendoring revisited 2026-06-02):
- **Repair needs no optical device** — it operates on the already-ripped files plus the downloaded parity, so it does not require the Distrobox container and is not gated by drive permissions. It is reached through a thin `CTDBRepair` adapter (mandatory per the unmaintained-dependency rule) so a future replacement is a one-file swap. **Open: how to ship `ctdb-cli`** — bundling a .NET app in the AppImage is heavy (see correction above), so weigh bundling a self-contained .NET publish vs. routing it through the dependency subsystem as an *optional* user-installed tool (like Picard). Not decided.
- **Explicit trigger first.** v1 surfaces an "Attempt CTDB repair" action only when a rip finishes with uncorrectable errors — transparent and testable. The fully-automatic "silently repair on error" model is a later refinement, not v1.
- **Submission shelved.** Contributing parity back to CTDB is opt-in power-user territory and likely subject to the same trust-gate as AccurateRip submission (KDD-12). Out of scope for now.

Net effect: the project becomes a superset of EAC's workflow — EAC needs CUETools as a *separate* application for parity repair; we integrate it.

### KDD-15 — Drive setup wizard writes `whipper.conf` (via whipper's own commands)

The biggest first-run friction is calibrating the drive: today the user hand-edits `whipper.conf` with an offset they looked up manually. A guided wizard fixes this, and (user decision, 2026-05-30) it is allowed to **write** `whipper.conf`.

To avoid *owning* whipper's config format (which would undercut the "`whipper.conf` is authoritative" principle and the adapter rule), the wizard drives whipper's OWN commands through the sacred `~/.local/bin/whipper` routing — `whipper drive analyze` (cache profile) and `whipper offset find` (offset; needs a CD that is in AccurateRip) — and lets whipper persist what it can. For anything whipper does not auto-persist, a thin adapter writes it after **backing up `whipper.conf` → `whipper.conf.bak`** and showing the user the before/after values to confirm. Re-runnable and reversible.

Fallback when `offset find` fails (no AccurateRip CD inserted, or whipper's admittedly "primitive" detection misfires): a manual-entry box. **Shipped 2026-05-31** — the wizard has a read-offset spinbox + "Save offset" (with a link to the AccurateRip drive-offset list for lookup). To avoid authoring `whipper.conf` (this KDD's whole point), the manual value is persisted as the GUI's `--offset` override (`Config.read_offset` + `override_read_offset`), not written into whipper's per-drive section. Paired with a **first-run offer**: if no offset is configured (`offset_config.is_offset_configured()` checks whipper.conf *and* the override), the GUI offers the wizard once on launch (`Config.drive_setup_prompted` guards re-nagging) — whipper refuses to rip without an offset, so a CD-R-only user would otherwise be stuck. Automated drive-model→offset *lookup* against the AccurateRip database (auto-filling the field) remains deferred; the user looks it up via the link for now.

Side effect: this resolves the "misleading read-offset field" UX bug (TASKS.md, P1 UX gaps) — Settings becomes read-only/informational with a "Re-detect…" button that launches the wizard, which becomes the single place the offset is set.

### KDD-16 — CTDB verify is built **clean-room** from the LGPL reference (no GPLv2 port)

Decided 2026-06-02, ahead of implementing KDD-14 Phase 1. **The question:** can we reuse the existing Python CTDB client, `bmwalters/python-cuetoolsdb`, to build verify? **The answer: no — implement clean-room instead.**

- **License facts (verified, not assumed).** We are **GPL-3.0-only** (KDD-10: `pyproject.toml` classifier + GPLv3 `LICENSE`). `python-cuetoolsdb` ships a bare **GPLv2** `LICENSE` file but declares **no version intent** anywhere the author controls — `setup.py` has no `license=` field and no Trove classifiers, and the source files carry no header/SPDX line. (A web check that reported "or later" was reading the boilerplate *"How to Apply These Terms"* appendix inside the GPLv2 text, not an author election.) With no "or later" grant we must treat it as **GPL-2.0-only**, which is **one-way incompatible** with GPL-3.0-only — we cannot copy or line-by-line port its code into our work.

- **Why clean-room is clean.** Copyright protects *code expression*, not the **protocol, wire format, or CRC algorithm** — those are facts/methods. Reimplementing them independently is not a derivative work. So we build our own `CTDBClient` from (a) the **LGPL** `gchudov/cuetools.net` source (LGPL is GPLv3-compatible) and (b) the public DB behaviour, ship it under our GPL-3.0-only, and **never read or paraphrase `python-cuetoolsdb`**. The implementer learns the algorithm from the LGPL C# + the spec, then writes original Python. SPDX `GPL-3.0-only` header on every new file.

- **Rejected alternative:** ask the upstream author to relicense as GPLv2-or-later. Slower, depends on a third party, and only buys the right to copy code we don't need — clean-room is faster and removes the dependency entirely.

- **Net effect:** the license gate that blocked KDD-14 Phase 1 is **closed**. The concrete protocol/CRC spec (grounded in the LGPL `CUEToolsDB.cs` + `CUETools.AccurateRip`/`CUETools.Parity`) lives in [docs/archive/upstream-modification-investigation.md](docs/archive/upstream-modification-investigation.md). The only remaining blocker is **hardware validation** — the locally-computed CRC must be confirmed against a real CD that is in CTDB (a T32-style test the cloud env can't run).

### KDD-17 — Zero-CLI distribution: self-integrating + self-updating AppImage + GUI first-run host wizard

Decided 2026-06-04 (user-approved; this is a sanctioned evolution of the distribution model per Critical Rule #2 / the deviation policy). **The goal:** a non-technical user touches no terminal — download one file, double-click, done. **The constraint that shapes everything:** the app is *not* self-contained — it routes through a host Distrobox container with whipper inside (Critical Rule #3), so the genuinely hard part is host setup, not GUI delivery.

**Decisions:**

- **The AppImage stays the single downloadable file.** It is the only Linux "one file you download and run" that works without a package manager. The remaining friction — the executable bit / file-manager "Allow executing" tick — is irreducible for a downloaded binary and is accepted.
- **Self-integrate on first run.** The app offers "Add me to the application menu?" and installs its own `.desktop` + icon, superseding the *user-facing* need for `install-appimage.sh`. (The script stays for scripted/CI installs.)
- **Self-update via the standard AppImage mechanism.** Embed AppImage update-information (zsync) and verify against the `.sha256` we already publish — this *is* the "check a manifest, skip if current, else download only the delta" pattern the user described, so we do **not** hand-roll a bespoke download stub (more code + supply-chain surface, reinvents a solved thing).
- **Move host setup into a GUI first-run wizard**, owned by the dependency self-management subsystem (Critical Rule #6 — one subsystem, no scattered checks). It does what `setup-host.sh` does (create the `ripping` container, install whipper + flac + metaflac in it, `distrobox-export`) but as buttons + progress, driving **rootless** podman/distrobox directly. On the primary target (Bazzite/Silverblue) the runtime is preinstalled, so this is fully click-driven with no elevation. On distros lacking the runtime, a **single polkit-elevated step** installs it (the one unavoidable privilege prompt; atomic distros may also need a reboot). `setup-host.sh` remains the CLI equivalent.

**Rejected alternatives:**

- **Flatpak / Flathub** — the only *true* one-click, auto-updating, store-installed Linux path, **but the sandbox cannot reach host `~/.local/bin/whipper` / Distrobox** without `flatpak-spawn --host` holes that gut the sandbox and contradict Critical Rule #3. Not adopted; revisit only as a deliberate architecture change.
- **A bespoke "stub that reads a remote config and downloads from source"** — superseded by AppImage update-information, which already does skip-if-current + delta fetch + verification.
- **A downloaded `.desktop` or shell-script "installer"** — blocked by the Linux desktop trust model (untrusted `.desktop` won't run; double-clicked scripts open in an editor).

**Sequencing note:** the self-integrate + self-update pieces are independent of the host wizard and can ship first; the host wizard is the larger lift and the bigger UX win.

**Amendment (2026-06-10, user-requested):** the original "never hand-roll the download — delegate to AppImageUpdate" call was reversed after real-world testing: `appimageupdatetool` isn't installed on the target systems (and is awkward to install on atomic distros), so the delegate path dead-ended in a browser download, a manual file swap, and a stale menu entry. The app now updates **in-app**: `update_install.py` downloads the release asset off-thread with progress, **verifies it against the published `.sha256`**, atomically installs it over `~/Applications/whipper-gui-x86_64.AppImage`, re-integrates the menu entries, and offers to restart into the new version (launch new + close old). The zsync update-information stays embedded, so AppImageUpdate delta updates remain possible for users who have the tool. Integration also re-offers per-file now (a declined offer silences only that exact file, so updates get their shortcuts remade).

**Status: all three slices SHIPPED** — (a) self-integration 2026-06-05, (c) host wizard 2026-06-05 (+ cyanrip step 2026-06-09), (b) self-update 2026-06-09 (zsync update-information embedded by an appimagetool re-pack in `build_appimage.sh`; `.zsync` uploaded by release.yml; in-app Help → Check for updates… delegates to AppImageUpdate or the release page). Remaining proof is hardware/release-gated: a real delta update needs two consecutive releases with the embed (v0.2.0 → v0.3.0).

### KDD-18 — cyanrip is the strategic successor backend; never fork whipper

Decided 2026-06-04 after a researched ecosystem audit ([docs/archive/ecosystem-audit-2026-06.md](docs/archive/ecosystem-audit-2026-06.md)), prompted by whipper's `offset find` failing on real hardware (Pioneer BDR-209D) and the question of long-term foundation.

- **whipper is effectively stalled.** Last release **v0.10.0, 2021-05-17 (~5 years)**; it imports `pkg_resources`, which is gone from setuptools ≥81 and Python 3.14 — a known compatibility cliff we currently paper over by installing `python3-setuptools` in the container. It still rips correctly today (Fedora packages 0.10.0), so this is a monitored risk, not an emergency.
- **cyanrip is the successor** (active: v0.9.3.1, 2024-06-05; C + FFmpeg; LGPL-2.1; AccurateRip v1/v2 + EAC CRC32 + MusicBrainz + ReplayGain; no Python cliff). We invoke rippers as subprocesses, so LGPL-2.1 is fine against GPL-3.0-only.
- **Decision:** keep whipper now; build **`CyanripImpl`** behind the existing `WhipperBackend` ABC as a config-selectable second backend (the ABC was designed for exactly this). **Never fork whipper** — forking inherits its maintenance burden + the `pkg_resources` cliff; if ripper-level changes are ever needed, contribute to *cyanrip* (active) instead. Writing our own ripper and upstreaming our GUI into whipper are both rejected (see the audit's options table).
- **CTDB is backend-independent** — neither ripper does it; our clean-room `ctdb/` library (KDD-16) rides above whichever backend is selected, so this decision doesn't touch it.
- **Backend-independent near-term win:** auto-look-up the drive's read offset from the AccurateRip offset list by drive model, so users never type an offset — this is what would have prevented the BDR-209D friction, and it's independent of the whipper-vs-cyanrip choice.
- ~~**Open feasibility unknown:** cyanrip's packaging for the Fedora-toolbox `ripping` container.~~ **RESOLVED 2026-06-09:** Fedora and RPM Fusion do not package cyanrip; the COPR `barsnick/non-fed` does (0.9.3.1, GPG-checked, F42–44). The host-setup wizard installs + exports it when the cyanrip backend is selected; fallback is a meson source build from Fedora-proper deps. See the audit doc's "Packaging research" section.
- **Status (2026-06-09):** phases 1–5 shipped (impl, Settings toggle, container packaging, `disc_info`, metadata model + template mapping + unified backend-aware Settings). Remaining: stdout progress parsing, cyanrip-log fidelity parsing, hardware parity run — tracked in TASKS item 9.

### KDD-19 — Decompose `MainWindow` via mixins, not collaborator objects (decided 2026-06-13)

`MainWindow` had grown to ~1700 lines — a god-object spanning rip control, self-update, host setup, drive calibration, dependency UI, cover art, and MusicBrainz handling. The "split when a file exceeds ~300 lines / one responsibility per module" convention demanded a split, but the obvious OOP move (extract collaborator objects) was rejected:

- **Why not collaborator objects:** the test suite reaches into ~50 distinct `window._method`/`window._attr` internals (driving slots synchronously, asserting state, connecting to signals). Extracting methods onto separate objects would have forced rewriting that entire test surface — high risk against the "no new bugs / lose no function" bar — and changed the public-ish shape every Qt signal connection relies on.
- **Decision: mixins.** Cohesive concern-groups move verbatim into `main_window_*.py` modules as plain (non-Qt) mixin classes that the concrete `MainWindow(QMainWindow, RipMixin, UpdateMixin, …)` inherits. Methods stay reachable as `window._x`; signals defined on the concrete class still resolve from mixin methods (verified by a PySide6 spike before committing). Each mixin documents the `self.` attributes it expects `__init__` to have set — that contract *is* the coupling, made explicit. Pure free functions go to `main_window_helpers.py` instead of a mixin.
- **Trade-off accepted:** mixins are a mild "where does this method live?" indirection, mitigated by the ownership table in `docs/architecture.md` and per-mixin docstrings. This is *not* the "clever metaprogramming" the conventions forbid — no metaclasses, no dynamic class creation; just multiple inheritance of focused method groups.
- **Hard-won testing lesson (also in `docs/architecture.md` §5 and `docs/testing.md`):** when a method moves to a new module, any test that monkeypatched a *module-level name* it uses (`mw.is_offset_configured`, `mw.RipWorker`) silently stops intercepting — the moved method resolves the name through its *new* module. During this refactor that briefly let a test start a real rip thread in headless mode (a hard abort). Fix: patch where the code now lives, or patch the function's **source module** and call it module-qualified so one patch point covers every caller. Patching an attribute on a *shared module object* (`drive_control.eject_drive`) is unaffected by caller location.
- **Status:** COMPLETE (2026-06-13). All six concern-groups extracted — `main_window_helpers.py` (pure fns) + `UpdateMixin` / `RipMixin` / `ProvisioningMixin` / `DriveMixin` / `DependencyMixin`. `main_window.py` 1707 → ~460 lines (a pure assembler: construction, menus, signal wiring, MusicBrainz slots, Settings). Every extraction was test-guarded (777 tests green throughout); the monkeypatch-target lesson is documented in `docs/architecture.md` §5 and `docs/testing.md`.

### KDD-20 — Documentation currency is enforced via an autoloaded anchor + checklist + CI backstop (decided 2026-06-20)

Decided after a session where the code and `CHANGELOG.md` stayed current but `docs/session-log.md` and lesson-graduation drifted until the maintainer called it out ("if you aren't updating, are you even reading these files? … how do we make it part of the procedure every time?").

- **Diagnosis.** The CHANGELOG never drifted because `CLAUDE.md` gives it a *per-commit rule with teeth* ("add a bullet in the same commit"), and `CLAUDE.md` is the one file injected into **every** session. The session-log + graduation had only soft "do it at milestones" framing, so they were deferred. The fix is to give them the same teeth, in the same always-read place.
- **Decision — three layers, daisy-chained off the autoloaded file:**
  1. **Anchor** — `CLAUDE.md` **Critical Rule #7** ("Documentation currency is part of Done"): CHANGELOG bullet in the same commit · session-log entry before session end · graduate every durable lesson to its home. It's the always-loaded entry point and *points outward* to the rest.
  2. **Detail** — `docs/testing.md §6` Definition of Done carries the concrete checklist items, each tagged back to Rule #7 (a bidirectional link).
  3. **Backstop** — a CI `changelog` job (`.github/workflows/ci.yml`) that fails any push/PR with no `CHANGELOG.md` change; a pure historical-record commit opts out with a `[skip changelog]` line of its own.
- **Why this shape.** For an LLM agent the highest-leverage lever is the file guaranteed to be loaded every session — a rule placed anywhere else gets deferred. CI catches the one piece a machine *can* check ("was the file touched"); it cannot judge whether a lesson was actually graduated, so the **rule, not CI, is the primary mechanism**. This deliberately mirrors the existing institutional "every shipped bug gets a regression test in the same change" rule.
- **Implementation lesson (the gate's own first bug).** The opt-out matcher first used a substring grep for `[skip changelog]`, which matched the commit message that *documented* the marker — a self-skip. Fixed to require the marker as its own line (`^\s*\[skip changelog\]\s*$`): prose mentions never match, deliberate opt-outs do. Caught by a local simulation before push and confirmed green in real CI.
- **Status:** SHIPPED (2026-06-20). Rule #7 + `testing.md §6` items + the CI `changelog` job are all live; the `changelog` job was confirmed `success` on the introducing commit (and the `[skip changelog]` opt-out on the follow-up record commit).

### KDD-21 — Behaviour-preserving refactor: shared composition root, step-engine module, and one worker-thread helper (decided 2026-06-22)

A whole-codebase, behaviour-preserving refactor (user-requested "complete refactor") to cut redundancy, improve readability, and split/merge by cohesion. No feature or contract change; the 943-test suite stayed green at every commit (now 950) and branch coverage rose 92.04 % → 92.43 %. The structural decisions worth recording:

- **One composition root (`composition.py`).** `app.py` and `preflight.default_context()` each built the same adapters (backend selection + host-exported-path fallback, MusicBrainz client, contact URL). They now both call `composition.build_backend()` / `build_musicbrainz_client()`, so the GUI and `--doctor` can't wire the adapters differently. The trivial zero-arg adapters (`CtdbHttpImpl`, `DependencyManager`) stay inline at each site — wrapping them would add indirection without removing duplication. `app.py` imports it *inside* the startup-guard `try:` so an import failure still surfaces the fatal dialog.
- **Step-engine vocabulary split out (`deps/step_engine.py`).** `StepStatus`/`StepResult`/`CommandRunner`/`SubprocessRunner`/`StepEngine` were defined in `host_setup.py`, so the *teardown* engine imported its core types from the *setup* engine — a backwards sibling dependency. They moved to their own module both engines (and the worker + dialogs) depend on. This is the canonical "split a file that's secretly doing two jobs" — driven by the import graph, not a line count.
- **One worker-thread lifecycle helper (`workers.start_worker_thread`).** Eight one-shot call sites repeated the same moveToThread → `finished`→`quit` → `thread.finished`→`deleteLater` → start wiring. The helper centralises it but **takes the thread the caller created** (rather than constructing it), so a test patching a module's `QThread` still intercepts — the design choice that made this low-risk. A base class was rejected (the prompt's own steer and ours): the signal shapes differ per worker (single `finished` vs `finished`+`failed` vs `step`+`finished`), and the persistent MusicBrainz worker doesn't fit the one-shot teardown at all, so it's left wired by hand.
- **DRY within modules.** `offset_config` collapsed two parse paths + two identical file-read blocks into one section scanner + one reader (two filters preserve the deliberate difference that "any offset set?" spans all sections while "per-drive offsets" do not — pinned by a new characterization test). The two backends' `_run_capture`/`_run` became one `run_capture()` (per-backend timeout kept on purpose). `find_offset`'s function-local `import re` hoisted to module top.
- **Lessons (graduated so we don't repeat them):**
  - **A shared helper relocates where a name resolves — move the monkeypatch target with it.** Routing cyanrip's `_run` through `whipper_backend.run_capture` meant `subprocess.run` now resolves in `whipper_backend`, so the cyanrip tests' patch moved there too (the same rule as KDD-19 / architecture.md §5, now with a *non-mixin* example).
  - **For Qt-thread wiring, keep object *construction* at the call site and centralise only the wiring.** Passing the thread in (not creating it in the helper) is what preserved every `module.QThread` test patch — construct-in-helper would have silently bypassed them.
  - **Running the real entry points during QA finds what the suite can't.** `whipper-gui --doctor`, run for real in the QA sweep, exposed a *pre-existing* crash (`HostSetup()` built without its required `runner` on the never-tested `host=None` path). Flagged and fixed separately (its own commit + regression test + CHANGELOG), never folded into a refactor commit — the "find a bug → stop and flag, don't silently fix inside a refactor" discipline.
