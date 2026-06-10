# Changelog

**This is the single, authoritative record of all notable changes to Whipper
GUI** — add an entry to `[Unreleased]` in the *same commit* as any change.
Format follows [Keep a Changelog](https://keepachangelog.com/); the project
adheres to [Semantic Versioning](https://semver.org/); dates are ISO-8601
(YYYY-MM-DD). The version itself is single-sourced from
`src/whipper_gui/__init__.py` (`__version__`); at release time the `[Unreleased]`
entries move under a dated `## [X.Y.Z]` heading. (Design decisions live in
`PLANNING.md` KDDs and the CLAUDE.md session log — not here.)

## [Unreleased]

*(nothing yet)*

## [0.2.1] — 2026-06-10

### Fixed
- **v0.2.0's release build uploaded no files.** Two packaging bugs: the
  build script looked for python-appimage's cached `appimagetool` with a
  glob that skipped its dot-prefixed cache directory, so the zsync
  update-information embed was silently skipped; the release upload then
  failed on the missing `.zsync` and aborted before attaching anything.
  The glob now matches the dot-form, and a dedicated "Verify update
  artifacts" workflow step fails early with a clear message if the
  `.zsync` is ever missing again. *(v0.2.0 was superseded without
  artifacts; v0.2.1 is identical plus this fix.)*

## [0.2.0] — 2026-06-09

### Added
- **AppImage self-update (the last zero-CLI slice, KDD-17b).** The AppImage
  now embeds standard zsync update-information
  (`gh-releases-zsync|…|whipper-gui-x86_64.AppImage.zsync`) and releases ship
  the `.zsync` file, so any AppImageUpdate-compatible tool can fetch only the
  changed blocks and verify them. In-app: **Help → Check for updates…** asks
  GitHub (off-thread) whether a newer release exists; if so it hands off to
  `appimageupdatetool`/`AppImageUpdate` when installed, or opens the release
  page — the app never downloads update payloads itself. The `.sha256`
  checksum is generated after the update info is embedded, so it always
  covers the shipped file.
- **`setup-host.sh --cyanrip`.** The CLI bootstrap now mirrors the GUI
  wizard's cyanrip step: enables the GPG-checked COPR inside the container
  only, installs cyanrip, and exports it to `~/.local/bin/cyanrip`.
- **"Uninstall Whipper GUI" menu entry + `--uninstall` mode.** AppImage
  self-integration now also installs an uninstaller launcher in the
  application menu (under System, not next to the app in Multimedia) that
  opens just the uninstaller via the new `whipper-gui --uninstall` flag — so
  removal needs neither a terminal nor the main app. Verified all our
  `.desktop` entries already file the app itself under Multimedia
  (`Categories=AudioVideo;Audio;`).
- **In-app Uninstaller (Tools → Uninstall Whipper GUI…).** Removes everything
  the app installed — menu/desktop shortcuts, host-exported
  whipper/metaflac/cyanrip, the `ripping` container, optionally `whipper.conf`
  and the AppImage file itself, and finally the app's own settings + logs —
  with live per-step progress, a confirmation gate, and per-piece checkboxes.
  **Never touched: your music, and Distrobox/podman themselves.** Settings +
  logs are removed last so a failed step still leaves the log to debug with;
  on success the app offers to close itself. `uninstall.sh` now also removes
  the host-exported cyanrip wrapper (parity).
- **Fidelity verdict + AccurateRip table for cyanrip rips (KDD-18).** New
  `parsers/cyanrip_log.py` parses cyanrip's rip log (EAC CRC32 per track,
  AccurateRip v1/v2 + confidence, preemphasis, drive/offset, ripping-error
  count) into the shared `RipLog`, with format auto-detection — a folder can
  hold logs from either ripper. The post-rip summary is worded around what
  cyanrip actually checks ("all N tracks ripped cleanly, no read errors" +
  "AccurateRip: N/M") instead of claiming whipper's Test/Copy CRC pass, and
  the per-track AccurateRip results table now fills in on both backends.
- **Live progress bars during cyanrip rips (KDD-18).** The rip worker now
  parses cyanrip's `\r`-redrawn progress lines ("Ripping track N, progress -
  X%, ETA - …"), so the overall + task bars move, the current track row is
  highlighted, and the status line shows percentage + ETA — same behaviour as
  whipper rips. Per-track completion lines peg that track's slice of the
  overall bar.
- **cyanrip rips are now driven entirely by the GUI's metadata (KDD-18).**
  The rip snapshots the track table (the MusicBrainz release you picked plus
  any edits) and feeds it to cyanrip via `-a`/`-t`, with MusicBrainz always
  disabled (`-N`): no wrong-release risk, no in-container network needed,
  values with `:`/`=`/`'` safely escaped, and the release MBID recorded as a
  tag. The folder/file naming templates now apply to cyanrip too — whipper
  `%A/%d/%t/%n/%y/%N/%a` tokens are translated to cyanrip's `-D`/`-F`
  `{…}` schemes, so both backends produce the same library layout.
- **One unified Settings page across backends.** Options the selected
  backend doesn't support (under cyanrip: CD-R switch, cover art, overread,
  keep-going, the whipper path) grey out instead of disappearing, with a
  tooltip explaining why and that switching the Ripping backend back to
  whipper re-enables them. Greyed-out values are kept, never cleared.
- **cyanrip backend now identifies discs (KDD-18).** `CyanripImpl.disc_info`
  runs `cyanrip -I -N` (info-only, offline — cyanrip computes the
  MusicBrainz DiscID and CDDB ID locally from the TOC) and the new
  `parsers/cyanrip_info.py` parses the report into the backend-neutral
  `DiscInfo` (IDs, track count, MB submission URL), so the disc panel and
  the GUI's host-side MusicBrainz lookup work identically on both backends.
  Includes a property-based "never raises" test per the testing rules.
- **Host-setup wizard can install the cyanrip backend (KDD-18).** When
  Settings → Ripping backend is set to cyanrip, the setup wizard (and the
  Tools → Set up Whipper GUI… flow) gains a step that installs cyanrip into
  the `ripping` container and host-exports it to `~/.local/bin/cyanrip`.
  Research finding (2026-06-09): Fedora does **not** package cyanrip (nor
  does RPM Fusion); the install uses the GPG-checked COPR
  `barsnick/non-fed` (cyanrip 0.9.3.1 built for Fedora 42–44 + rawhide) via
  a version-generic `.repo` file — no `dnf copr` plugin needed. Switching
  the backend in Settings now offers to run the wizard if cyanrip is
  missing, and the app prefers the host-exported absolute path when
  constructing the cyanrip backend (desktop launches have a minimal PATH).
- **Institutionalized testing strategy + stronger test infrastructure.** New
  [`docs/testing.md`](docs/testing.md) codifies the approach (testing trophy +
  an explicit real-hardware gate, a five-tier case taxonomy, property/golden/
  fault-injection/mutation guidance, the non-negotiable rules, and a Definition
  of Done). Concretely: **property-based tests** (`hypothesis`) lock in the
  "parsers never raise on arbitrary input" invariant
  (`tests/test_parsers_property.py`); CI now runs **branch coverage with a hard
  `--cov-fail-under=88` gate** (baseline ~91%, ratchets up) across a **Python
  3.11–3.13 matrix**; `pytest-cov` + `hypothesis` added to the `dev` extra and
  `mutmut` documented as a periodic audit. Suite is now 534 tests.
- **Ruff linter + formatter.** Adopted `ruff` (config in `pyproject.toml`:
  rules `E,F,W,I,B,UP`, `E501` off; `ruff>=0.15` in the `dev` extra) with a
  parallel `lint` job in CI running `ruff check` + `ruff format --check`. Fixed
  all findings and raised coverage; the suite is now 525 tests.
- **CTDB verify (Phase 1 — library + validation script).** Clean-room (KDD-16)
  CUETools Database lookup client (`adapters/ctdb_client.py`) and verify logic
  (`whipper_gui/ctdb/`), plus a standalone `scripts/ctdb_verify.py` to validate
  on real hardware. The `toc=` wire format and the audio CRC are
  hardware-validation-gated (both fail safe — never a false "verified"); the
  GUI wiring is deferred until they're confirmed. See `docs/test-plan.md`
  Test 1. PCM decode uses the host `flac` if present (optional dependency).
- **Manual / hardware test plan** (`docs/test-plan.md`) — a step-by-step
  checklist for everything that can't be validated in CI (CTDB verify/repair,
  `drive analyze`/`offset find` success strings, GUI screenshot, Picard UX,
  PyPI go-live).
- **Automated PyPI publishing.** A new `.github/workflows/publish-pypi.yml`
  builds the wheel + sdist and publishes them to PyPI when a release is
  published (i.e. on every `v*` tag, alongside the AppImage). Uses PyPI
  Trusted Publishing (OIDC) — no stored token. One-time PyPI-side setup is
  documented in the workflow header. It's a separate workflow from
  `release.yml`, so a PyPI misconfiguration can't block the AppImage release.

### Changed
- **README leads with a no-terminal install.** A new "Easiest — download one
  file, no terminal" section: download the AppImage, do the one-time "allow
  executing" step (GUI instructions for KDE/GNOME), double-click, and answer the
  first-run prompts (menu integration + the host-setup wizard). The scripted/
  CLI paths remain below for testers and developers; Method A notes that
  `install-appimage.sh` is no longer required (self-integration replaces it).

### Changed
- **Clear, actionable message when a track can't be read.** When whipper gives up
  on a track after its retries (scratched/dirty disc, or the cd-paranoia
  >587-offset upstream bug), the status now says which track failed and what to
  do — clean the disc, or turn on "Keep going" in Settings to rip the readable
  tracks — instead of a bare "Rip failed".

### Added
- **Settings → Ripping backend toggle (cyanrip, Phase 2 start).** You can now
  pick the backend (whipper | cyanrip) in Settings; it's wired to
  `Config.ripper_backend` and applied on next launch. cyanrip is marked
  experimental and still needs to be installed in the container (provisioning is
  the next phase). Completes the user-facing half of making cyanrip selectable.
- **cyanrip backend — Phase 1 (KDD-18).** A second ripping backend
  (`adapters/cyanrip_backend.py`, `CyanripImpl`) behind the existing
  `WhipperBackend` ABC, selectable via `Config.ripper_backend = "cyanrip"`
  (app.py picks the backend; default stays whipper). cyanrip is the actively
  maintained successor and — critically — applies the read offset with its own
  paranoia (`-s`), avoiding whipper's cd-paranoia bug at offsets > 587 that
  fails tracks on the Pioneer BDR-209D (+667). Phase 1 ships the tested core:
  the rip argv builder (`-d/-s/-o flac/-r/-N/-G`), `version`, `find_offset`
  (`-f`), and a backend-independent `/dev`+sysfs drive scan; disc-info parsing
  and naming-template mapping are tracked as the remaining phases in
  `docs/ecosystem-audit-2026-06.md`. Not yet user-selectable in the GUI.
- **Autonomous heal when the ripper can't reach MusicBrainz.** whipper inside the
  container aborts (`unable to retrieve disc metadata, --unknown argument not
  passed`) when it has no network — even for a known disc, because it fetches the
  release online. The GUI already has the metadata from its own host-side lookup,
  so on that specific failure it now **automatically re-rips as an unknown-album
  rip** (`--unknown`, no release-id → no network needed) and tags the FLACs
  locally from the on-screen track list. One retry per Start; surfaced in the
  status line. The `RipWorker` watches whipper's output for the marker.

### Changed
- **Ripping no longer demands the wizard when the drive's offset is already
  known.** If you hit Start without a saved offset but your drive is in the
  bundled AccurateRip list, the GUI now **applies that offset automatically**
  (your Pioneer → +667), tells you once where it came from, and lets the rip
  proceed — instead of blocking and sending you to the drive-setup wizard. Only
  a genuinely unknown drive still needs the wizard. (The manual/wizard-saved
  offset path is unchanged: set it once, then you're good.)
- **Host-setup wizard: live progress + honest end states (no more "frozen / done
  too soon").** The bootstrap engine now emits a **"⏳ currently doing X…"**
  status *before* each step runs — so during a multi-minute image pull or
  in-container `dnf install` the wizard shows what's happening instead of a
  static bar that looks hung. Slow steps say "this can take a few minutes". The
  finish message now distinguishes **"Everything was already set up — you're
  ready to rip"** (the common Bazzite case, which previously flashed by and
  looked like nothing happened) from a setup that actually installed things, and
  surfaces the failed step otherwise.

### Added
- **App shortcut: Desktop icon + a re-runnable menu action.** Self-integration
  now also drops a clickable icon in your **Desktop folder** (not just the
  applications menu), and there's a **Tools → Add app shortcut** action so you
  can (re)create the menu + desktop shortcut any time — the first-run offer was
  one-shot, so a dismissed prompt previously left no way to redo it. GNOME
  desktop icons are marked trusted (best-effort) so they launch on double-click.
- **AppImage self-integration on first run — no terminal (KDD-17, step 2).** The
  first time the AppImage runs, it offers to add Whipper GUI to your
  applications menu (writes a `.desktop` entry pointing at the AppImage, drops
  the icon, refreshes the menu caches) and makes the AppImage executable — so
  after the first double-click it launches from the menu like any installed
  app. Supersedes the manual `install-appimage.sh` for the common case; no-op
  on source/pipx installs. New `appimage_integration.py`; one-time/dismissible
  (`Config.appimage_integration_prompted`).
- **First-run host setup from the GUI — no terminal (KDD-17, step 1).** A new
  **Tools → Set up Whipper GUI…** wizard (also offered automatically on first
  launch when whipper isn't installed yet) does what `setup-host.sh` did by
  hand: installs Distrobox + a container backend, creates the `ripping`
  container, installs whipper into it, and exports it to the host — with live
  per-step progress and idempotent re-runs. System-package installs use a
  graphical **polkit** prompt (`pkexec`) instead of `sudo`, so no terminal is
  needed; on Bazzite/Silverblue the runtime is preinstalled, so those steps are
  skipped and nothing is prompted. Engine: `deps/host_setup.py` (injectable
  runner, dry-run, fully unit-tested); UI: `ui/host_setup_dialog.py` +
  `workers/host_setup_worker.py`.
- **Read offset is now looked up by drive model (full AccurateRip list, bundled).**
  whipper's `offset find` is unreliable (it failed on a Pioneer BDR-209D even with
  a disc that's in AccurateRip). The drive-setup wizard now resolves the offset the
  way EAC/dBpoweramp do — by the drive's vendor+model — and pre-fills it for
  one-click save, **with no disc and no whipper probe**. The **entire AccurateRip
  drive-offset list (~4,800 drives)** is imported and bundled in-code
  (`adapters/accuraterip_offsets_data.py`, a ~21 KB gzip blob), so it works offline
  for any drive — refreshable via `scripts/update_drive_offsets.py` (which validates
  the parse against the known BDR-209D = +667 before writing). Layered: user CSV
  (`~/.config/whipper-gui/drive_offsets.csv`) > curated overrides > bundled list.
  whipper's `offset find` is kept as optional verification. New
  `adapters/accuraterip_offsets.py` (`OffsetDatabase`). See
  `docs/offset-investigation-2026-06.md`.

### Fixed
- **Saving Settings no longer resets the one-time first-run flags.** `to_config`
  rebuilt `Config` from scratch and dropped `drive_setup_prompted` /
  `host_setup_prompted` / `appimage_integration_prompted`, so after saving
  Settings the first-run offers could re-appear on the next launch. Preserved now.
- **Ripping without a configured read offset now stops with a clear popup**
  instead of failing cryptically inside whipper. If no offset is set (neither
  whipper.conf nor the GUI's `--offset` override), Start shows a warning that
  explains an accurate offset is required and offers to open the drive-setup
  wizard — which fills the offset in automatically when the drive model is
  known, or detects it from a CD that's in the AccurateRip database.
- **The app no longer vanishes silently on a startup error.** Drive listing
  (and the rest of startup) ran after the window was shown but outside any
  guard, so an unexpected error — e.g. the drive-list parser choking on
  unhandled whipper output — let the window appear and then immediately
  disappear with nothing logged on screen. Startup is now wrapped: any
  unexpected error (including ones raised inside a Qt slot during the event
  loop, via a `sys.excepthook`) is logged **and shown in a dialog** with the
  log-file path, instead of aborting the process. `DrivePicker.refresh()` also
  now degrades any non-`WhipperError` to an "(error: …)" placeholder so a
  drive-listing hiccup leaves a usable window.
- **Drive-setup wizard:** the manual read-offset spinbox (and its up/down
  arrows) and the **Save offset** button are now locked while detection is
  running, so a value can't be edited/saved mid-detection and race what whipper
  writes. They re-enable when detection finishes.

### Changed
- **Documentation audit (2026-06-09).** PLANNING.md caught up with the code
  (directory tree + per-module list now include the host-setup wizard,
  AppImage self-integration, AccurateRip offset lookup, and the cyanrip
  backend/parser; the pre-implementation "future CyanripImpl" sketch replaced
  with the as-built design). TASKS.md gained a **Current plan & priorities**
  section — the live, ordered queue with difficulty estimates — and the
  zero-CLI checkboxes were corrected to match what shipped. README gained a
  "Ripping backends" section; the in-app User Guide documents the backend
  toggle; the hardware test plan gained Test 8 (cyanrip install + parity run).

## [0.1.0] — 2026-06-01

### Added
- **One-command installer (`install.sh`).** A single downloadable file (also a
  release asset) that takes a machine from nothing to a launchable app: sets up
  the host stack (Distrobox + `ripping` container + whipper, via
  `setup-host.sh --no-gui`), downloads the published AppImage, and adds the
  desktop shortcut **plus an "Uninstall Whipper GUI" shortcut**. Flags:
  `--yes`, `--dry-run`, `--no-host`, `--appimage PATH`, `--build`. The
  uninstall shortcut runs the comprehensive `uninstall.sh` (interactive, with
  options); `uninstall.sh` now also removes the AppImage, its icon, and the
  shortcuts, so it cleanly handles both the source and AppImage installs.
- **AppImage built on every push to `main`** (`.github/workflows/appimage.yml`),
  not just at release time, so a broken build recipe is caught immediately. It
  also runs on demand (`workflow_dispatch`) on any branch, uploading a
  downloadable AppImage artifact for testing branches that have no release yet.
  See `docs/appimage-testing.md`.
- **Help menu.** A new **Help → About** dialog shows the version number plus
  support-relevant info (Python/Qt/PySide6 versions, config/log/whipper paths,
  project & issue links), and **Help → User Guide** opens a built-in,
  task-oriented guide (`whipper_gui/help_content.py`).
- **Force-stop for a runaway drive.** Cancelling a rip kills the host-side
  process, but the reader runs inside the `ripping` container and podman
  doesn't forward the signal, so the drive could keep spinning for minutes with
  no way to stop it. Cancel now auto-escalates after a short countdown (and
  there's a manual **Force stop** button): it kills the **whipper orchestrator**
  (which otherwise just respawns the reader), `fuser -k`'s the device, and
  ejects — a deliberate, user-approved exception to the "never call into the
  container" rule, scoped to this case only. Validated on real hardware: Cancel
  now stops the drive within a few seconds.
- **Desktop integration for the AppImage** (`install-appimage.sh`, shipped as
  a release asset): adds an app-menu entry + Desktop icon for a downloaded
  AppImage (which otherwise installs no shortcut), with `--uninstall`.
- **First-run read-offset onboarding.** whipper refuses to rip until a read
  offset is configured; a fresh user (especially one with only CD-Rs, who
  can't run AccurateRip auto-detection) would otherwise hit a cryptic error.
  On first launch, if no offset is set (neither in `whipper.conf` nor as the
  GUI's `--offset` override), the GUI now offers the drive-setup wizard once —
  dismissible, and never re-nagged (afterwards it lives on Tools → Set up
  drive…). The wizard gains a **manual-entry fallback**: when auto-detection
  can't run, enter your drive's published offset by hand (linked to
  AccurateRip's list); it's applied via `--offset`, so `whipper.conf` is never
  hand-authored (KDD-15).

### Fixed
- **CI on `main` was red.** Since the T32 change that auto-creates the output +
  working directories before a rip, the whipper-backend argv tests created
  `/music`, which fails as non-root on the CI runner (it only passed in a
  root dev container). The argv-only tests no longer touch the filesystem; the
  one test that asserts directory creation uses a writable temp path.

## [0.0.1] — 2026-05-31

**First public test release.** A Linux GUI front-end for the `whipper` CD-ripping
CLI, aiming for EAC-equivalent archival quality. Validated on real Bazzite
hardware: a full 16-track rip *through the published AppImage*, with every
track's Test CRC matching its Copy CRC and "no errors occurred".

### What works

- **End-to-end FLAC ripping** through the host-exported `~/.local/bin/whipper`
  (Distrobox routing), with per-track AccurateRip confidence and Test/Copy CRC
  verification reported in the UI.
- **MusicBrainz disc identification** via a dedicated adapter — whipper's
  interactive TTY prompt never surfaces; a release picker handles multiple
  matches, and unknown discs fall back to editable `Track NN` placeholder rows.
- **Drive setup wizard** (Tools → Set up drive…) runs whipper's own
  `drive analyze` + `offset find` and writes `whipper.conf` for you — no more
  hand-editing read offsets.
- **Drive-access diagnostics** (Tools → Diagnose drive access…) classify the
  "no drive" case and hand you the exact `usermod` fix when it's a permissions
  problem.
- **EAC parity Settings:** cover art (fetch/embed/save), force-overread,
  max-retries, keep-going, CD-R support, and a manual read-offset override.
- **Progress + fidelity UX:** an overall progress bar plus a current-task bar,
  an animated pre-track disc scan, and an end-of-rip fidelity verdict.
- **Single-file AppImage** bundling Python + Qt + dependencies (the GUI side
  needs nothing else installed), plus a `pipx`/source path for developers.

### Install & uninstall

- **`setup-host.sh`** — one command bootstraps the entire host stack (Distrobox
  → `ripping` container → whipper + flac → host export), idempotent, with
  `--dry-run` / `--yes` / `--no-gui`.
- **`uninstall.sh`** — layered, safest-first teardown; never removes ripped
  music or the repo without an explicit flag and a typed confirmation.
- `dev-setup.sh` installs a KDE app-menu entry and a desktop launcher; both are
  cleaned up by `uninstall.sh`.

### Known limitations

- The **host stack is required** — the AppImage cannot rip on its own (this is
  intentional; whipper runs inside Distrobox).
- **FLAC only** in v1 (MP3/WAV are backlog). FLAC compression level is fixed at
  whipper's upstream default (`-5`); see the README for a post-rip re-encode
  recipe if you want `-8`.
- `setup-host.sh` is verified by `--dry-run` and smoke tests; the full
  hardware-bootstrap path has had limited real-world runs.
- Linux x86-64 only.

[0.2.1]: https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/tag/v0.1.0
[0.0.1]: https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/tag/v0.0.1
