"""Architectural fitness test: the GUI thread is never blocked.

Codifies CLAUDE.md's **"never block the GUI thread"** rule as an executable
guard so the freeze bug class can't creep back (the 2026-06-13 in-app-update
freeze, plus the latent `gio`/`kbuildsycoca`/launch-probe freezes). No module
under ``src/whipper_gui/ui/`` may make a *synchronous blocking* call —
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

_UI_DIR = Path(__file__).resolve().parents[1] / "src" / "whipper_gui" / "ui"

# Module-qualified calls that block the calling thread until they return.
_FORBIDDEN_QUALIFIED: set[tuple[str, str]] = {
    ("subprocess", "run"),
    ("subprocess", "check_output"),
    ("subprocess", "check_call"),
    ("subprocess", "call"),
    ("time", "sleep"),
}
# Calls by attribute name regardless of receiver — network I/O has no business
# on the GUI thread under any spelling (urllib.request.urlopen, request.urlopen).
_FORBIDDEN_ATTRS: set[str] = {"urlopen"}


def _ui_modules() -> list[Path]:
    return sorted(p for p in _UI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _blocking_calls(path: Path) -> list[str]:
    """Return 'line:call' for each blocking call found in `path` (AST-based)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        receiver = node.func.value.id if isinstance(node.func.value, ast.Name) else "?"
        if (receiver, attr) in _FORBIDDEN_QUALIFIED or attr in _FORBIDDEN_ATTRS:
            hits.append(f"line {node.lineno}: {receiver}.{attr}(...)")
    return hits


@pytest.mark.parametrize("path", _ui_modules(), ids=lambda p: p.name)
def test_ui_module_makes_no_blocking_calls(path: Path) -> None:
    hits = _blocking_calls(path)
    assert not hits, (
        f"{path.name} makes a blocking call on the GUI thread "
        f"({'; '.join(hits)}). Move it to a QObject worker on a QThread, or "
        "fire-and-forget subprocess.Popen(..., start_new_session=True). "
        "See CLAUDE.md 'never block the GUI thread' + docs/best-practices.md §5."
    )


def test_guard_actually_detects_a_blocking_call(tmp_path: Path) -> None:
    """Meta-test: prove the guard isn't a no-op — it must flag a planted call
    and must ignore a mere mention in a string/comment."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "import subprocess, time, urllib.request\n"
        "def bad():\n"
        "    subprocess.run(['x'])\n"
        "    time.sleep(1)\n"
        "    urllib.request.urlopen('http://x')\n"
    )
    assert len(_blocking_calls(offender)) == 3

    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        '"""We must not call subprocess.run here."""\n'
        "import subprocess\n"
        "def ok():\n"
        "    subprocess.Popen(['x'], start_new_session=True)  # fire-and-forget\n"
    )
    assert _blocking_calls(innocent) == []
