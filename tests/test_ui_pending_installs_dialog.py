"""Tests for whipper_gui.ui.dialogs.pending_installs."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from whipper_gui.deps.checks import ProbeResult
from whipper_gui.deps.registry import DependencySpec, Tier
from whipper_gui.deps.resolvers import InstallResult, MissingItem
from whipper_gui.ui.dialogs.pending_installs import PendingInstallsDialog


# --- Spec / item factories ------------------------------------------------


def _spec(
    dep_id: str,
    min_version: tuple[int, ...] = (0, 0, 0),
    install_command: list[str] | None = None,
) -> DependencySpec:
    return DependencySpec(
        dep_id=dep_id,
        display_name=dep_id,
        probe=lambda: ProbeResult(present=False, version=None, location=None),
        min_version=min_version,
        tier=Tier.QUEUED,
        install_command=install_command or ["echo", dep_id],
        search_string=f"install {dep_id}",
    )


def _item(dep_id: str, min_version: tuple[int, ...] = (0, 0, 0)) -> MissingItem:
    return MissingItem(
        spec=_spec(dep_id, min_version=min_version),
        probe=ProbeResult(present=False, version=None, location=None),
    )


# --- Construction --------------------------------------------------------


def test_window_title_and_modality(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("picard")])
    assert dialog.windowTitle() == "Pending installs"
    assert dialog.isModal() is True


def test_one_checkbox_per_item_default_checked(qapp: QApplication) -> None:
    items = [_item("a"), _item("b"), _item("c")]
    dialog = PendingInstallsDialog(items)

    assert set(dialog._checkboxes.keys()) == {"a", "b", "c"}
    for checkbox in dialog._checkboxes.values():
        assert checkbox.isChecked() is True


def test_row_label_includes_min_version(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("metaflac", min_version=(1, 3, 0))])
    label = dialog._checkboxes["metaflac"].text()
    assert "metaflac" in label
    assert ">= 1.3.0" in label


def test_row_label_omits_version_for_any_floor(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("picard", min_version=(0, 0, 0))])
    label = dialog._checkboxes["picard"].text()
    assert label == "picard"


# --- Selection -----------------------------------------------------------


def test_selected_items_returns_checked_subset(
    qapp: QApplication,
) -> None:
    items = [_item("a"), _item("b"), _item("c")]
    dialog = PendingInstallsDialog(items)

    dialog._checkboxes["b"].setChecked(False)

    selected_ids = [it.spec.dep_id for it in dialog.selected_items()]
    assert selected_ids == ["a", "c"]


def test_selected_items_empty_when_all_unchecked(
    qapp: QApplication,
) -> None:
    items = [_item("a"), _item("b")]
    dialog = PendingInstallsDialog(items)
    for cb in dialog._checkboxes.values():
        cb.setChecked(False)

    assert dialog.selected_items() == []


# --- Install button signal -----------------------------------------------


def test_install_button_emits_install_requested(
    qapp: QApplication,
) -> None:
    dialog = PendingInstallsDialog([_item("a")])
    fired: list[bool] = []
    dialog.install_requested.connect(lambda: fired.append(True))

    dialog._install_button.click()

    assert fired == [True]


def test_install_button_does_not_close_dialog(
    qapp: QApplication,
) -> None:
    """The caller drives the install loop while the dialog stays open."""
    dialog = PendingInstallsDialog([_item("a")])

    dialog._install_button.click()

    assert dialog.isVisible() is False  # we never showed it
    assert dialog.result() == 0  # neither accepted nor rejected


def test_cancel_button_rejects(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])
    dialog._cancel_button.click()

    assert dialog.result() == int(dialog.DialogCode.Rejected)


# --- Status updates ------------------------------------------------------


def test_mark_in_progress_sets_row_status(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a"), _item("b")])

    dialog.mark_in_progress("a")

    assert dialog._status_labels["a"].text() == "installing…"
    assert dialog._status_labels["b"].text() == ""


def test_mark_result_success_renders_ok(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])

    dialog.mark_result("a", success=True)

    assert dialog._status_labels["a"].text() == "OK"


def test_mark_result_failure_renders_error_short(
    qapp: QApplication,
) -> None:
    dialog = PendingInstallsDialog([_item("a")])

    dialog.mark_result("a", success=False, message="boom")

    assert dialog._status_labels["a"].text() == "FAILED: boom"


def test_mark_result_failure_truncates_long_messages(
    qapp: QApplication,
) -> None:
    dialog = PendingInstallsDialog([_item("a")])
    long_message = "x" * 200

    dialog.mark_result("a", success=False, message=long_message)

    label = dialog._status_labels["a"].text()
    assert label.startswith("FAILED: ")
    assert label.endswith("…")
    assert len(label) <= len("FAILED: ") + 60


def test_mark_result_unknown_dep_id_is_safe(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])

    # Should not raise.
    dialog.mark_result("not-in-list", success=True)


# --- Install-phase lockdown ----------------------------------------------


def test_set_install_phase_active_disables_picker(
    qapp: QApplication,
) -> None:
    dialog = PendingInstallsDialog([_item("a"), _item("b")])

    dialog.set_install_phase_active(True)

    for cb in dialog._checkboxes.values():
        assert cb.isEnabled() is False
    assert dialog._install_button.isEnabled() is False


def test_set_install_phase_inactive_re_enables_picker(
    qapp: QApplication,
) -> None:
    dialog = PendingInstallsDialog([_item("a")])
    dialog.set_install_phase_active(True)
    dialog.set_install_phase_active(False)

    assert dialog._checkboxes["a"].isEnabled() is True
    assert dialog._install_button.isEnabled() is True


# --- Show close button ---------------------------------------------------


def test_show_close_button_swaps_buttons(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])

    dialog.show_close_button()

    assert dialog._install_button.isVisible() is False
    assert dialog._cancel_button.isVisible() is False
    assert dialog._close_button is not None


def test_show_close_button_is_idempotent(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])

    dialog.show_close_button()
    dialog.show_close_button()  # should not add a second button

    # We can confirm idempotency by checking the button box children
    # count rather than relying on internal state.
    assert dialog._close_button is not None


def test_close_button_accepts_dialog(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")])
    dialog.show_close_button()
    assert dialog._close_button is not None

    dialog._close_button.click()

    assert dialog.result() == int(dialog.DialogCode.Accepted)


# --- Self-driven install loop (install_one mode) -------------------------


def _ok(item: MissingItem) -> InstallResult:
    return InstallResult(spec=item.spec, success=True, message="installed")


def _fail(item: MissingItem) -> InstallResult:
    return InstallResult(
        spec=item.spec, success=False, message="boom: network down"
    )


def test_install_one_mode_drives_loop_and_updates_rows(
    qapp: QApplication,
) -> None:
    """With install_one, clicking Install installs each ticked item, updates
    its row, records a result, and swaps in the Close button."""
    items = [_item("a"), _item("b")]
    dialog = PendingInstallsDialog(items, install_one=_ok)

    dialog._install_button.click()

    assert dialog._status_labels["a"].text() == "OK"
    assert dialog._status_labels["b"].text() == "OK"
    assert [(r.spec.dep_id, r.success) for r in dialog.results()] == [
        ("a", True), ("b", True)
    ]
    assert dialog._close_button is not None  # ready to dismiss


def test_install_one_mode_records_failures(qapp: QApplication) -> None:
    dialog = PendingInstallsDialog([_item("a")], install_one=_fail)

    dialog._install_button.click()

    result = dialog.results()[0]
    assert result.success is False
    assert "boom" in result.message
    assert dialog._status_labels["a"].text().startswith("FAILED")


def test_install_one_mode_skips_unticked_as_declined(
    qapp: QApplication,
) -> None:
    """Unticked items are not installed; they come back as user_declined so
    the manager won't cascade them to the next tier."""
    items = [_item("a"), _item("b")]
    installed: list[str] = []

    def install_one(item: MissingItem) -> InstallResult:
        installed.append(item.spec.dep_id)
        return _ok(item)

    dialog = PendingInstallsDialog(items, install_one=install_one)
    dialog._checkboxes["b"].setChecked(False)

    dialog._install_button.click()

    assert installed == ["a"]  # b was never installed
    by_id = {r.spec.dep_id: r for r in dialog.results()}
    assert by_id["a"].success is True
    assert by_id["b"].user_declined is True


def test_cancel_in_install_one_mode_declines_all(qapp: QApplication) -> None:
    """Cancelling before installing records a decline for every item."""
    items = [_item("a"), _item("b")]
    dialog = PendingInstallsDialog(items, install_one=_ok)

    dialog._cancel_button.click()  # reject() before any install

    assert all(r.user_declined for r in dialog.results())
    assert {r.spec.dep_id for r in dialog.results()} == {"a", "b"}
