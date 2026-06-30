"""Tests for platterpus.naming — the file-naming presets + preview renderer."""

from __future__ import annotations

import pytest

from platterpus import naming


def test_default_preset_is_clean_artist_album_track_title() -> None:
    # The recommended default must be the clean layout, not the old cluttered
    # one that repeated album/artist and trailed the date.
    assert naming.DEFAULT_PRESET is naming.PRESETS[0]
    assert naming.DEFAULT_PRESET.track_template == "%A/%d/%t - %n"


def test_preset_for_templates_matches_and_rejects() -> None:
    p = naming.DEFAULT_PRESET
    assert naming.preset_for_templates(p.track_template, p.disc_template) is p
    # A hand-edited template matches no preset → Custom (None).
    assert naming.preset_for_templates("%A/%n", "%A/%d/%d") is None


def test_render_preview_clean_template() -> None:
    out = naming.render_preview("%A/%d/%t - %n", naming.SAMPLE_EASY)
    assert out == "Led Zeppelin/Led Zeppelin IV/01 - Black Dog.flac"


def test_render_preview_zero_pads_track_to_disc_width() -> None:
    # 15-track disc → 2-digit width; track 3 → "03".
    out = naming.render_preview("%t", naming.SAMPLE_STRESS)
    assert out == "03.flac"


def test_render_preview_sanitises_colon_in_value_not_separator() -> None:
    # A ":" inside the album value becomes cyanrip's "∶"; the template's own
    # "/" stays a real path separator.
    out = naming.render_preview("%A/%d", naming.SAMPLE_STRESS)
    assert "Riding with the King∶ Deluxe Edition" in out
    assert ":" not in out
    # Two real separators (one from the template, plus the .flac has none).
    assert out.count("/") == 1


def test_render_preview_year_token_is_full_date_today() -> None:
    # Documented caveat: %y resolves to the full date, not a bare year.
    out = naming.render_preview("%d (%y)", naming.SAMPLE_EASY)
    assert "(1971-11-08)" in out


def test_render_preview_compilation_uses_track_artist() -> None:
    out = naming.render_preview("%t - %a - %n", naming.SAMPLE_STRESS)
    assert "Eric Clapton feat. B.B. King" in out


@pytest.mark.parametrize(
    "template",
    ["", "%", "%%", "%z", "%A/%z/%", "no codes at all", "%t%n%d%a%A%y"],
)
def test_render_preview_never_raises(template: str) -> None:
    # It backs a live preview as the user types — it must never raise, on any
    # input, and always end in .flac.
    out = naming.render_preview(template, naming.SAMPLE_EASY)
    assert out.endswith(".flac")


def test_render_preview_literal_percent() -> None:
    assert naming.render_preview("100%%", naming.SAMPLE_EASY) == "100%.flac"


def test_render_preview_unknown_token_passes_through() -> None:
    # An unknown %z stays visible (so a typo is obvious), rather than vanishing.
    assert naming.render_preview("%z", naming.SAMPLE_EASY) == "%z.flac"


def test_every_preset_renders_for_both_samples() -> None:
    for preset in naming.PRESETS:
        for sample in (naming.SAMPLE_EASY, naming.SAMPLE_STRESS):
            out = naming.render_preview(preset.track_template, sample)
            assert out.endswith(".flac")
            assert "%" not in out  # every token in a shipped preset resolves


def test_custom_label_is_not_a_preset_key() -> None:
    # The Custom sentinel must never collide with a real preset (else selecting
    # it would overwrite the user's hand-tuned templates).
    assert all(p.label != naming.CUSTOM_LABEL for p in naming.PRESETS)
