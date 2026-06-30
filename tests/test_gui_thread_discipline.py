"""Architectural fitness test: the GUI thread is never blocked.

Codifies CLAUDE.md's **"never block the GUI thread"** rule as an executable
guard so the freeze bug class can't creep back (the 2026-06-13 in-app-update
freeze, plus the latent `gio`/`kbuildsycoca`/launch-probe freezes). No module
under ``src/platterpus/ui/`` may make a *synchronous blocking* call —
``subprocess.run``/``check_output``/``check_call``/``call``, any ``urlopen``,
or ``time.sleep``. Blocking work belongs on a ``QObject`` worker on a
``QThread`` (need the result) or a fire-and-forget ``subprocess.Popen(...,
start_new_session=True)`` (don't).

Why AST, not grep: parsing means a docstring, comment, or string that merely
*mentions* ``subprocess.run`` doesn't trip the guard — only a real call does.

Deliberately NOT forbidden: ``QThread.wait()`` / ``thread.join()``. The UI
uses those only at *teardown* (``closeEvent`` / dialog ``reject``) to join a
worker before destroying it — required (destroying a running ``QThread``
aborts the app) and bounded. Blocking during normal operation is the bug;
joining on the way out is correct.

This is a "fitness function" test — a small, fast check that protects an
architectural property instead of a single behaviour. Portable pattern: any
GUI project can drop this in to keep its event loop responsive.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_UI_DIR = Path(__file__).resolve().parents[1] / "src" / "platterpus" / "ui"

# Module-qualified calls that block the calling thread until they return.
_FORBIDDEN_QUALIFIED: set[tuple[str, str]] = {
    ("subprocess", "run"),
    ("subprocess", "check_output"),
    ("subprocess", "check_call"),
    ("subprocess", "call"),
    ("os", "system"),
    ("os", "waitpid"),
    ("time", "sleep"),
}
# Whole modules that have no business being called on the GUI thread under any
# spelling — every call on them is synchronous network/blocking I/O.
_FORBIDDEN_RECEIVERS: set[str] = {"requests"}
# Calls by attribute name regardless of receiver — network I/O has no business
# on the GUI thread under any spelling (urllib.request.urlopen, request.urlopen).
_FORBIDDEN_ATTRS: set[str] = {"urlopen"}


def _ui_modules() -> list[Path]:
    return sorted(p for p in _UI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _import_aliases(tree: ast.AST) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Resolve a module's imports so aliased blockers can't slip the guard.

    Returns ``(module_alias, name_import)``:
      * ``module_alias`` maps a local name → canonical top-level module, covering
        ``import subprocess`` and ``import subprocess as sp`` (and ``import
        time as _time``). The canonical name is the FIRST dotted component, so
        ``import urllib.request`` maps ``urllib`` → ``urllib``.
      * ``name_import`` maps a bare local name → ``(module, attr)`` for
        ``from subprocess import run`` / ``from time import sleep as nap``, so a
        direct ``run(...)`` / ``nap(...)`` call resolves back to its origin.

    Without this the guard only caught the literal ``subprocess.run`` spelling —
    ``import subprocess as sp; sp.run(...)`` and ``from subprocess import run``
    both slipped through (the gap behind why blocking calls reached the GUI).
    """
    module_alias: dict[str, str] = {}
    name_import: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                module_alias[local] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            for alias in node.names:
                name_import[alias.asname or alias.name] = (top, alias.name)
    return module_alias, name_import


def _blocking_calls(path: Path) -> list[str]:
    """Return 'line:call' for each blocking call found in `path` (AST-based).

    Resolves import aliases first, so a blocker is caught however it's spelled —
    ``subprocess.run``, ``sp.run`` (aliased import), or a bare ``run`` brought in
    via ``from subprocess import run``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_alias, name_import = _import_aliases(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            attr = func.attr
            raw = func.value.id if isinstance(func.value, ast.Name) else "?"
            module = module_alias.get(raw, raw)  # resolve `sp` → `subprocess`
            if (
                (module, attr) in _FORBIDDEN_QUALIFIED
                or module in _FORBIDDEN_RECEIVERS
                or attr in _FORBIDDEN_ATTRS
            ):
                hits.append(f"line {node.lineno}: {module}.{attr}(...)")
        elif isinstance(func, ast.Name):
            # A bare call like `run(...)` / `sleep(...)` — blocking only if it was
            # `from <module> import <that-name>` for a forbidden (module, attr).
            origin = name_import.get(func.id)
            if origin is not None and (
                origin in _FORBIDDEN_QUALIFIED or origin[1] in _FORBIDDEN_ATTRS
            ):
                hits.append(f"line {node.lineno}: {origin[0]}.{origin[1]}(...)")
    return hits


@pytest.mark.parametrize("path", _ui_modules(), ids=lambda p: p.name)
def test_ui_module_makes_no_blocking_calls(path: Path) -> None:
    hits = _blocking_calls(path)
    assert not hits, (
        f"{path.name} makes a blocking call on the GUI thread "
        f"({'; '.join(hits)}). Move it to a QObject worker on a QThread, or "
        "fire-and-forget subprocess.Popen(..., start_new_session=True). "
        "See CLAUDE.md 'never block the GUI thread' + docs/architecture.md §3.2."
    )


def test_guard_actually_detects_a_blocking_call(tmp_path: Path) -> None:
    """Meta-test: prove the guard isn't a no-op — it must flag a planted call
    and must ignore a mere mention in a string/comment."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "import subprocess, time, urllib.request, os\n"
        "def bad():\n"
        "    subprocess.run(['x'])\n"
        "    time.sleep(1)\n"
        "    urllib.request.urlopen('http://x')\n"
        "    os.system('x')\n"
    )
    assert len(_blocking_calls(offender)) == 4

    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""We must not call subprocess.run here."""\n'
        "import subprocess\n"
        "def ok():\n"
        "    subprocess.Popen(['x'], start_new_session=True)  # fire-and-forget\n"
        "    ', '.join(['a', 'b'])  # str.join is not thread.join\n"
        "    thread.wait(2000)  # QThread teardown join is allowed\n"
    )
    assert _blocking_calls(innocent) == []


def test_guard_resolves_import_aliases(tmp_path: Path) -> None:
    """The blind spot that let blocking calls through before: a blocker reached
    through an aliased import (`import subprocess as sp`) or a bare name brought
    in via `from ... import` must be caught, not just the literal `module.attr`
    spelling."""
    aliased = tmp_path / "aliased.py"
    aliased.write_text(
        "import subprocess as sp\n"
        "import time as _t\n"
        "from subprocess import run\n"
        "from time import sleep as nap\n"
        "import requests\n"
        "def bad():\n"
        "    sp.run(['x'])\n"  # aliased module
        "    run(['x'])\n"  # from-import bare name
        "    nap(1)\n"  # from-import aliased name
        "    requests.get('http://x')\n"  # whole-module-forbidden receiver
        "    _t.monotonic()\n"  # NOT blocking — only time.sleep is
    )
    hits = _blocking_calls(aliased)
    # 4 blockers; _t.monotonic() must NOT be flagged.
    assert len(hits) == 4, hits
    assert not any("monotonic" in h for h in hits)
