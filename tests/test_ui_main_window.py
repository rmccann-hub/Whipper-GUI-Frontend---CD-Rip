"""Tests for whipper_gui.ui.main_window.

These are integration-flavored: we instantiate the real MainWindow with
fake backends and verify the high-level signal wiring and slot behavior.
We DON'T drive a real Qt event loop — tests poke slots directly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
from whipper_gui.drive_access import DriveAccessDiagnosis
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
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
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
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown disc (no MB ID) still shows numbered blank rows.

    whipper reports the track count even for a disc MusicBrainz can't
    identify; we render that many rows so the user sees the disc."""
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(num_tracks=16)  # no MB/CDDB id
    window = teardown_threads(backend=backend)
    prompted: list[bool] = []
    monkeypatch.setattr(
        window, "open_unknown_album_dialog",
        lambda: prompted.append(True) or False,
    )

    window._on_drive_changed("/dev/sr0")

    assert len(window._track_table.tracks()) == 16
    assert window._track_table.tracks()[0].number == 1
    assert window._track_table.tracks()[0].title == "Track 01"
    assert prompted == [True]  # unknown-album flow was offered


def test_zero_mb_results_shows_blank_track_rows(
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disc with an MB ID but no registered release also gets blank rows."""
    backend = _FakeBackend()
    backend.disc_info_return = DiscInfo(
        musicbrainz_disc_id="mb-id", num_tracks=12
    )
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
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.diagnose_drive_access",
        lambda **kw: _diag("permission", "sudo usermod -aG cdrom $USER"),
    )

    window._on_drives_unavailable()
    window._on_drives_unavailable()  # refresh again — must NOT re-pop

    assert len(shown) == 1


def test_drives_unavailable_quiet_when_not_actionable(
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.diagnose_drive_access",
        lambda **kw: _diag("no_device", None),
    )

    window._on_drives_unavailable()

    assert shown == []  # nothing the user can do → don't interrupt


def test_tools_diagnose_always_shows(
    teardown_threads, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = teardown_threads()
    shown: list[DriveAccessDiagnosis] = []
    monkeypatch.setattr(window, "_present_drive_diagnosis", shown.append)
    monkeypatch.setattr(
        "whipper_gui.ui.main_window.diagnose_drive_access",
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
        def log_lines(self): return iter(())
        def wait(self, timeout=None): return 0
        def cancel(self, term_timeout: float = 5.0): return -15

    backend.rip = lambda **kw: _StubHandle()  # type: ignore[assignment]
    window = teardown_threads(backend=backend)
    window._track_table._album_artist_edit.setText("jimmy2")
    window._track_table._album_title_edit.setText("for")

    from whipper_gui.workers.rip_worker import RipParameters
    window._on_rip_requested(RipParameters(
        drive="/dev/sr0", release_id="", output_dir=Path("/tmp/x"),
        track_template="literal-unknown", disc_template="literal-unknown",
        unknown=True,
    ))

    assert window._active_rip_params.track_template == "jimmy2/for/%t - Track %t"
    assert window._active_rip_params.disc_template == "jimmy2/for/for"
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.quit(); window._rip_thread.wait(2000)


def test_unknown_rip_folder_falls_back_when_album_blank(
    teardown_threads,
) -> None:
    backend = _FakeBackend()

    class _StubHandle:
        def log_lines(self): return iter(())
        def wait(self, timeout=None): return 0
        def cancel(self, term_timeout: float = 5.0): return -15

    backend.rip = lambda **kw: _StubHandle()  # type: ignore[assignment]
    window = teardown_threads(backend=backend)
    # album fields left blank
    from whipper_gui.workers.rip_worker import RipParameters
    window._on_rip_requested(RipParameters(
        drive="/dev/sr0", release_id="", output_dir=Path("/tmp/x"),
        track_template="t", disc_template="d", unknown=True,
    ))
    assert window._active_rip_params.track_template.startswith(
        "Unknown Artist/Unknown Album/"
    )
    if window._rip_thread is not None and window._rip_thread.isRunning():
        window._rip_thread.quit(); window._rip_thread.wait(2000)


def test_safe_path_segment() -> None:
    from whipper_gui.ui.main_window import _safe_path_segment
    assert _safe_path_segment("  jimmy2 ") == "jimmy2"
    assert _safe_path_segment("AC/DC") == "AC-DC"          # no stray subdir
    assert _safe_path_segment("50%off") == "50off"          # no whipper code
    assert _safe_path_segment("") == ""                      # blank → fallback


# --- First-run drive-setup offer + manual offset -------------------------


def test_should_offer_when_unconfigured_and_not_prompted(
    teardown_threads, monkeypatch
) -> None:
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: False)
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    assert window._should_offer_drive_setup() is True


def test_no_offer_when_already_prompted(teardown_threads, monkeypatch) -> None:
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: False)
    window = teardown_threads(config=Config(drive_setup_prompted=True))
    assert window._should_offer_drive_setup() is False


def test_no_offer_when_offset_already_configured(
    teardown_threads, monkeypatch
) -> None:
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: True)
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    assert window._should_offer_drive_setup() is False


def test_maybe_offer_records_prompt_and_launches_on_yes(
    teardown_threads, monkeypatch
) -> None:
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: False)
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
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: False)
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
    import whipper_gui.ui.main_window as mw
    monkeypatch.setattr(mw, "is_offset_configured", lambda _override: True)
    window = teardown_threads(config=Config(drive_setup_prompted=False))
    launched: list[bool] = []
    monkeypatch.setattr(window, "_on_drive_setup", lambda: launched.append(True))

    window._maybe_offer_drive_setup()

    assert launched == []
    assert window._config.drive_setup_prompted is False  # never even offered


def _patch_force_stop(monkeypatch) -> list[dict]:
    """Record force-stop calls instead of touching a real drive/container.

    We patch only ``drive_control.force_stop_drive`` (resolved at call time by
    ``_do_force_stop``) and let the real daemon thread run the fast fake — we
    deliberately do NOT replace ``threading.Thread`` globally, which could
    interfere with other threads spawned during the test.
    """
    import whipper_gui.ui.main_window as mw

    calls: list[dict] = []
    monkeypatch.setattr(
        mw.drive_control, "force_stop_drive",
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
    import whipper_gui.ui.main_window as mw

    calls: list[dict] = []
    monkeypatch.setattr(
        mw.drive_control, "eject_drive", lambda **kw: calls.append(kw)
    )
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


def test_force_stop_button_stops_timer_and_fires(
    teardown_threads, monkeypatch
) -> None:
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
