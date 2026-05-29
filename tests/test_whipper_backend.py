"""Tests for whipper_gui.adapters.whipper_backend.

The adapter shells out to the real whipper binary in production, so
these tests mock subprocess and verify the adapter constructs the right
argv, parses output through the right parser, and surfaces errors
correctly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whipper_gui.adapters import whipper_backend
from whipper_gui.adapters.whipper_backend import (
    RipHandle,
    WhipperBackend,
    WhipperError,
    WhipperHostExportedImpl,
)


# --- Fakes for subprocess --------------------------------------------------


def _ok_run(stdout: str = "", stderr: str = "") -> Any:
    """Return value mimicking a successful subprocess.run."""
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)


def _fail_run(stdout: str = "", stderr: str = "boom\n") -> Any:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=1)


class _FakePopen:
    """Stand-in for subprocess.Popen suitable for unit testing.

    Exposes the argv we were called with so tests can assert command
    construction, and a configurable .stdout iterator for log-line tests.
    """

    instances: list["_FakePopen"] = []

    def __init__(
        self, argv: list[str], *args: Any, **kwargs: Any
    ) -> None:
        self.argv: list[str] = argv
        self.popen_args: dict[str, Any] = kwargs
        self.stdout = iter(())  # type: ignore[assignment]
        self.returncode: int | None = None
        self.terminated: bool = False
        self.killed: bool = False
        _FakePopen.instances.append(self)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15  # POSIX SIGTERM convention

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9  # SIGKILL convention


@pytest.fixture(autouse=True)
def _reset_popen_instances() -> None:
    _FakePopen.instances.clear()


# --- list_drives ----------------------------------------------------------


def test_list_drives_invokes_drive_list_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_output = (
        "drive: /dev/sr0, vendor: PIONEER, model: BD-RW BDR-209D, release: 1.51\n"
        "       Configured read offset: 667\n"
        "       Can defeat audio cache: True\n"
    )

    captured_argv: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        captured_argv.append(argv)
        return _ok_run(stdout=sample_output)

    monkeypatch.setattr(whipper_backend.subprocess, "run", fake_run)

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    drives = impl.list_drives()

    assert captured_argv[0] == ["/x/whipper", "drive", "list"]
    assert len(drives) == 1
    assert drives[0].device == "/dev/sr0"
    assert drives[0].read_offset == 667


def test_list_drives_raises_whipper_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        whipper_backend.subprocess, "run",
        lambda *a, **kw: _fail_run(stderr="error: device busy\n"),
    )

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    with pytest.raises(WhipperError) as info:
        impl.list_drives()

    assert "device busy" in str(info.value)


def test_list_drives_raises_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_found(*a: Any, **kw: Any) -> Any:
        raise FileNotFoundError("/x/whipper")

    monkeypatch.setattr(whipper_backend.subprocess, "run", not_found)

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    with pytest.raises(WhipperError) as info:
        impl.list_drives()
    assert "not found" in str(info.value)


def test_list_drives_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="whipper", timeout=30)

    monkeypatch.setattr(whipper_backend.subprocess, "run", boom)

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    with pytest.raises(WhipperError) as info:
        impl.list_drives()
    assert "timed out" in str(info.value)


# --- disc_info ------------------------------------------------------------


def test_disc_info_passes_drive_flag_before_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = (
        "CDDB disc id: 12345678\n"
        "MusicBrainz disc id abc-def\n"
        "MusicBrainz lookup URL https://example/x\n"
    )
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> Any:
        captured.append(argv)
        return _ok_run(stdout=sample)

    monkeypatch.setattr(whipper_backend.subprocess, "run", fake_run)

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    info = impl.disc_info("/dev/sr0")

    # Whipper has no -d/--device flag for `cd info` — it auto-detects
    # the single drive. The argv MUST NOT include -d (caused real
    # "unrecognized arguments: -d" errors on the user's Bazzite test).
    assert captured[0] == ["/x/whipper", "cd", "info"]
    assert info.cddb_disc_id == "12345678"
    assert info.musicbrainz_disc_id == "abc-def"


def test_disc_info_returns_empty_for_disc_not_in_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whipper's `cd info` exits -1 with "unable to retrieve disc
    metadata" when the disc isn't in MusicBrainz/FreeDB. The adapter
    must treat this as "unknown disc" and return an empty DiscInfo, NOT
    raise — otherwise the GUI can't render anything for unknown discs."""
    failed_output = (
        "CRITICAL:whipper.command.cd:unable to retrieve disc metadata, "
        "--unknown argument not passed\n"
    )
    monkeypatch.setattr(
        whipper_backend.subprocess, "run",
        lambda *a, **kw: _fail_run(stderr=failed_output),
    )

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    info = impl.disc_info("/dev/sr0")

    # Empty DiscInfo — the GUI shows "not in MusicBrainz" status and
    # the user opens File → Rip as Unknown Album.
    assert info.cddb_disc_id == ""
    assert info.musicbrainz_disc_id == ""
    assert info.musicbrainz_submit_url == ""


def test_disc_info_still_raises_on_other_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures that aren't the "disc not in database" case must still
    surface as WhipperError so the GUI shows a real error message."""
    monkeypatch.setattr(
        whipper_backend.subprocess, "run",
        lambda *a, **kw: _fail_run(stderr="error: drive is empty\n"),
    )

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    with pytest.raises(WhipperError) as info:
        impl.disc_info("/dev/sr0")
    assert "drive is empty" in str(info.value)


# --- version --------------------------------------------------------------


def test_version_returns_trimmed_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        whipper_backend.subprocess, "run",
        lambda *a, **kw: _ok_run(stdout="whipper 0.10.0\n"),
    )

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    assert impl.version() == "whipper 0.10.0"


# --- rip (Popen) ----------------------------------------------------------


def test_rip_builds_expected_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)

    impl = WhipperHostExportedImpl(
        binary_path=Path("/x/whipper"),
        working_dir=Path("/tmp/work"),
    )
    handle = impl.rip(
        drive="/dev/sr0",
        release_id="abc-mbid",
        output_dir=Path("/music"),
        track_template="%A/%d/%t. %n",
        disc_template="%A/%d/%d",
        unknown=False,
    )

    assert isinstance(handle, RipHandle)
    argv = _FakePopen.instances[0].argv
    assert argv[0] == "/x/whipper"
    # Whipper has no -d/--device flag — it auto-detects the drive.
    # Multi-drive selection is P1 (see TASKS.md). For v1, the `drive`
    # parameter is accepted in the rip() signature but not forwarded.
    assert "-d" not in argv
    assert "cd" in argv and "rip" in argv
    assert "--release-id" in argv and "abc-mbid" in argv
    assert "--output-directory" in argv and "/music" in argv
    assert "--working-directory" in argv and "/tmp/work" in argv
    assert "--track-template" in argv and "%A/%d/%t. %n" in argv
    assert "--unknown" not in argv


def test_rip_unknown_flag_appended_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="unused",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
        unknown=True,
    )
    assert "--unknown" in _FakePopen.instances[0].argv


def test_rip_cdr_flag_appended_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cdr=True must add whipper's --cdr flag so burned discs rip.

    Real-hardware testing (T32) hit "inserted disc seems to be a CD-R,
    --cdr not passed" on a home-burned disc; this flag is the fix."""
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
        cdr=True,
    )
    assert "--cdr" in _FakePopen.instances[0].argv


def test_rip_cdr_flag_absent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
    )
    assert "--cdr" not in _FakePopen.instances[0].argv


def test_rip_creates_working_and_output_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """rip() must create the output + working dirs before launching.

    Whipper does a bare os.chdir() into --working-directory and crashes
    with FileNotFoundError if it doesn't exist (T32 on a fresh
    ~/.cache/whipper-gui)."""
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    out_dir = tmp_path / "music" / "rips"
    work_dir = tmp_path / "cache" / "whipper-gui"
    assert not out_dir.exists() and not work_dir.exists()

    impl = WhipperHostExportedImpl(
        binary_path=Path("/x/whipper"), working_dir=work_dir
    )
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=out_dir,
        track_template="t",
        disc_template="d",
    )

    assert out_dir.is_dir()
    assert work_dir.is_dir()


def test_rip_omits_working_directory_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
    )
    assert "--working-directory" not in _FakePopen.instances[0].argv


# --- RipHandle ------------------------------------------------------------


def test_rip_handle_yields_log_lines() -> None:
    fake = _FakePopen(argv=[], stdout=None)
    fake.stdout = iter(["one\n", "two\n", "three\n"])  # type: ignore[assignment]
    handle = RipHandle(process=fake)  # type: ignore[arg-type]

    assert list(handle.log_lines()) == ["one", "two", "three"]


def test_rip_handle_cancel_sends_terminate_then_kill_on_timeout() -> None:
    class _SlowFakePopen(_FakePopen):
        def wait(self, timeout: float | None = None) -> int:
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="whipper", timeout=5)
            return -9

    fake = _SlowFakePopen(argv=[])
    handle = RipHandle(process=fake)  # type: ignore[arg-type]

    code = handle.cancel(term_timeout=0.01)

    assert fake.terminated is True
    assert fake.killed is True
    assert code == -9


def test_rip_handle_cancel_on_already_exited_process_is_safe() -> None:
    fake = _FakePopen(argv=[])
    fake.returncode = 0
    handle = RipHandle(process=fake)  # type: ignore[arg-type]

    assert handle.cancel() == 0
    assert fake.terminated is False
    assert fake.killed is False


# --- ABC discipline -------------------------------------------------------


def test_abstract_methods_block_instantiation() -> None:
    """WhipperBackend itself must not be instantiable."""
    with pytest.raises(TypeError):
        WhipperBackend()  # type: ignore[abstract]
