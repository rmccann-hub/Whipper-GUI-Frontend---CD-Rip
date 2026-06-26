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
- **Modules:** small and focused. Split when a file exceeds ~300 lines. One responsibility per module. The line count is a *heuristic for cohesion*, not a hard cap — don't split a cohesive 350-line file to hit a number, and *do* split a 200-line file that's secretly doing three jobs. A heavily-tested Qt "god-object" (e.g. `MainWindow`) is split via **mixins** the concrete class inherits, so methods stay reachable as `window._x` (which tests and Qt signal wiring depend on) while each concern lives in its own focused file — see `docs/architecture.md`.
- **No clever metaprogramming.** Avoid decorators that mutate behavior unobviously, dynamic class creation, monkey-patching, or "magic" imports.
- **Never block the GUI thread.** Any operation that can take more than a few milliseconds — `subprocess.run`, network I/O, large-file hashing/copying, `thread.join()`, `kbuildsycoca6` — must NOT run on the Qt main thread; a blocked event loop shows "Not Responding" and ignores every click until it returns. Need the result → a `QObject` worker on a `QThread` (or a daemon thread that reports back via a queued signal). Don't need it → fire-and-forget `subprocess.Popen(..., start_new_session=True)`. This rule was written in blood: it caused the in-app-update freeze and several latent freezes (2026-06-13). When reviewing a change, ask: *if this ran on a stalled network or a cold container, would the window freeze?*
- **Error handling:** catch specific exceptions, never bare `except:`. Log with the `logging` module, not `print`.
- **Subprocess output parsing:** robust to whipper minor-version output changes. Use named-group regexes, not column-index splits. Parsers of external output **never raise** — they return a best-effort dataclass and get a `hypothesis` "never raises" property test.
- **Naming:** snake_case for functions, variables, modules; PascalCase for classes; SCREAMING_SNAKE_CASE for module-level constants.

## Critical rules

1. **Unmaintained dependencies require adapter layers.** Currently flagged as unmaintained: `whipper`, `python-musicbrainzngs`, and `appimage-builder` (if ever reached for). Every call into these MUST go through a thin adapter module so a future replacement is feasible without rewriting the GUI. Adapter modules are mandatory, not optional.

2. **`python-appimage` is the AppImage builder.** Do not use `appimage-builder` without stopping and asking first. If a build requirement cannot be expressed in `python-appimage`, describe the specific limitation in detail before reaching for any alternative. If `appimage-builder` is approved as a fallback, the recipe must stay close enough to vanilla that swapping back is cheap.

3. **Distrobox routing is sacred.** The GUI calls `~/.local/bin/whipper`. It does not call into the container directly, does not assume native whipper, does not try to install or update whipper itself.

4. **FLAC is the default and the archival master; MP3, WavPack, and WAV are derived outputs.** (Superseded the original "FLAC only for v1" — multi-format shipped 2026-06-26 with the maintainer's explicit sign-off; FLAC stays the lossless master.) Every rip produces FLAC first (lossless, provably bit-perfect); when the user selects another format in Settings the GUI **keeps that FLAC** and derives the chosen format from it via the *single* post-rip transcode adapter (`adapters/transcode.py`). FLAC and WavPack are lossless; MP3 is best-practice VBR (lossy by design — "not for that use"); WAV is raw PCM (no tags/art — the UI warns). Every encoder routes through the same dependency self-management subsystem — **no bespoke per-encoder install code**. A new format extends the one transcode adapter + the one dep subsystem; it never gets its own install path.

5. **No bypass of MusicBrainz query path.** Always query MusicBrainz via the `MusicBrainzClient` adapter (currently backed by `python-musicbrainzngs`) to obtain the release ID first, then invoke whipper with `--release-id <MBID>`. Never let whipper's interactive TTY prompt surface to the user.

6. **Dependency self-management is one subsystem, not scattered checks.** All "is this dependency present and the right version" logic lives in a single module with the three-tier resolution strategy (auto-install → queued install → copyable search string). New dependencies route through it; no ad-hoc availability checks elsewhere in the codebase.

7. **Documentation currency is part of "Done."** A change isn't finished when the tests are green — it's finished when the *record* matches the code. This rule is the always-loaded anchor; it **daisy-chains** to the rest, so the one file guaranteed to be read every session pulls the others in. Three obligations, in order:
   - **In the same commit as the change:** add the `CHANGELOG.md` `[Unreleased]` bullet (mechanics under *Project operations → Single record of changes*; CI backstops this). Pure historical-record commits (e.g. a session-log catch-up) are exempt and mark themselves with a `[skip changelog]` line of its own in the commit message.
   - **Before ending a session:** append a `docs/session-log.md` entry (newest-first) — what was built, decided, learned.
   - **Graduate every durable lesson to its real home** — a Critical rule or Code convention *here*, a KDD in `PLANNING.md`, or `docs/architecture.md` / `docs/testing.md` — so the rule lives where it's read and the log keeps only the dated entry. A lesson left *only* in the log is not graduated.

   The full code-and-docs checklist is the **Definition of Done in `docs/testing.md §6`**. Same bite as the regression-test rule: institutional, non-negotiable.

8. **No copyrighted media in the repo — ever, not even temporarily.** This repository is public. Never `git add`/commit a music file or any other copyrighted media — **no `.flac`, `.wav`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wv`, `.ape`, `.aiff`, `.dsf`, etc.** — and this includes *temporary* files dropped in for testing. Owning the disc does not grant redistribution rights, and a public commit (and git history) is redistribution. **How we test with real audio instead:** work on it **outside the repo** — the session scratchpad or a `/tmp` dir — and delete it when done; the durable proof we commit is the **text** artifact (EAC/whipper/cyanrip **logs** + per-track **CRCs**), never the audio (the CRCs prove bit-perfection without it — see `output_reference/README.md`). `.gitignore` denies audio extensions as a backstop, but the rule is the line of defense, not the backstop. If a test genuinely needs real PCM, use a **short, self-generated or CC0/public-domain** sample, never a commercial track. Same bite as the rules above: institutional, non-negotiable.

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

## Working with the maintainer (learned)

This project is as much about building durable standards as shipping the app — so this section captures what past sessions learned about *how this maintainer works and what they value*. Treat it as guidance, not law.

- **North star: "good music, good cover image, good everything."** The goal isn't "a rip" — it's a complete, trustworthy library entry: bit-perfect audio (provable via CRCs), correct tags, embedded cover art. When weighing work, favor what moves the whole experience toward that.
- **UX responsiveness is a feature, not a polish item.** The maintainer notices and reports freezes, dead buttons, and "Not Responding" windows immediately, and values them fixed ("users value those to be as responsive as possible"). This is why the GUI-thread rule above exists. A working feature that *feels* broken (frozen, silent, ambiguous) is a bug.
- **Zero-terminal for end users.** The target user downloads one file, double-clicks, and answers prompts — no command line. Distribution and setup decisions are judged against that bar (KDD-17).
- **Limited programming experience → optimize for the next reader.** Comment intent, not mechanics. Explain *why*. Spell out reasoning rather than asserting; the maintainer asks "is this arbitrary or is there a reason?" and deserves the reason. Prefer clarity over cleverness everywhere.
- **Build for contributors who aren't them, in ways not yet conceived.** Leave extension seams and document them (`docs/architecture.md`). Modular, adapter-bounded, test-covered code is the deliverable — not just working code.
- **Real hardware is the ground truth.** Many of the best fixes came from real-disc testing on the Bazzite + Pioneer BDR-209D rig (the >587 offset bug → cyanrip; the cdrdao TOC flake → Rescan; the EAC baseline). Code-side prep is welcome, but the final proof is a hardware run; flag hardware-gated work honestly.
- **Every shipped bug gets a regression test in the same change.** Institutional, non-negotiable (see `docs/testing.md`).
- **Momentum with safety.** The maintainer pushes for autonomous forward progress ("proceed", "get it done") — so act on reversible, in-scope work without asking, commit in small test-green units, and report at milestones. Still stop for destructive or scope-changing decisions.
- **Autonomous releases are expected.** Cut releases via the `workflow_dispatch` path from the cloud session (see CI/release below); don't wait for a manual tag push.

## Companion documents

Read these alongside this file when picking up a session:

- **`PLANNING.md`** — architecture, module design, key design decisions (KDD-01 through KDD-21)
- **`TASKS.md`** — active task checklist; update status (`[ ]` → `[~]` → `[x]`) as work progresses. Sections: P0 (v1 release, T01-T32), P1.1 (install/uninstall ease — highest-priority P1 subset), P1 (broader backlog), P2 (future), Out of scope.
- **`DEPENDENCIES.md`** — dep table with last release dates and replacement plans; review per the cadence stated in that file
- **`README.md`** — outward-facing project description and install instructions
- **`docs/architecture.md`** — architecture & contributor guide: the layered design, the core patterns *with the why and hard-won lessons* (adapter layer, the never-block-the-GUI-thread discipline + worker mechanics, subprocess rules, never-raise parsers, the dependency subsystem, the MainWindow mixin decomposition, error/logging), extension recipes, packaging/release/security, and future directions. **Start here to extend the program.** (Absorbed the former `docs/best-practices.md`.)
- **`docs/README.md`** — index of the docs/ directory, the single-source-of-truth map, and a rebuild-from-scratch checklist
- **`docs/whipper-gui-research-brief-v2.1.md`** — the project brief; canonical for requirements and scope
- **`docs/whipper-gui-session-start.md`** — bootstrap instructions a fresh Claude Code session uses to reproduce the initial planning artifacts; its **Step 0** holds the optional Research-mode prompt for refreshing tool-choice validation
- **`docs/log-format-comparison.md`** — whipper rip log vs EAC log side-by-side (referenced by KDD-11)
- **`docs/testing.md`** — the testing strategy & standards (the trophy + hardware gate, the five-tier case taxonomy, property/golden/fault-injection guidance, the coverage gate, and the institutional rules: every bug gets a regression test; parsers never raise)
- **`docs/test-plan.md`** — manual & release testing: the end-to-end acceptance run, the EAC output-parity check, the distro + problem-permutation matrices, and the deep single-feature gated cases (absorbed the former `docs/release-testing.md`)
- **`docs/session-log.md`** — chronological session history (what was built/decided/learned each session, newest first). Read it for *continuity*; durable lessons graduate from it into the docs above.
- **`docs/ripper-engine-strategy.md`** — living research/options doc on forking/combining whipper + cyanrip long-term (licensing, option menu, decision gates). Revisits KDD-18; research only, not a commitment.
- **`docs/archive/`** — retired point-in-time investigations (ecosystem audit, read-offset, upstream-modification/CTDB spec) **plus external reference material** (the EAC archival master guide); durable conclusions have graduated into KDDs / DEPENDENCIES / adapter comments (see `docs/archive/README.md`)

If `PLANNING.md` and the brief conflict, the brief wins on requirements/scope and `PLANNING.md` wins on implementation choices. If `PLANNING.md` and the research output conflict, raise it with the user — don't silently pick.

There is no `compass_artifact_*.md` in the repo; the original v1 research validation was unavailable when the project was bootstrapped, so the project proceeded against the brief alone. To refresh tool-choice research, follow `docs/whipper-gui-session-start.md` Step 0.

---

## Project operations

*This section grows as the project develops. Add concrete commands, paths, and operational notes as they're established. Keep entries terse.*

### Build commands

- AppImage: `bash build/build_appimage.sh` (produces `whipper-gui-x86_64.AppImage` at repo root via `python-appimage`)
- App icon: `python3 build/make_icon.py` (regenerates the committed `build/python-appimage/whipper-gui.png`; needs Pillow)

### CI / release

- **CI:** `.github/workflows/ci.yml` runs `pytest` **and `ruff`** (lint + format check) on every push to `main` and every PR.
- **Releasing is automated** — do *not* hand-build/upload. Cut a release by pushing a version tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) **or by dispatching the Release workflow with the tag as input — it creates the tag itself (works from the cloud session via the Actions API; tag pushes don't)**. `.github/workflows/release.yml` then builds the AppImage (reusing `build/build_appimage.sh`) and attaches it + a `.sha256` to a GitHub Release; `publish-pypi.yml` publishes the wheel+sdist. `v0.*` tags publish as pre-releases. Before tagging: **(1)** bump the version in **`src/whipper_gui/__init__.py` (`__version__`)** — this is the *single source*; `pyproject.toml` reads it dynamically, so do **not** add a version there — and **(2)** move the `CHANGELOG.md` `[Unreleased]` entries under a new `## [X.Y.Z] — <date>` heading with a matching compare link.
- **Single record of changes:** every notable change is recorded in **`CHANGELOG.md`** (the one authoritative update log; Keep-a-Changelog style). Add a bullet to its `[Unreleased]` section **in the same commit** as the change. `PLANNING.md` (KDDs) and `docs/session-log.md` are for *design decisions and session history*, not the user-facing change record.

### Run commands

- **Quickstart from a fresh clone:** `bash dev-setup.sh` then `source .venv/bin/activate && whipper-gui`
- **Manual:** `python3 -m venv .venv && source .venv/bin/activate && pip install --upgrade pip && pip install -e . && whipper-gui`
- **From the AppImage (once published):** `./whipper-gui-x86_64.AppImage`
- **From a `pipx` install (once published):** `whipper-gui`
- **Version check without launching the GUI:** `whipper-gui --version`
- **Preflight / "doctor" (first-pass environment test, no CD needed):** `whipper-gui --doctor` (no extra flags — it just runs the full check and exits). For the tunable form use `python scripts/preflight.py`, which adds `--no-network` (skip the MB/CAA/CTDB reachability checks) and `--backend whipper|cyanrip` (override which backend to probe). Both exit non-zero on a hard blocker. Logic lives in `src/whipper_gui/preflight.py` (reuses the real adapters + the dependency subsystem); `--doctor` and the script are thin CLIs over it.

### Test commands

- `pytest` from repo root (no env vars needed — `pyproject.toml` sets `pythonpath = ["src"]`)
- **What CI enforces:** branch coverage + a hard floor — `pytest --cov=whipper_gui --cov-report=term-missing --cov-fail-under=91` on a **Python 3.11–3.13 matrix**. The gate **ratchets up, never down**.
- Property-based tests (parsers never crash on any input): `pytest tests/test_parsers_property.py` (needs `hypothesis`, in the `dev` extra).
- Periodic test-quality audit (slow, not a CI gate): `pipx run mutmut run --paths-to-mutate src/whipper_gui/parsers/`.
- **Testing strategy + the rules every change is held to live in [`docs/testing.md`](docs/testing.md)** (the trophy + hardware gate, the five-tier case taxonomy, and the Definition of Done). **Institutional rule: every shipped bug gets a regression test in the same PR as the fix; every new parser of external output gets a property-based "never raises" test.**

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

### Enforced safety (.claude/ + git hook)

Beyond the *guidance* in the Critical rules above, a few things are **enforced** (not just trusted):

- **`.githooks/pre-commit`** — blocks any commit that stages an audio/copyrighted-media file (Critical rule #8), even via `git add -f`. The hard guarantee behind the rule + the `.gitignore` backstop. Activate per clone with `git config core.hooksPath .githooks` (**`dev-setup.sh` does this**); bypass for a verified CC0/self-generated sample with `git commit --no-verify`.
- **`.claude/settings.json`** (committed, shared) — permission `deny` for destructive commands (`rm -rf`, `git push --force`/`-f`/`--force-with-lease`) and secret reads (`.env*`, `secrets/**`), plus a `PreToolUse` hook that blocks a Bash call while audio is staged (the Claude-session belt for the same rule; git hook is the canonical guard). Deliberately does **not** prompt on normal `git push`, to preserve the merge-and-keep-going workflow. Personal overrides go in `.claude/settings.local.json` (git-ignored). Run `/memory` or `/hooks` to confirm what loaded.

### Important paths

- Source root: `src/whipper_gui/`
- User config: `~/.config/whipper-gui/config.toml`
- User logs: `~/.local/share/whipper-gui/log.txt`
- Whipper config (shared with Distrobox container): `~/.config/whipper/whipper.conf`
- Whipper binary (host-exported from Distrobox): `~/.local/bin/whipper`
- MusicBrainz Picard (Flatpak, used for auto-launch on unknown discs): `flatpak run org.musicbrainz.Picard`

### Getting help (Claude Code / Anthropic)

For problems with the **AI tooling itself** — Claude Code, the Claude model, or the Anthropic API. (This is *not* Whipper GUI end-user support; app questions route to the project maintainer, not Anthropic.)

- **Fastest:** the support messenger at [support.anthropic.com](https://support.anthropic.com/en/) — message icon, bottom-right. Or, when signed in, **[Claude.ai](https://claude.ai)** / **[Console](https://console.anthropic.com)** → your initials → **"Get help."** (Signed-in routes faster — they see the account.)
- **API / developer issues:** [support.claude.com](https://support.claude.com).
- **Topic-specific email:** safety / harmful content → `usersafety@anthropic.com`; security vulnerability → `security@anthropic.com`; privacy / data request → `privacy@anthropic.com`.
- **Claude via Amazon Bedrock or Google Vertex:** contact AWS / Google support, not Anthropic directly.
- Reference: [How can I contact Support?](https://support.anthropic.com/en/articles/9015913-how-can-i-contact-support)

### Session history

Chronological session notes — what was built, decided, and learned each session — live in **[`docs/session-log.md`](docs/session-log.md)** (newest first). They're kept out of this file so the always-loaded project context stays lean and scannable.

**Graduation rule:** a durable lesson from the log belongs in its real home — *Code conventions* / *Critical rules* above, a KDD in `PLANNING.md`, or `docs/architecture.md` / `docs/testing.md` — not left only in the dated log. The log is append-only chronology; the rules are the distillation.
