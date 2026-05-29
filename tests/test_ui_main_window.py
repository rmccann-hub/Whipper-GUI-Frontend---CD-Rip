"""Tests for whipper_gui.ui.main_window.

These are integration-flavored: we instantiate the real MainWindow with
fake backends and verify the high-level signal wiring and slot behavior.
We DON'T drive a real Qt event loop — tests poke slots directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from whipper_gui.adapters.metaflac import MetaflacAdapter
from whipper_gui.adapters.musicbrainz_client import (
    MusicBrainzClient,
    ReleaseDetail,
    ReleaseSummary,
    TocSignature,
    TrackSummary,
)
from whipper_gui.adapters.whipper_backend import (
    DiscInfo,
    RipHandle,
    WhipperBackend,
    WhipperError,
)
from whipper_gui.config import Config
from whipper_gui.deps.manager import DependencyManager
from whipper_gui.parsers.drive_list import DriveDescriptor
from whipper_gui.ui.main_window import MainWindow


# --- Fakes ---------------------------------------------------------------


class _FakeBackend(WhipperBackend):
    def __init__(self) -> None:
        self.drives: list[DriveDescriptor] = []
        self.disc_info_return: DiscInfo = DiscInfo()
        self.disc_info_raises: Exception | None = None
        self.disc_info_calls: list[str] = []

    def list_drives(self) -> list[DriveDescriptor]:
        return self.drives

    def disc_info(self, drive: str) -> DiscInfo:
        self.disc_info_calls.append(drive)
        if self.disc_info_raises:
            raise self.disc_info_raises
        return self.disc_info_return

    def rip(
        self,
        drive: str,
        release_id: str,
        output_dir: Path,
        track_template: str,
        disc_template: str,
        unknown: bool = False,
    ) -> RipHandle:
        raise NotImplementedError  # the rip tests don't reach here

    def version(self) -> str:
        return "fake 0.0.0"


class _FakeMb(MusicBrainzClient):
    def __init__(self) -> None:
        self.disc_id_calls: list[str] = []
        self.toc_calls: list[TocSignature] = []
        self.mbid_calls: list[str] = []
        self.disc_id_result: list[ReleaseSummary] = []
        self.mbid_result: ReleaseDetail | None = None

    def releases_by_disc_id(self, disc_id: str) -> list[ReleaseSummary]:
        self.disc_id_calls.append(disc_id)
        return self.disc_id_result

    def releases_by_toc(self, toc: TocSignature) -> list[ReleaseSummary]:
        self.toc_calls.append(toc)
        return []

    def release_by_mbid(self, mbid: str) -> ReleaseDetail:
        self.mbid_calls.append(mbid)
        assert self.mbid_result is not None
        return self.mbid_result

    def set_user_agent(self, app: str, version: str, contact: str) -> None:
        pass


def _detail() -> ReleaseDetail:
    return ReleaseDetail(
        summary=ReleaseSummary(
            mbid="some-mbid",
            title="Album",
            artist_credit="Artist",
            date="2024",
            track_count=2,
        ),
        tracks=(
            TrackSummary(number=1, title="One"),
            TrackSummary(number=2, title="Two"),
        ),
    )


def _make_window(
    qapp: QApplication,
    backend: _FakeBackend | None = None,
    mb_client: _FakeMb | None = None,
    config: Config | None = None,
    save_cfg: Any = None,
) -> MainWindow:
    backend = backend or _FakeBackend()
    mb_client = mb_client or _FakeMb()
    return MainWindow(
        config=config or Config(),
        backend=backend,
        mb_client=mb_client,
        metaflac=MetaflacAdapter(),
        dependency_manager=DependencyManager(specs=[]),
        save_config=save_cfg or (lambda _: None),
    )


@pytest.fixture()
def teardown_threads(qapp: QApplication):
    """Make sure any QThreads owned by windows are stopped before next test."""
    created: list[MainWindow] = []

    def factory(**kwargs: Any) -> MainWindow:
        window = _make_window(qapp, **kwargs)
        created.append(window)
        return window

    yield factory

    for window in created:
        # Quit the MB worker thread so it doesn't leak between tests.
        if window._mb_thread.isRunning():
            window._mb_thread.quit()
            window._mb_thread.wait(2000)
        window.deleteLater()


# --- Construction --------------------------------------------------------


def test_constructs_without_crashing(teardown_threads) -> None:
    window = teardown_threads()
    assert window.windowTitle() == "Whipper GUI"


def test_central_widget_contains_main_widgets(teardown_threads) -> None:
    """The five primary widgets are wired into the central layout."""
    window = teardown_threads()
    # Just check that the references are populated. Exhaustive layout
    # assertion would be brittle; the existence + types are what matter.
    assert window._drive_picker is not None
    assert window._disc_info_panel is not None
    assert window._track_table is not None
    assert window._rip_controls is not None
    assert window._rip_progress is not None


def test_menus_have_settings_and_check_deps(teardown_threads) -> None:
    window = teardown_threads()
    menubar = window.menuBar()
    actions: list[str] = []
    for menu in menubar.findChildren(type(menubar.addMenu("tmp"))):
        for action in menu.actions():
            actions.append(action.text())
    assert any("Settings" in text for text in actions)
    assert any("dependencies" in text.lower() for text in actions)


# --- Drive change → disc_info → MB lookup pipeline -----------------------


def test_drive_change_triggers_disc_info_and_mb_lookup(
    teardown_threads,
) -> None:
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(
        cddb_disc_id="abc",
        musicbrainz_disc_id="mb-id",
    )
    mb = _FakeMb()
    window = teardown_threads(backend=backend, mb_client=mb)

    window._on_drive_changed("/dev/sr0")

    assert backend.disc_info_calls == ["/dev/sr0"]
    assert window._disc_info_panel._mb_id_value.text() == "mb-id"
    assert window._disc_info_panel._cddb_id_value.text() == "abc"
    # MB lookup is queued via signal to the worker; we just confirm
    # the panel's loading status was set (the worker's eventual call
    # happens on its thread and isn't deterministic without an event
    # loop drive).
    assert "MusicBrainz" in window._disc_info_panel._mb_match_value.text()


def test_drive_change_handles_whipper_error(teardown_threads) -> None:
    backend = _FakeBackend()
    backend.disc_info_raises = WhipperError("no disc")
    window = teardown_threads(backend=backend)

    window._on_drive_changed("/dev/sr0")

    text = window._disc_info_panel._mb_match_value.text()
    assert "error" in text.lower()


# --- MB result handling --------------------------------------------------


def test_mb_releases_single_match_fetches_detail(teardown_threads) -> None:
    mb = _FakeMb()
    mb.mbid_result = _detail()
    window = teardown_threads(mb_client=mb)

    # Single-match path goes through fetch_release on the MB worker;
    # We exercise it via the slot directly to avoid thread timing.
    summary = ReleaseSummary(
        mbid="some-mbid", title="Album", artist_credit="Artist"
    )
    window._on_mb_releases([summary])

    # The fetch is queued via signal; we can't deterministically observe
    # mbid_result without driving the event loop. Instead, assert that
    # the panel was updated.
    text = window._disc_info_panel._mb_match_value.text()
    assert "1 match" in text


def test_mb_release_detail_populates_track_table(teardown_threads) -> None:
    window = teardown_threads()

    window._on_mb_release_detail(_detail())

    assert window._track_table.album_metadata().artist == "Artist"
    assert len(window._track_table.tracks()) == 2
    assert window._current_release_id == "some-mbid"


# --- Rip request: validation gate ---------------------------------------


def test_rip_requested_blocked_when_track_table_invalid(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty track table fails validation; a warning is shown and no
    rip worker is spun up."""
    window = teardown_threads()

    warnings: list[tuple[str, str]] = []

    def fake_warning(parent: Any, title: str, text: str) -> Any:
        warnings.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.warning", fake_warning
    )

    from whipper_gui.workers.rip_worker import RipParameters

    params = RipParameters(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/tmp"),
        track_template="t",
        disc_template="d",
    )
    window._on_rip_requested(params)

    assert warnings  # at least one warning was raised
    assert window._rip_worker is None


def test_rip_requested_in_unknown_mode_skips_validation(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown-mode rips don't need pre-populated track metadata."""
    backend = _FakeBackend()
    # We intercept the rip() call so we don't actually fork a process.
    captured: list[dict[str, Any]] = []

    class _StubHandle:
        def log_lines(self) -> Any:
            return iter(())

        def wait(self, timeout: Any = None) -> int:
            return 0

        def cancel(self, term_timeout: float = 5.0) -> int:
            return -15

    def fake_rip(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return _StubHandle()

    backend.rip = fake_rip  # type: ignore[assignment]
    window = teardown_threads(backend=backend)

    from whipper_gui.workers.rip_worker import RipParameters

    params = RipParameters(
        drive="/dev/sr0",
        release_id="",
        output_dir=Path("/tmp/unused"),
        track_template="t",
        disc_template="d",
        unknown=True,
    )
    window._on_rip_requested(params)

    # Worker created; rip thread started (we don't wait for completion).
    assert window._rip_worker is not None
    # Clean up — quit the rip thread we just started.
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.quit()
        window._rip_thread.wait(2000)


# --- closeEvent ----------------------------------------------------------


def test_close_event_stops_mb_thread(teardown_threads) -> None:
    window = teardown_threads()
    assert window._mb_thread.isRunning() is True
    window.close()
    # Thread should be stopped by closeEvent.
    assert window._mb_thread.isRunning() is False


# --- Dep summary popup ---------------------------------------------------


def test_dep_summary_with_no_failures_omits_failure_block(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean dep-check produces a minimal popup."""
    from whipper_gui.deps.manager import DependencyReport

    window = teardown_threads()
    captured: list[tuple[str, str]] = []

    def fake_info(parent: Any, title: str, text: str) -> Any:
        captured.append((title, text))
        return None

    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.information", fake_info
    )

    report = DependencyReport(ok=[], missing=[], install_results=[])
    window._show_dep_summary(report)

    assert len(captured) == 1
    title, text = captured[0]
    assert title == "Dependency check complete"
    assert "Install failures" not in text  # no failure section
    assert "0 ok" in text


def test_dep_summary_includes_failure_details(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real install failures must surface in the popup, not just the log."""
    from whipper_gui.deps.checks import ProbeResult
    from whipper_gui.deps.manager import DependencyReport
    from whipper_gui.deps.registry import DependencySpec, Tier
    from whipper_gui.deps.resolvers import InstallResult

    spec = DependencySpec(
        dep_id="picard",
        display_name="MusicBrainz Picard (Flatpak)",
        probe=lambda: ProbeResult(present=False, version=None, location=None),
        min_version=(0, 0, 0),
        tier=Tier.AUTO,
        install_command=["flatpak", "install"],
        search_string="x",
    )
    failure = InstallResult(
        spec=spec,
        success=False,
        message="install failed: No remote refs found for 'flathub'",
        user_declined=False,
    )

    window = teardown_threads()
    captured: list[tuple[str, str]] = []

    def fake_info(parent: Any, title: str, text: str) -> Any:
        captured.append((title, text))
        return None

    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.information", fake_info
    )

    report = DependencyReport(
        ok=[], missing=[], install_results=[failure]
    )
    window._show_dep_summary(report)

    text = captured[0][1]
    assert "Install failures" in text
    assert "MusicBrainz Picard" in text
    assert "No remote refs found" in text
    assert "log.txt" in text  # points user at the log for full detail


def test_dep_summary_does_not_show_user_declines_as_failures(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Declines are already conveyed by the dialog itself; they shouldn't
    appear in the summary as if they were errors."""
    from whipper_gui.deps.checks import ProbeResult
    from whipper_gui.deps.manager import DependencyReport
    from whipper_gui.deps.registry import DependencySpec, Tier
    from whipper_gui.deps.resolvers import InstallResult

    spec = DependencySpec(
        dep_id="picard",
        display_name="MusicBrainz Picard (Flatpak)",
        probe=lambda: ProbeResult(present=False, version=None, location=None),
        min_version=(0, 0, 0),
        tier=Tier.AUTO,
        install_command=None,
        search_string="x",
    )
    decline = InstallResult(
        spec=spec,
        success=False,
        message="user declined auto-install",
        user_declined=True,
    )

    window = teardown_threads()
    captured: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.information",
        lambda parent, title, text: captured.append((title, text)) or None,
    )

    report = DependencyReport(
        ok=[], missing=[], install_results=[decline]
    )
    window._show_dep_summary(report)

    text = captured[0][1]
    assert "Install failures" not in text  # decline isn't a failure
