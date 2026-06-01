# Documentation

This directory contains the canonical source material the project was built from, plus reference documents the rest of the codebase points to.

## Source documents (anchor for "rebuild from scratch")

These three files together with the top-level `CLAUDE.md`, `PLANNING.md`, `TASKS.md`, `DEPENDENCIES.md`, and `README.md` are the full context needed to reproduce the project from a clean slate.

| File | What it is | Authority on |
|---|---|---|
| `whipper-gui-research-brief-v2.1.md` | The original requirements brief — every P0/P1 feature, every constraint, every scope decision started here. | **Requirements and scope.** When PLANNING.md and the brief conflict, the brief wins on requirements; PLANNING wins on implementation. |
| `whipper-gui-session-start.md` | The bootstrap instructions a fresh Claude Code session followed to produce the initial five top-level files (CLAUDE.md, PLANNING.md, TASKS.md, DEPENDENCIES.md, README.md). | **Initial repo state and the bootstrap procedure.** Re-run this against a clean repo to re-derive the planning artifacts. |
| `whipper-gui-research-rerun-prompt.md` | Instructions for invoking Claude Opus 4.7 Research mode against the brief to produce a fresh `compass_artifact_*.md` validation pass. | **How to refresh the tool-choice research** (framework, distribution, dependencies) when more than ~6 months have elapsed since the last validation. |

> **About the `compass_artifact_*.md` Research validation file:** the original v1 brief produced a compass-artifact research validation in a Claude Research session; the user could not locate it when this project was bootstrapped, so the project proceeded against the brief alone (see CLAUDE.md "Companion documents"). If the rerun-prompt is ever invoked, save the resulting `compass_artifact_*.md` into this directory.

## Reference documents

| File | What it is |
|---|---|
| `log-format-comparison.md` | Side-by-side comparison of whipper's rip log against EAC's, anchoring [PLANNING.md KDD-11](../PLANNING.md). The hand-authored EAC log at `tests/fixtures/rip_log_eac_reference.log` is the comparison's data. |
| `appimage-testing.md` | How the AppImage is built (on every push to `main`, on demand for any branch, and at release) and how to test it in each case — including branches with no published release yet. |

## Where the rest of the project context lives

Outside this directory:

| File | What it covers |
|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | Persistent rules and conventions; locked rules section; project operations |
| [`../PLANNING.md`](../PLANNING.md) | Architecture, directory tree, per-module responsibilities, adapter designs, dependency-manager design, 15 keyed design decisions |
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
   - `whipper-gui-research-rerun-prompt.md`
3. **Re-run Research validation** (optional but recommended after 6+ months): follow `whipper-gui-research-rerun-prompt.md`, save the result as `docs/compass_artifact_<hash>_text_markdown.md`.
4. **Boot a fresh Claude Code session,** attach the brief + session-start + (if present) compass artifact + CLAUDE.md, and ask it to execute `whipper-gui-session-start.md`. The session will reproduce PLANNING.md, TASKS.md, DEPENDENCIES.md, README.md from scratch and then begin executing the task list.
5. **Subsequent sessions** follow CLAUDE.md as the primary instruction document, using TASKS.md to track what's next.
