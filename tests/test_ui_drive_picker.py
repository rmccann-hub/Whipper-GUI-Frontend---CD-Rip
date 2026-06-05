"""Tests for whipper_gui.ui.drive_picker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from whipper_gui.adapters.whipper_backend import (
    DiscInfo,
    RipHandle,
    WhipperBackend,
    WhipperError,
)
from whipper_gui.parsers.drive_list import DriveDescriptor
from whipper_gui.ui.drive_picker import DrivePicker

# --- Fake backend ---------------------------------------------------------


class _FakeBackend(WhipperBackend):
    """WhipperBackend stub that returns a configurable list (or raises)."""

    def __init__(self) -> None:
        self._drives: list[DriveDescriptor] = []
        self._raise: Exception | None = None
        self.list_calls: int = 0

    def set_drives(self, drives: list[DriveDescriptor]) -> None:
        self._drives = drives
        self._raise = None

    def raise_on_list(self, exc: Exception) -> None:
        self._raise = exc

    def list_drives(self) -> list[DriveDescriptor]:
        self.list_calls += 1
        if self._raise:
            raise self._raise
        return self._drives

    def disc_info(self, drive: str) -> DiscInfo:
        raise NotImplementedError

    def rip(
        self,
        drive: str,
        release_id: str,
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
    ) -> RipHandle:
        raise NotImplementedError

    def version(self) -> str:
        return "fake"


def _drive(device: str, vendor: str = "ACME", model: str = "X") -> DriveDescriptor:
    return DriveDescriptor(
        device=device,
        vendor=vendor,
        model=model,
        release="1.0",
    )


# --- Construction --------------------------------------------------------


def test_constructs_empty_until_refreshed(qapp: QApplication) -> None:
    backend = _FakeBackend()
    picker = DrivePicker(backend)

    # Constructor doesn't call refresh() — the caller decides when.
    assert backend.list_calls == 0
    assert picker.current_device() is None


# --- refresh() — happy paths ---------------------------------------------


def test_refresh_populates_combo(qapp: QApplication) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0"), _drive("/dev/sr1")])
    picker = DrivePicker(backend)

    picker.refresh()

    assert picker._combo.count() == 2
    assert picker.current_device() == "/dev/sr0"
    assert backend.list_calls == 1


def test_refresh_emits_drive_changed_for_initial_selection(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0")])
    picker = DrivePicker(backend)
    seen: list[str] = []
    picker.drive_changed.connect(seen.append)

    picker.refresh()

    assert seen == ["/dev/sr0"]


def test_eject_button_emits_selected_device(qapp: QApplication) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0"), _drive("/dev/sr1")])
    picker = DrivePicker(backend)
    picker.refresh()
    seen: list[str] = []
    picker.eject_requested.connect(seen.append)

    picker._eject_button.click()

    assert seen == ["/dev/sr0"]


def test_eject_button_emits_empty_when_no_drive(qapp: QApplication) -> None:
    """With only a placeholder shown, Eject targets the system default ("")."""
    backend = _FakeBackend()
    backend.set_drives([])
    picker = DrivePicker(backend)
    picker.refresh()  # "(no drives found)" placeholder
    seen: list[str] = []
    picker.eject_requested.connect(seen.append)

    picker._eject_button.click()

    assert seen == [""]


def test_refresh_label_includes_vendor_model_device(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0", vendor="PIONEER", model="BD-RW  BDR-209D")])
    picker = DrivePicker(backend)

    picker.refresh()

    label = picker._combo.itemText(0)
    assert "PIONEER" in label
    assert "BDR-209D" in label
    assert "/dev/sr0" in label


# --- refresh() — empty case ----------------------------------------------


def test_refresh_with_no_drives_shows_placeholder(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([])
    picker = DrivePicker(backend)
    seen: list[str] = []
    picker.drive_changed.connect(seen.append)

    picker.refresh()

    # One placeholder item, but its data is None — current_device returns None.
    assert picker._combo.count() == 1
    assert picker.current_device() is None
    # No drive_changed signal when there's no actual drive.
    assert seen == []


def test_refresh_with_no_drives_emits_drives_unavailable(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([])
    picker = DrivePicker(backend)
    fired: list[bool] = []
    picker.drives_unavailable.connect(lambda: fired.append(True))

    picker.refresh()

    assert fired == [True]


def test_refresh_with_drives_does_not_emit_unavailable(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives(
        [DriveDescriptor(device="/dev/sr0", vendor="V", model="M", release="1")]
    )
    picker = DrivePicker(backend)
    fired: list[bool] = []
    picker.drives_unavailable.connect(lambda: fired.append(True))

    picker.refresh()

    assert fired == []


# --- refresh() — error case ----------------------------------------------


def test_refresh_handles_whipper_error_without_crashing(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.raise_on_list(WhipperError("whipper missing"))
    picker = DrivePicker(backend)
    seen: list[str] = []
    picker.drive_changed.connect(seen.append)

    picker.refresh()

    # Error placeholder is visible; current_device stays None.
    assert "error" in picker._combo.itemText(0).lower()
    assert picker.current_device() is None
    assert seen == []


def test_refresh_handles_unexpected_exception_without_crashing(
    qapp: QApplication,
) -> None:
    # A non-WhipperError (e.g. a parser choking on unexpected whipper
    # output) must NOT propagate out of refresh() — that's what made the
    # whole window vanish at startup. It should degrade to a placeholder.
    backend = _FakeBackend()
    backend.raise_on_list(ValueError("malformed drive list"))
    picker = DrivePicker(backend)
    seen: list[str] = []
    picker.drive_changed.connect(seen.append)

    picker.refresh()  # must not raise

    label = picker._combo.itemText(0).lower()
    assert "error" in label
    assert "valueerror" in label  # the type is surfaced for diagnosis
    assert picker.current_device() is None
    assert seen == []


# --- Selection persistence ----------------------------------------------


def test_refresh_preserves_selection_if_device_still_present(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0"), _drive("/dev/sr1")])
    picker = DrivePicker(backend)
    picker.refresh()
    picker._combo.setCurrentIndex(1)  # select /dev/sr1
    assert picker.current_device() == "/dev/sr1"

    # Now refresh with the same set — selection should stick.
    seen: list[str] = []
    picker.drive_changed.connect(seen.append)
    picker.refresh()

    assert picker.current_device() == "/dev/sr1"
    assert seen == ["/dev/sr1"]


def test_refresh_falls_back_to_first_when_previous_device_gone(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0"), _drive("/dev/sr1")])
    picker = DrivePicker(backend)
    picker.refresh()
    picker._combo.setCurrentIndex(1)
    assert picker.current_device() == "/dev/sr1"

    # /dev/sr1 disappeared.
    backend.set_drives([_drive("/dev/sr0")])
    picker.refresh()

    assert picker.current_device() == "/dev/sr0"


# --- User-driven selection -----------------------------------------------


def test_user_selection_change_emits_drive_changed(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0"), _drive("/dev/sr1")])
    picker = DrivePicker(backend)
    picker.refresh()

    seen: list[str] = []
    picker.drive_changed.connect(seen.append)
    picker._combo.setCurrentIndex(1)

    assert seen == ["/dev/sr1"]


# --- Refresh button ------------------------------------------------------


def test_refresh_button_click_re_invokes_backend(
    qapp: QApplication,
) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0")])
    picker = DrivePicker(backend)
    picker.refresh()

    assert backend.list_calls == 1
    picker._refresh_button.click()
    assert backend.list_calls == 2


# --- current_drive() (used for the offset-by-model lookup) ----------------


def test_current_drive_returns_selected_descriptor(qapp: QApplication) -> None:
    backend = _FakeBackend()
    backend.set_drives([_drive("/dev/sr0", vendor="PIONEER", model="BD-RW  BDR-209D")])
    picker = DrivePicker(backend)
    picker.refresh()

    drive = picker.current_drive()
    assert drive is not None
    assert drive.vendor == "PIONEER"
    assert drive.model == "BD-RW  BDR-209D"
    assert drive.device == "/dev/sr0"


def test_current_drive_none_when_no_drives(qapp: QApplication) -> None:
    backend = _FakeBackend()
    backend.set_drives([])
    picker = DrivePicker(backend)
    picker.refresh()
    assert picker.current_drive() is None


def test_current_drive_none_on_backend_error(qapp: QApplication) -> None:
    backend = _FakeBackend()
    backend.raise_on_list(WhipperError("boom"))
    picker = DrivePicker(backend)
    picker.refresh()
    assert picker.current_drive() is None
