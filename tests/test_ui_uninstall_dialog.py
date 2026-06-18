"""Tests for the in-app Uninstaller dialog.

Render slots are driven directly with fake results (no QThread, nothing
removed); the run flow is tested with a fake teardown factory and a
monkeypatched confirm prompt.
"""

from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from whipper_gui.deps.host_setup import StepResult, StepStatus
from whipper_gui.ui.uninstall_dialog import UninstallDialog


def _dialog(qapp: QApplication, build=None) -> UninstallDialog:
    return UninstallDialog(build_teardown=build or (lambda *a: None))


def test_checkboxes_default_to_remove_everything(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    assert dialog._container_check.isChecked() is True
    assert dialog._whipper_conf_check.isChecked() is True


def test_confirm_cancel_runs_nothing(qapp: QApplication, monkeypatch) -> None:
    built: list = []
    dialog = _dialog(qapp, build=lambda *a: built.append(a))
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    dialog._on_uninstall_clicked()
    assert built == []  # declined → no teardown was even constructed
    assert dialog._thread is None


def test_confirm_yes_builds_teardown_from_checkboxes(
    qapp: QApplication, monkeypatch
) -> None:
    """The ticked boxes flow into the engine; the worker thread starts."""

    class _InstantEngine:
        def __init__(self, args):
            self.args = args

        def run(self, progress=None, dry_run=False, cancelled=None):
            return [StepResult("shortcuts", "Shortcuts", StepStatus.DONE)]

    built: list = []

    def build(remove_container: bool, remove_whipper_config: bool):
        built.append((remove_container, remove_whipper_config))
        return _InstantEngine(built[-1])

    dialog = _dialog(qapp, build=build)
    dialog._whipper_conf_check.setChecked(False)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    dialog._on_uninstall_clicked()
    # `built` is appended synchronously before the thread starts; join the
    # worker via the dialog's own teardown (no event pumping — processing
    # global events here would fire stale deferred events from other tests).
    dialog._stop()

    assert built == [(True, False)]


def test_on_finished_success_locks_ui_and_signals(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._uninstall_button.setEnabled(False)  # as the run flow leaves it
    seen: list[bool] = []
    dialog.uninstall_finished.connect(seen.append)

    dialog._on_finished(
        [
            StepResult("shortcuts", "Shortcuts", StepStatus.RAN, "removed …"),
            StepResult("app_data", "Settings + logs", StepStatus.RAN),
        ]
    )

    assert "✓" in dialog._status_label.text()
    assert "Close this app" in dialog._status_label.text()
    # No "try again" affordance after success — the app should be closed.
    assert dialog._uninstall_button.isEnabled() is False
    assert seen == [True]


def test_on_finished_failure_reenables_and_reports(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._uninstall_button.setEnabled(False)
    seen: list[bool] = []
    dialog.uninstall_finished.connect(seen.append)

    dialog._on_finished(
        [
            StepResult("shortcuts", "Shortcuts", StepStatus.RAN),
            StepResult(
                "container",
                "'ripping' container",
                StepStatus.FAILED,
                "container is in use",
            ),
            StepResult("app_data", "Settings + logs", StepStatus.CANCELLED),
        ]
    )

    assert "container is in use" in dialog._status_label.text()
    assert dialog._uninstall_button.isEnabled() is True  # retry possible
    assert seen == [False]


def test_on_step_appends_result_lines(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._on_step(StepResult("exports", "Exports", StepStatus.RAN, "removed whipper"))
    assert "removed whipper" in dialog._results.toPlainText()
    # RUNNING goes to the status line, not the log.
    dialog._on_step(StepResult("container", "Container", StepStatus.RUNNING))
    assert "Container" in dialog._status_label.text()
    assert "Container" not in dialog._results.toPlainText()


def test_on_step_without_detail_has_no_dash(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._on_step(StepResult("shortcuts", "Shortcuts", StepStatus.RAN))
    line = dialog._results.toPlainText()
    assert "Shortcuts" in line
    assert "—" not in line  # no detail → no " — …" suffix


def test_uninstall_click_ignored_while_already_running(
    qapp: QApplication, monkeypatch
) -> None:
    built: list = []
    dialog = _dialog(qapp, build=lambda *a: built.append(a))
    # Pretend a run is already in flight.
    dialog._thread = QThread(dialog)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    dialog._on_uninstall_clicked()  # must early-return, not start a second run

    assert built == []  # no second teardown built
    dialog._thread = None  # avoid touching the sentinel thread at teardown


def test_step_and_finished_ignored_while_closing(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._closing = True
    seen: list[bool] = []
    dialog.uninstall_finished.connect(seen.append)

    dialog._on_step(StepResult("exports", "Exports", StepStatus.RAN, "x"))
    dialog._on_finished([StepResult("shortcuts", "Shortcuts", StepStatus.RAN)])

    # A closing dialog updates nothing and emits nothing (the window is going
    # away; touching destroyed widgets would crash).
    assert dialog._results.toPlainText() == ""
    assert seen == []


def test_on_finished_incomplete_without_a_failed_step(qapp: QApplication) -> None:
    # No FAILED step, but not all ok (a CANCELLED step) → the generic
    # "did not complete" message, and the UI re-enables for a retry.
    dialog = _dialog(qapp)
    dialog._uninstall_button.setEnabled(False)
    seen: list[bool] = []
    dialog.uninstall_finished.connect(seen.append)

    dialog._on_finished(
        [
            StepResult("shortcuts", "Shortcuts", StepStatus.RAN),
            StepResult("app_data", "Settings + logs", StepStatus.CANCELLED),
        ]
    )

    assert dialog._status_label.text() == "Uninstall did not complete."
    assert dialog._uninstall_button.isEnabled() is True
    assert seen == [False]


def test_stop_is_a_no_op_when_nothing_is_running(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog._stop()  # thread is None → returns without error
    assert dialog._thread is None


def test_stop_quits_a_started_threadless_worker(qapp: QApplication) -> None:
    # thread present but no worker (e.g. teardown raced): _stop still quits and
    # clears the thread without trying to cancel a missing worker.
    dialog = _dialog(qapp)
    dialog._thread = QThread(dialog)  # never started → wait() returns at once
    dialog._worker = None

    dialog._stop()

    assert dialog._thread is None
    assert dialog._worker is None


def test_reject_marks_closing_and_stops(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog.reject()
    assert dialog._closing is True
    assert dialog._thread is None


def test_close_event_marks_closing_and_stops(qapp: QApplication) -> None:
    dialog = _dialog(qapp)
    dialog.close()  # delivers a real QCloseEvent → closeEvent
    assert dialog._closing is True
    assert dialog._thread is None
