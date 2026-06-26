# Documentation

This directory contains the canonical source material the project was built from, plus reference documents the rest of the codebase points to.

## Single source of truth — where each kind of content lives

To keep the docs efficient and stop the same rule from sprawling across files (and going stale in some), every kind of content has **one canonical home**. State it there; everywhere else, *link* — don't re-explain.

| Content | Canonical home |
|---|---|
| Locked coding conventions & critical rules | `CLAUDE.md` → *Code conventions* / *Critical rules* |
| How the maintainer works / project values | `CLAUDE.md` → *Working with the maintainer* |
| CI / release & build operations | `CLAUDE.md` → *Project operations* |
| Architectural decisions + rationale (KDD-NN) | `PLANNING.md` |
| Module map & per-module responsibility | `PLANNING.md` |
| Layered design, patterns, engineering lessons, extension recipes, packaging/release/security | `docs/architecture.md` |
| Testing strategy, taxonomy, institutional rules | `docs/testing.md` |
| Manual & release testing (acceptance run + gated cases + tester matrices) | `docs/test-plan.md` |
| Dependency pins, dates, licenses, retirement log | `DEPENDENCIES.md` |
| User-facing changes | `CHANGELOG.md` |
| Active task queue | `TASKS.md` |
| What happened each session (chronology) | `docs/session-log.md` |
| Install / usage docs | `README.md` |

A lesson legitimately appears in **two** places: a one-line *rule* in its canonical home, and a dated *entry* in `docs/session-log.md` recording how it arose (the **graduation rule** — distillation up, chronology down). Anything beyond that is duplication to delete.

## Source documents (anchor for "rebuild from scratch")

These two files, together with the top-level `CLAUDE.md`, `PLANNING.md`, `TASKS.md`, `DEPENDENCIES.md`, and `README.md`, are the full context needed to reproduce the project from a clean slate.

| File | What it is | Authority on |
|---|---|---|
| [`whipper-gui-research-brief-v2.1.md`](whipper-gui-research-brief-v2.1.md) | The original requirements brief — every P0/P1 feature, every constraint, every scope decision started here. | **Requirements and scope.** When PLANNING.md and the brief conflict, the brief wins on requirements; PLANNING wins on implementation. |
| [`whipper-gui-session-start.md`](whipper-gui-session-start.md) | The bootstrap instructions a fresh Claude Code session followed to produce the initial five top-level files — and (Step 0, optional) the paste-verbatim Research-mode prompt for refreshing the tool-choice validation against the brief. | **Initial repo state + the bootstrap procedure, and how to refresh the tool-choice research.** Re-run it against a clean repo to re-derive the planning artifacts. |

> **About the `compass_artifact_*.md` Research validation file:** the original v1 brief produced a compass-artifact research validation in a Claude Research session; the user could not locate it when this project was bootstrapped, so the project proceeded against the brief alone (see CLAUDE.md "Companion documents"). If the session-start Step 0 rerun prompt is ever invoked, save the resulting `compass_artifact_*.md` into this directory.

## Reference documents

| File | What it is |
|---|---|
| [`architecture.md`](architecture.md) | **Architecture & contributor guide** — the layered design and dependency direction; the core patterns *with the why and the hard-won lessons* (adapter layer, the never-block-the-GUI-thread discipline + worker mechanics, subprocess rules, never-raise parsers, the dependency subsystem, the MainWindow mixin decomposition, error/logging); step-by-step **extension recipes**; the testing contract; packaging/building/releasing; security & licensing hygiene; and the architectural future-directions horizon. **Start here to extend the program.** (Absorbed the former `best-practices.md`.) |
| [`testing.md`](testing.md) | **Testing strategy & standards** — the trophy + a real-hardware gate, the five-tier case taxonomy (easy/medium/hard/edge/unexpected), when to use property-based / golden / fault-injection / mutation testing, the institutional rules (every bug gets a regression test; parsers never raise; coverage gate ratchets up), and a Definition of Done. Portable to sibling projects. |
| [`test-plan.md`](test-plan.md) | **Manual & release testing** — the end-to-end clean-cycle acceptance run (uninstall → fresh install → drive setup → rip → verify), the **EAC output-parity** check (with the per-track CRC baseline), the **Linux-distro** + **problem-permutation** matrices for onboarding testers, *and* the deep single-feature gated cases (CTDB verify CRC, `drive analyze`/`offset find` strings, GUI screenshot, Picard UX, PyPI go-live, the cyanrip parity run). Run one at a time and record results. (Absorbed the former `release-testing.md`.) |
| [`appimage-testing.md`](appimage-testing.md) | How the AppImage is built (on every push to `main`, on demand for any branch, and at release) and how to test it in each case — including branches with no published release yet. |
| [`log-format-comparison.md`](log-format-comparison.md) | Side-by-side comparison of whipper's rip log against EAC's, anchoring [PLANNING.md KDD-11](../PLANNING.md). The hand-authored EAC log at `tests/fixtures/rip_log_eac_reference.log` is the comparison's data. |
| [`session-log.md`](session-log.md) | **Chronological session history** — what each Claude Code session built, decided, and learned (newest first). The project's institutional memory; durable lessons graduate from here into the docs above. |
| [`ripper-engine-strategy.md`](ripper-engine-strategy.md) | **Research / options (living, long-horizon):** the feasibility of forking and/or combining whipper + cyanrip and maintaining our own engine — licensing analysis, the option menu, and decision gates. Revisits KDD-18's "never fork" stance; a commitment requires a new KDD. |
| [`mp3-wav-support.md`](mp3-wav-support.md) | **Design-of-record for multi-format output (SHIPPED 2026-06-26, KDD-22):** the FLAC-master + WavPack/MP3/WAV-derived model, per-format parity semantics, the verified encoder args (FLAC `-8 -e -p`, MP3 VBR `-V0`, WavPack lossless), the transcode-always decision, and the one open item (embedding cover art inside `.wv`). Flipped Critical Rule #4 (FLAC is now the default/master, not the only format). |
| [`archive/`](archive/README.md) | Retired point-in-time investigations (ecosystem audit, read-offset, upstream-modification/CTDB spec) **plus external reference material** (the EAC archival master guide). Their durable conclusions have graduated into KDDs / DEPENDENCIES / adapter comments — see `archive/README.md` for the map. |

## Where the rest of the project context lives

Outside this directory:

| File | What it covers |
|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | Persistent rules and conventions; locked rules section; project operations |
| [`../PLANNING.md`](../PLANNING.md) | Architecture, directory tree, per-module responsibilities, adapter designs, dependency-manager design, keyed design decisions (KDD-01 … KDD-21) |
| [`../TASKS.md`](../TASKS.md) | Active task checklist — P0 (T01-T32), P1.1 (install/uninstall ease), P1 (broader backlog), P2 (future), Out of scope |
| [`../DEPENDENCIES.md`](../DEPENDENCIES.md) | Pinned versions, last upstream release dates, retirement-review log |
| [`../README.md`](../README.md) | User-facing install instructions, troubleshooting, EAC comparison |
| [`../build/python-appimage/README.md`](../build/python-appimage/README.md) | AppImage build recipe details |

## Rebuild-from-scratch checklist

If you needed to start over with a fresh git repository:

1. **Place these files at repo root:**
   - `CLAUDE.md` (copy verbatim from the user's CLAUDE.md template — the rules section is locked)
   - `PLANNING.md`, `TASKS.md`, `DEPENDENCIES.md`, `README.md` (produced by Claude Code Step 3 per `whipper-gui-session-start.md`)
2. **Place these files in `docs/`:**
   - `whipper-gui-research-brief-v2.1.md`
   - `whipper-gui-session-start.md`
3. **(Optional but recommended after 6+ months) Re-run Research validation:** follow `whipper-gui-session-start.md` **Step 0**, save the result as `docs/compass_artifact_<hash>_text_markdown.md`.
4. **Boot a fresh Claude Code session,** attach the brief + session-start + (if present) compass artifact + CLAUDE.md, and ask it to execute `whipper-gui-session-start.md`. The session reproduces PLANNING.md, TASKS.md, DEPENDENCIES.md, README.md from scratch and then begins executing the task list.
5. **Subsequent sessions** follow CLAUDE.md as the primary instruction document, using TASKS.md to track what's next.
</content>
