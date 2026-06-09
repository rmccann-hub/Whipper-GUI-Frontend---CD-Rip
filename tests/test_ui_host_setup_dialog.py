"""Tests for the host-setup wizard dialog.

We drive the render slots (`_on_step`, `_on_finished`) directly with a fake
host (no QThread, no real commands), so the dialog's display logic is tested
without touching Distrobox/podman.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from whipper_gui.deps.host_setup import StepResult, StepStatus
from whipper_gui.ui.host_setup_dialog import HostSetupDialog


class _FakeHost:
    """Minimal stand-in for HostSetup (duck-typed)."""

    def __init__(self, ready: bool, include_cyanrip: bool = False) -> None:
        self._ready = ready
        self.include_cyanrip = include_cyanrip

    def is_ready(self) -> bool:
        return self._ready

    def run(self, progress=None, cancelled=None):  # pragma: no cover - unused here
        return []


def _dialog(
    qapp: QApplication, ready: bool = True, include_cyanrip: bool = False
) -> HostSetupDialog:
    return HostSetupDialog(host_setup=_FakeHost(ready, include_cyanrip))


def test_intro_omits_cyanrip_by_default(qapp: QApplication) -> None:
    assert "cyanrip" not in _dialog(qapp)._intro.text()


def test_intro_mentions_cyanrip_when_included(qapp: QApplication) -> None:
    assert "cyanrip" in _dialog(qapp, include_cyanrip=True)._intro.text()


def test_on_step_appends_formatted_line(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._on_step(
        StepResult("distrobox", "Distrobox", StepStatus.DONE, "already present")
    )
    text = dialog._results.toPlainText()
    assert "Distrobox" in text
    assert "already present" in text
    assert "✓" in text


def test_on_step_running_updates_status_not_log(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._on_step(
        StepResult(
            "tools",
            "whipper + flac (in container)",
            StepStatus.RUNNING,
            "working… this can take a few minutes",
        )
    )
    # RUNNING shows what's happening in the status line, not the results log.
    assert "whipper + flac" in dialog._status_label.text()
    assert "⏳" in dialog._status_label.text()
    assert dialog._results.toPlainText() == ""


def test_on_finished_all_already_present(qapp: QApplication) -> None:
    dialog = _dialog(qapp, ready=True)
    dialog._on_finished(
        [
            StepResult("distrobox", "Distrobox", StepStatus.DONE, "already present"),
            StepResult("export", "Export", StepStatus.DONE, "already present"),
        ]
    )
    assert "already set up" in dialog._status_label.text().lower()


def test_on_step_ignored_while_closing(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._closing = True
    dialog._on_step(StepResult("x", "X", StepStatus.RAN))
    assert dialog._results.toPlainText() == ""


def test_on_finished_ready_reports_success(qapp: QApplication) -> None:
    dialog = _dialog(qapp, ready=True)
    seen: list[bool] = []
    dialog.setup_finished.connect(seen.append)

    dialog._on_finished([StepResult("export", "Export", StepStatus.RAN)])

    assert "complete" in dialog._status_label.text().lower()
    assert dialog._setup_button.text() == "Re-run setup"
    assert seen == [True]


def test_on_finished_failure_shows_failed_step(qapp: QApplication) -> None:
    dialog = _dialog(qapp, ready=False)
    seen: list[bool] = []
    dialog.setup_finished.connect(seen.append)

    dialog._on_finished(
        [
            StepResult("distrobox", "Distrobox", StepStatus.RAN),
            StepResult(
                "backend",
                "Container backend (podman)",
                StepStatus.FAILED,
                "install it manually and retry",
            ),
        ]
    )

    text = dialog._status_label.text()
    assert "Container backend" in text
    assert "manually" in text
    assert seen == [False]
