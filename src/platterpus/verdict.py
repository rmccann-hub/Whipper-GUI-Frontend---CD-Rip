"""The single, pure AccurateRip "is this rip trustworthy?" verdict.

This lives in its own Qt-free module because **more than one surface needs the
same answer**: the results-pane verdict banner (`ui/rip_progress`), the
machine-readable rip report (`rip_report`), and any future consumer. Keeping it
here (not in a UI module) is the "one definition of verified" rule from
docs/ux-design-principles.md — duplicating it is exactly the bug that made the
disc-info panel disagree with the banner.

It builds on the per-track predicate in `parsers/rip_log`
(`track_accuraterip_verified`, confidence ≥ 1), so the whole-disc verdict and
the per-track checkmarks can never diverge.
"""

from __future__ import annotations

from platterpus.parsers.rip_log import track_accuraterip_verified


def accuraterip_verdict(rip_log: object) -> tuple[str, str]:
    """At-a-glance AccurateRip verdict: ``(message, level)``.

    ``level`` is "ok" (all audio tracks verified — bit-perfect against the
    shared AccurateRip database), "warn" (some but not all matched), or
    "neutral" (none matched — typically a disc nobody has submitted, e.g. a
    CD-R). An empty ``message`` means "show nothing" (no audio tracks parsed).

    Pure and never-raises (reads via ``getattr``) so it accepts both the
    whipper and cyanrip ``RipLog`` shapes and any partially-parsed log. The
    wording never claims more than AccurateRip returned — this is the trust
    headline, so it must be honest above all.
    """
    tracks = getattr(rip_log, "tracks", ()) or ()
    # Audio tracks only: a data track has neither a Copy CRC nor an AR result.
    audio = [
        t
        for t in tracks
        if getattr(t, "copy_crc", "")
        or getattr(t, "accuraterip_v1", None) is not None
        or getattr(t, "accuraterip_v2", None) is not None
    ]
    total = len(audio)
    if total == 0:
        return "", "neutral"
    verified = sum(1 for t in audio if track_accuraterip_verified(t))
    if verified == total:
        # Only count confidences of ACTUAL matches (>= 1, same as
        # accuraterip_is_match). A track can be verified on its v2 while its v1
        # is "present, no match" with confidence 0 — including that 0 would
        # render a misleading "confidence 0+" floor.
        confidences = [
            conf
            for t in audio
            for conf in (
                getattr(getattr(t, "accuraterip_v1", None), "confidence", None),
                getattr(getattr(t, "accuraterip_v2", None), "confidence", None),
            )
            if conf is not None and conf >= 1
        ]
        tail = f" (confidence {min(confidences)}+)" if confidences else ""
        return (
            f"✓ Bit-perfect: all {total} tracks verified against AccurateRip{tail}",
            "ok",
        )
    if verified > 0:
        return (
            f"⚠ {verified} of {total} tracks verified against AccurateRip — "
            "the rest aren't in the database or didn't match (see the table)",
            "warn",
        )
    # The leading "ⓘ" (like ✓/⚠ above) means the status is conveyed by symbol +
    # text, never colour alone — colour-blind and screen-reader users get the
    # same signal as the green/amber/grey tint (ux-design-principles.md #10).
    return (
        "ⓘ AccurateRip: no tracks matched the database — expected for a disc "
        "nobody has submitted (e.g. a burned CD-R); the per-track Copy CRCs "
        "below still prove a secure read",
        "neutral",
    )
