"""Tests for the AppImage build harness.

The actual AppImage build needs Linux + python-appimage and is the
domain of T32's smoke test. Here we just verify the recipe directory
has the structure python-appimage expects and that the build script
references the right files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build"
RECIPE_DIR = BUILD_DIR / "python-appimage"


def test_build_script_exists_and_is_executable() -> None:
    script = BUILD_DIR / "build_appimage.sh"
    assert script.is_file()
    # On POSIX, the executable bit must be set for `bash build/...` to
    # work without an explicit interpreter prefix.
    import os

    assert os.access(script, os.X_OK), f"{script} is not executable; run chmod +x"


# python-appimage globs the entrypoint as `entrypoint.*`, so it MUST carry
# an extension or it is silently ignored (the default AppRun then runs the
# bare interpreter — `--version` prints Python's version, not ours).
ENTRYPOINT = RECIPE_DIR / "entrypoint.sh"


def test_recipe_dir_has_required_files() -> None:
    expected = {"requirements.txt", "entrypoint.sh", "whipper-gui.desktop"}
    actual = {p.name for p in RECIPE_DIR.iterdir() if p.is_file()}
    missing = expected - actual
    assert not missing, f"recipe missing: {missing}"


def test_entrypoint_has_extension_for_glob() -> None:
    """python-appimage matches `entrypoint.*`; a bare `entrypoint` is ignored."""
    assert ENTRYPOINT.is_file()
    # Guard against re-introducing an extensionless entrypoint.
    assert not (RECIPE_DIR / "entrypoint").exists()


def test_entrypoint_is_executable() -> None:
    import os

    assert os.access(ENTRYPOINT, os.X_OK)


def test_entrypoint_invokes_whipper_gui_module() -> None:
    """The entrypoint must run `python -m whipper_gui`."""
    text = ENTRYPOINT.read_text()
    assert "whipper_gui" in text
    assert "-m" in text  # invoking as a module


def test_entrypoint_points_openssl_at_host_ca_bundle() -> None:
    """The bundled CPython has no CA certs, so the entrypoint must set
    SSL_CERT_FILE from the host bundle or MusicBrainz HTTPS lookups fail
    with CERTIFICATE_VERIFY_FAILED (real bug found in the first AppImage rip)."""
    text = ENTRYPOINT.read_text()
    assert "SSL_CERT_FILE" in text
    # Must reference at least the two mainstream layouts.
    assert "/etc/pki/tls/certs/ca-bundle.crt" in text  # Fedora/Bazzite
    assert "/etc/ssl/certs/ca-certificates.crt" in text  # Debian/Ubuntu


def test_desktop_file_has_correct_app_id() -> None:
    """The .desktop Exec/Icon fields must match the AppImage name."""
    text = (RECIPE_DIR / "whipper-gui.desktop").read_text()
    assert "[Desktop Entry]" in text
    assert "Exec=whipper-gui" in text
    assert "Icon=whipper-gui" in text
    assert "Type=Application" in text


def test_desktop_name_has_no_space() -> None:
    """python-appimage derives the (unquoted) output filename from Name=; a
    space splits the appimagetool command and the AppImage is never built."""
    for line in (RECIPE_DIR / "whipper-gui.desktop").read_text().splitlines():
        if line.startswith("Name="):
            assert " " not in line[len("Name=") :], (
                "desktop Name must not contain spaces"
            )
            break
    else:
        pytest.fail("no Name= line in .desktop")


def _requirement_lines() -> list[str]:
    lines = (RECIPE_DIR / "requirements.txt").read_text().splitlines()
    non_comment = [line.strip() for line in lines if not line.strip().startswith("#")]
    return [line for line in non_comment if line]


def test_requirements_request_local_whipper_gui_package() -> None:
    """The bare `whipper-gui` line is resolved to the local wheel via the
    PIP_FIND_LINKS the build script exports (a global `--find-links .` line
    cannot work: python-appimage installs each line from a temp dir)."""
    assert "whipper-gui" in _requirement_lines()
    script = (BUILD_DIR / "build_appimage.sh").read_text()
    assert "PIP_FIND_LINKS" in script


def test_requirements_have_no_shell_redirection_chars() -> None:
    """python-appimage runs each `pip install` through a shell, so `<`/`>` in
    a version specifier is read as a redirection and crashes the build."""
    for line in _requirement_lines():
        assert "<" not in line and ">" not in line, (
            f"requirement {line!r} uses < or > (use ~= instead)"
        )


def test_requirements_pins_match_dependencies_md() -> None:
    """Runtime dep pins in the recipe must match the source-of-truth.

    Expressed with `~=` (no shell-special chars) but equivalent to the
    pyproject.toml / DEPENDENCIES.md bounds:
      PySide6 ~=6.7  ==  >=6.7,<7.0     tomli-w ~=1.0  ==  >=1.0,<2.0
    """
    text = (RECIPE_DIR / "requirements.txt").read_text()
    assert "PySide6~=6.7" in text
    assert "musicbrainzngs==0.7.1" in text
    assert "tomli-w~=1.0" in text


# --- Self-update: zsync update-information (KDD-17b) -----------------------


def test_build_script_embeds_zsync_update_information() -> None:
    """The build re-packs with appimagetool -u so AppImageUpdate-compatible
    tools can delta-update from GitHub releases. The transport string must
    name this repo and the exact artifact the release uploads."""
    script = (BUILD_DIR / "build_appimage.sh").read_text(encoding="utf-8")
    assert "gh-releases-zsync|rmccann-hub|Whipper-GUI-Frontend---CD-Rip|" in script
    assert ".AppImage.zsync" in script
    assert '-u "$UPDATE_INFO"' in script
    # Falls back to python-appimage's cached appimagetool (no new host dep).
    # REGRESSION (v0.2.0): the cache dir is DOT-prefixed
    # (.appimagetool-<ver>.appdir/AppRun); a plain * glob missed it and the
    # embed silently skipped. The script must glob the dot-form explicitly.
    assert ".cache/python-appimage/bin" in script
    assert "/.appimagetool*/AppRun" in script


def test_release_workflow_ships_the_zsync_file() -> None:
    """release.yml installs zsyncmake (so the .zsync is produced) and uploads
    it in BOTH the create and re-upload branches, and the checksum step runs
    AFTER the build so the .sha256 covers the update-info-embedded file."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "apt-get install -y -q zsync" in workflow
    assert workflow.count("whipper-gui-x86_64.AppImage.zsync") >= 2
    # REGRESSION (v0.2.0): a missing .zsync must fail at a dedicated verify
    # step with a clear message, not as a cryptic `gh release upload` error
    # after which the release ends up with no assets at all.
    assert "Verify update artifacts" in workflow
    assert workflow.index("Verify update artifacts") < workflow.index("sha256sum")
    # Build (which embeds update info) must precede the checksum generation.
    assert workflow.index("build_appimage.sh") < workflow.index("sha256sum")
