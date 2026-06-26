"""Tests for the cyanrip backend (Phase 1: argv builder + drive scan).

The actual cyanrip execution is hardware-gated; here we test the pure argv
construction and the sysfs-based drive scan with injected paths.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from whipper_gui.adapters.cyanrip_backend import (
    CyanripImpl,
    _escape_meta_value,
    _metadata_args,
    scheme_from_template,
)
from whipper_gui.adapters.whipper_backend import RipMetadata, TrackTag, WhipperError


def _patch_run(monkeypatch, *, stdout: str = "", stderr: str = "", raises=None):
    """Stub the subprocess.run that cyanrip's info/version probes use.

    cyanrip's `_run` now delegates to the shared `run_capture` helper, which
    lives in `whipper_backend` — so the call resolves `subprocess.run` through
    THAT module, and the patch must target it there (docs/testing.md §8: move
    the monkeypatch target to where the code now lives).
    """
    import whipper_gui.adapters.whipper_backend as mod

    def fake_run(argv, **kwargs):
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)


def _impl() -> CyanripImpl:
    return CyanripImpl(binary_path="cyanrip")


# --- rip argv builder -----------------------------------------------------


def test_rip_argv_known_disc_with_offset() -> None:
    argv = _impl()._build_rip_argv(
        "/dev/sr0",
        unknown=False,
        cover_art="embed",
        max_retries=5,
        read_offset_override=667,
    )
    assert argv[0] == "cyanrip"
    assert "-d" in argv and argv[argv.index("-d") + 1] == "/dev/sr0"
    # cyanrip applies the offset itself via -s (no whipper >587 bug).
    assert "-s" in argv and argv[argv.index("-s") + 1] == "667"
    assert "-o" in argv and argv[argv.index("-o") + 1] == "flac"
    assert "-r" in argv and argv[argv.index("-r") + 1] == "5"
    # MusicBrainz is ALWAYS off — the GUI feeds tags via -a/-t instead
    # (KDD-18 metadata model; keeps the rip offline + deterministic).
    assert "-N" in argv
    assert "-G" not in argv  # cover art wanted → keep embedding on


def test_rip_argv_unknown_disc_disables_musicbrainz() -> None:
    argv = _impl()._build_rip_argv(
        "/dev/sr0",
        unknown=True,
        cover_art="",
        max_retries=5,
        read_offset_override=667,
    )
    assert "-N" in argv  # unknown → disable MusicBrainz (no network needed)
    assert "-G" in argv  # no cover art → disable embedding


def test_rip_argv_omits_offset_when_none() -> None:
    argv = _impl()._build_rip_argv(
        "/dev/sr0",
        unknown=False,
        cover_art="embed",
        max_retries=5,
        read_offset_override=None,
    )
    assert "-s" not in argv


def test_rip_argv_always_disables_mb_and_feeds_gui_metadata() -> None:
    """KDD-18 metadata model: cyanrip never does its own MB lookup — the
    GUI's tags (release pick + user edits) are fed via -a/-t, offline."""
    meta = RipMetadata(
        album_artist="The Police",
        album_title="Greatest Hits",
        year="1992",
        genre="Rock",
        disc_number=1,
        total_discs=2,  # multi-disc → a "disc=n/total" tag is emitted
        tracks=(
            TrackTag(1, "Roxanne", "The Police", isrc="GBAAA0000001"),
            TrackTag(2, "Can't Stand Losing You"),
        ),
    )
    argv = _impl()._build_rip_argv(
        "/dev/sr0",
        unknown=False,
        cover_art="embed",
        max_retries=5,
        read_offset_override=667,
        release_id="1e477f68-c407-4eae-ad01-518528cedc2c",
        track_template="%A/%d/%t - %n",
        metadata=meta,
    )
    assert "-N" in argv  # even for a known disc
    album_arg = argv[argv.index("-a") + 1]
    assert "album=Greatest Hits" in album_arg
    assert "album_artist=The Police" in album_arg
    assert "date=1992" in album_arg
    assert "genre=Rock" in album_arg
    assert "disc=1/2" in album_arg
    assert "musicbrainz_albumid=1e477f68-c407-4eae-ad01-518528cedc2c" in album_arg
    track_args = [argv[i + 1] for i, a in enumerate(argv) if a == "-t"]
    assert track_args[0] == "1=title=Roxanne:artist=The Police:isrc=GBAAA0000001"
    # No artist/isrc → those pairs are skipped; the ' is escaped for
    # av_get_token (which treats bare ' as a quote character).
    assert track_args[1] == "2=title=Can\\'t Stand Losing You"
    # Templates: dir part → -D, file part → -F, tokens translated.
    assert argv[argv.index("-D") + 1] == "{album_artist}/{album}"
    assert argv[argv.index("-F") + 1] == "{track} - {title}"


def test_rip_argv_no_metadata_omits_tag_flags() -> None:
    argv = _impl()._build_rip_argv(
        "/dev/sr0",
        unknown=True,
        cover_art="",
        max_retries=5,
        read_offset_override=None,
        release_id="",
        track_template="",
        metadata=None,
    )
    assert "-N" in argv
    assert "-a" not in argv and "-t" not in argv
    assert "-D" not in argv and "-F" not in argv


# --- metadata escaping (cyanrip parses -a/-t with av_dict_parse_string) ----


def test_meta_value_escaping_makes_separators_safe() -> None:
    assert _escape_meta_value("Live: At The Met") == "Live\\: At The Met"
    assert _escape_meta_value("a=b") == "a\\=b"
    assert _escape_meta_value("back\\slash") == "back\\\\slash"
    assert _escape_meta_value("It's") == "It\\'s"
    assert _escape_meta_value("plain") == "plain"


def test_metadata_args_skip_empty_fields() -> None:
    # Single disc + no genre → only the album title; no disc=/genre= noise.
    args = _metadata_args(RipMetadata(album_title="X"), release_id="")
    assert args == ["-a", "album=X"]
    assert _metadata_args(None, release_id="") == []
    # A track with no title/artist/isrc contributes no -t at all.
    args = _metadata_args(RipMetadata(tracks=(TrackTag(3),)), release_id="")
    assert args == []


# --- whipper template → cyanrip scheme --------------------------------------


def test_scheme_translates_default_known_template() -> None:
    assert (
        scheme_from_template("%t - %n - %d - %A - %y")
        == "{track} - {title} - {album} - {album_artist} - {date}"
    )


def test_scheme_keeps_literals_and_unknown_tokens() -> None:
    # The unknown-disc template is all literals + %t; literals pass through.
    assert (
        scheme_from_template("Unknown Artist/Unknown Album/%t - Track %t")
        == "Unknown Artist/Unknown Album/{track} - Track {track}"
    )
    # An unmapped token stays visible rather than vanishing.
    assert scheme_from_template("%X - %n") == "%X - {title}"
    # A trailing lone % can't form a token; kept as-is.
    assert scheme_from_template("100%") == "100%"


def test_scheme_neutralizes_literal_braces() -> None:
    # {…} is cyanrip's substitution syntax — stray braces in a user template
    # must not be parsed as (missing) tag keys.
    assert scheme_from_template("{weird} %n") == "(weird) {title}"


# --- drive scan -----------------------------------------------------------


def test_list_drives_scans_dev_and_sysfs(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "sr0").write_bytes(b"")
    (dev / "sda").write_bytes(b"")  # not optical — must be ignored
    sysblk = tmp_path / "sys-block"
    info = sysblk / "sr0" / "device"
    info.mkdir(parents=True)
    (info / "vendor").write_text("PIONEER\n")
    (info / "model").write_text("BD-RW   BDR-209D\n")
    (info / "rev").write_text("1.51\n")

    impl = CyanripImpl(dev_root=dev, sys_block=sysblk)
    drives = impl.list_drives()

    assert len(drives) == 1
    d = drives[0]
    assert d.device == str(dev / "sr0")
    assert d.vendor == "PIONEER"
    assert d.model == "BD-RW   BDR-209D"
    assert d.release == "1.51"


def test_list_drives_empty_when_no_optical(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    impl = CyanripImpl(dev_root=dev, sys_block=tmp_path / "sys")
    assert impl.list_drives() == []


def test_list_drives_tolerates_missing_sysfs(tmp_path: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    (dev / "sr0").write_bytes(b"")
    impl = CyanripImpl(dev_root=dev, sys_block=tmp_path / "nope")
    drives = impl.list_drives()
    assert len(drives) == 1
    assert drives[0].vendor == ""  # sysfs absent → blank, no crash


def test_list_drives_degrades_on_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scanning /dev can raise OSError (e.g. a permission/IO error); the scan
    must degrade to an empty list, never propagate."""
    impl = CyanripImpl(dev_root=Path("/dev"))

    def boom(self: Path, pattern: str):
        raise OSError("I/O error")

    monkeypatch.setattr(type(impl._dev_root), "glob", boom)
    assert impl.list_drives() == []


# --- disc_info (runs `cyanrip -I -N` and parses the report) ---------------


def test_disc_info_runs_info_only_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """disc_info must use info-only mode (-I) with MusicBrainz disabled (-N)
    — identification is local; the GUI does its own MB lookup — and pass the
    selected device."""
    # cyanrip's `_run` delegates to the shared run_capture in whipper_backend,
    # so the subprocess.run patch targets that module (see _patch_run).
    import whipper_gui.adapters.whipper_backend as mod

    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Disc tracks:    16\n"
                "DiscID:         xA2hjkk0Jl0gKKtIdYuTje4JTXY-\n"
                "CDDB ID:        c50a780f\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    info = _impl().disc_info("/dev/sr0")

    argv = seen[0]
    assert "-I" in argv and "-N" in argv
    assert argv[argv.index("-d") + 1] == "/dev/sr0"
    assert info.musicbrainz_disc_id == "xA2hjkk0Jl0gKKtIdYuTje4JTXY-"
    assert info.cddb_disc_id == "c50a780f"
    assert info.num_tracks == 16


def test_disc_info_error_output_degrades_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from whipper_gui.parsers.cd_info import DiscInfo

    _patch_run(monkeypatch, stdout="Unable to read disc TOC!\n")
    assert _impl().disc_info("/dev/sr0") == DiscInfo()


def test_disc_info_raises_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run(monkeypatch, raises=FileNotFoundError("cyanrip"))
    with pytest.raises(WhipperError, match="not found"):
        _impl().disc_info("/dev/sr0")


# --- version / find_offset (subprocess stubbed) ---------------------------


def test_version_returns_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, stdout="cyanrip 0.9.3.1\n")
    assert _impl().version() == "cyanrip 0.9.3.1"


def test_does_not_self_verify_encode() -> None:
    # cyanrip (FFmpeg) has no decode-verify pass, so the GUI runs a post-rip
    # check; it inherits the ABC default.
    assert _impl().self_verifies_encode() is False


def test_produces_max_compression_flac_true() -> None:
    # cyanrip drives libavcodec at the maximum FLAC compression already, so a
    # post-rip `flac -8` re-compress would gain nothing — the GUI skips it.
    assert _impl().produces_max_compression_flac() is True


def test_native_output_formats_includes_wav_and_mp3() -> None:
    # cyanrip CAN emit these natively via `-o`. This stays a reserved capability
    # seam (KDD-22) — the shipped feature transcodes from FLAC for both backends.
    fmts = _impl().native_output_formats()
    assert {"flac", "wav", "mp3", "wavpack"} <= fmts


def test_find_offset_parses_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, stdout="Detected drive offset: 667\n")
    assert _impl().find_offset("/dev/sr0") == 667


def test_find_offset_raises_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, stdout="no offset here")
    with pytest.raises(WhipperError):
        _impl().find_offset("/dev/sr0")


def test_run_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, raises=FileNotFoundError("cyanrip"))
    with pytest.raises(WhipperError, match="not found"):
        _impl().version()
