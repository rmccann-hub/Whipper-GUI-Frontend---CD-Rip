"""Tests for whipper_gui.ui.main_window.

These are integration-flavored: we instantiate the real MainWindow with
fake backends and verify the high-level signal wiring and slot behavior.
We DON'T drive a real Qt event loop — tests poke slots directly.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
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
from whipper_gui.drive_access import DriveAccessDiagnosis
from whipper_gui.parsers.drive_list import DriveDescriptor
from whipper_gui.parsers.rip_log import RipLog, TrackResult
from whipper_gui.ui.main_window import MainWindow, _fidelity_summary

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
        **kwargs: object,
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
        # Join a launch dependency-check thread too — destroying a window with
        # a running QThread aborts the process. quit() here is delivered to the
        # thread's own loop directly (not via the queued finished→quit), so it
        # works even when the test never pumped the GUI event loop.
        if (
            window._dep_check_thread is not None
            and window._dep_check_thread.isRunning()
        ):
            window._dep_check_thread.quit()
            window._dep_check_thread.wait(2000)
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


def test_menus_have_settings_but_not_duplicate_dep_check(teardown_threads) -> None:
    window = teardown_threads()
    menubar = window.menuBar()
    actions: list[str] = []
    for menu in menubar.findChildren(type(menubar.addMenu("tmp"))):
        for action in menu.actions():
            actions.append(action.text())
    assert any("Settings" in text for text in actions)
    # The dependency check moved entirely to the Settings dialog button —
    # it must NOT also appear in the menus.
    assert not any("dependencies" in text.lower() for text in actions)


# --- Drive change → disc_info → MB lookup pipeline -----------------------


def test_drive_change_triggers_disc_info_and_mb_lookup(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(
        cddb_disc_id="abc",
        musicbrainz_disc_id="mb-id",
    )
    mb = _FakeMb()
    window = teardown_threads(backend=backend, mb_client=mb)
    # The fake MB returns [] synchronously, which now routes to the
    # no-match handler and would open a modal. Stub it so the test
    # focuses on the disc-info + lookup wiring.
    monkeypatch.setattr(window, "open_unknown_album_dialog", lambda: False)

    window._on_drive_changed("/dev/sr0")

    assert backend.disc_info_calls == ["/dev/sr0"]
    assert window._disc_info_panel._mb_id_value.text() == "mb-id"
    assert window._disc_info_panel._cddb_id_value.text() == "abc"
    # MB lookup is queued via signal to the worker; we just confirm
    # the panel's loading status was set (the worker's eventual call
    # happens on its thread and isn't deterministic without an event
    # loop drive).
    assert "MusicBrainz" in window._disc_info_panel._mb_match_value.text()


def test_no_mb_match_shows_blank_track_rows(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown disc (no MB ID) still shows numbered blank rows.

    whipper reports the track count even for a disc MusicBrainz can't
    identify; we render that many rows so the user sees the disc."""
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(num_tracks=16)  # no MB/CDDB id
    window = teardown_threads(backend=backend)
    prompted: list[bool] = []
    monkeypatch.setattr(
        window,
        "open_unknown_album_dialog",
        lambda: prompted.append(True) or False,
    )

    window._on_drive_changed("/dev/sr0")

    assert len(window._track_table.tracks()) == 16
    assert window._track_table.tracks()[0].number == 1
    assert window._track_table.tracks()[0].title == "Track 01"
    assert prompted == [True]  # unknown-album flow was offered


def test_zero_mb_results_shows_blank_track_rows(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disc with an MB ID but no registered release also gets blank rows."""
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(musicbrainz_disc_id="mb-id", num_tracks=12)
    mb = _FakeMb()  # returns [] for the lookup
    window = teardown_threads(backend=backend, mb_client=mb)
    monkeypatch.setattr(window, "open_unknown_album_dialog", lambda: False)

    window._on_drive_changed("/dev/sr0")

    assert len(window._track_table.tracks()) == 12


def test_mb_lookup_error_falls_back_to_placeholder_rows(
    teardown_threads,
) -> None:
    """A MusicBrainz lookup failure (e.g. the AppImage TLS bug) must not
    leave the track table empty — show numbered placeholder rows instead."""
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(musicbrainz_disc_id="mb-id", num_tracks=10)
    window = teardown_threads(backend=backend)
    # Simulate disc_info having recorded the track count, then the worker
    # erroring out (as the SSL CERTIFICATE_VERIFY_FAILED did).
    window._current_num_tracks = 10
    window._on_mb_error("MB disc-id lookup failed: SSL CERTIFICATE_VERIFY_FAILED")

    assert len(window._track_table.tracks()) == 10
    assert "error" in window._disc_info_panel._mb_match_value.text().lower()


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
    summary = ReleaseSummary(mbid="some-mbid", title="Album", artist_credit="Artist")
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

    # Offset IS configured here so we exercise the track-table guard, not the
    # read-offset guard that now precedes it.
    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: True
    )

    warnings: list[tuple[str, str]] = []

    def fake_warning(parent: Any, title: str, text: str) -> Any:
        warnings.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr("whipper_gui.ui.main_window.QMessageBox.warning", fake_warning)

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

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: True
    )

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


def test_rip_requested_blocked_when_no_read_offset(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No read offset configured → the rip is blocked with a warning that
    points at the drive-setup wizard, no worker is started, and answering
    Yes opens the wizard."""

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: False
    )
    window = teardown_threads()

    warnings: list[tuple[str, str]] = []

    def fake_warning(parent: Any, title: str, text: str, *args: Any) -> Any:
        warnings.append((title, text))
        return QMessageBox.StandardButton.Yes  # "open the wizard"

    monkeypatch.setattr("whipper_gui.ui.main_window.QMessageBox.warning", fake_warning)
    opened: list[bool] = []
    monkeypatch.setattr(window, "_on_drive_setup", lambda: opened.append(True))

    from whipper_gui.workers.rip_worker import RipParameters

    window._on_rip_requested(
        RipParameters(
            drive="/dev/sr0",
            release_id="x",
            output_dir=Path("/tmp"),
            track_template="t",
            disc_template="d",
        )
    )

    assert warnings, "a warning should be shown when no offset is configured"
    assert "offset" in (warnings[0][0] + warnings[0][1]).lower()
    assert window._rip_worker is None  # the rip did not start
    assert opened == [True]  # answering Yes opened the wizard


def test_auto_apply_known_offset_for_known_drive(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drive whose offset is in the AccurateRip list is applied automatically
    (no wizard) — the user's Pioneer resolves to +667."""
    saved: list[Config] = []
    window = teardown_threads(save_cfg=saved.append)
    monkeypatch.setattr(
        window._drive_picker,
        "current_drive",
        lambda: DriveDescriptor(
            device="/dev/sr0", vendor="PIONEER", model="BD-RW  BDR-209D", release="1.0"
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    assert window._auto_apply_known_offset() is True
    assert window._config.override_read_offset is True
    assert window._config.read_offset == 667
    assert saved and saved[-1].read_offset == 667


def test_auto_apply_returns_false_for_unknown_or_no_drive(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = teardown_threads()
    # No drive selected.
    monkeypatch.setattr(window._drive_picker, "current_drive", lambda: None)
    assert window._auto_apply_known_offset() is False
    # Unknown drive model.
    monkeypatch.setattr(
        window._drive_picker,
        "current_drive",
        lambda: DriveDescriptor(
            device="/dev/sr0", vendor="ACME", model="Frobnicator 9000", release="1"
        ),
    )
    assert window._auto_apply_known_offset() is False
    assert window._config.override_read_offset is False  # nothing applied


def test_rip_not_blocked_when_drive_offset_is_known(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Start with no saved offset but a known drive → auto-apply + rip proceeds,
    no 'set up your drive' warning."""

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: False
    )

    backend = _FakeBackend()
    rip_kwargs: list[dict] = []

    class _StubHandle:
        def log_lines(self):
            return iter(())

        def wait(self, timeout=None):
            return 0

        def cancel(self, term_timeout: float = 5.0):
            return -15

    def _fake_rip(**kw):
        rip_kwargs.append(kw)
        return _StubHandle()

    backend.rip = _fake_rip  # type: ignore[assignment]
    window = teardown_threads(backend=backend)
    monkeypatch.setattr(
        window._drive_picker,
        "current_drive",
        lambda: DriveDescriptor(
            device="/dev/sr0", vendor="PIONEER", model="BD-RW  BDR-209D", release="1.0"
        ),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    warned: list[bool] = []
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.warning",
        lambda *a, **k: warned.append(True),
    )

    from whipper_gui.workers.rip_worker import RipParameters

    window._on_rip_requested(
        RipParameters(
            drive="/dev/sr0",
            release_id="",
            output_dir=Path("/tmp/x"),
            track_template="t",
            disc_template="d",
            unknown=True,
        )
    )

    assert warned == []  # not blocked
    assert window._config.read_offset == 667  # auto-applied
    assert window._rip_worker is not None  # rip started
    # Crucially, whipper actually receives the offset (regression for the
    # "drive offset unconfigured" bug — params were built before auto-apply).
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.wait(2000)
    assert rip_kwargs and rip_kwargs[0].get("read_offset_override") == 667


def test_auto_heal_retries_as_unknown_on_no_metadata_failure(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed known rip that flagged needs_unknown_retry triggers one
    rip-as-unknown retry."""
    from types import SimpleNamespace

    from whipper_gui.workers.rip_worker import RipParameters

    window = teardown_threads()
    # Simulate the just-finished worker reporting it needs a heal.
    window._rip_worker = SimpleNamespace(needs_unknown_retry=True)  # type: ignore[assignment]
    window._active_rip_params = RipParameters(
        drive="/dev/sr0",
        release_id="mbid",
        output_dir=Path("/tmp/x"),
        track_template="t",
        disc_template="d",
        unknown=False,
    )
    window._rip_cancelled = False
    window._auto_retry_done = False

    retried: list[RipParameters] = []
    monkeypatch.setattr(window, "_start_rip_worker", lambda p: retried.append(p))
    # The retry is deferred via QTimer.singleShot; call synchronously instead.
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QTimer.singleShot", lambda _ms, fn: fn()
    )

    window._on_rip_finished(False, "")

    assert window._auto_retry_done is True
    assert len(retried) == 1
    assert retried[0].unknown is True  # retried as unknown-album
    assert retried[0].release_id == ""  # no release-id → no network needed


def test_rip_finished_shows_actionable_failure_hint(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    window = teardown_threads()
    window._rip_worker = SimpleNamespace(  # type: ignore[assignment]
        needs_unknown_retry=False,
        failure_hint="Track 3 couldn't be read — clean the disc.",
    )
    window._active_rip_params = None
    window._rip_cancelled = False
    window._auto_retry_done = True
    statuses: list[str] = []
    monkeypatch.setattr(window._rip_progress, "set_status", statuses.append)

    window._on_rip_finished(False, "")

    assert any("Track 3" in s for s in statuses)


def test_no_auto_heal_when_not_flagged(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from whipper_gui.workers.rip_worker import RipParameters

    window = teardown_threads()
    window._rip_worker = SimpleNamespace(  # type: ignore[assignment]
        needs_unknown_retry=False, failure_hint=""
    )
    window._active_rip_params = RipParameters(
        drive="/dev/sr0",
        release_id="mbid",
        output_dir=Path("/tmp/x"),
        track_template="t",
        disc_template="d",
        unknown=False,
    )
    window._rip_cancelled = False
    window._auto_retry_done = False
    retried: list = []
    monkeypatch.setattr(window, "_start_rip_worker", lambda p: retried.append(p))
    window._on_rip_finished(False, "")
    assert retried == []  # ordinary failure → no heal


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

    monkeypatch.setattr("whipper_gui.ui.main_window.QMessageBox.information", fake_info)

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

    monkeypatch.setattr("whipper_gui.ui.main_window.QMessageBox.information", fake_info)

    report = DependencyReport(ok=[], missing=[], install_results=[failure])
    window._show_dep_summary(report)

    text = captured[0][1]
    assert "Install failures" in text
    assert "MusicBrainz Picard" in text
    assert "No remote refs found" in text
    assert "log.txt" in text  # points user at the log for full detail


def test_dep_summary_stamps_installed_versions(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OK deps are listed with the detected version (reproducibility), and
    a probed-but-version-unknown dep renders as 'unknown'."""
    from whipper_gui.deps.checks import ProbeResult
    from whipper_gui.deps.manager import DependencyReport
    from whipper_gui.deps.registry import DependencySpec, Tier

    def _spec(dep_id: str, name: str) -> DependencySpec:
        return DependencySpec(
            dep_id=dep_id,
            display_name=name,
            probe=lambda: ProbeResult(present=True, version=None, location=None),
            min_version=(0, 0, 0),
            tier=Tier.MANUAL,
            install_command=None,
            search_string="x",
        )

    whipper = _spec("whipper", "whipper")
    flac = _spec("flac", "FLAC")

    window = teardown_threads()
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.QMessageBox.information",
        lambda parent, title, text: captured.append((title, text)),
    )

    report = DependencyReport(
        ok=[whipper, flac],
        ok_versions={"whipper": (0, 10, 0)},  # flac omitted → "unknown"
    )
    window._show_dep_summary(report)

    text = captured[0][1]
    assert "Installed:" in text
    assert "whipper 0.10.0" in text
    assert "FLAC unknown" in text


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

    report = DependencyReport(ok=[], missing=[], install_results=[decline])
    window._show_dep_summary(report)

    text = captured[0][1]
    assert "Install failures" not in text  # decline isn't a failure


# --- Fidelity summary ------------------------------------------------------


def _crc_track(number: int, test: str, copy: str) -> TrackResult:
    return TrackResult(number=number, test_crc=test, copy_crc=copy, status="Copy OK")


def test_fidelity_summary_all_verified() -> None:
    rip_log = RipLog(
        tracks=(
            _crc_track(1, "AAAA", "AAAA"),
            _crc_track(2, "BBBB", "BBBB"),
        )
    )
    summary = _fidelity_summary(rip_log)
    assert "all 2 tracks verified" in summary
    assert "CRCs match" in summary


def test_fidelity_summary_partial_verification() -> None:
    rip_log = RipLog(
        tracks=(
            _crc_track(1, "AAAA", "AAAA"),
            TrackResult(number=2, test_crc="BBBB", copy_crc="CCCC"),  # mismatch
        )
    )
    summary = _fidelity_summary(rip_log)
    assert "1/2 tracks CRC-verified" in summary


def test_fidelity_summary_mentions_accuraterip_when_matched() -> None:
    rip_log = RipLog(
        tracks=(_crc_track(1, "AAAA", "AAAA"),),
        accuraterip_summary="Found, exact match for all tracks",
    )
    assert "AccurateRip confirmed" in _fidelity_summary(rip_log)


def test_fidelity_summary_no_tracks() -> None:
    assert _fidelity_summary(RipLog(tracks=())) == "Done."


def test_fidelity_summary_cyanrip_clean_rip() -> None:
    """cyanrip has no test+copy dual read — the verdict is worded around
    its actual checks (paranoia error count + AccurateRip)."""
    rip_log = RipLog(
        log_creator="cyanrip 0.9.3.1",
        tracks=(
            TrackResult(number=1, copy_crc="AAAA", status="ripped successfully"),
            TrackResult(number=2, copy_crc="BBBB", status="ripped successfully"),
        ),
        health_status="No errors occurred",
        accuraterip_summary="2/2 tracks ripped accurately (AccurateRip)",
    )
    summary = _fidelity_summary(rip_log)
    assert "all 2 tracks ripped cleanly" in summary
    assert "AccurateRip: 2/2" in summary
    assert "CRCs match" not in summary  # never claim a check that didn't run


def test_fidelity_summary_cyanrip_with_errors() -> None:
    rip_log = RipLog(
        log_creator="cyanrip 0.9.3.1",
        tracks=(
            TrackResult(number=1, status="ripped successfully"),
            TrackResult(number=2, status="ripped with errors"),
        ),
        health_status="3 ripping errors",
        accuraterip_summary="0/2 tracks ripped accurately (AccurateRip)",
    )
    summary = _fidelity_summary(rip_log)
    assert "1/2 tracks ripped cleanly" in summary
    assert "AccurateRip" not in summary  # 0/2 isn't a confirmation


# --- Unknown-mode tag post-processing -------------------------------------


def _params(output_dir: Path, unknown: bool):
    from whipper_gui.workers.rip_worker import RipParameters

    return RipParameters(
        drive="/dev/sr0",
        release_id="" if unknown else "mbid",
        output_dir=output_dir,
        track_template="t",
        disc_template="d",
        unknown=unknown,
        cdr=False,
    )


def test_unknown_rip_finish_runs_tag_post_processing(
    teardown_threads, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    window = teardown_threads()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        window,
        "run_unknown_post_processing",
        lambda out, picard: calls.append((out, picard)),
    )
    window._pending_picard_launch = True
    window._active_rip_params = _params(tmp_path, unknown=True)
    # whipper writes the .log next to the FLACs; that folder (not the
    # configured output root) is what should be tagged.
    album_dir = tmp_path / "Unknown Artist" / "Unknown Album"
    album_dir.mkdir(parents=True)
    log_file = album_dir / "Unknown Album.log"
    log_file.write_text("", encoding="utf-8")

    window._on_rip_finished(True, str(log_file))

    assert calls == [(album_dir, True)]  # scoped to the just-ripped folder
    assert window._active_rip_params is None  # cleared for the next rip


def test_known_rip_finish_skips_tag_post_processing(
    teardown_threads, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    window = teardown_threads()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        window,
        "run_unknown_post_processing",
        lambda out, picard: calls.append((out, picard)),
    )
    window._active_rip_params = _params(tmp_path, unknown=False)

    window._on_rip_finished(True, "")

    assert calls == []  # identified discs are tagged by whipper itself


def test_failed_unknown_rip_skips_tag_post_processing(
    teardown_threads, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    window = teardown_threads()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        window,
        "run_unknown_post_processing",
        lambda out, picard: calls.append((out, picard)),
    )
    window._active_rip_params = _params(tmp_path, unknown=True)

    window._on_rip_finished(False, "")  # rip failed

    assert calls == []  # nothing to tag


class _CapturingMetaflac(MetaflacAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[Path, dict[str, str]]] = []

    def write_tags(self, flac_path: Path, tags: dict[str, str]) -> None:
        self.calls.append((flac_path, dict(tags)))


def test_run_unknown_post_processing_applies_table_edits(
    teardown_threads, tmp_path: Path
) -> None:
    """The album fields the user edited in the track table reach the FLAC tags."""
    window = teardown_threads()
    fake = _CapturingMetaflac()
    window._metaflac = fake
    # Show two placeholder rows, then simulate the user editing the album.
    window._track_table.set_placeholder_tracks(2)
    window._track_table._album_artist_edit.setText("Various Artists")
    window._track_table._album_title_edit.setText("My Compilation")
    window._track_table._album_year_edit.setText("2001")
    for name in ("01 - Track 01.flac", "02 - Track 02.flac"):
        (tmp_path / name).write_bytes(b"")

    window.run_unknown_post_processing(tmp_path, launch_picard=False)

    assert len(fake.calls) == 2
    first_tags = fake.calls[0][1]
    assert first_tags["ALBUM"] == "My Compilation"
    assert first_tags["ALBUMARTIST"] == "Various Artists"
    assert first_tags["DATE"] == "2001"
    assert first_tags["TRACKNUMBER"] == "01"


# --- Drive-access diagnostics ---------------------------------------------


def _diag(severity: str, fix: str | None) -> DriveAccessDiagnosis:
    return DriveAccessDiagnosis(
        severity=severity, summary="s", detail="d", fix_command=fix
    )


def test_drives_unavailable_nudges_once_when_actionable(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.diagnose_drive_access",
        lambda **kw: _diag("permission", "sudo usermod -aG cdrom $USER"),
    )

    window._on_drives_unavailable()
    window._on_drives_unavailable()  # refresh again — must NOT re-pop

    assert len(shown) == 1


def test_drives_unavailable_quiet_when_not_actionable(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.diagnose_drive_access",
        lambda **kw: _diag("no_device", None),
    )

    window._on_drives_unavailable()

    assert shown == []  # nothing the user can do → don't interrupt


def test_tools_diagnose_always_shows(
    teardown_threads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.diagnose_drive_access",
        lambda **kw: _diag("no_device", None),
    )

    window._show_drive_access_diagnosis()  # Tools → Diagnose

    assert len(shown) == 1  # shows regardless of severity


# --- Unknown-disc folder naming from album fields ------------------------


def test_unknown_rip_folder_uses_album_fields(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The album artist/title the user typed should drive the unknown-disc
    folder template (not the literal "Unknown Artist/Unknown Album")."""
    backend = _FakeBackend()

    class _StubHandle:
        def log_lines(self):
            return iter(())

        def wait(self, timeout=None):
            return 0

        def cancel(self, term_timeout: float = 5.0):
            return -15

    backend.rip = lambda **kw: _StubHandle()  # type: ignore[assignment]
    window = teardown_threads(backend=backend)

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: True
    )
    window._track_table._album_artist_edit.setText("jimmy2")
    window._track_table._album_title_edit.setText("for")

    from whipper_gui.workers.rip_worker import RipParameters

    window._on_rip_requested(
        RipParameters(
            drive="/dev/sr0",
            release_id="",
            output_dir=Path("/tmp/x"),
            track_template="literal-unknown",
            disc_template="literal-unknown",
            unknown=True,
        )
    )

    assert window._active_rip_params.track_template == "jimmy2/for/%t - Track %t"
    assert window._active_rip_params.disc_template == "jimmy2/for/for"
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.quit()
        window._rip_thread.wait(2000)


def test_unknown_rip_folder_falls_back_when_album_blank(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _FakeBackend()

    class _StubHandle:
        def log_lines(self):
            return iter(())

        def wait(self, timeout=None):
            return 0

        def cancel(self, term_timeout: float = 5.0):
            return -15

    backend.rip = lambda **kw: _StubHandle()  # type: ignore[assignment]
    window = teardown_threads(backend=backend)

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.is_offset_configured", lambda _override: True
    )
    # album fields left blank
    from whipper_gui.workers.rip_worker import RipParameters

    window._on_rip_requested(
        RipParameters(
            drive="/dev/sr0",
            release_id="",
            output_dir=Path("/tmp/x"),
            track_template="t",
            disc_template="d",
            unknown=True,
        )
    )
    assert window._active_rip_params.track_template.startswith(
        "Unknown Artist/Unknown Album/"
    )
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.quit()
        window._rip_thread.wait(2000)


def test_safe_path_segment() -> None:
    from whipper_gui.ui.main_window import _safe_path_segment

    assert _safe_path_segment("  jimmy2 ") == "jimmy2"
    assert _safe_path_segment("AC/DC") == "AC-DC"  # no stray subdir
    assert _safe_path_segment("50%off") == "50off"  # no whipper code
    assert _safe_path_segment("") == ""  # blank → fallback


# --- First-run drive-setup offer + manual offset -------------------------


def test_should_offer_when_unconfigured_and_not_prompted(
    teardown_threads, monkeypatch
) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: False
    )
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    assert window._should_offer_drive_setup() is True


def test_no_offer_when_already_prompted(teardown_threads, monkeypatch) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: False
    )
    window = teardown_threads(config=Config(drive_setup_prompted=True))
    assert window._should_offer_drive_setup() is False


def test_no_offer_when_offset_already_configured(teardown_threads, monkeypatch) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: True
    )
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    assert window._should_offer_drive_setup() is False


def test_maybe_offer_records_prompt_and_launches_on_yes(
    teardown_threads, monkeypatch
) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: False
    )
    saved: list[Config] = []
    window = teardown_threads(
        config=Config(drive_setup_prompted=False), save_cfg=saved.append
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    launched: list[bool] = []
    monkeypatch.setattr(window, "_on_drive_setup", lambda: launched.append(True))

    window._maybe_offer_drive_setup()

    # Recorded so it never re-nags, persisted, and the wizard was launched.
    assert window._config.drive_setup_prompted is True
    assert saved and saved[-1].drive_setup_prompted is True
    assert launched == [True]


def test_maybe_offer_no_launch_on_no(teardown_threads, monkeypatch) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: False
    )
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    launched: list[bool] = []
    monkeypatch.setattr(window, "_on_drive_setup", lambda: launched.append(True))

    window._maybe_offer_drive_setup()

    assert launched == []
    assert window._config.drive_setup_prompted is True  # still recorded


def test_maybe_offer_skips_when_configured(teardown_threads, monkeypatch) -> None:

    monkeypatch.setattr(
        "whipper_gui.ui.main_window_drive.is_offset_configured", lambda _override: True
    )
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    launched: list[bool] = []
    monkeypatch.setattr(window, "_on_drive_setup", lambda: launched.append(True))

    window._maybe_offer_drive_setup()

    assert launched == []
    assert window._config.drive_setup_prompted is False  # never even offered


# --- First-run host-setup offer ------------------------------------------


def test_host_stack_ready_reflects_whipper_path(teardown_threads, tmp_path) -> None:
    whipper = tmp_path / "whipper"
    window = teardown_threads(config=Config(whipper_path=str(whipper)))
    assert window._host_stack_ready() is False
    whipper.write_text("#!/bin/sh\n")
    assert window._host_stack_ready() is True


def test_first_run_offers_host_setup_when_not_ready(
    teardown_threads, monkeypatch
) -> None:
    window = teardown_threads()
    monkeypatch.setattr(window, "_host_stack_ready", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(window, "_maybe_offer_host_setup", lambda: calls.append("host"))
    monkeypatch.setattr(
        window, "_maybe_offer_drive_setup", lambda: calls.append("drive")
    )
    window._maybe_offer_first_run_setup()
    assert calls == ["host"]  # host stack first; drive offer not reached


def test_first_run_offers_drive_setup_when_host_ready(
    teardown_threads, monkeypatch
) -> None:
    window = teardown_threads()
    monkeypatch.setattr(window, "_host_stack_ready", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(window, "_maybe_offer_host_setup", lambda: calls.append("host"))
    monkeypatch.setattr(
        window, "_maybe_offer_drive_setup", lambda: calls.append("drive")
    )
    window._maybe_offer_first_run_setup()
    assert calls == ["drive"]


def test_maybe_offer_host_setup_records_and_opens_on_yes(
    teardown_threads, monkeypatch
) -> None:
    saved: list[Config] = []
    window = teardown_threads(
        config=Config(host_setup_prompted=False), save_cfg=saved.append
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    opened: list[bool] = []
    monkeypatch.setattr(window, "open_host_setup_dialog", lambda: opened.append(True))

    window._maybe_offer_host_setup()

    assert window._config.host_setup_prompted is True
    assert saved and saved[-1].host_setup_prompted is True
    assert opened == [True]


def test_maybe_offer_host_setup_skips_when_already_prompted(
    teardown_threads, monkeypatch
) -> None:
    window = teardown_threads(config=Config(host_setup_prompted=True))
    opened: list[bool] = []
    monkeypatch.setattr(window, "open_host_setup_dialog", lambda: opened.append(True))
    window._maybe_offer_host_setup()
    assert opened == []


def test_start_rip_worker_snapshots_track_table_metadata(
    teardown_threads, monkeypatch
) -> None:
    """The rip params must carry the track table's album/track tags so a
    metadata-fed backend (cyanrip -a/-t) tags exactly what the user sees."""
    from whipper_gui.workers.rip_worker import RipParameters

    window = teardown_threads()
    window._track_table.set_release(_detail())
    seen: list[RipParameters] = []

    class _NoopWorker:
        def __init__(self, backend, params):
            seen.append(params)

        def moveToThread(self, thread):
            pass

        def start_rip(self):
            pass

        # Signal stand-ins that accept connect() without doing anything.
        class _Sig:
            def connect(self, *_a, **_k):
                pass

        log_line = progress = status = current_track = error = finished = _Sig()

    monkeypatch.setattr("whipper_gui.ui.main_window_rip.RipWorker", _NoopWorker)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window_rip.QThread", lambda parent=None: _FakeThread()
    )

    window._start_rip_worker(
        RipParameters(
            drive="/dev/sr0",
            release_id="some-mbid",
            output_dir=Path("/tmp/out"),
            track_template="t",
            disc_template="d",
        )
    )

    meta = seen[0].metadata
    assert meta is not None
    assert meta.album_artist == "Artist"
    assert meta.album_title == "Album"
    assert meta.year == "2024"
    assert meta.tracks == ((1, "One", ""), (2, "Two", ""))


class _FakeThread:
    """Minimal QThread stand-in: collects connects, never starts."""

    class _Sig:
        def connect(self, *_a, **_k):
            pass

    started = finished = _Sig()

    def start(self):
        pass

    def quit(self):
        pass

    def deleteLater(self):
        pass


# --- Update check (KDD-17b) -------------------------------------------------


def test_help_menu_has_check_for_updates(teardown_threads) -> None:
    window = teardown_threads()
    menubar = window.menuBar()
    actions: list[str] = []
    for menu in menubar.findChildren(type(menubar.addMenu("tmp"))):
        actions += [a.text() for a in menu.actions()]
    assert any("Check for" in text and "updates" in text for text in actions)


def test_update_result_none_reports_check_failure(
    teardown_threads, monkeypatch
) -> None:
    window = teardown_threads()
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text, *a, **k: seen.append(text),
    )
    window._on_update_result(None)
    assert seen and "Couldn't check" in seen[0]


def test_update_result_up_to_date(teardown_threads, monkeypatch) -> None:
    from whipper_gui import __version__
    from whipper_gui.update_check import ReleaseInfo

    window = teardown_threads()
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text, *a, **k: seen.append(text),
    )
    window._on_update_result(ReleaseInfo(version=__version__, url="x"))
    assert seen and "up to date" in seen[0]


def test_update_result_newer_without_appimage_opens_release_page(
    teardown_threads, monkeypatch
) -> None:
    """Source/pipx installs can't be file-swapped → offer the download page."""
    from PySide6.QtGui import QDesktopServices

    import whipper_gui.appimage_integration as ai
    from whipper_gui.update_check import ReleaseInfo

    window = teardown_threads()
    monkeypatch.setattr(ai, "appimage_path", lambda: None)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        staticmethod(lambda url: opened.append(url.toString())),
    )

    window._on_update_result(ReleaseInfo(version="99.0.0", url="https://example.com/r"))

    assert opened == ["https://example.com/r"]


def test_update_result_newer_as_appimage_starts_builtin_install(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """Running as an AppImage → the built-in download/verify/install flow
    (KDD-17b amendment: no external tool, no manual download)."""
    import whipper_gui.appimage_integration as ai
    from whipper_gui.update_check import ReleaseInfo

    window = teardown_threads()
    monkeypatch.setattr(
        ai, "appimage_path", lambda: tmp_path / "whipper-gui-x86_64.AppImage"
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    started: list[str] = []
    monkeypatch.setattr(window, "_begin_update_install", started.append)

    window._on_update_result(ReleaseInfo(version="99.0.0", url="https://x"))

    assert started == ["99.0.0"]


def test_update_install_success_offers_restart(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """A verified install ends with re-integration + a restart into the
    new file (launch new, close old) — the 'old version stays open and the
    menu launches the old file' report, fixed."""
    import subprocess as subprocess_mod

    import whipper_gui.appimage_integration as ai

    window = teardown_threads()
    new_path = tmp_path / "Applications" / "whipper-gui-x86_64.AppImage"
    integrated: list[Path] = []
    monkeypatch.setattr(ai, "integrate", lambda p, **k: integrated.append(p))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    launched: list[list[str]] = []
    monkeypatch.setattr(
        subprocess_mod, "Popen", lambda argv, **kw: launched.append(argv)
    )
    closed: list[bool] = []
    monkeypatch.setattr(window, "close", lambda: closed.append(True))

    class _FakeDialog:
        def close(self):
            pass

    window._on_update_install_finished(True, str(new_path), _FakeDialog())

    assert integrated == [new_path]  # menu entry repointed at the new file
    assert launched == [[str(new_path)]]  # new version started
    assert closed == [True]  # old session closed


def test_update_install_failure_changes_nothing(teardown_threads, monkeypatch) -> None:
    window = teardown_threads()
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, text, *a, **k: warnings.append(text),
    )

    class _FakeDialog:
        def close(self):
            pass

    window._on_update_install_finished(
        False, "checksum verification failed", _FakeDialog()
    )

    assert warnings and "checksum verification failed" in warnings[0]
    assert "Nothing was changed" in warnings[0]


# --- In-app Uninstaller wiring ---------------------------------------------


def test_tools_menu_has_uninstall_action(teardown_threads) -> None:
    window = teardown_threads()
    menubar = window.menuBar()
    actions: list[str] = []
    for menu in menubar.findChildren(type(menubar.addMenu("tmp"))):
        actions += [a.text() for a in menu.actions()]
    assert any("Uninstall Whipper GUI" in text for text in actions)


def test_uninstall_finished_offers_quit_on_success(
    teardown_threads, monkeypatch
) -> None:
    window = teardown_threads()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    closed: list[bool] = []
    monkeypatch.setattr(window, "close", lambda: closed.append(True))

    window._on_uninstall_finished(True)
    assert closed == [True]

    # An incomplete uninstall must NOT prompt or close.
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("prompted")),
    )
    window._on_uninstall_finished(False)
    assert closed == [True]


# --- cyanrip in the host-setup wizard (KDD-18) ----------------------------


def test_build_host_setup_includes_cyanrip_per_config(teardown_threads) -> None:
    """The wizard installs cyanrip only when the cyanrip backend is selected."""
    window = teardown_threads(config=Config(ripper_backend="cyanrip"))
    assert window._build_host_setup().include_cyanrip is True

    window = teardown_threads()  # default config → whipper backend
    assert window._build_host_setup().include_cyanrip is False


def test_switch_to_cyanrip_offers_install_when_missing(
    teardown_threads, monkeypatch
) -> None:
    import whipper_gui.deps.host_setup as host_setup

    window = teardown_threads(config=Config(ripper_backend="cyanrip"))
    monkeypatch.setattr(host_setup, "cyanrip_on_host", lambda: False)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    opened: list[bool] = []
    monkeypatch.setattr(window, "open_host_setup_dialog", lambda: opened.append(True))

    window._maybe_offer_cyanrip_install(old_backend="whipper")

    assert opened == [True]


def test_no_cyanrip_offer_when_already_installed(teardown_threads, monkeypatch) -> None:
    import whipper_gui.deps.host_setup as host_setup

    window = teardown_threads(config=Config(ripper_backend="cyanrip"))
    monkeypatch.setattr(host_setup, "cyanrip_on_host", lambda: True)
    opened: list[bool] = []
    monkeypatch.setattr(window, "open_host_setup_dialog", lambda: opened.append(True))

    window._maybe_offer_cyanrip_install(old_backend="whipper")

    assert opened == []


def test_no_cyanrip_offer_when_backend_unchanged(teardown_threads, monkeypatch) -> None:
    """Re-saving Settings while already on cyanrip must not re-nag."""
    import whipper_gui.deps.host_setup as host_setup

    window = teardown_threads(config=Config(ripper_backend="cyanrip"))
    monkeypatch.setattr(host_setup, "cyanrip_on_host", lambda: False)
    opened: list[bool] = []
    monkeypatch.setattr(window, "open_host_setup_dialog", lambda: opened.append(True))

    window._maybe_offer_cyanrip_install(old_backend="cyanrip")

    assert opened == []


# --- First-run AppImage integration offer --------------------------------


def test_no_integration_offer_when_not_appimage(teardown_threads, monkeypatch) -> None:
    import whipper_gui.appimage_integration as ai

    monkeypatch.setattr(ai, "appimage_path", lambda: None)
    window = teardown_threads()
    integrated: list[bool] = []
    monkeypatch.setattr(ai, "integrate", lambda *a, **k: integrated.append(True))
    window._maybe_offer_appimage_integration()  # must be a no-op
    assert integrated == []


def test_integration_offer_runs_on_yes(teardown_threads, monkeypatch, tmp_path) -> None:
    import whipper_gui.appimage_integration as ai

    appimage = tmp_path / "whipper-gui-x86_64.AppImage"
    appimage.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: appimage)
    monkeypatch.setattr(ai, "is_integrated", lambda *_a, **_k: False)
    saved: list[Config] = []
    window = teardown_threads(
        config=Config(appimage_integration_prompted=False), save_cfg=saved.append
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    integrated: list[Path] = []
    # Stub the relocation (identity) — its real behaviour is covered by
    # test_integration_offer_relocates_then_integrates and the
    # appimage_integration unit tests; here we only care about the wiring.
    monkeypatch.setattr(ai, "relocate_to_applications", lambda p: p)
    monkeypatch.setattr(ai, "integrate", lambda p: integrated.append(p))

    window._maybe_offer_appimage_integration()

    assert window._config.appimage_integration_prompted is True
    assert saved and saved[-1].appimage_integration_prompted is True
    assert integrated == [appimage]


def test_integration_offer_skips_only_the_declined_file(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """Declining silences the offer for THAT file only — a different file
    (a freshly downloaded update) gets the offer again."""
    import whipper_gui.appimage_integration as ai

    declined = tmp_path / "whipper-gui-x86_64.AppImage"
    declined.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: declined)
    monkeypatch.setattr(ai, "is_integrated", lambda p: False)
    window = teardown_threads(
        config=Config(integration_declined_path=str(declined)),
        save_cfg=lambda c: None,
    )
    asked: list[bool] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: (asked.append(True), QMessageBox.StandardButton.No)[1],
    )
    window._maybe_offer_appimage_integration()
    assert asked == []  # same file declined before → no nag


def test_integration_reoffers_for_a_new_file_despite_legacy_flag(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """REGRESSION (real-user report 2026-06-10): the legacy 'prompted once'
    boolean suppressed the offer forever, so a downloaded UPDATE never got
    its menu entry remade. A not-yet-integrated file must be offered even
    when the legacy flag is set."""
    import whipper_gui.appimage_integration as ai

    new_version = tmp_path / "whipper-gui-x86_64.AppImage"
    new_version.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: new_version)
    monkeypatch.setattr(ai, "is_integrated", lambda p: False)
    monkeypatch.setattr(ai, "relocate_to_applications", lambda p: p)
    integrated: list[Path] = []
    monkeypatch.setattr(ai, "integrate", lambda p, **k: integrated.append(p))
    window = teardown_threads(
        config=Config(appimage_integration_prompted=True),  # legacy flag set
        save_cfg=lambda c: None,
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._maybe_offer_appimage_integration()

    assert integrated == [new_version]


def test_integration_decline_is_remembered_per_file(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    import whipper_gui.appimage_integration as ai

    appimage = tmp_path / "whipper-gui-x86_64.AppImage"
    appimage.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: appimage)
    monkeypatch.setattr(ai, "is_integrated", lambda p: False)
    saved: list[Config] = []
    window = teardown_threads(config=Config(), save_cfg=saved.append)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )

    window._maybe_offer_appimage_integration()

    assert saved and saved[-1].integration_declined_path == str(appimage)


def test_add_app_shortcut_integrates_when_appimage(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    import whipper_gui.appimage_integration as ai

    appimage = tmp_path / "whipper-gui-x86_64.AppImage"
    appimage.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: appimage)
    integrated: list[Path] = []
    monkeypatch.setattr(ai, "relocate_to_applications", lambda p: p)
    monkeypatch.setattr(ai, "integrate", lambda p: integrated.append(p))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window = teardown_threads()

    window._on_add_app_shortcut()

    assert integrated == [appimage]


def test_add_app_shortcut_noop_when_not_appimage(teardown_threads, monkeypatch) -> None:
    import whipper_gui.appimage_integration as ai

    monkeypatch.setattr(ai, "appimage_path", lambda: None)
    integrated: list[bool] = []
    monkeypatch.setattr(ai, "integrate", lambda *a, **k: integrated.append(True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window = teardown_threads()

    window._on_add_app_shortcut()  # explains, doesn't integrate

    assert integrated == []


def _patch_force_stop(monkeypatch) -> list[dict]:
    """Record force-stop calls instead of touching a real drive/container.

    We patch only ``drive_control.force_stop_drive`` (resolved at call time by
    ``_do_force_stop``) and let the real daemon thread run the fast fake — we
    deliberately do NOT replace ``threading.Thread`` globally, which could
    interfere with other threads spawned during the test.
    """
    from whipper_gui import drive_control

    calls: list[dict] = []
    monkeypatch.setattr(
        drive_control,
        "force_stop_drive",
        lambda **kw: calls.append(kw),
    )
    return calls


def _join_force_stop(window) -> None:
    if window._force_stop_thread is not None:
        window._force_stop_thread.join(timeout=2)


def test_help_menu_has_about_and_user_guide(teardown_threads) -> None:
    from PySide6.QtWidgets import QMenu

    window = teardown_threads()
    menus = window.menuBar().findChildren(QMenu)
    help_menus = [m for m in menus if m.title() == "&Help"]
    assert help_menus, f"no Help menu among {[m.title() for m in menus]}"
    labels = [a.text() for a in help_menus[0].actions()]
    assert any("About" in lbl for lbl in labels)
    assert any("User Guide" in lbl for lbl in labels)


def test_cancel_arms_force_stop_timer(teardown_threads) -> None:
    window = teardown_threads()
    window._rip_worker = SimpleNamespace(cancel=lambda: None)
    window._on_rip_cancel()
    try:
        assert window._rip_cancelled is True
        assert window._force_stop_timer.isActive()
        assert window._force_stop_done is False
    finally:
        window._force_stop_timer.stop()


def test_auto_force_stop_calls_drive_control(teardown_threads, monkeypatch) -> None:
    calls = _patch_force_stop(monkeypatch)
    window = teardown_threads()
    window._auto_force_stop()
    _join_force_stop(window)
    assert len(calls) == 1
    assert "device" in calls[0]
    assert window._force_stop_done is True


def test_auto_force_stop_is_noop_when_already_done(
    teardown_threads, monkeypatch
) -> None:
    calls = _patch_force_stop(monkeypatch)
    window = teardown_threads()
    window._force_stop_done = True
    window._auto_force_stop()
    _join_force_stop(window)
    assert calls == []


# --- Eject ---------------------------------------------------------------


def _patch_eject(monkeypatch) -> list[dict]:
    """Record eject_drive calls instead of touching a real drive."""
    from whipper_gui import drive_control

    calls: list[dict] = []
    monkeypatch.setattr(drive_control, "eject_drive", lambda **kw: calls.append(kw))
    return calls


def _join_eject(window) -> None:
    if window._eject_thread is not None:
        window._eject_thread.join(timeout=2)


def _rip_params(drive: str, unknown: bool = False):
    from whipper_gui.workers.rip_worker import RipParameters

    return RipParameters(
        drive=drive,
        release_id="mbid",
        output_dir=Path("/tmp"),
        track_template="t",
        disc_template="d",
        unknown=unknown,
    )


def test_manual_eject_request_calls_drive_control(
    teardown_threads, monkeypatch
) -> None:
    calls = _patch_eject(monkeypatch)
    window = teardown_threads()

    window._on_eject_requested("/dev/sr0")
    _join_eject(window)

    assert calls == [{"device": "/dev/sr0"}]


def test_auto_eject_on_successful_rip_when_enabled(
    teardown_threads, monkeypatch
) -> None:
    calls = _patch_eject(monkeypatch)
    window = teardown_threads(config=Config(auto_eject_after_rip=True))
    window._active_rip_params = _rip_params("/dev/sr0")

    window._on_rip_finished(True, "")
    _join_eject(window)

    assert calls == [{"device": "/dev/sr0"}]


def test_no_auto_eject_when_disabled(teardown_threads, monkeypatch) -> None:
    calls = _patch_eject(monkeypatch)
    window = teardown_threads(config=Config(auto_eject_after_rip=False))
    window._active_rip_params = _rip_params("/dev/sr0")

    window._on_rip_finished(True, "")
    _join_eject(window)

    assert calls == []


def test_no_auto_eject_on_failed_rip(teardown_threads, monkeypatch) -> None:
    calls = _patch_eject(monkeypatch)
    window = teardown_threads(config=Config(auto_eject_after_rip=True))
    window._active_rip_params = _rip_params("/dev/sr0")

    window._on_rip_finished(False, "")
    _join_eject(window)

    assert calls == []


def test_force_stop_button_stops_timer_and_fires(teardown_threads, monkeypatch) -> None:
    calls = _patch_force_stop(monkeypatch)
    window = teardown_threads()
    window._force_stop_timer.start(60000)
    window._on_force_stop_button()
    _join_force_stop(window)
    assert window._force_stop_timer.isActive() is False
    assert len(calls) == 1


def test_manual_offset_saved_sets_override(teardown_threads) -> None:
    saved: list[Config] = []
    window = teardown_threads(config=Config(), save_cfg=saved.append)

    window._on_manual_offset_saved(667)

    assert window._config.read_offset == 667
    assert window._config.override_read_offset is True
    assert saved and saved[-1].read_offset == 667


# --- Dialog-driven queued resolver (live per-item install feedback) ------


def test_dialog_queued_resolver_returns_install_results(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_DialogQueuedResolver drives the dialog's own install loop and returns
    one InstallResult per item. We replace exec() (which would block on a
    modal loop) with a stub that runs the loop and accepts, so the wiring is
    tested without a real event loop."""
    from whipper_gui.deps.checks import ProbeResult
    from whipper_gui.deps.registry import DependencySpec, Tier
    from whipper_gui.deps.resolvers import InstallResult, MissingItem
    from whipper_gui.ui.dialogs.pending_installs import PendingInstallsDialog
    from whipper_gui.ui.main_window import _DialogQueuedResolver

    def _item(dep_id: str) -> MissingItem:
        spec = DependencySpec(
            dep_id=dep_id,
            display_name=dep_id,
            probe=lambda: ProbeResult(present=False, version=None, location=None),
            min_version=(0, 0, 0),
            tier=Tier.QUEUED,
            install_command=["echo", dep_id],
            search_string="x",
        )
        return MissingItem(
            spec=spec,
            probe=ProbeResult(present=False, version=None, location=None),
        )

    def fake_exec(self: PendingInstallsDialog) -> int:
        self._run_install_loop()
        return int(self.DialogCode.Accepted)

    monkeypatch.setattr(PendingInstallsDialog, "exec", fake_exec)

    def install_one(item):
        return InstallResult(spec=item.spec, success=True, message="installed")

    resolver = _DialogQueuedResolver(parent=None, install_one=install_one)

    results = resolver.resolve([_item("a"), _item("b")])

    assert [(r.spec.dep_id, r.success) for r in results] == [("a", True), ("b", True)]


def test_dialog_queued_resolver_empty_items_is_noop(qapp) -> None:
    from whipper_gui.ui.main_window import _DialogQueuedResolver

    resolver = _DialogQueuedResolver(parent=None, install_one=lambda i: None)
    assert resolver.resolve([]) == []


def test_friendly_disc_scan_error_for_cdrdao_toc_flake() -> None:
    """The cdrdao read-toc temp-file FileNotFoundError (drive not ready)
    becomes plain language pointing at the Rescan disc button."""
    from whipper_gui.ui.main_window import _friendly_disc_scan_error

    raw = (
        "whipper failed: FileNotFoundError: [Errno 2] No such file or "
        "directory: '/tmp/tmp55rw20ax.cdrdao.read-toc.whipper.task'"
    )
    friendly = _friendly_disc_scan_error(raw)
    assert "Rescan disc" in friendly
    assert "table of contents" in friendly
    assert "FileNotFoundError" not in friendly  # no raw traceback text

    # Unrecognized errors pass through untouched — never hide information.
    assert _friendly_disc_scan_error("whipper failed: exit 1") == (
        "whipper failed: exit 1"
    )


def test_integration_offer_relocates_then_integrates(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """Accepting the first-run offer settles the AppImage into
    ~/Applications BEFORE integrating, so the menu entry never points into
    Downloads (real-user feedback, 2026-06-10)."""
    import whipper_gui.appimage_integration as ai

    window = teardown_threads(
        config=Config(appimage_integration_prompted=False), save_cfg=lambda c: None
    )
    downloaded = tmp_path / "Downloads" / "whipper-gui-x86_64.AppImage"
    moved = tmp_path / "Applications" / "whipper-gui-x86_64.AppImage"
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(ai, "appimage_path", lambda: downloaded)
    monkeypatch.setattr(ai, "is_integrated", lambda p: False)
    monkeypatch.setattr(
        ai,
        "relocate_to_applications",
        lambda p: (calls.append(("relocate", p)), moved)[1],
    )
    monkeypatch.setattr(
        ai, "integrate", lambda p, **k: (calls.append(("integrate", p)), None)[1]
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._maybe_offer_appimage_integration()

    # Relocate first, then integrate FROM THE NEW PATH.
    assert calls == [("relocate", downloaded), ("integrate", moved)]


def test_integration_offer_fires_when_integrated_but_unsettled(
    teardown_threads, monkeypatch, tmp_path
) -> None:
    """REGRESSION (real-user report 2026-06-10 #2): an update saved over the
    path the old menu entry pointed at IS 'integrated' (the Exec matches)
    but still lives in Downloads — the offer must fire so the file gets
    moved to ~/Applications and the icons remade."""
    import whipper_gui.appimage_integration as ai

    in_downloads = tmp_path / "Downloads" / "whipper-gui-x86_64.AppImage"
    in_downloads.parent.mkdir()
    in_downloads.write_bytes(b"x")
    monkeypatch.setattr(ai, "appimage_path", lambda: in_downloads)
    monkeypatch.setattr(ai, "is_integrated", lambda p: True)  # entry matches…
    # …but the file isn't settled (the real is_settled sees Downloads).
    moved = tmp_path / "Applications" / "whipper-gui-x86_64.AppImage"
    monkeypatch.setattr(ai, "relocate_to_applications", lambda p: moved)
    integrated: list[Path] = []
    monkeypatch.setattr(ai, "integrate", lambda p, **k: integrated.append(p))
    window = teardown_threads(config=Config(), save_cfg=lambda c: None)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._maybe_offer_appimage_integration()

    assert integrated == [moved]


# --- Post-rip cover art (backend-independent, 2026-06-13) -------------------


_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"x" * 16


class _RecordingMetaflac:
    """Duck-typed MetaflacAdapter stand-in that records embed calls."""

    def __init__(self) -> None:
        self.embedded: list[Path] = []

    def embed_picture(self, flac_path: Path, image_path: Path) -> None:
        self.embedded.append(flac_path)


def _cover_album(tmp_path: Path) -> tuple[Path, Path]:
    """An album folder with one FLAC and the rip log next to it."""
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "01 - Track.flac").write_bytes(b"flac")
    log_file = album / "Album.log"
    log_file.write_text("", encoding="utf-8")
    return album, log_file


def test_cyanrip_rip_finish_fetches_and_applies_cover_art(
    teardown_threads, tmp_path: Path
) -> None:
    """cyanrip never fetches art (the GUI bypasses its MB lookup), so the
    GUI fetches the front cover itself and embeds + saves it."""
    window = teardown_threads(
        config=Config(ripper_backend="cyanrip", cover_art="complete")
    )
    album, log_file = _cover_album(tmp_path)
    fake_metaflac = _RecordingMetaflac()
    window._metaflac = fake_metaflac
    urls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        urls.append(url)
        return _JPEG_BYTES

    window._cover_art_fetcher = fake_fetch
    window._current_release_id = "release-mbid"
    window._active_rip_params = _params(tmp_path, unknown=False)

    window._on_rip_finished(True, str(log_file))
    assert window._cover_art_thread is not None
    window._cover_art_thread.join(timeout=10)

    assert urls == ["https://coverartarchive.org/release/release-mbid/front"]
    assert (album / "cover.jpg").read_bytes() == _JPEG_BYTES
    assert fake_metaflac.embedded == [album / "01 - Track.flac"]


def test_whipper_known_rip_skips_gui_cover_art(
    teardown_threads, tmp_path: Path
) -> None:
    """whipper fetches art itself (--cover-art) for identified discs —
    the GUI must stay out of the way."""
    window = teardown_threads()  # default backend whipper, cover_art "embed"
    window._current_release_id = "release-mbid"
    window._active_rip_params = _params(tmp_path, unknown=False)

    window._on_rip_finished(True, "")

    assert window._cover_art_thread is None


def test_unknown_heal_rip_fetches_cover_art_when_release_is_known(
    teardown_threads, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The no-network heal re-rips as --unknown (whipper can't fetch art),
    but the GUI still knows the release — so it supplies the art too."""
    window = teardown_threads(config=Config(cover_art="embed"))
    monkeypatch.setattr(window, "run_unknown_post_processing", lambda out, picard: None)
    album, log_file = _cover_album(tmp_path)
    fake_metaflac = _RecordingMetaflac()
    window._metaflac = fake_metaflac
    window._cover_art_fetcher = lambda url: _JPEG_BYTES
    window._current_release_id = "release-mbid"
    window._active_rip_params = _params(tmp_path, unknown=True)

    window._on_rip_finished(True, str(log_file))
    assert window._cover_art_thread is not None
    window._cover_art_thread.join(timeout=10)

    assert fake_metaflac.embedded == [album / "01 - Track.flac"]
    # "embed" mode: the image was a temp file for metaflac, not kept.
    assert not (album / "cover.jpg").exists()


def test_unidentified_disc_skips_cover_art(teardown_threads, tmp_path: Path) -> None:
    """No release ID (MusicBrainz never matched) → nothing to look up."""
    window = teardown_threads(
        config=Config(ripper_backend="cyanrip", cover_art="complete")
    )
    window._current_release_id = ""
    window._active_rip_params = _params(tmp_path, unknown=False)

    window._on_rip_finished(True, "")

    assert window._cover_art_thread is None


def test_cover_art_off_skips_the_fetch(teardown_threads, tmp_path: Path) -> None:
    window = teardown_threads(config=Config(ripper_backend="cyanrip", cover_art=""))
    window._current_release_id = "release-mbid"
    window._active_rip_params = _params(tmp_path, unknown=False)

    window._on_rip_finished(True, "")

    assert window._cover_art_thread is None


def test_cover_art_outcome_lands_in_the_log_view(teardown_threads) -> None:
    window = teardown_threads()
    window._on_cover_art_done("Cover art: embedded in 14 track(s).")
    assert "Cover art: embedded in 14 track(s)." in (
        window._rip_progress._log_view.toPlainText()
    )


# --- Launch dependency check runs off the GUI thread (TASKS #11a) ----------


def test_run_dependency_check_async_probes_off_thread_and_applies(
    teardown_threads, qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launch-time dependency check probes on a worker thread, then
    applies the report on the GUI thread (show_summary=False). Proves the
    worker→GUI-thread-apply wiring + cleanup, without freezing the window."""
    # First-run offers marked done so the processEvents poll below can't fire
    # a deferred _maybe_offer_* singleShot into a modal dialog (blocks headless).
    window = teardown_threads(
        config=Config(
            host_setup_prompted=True,
            drive_setup_prompted=True,
            appimage_integration_prompted=True,
        )
    )
    applied: list[bool] = []
    monkeypatch.setattr(
        window,
        "_apply_dependency_report",
        lambda _mgr, _report, show_summary: applied.append(show_summary),
    )

    window.run_dependency_check_async()
    assert window._dep_check_thread is not None  # a worker thread was started

    deadline = time.monotonic() + 8.0
    while not applied and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)

    assert applied, "async dependency check never applied its report"
    assert applied[0] is False  # launch path never forces the summary popup
    assert window._dep_check_thread is None  # cleaned up after finishing


def test_run_dependency_check_async_is_single_flight(
    teardown_threads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second async check while one is running is a no-op (one at a time)."""
    window = teardown_threads(
        config=Config(host_setup_prompted=True, drive_setup_prompted=True)
    )
    window.run_dependency_check_async()
    first_thread = window._dep_check_thread
    window.run_dependency_check_async()  # must not start a second
    assert window._dep_check_thread is first_thread
