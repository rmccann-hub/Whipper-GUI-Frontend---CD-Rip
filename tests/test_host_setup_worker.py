"""Tests for whipper_gui.workers.host_setup_worker.

The worker drives a step engine (HostSetup or HostTeardown) off the GUI
thread, re-emitting each StepResult and the final list. Tests use a fake
engine so nothing installs or shells out; signals are driven synchronously.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QApplication

from whipper_gui.deps.host_setup import StepResult, StepStatus
from whipper_gui.workers.host_setup_worker import HostSetupWorker


class _FakeEngine:
    """A StepEngine that emits canned steps and records how it was called."""

    def __init__(
        self, steps: list[StepResult] | None = None, raises: Exception | None = None
    ) -> None:
        self._steps = steps or []
        self._raises = raises
        self.cancelled_probe: Callable[[], bool] | None = None

    def run(
        self,
        progress: Callable[[StepResult], None] | None = None,
        dry_run: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[StepResult]:
        self.cancelled_probe = cancelled
        if self._raises is not None:
            raise self._raises
        for step in self._steps:
            if progress is not None:
                progress(step)
        return self._steps


def _step(step_id: str) -> StepResult:
    return StepResult(step_id=step_id, title=step_id, status=StepStatus.RAN)


def test_run_emits_each_step_then_the_full_list(qapp: QApplication) -> None:
    steps = [_step("distrobox"), _step("container"), _step("whipper")]
    worker = HostSetupWorker(_FakeEngine(steps))
    per_step: list[StepResult] = []
    final: list[list[StepResult]] = []
    worker.step.connect(per_step.append)
    worker.finished.connect(final.append)

    worker.run()

    assert [s.step_id for s in per_step] == ["distrobox", "container", "whipper"]
    assert len(final) == 1
    assert [s.step_id for s in final[0]] == ["distrobox", "container", "whipper"]


def test_cancel_is_observable_through_the_engine_probe(qapp: QApplication) -> None:
    engine = _FakeEngine([_step("distrobox")])
    worker = HostSetupWorker(engine)
    worker.run()

    # The engine received a cancelled() probe; it reflects the worker's flag.
    assert engine.cancelled_probe is not None
    assert engine.cancelled_probe() is False
    worker.cancel()
    assert worker._cancelled is True
    assert engine.cancelled_probe() is True


def test_run_never_crashes_and_finishes_empty_on_engine_error(
    qapp: QApplication,
) -> None:
    worker = HostSetupWorker(_FakeEngine(raises=RuntimeError("boom")))
    final: list[list[StepResult]] = []
    worker.finished.connect(final.append)

    worker.run()  # must not raise — a worker always finishes

    assert final == [[]]  # an empty result is still emitted so the thread ends
