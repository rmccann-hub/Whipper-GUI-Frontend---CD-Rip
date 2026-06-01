"""Tests for whipper_gui.adapters.whipper_backend.

The adapter shells out to the real whipper binary in production, so
these tests mock subprocess and verify the adapter constructs the right
argv, parses output through the right parser, and surfaces errors
correctly.
"""

from __future__ import annotations

import signal
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
        self.pid: int = 424242  # cancel paths address the process GROUP
        self.terminated: bool = False
        self.killed: bool = False
        _FakePopen.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


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


def test_disc_info_salvages_track_count_from_failed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the "unable to retrieve disc metadata" failure, whipper has
    still printed the disc IDs and "N audio tracks" to stdout. The
    adapter parses that partial output so the GUI can show numbered
    blank rows for an unknown disc (T32)."""
    failed_output = (
        "CDDB disc id: d30e9010\n"
        "MusicBrainz disc id PKt4tUZ9zkm_5aEh6ButPQLlNs0-\n"
        "Disc duration: 01:02:08.026, 16 audio tracks\n"
        "CRITICAL:whipper.command.cd:unable to retrieve disc metadata, "
        "--unknown argument not passed\n"
    )
    monkeypatch.setattr(
        whipper_backend.subprocess, "run",
        lambda *a, **kw: _fail_run(stdout=failed_output),
    )

    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    info = impl.disc_info("/dev/sr0")

    assert info.cddb_disc_id == "d30e9010"
    assert info.musicbrainz_disc_id == "PKt4tUZ9zkm_5aEh6ButPQLlNs0-"
    assert info.num_tracks == 16


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


def _disable_mkdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """rip() creates the output + working dirs before launching. The argv-only
    tests below point output_dir at an absolute path like /music, which CI
    (non-root) can't create — and they don't care about real dirs anyway, so
    no-op the creation. (test_rip_creates_working_and_output_dirs uses a real
    writable tmp_path and is intentionally NOT patched.)"""
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)


def test_rip_builds_expected_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    _disable_mkdir(monkeypatch)

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
    _disable_mkdir(monkeypatch)
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
    _disable_mkdir(monkeypatch)
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
    _disable_mkdir(monkeypatch)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
    )
    assert "--cdr" not in _FakePopen.instances[0].argv


def _rip_argv(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> list[str]:
    """Run rip() with the given kwargs and return the captured argv."""
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _FakePopen)
    _disable_mkdir(monkeypatch)
    impl = WhipperHostExportedImpl(binary_path=Path("/x/whipper"))
    impl.rip(
        drive="/dev/sr0",
        release_id="x",
        output_dir=Path("/music"),
        track_template="t",
        disc_template="d",
        **kwargs,
    )
    return _FakePopen.instances[0].argv


def test_rip_max_retries_always_passed_with_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = _rip_argv(monkeypatch, max_retries=8)
    assert "--max-retries" in argv
    assert argv[argv.index("--max-retries") + 1] == "8"


def test_rip_cover_art_passed_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = _rip_argv(monkeypatch, cover_art="embed")
    assert argv[argv.index("--cover-art") + 1] == "embed"


def test_rip_cover_art_omitted_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "--cover-art" not in _rip_argv(monkeypatch, cover_art="")


def test_rip_overread_and_keep_going_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = _rip_argv(monkeypatch, force_overread=True, keep_going=True)
    assert "--force-overread" in argv
    assert "--keep-going" in argv


def test_rip_overread_and_keep_going_absent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = _rip_argv(monkeypatch)
    assert "--force-overread" not in argv
    assert "--keep-going" not in argv


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
    _disable_mkdir(monkeypatch)
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


def test_rip_handle_cancel_signals_group_terminate_then_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel must SIGTERM then (on timeout) SIGKILL the process GROUP, so
    cdparanoia — not just the whipper parent — dies and the drive stops."""
    sent: list[int] = []
    monkeypatch.setattr(whipper_backend.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        whipper_backend.os, "killpg", lambda pgid, sig: sent.append(sig)
    )

    class _SlowFakePopen(_FakePopen):
        def wait(self, timeout: float | None = None) -> int:
            if signal.SIGKILL not in sent:  # SIGTERM didn't take → time out
                raise subprocess.TimeoutExpired(cmd="whipper", timeout=5)
            self.returncode = -9
            return -9

    fake = _SlowFakePopen(argv=[])
    handle = RipHandle(process=fake)  # type: ignore[arg-type]

    code = handle.cancel(term_timeout=0.01)

    assert sent == [signal.SIGTERM, signal.SIGKILL]
    assert code == -9


def test_rip_handle_cancel_on_already_exited_process_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(whipper_backend.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        whipper_backend.os, "killpg", lambda pgid, sig: killed.append(sig)
    )
    fake = _FakePopen(argv=[])
    fake.returncode = 0
    handle = RipHandle(process=fake)  # type: ignore[arg-type]

    assert handle.cancel() == 0
    assert killed == []  # nothing signalled — it had already exited


# --- ABC discipline -------------------------------------------------------


def test_abstract_methods_block_instantiation() -> None:
    """WhipperBackend itself must not be instantiable."""
    with pytest.raises(TypeError):
        WhipperBackend()  # type: ignore[abstract]


# --- drive calibration (setup wizard) -------------------------------------


def _impl() -> WhipperHostExportedImpl:
    return WhipperHostExportedImpl(binary_path=Path("/x/whipper"))


class _SetupPopen:
    """Popen stand-in for the cancellable drive-setup runner.

    analyze_drive/find_offset go through `_run_setup_capture`, which uses
    Popen + communicate() (so the process can be SIGKILLed on cancel), not
    subprocess.run — hence these tests mock Popen.
    """

    output: str = ""
    rc: int = 0
    captured: list[list[str]] = []

    def __init__(self, argv: list[str], *args: Any, **kwargs: Any) -> None:
        self.argv = argv
        self.returncode = type(self).rc
        self.killed = False
        type(self).captured.append(argv)

    def communicate(self, timeout: float | None = None) -> tuple[str, None]:
        return type(self).output, None

    def poll(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _patch_setup_popen(
    monkeypatch: pytest.MonkeyPatch, output: str, rc: int = 0
) -> list[list[str]]:
    """Make whipper-setup subprocesses return `output`; return captured argv."""
    _SetupPopen.output = output
    _SetupPopen.rc = rc
    _SetupPopen.captured = []
    monkeypatch.setattr(whipper_backend.subprocess, "Popen", _SetupPopen)
    return _SetupPopen.captured


def test_analyze_drive_returns_true_and_passes_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_setup_popen(
        monkeypatch, "cdparanoia can defeat the audio cache on this drive\n"
    )
    assert _impl().analyze_drive("/dev/sr0") is True
    assert captured[0] == ["/x/whipper", "drive", "analyze", "-d", "/dev/sr0"]


def test_analyze_drive_returns_false_when_cache_cannot_be_defeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setup_popen(
        monkeypatch, "cdparanoia cannot defeat the audio cache on this drive\n"
    )
    assert _impl().analyze_drive("/dev/sr0") is False


def test_analyze_drive_raises_friendly_error_without_disc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setup_popen(
        monkeypatch, "cannot analyze the drive: is there a CD in it?\n"
    )
    with pytest.raises(WhipperError) as info:
        _impl().analyze_drive("/dev/sr0")
    assert "Insert a CD" in str(info.value)


def test_find_offset_parses_value_and_passes_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_setup_popen(monkeypatch, "\nRead offset of device is: 667.\n")
    assert _impl().find_offset("/dev/sr0") == 667
    assert captured[0] == ["/x/whipper", "offset", "find", "-d", "/dev/sr0"]


def test_find_offset_handles_negative_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setup_popen(monkeypatch, "Read offset of device is: -582.\n")
    assert _impl().find_offset("/dev/sr0") == -582


def test_find_offset_raises_actionable_error_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setup_popen(monkeypatch, "no offset found\n", rc=1)
    with pytest.raises(WhipperError) as info:
        _impl().find_offset("/dev/sr0")
    assert "AccurateRip" in str(info.value)


def test_cancel_setup_kills_running_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cancel_setup() must SIGKILL the whole setup process group (so the
    in-tree cdparanoia stops the drive, not just the parent)."""
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(whipper_backend.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        whipper_backend.os, "killpg", lambda pgid, sig: sent.append((pgid, sig))
    )
    impl = _impl()
    proc = _SetupPopen(["/x/whipper", "offset", "find"])
    proc.returncode = None  # type: ignore[assignment]  # still running
    proc.pid = 999  # type: ignore[attr-defined]
    impl._setup_proc = proc  # type: ignore[assignment]

    impl.cancel_setup()

    assert sent == [(999, signal.SIGKILL)]


def test_back_up_whipper_config_copies_when_present(tmp_path: Path) -> None:
    conf = tmp_path / "whipper.conf"
    conf.write_text("[main]\n", encoding="utf-8")

    backup = whipper_backend.back_up_whipper_config(conf)

    assert backup == tmp_path / "whipper.conf.bak"
    assert backup.read_text(encoding="utf-8") == "[main]\n"


def test_back_up_whipper_config_returns_none_when_absent(tmp_path: Path) -> None:
    assert whipper_backend.back_up_whipper_config(tmp_path / "nope.conf") is None


def test_rip_offset_override_passed_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = _rip_argv(monkeypatch, read_offset_override=667)
    assert argv[argv.index("--offset") + 1] == "667"


def test_rip_offset_override_absent_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "--offset" not in _rip_argv(monkeypatch, read_offset_override=None)
