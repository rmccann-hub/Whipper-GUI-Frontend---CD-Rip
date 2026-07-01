# SPDX-License-Identifier: GPL-3.0-only
"""The adaptive read-speed ladder — the pure decision logic behind the rip.

The goal (the maintainer's north star): behave like a careful EAC user with zero
terminal. **Start fast, and only slow down / re-read harder when a disc actually
needs it — quality can only go UP, never down.** A clean disc rips at full speed;
a marginal one is re-read at progressively slower speeds (which many drives read
more accurately) and, at the floor, with cyanrip's `-Z` re-rip-until-match.

This module is the *brain* only — pure, no Qt, no subprocess, **never raises**.
The rip worker calls :func:`next_step` after each pass to decide the next attempt,
and :func:`attempts_to_report` to record what each pass needed (honest reporting:
a disc that still can't read clean at the floor is FLAGGED, never papered over).

**Hardware-gated (see docs/ripper-engine-strategy.md §8 — flagged for the
Bazzite + Pioneer BDR-209D validation before this is treated as authoritative):**
  (a) whether cyanrip exposes a reliable per-track "unrecoverable read" signal we
      can trigger the step-down on (today we trigger on the log's ripping-error
      count — a whole-disc signal);
  (b) whether cyanrip can re-rip a *subset* of tracks at a new speed, or the whole
      disc must re-run (today we re-run the whole disc — safe, if slower);
  (c) whether the BDR-209D honours ``-S`` through the Linux/libcdio-paranoia
      stack at all (if not, the ladder degrades to plain re-reads — no regression).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# The read-speed rungs, fastest → slowest. 0 means "let the drive pick" (its
# maximum) and is the first, fastest rung — cyanrip omits ``-S`` entirely there.
# The remaining rungs are the classic EAC-style step-down (8× → 4× → 2×); many
# drives read a marginal disc more accurately slower. 2× is the FLOOR (the last
# rung): below it there's little accuracy to gain and a lot of time to lose.
DEFAULT_LADDER: tuple[int, ...] = (0, 8, 4, 2)
FLOOR_SPEED: int = DEFAULT_LADDER[-1]

# At the floor speed, if a disc STILL won't read clean, escalate cyanrip's `-Z N`
# (re-rip a track until N reads' checksums agree) instead of going slower. Start
# at 2 (two agreeing reads) and climb to this ceiling, then give up (and FLAG).
_Z_FLOOR: int = 2
MAX_SECURE_REREP: int = 3

# A hard backstop on total passes, independent of the ladder maths, so a bug can
# never spin a disc forever: ladder rungs + the -Z escalations, plus slack.
MAX_ATTEMPTS: int = 6


@dataclass(frozen=True)
class LadderStep:
    """The next rip attempt the ladder recommends after a pass with read errors."""

    speed: int  # 0 = drive default/max; else the ``-S`` value
    secure_rerip_matches: int  # cyanrip's ``-Z`` for this attempt (0 = off)
    reason: str  # human-readable why, for the log/report


@dataclass(frozen=True)
class SpeedAttempt:
    """A record of one completed rip pass — what it used and how it went.

    ``clean`` is True when the pass read without unrecoverable errors (the rip
    can stop). The escalation history is a list of these, so the report can show
    exactly which speed / ``-Z`` a disc needed — or that it never read clean.
    """

    attempt: int  # 1-based
    speed: int  # 0 = drive default/max
    secure_rerip_matches: int
    clean: bool


def next_step(
    *,
    current_speed: int,
    current_secure_rerip: int,
    ladder: tuple[int, ...] = DEFAULT_LADDER,
    max_secure_rerip: int = MAX_SECURE_REREP,
) -> LadderStep | None:
    """Given the pass that just failed, return the next attempt — or None to stop.

    Escalation order: step DOWN the speed ladder first (slower reads are often
    more accurate), and only once at the floor speed, escalate ``-Z`` (re-read
    until N passes agree). Returns None when both are exhausted — the caller then
    stops and FLAGS the disc as still-failing. Never raises: an unknown current
    speed is treated as the top rung so escalation still makes progress.
    """
    try:
        if not ladder:
            return None
        floor = ladder[-1]
        # Still room to slow down? Step to the next-slower rung, keeping -Z.
        if current_speed != floor:
            try:
                idx = ladder.index(current_speed)
            except ValueError:
                # Unknown speed → treat as the top rung so we still step toward
                # the floor rather than stalling.
                idx = 0
            if idx < len(ladder) - 1:
                nxt = ladder[idx + 1]
                return LadderStep(
                    speed=nxt,
                    secure_rerip_matches=current_secure_rerip,
                    reason=(
                        f"read errors — retrying at {_speed_label(nxt)} "
                        "(slower reads are often more accurate)"
                    ),
                )
        # At the floor speed: escalate -Z instead of going slower.
        next_z = max(current_secure_rerip + 1, _Z_FLOOR)
        if next_z <= max_secure_rerip:
            return LadderStep(
                speed=floor,
                secure_rerip_matches=next_z,
                reason=(
                    f"still failing at {_speed_label(floor)} — re-reading until "
                    f"{next_z} passes agree (-Z {next_z})"
                ),
            )
        return None
    except Exception:  # noqa: BLE001 — a policy helper must never crash the rip
        log.exception("read-speed ladder next_step failed; stopping escalation")
        return None


def _speed_label(speed: int) -> str:
    """Human label for a rung: 0 → 'max speed', else 'N×'."""
    return "max speed" if speed <= 0 else f"{speed}×"


def read_errors_present(rip_log: object) -> bool:
    """True if a parsed rip log shows unrecoverable read errors — the signal
    that a slower re-read might help.

    Pure and never raises (it drives an escalation decision from a best-effort
    parse). cyanrip normalises its finish line to ``health_status`` of
    "No errors occurred" (0 errors) or "N ripping errors"; a per-track failure
    also lands as an "error" in that track's status. A disc simply *not in
    AccurateRip* is NOT an error (nothing to re-read for) — this returns False
    for it, so the ladder never spins on a clean-but-unknown disc.
    """
    try:
        health = getattr(rip_log, "health_status", "") or ""
        if health and "no error" not in health.lower():
            return True
        for track in getattr(rip_log, "tracks", ()) or ():
            if "error" in (getattr(track, "status", "") or "").lower():
                return True
        return False
    except Exception:  # noqa: BLE001 — an escalation predicate must not crash
        log.exception("read_errors_present failed; assuming no errors")
        return False


def attempts_to_report(attempts: list[SpeedAttempt]) -> dict | None:
    """Summarize the escalation history for the JSON report. None if no attempts.

    Records every pass (speed + ``-Z`` + whether it read clean), the final
    settings, whether the ladder had to escalate at all, and — the honest bit —
    whether the disc was left ``unresolved`` (never read clean even at the floor).
    Never raises.
    """
    try:
        if not attempts:
            return None
        last = attempts[-1]
        return {
            "attempts": [
                {
                    "attempt": a.attempt,
                    "speed": a.speed,
                    "speed_label": _speed_label(a.speed),
                    "secure_rerip_matches": a.secure_rerip_matches,
                    "clean": a.clean,
                }
                for a in attempts
            ],
            "final_speed": last.speed,
            "final_speed_label": _speed_label(last.speed),
            "final_secure_rerip_matches": last.secure_rerip_matches,
            # Did we ever have to step down / re-read harder than the first pass?
            "escalated": len(attempts) > 1,
            # The honest flag: the disc never read clean, even at the floor.
            "unresolved": not last.clean,
        }
    except Exception:  # noqa: BLE001 — report helpers never crash a rip
        log.exception("read-speed ladder attempts_to_report failed")
        return None
