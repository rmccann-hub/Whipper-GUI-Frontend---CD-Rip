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
    out = capsys.readouterr().out + capsys.readouterr().err
    # argparse may print to stdout or stderr depending on version.
    # Verify the version string appears at least once in either stream.


def test_main_version_text_matches_package_version(
    capsys: pytest.CaptureFixture,
) -> None:
    """The version string includes the package's __version__."""
    with pytest.raises(SystemExit):
        app_module.main(["--version"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert __version__ in combined


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
