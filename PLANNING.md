# PLANNING.md — Whipper GUI Architecture and Design

This is the architecture document. It captures *how* the GUI is built. For *what* to build, see the brief (`docs/whipper-gui-research-brief-v2.1.md` once archived). For *which sessions are working on which slice*, see `TASKS.md`. For *which deps are pinned and why*, see `DEPENDENCIES.md`.

This file is **living**. When an architectural decision is made or revisited, update the relevant section here. The Key Design Decisions section at the bottom is the changelog of architectural intent — future-you reads it to understand "why is it like this?"

---

## 1. Directory tree

Every file the project intends to create. New files added during a task should be reflected back here when the task completes.

```
Whipper-GUI-Frontend---CD-Rip/
├── CLAUDE.md                            # persistent project context (locked rules)
├── PLANNING.md                          # this file — architecture and design
├── TASKS.md                             # active task checklist
├── DEPENDENCIES.md                      # dep table with release dates + replacement plans
├── README.md                            # outward-facing description
├── pyproject.toml                       # package metadata + pinned deps + entry points
├── .gitignore
├── .gitattributes                       # (already present)
│
├── docs/                                # archived brief + research, plus design notes
│   ├── whipper-gui-research-brief-v2.1.md
│   └── (compass_artifact_*.md when produced)
│
├── build/                               # everything related to producing the AppImage
│   ├── build_appimage.sh                # one-shot build script (calls python-appimage)
│   └── python-appimage/
│       ├── requirements.txt             # pip deps bundled into the AppImage
│       └── README.md                    # build-time prerequisites and gotchas
│
├── tests/                               # pytest test tree
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_whipper_backend.py
│   ├── test_musicbrainz_client.py
│   ├── test_metaflac_adapter.py
│   ├── test_rip_log_parser.py
│   ├── test_drive_list_parser.py
│   ├── test_cd_info_parser.py
│   ├── test_dependency_manager.py
│   ├── test_config.py
│   └── fixtures/
│       ├── sample_rip.log
│       ├── sample_drive_list.txt
│       └── sample_cd_info.txt
│
└── src/
    └── whipper_gui/
        ├── __init__.py                  # package version + metadata
        ├── __main__.py                  # `python -m whipper_gui` entry point
        ├── app.py                       # QApplication construction + startup sequence
        ├── config.py                    # TOML config load/save + defaults + schema
        ├── logging_setup.py             # logging configuration (rotating file + console)
        ├── paths.py                     # user dirs, config path, log path constants
        │
        ├── adapters/                    # ALL calls into external tools go through here
        │   ├── __init__.py
        │   ├── whipper_backend.py       # WhipperBackend ABC + WhipperHostExportedImpl
        │   ├── musicbrainz_client.py    # MusicBrainzClient ABC + MusicBrainzNgsImpl
        │   └── metaflac.py              # MetaflacAdapter (tag write-back)
        │
        ├── deps/                        # dependency self-management subsystem (brief P0 #11)
        │   ├── __init__.py
        │   ├── manager.py               # DependencyManager — single orchestrator
        │   ├── registry.py              # declarative DependencySpec list
        │   ├── checks.py                # probe functions (present? version?)
        │   ├── resolvers.py             # AutoInstaller, QueuedInstaller, ManualPrompt
        │   └── version.py               # version-string parsing utility
        │
        ├── parsers/                     # whipper stdout/log parsing (named-group regexes)
        │   ├── __init__.py
        │   ├── rip_log.py               # parse the `.log` file whipper writes per rip
        │   ├── drive_list.py            # parse `whipper drive list`
        │   └── cd_info.py               # parse `whipper cd info`
        │
        ├── ui/
        │   ├── __init__.py
        │   ├── main_window.py           # MainWindow — central layout + signal wiring
        │   ├── drive_picker.py          # drive dropdown widget
        │   ├── disc_info_panel.py       # TOC / MB match / AccurateRip availability
        │   ├── release_picker.py        # modal: pick from multiple MB matches
        │   ├── track_table.py           # editable per-track table pre-rip
        │   ├── rip_controls.py          # Start/Cancel buttons + parameter assembly
        │   ├── rip_progress.py          # live progress + AccurateRip results + log viewer
        │   ├── settings_dialog.py       # settings page
        │   ├── unknown_album.py         # unknown-album helper flow
        │   └── dialogs/
        │       ├── __init__.py
        │       ├── pending_installs.py  # tier (b) queued installs dialog
        │       └── manual_install.py    # tier (c) copyable search string dialog
        │
        └── workers/                     # long-running operations off the GUI thread
            ├── __init__.py
            ├── rip_worker.py            # drives the whipper rip subprocess
            └── mb_worker.py             # drives MusicBrainz queries
```

---

## 2. Per-module responsibility

One paragraph per module, no more. If a module's paragraph creeps beyond a few sentences, the module is probably doing too much.

### Top-level

- **`__init__.py`** — exposes package version (read by `pyproject.toml` and `--version` CLI). No runtime logic.
- **`__main__.py`** — invoked by `python -m whipper_gui`. Imports and calls `app.main()`. Stays tiny so packaging tools and AppImage entry points have a stable target.
- **`app.py`** — builds the `QApplication`, instantiates the `DependencyManager` and runs its initial check (which may show install dialogs before the main window appears), then constructs and shows the `MainWindow`. Wires logging early so any failure during startup is captured.
- **`config.py`** — pure-Python TOML config loader/saver. Reads `~/.config/whipper-gui/config.toml` via `tomllib` (stdlib in 3.11+), writes via `tomli-w`. Defines the default config dict and a schema version. Atomic writes (temp file + rename) so a crash mid-save doesn't corrupt the file.
- **`logging_setup.py`** — configures Python's `logging` module once at startup. Rotating file handler at `~/.local/share/whipper-gui/log.txt`, plus a console handler at INFO. Project modules use `logging.getLogger(__name__)` everywhere; no module configures handlers itself.
- **`paths.py`** — module-level constants for the user config dir, log dir, and any other path computed from `XDG_*` env vars or hard-coded fallbacks. Single source of truth so paths aren't recomputed at call sites.

### Adapters (`adapters/`)

Every call into an external tool goes through this layer. CLAUDE.md Critical Rule #1 makes adapter layers mandatory for unmaintained deps; we apply the same pattern to `metaflac` for consistency.

- **`whipper_backend.py`** — defines `WhipperBackend`, an abstract base class with the methods the GUI needs (`list_drives()`, `disc_info(drive)`, `rip(...)`, `cancel()`). The v1 concrete implementation is `WhipperHostExportedImpl`, which `subprocess`-invokes `~/.local/bin/whipper`. A future `CyanripImpl` could implement the same ABC; the choice would be a config setting.
- **`musicbrainz_client.py`** — defines `MusicBrainzClient` ABC with `releases_by_disc_id(disc_id)`, `releases_by_toc(toc)`, `release_by_mbid(mbid)`. v1 implementation `MusicBrainzNgsImpl` wraps `musicbrainzngs`. A `RequestsJsonImpl` is reserved for the day `musicbrainzngs` finally bitrots — it would hit `https://musicbrainz.org/ws/2/...?fmt=json` directly with `requests`.
- **`metaflac.py`** — `MetaflacAdapter` wrapping the `metaflac` CLI. Used by the Unknown Album helper to apply `Track NN` placeholder tags after a `--unknown` rip.

### Dependency self-management subsystem (`deps/`)

Implements brief P0 #11. **All** dependency checks live here. CLAUDE.md Critical Rule #6 forbids ad-hoc `shutil.which()` calls anywhere else.

- **`manager.py`** — `DependencyManager`. Single entry point `check_all()` invoked at app launch and from the Settings "Check dependencies" button. Walks the registry, runs each probe, classifies missing items into tiers (a)/(b)/(c), and drives the appropriate resolver. Returns a `DependencyReport` for UI display.
- **`registry.py`** — declarative list of `DependencySpec` dataclasses. Each spec names: dependency id, human-readable name, probe function (from `checks.py`), minimum version, eligible install tier(s), install command template (e.g. `flatpak install --user flathub org.musicbrainz.Picard`), and a copyable search string for tier (c) fallback. New dependencies are added here, nowhere else.
- **`checks.py`** — probe functions. One per dependency: `check_whipper()`, `check_metaflac()`, `check_libdiscid()`, `check_picard_flatpak()`, `check_python_pkg(name)`. Each returns a `ProbeResult` (present: bool, version: str | None, location: str | None).
- **`resolvers.py`** — three resolver classes corresponding to the three tiers. `AutoInstaller` runs silent installs after one confirmation dialog (pipx, `flatpak install --user`). `QueuedInstaller` drives `ui.dialogs.pending_installs`. `ManualPrompt` drives `ui.dialogs.manual_install`. The resolvers are dumb about which tier a dep belongs to — that's the registry's job; resolvers just execute.
- **`version.py`** — small helper: parse a version string out of CLI output using a named-group regex, compare semver-ish strings against a minimum. Tiny, well-tested.

### Whipper output parsers (`parsers/`)

Subprocess output parsing per CLAUDE.md (named-group regexes, robust to minor-version drift).

- **`rip_log.py`** — parses whipper's per-rip `.log` file into a structured `RipLog` dataclass: per-track CRCs, AccurateRip match status, AccurateRip confidence, read offset confirmation, total error count.
- **`drive_list.py`** — parses stdout of `whipper drive list` into a list of `DriveDescriptor` (vendor, model, firmware, device path).
- **`cd_info.py`** — parses stdout of `whipper cd info` into a `DiscInfo` (TOC, MusicBrainz disc ID, MB match status, AccurateRip availability).

### UI (`ui/`)

PySide6 widgets and dialogs. Each module is one screen or one widget; nothing here knows about subprocess details — that's the workers and adapters.

- **`main_window.py`** — `MainWindow(QMainWindow)`. Central widget is a vertical stack of: `DrivePicker`, `DiscInfoPanel`, `TrackTable`, `RipControls`, `RipProgress`. Menu bar with Settings, Check Dependencies, Quit. Wires worker signals into widget slots.
- **`drive_picker.py`** — `DrivePicker(QWidget)`. Combo box over drives discovered via `WhipperBackend.list_drives()`. Emits `drive_changed(device_path)`.
- **`disc_info_panel.py`** — read-only panel. Updates when a drive is selected or a disc is detected. Shows TOC, MB match status, AccurateRip availability.
- **`release_picker.py`** — `ReleasePickerDialog(QDialog)`. Shown only when `MusicBrainzClient` returns >1 candidate for the inserted disc. List of releases with year, label, country, track count. Returns the chosen MBID. **This is the v1 substitute for whipper's TTY prompt** — Critical Rule #5.
- **`track_table.py`** — `TrackTable(QTableView)` with a custom `QAbstractTableModel`. Editable per-track tags + album-level fields above the table. Validates before allowing the rip to start.
- **`rip_controls.py`** — Start / Cancel buttons. On Start, assembles rip parameters (drive, MBID, output dir from config, template, edited tags) and emits `rip_requested(params)`.
- **`rip_progress.py`** — three panes: live whipper stdout (read-only), per-track AccurateRip results table (populated when the rip log is parsed at the end), and a "View log" button that opens the saved `.log` file in the default text viewer.
- **`settings_dialog.py`** — `SettingsDialog(QDialog)`. Fields for output dir, working dir, track template, disc template, read offset, whipper/metaflac paths, auto-launch-Picard toggle. Persists through `config.py`.
- **`unknown_album.py`** — `UnknownAlbumDialog(QDialog)` + helper functions. Triggers a `whipper cd rip --unknown`, applies placeholder tags via `MetaflacAdapter`, optionally invokes `flatpak run org.musicbrainz.Picard <output_folder>`.
- **`dialogs/pending_installs.py`** — `PendingInstallsDialog(QDialog)`. Tier (b) UI: per-item checkboxes, "Install selected" button, per-item progress feedback. Backed by `QueuedInstaller`.
- **`dialogs/manual_install.py`** — `ManualInstallDialog(QDialog)`. Tier (c) UI: shows missing item, minimum version, why it can't auto-install, copyable search string in a read-only `QLineEdit`. Primary action: Copy. Secondary: Close.

### Workers (`workers/`)

Long-running operations on background `QThread`s so the GUI stays responsive.

- **`rip_worker.py`** — `RipWorker(QObject)` moved to a `QThread`. Owns the rip subprocess. Emits `log_line(str)` for each line of whipper output, `progress(...)` for parseable progress events, `finished(success, rip_log_path)` on exit, `error(message)` on failure. Supports cancel via subprocess terminate + child-process cleanup.
- **`mb_worker.py`** — `MusicBrainzWorker(QObject)` moved to a `QThread`. Drives `MusicBrainzClient` calls (which can take a few seconds and shouldn't block input). Emits `releases_returned(list)` or `error(message)`.

---

## 3. Pinned dependency list

Full table with release dates and replacement plans lives in `DEPENDENCIES.md`. Inline-justification summary:

| Package | Pin | Why |
|---|---|---|
| `PySide6` | `>=6.7,<7` | Qt 6 LGPL bindings; Qt 7 is not released yet but cap to avoid a breaking jump. KDE Plasma 6 ships Qt 6.x so native look comes free. |
| `musicbrainzngs` | `==0.7.1` | Last release (2020); pin exact so the adapter knows what shape to expect. Adapter ABC isolates the GUI from this dep's eventual retirement. |
| `tomli-w` | `>=1.0,<2` | TOML writer (stdlib `tomllib` reads only). Small, MIT, actively maintained. |
| `python-appimage` | `>=1.4,<2` | AppImage builder (dev/build-time only — not a runtime dep). Per CLAUDE.md Critical Rule #2 the chosen tool. |
| `pytest` | `>=8,<9` | Test runner (dev only). |

System dependencies (not Python packages, surfaced to the user via the dependency subsystem):

| Tool | How obtained | Tier |
|---|---|---|
| `whipper` | Host-exported from Distrobox container `ripping` at `~/.local/bin/whipper` | (c) — manual; install path is the user's existing Distrobox setup |
| `metaflac` | Same Distrobox export route as whipper | (c) — manual |
| `libdiscid` | System library; on Bazzite via `rpm-ostree install` + reboot | (c) — manual |
| MusicBrainz Picard | Flathub: `flatpak install --user flathub org.musicbrainz.Picard` | (a) — auto-install after one confirmation |
| `lame`, `sox` (P1) | System or container; deferred until MP3/WAV support lands | (a) or (b) per future spec |

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

### Future: `CyanripImpl`

Stub `cyanrip_backend.py` is **not** created at v1 to avoid dead code. Drop-in shape:

- Implements the same ABC.
- `list_drives()` uses `cyanrip -L` (or device probing).
- `rip()` translates `release_id` into `cyanrip -R <mbid>`.
- Selection between implementations would be a `backend = "whipper" | "cyanrip"` key in the config file, read by `app.py` at startup.

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

### KDD-07 — AppImage carries the GUI only, not whipper

AppImages are unsandboxed, so calling `~/.local/bin/whipper` from inside one works. But bundling whipper into the AppImage would (a) duplicate what's already installed via Distrobox, (b) silently sidestep the host-exported binary the user has configured, and (c) violate Critical Rule #3 ("does not try to install or update whipper itself"). The AppImage ships the GUI; the user's existing Distrobox `ripping` container ships whipper. The README spells this out as a prerequisite.

### KDD-08 — Reserve, don't pre-build, the alternate adapter implementations

`WhipperBackend` and `MusicBrainzClient` are ABCs, and the brief calls out future alternatives (`cyanrip`, raw `requests`). v1 does not create empty `CyanripImpl` or `RequestsJsonImpl` skeletons — they would be dead code. The ABC shapes are documented above so when retirement does happen, the new impl can be added in one focused PR. CLAUDE.md's "no half-finished implementations" rule.

### KDD-09 — Tests live alongside the package, not inside it

`tests/` at repo root, not `src/whipper_gui/tests/`. The package shipped to end-users contains no test code or fixtures. pytest discovers via `tests/` directly.

### KDD-10 — License: TBD (open question)

The brief does not specify a license. Until the user picks one, `pyproject.toml` will note `License :: OSI Approved :: MIT License` as a placeholder for the project metadata, but the actual `LICENSE` file is **not** committed in the bootstrap step. Flagged for explicit user decision before any public release. (PySide6 is LGPL, so MIT/Apache/BSD for our own code are all compatible; GPL would also work.)

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

The practical takeaway: archival verification on Linux is already solid — AccurateRip is wired through and visible in the GUI. Adding CTDB as a second verification path is post-v1 work whose cost is manageable.
