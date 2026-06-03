# Best practices & engineering patterns

Practical guidance for working in this codebase: the patterns we follow, **why**
we follow them, and the hard-won lessons behind them. This is a reference for
contributors — not a rulebook.

## How this relates to the other docs

- **[`../CLAUDE.md`](../CLAUDE.md) is authoritative.** Its *Code conventions*,
  *Critical rules*, and *Deviation policy* sections are the locked contract; if
  anything here ever conflicts with CLAUDE.md, CLAUDE.md wins. This document
  explains and expands on those rules — the *how* and *why* — and collects the
  patterns and gotchas discovered while building the project.
- **[`../PLANNING.md`](../PLANNING.md)** holds the architecture and the keyed
  design decisions (KDD-01 … KDD-16) referenced throughout.
- The **"Notes for future sessions"** log in CLAUDE.md is the running record of
  specific bugs and fixes; this doc distils the *general* lessons from it.

Each section below ends with **References** — authoritative external sources for
the underlying practice.

---

## 1. Python style & typing

We follow [PEP 8](https://peps.python.org/pep-0008/) with the project specifics
locked in CLAUDE.md *Code conventions*:

- **Type hints are mandatory** on every function signature, class attribute, and
  module-level constant ([PEP 484](https://peps.python.org/pep-0484/)). They are
  documentation the reader can trust and a linter can check.
- **Naming:** `snake_case` for functions/variables/modules, `PascalCase` for
  classes, `SCREAMING_SNAKE_CASE` for module-level constants.
- **Small, single-responsibility modules** — split when a file passes ~300
  lines. Splitting an oversized file is explicitly a "just do it" change.
- **Heavy comments that explain *intent*, not mechanics.** The maintainer has
  limited programming experience; a reader who knows Python but not Qt or
  whipper should still understand the file. Comment *why*, not *what the line
  does*.
- **No clever metaprogramming** — no behaviour-mutating decorators, dynamic
  class creation, monkey-patching, or "magic" imports.

**References:** [PEP 8](https://peps.python.org/pep-0008/) ·
[PEP 484 — type hints](https://peps.python.org/pep-0484/) ·
[PEP 257 — docstrings](https://peps.python.org/pep-0257/)

---

## 2. Adapter / API design (the unmaintained-dependency rule)

CLAUDE.md *Critical rule #1*: **every call into an unmaintained dependency goes
through a thin adapter module**, so a future replacement is a one-file swap
rather than a codebase-wide rewrite. Currently flagged: `whipper`,
`python-musicbrainzngs`, `python-appimage`.

The pattern (see [`../PLANNING.md`](../PLANNING.md) §5–§6):

- Define an **abstract base class** describing *what the GUI needs*, in our own
  vocabulary (e.g. `WhipperBackend`, `MusicBrainzClient`, and the planned
  `CTDBClient`). The GUI depends only on the ABC.
- Provide a **concrete implementation** that wraps the real tool/library
  (`src/whipper_gui/adapters/whipper_backend.py`, etc.).
- **Inject the adapter** at construction so tests pass a fake — no real binary,
  network, or drive in the test suite.
- Keep the ABC surface *minimal and capability-shaped*. Optional capabilities
  (e.g. `analyze_drive()`/`find_offset()`) default to `NotImplementedError` so
  fakes and alternative backends still construct.

Design the interface around the consumer's needs, not the wrapped library's
shape — that's what makes the dependency swappable.

**References:**
[`abc` — abstract base classes](https://docs.python.org/3/library/abc.html) ·
Dependency-inversion principle.

---

## 3. Invoking external programs (subprocess)

The GUI shells out constantly (whipper, flatpak, eject, pkill). Rules we hold to:

- **Never `shell=True`.** Pass an **argument list**, not a string — the module
  handles quoting/escaping and there is no shell to inject into. This is the
  single most important subprocess-security practice.
- **Resolve executables to absolute paths when the environment is hostile.** A
  GUI launched from a desktop icon (not a shell) inherits a *minimal* `PATH`
  that can miss `~/.local/bin` and even `/usr/bin`. `drive_control._resolve()`
  falls back through common absolute locations; do the same for any tool a
  desktop-launched process must reach.
- **Always set a `timeout`.** A wedged child must not hang the GUI forever
  (install commands cap at 300 s; force-stop probes at 20 s).
- **Capture output, then `log` it** — don't let it stream to a console the user
  can't see. Surface the *last* error line to the user and keep the full output
  in the log file.
- **Catch specific exceptions:** `FileNotFoundError`, `subprocess.TimeoutExpired`,
  `subprocess.SubprocessError`, `OSError` — never a bare `except`.
- **Cancel the whole process group, not just the parent.** A ripped-from-under
  reader (`cdparanoia`) outlives a killed parent. We launch cancellable
  subprocesses with `start_new_session=True` and signal the group
  (`os.killpg`). See `drive_control.force_stop_drive()` and CLAUDE.md
  *Critical Rule #3* for the (scoped, user-approved) force-stop exception and
  its hard-won `pkill` anchoring rules.

**References:**
[`subprocess`](https://docs.python.org/3/library/subprocess.html) ·
[Bandit B602 — `shell=True`](https://bandit.readthedocs.io/en/latest/plugins/b602_subprocess_popen_with_shell_equals_true.html) ·
[`shlex.quote`](https://docs.python.org/3/library/shlex.html#shlex.quote)
(only if a shell is truly unavoidable).

---

## 4. Parsing tool output robustly

CLAUDE.md *Code conventions*: parse subprocess output with **named-group
regexes, not column-index splits**, so a whipper minor-version output change
doesn't silently break parsing. See `src/whipper_gui/deps/version.py`
(`DEFAULT_VERSION_PATTERN`) and the rip-progress patterns in
`workers/rip_worker.py` (`Reading track (?P<track>\d+) of (?P<total>\d+)`).

- Match on *labels*, not positions.
- Treat "couldn't parse" as a first-class outcome (return `None`/empty), not a
  crash — upstream output drifts.
- Add a fixture + test for every real-world output sample you encounter.

**References:** [`re`](https://docs.python.org/3/library/re.html).

---

## 5. Qt / PySide6 threading

Any work that blocks (a rip, a MusicBrainz lookup, `whipper drive analyze`) runs
off the GUI thread. The patterns, all enforced by examples in
`src/whipper_gui/workers/`:

- **Worker-object + `moveToThread`, not `QThread` subclassing.** A `QThread`
  instance lives in the thread that *created* it, so slots on a `QThread`
  subclass run in the wrong thread. Put the work in a `QObject` worker and
  `moveToThread()` it. See `RipWorker`, `MbWorker`, `DriveSetupWorker`.
- **Never touch widgets from a worker thread.** Communicate results back via
  **signals** — cross-thread connections are delivered as *queued* connections
  and run in the receiver's (GUI) thread. The worker emits
  `progress`/`status`/`finished`; the GUI updates widgets in the connected
  slots.
- **Clean up deterministically:** connect `worker.finished → thread.quit`,
  `worker.finished → worker.deleteLater`, `thread.finished →
  thread.deleteLater`. **Join/stop threads before the window closes**
  (`closeEvent`) — destroying a `QThread` that's still running aborts the whole
  app. (This bit us: closing the drive-setup dialog mid-detection killed the
  process — fixed by cancelling + joining on `reject()`/`closeEvent`.)
- **Don't call `QApplication.processEvents()` from inside a slot that runs
  during a modal `exec()`.** It re-enters the event loop and pumps unrelated
  timers/threads — an order-dependent crash. To force an immediate repaint
  (e.g. show an "installing…" label before a blocking call), use
  `widget.repaint()` instead. (Lesson from the Pending-installs dialog.)
- Use thread-safe primitives for cancellation flags — a plain `bool` set from
  the GUI thread and read by the worker is fine under the GIL; anything richer
  needs care.

**References:**
[QThread (Qt for Python)](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html) ·
[Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html) ·
[Signals & Slots](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html) ·
[Real Python — QThread](https://realpython.com/python-pyqt-qthread/).

---

## 6. Error handling & logging

- **Catch specific exceptions**, never bare `except:`. A last-resort
  `except Exception` is acceptable *only* at a thread/GUI boundary where a crash
  would take down the app, and it must `log.exception(...)` and degrade
  gracefully (e.g. tagging must never crash the GUI).
- **Use the `logging` module, never `print`.** The user's log lives at
  `~/.local/share/whipper-gui/log.txt`; it's the first thing to ask for in a bug
  report. Log at the right level: `debug` for probe detail, `info` for
  lifecycle, `warning` for recoverable failures, `exception` for unexpected ones.
- **Surface the actionable line to the user; keep the full detail in the log.**
  (e.g. the dependency-summary "Install failures" block shows the last error
  line and points at the log.)

**References:**
[Logging HOWTO](https://docs.python.org/3/howto/logging.html) ·
[`logging`](https://docs.python.org/3/library/logging.html).

---

## 7. Testing

The suite runs with no env vars (`pyproject.toml` sets `pythonpath = ["src"]`)
and touches no real hardware, network, or container.

- **Inject fakes through the adapters.** Backend/MB/metaflac fakes let worker
  and window tests run deterministically and offline.
- **GUI tests** use the shared `qapp` fixture (`tests/conftest.py`) and run
  headless under `QT_QPA_PLATFORM=offscreen`.
- **Drive signals synchronously in tests.** Qt signals are callable without an
  event loop; with direct connections, connected slots fire immediately — assert
  on collected emissions. For threaded code, stash the thread on the object and
  `join()` it in the test rather than sleeping.
- **Regression-guard every real bug.** Each production fix in this project
  landed with a test that would have caught it (the AppImage recipe bugs,
  the declined-cascade, the force-stop anchoring, the processEvents crash).
- Keep tests fast and order-independent — a test that only fails after another
  test ran is a real defect (it caught a Qt re-entrancy crash here).

**References:** [pytest](https://docs.pytest.org/) ·
[Qt for Python test patterns](https://doc.qt.io/qtforpython-6/).

---

## 8. Packaging & the AppImage

We build a single-file AppImage with
[`python-appimage`](https://github.com/niess/python-appimage) (CLAUDE.md
*Critical rule #2* — do **not** reach for `appimage-builder` without asking).
The build recipe (`build/build_appimage.sh`, `build/python-appimage/`) encodes
several gotchas found the hard way — see
[`appimage-testing.md`](appimage-testing.md) and
[`../build/python-appimage/README.md`](../build/python-appimage/README.md):

- `python-appimage` installs `requirements.txt` **one line at a time from a temp
  dir**, so a `--find-links .` line fails → use the `PIP_FIND_LINKS` env var.
- Each `pip install` runs through a shell, so `<`/`>` version pins read as
  redirections → use `~=` pins.
- The entrypoint is globbed as `entrypoint.*`, so it **must** have an extension
  (`entrypoint.sh`).
- A space in the `.desktop` `Name=` breaks the unquoted `appimagetool` call →
  `Name=Whipper-GUI`.
- The bundled manylinux CPython has **no CA certificates**, so HTTPS
  (MusicBrainz) fails until `entrypoint.sh` points `SSL_CERT_FILE`/`SSL_CERT_DIR`
  at the host bundle.
- FUSE-less hosts (CI) need `APPIMAGE_EXTRACT_AND_RUN=1`; rate-limited base-image
  downloads need an authenticated `GITHUB_TOKEN` or a pre-staged base image.
- **Single-source the version** from `src/whipper_gui/__init__.py:__version__`
  (`pyproject.toml` reads it dynamically) — never hard-code it twice.

**References:**
[Python Packaging User Guide](https://packaging.python.org/) ·
[`python-appimage`](https://github.com/niess/python-appimage) ·
[PEP 621 — project metadata](https://peps.python.org/pep-0621/).

---

## 9. Releasing & publishing

Releases are **tag-driven and automated** — don't hand-build or hand-upload:

- Bump `version` in `src/whipper_gui/__init__.py`, add a `CHANGELOG.md` entry,
  then `git tag vX.Y.Z && git push origin vX.Y.Z`. `release.yml` builds the
  AppImage + `.sha256` and attaches them to a GitHub Release; `v0.*` tags
  publish as pre-releases.
- The wheel/sdist publish to PyPI via `publish-pypi.yml` using **Trusted
  Publishing (OIDC)** — no API token is stored in the repo. Keep publish in a
  *separate* workflow so a PyPI misconfiguration can't block the AppImage
  release.
- Follow [Semantic Versioning](https://semver.org/); keep
  [Keep a Changelog](https://keepachangelog.com/) order (newest first, an
  `Unreleased` section at the top).

**References:**
[PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/) ·
[`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish) ·
[SemVer](https://semver.org/) · [Keep a Changelog](https://keepachangelog.com/).

---

## 10. Security & licensing hygiene

- **No `shell=True`; argument lists only** (see §3) — the GUI passes
  user-entered metadata (album/track names) into subprocess argv and path
  templates, so injection-safety matters.
- **Never write secrets to the log** or to committed files. The release pipeline
  deliberately uses OIDC Trusted Publishing so there's no token to leak.
- **Respect the Distrobox routing boundary** (CLAUDE.md *Critical rule #3*): the
  GUI calls the host-exported `~/.local/bin/whipper`; it does not enter the
  container, except the one scoped, user-approved force-stop exception.
- **Licensing:** we are GPL-3.0-only. Before reusing third-party code, check
  compatibility — e.g. CTDB verify is built **clean-room** from the LGPL
  reference, *not* ported from the GPL-2.0-only `python-cuetoolsdb` (KDD-16).
  Protocols/algorithms are facts (not copyrightable expression); specific code
  is. When in doubt, reimplement from a spec and add an SPDX header.

**References:**
[OWASP — OS command injection](https://owasp.org/www-community/attacks/Command_Injection) ·
[SPDX license identifiers](https://spdx.org/licenses/) ·
[GNU license compatibility](https://www.gnu.org/licenses/gpl-faq.html).

---

## 11. Documentation practices

- **Keep the canonical source single.** Each fact lives in one place and others
  link to it: CLAUDE.md = rules; PLANNING.md = architecture/KDDs; TASKS.md =
  the checklist; README.md = the user-facing guide; this doc = patterns.
- **Log decisions and gotchas as you go** in CLAUDE.md *Notes for future
  sessions* — dated, specific, with the *why*. That log is where most of this
  document came from.
- **Cross-link, don't copy.** Reference a KDD or a sibling doc by link rather
  than restating it; restated facts drift out of sync.
- Update `TASKS.md` status markers (`[ ]` → `[~]` → `[x]`) and `CHANGELOG.md`
  as work lands.
