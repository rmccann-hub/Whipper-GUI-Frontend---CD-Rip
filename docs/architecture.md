# Architecture & Contributor Guide

> **Who this is for.** Anyone — not just the original author — who wants to
> understand, extend, or safely change Whipper GUI. It explains *how the
> pieces fit*, *the patterns to follow* (with the **why** and the hard-won
> lessons behind them), and *where to plug new things in*.
>
> Read it alongside its companions, each of which owns a different slice so
> nothing is stated twice:
> - **[`../CLAUDE.md`](../CLAUDE.md)** — the *locked* contract: code
>   conventions, critical rules, deviation policy. If anything here ever
>   conflicts with CLAUDE.md, **CLAUDE.md wins**; this guide explains and
>   expands those rules, it does not override them.
> - **[`../PLANNING.md`](../PLANNING.md)** — the module map and the keyed
>   design-decision log (KDD-01 … KDD-19): the "why is it like this?" record.
> - **[`testing.md`](testing.md)** — the testing strategy, taxonomy, and
>   Definition of Done.
> - **[`session-log.md`](session-log.md)** — the dated chronology of how each
>   lesson here arose.

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

> **Code style** (type hints, naming, ~300-line module heuristic, heavy
> intent-comments, no clever metaprogramming) is owned by `CLAUDE.md`
> *Code conventions* — follow it there; it isn't restated here.

## 3. Patterns you must follow

Each pattern below is the **single canonical home** for that topic. Other
docs (and KDDs) link here rather than restating.

### 3.1 Adapter layer for every external tool (Critical Rule #1)
Every call into an unmaintained or external dependency goes through a thin
adapter behind an interface, so a future replacement is a one-file swap, not
a codebase-wide rewrite. Currently flagged unmaintained: `whipper`,
`python-musicbrainzngs`, `python-appimage`.

The pattern (designs in [`../PLANNING.md`](../PLANNING.md) §5–§6):

- Define an **abstract base class** describing *what the GUI needs*, in our
  own vocabulary (`WhipperBackend`, `MusicBrainzClient`, `CTDBClient`). The
  GUI depends only on the ABC.
- Provide a **concrete implementation** that wraps the real tool/library
  (`adapters/whipper_backend.py`; `CyanripImpl` is a second backend).
- **Inject the adapter** at construction so tests pass a fake — no real
  binary, network, or drive in the suite.
- Keep the ABC surface *minimal and capability-shaped*. Optional capabilities
  (e.g. `analyze_drive()` / `find_offset()`) default to `NotImplementedError`
  so fakes and alternative backends still construct.

Design the interface around the *consumer's* needs, not the wrapped library's
shape — that's what makes the dependency swappable. **Never** call an external
tool from a widget; **never fork whipper** (KDD-18) — write an adapter.

### 3.2 Never block the GUI thread (this caused real bugs — internalize it)
Anything that can take more than a few milliseconds — `subprocess.run`,
network I/O, large-file hashing/copying, `thread.join()`, `QThread.wait()`,
`kbuildsycoca6`, even a "best-effort" shell-out — freezes the event loop. A
frozen loop means the window shows "Not Responding" and ignores *every* click
(including Cancel and the X) until it returns.

Two sanctioned tools:
- **Need the result?** A `QObject` worker moved to a `QThread` (or a daemon
  `threading.Thread` that reports back via a queued signal). The result
  arrives as a signal — cross-thread connections are delivered on the GUI
  thread. See `workers/` and the `_start_*` methods.
- **Don't need the result?** Fire-and-forget:
  `subprocess.Popen(argv, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)`
  and return immediately. This is how the menu-cache refresh
  (`appimage_integration._default_refresh`) and the GNOME `gio` trust-marking
  (`_mark_trusted`) run.

When reviewing a diff, ask: *if this line ran on a stalled network or a cold
container, would the window freeze?* If yes, it belongs in a worker or a
fire-and-forget `Popen`.

> **Post-mortem (2026-06-13), worth re-reading before any UI change.** The
> in-app updater went "Not Responding" frozen at 100% for minutes; Cancel did
> nothing and the X took ages. Root cause: the post-download menu
> re-integration called `kbuildsycoca6` via `subprocess.run(timeout=30)` **on
> the GUI thread**. The same anti-pattern lurked in `_mark_trusted` (a 15 s
> `gio` call) and the launch dependency probe (`whipper --version`, which
> enters the container). All three were the *same class* of bug.

Worker mechanics, all demonstrated in `workers/`:

- **Worker-object + `moveToThread`, not `QThread` subclassing.** A `QThread`
  instance lives in the thread that *created* it, so slots on a `QThread`
  subclass run in the wrong thread. Put the work in a `QObject` worker and
  `moveToThread()` it. See `RipWorker`, `MbWorker`, `DriveSetupWorker`.
- **Never touch widgets from a worker thread.** Communicate results back via
  **signals** (delivered as queued connections on the GUI thread). The worker
  emits `progress`/`status`/`finished`; the GUI updates widgets in the slots.
- **Clean up deterministically:** connect `worker.finished → thread.quit`,
  `worker.finished → worker.deleteLater`, `thread.finished →
  thread.deleteLater`. **Join/stop threads before the window closes**
  (`closeEvent`) — destroying a running `QThread` aborts the whole app.
  (This bit us: closing the drive-setup dialog mid-detection killed the
  process — fixed by cancelling + joining on `reject()`/`closeEvent`.)
- **Don't call `QApplication.processEvents()` from inside a slot that runs
  during a modal `exec()`.** It re-enters the event loop and pumps unrelated
  timers/threads — an order-dependent crash. To force an immediate repaint
  (e.g. an "installing…" label before a blocking call), use `widget.repaint()`.
- Use thread-safe primitives for cancellation flags — a plain `bool` set from
  the GUI thread and read by the worker is fine under the GIL; anything richer
  needs care.

### 3.3 Invoking external programs (subprocess)
The GUI shells out constantly (whipper, flatpak, eject, pkill):

- **Never `shell=True`.** Pass an **argument list**, not a string — the module
  handles quoting/escaping and there is no shell to inject into. The GUI puts
  user-entered metadata (album/track names) into argv and path templates, so
  this is the single most important subprocess-security practice.
- **Resolve executables to absolute paths when the environment is hostile.** A
  GUI launched from a desktop icon (not a shell) inherits a *minimal* `PATH`
  that can miss `~/.local/bin` and even `/usr/bin`. `drive_control._resolve()`
  falls back through common absolute locations; do the same for any tool a
  desktop-launched process must reach.
- **Always set a `timeout`** (install commands cap at 300 s; force-stop probes
  at 20 s) — a wedged child must not hang forever.
- **Capture output, then `log` it** — don't stream to a console the user can't
  see. Surface the *last* error line; keep the full output in the log file.
- **Catch specific exceptions:** `FileNotFoundError`,
  `subprocess.TimeoutExpired`, `subprocess.SubprocessError`, `OSError` — never
  a bare `except`.
- **Cancel the whole process group, not just the parent.** A ripped-from-under
  reader (`cdparanoia`) outlives a killed parent. Launch cancellable
  subprocesses with `start_new_session=True` and signal the group
  (`os.killpg`). See `drive_control.force_stop_drive()` and CLAUDE.md Critical
  Rule #3 for the scoped, user-approved force-stop exception and its `pkill`
  anchoring rules.

### 3.4 Parsers never raise (institutional rule)
Anything that parses external output uses **named-group regexes** (not column
indices — tool output shifts between minor versions), tolerates garbage, and
returns a best-effort dataclass instead of raising:

- Match on *labels*, not positions. See `deps/version.py`
  (`DEFAULT_VERSION_PATTERN`) and the rip-progress patterns in
  `workers/rip_worker.py` (`Reading track (?P<track>\d+) of (?P<total>\d+)`).
- Treat "couldn't parse" as a first-class outcome (return `None`/empty), not a
  crash — upstream output drifts.
- Add a fixture + test for every real-world output sample you encounter, and a
  `hypothesis` "never raises on arbitrary input" property test for every new
  parser (`tests/test_parsers_property.py`).

### 3.5 One dependency subsystem (Critical Rule #6)
All "is this tool present and the right version?" logic lives in `deps/`
(probe → three-tier resolve: auto-install → queued install → copyable search
string). Do **not** add ad-hoc `shutil.which` checks elsewhere. New deps are
registered in `deps/registry.py` (mark `optional=True` if absence shouldn't
nag).

### 3.6 MainWindow is composed from mixins
`MainWindow` was a 1707-line god-object; it's decomposed (2026-06-13) into
cohesive `*Mixin` classes it inherits, so each concern lives in its own
focused file while methods stay reachable as `window._x` (which the test
suite and Qt signal wiring depend on). Each mixin documents the `self.`
attributes it assumes `MainWindow.__init__` has set. **This table is the
canonical ownership map** — KDD-19 records the *decision* and links here.

| Concern | Home |
|---------|------|
| Pure helpers (string-safety, fidelity verdict) | `main_window_helpers.py` |
| Self-update (check / download / install / restart) | `main_window_update.py` (`UpdateMixin`) |
| Rip lifecycle, force-stop, eject, cover art | `main_window_rip.py` (`RipMixin`) |
| Host setup / AppImage integration / uninstall | `main_window_provision.py` (`ProvisioningMixin`) |
| Drive setup / offset / access diagnosis | `main_window_drive.py` (`DriveMixin`) |
| Dependency check / resolve / summary (+ `_DialogQueuedResolver`) | `main_window_deps.py` (`DependencyMixin`) |
| Construction, menus, signal wiring, MusicBrainz slots, settings | `main_window.py` (the ~460-line assembler) |

`MainWindow(QMainWindow, RipMixin, UpdateMixin, ProvisioningMixin, DriveMixin, DependencyMixin)`
— a 1707-line god-object reduced to a ~460-line assembler plus six focused
modules.

### 3.7 Error handling & logging
- **Catch specific exceptions**, never bare `except:`. A last-resort
  `except Exception` is acceptable *only* at a thread/GUI boundary where a
  crash would take down the app, and it must `log.exception(...)` and degrade
  gracefully (tagging must never crash the GUI).
- **Use the `logging` module, never `print`.** The user's log lives at
  `~/.local/share/whipper-gui/log.txt` — the first thing to ask for in a bug
  report (the Settings *debug logging* toggle raises it to verbose DEBUG). Log
  at the right level: `debug` for probe detail, `info` for lifecycle,
  `warning` for recoverable failures, `exception` for unexpected ones.
- **Surface the actionable line to the user; keep the full detail in the log**
  (e.g. the dependency-summary "Install failures" block shows the last error
  line and points at the log).

## 4. Extension points — how to add things

> The goal: a contributor who has never spoken to the author can add a
> capability by following one of these recipes, without touching unrelated
> code.

### Add a ripping backend (e.g. a future `XyzripImpl`)
1. Implement the `WhipperBackend` ABC in `adapters/xyzrip_backend.py`
   (`rip`, `disc_info`, `version`, optional `find_offset`/`analyze_drive`).
2. Add a parser in `parsers/` for its log + disc-info output (named-group
   regex, never-raise, + a property test). Map it onto the shared `RipLog` /
   `DiscInfo` dataclasses so the GUI verdict code is unchanged.
3. Add the choice to `Config.ripper_backend` and select it in `app.py`.
4. If it needs a package, add a wizard step in `deps/host_setup.py` and CLI
   parity in `setup-host.sh` (keep the two install stanzas in sync).
5. Gate any backend-specific Settings widgets in `settings_dialog.py`
   (`_apply_backend_capabilities`) — grey out, explain, never lose values.

### Add an output format (MP3, WAV, …)
Route the encoder through the dependency subsystem (no bespoke install code),
add the format to `Config`, and pass it through `RipParameters` → the backend
argv. FLAC-only is a v1 scope rule (Critical Rule #4), so this is a
deliberate, reviewed expansion.

### Add a dependency
Register it in `deps/registry.py` with its probe and install tiers. Mark it
`optional=True` if its absence shouldn't nag. Nothing else changes.

### Add a parser of external output
New module in `parsers/`, named-group regex, return a dataclass, never raise,
add a property test. If it feeds a verdict, extend `fidelity_summary` in
`main_window_helpers.py`.

### Add a metadata or art source
New adapter behind a small interface (mirror `MusicBrainzClient` /
`cover_art`). Query it on the host (Critical Rule #5: the GUI resolves the
release, never the ripper's interactive prompt).

## 5. Testing contract (the safety net that lets us refactor fearlessly)

> **The full strategy, taxonomy, and Definition of Done live in
> [`testing.md`](testing.md)** — authoritative. This is the quick reference.

- `pytest` from the repo root (no env vars — `pyproject.toml` sets
  `pythonpath = ["src"]`); the suite touches no real hardware, network, or
  container. CI enforces **branch coverage with a hard floor**
  (`--cov-fail-under`, ~90, ratchets up) on Python 3.11–3.13, plus `ruff`
  lint + format.
- **Institutional rules:** every shipped bug gets a regression test in the
  same change; every new external-output parser gets a never-raises property
  test.
- **Inject fakes through the adapters** (backend/MB/metaflac) so worker and
  window tests run deterministically and offline. GUI tests use the shared
  `qapp` fixture (`tests/conftest.py`) under `QT_QPA_PLATFORM=offscreen`.
- **Drive signals synchronously in tests.** Qt signals are callable without an
  event loop; with direct connections, slots fire immediately — assert on
  collected emissions. For threaded code, stash the thread on the object and
  `join()` it rather than sleeping. **Stub anything that would touch the
  network or a real subprocess** (the update downloader, the cover-art
  fetcher, `gio`/`kbuildsycoca`) — an unstubbed one can hang the suite.
- Keep tests fast and order-independent — a test that only fails after another
  ran is a real defect (it caught a Qt re-entrancy crash here).

### 5.1 When you move code between modules, move its monkeypatch targets too
`monkeypatch.setattr(some_module, "free_function", fake)` only affects callers
that resolve the name *through that module*. If a method moves to a new
module, patch it there — or patch the function's *source* module and call it
module-qualified (e.g. `offset_config.is_offset_configured(...)`) so one patch
point covers every caller. A patch that silently stops intercepting is how the
2026-06-13 `RipMixin` extraction briefly let a test start a real rip thread.
Patching an attribute *on a shared module object* (`drive_control.eject_drive`)
is unaffected by where the caller lives.

## 6. Packaging, building & releasing

We build a single-file AppImage with
[`python-appimage`](https://github.com/niess/python-appimage) (Critical Rule
#2 — do **not** reach for `appimage-builder` without asking). Build/CI test
procedure: [`appimage-testing.md`](appimage-testing.md); recipe details:
[`../build/python-appimage/README.md`](../build/python-appimage/README.md).

The recipe (`build/build_appimage.sh`, `build/python-appimage/`) encodes
several gotchas found the hard way:

- `python-appimage` installs `requirements.txt` **one line at a time from a
  temp dir**, so a `--find-links .` line fails → use the `PIP_FIND_LINKS` env
  var.
- Each `pip install` runs through a shell, so `<`/`>` version pins read as
  redirections → use `~=` pins.
- The entrypoint is globbed as `entrypoint.*`, so it **must** have an
  extension (`entrypoint.sh`).
- A space in the `.desktop` `Name=` breaks the unquoted `appimagetool` call →
  `Name=Whipper-GUI`.
- The bundled manylinux CPython has **no CA certificates**, so HTTPS
  (MusicBrainz) fails until `entrypoint.sh` points `SSL_CERT_FILE` /
  `SSL_CERT_DIR` at the host bundle.
- FUSE-less hosts (CI) need `APPIMAGE_EXTRACT_AND_RUN=1`; rate-limited
  base-image downloads need an authenticated `GITHUB_TOKEN` or a pre-staged
  base image.

**Releasing is tag-driven and automated** — don't hand-build or hand-upload.
The operational steps (bump `__version__`, roll the CHANGELOG, dispatch the
workflow) are owned by `CLAUDE.md` *CI / release*; the contract that shapes
the design:

- **Single-source the version** from `src/whipper_gui/__init__.py:__version__`
  (`pyproject.toml` reads it dynamically) — never hard-code it twice.
- `release.yml` builds the AppImage + `.sha256` (+ `.zsync`) and attaches them
  to a GitHub Release; `v0.*` tags publish as pre-releases.
- The wheel/sdist publish to PyPI via `publish-pypi.yml` using **Trusted
  Publishing (OIDC)** — no API token in the repo. Keep publish in a *separate*
  workflow so a PyPI misconfiguration can't block the AppImage release.
- Follow [SemVer](https://semver.org/) and
  [Keep a Changelog](https://keepachangelog.com/) (newest first, an
  `Unreleased` section on top).

## 7. Security & licensing hygiene

- **No `shell=True`; argument lists only** (§3.3) — the GUI passes
  user-entered metadata into subprocess argv and path templates.
- **Never write secrets to the log** or to committed files. The release
  pipeline uses OIDC Trusted Publishing so there's no token to leak.
- **Respect the Distrobox routing boundary** (Critical Rule #3): the GUI calls
  the host-exported `~/.local/bin/whipper`; it does not enter the container,
  except the one scoped, user-approved force-stop exception.
- **Licensing:** we are GPL-3.0-only. Before reusing third-party code, check
  compatibility — e.g. CTDB verify is built **clean-room** from the LGPL
  reference, *not* ported from the GPL-2.0-only `python-cuetoolsdb` (KDD-16).
  Protocols/algorithms are facts (not copyrightable expression); specific code
  is. When in doubt, reimplement from a spec and add an SPDX header.

## 8. Future improvements & directions

Concrete backlog lives in `TASKS.md`; this section is the *architectural*
horizon — the seams that exist so future contributors can take the program
places we haven't planned.

- **Backends as plugins.** The `WhipperBackend` ABC + `Config.ripper_backend`
  selector already make backends swappable. A small entry-point/registry could
  let third parties drop in a backend without editing `app.py`.
- **A real preferences framework.** `config.py` is a flat dataclass with
  manual schema migration; as options grow, a typed settings registry with
  per-key metadata (label, help, backend-applicability) would let the Settings
  dialog build itself instead of hand-wiring each widget.
- **CTDB repair** (KDD-14/16): the verify half is built and
  backend-independent; repair (wrapping the .NET `ctdb-cli`) is the headline
  EAC++ differentiator, parked on the bundle-vs-install question.
- **Library management:** ReplayGain, auto-move to a library tree, multi-disc
  queue, udev-driven auto-detect on disc insert — all sit above the rip
  pipeline and need no changes to the adapter layer.
- **Internationalization:** user-facing strings are currently inline; a future
  `tr()` pass would route them through Qt's translation system.
- **Packaging reach:** AppImage + pipx today; the adapter/host-wizard split
  keeps a Flatpak-with-host-access or other channel conceivable without
  touching the GUI (subject to Critical Rule #3).

When you add a capability the author never imagined: keep the layer direction
(§2), put external calls behind an adapter (§3.1), never block the GUI thread
(§3.2), and leave a test. That's the whole contract.

## References

External sources for the practices above:

- **Python & typing:** [PEP 8](https://peps.python.org/pep-0008/) ·
  [PEP 484 type hints](https://peps.python.org/pep-0484/) ·
  [PEP 257 docstrings](https://peps.python.org/pep-0257/)
- **Adapters:** [`abc`](https://docs.python.org/3/library/abc.html) ·
  dependency-inversion principle
- **Subprocess:** [`subprocess`](https://docs.python.org/3/library/subprocess.html) ·
  [Bandit B602 `shell=True`](https://bandit.readthedocs.io/en/latest/plugins/b602_subprocess_popen_with_shell_equals_true.html) ·
  [`shlex.quote`](https://docs.python.org/3/library/shlex.html#shlex.quote)
- **Parsing:** [`re`](https://docs.python.org/3/library/re.html)
- **Qt threading:**
  [QThread](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html) ·
  [Threads & QObjects](https://doc.qt.io/qt-6/threads-qobject.html) ·
  [Signals & Slots](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html) ·
  [Real Python — QThread](https://realpython.com/python-pyqt-qthread/)
- **Logging:** [Logging HOWTO](https://docs.python.org/3/howto/logging.html) ·
  [`logging`](https://docs.python.org/3/library/logging.html)
- **Testing:** [pytest](https://docs.pytest.org/)
- **Packaging & release:**
  [Python Packaging User Guide](https://packaging.python.org/) ·
  [`python-appimage`](https://github.com/niess/python-appimage) ·
  [PEP 621](https://peps.python.org/pep-0621/) ·
  [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/) ·
  [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish) ·
  [SemVer](https://semver.org/) · [Keep a Changelog](https://keepachangelog.com/)
- **Security & licensing:**
  [OWASP — OS command injection](https://owasp.org/www-community/attacks/Command_Injection) ·
  [SPDX licenses](https://spdx.org/licenses/) ·
  [GNU license compatibility](https://www.gnu.org/licenses/gpl-faq.html)
</content>
</invoke>
