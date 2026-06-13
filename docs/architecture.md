# Architecture & Contributor Guide

> **Who this is for.** Anyone — not just the original author — who wants to
> understand, extend, or safely change Whipper GUI. It explains *how the
> pieces fit*, *the patterns to follow*, and *where to plug new things in*.
> Read it alongside `CLAUDE.md` (the locked conventions + critical rules)
> and `PLANNING.md` (the design-decision log, KDD-01…KDD-18).

## 1. What this program is

A Linux desktop GUI (PySide6 / Qt6) that drives the `whipper` (and, newer,
`cyanrip`) audio-CD ripping CLIs to produce EAC-equivalent, archival-quality
FLAC rips. The GUI itself never rips: it shells out to a host-exported
`~/.local/bin/whipper`, which transparently enters a Distrobox container
named `ripping` to do the work. **This routing is non-negotiable** (see
`CLAUDE.md` Critical Rule #3) — the GUI is an orchestrator and a user
interface, not a ripper.

```
┌────────────────────────────────────────────────────────────┐
│  Whipper GUI (this app, runs on the host as PySide6)         │
│   • picks the MusicBrainz release  • builds the rip command  │
│   • shows progress + the fidelity verdict  • tags / art      │
└───────────────┬──────────────────────────────────────────────┘
                │ subprocess → ~/.local/bin/whipper (host export)
                ▼
        ┌───────────────────────┐     MusicBrainz / Cover Art Archive /
        │ Distrobox "ripping"   │     CTDB / AccurateRip  ◄─ queried by the
        │ container: whipper /  │        GUI on the host (never the ripper)
        │ cyanrip + flac        │
        └───────────────────────┘
```

## 2. The layers (and the dependency direction)

Dependencies point **downward** only — UI depends on workers/adapters,
adapters depend on nothing in the UI. Keep it that way; it's what makes the
pieces independently testable and replaceable.

| Layer | Package | Responsibility | May import |
|-------|---------|----------------|------------|
| **UI** | `ui/` | Qt widgets, dialogs, the main window. *No business logic, no blocking I/O.* | workers, adapters, parsers, deps, config |
| **Workers** | `workers/` | `QObject`s that run slow work (network, subprocess) off the GUI thread and emit results as signals. | adapters, parsers |
| **Adapters** | `adapters/` | The *only* code that talks to an external tool/service (whipper, cyanrip, metaflac, MusicBrainz, Cover Art Archive, CTDB, AccurateRip). Thin, swappable. | parsers, stdlib |
| **Parsers** | `parsers/` | Turn external tool output (rip logs, disc info) into typed dataclasses. Pure, never raise. | stdlib only |
| **Deps** | `deps/` | The single dependency self-management subsystem (detect → install → guide) and the host bootstrap/teardown engines. | adapters, stdlib |
| **Domain** | `ctdb/` | Backend-independent CTDB verify (TOC math, PCM decode, CRC). | adapters, stdlib |
| **Core** | `config.py`, `paths.py`, `logging_setup.py`, `app.py` | Config schema, well-known paths, app entry/composition root. | everything (composition) |

`app.py` is the **composition root**: it constructs the concrete adapters,
picks the backend from config, and injects everything into `MainWindow`.
Nothing else should construct adapters — inject them, so tests can pass fakes.

## 3. Patterns you must follow

### 3.1 Adapter layer for every external tool (Critical Rule #1)
Every call into an unmaintained or external dependency goes through a thin
adapter behind an interface, so a future replacement doesn't ripple into the
GUI. The ripping backends sit behind the `WhipperBackend` ABC
(`adapters/whipper_backend.py`); `CyanripImpl` is a second implementation.
MusicBrainz, the Cover Art Archive, metaflac, CTDB, and AccurateRip each
have their own adapter module. **Never** call an external tool from a widget.

### 3.2 The threading discipline (this caused real bugs — internalize it)
**Never run a blocking operation on the Qt GUI thread.** Blocking = network,
`subprocess.run`, large-file hashing/copying, `thread.join()`,
`kbuildsycoca6`, anything that can take more than a few milliseconds. When
the GUI thread blocks, the window goes "Not Responding" and every click is
ignored until it unblocks (see the 2026-06-13 update-freeze post-mortem in
`CLAUDE.md`).

Two sanctioned tools:
- **Need the result?** Use a `QObject` worker moved to a `QThread`; emit the
  result as a signal (cross-thread signals are delivered on the GUI thread).
  See `workers/` and `_start_*` methods. Daemon `threading.Thread` is used
  for fire-once background work whose result comes back via a Qt signal
  (e.g. the post-rip cover-art fetch).
- **Don't need the result?** Fire-and-forget: `subprocess.Popen(..., start_new_session=True)`
  and return immediately (e.g. the menu-cache refresh, `gio` trust-marking).

When reviewing a change: *if this line ran on a stalled network or a cold
container, would the window freeze?* If yes, it belongs in a worker.

### 3.3 Parsers never raise (institutional rule)
Anything that parses external output uses **named-group regexes** (not
column indices — tool output shifts between minor versions), tolerates
garbage, and returns a best-effort dataclass instead of raising. Every new
parser gets a `hypothesis` "never raises on arbitrary input" property test
(`tests/test_parsers_property.py`).

### 3.4 One dependency subsystem (Critical Rule #6)
All "is this tool present and the right version?" logic lives in `deps/`
(probe → three-tier resolve: auto-install → queued install → copyable search
string). Do **not** add ad-hoc `shutil.which` checks elsewhere. New deps are
registered in `deps/registry.py`.

### 3.5 MainWindow is composed from mixins
`MainWindow` was a 1700-line god-object; it's being decomposed (2026-06-13)
into cohesive `*Mixin` classes it inherits, so each concern lives in its own
focused file while methods stay reachable as `window._x` (which the test
suite and Qt signal wiring depend on). The mixin contract: each documents
the `self.` attributes it assumes `MainWindow.__init__` has set.

| Concern | Home | Status |
|---------|------|--------|
| Pure helpers (string-safety, fidelity verdict) | `main_window_helpers.py` | done |
| Self-update (check / download / install / restart) | `main_window_update.py` (`UpdateMixin`) | done |
| Rip lifecycle, force-stop, eject, cover art | `main_window.py` (rip section) | *to extract → `RipMixin`* |
| Host setup / AppImage integration / uninstall | `main_window.py` | *to extract → `ProvisioningMixin`* |
| Drive setup / offset / access diagnosis | `main_window.py` | *to extract → `DriveMixin`* |
| Dependency check / resolve / summary | `main_window.py` | *to extract → `DependencyMixin`* |
| Construction, menus, signal wiring, MusicBrainz slots | `main_window.py` | stays (the assembler) |

## 4. Extension points — how to add things

> The goal: a contributor who has never spoken to the author can add a
> capability by following one of these recipes, without touching unrelated
> code.

### Add a ripping backend (e.g. a future `XyzripImpl`)
1. Implement the `WhipperBackend` ABC in `adapters/xyzrip_backend.py`
   (`rip`, `disc_info`, `version`, optional `find_offset`/`analyze_drive`).
2. Add a parser in `parsers/` for its log + disc-info output (named-group
   regex, never-raise, + a property test). Map it onto the shared `RipLog`
   / `DiscInfo` dataclasses so the GUI verdict code is unchanged.
3. Add the choice to `Config.ripper_backend` and select it in `app.py`.
4. If it needs a package, add a wizard step in `deps/host_setup.py` and CLI
   parity in `setup-host.sh` (keep the two install stanzas in sync).
5. Gate any backend-specific Settings widgets in `settings_dialog.py`
   (`_apply_backend_capabilities`) — grey out, explain, never lose values.
   **Never fork whipper** (Critical Rule / KDD-18) — write an adapter.

### Add an output format (MP3, WAV, …)
Route the encoder through the dependency subsystem (no bespoke install
code), add the format to `Config`, and pass it through `RipParameters` →
the backend argv. FLAC-only is a v1 scope rule (Critical Rule #4), so this
is a deliberate, reviewed expansion.

### Add a dependency
Register it in `deps/registry.py` with its probe and install tiers. Mark it
`optional=True` if its absence shouldn't nag. Nothing else changes.

### Add a parser of external output
New module in `parsers/`, named-group regex, return a dataclass, never
raise, add a property test. If it feeds a verdict, extend `fidelity_summary`
in `main_window_helpers.py`.

### Add a metadata or art source
New adapter behind a small interface (mirror `MusicBrainzClient` /
`cover_art`). Query it on the host (Critical Rule #5: the GUI resolves the
release, never the ripper's interactive prompt).

## 5. Testing contract (the safety net that lets us refactor fearlessly)

- `pytest` from the repo root; CI enforces **branch coverage with a hard
  floor** (`--cov-fail-under`, currently ~88, ratchets up) on Python
  3.11–3.13, plus `ruff` lint + format.
- Test strategy, taxonomy (easy/medium/hard/edge/unexpected), and the
  Definition of Done live in `docs/testing.md`.
- **Institutional rules:** every shipped bug gets a regression test in the
  same change; every new external-output parser gets a never-raises property
  test.
- UI is testable because adapters/workers are injected — pass fakes, drive
  slots synchronously, connect to signals, assert. See `tests/test_ui_*` and
  `tests/test_*_worker.py`. **Stub anything that would touch the network or a
  real subprocess** (the update downloader, the cover-art fetcher, `gio`/
  `kbuildsycoca`) — an unstubbed one can hang the suite.

## 6. Future improvements & directions

Concrete backlog lives in `TASKS.md`; this section is the *architectural*
horizon — the seams that exist so future contributors can take the program
places we haven't planned.

- **Backends as plugins.** The `WhipperBackend` ABC + `Config.ripper_backend`
  selector already make backends swappable. A small entry-point/registry
  could let third parties drop in a backend without editing `app.py`.
- **A real preferences framework.** `config.py` is a flat dataclass with
  manual schema migration; as options grow, a typed settings registry with
  per-key metadata (label, help, backend-applicability) would let the
  Settings dialog build itself instead of hand-wiring each widget.
- **CTDB repair** (KDD-14/16): the verify half is built and backend-
  independent; repair (wrapping the .NET `ctdb-cli`) is the headline EAC++
  differentiator, parked on the bundle-vs-install question.
- **Library management:** ReplayGain, auto-move to a library tree, multi-disc
  queue, udev-driven auto-detect on disc insert — all sit above the rip
  pipeline and need no changes to the adapter layer.
- **Off-thread the launch probes** (TASKS #11): the dependency check still
  runs synchronously after `show()`; moving it (and `refresh_drives`) into a
  worker would make startup fully non-blocking on a cold container.
- **Internationalization:** user-facing strings are currently inline; a
  future `tr()` pass would route them through Qt's translation system.
- **Packaging reach:** AppImage + pipx today; the adapter/host-wizard split
  keeps a Flatpak-with-host-access or other channel conceivable without
  touching the GUI (subject to Critical Rule #3).

When you add a capability the author never imagined: keep the layer
direction (§2), put external calls behind an adapter (§3.1), never block the
GUI thread (§3.2), and leave a test. That's the whole contract.
