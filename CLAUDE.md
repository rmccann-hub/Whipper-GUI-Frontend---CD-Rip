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

- **`PLANNING.md`** — architecture, module design, key design decisions (KDD-01 through KDD-16)
- **`TASKS.md`** — active task checklist; update status (`[ ]` → `[~]` → `[x]`) as work progresses. Sections: P0 (v1 release, T01-T32), P1.1 (install/uninstall ease — highest-priority P1 subset), P1 (broader backlog), P2 (future), Out of scope.
- **`DEPENDENCIES.md`** — dep table with last release dates and replacement plans; review per the cadence stated in that file
- **`README.md`** — outward-facing project description and install instructions
- **`docs/README.md`** — index of the docs/ directory and a rebuild-from-scratch checklist
- **`docs/whipper-gui-research-brief-v2.1.md`** — the project brief; canonical for requirements and scope
- **`docs/whipper-gui-session-start.md`** — bootstrap instructions a fresh Claude Code session uses to reproduce the initial planning artifacts
- **`docs/whipper-gui-research-rerun-prompt.md`** — Research-mode prompt for refreshing tool-choice validation
- **`docs/log-format-comparison.md`** — whipper rip log vs EAC log side-by-side (referenced by KDD-11)
- **`docs/best-practices.md`** — engineering patterns and hard-won lessons (Qt threading, subprocess, adapters, testing, packaging, releasing, security); complements the locked *Code conventions* and *Critical rules* here

If `PLANNING.md` and the brief conflict, the brief wins on requirements/scope and `PLANNING.md` wins on implementation choices. If `PLANNING.md` and the research output conflict, raise it with the user — don't silently pick.

There is no `compass_artifact_*.md` in the repo; the original v1 research validation was unavailable when the project was bootstrapped, so the project proceeded against the brief alone. To refresh tool-choice research, follow `docs/whipper-gui-research-rerun-prompt.md`.

---

## Project operations

*This section grows as the project develops. Add concrete commands, paths, and operational notes as they're established. Keep entries terse.*

### Build commands

- AppImage: `bash build/build_appimage.sh` (produces `whipper-gui-x86_64.AppImage` at repo root via `python-appimage`)
- App icon: `python3 build/make_icon.py` (regenerates the committed `build/python-appimage/whipper-gui.png`; needs Pillow)

### CI / release

- **CI:** `.github/workflows/ci.yml` runs `pytest` on every push to `main` and every PR.
- **Releasing is automated** — do *not* hand-build/upload. Cut a release by pushing a version tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. `.github/workflows/release.yml` then builds the AppImage (reusing `build/build_appimage.sh`) and attaches it + a `.sha256` to a GitHub Release. `v0.*` tags publish as pre-releases. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry before tagging.

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

- **Lint:** `ruff check src tests` (config in `pyproject.toml` `[tool.ruff]`; rules `E,F,W,I,B,UP`, `E501` off). Auto-fix: `ruff check src tests --fix`.
- **Format:** `ruff format src tests` (88-col, double quotes — matches the existing code). CI checks with `ruff format --check`.
- **CI:** the `lint` job in `.github/workflows/ci.yml` runs both in check mode on every push/PR, in parallel with `test`.
- `ruff` is in the `dev` extra (`pip install -e ".[dev]"`).

### Important paths

- Source root: `src/whipper_gui/`
- User config: `~/.config/whipper-gui/config.toml`
- User logs: `~/.local/share/whipper-gui/log.txt`
- Whipper config (shared with Distrobox container): `~/.config/whipper/whipper.conf`
- Whipper binary (host-exported from Distrobox): `~/.local/bin/whipper`
- MusicBrainz Picard (Flatpak, used for auto-launch on unknown discs): `flatpak run org.musicbrainz.Picard`

### Notes for future sessions

- **Ruff + coverage + doc audit (2026-06-04):** Adopted **ruff** as the linter+formatter — config in `pyproject.toml` (`[tool.ruff]`, rules `E,F,W,I,B,UP`, `E501` off; `ruff>=0.15` in the `dev` extra) and a parallel **`lint` job** in `ci.yml` running `ruff check` + `ruff format --check`. Fixed all findings + raised coverage; the suite is now **525 tests** (was 454) and **35 CTDB tests** (was 30). Then did a **doc consistency pass** (unified `[ ]`/`[~]`/`[x]`/`[?]` markers across TASKS + test-plan, de-duplicated CTDB verify/repair to one authoritative spot, cross-linked docs) **and a doc accuracy audit** against the code: refreshed PLANNING.md's directory tree + per-module list (they predated the `ctdb/` package, `adapters/ctdb_client.py`, `drive_access`/`drive_control`/`offset_config`/`help_content`, the drive-setup/help dialogs+worker, `scripts/`, the new workflows, and `entrypoint.sh`), added `ruff` to DEPENDENCIES/PLANNING dep tables, and corrected stale counts + the README "Coming in P1" list (those EAC toggles already shipped). `docs/test-plan.md` now uses the repo's checkbox convention.
- **CTDB verify Phase-1 library landed (2026-06-03, KDD-16):** Clean-room lookup client + verify logic shipped — `adapters/ctdb_client.py` (GET `db.cuetools.net/lookup2.php`, XML `entry` parse, stdlib only) and `src/whipper_gui/ctdb/` (`toc.py` disc-TOC math + `toc=` builder; `decode.py` host-`flac`/`metaflac` wrappers; `crc.py` the audio CRC; `verify.py` orchestration + `Verdict` enum). Standalone `scripts/ctdb_verify.py` is the hardware test vehicle. **35 unit tests** cover the deterministic parts. **Deliberately NOT wired into the GUI** (user decision 2026-06-03: library+script+test-plan first) because **two pieces are hardware-validation-gated**: (1) the `toc=` wire format and (2) the bit-exact CRC (`crc.ctdb_crc_offset0` is a placeholder zlib CRC-32 with `CRC_VALIDATED=False`). Both are isolated behind a single seam and **fail safe** — a wrong CRC yields NO_MATCH, never a false "verified". PCM decode uses host `flac` if present (optional dep). Validation steps: `docs/test-plan.md` Test 1 (fix `ctdb/toc.py` if `not_in_db`; fix `ctdb/crc.py` from the **LGPL** `CUETools.AccurateRip` if `no_match` — never read `python-cuetoolsdb`). New **`docs/test-plan.md`** is the running manual/hardware checklist for all remaining gated work.
- **CTDB verify license gate RESOLVED — clean-room (2026-06-02, KDD-16):** Verified the licenses rather than assuming: we're GPL-3.0-only; `python-cuetoolsdb` is bare GPLv2 with *no* author version-election (no `license=`, no classifiers, no SPDX headers) → treat as GPL-2.0-**only** → one-way-incompatible with GPLv3, so we **cannot port it**. Decision: build CTDB verify **clean-room** from the **LGPL** `gchudov/cuetools.net` source (LGPL is GPLv3-compatible); protocol/CRC are facts, not copyrightable expression, so independent reimplementation is fine. **Never read/paraphrase `python-cuetoolsdb`.** Wrote an LGPL-grounded protocol+CRC spec in `docs/upstream-modification-investigation.md` (confirmed from `CUETools.CTDB/CUEToolsDB.cs`: host `db.cuetools.net`, `GET /lookup2.php?version=3&ctdb=1&fuzzy=&metadata=&toc=`, response `entry` w/ `crc`/`confidence`/`npar`/`id`/`hasParity`/`trackcrcs`/`syndrome`; audio CRC = `AccurateRipVerify.CTDBCRC(offset)` over ±`(5*588-1)`=±2939 samples — read `CUETools.AccurateRip`/`CUETools.Parity` for the bit-exact polynomial at impl time). **Only remaining blocker is hardware validation** (a real CD that's in CTDB); no code written yet by design.
- **openSUSE installer support + CTDB groundwork (2026-06-02):** `setup-host.sh` now auto-handles openSUSE — added `*suse*) zypper --non-interactive install …` to `ensure_distrobox` + `ensure_container_backend` (README distro table: openSUSE ⚠️→✅). Made distro detection testable via an `OS_RELEASE_FILE` env override (tests point it at a fixture). The **declined-dependency-cascade** backlog item turned out to be already done+tested (manager.py skips cascade on `user_declined`) — marked complete in TASKS. **CTDB verify is the ranked-next feature but was deliberately NOT coded:** it needs a real CD that's in CTDB to validate the audio CRC (a T32-style hardware test the cloud env can't do), and there's a **GPL-2.0 (python-cuetoolsdb) vs GPL-3.0-only (us)** license gate to resolve first. Instead, corrected a material error — **`ctdb-cli` is C#/.NET 10, NOT a C tool** (KDD-14 had it backwards), so Phase-2 AppImage bundling is heavy (bundle-vs-optional-install now open) — and wrote a concrete Phase-1 spec in `docs/upstream-modification-investigation.md`. Verify is pure-Python (not a `ctdb-cli` wrap); repair wraps `ctdb-cli`.
- **v0.1.0 shipped + EAC-parity upstream investigation (2026-06-02):** First public release [v0.1.0](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/tag/v0.1.0) is live (AppImage + `.sha256` + `install.sh` + `install-appimage.sh`), all three workflows green on real runs. *(Gotcha: it's marked a full release, not pre-release — created via the UI, and `release.yml` only sets `--prerelease` on the create path, not the asset-upload path. Future `git tag`-driven `v0.*` releases auto-mark correctly.)* Did a full test/doc audit: 454 tests pass; README now has an all-distros install table (Fedora/Bazzite, Ubuntu/Debian, Mint/Pop!_OS, Arch, openSUSE — note `setup-host.sh` doesn't yet auto-handle `zypper`, so openSUSE users `zypper install podman` first; tasked as a follow-up). New **investigation** doc `docs/upstream-modification-investigation.md` + TASKS.md section on modifying upstream open source for EAC parity: headline — most EAC *correctness* is already in whipper; the real win is **CTDB verify+repair** (wrap LGPL `ctdb-cli`, confirmed feasible — not a whipper change). **Guardrail: never fork whipper** (unmaintained; migrate the adapter to `cyanrip` if forced). Permanently non-feasible (don't revisit): AccurateRip/CTDB *submission* (policy/trust-gated), C2 error-pointer reading (C-level rewrite, marginal), byte-for-byte EAC log parity, separate offset DB.
- **One-file installer + AppImage CI (2026-06-01):** `install.sh` is the headline end-user installer — host stack (`setup-host.sh --no-gui`) + download the released AppImage + `install-appimage.sh` (desktop integration). It's curl-pipe-able and reuses the sibling scripts (downloads them if not run from a checkout). `install-appimage.sh` now also installs an **"Uninstall Whipper GUI"** launcher that runs a staged copy of `uninstall.sh` (placed at `~/Applications/whipper-gui-uninstall.sh`); `uninstall.sh` gained AppImage/icon/shortcut removal so it's the single comprehensive uninstaller for both install paths. AppImage download uses the **releases API** (not `/releases/latest/`) because `v0.*` are pre-releases. New `.github/workflows/appimage.yml` builds + smoke-tests the AppImage on every push to `main` and (via `workflow_dispatch`) uploads a downloadable artifact for any branch — see `docs/appimage-testing.md`. Gotcha fixed: an EXIT-trap cleanup must `return 0` or its non-zero status becomes the script's exit code.
- **Help menu + version 0.1.0 (2026-06-01):** `Help → About` (`ui/help_dialogs.AboutDialog`) shows the version (`__version__`, bumped to 0.1.0 in both `src/whipper_gui/__init__.py` and `pyproject.toml` — keep them in lockstep) plus Python/Qt/PySide6 versions and the config/log/whipper paths; `Help → User Guide` (`HelpDialog`) renders `help_content.USER_GUIDE` (a Markdown string kept *in code*, not as packaged data, to dodge AppImage package-data pitfalls — edit the guide there). About deliberately does NOT shell out to whipper (would enter the container/could stall). Also fixed a long-standing red `main` CI: the whipper-backend argv tests created `/music` (fails non-root on CI); they now no-op `Path.mkdir`.
- **Critical Rule #3 — one approved exception (2026-05-31): force-stopping a cancelled rip.** A rip runs whipper-in-`ripping`-container, which spawns `cdrdao` (TOC/"Reading table") then `cd-paranoia` (track rip); podman doesn't forward the host SIGKILL, so the drive can spin for minutes after Cancel (the physical eject button is inhibited while a read holds the device). `drive_control.force_stop_drive()` (host-first, all best-effort): **(1) `pkill -KILL -f 'whipper (cd|drive|offset|…)'`** — whipper is the *orchestrator* and respawns the reader if you kill only the reader, so you MUST kill whipper; the pattern is anchored to `whipper <subcommand>` so it can never match the GUI's "whipper-gui" cmdline or self-match; **(2) `pkill -KILL 'cdparanoia|cd-paranoia|cdrdao'`** by process *name* (no `-f`); **(3) `fuser -k <device>`** — name-independent kill of whatever still holds the device (GUI never opens it); **(4) `distrobox enter ripping -- pkill …`** only if the host pkill matched nothing (the user-approved into-the-container call); **(5) then `eject`**. Hard-won real-user lessons (2026-06-01): on rootless podman the in-container procs are host-visible so host `pkill`/`fuser` reach them; `pkill cdrdao` alone does NOTHING (whipper respawns it) — kill whipper; never `pkill -f whipper` (matches "whipper-gui" → kills the app) nor `-f` with reader names (self-matches the wrapper). `pkill`/`fuser`/`distrobox`/`eject` resolved to absolute paths (desktop-launched GUI has minimal PATH). **Scope is strictly force-stop on cancel** — ripping still goes through `~/.local/bin/whipper`. MainWindow auto-escalates `_FORCE_STOP_COUNTDOWN_MS` (5s) after Cancel, plus a manual "Force stop" button. Do NOT widen this exception without asking.
- **P0 status: COMPLETE — all 32 tasks done.** T32 closed 2026-05-30: a full 16-track rip ran **through the AppImage** on Bazzite, `success=True`, every Test CRC == Copy CRC, "No errors occurred". Next up is the P1 release milestones (merge to `main`, tag `v0.0.1`, publish the AppImage).
- **AppImage CA-cert bug (fixed 2026-05-30):** the bundled manylinux CPython has no CA certificates, so MusicBrainz HTTPS lookups failed with `CERTIFICATE_VERIFY_FAILED` — disc identification was silently broken in the distributed build (the editable install worked because it uses system Python). `entrypoint.sh` now points `SSL_CERT_FILE`/`SSL_CERT_DIR` at the host CA bundle (Fedora/Bazzite, Debian/Ubuntu, Arch/openSUSE, Alpine paths). Verified: the bundled interpreter does an HTTPS GET to musicbrainz.org → 200 once the env var is set. Guarded by `tests/test_build_harness.py`.
- **Progress + fidelity UX (2026-05-30, real-use feedback):** `RipWorker.progress` now emits `(overall, task)` — an overall bar (monotonic, whole-rip, 0-5% disc scan / 5-95% tracks / 95-100% finalize) plus a current-task bar; the pre-track disc scan animates instead of sitting at 0%. On finish the status line shows a fidelity verdict ("Done — all N tracks verified, Test/Copy CRCs match") via `_fidelity_summary`. A MusicBrainz lookup *error* now also falls back to placeholder track rows (previously only a clean no-match did), so the table is never empty.
- **EAC parity-gap Settings shipped (2026-05-30, roadmap #4):** cover art (`-C/--cover-art`, choices `file|embed|complete` — NOT the `none/embedded/file` the backlog guessed; verify flags against `whipper/command/cd.py`), force-overread (`-x`), max-retries (`-r`, always passed, default 5), keep-going (`-k`). Config fields + Settings widgets + `RipParameters` + argv passthrough. **Behaviour change:** `cover_art` defaults to `embed`, so rips now fetch art over the network by default.
- **Drive-access diagnostics shipped (2026-05-30):** `drive_access.diagnose_drive_access()` (pure stdlib, injectable probes) classifies the no-drive case as `no_device` / `permission` (gives `sudo usermod -aG <group> $USER`) / `ok`. `DrivePicker.drives_unavailable` → MainWindow auto-nudges once per session only when actionable; always available via Tools → Diagnose drive access…. Roadmap item #3 done.
- **Real-user fixes (2026-05-31, third from-scratch test):**
  - **Drive kept spinning after Cancel (rip + wizard):** killing only the whipper parent orphaned `cdparanoia` (the actual reader). Now launch the rip + setup subprocesses with `start_new_session=True` and cancel via `os.killpg` on the whole group (`_kill_group`). Caveat: the *in-container* (podman) ripper is a separate tree podman doesn't instantly signal, so the drive can still take a moment to spin down — documented, not fully solvable from our side.
  - **Cancel message:** distinguishes user cancellation ("Rip cancelled by user. Partial files may remain.") from a real failure; cancel status warns the drive may take a moment.
  - **Drive setup dialog** was tiny/clipped → `resize(560,420)` + min size + results in a scrollable read-only `QPlainTextEdit`.
  - **Picard "1 missing" nag:** added `DependencySpec.optional`; Picard is `optional=True`. The launch check no longer nags/counts optional deps; the summary lists them as "Optional (not installed): …".
  - **Album fields now drive the rip:** album-artist edit propagates to every track's Artist column (`TrackTableModel.set_all_artists`, fired on `editingFinished`; per-track edits still hold). And an unknown-disc rip names the folder from the (sanitized) album artist/title (`_safe_path_segment`) instead of the literal "Unknown Artist/Unknown Album".
  - **Desktop icon:** `dev-setup.sh` also drops a launcher on `~/Desktop` (chmod +x, GNOME-trusted); `uninstall.sh` removes it. Both refresh KDE's `kbuildsycoca` so the menu entry appears/disappears without a re-login.
- **`setup-host.sh` shipped (2026-05-30):** one-command bootstrap of README Steps 1-4 (Distrobox → `ripping` container → `dnf install whipper flac python3-setuptools` → `distrobox-export`) + clone + `dev-setup.sh`. Idempotent; `--dry-run`/`--yes`/`--no-gui`/`--container`/`--image`; runs in-place if inside a checkout, else clones; `curl … | bash`-able. **Only `--dry-run`-tested (no Distrobox in CI) — needs a real-hardware confirm.** Excludes drive calibration (GUI wizard) and Picard (GUI dep manager). Smoke tests in `tests/test_setup_host_script.py`.
- **Real-user fixes (2026-05-30, second from-scratch test):**
  - **Wizard crash fixed (critical):** closing the drive-setup dialog mid-detection destroyed a still-running `QThread` (Qt aborted the whole app) and orphaned the `whipper offset find` process (drive kept spinning). Fix: setup commands now run via a cancellable `Popen` (`_run_setup_capture` + `cancel_setup()` which SIGKILLs — the worker's `communicate()` is the sole reaper, so no waitpid race); `DriveSetupWorker.cancel()`; the dialog cancels + joins the thread on `reject()`/`closeEvent` and guards `_on_finished` with a `_closing` flag.
  - **Dependency check de-duplicated:** removed the Tools → "Check dependencies…" menu item; it lives only on the Settings button now (+ the launch-time auto-check).
  - **Manual offset in Settings:** the read-offset spinbox is editable again, with an "Override whipper.conf" checkbox → passes `whipper --offset N` (`Config.override_read_offset`, `RipParameters.read_offset_override`). Lets the user set the offset without editing whipper.conf; the wizard remains the primary path.
  - **Desktop entry:** `dev-setup.sh` installs `~/.local/share/applications/whipper-gui.desktop` (Exec = venv launcher, Icon = stock `media-optical`); `uninstall.sh` removes it.
- **Drive setup wizard shipped (2026-05-30, KDD-15):** Tools → "Set up drive…" (+ Settings "Re-detect…") opens `DriveSetupDialog`, which runs whipper's own `drive analyze` + `offset find` via `DriveSetupWorker` (off-thread) — they persist to `whipper.conf` themselves; `back_up_whipper_config()` makes a `.bak` first. New adapter methods `analyze_drive()`/`find_offset()` are an *optional* ABC capability (NotImplementedError default, so fakes/other backends still construct). Read-offset Settings field is now read-only + the wizard button (fixes the "misleading field" gap). Deferred: manual-offset write fallback, first-run auto-offer, live streaming output. roadmap item #2 done.
- **Post-v1 roadmap set (2026-05-30, after an "EAC successor" research review):** ranked in TASKS.md P1 — (1) release milestones, (2) **drive setup wizard** that writes `whipper.conf` via whipper's own `drive analyze`/`offset find` (KDD-15), (3) **drive-access permission diagnostics** (cdrom-group / `/dev/sr0`), (4) the four EAC parity-gap Settings widgets, (5) **CTDB verify** (pure-Python, Phase 1), (6) **CTDB repair** (Phase 2: wrap the `ctdb-cli` C tool, bundled in the AppImage, explicit trigger, submission shelved — KDD-14). Most of the doc's forensic content is already handled by whipper; its Flatpak/Snap sandboxing section is N/A (we ship AppImage+pipx to reach host whipper). Test&Copy dual-pass downgraded — whipper already gives per-track Test/Copy CRC.
- **Edited tags feed the unknown rip (2026-05-30):** after a successful unknown-mode rip, `_on_rip_finished` → `run_unknown_post_processing` writes the track table's (edited) album/track fields to the FLACs via `apply_track_tags()` (blanks fall back to placeholders; a typed year → `DATE`). Scoped to the just-ripped album folder (the `.log`'s parent), NOT the output root — globbing the root would re-tag the whole library. Edits flow to tags only, not filenames.
- **T32 AppImage build (2026-05-29):** `bash build/build_appimage.sh` produces `whipper-gui-x86_64.AppImage`; `--version` prints `whipper-gui 0.0.1`; a headless `QT_QPA_PLATFORM=offscreen` launch reaches the Qt event loop (config created, MusicBrainz adapter up, dependency manager probes all deps). Building it surfaced **five recipe bugs the unit tests missed** — all fixed + regression-guarded in `tests/test_build_harness.py`:
  - python-appimage installs requirements.txt **one line at a time from a temp dir**, so a standalone `--find-links .` line fails → use `PIP_FIND_LINKS` (exported by the build script) instead.
  - `system()` runs each `pip install` through a shell, so `<`/`>` in pins are read as redirections → pins use `~=` (`PySide6~=6.7`, `tomli-w~=1.0`).
  - the entrypoint is globbed as `entrypoint.*`, so it must have an extension (`entrypoint.sh`) or the bare interpreter runs.
  - a space in the `.desktop` `Name=` breaks the unquoted appimagetool command → `Name=Whipper-GUI`; the script normalises the output to `whipper-gui-x86_64.AppImage`.
  - python-appimage fetches the CPython base image via the GitHub **API** (403s when rate-limited) → optional `WHIPPER_GUI_BASE_IMAGE` env var feeds a pre-downloaded base image; FUSE-less hosts also need `APPIMAGE_EXTRACT_AND_RUN=1`.
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
- **Branch state (2026-05-30):** merged to **`main`** — `main` now carries the full project (default branch for fresh clones). Repo is public; license GPL-3.0-only. Ongoing work continued on `claude/lucid-babbage-JYI8c` and is merged forward to `main`. The `dev-setup.sh` branch-guard and the README dev-branch/auth steps were removed as part of the merge.
