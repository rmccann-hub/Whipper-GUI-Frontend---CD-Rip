"""Tests for whipper_gui.workers.drive_setup_worker."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.whipper_backend import WhipperBackend, WhipperError
from whipper_gui.workers import drive_setup_worker as dsw
from whipper_gui.workers.drive_setup_worker import (
    DriveSetupResult,
    DriveSetupWorker,
)


class _FakeBackend(WhipperBackend):
    """Implements just the calibration methods the worker calls."""

    def __init__(
        self,
        offset: int | None = 667,
        cache: bool | None = True,
        offset_exc: Exception | None = None,
        analyze_exc: Exception | None = None,
    ) -> None:
        self._offset = offset
        self._cache = cache
        self._offset_exc = offset_exc
        self._analyze_exc = analyze_exc
        self.devices: list[str] = []

    # Abstract members we don't exercise here:
    def list_drives(self):  # type: ignore[override]
        return []

    def disc_info(self, drive):  # type: ignore[override]
        raise NotImplementedError

    def rip(self, *a, **kw):  # type: ignore[override]
        raise NotImplementedError

    def version(self) -> str:  # type: ignore[override]
        return "fake"

    def analyze_drive(self, device: str):  # type: ignore[override]
        self.devices.append(device)
        if self._analyze_exc:
            raise self._analyze_exc
        return self._cache

    def find_offset(self, device: str) -> int:  # type: ignore[override]
        if self._offset_exc:
            raise self._offset_exc
        assert self._offset is not None
        return self._offset


@pytest.fixture(autouse=True)
def _no_real_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real ~/.config/whipper/whipper.conf in tests."""
    monkeypatch.setattr(
        dsw, "back_up_whipper_config", lambda *a, **kw: Path("/x/whipper.conf.bak")
    )


def _run(worker: DriveSetupWorker) -> DriveSetupResult:
    captured: list[DriveSetupResult] = []
    worker.finished.connect(captured.append)
    worker.run()
    assert len(captured) == 1
    return captured[0]


def test_worker_reports_offset_and_cache(qapp: QApplication) -> None:
    backend = _FakeBackend(offset=667, cache=True)
    result = _run(DriveSetupWorker(backend, "/dev/sr0"))

    assert result.offset == 667
    assert result.can_defeat_cache is True
    assert result.offset_error is None
    assert result.ok is True
    assert backend.devices == ["/dev/sr0"]  # device forwarded
    assert result.backup_path == Path("/x/whipper.conf.bak")


def test_worker_records_offset_failure_but_keeps_cache(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend(cache=True, offset_exc=WhipperError("not in AccurateRip"))
    result = _run(DriveSetupWorker(backend, "/dev/sr0"))

    assert result.offset is None
    assert result.ok is False
    assert "AccurateRip" in (result.offset_error or "")
    assert result.can_defeat_cache is True  # analyze still succeeded


def test_worker_handles_unsupported_backend(qapp: QApplication) -> None:
    backend = _FakeBackend(
        offset_exc=NotImplementedError(), analyze_exc=NotImplementedError()
    )
    result = _run(DriveSetupWorker(backend, ""))

    assert result.offset is None
    assert result.can_defeat_cache is None
    assert result.offset_error and result.analyze_error


def test_cancel_sets_flag_and_calls_backend(qapp: QApplication) -> None:
    cancels: list[bool] = []
    backend = _FakeBackend()
    backend.cancel_setup = lambda: cancels.append(True)  # type: ignore[method-assign]
    worker = DriveSetupWorker(backend, "/dev/sr0")

    worker.cancel()

    assert worker._cancelled is True
    assert cancels == [True]


def test_run_short_circuits_when_cancelled_before_start(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    worker = DriveSetupWorker(backend, "/dev/sr0")
    worker._cancelled = True

    result = _run(worker)

    # No probing happened; an empty result is emitted so the thread ends.
    assert result.offset is None
    assert backend.devices == []
