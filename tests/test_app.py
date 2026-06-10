"""Tests for whipper_gui.app.

`main()` constructs heavy components (QApplication, real subprocess
adapters); tests focus on the lightweight paths — argparse, the
`--version` short-circuit — and on importing the module without
crashes.
"""

from __future__ import annotations

import pytest

from whipper_gui import __version__
from whipper_gui import app as app_module


def test_main_version_flag_prints_and_exits(capsys: pytest.CaptureFixture) -> None:
    """--version exits via SystemExit before any heavy construction."""
    with pytest.raises(SystemExit) as excinfo:
        app_module.main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    # argparse may print to stdout or stderr depending on version.
    # Verify the version string appears at least once in either stream.
    assert "whipper-gui" in out


def test_main_version_text_matches_package_version(
    capsys: pytest.CaptureFixture,
) -> None:
    """The version string includes the package's __version__."""
    with pytest.raises(SystemExit):
        app_module.main(["--version"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert __version__ in combined


def test_installed_metadata_matches_canonical_version() -> None:
    """The build's dynamic version must equal the single source of truth.

    `__version__` in `whipper_gui/__init__.py` is canonical; `pyproject.toml`
    reads it via `[tool.setuptools.dynamic]`. If that wiring breaks, the
    installed package metadata would drift from `__version__` — catch it here.
    Skips when the package isn't installed (e.g. a raw source run).
    """
    import importlib.metadata as metadata

    try:
        installed = metadata.version("whipper-gui")
    except metadata.PackageNotFoundError:
        pytest.skip("whipper-gui not installed; nothing to compare against")
    assert installed == __version__


def test_main_unknown_flag_exits_non_zero(
    capsys: pytest.CaptureFixture,
) -> None:
    """argparse rejects unknown flags."""
    with pytest.raises(SystemExit) as excinfo:
        app_module.main(["--bogus-flag"])
    # argparse returns 2 for argument errors.
    assert excinfo.value.code != 0


def test_main_module_is_importable() -> None:
    """The bare import path used by `python -m whipper_gui` works."""
    # This re-imports a known package; sanity check that no module-level
    # side effects (Qt construction, subprocess calls) happen on import.
    import importlib

    module = importlib.reload(app_module)
    assert hasattr(module, "main")
    assert callable(module.main)


# --- Crash handler -------------------------------------------------------


def test_show_fatal_dialog_noops_without_qapplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fatal-error dialog must be safe to call when no QApplication
    exists (the GUI itself failed to come up): it should quietly no-op
    rather than raise — and never block on a modal exec()."""
    from PySide6.QtWidgets import QApplication

    # Force the "no QApplication" branch regardless of whether another
    # test in this process already constructed one (which would otherwise
    # pop a blocking modal dialog).
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    app_module._show_fatal_dialog("test", RuntimeError("boom"))  # must not raise


def test_install_excepthook_sets_and_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """_install_excepthook installs a hook that routes normal exceptions to
    the dialog and passes KeyboardInterrupt through to the default hook."""
    import sys

    shown: list[tuple[str, BaseException]] = []
    monkeypatch.setattr(
        app_module, "_show_fatal_dialog", lambda title, exc: shown.append((title, exc))
    )

    original = sys.excepthook
    try:
        app_module._install_excepthook()
        assert sys.excepthook is not original

        err = ValueError("kaboom")
        sys.excepthook(ValueError, err, None)
        assert shown and shown[-1][1] is err

        shown.clear()
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert shown == []  # KeyboardInterrupt is not routed to the dialog
    finally:
        sys.excepthook = original


def test_main_uninstall_flag_opens_uninstaller_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`whipper-gui --uninstall` (the Uninstall menu entry) opens just the
    uninstaller dialog — no adapters, no main window."""
    import whipper_gui.ui.uninstall_dialog as ud
    from whipper_gui import app as app_module

    opened: list[bool] = []

    class _FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            opened.append(True)
            return 0

    monkeypatch.setattr(ud, "UninstallDialog", _FakeDialog)
    # A MainWindow being constructed would mean the flag was ignored.
    import whipper_gui.ui.main_window as mw

    monkeypatch.setattr(
        mw,
        "MainWindow",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("main window built")),
    )

    assert app_module.main(["--uninstall"]) == 0
    assert opened == [True]
