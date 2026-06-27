"""Pure helper functions for the main window.

These are deliberately free functions, not methods: they take plain
inputs and return plain outputs with no dependence on the window's
widgets or Qt state, which makes them trivially unit-testable and keeps
``main_window.py`` focused on wiring. Extracted from ``main_window`` as
part of the 2026-06-13 modularization (the window had grown into a
1700-line god-object); ``main_window`` re-exports these names so existing
imports keep working.

Future contributors: any new "transform a string / summarize a parsed
object" logic for the main window belongs here, not as a method on
``MainWindow``. If a helper starts needing widget state, that's a sign it
should be a method instead.
"""

from __future__ import annotations


def safe_path_segment(value: str) -> str:
    """Make a user string safe to drop literally into a whipper template.

    Strips whitespace, turns ``/`` into ``-`` (it'd create stray subdirs),
    and drops ``%`` (whipper treats it as a format code). Returns ``""`` for
    blank input so callers can fall back to an "Unknown …" placeholder.
    """
    return (value or "").strip().replace("/", "-").replace("%", "")


def friendly_disc_scan_error(error_text: str) -> str:
    """Turn known disc-scan failures into plain language with a next step.

    The headline case (real-user report, 2026-06-10): whipper has cdrdao
    read the disc's table of contents into a temp file; when the drive
    isn't ready yet (disc still spinning up, or scanned the instant it was
    inserted) cdrdao produces nothing and whipper trips over the missing
    file — "FileNotFoundError: ... .cdrdao.read-toc.whipper.task". A retry
    almost always succeeds, so point at the Rescan disc button instead of
    showing a raw traceback line.

    Future contributors: add new ``if <signature>: return <plain message>``
    branches here as real-user reports surface other recoverable scan
    failures. Always fall through to the raw text for anything unrecognized
    — never hide information the user might need to report a bug.
    """
    if "read-toc" in error_text and (
        "FileNotFoundError" in error_text or "No such file" in error_text
    ):
        return (
            "The drive couldn't read the disc's table of contents — this "
            "usually means the disc wasn't ready yet (still spinning up). "
            "Click “Rescan disc” to try again."
        )
    # Cold-container start (real-user report, 2026-06-27): the FIRST whipper
    # call of a session has to start the Distrobox container, which can take
    # longer than the timeout. The timeouts were raised to budget for it, but
    # if one is still hit a retry runs against the now-warm container and
    # almost always succeeds — so point at Rescan rather than the raw text.
    if "timed out" in error_text:
        return (
            "Reading the disc took too long — the first scan after opening "
            "the app has to start the ripping container, which can be slow. "
            "Click “Rescan disc” to try again (it’s much faster the second time)."
        )
    return error_text


def fidelity_summary(rip_log: object) -> str:
    """One-line rip-quality verdict for the status label.

    whipper rips each track twice and records a Test CRC and Copy CRC; a
    match means the two independent reads were bit-identical (a secure,
    archival-quality rip). This surfaces that confidence directly so the
    user doesn't have to open the log to confirm fidelity — addressing the
    "I can't confirm fidelity" feedback. AccurateRip is reported only when
    it actually matched, since it's "not in database" for any disc nobody
    has submitted (e.g. CD-Rs).

    Takes ``object`` and reads fields via ``getattr`` defensively because it
    must accept both the whipper and cyanrip ``RipLog`` shapes (and never
    raise on a partially-parsed log). Future contributors adding a third
    backend: give its log a ``log_creator`` prefix and branch on it here,
    wording the verdict around what that ripper actually verifies — don't
    claim a Test/Copy match a ripper didn't perform.
    """
    tracks = getattr(rip_log, "tracks", ()) or ()
    total = len(tracks)
    if total == 0:
        return "Done."
    # cyanrip's verification model differs from whipper's: one EAC CRC per
    # track plus a paranoia error count, not a test+copy dual read. Word
    # the verdict to match what was actually checked.
    if str(getattr(rip_log, "log_creator", "")).startswith("cyanrip"):
        clean = sum(
            1 for t in tracks if getattr(t, "status", "") == "ripped successfully"
        )
        no_errors = getattr(rip_log, "health_status", "") == "No errors occurred"
        if clean == total and no_errors:
            summary = f"Done — all {total} tracks ripped cleanly, no read errors."
        else:
            summary = (
                f"Done — {clean}/{total} tracks ripped cleanly; "
                f"check the log for the rest."
            )
        ar = getattr(rip_log, "accuraterip_summary", "") or ""
        if ar and not ar.startswith("0/"):
            summary += f" AccurateRip: {ar}."
        return summary
    verified = sum(
        1
        for t in tracks
        if getattr(t, "test_crc", "")
        and getattr(t, "test_crc", "") == getattr(t, "copy_crc", "")
    )
    if verified == total:
        summary = f"Done — all {total} tracks verified, Test/Copy CRCs match."
    else:
        summary = (
            f"Done — {verified}/{total} tracks CRC-verified; "
            f"check the log for the rest."
        )
    # Append AccurateRip confirmation only when at least one track matched.
    ar = (getattr(rip_log, "accuraterip_summary", "") or "").lower()
    if "exact match" in ar or "found" in ar:
        summary += " AccurateRip confirmed."
    return summary
