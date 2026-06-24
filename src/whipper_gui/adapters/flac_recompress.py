# SPDX-License-Identifier: GPL-3.0-only
"""Optional post-rip FLAC re-compression to the maximum level.

whipper encodes FLAC at the tool default (`-5`); this re-encodes each output FLAC
at `-8 -e -p` (flac's `--best` plus exhaustive model + coefficient search) to
shrink the files as far as flac can. It is **lossless and `--verify`'d**, so the
audio is provably bit-identical to before, and `flac` **preserves all metadata**
(Vorbis tags, embedded cover art, cuesheet) when it re-encodes a FLAC input — so
the tags whipper wrote and any art the GUI embedded survive.

Opt-in (default off) and pointless for backends that already max compression
(cyanrip), which the GUI skips. Each file is re-encoded to a sibling temp file and
then **atomically swapped in**, so a failure (or a crash) leaves the original
untouched. Best-effort; **never raises**.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_FLAC_BINARY: str = "flac"

# `-8` is flac's maximum compression *preset* (a.k.a. `--best` /
# `--compression-level-8`); per the xiph spec it expands to
# `-l 12 -b 4096 -m -r 6 -A "subdivide_tukey(3)"` (flags verified current
# against xiph.org/flac/documentation_tools_flac.html, 2026-06-23). Compression
# level is purely a file-size knob — every level is lossless, and `--verify`
# proves the decoded audio is bit-identical regardless of level, so the priority
# (bit-perfect) holds no matter what and the smaller file is the bonus.
#
# WHY THIS IS OPT-IN / OFF BY DEFAULT (the real reason, not just "modest gain"):
# higher compression raises the LPC prediction order — the `-l` setting, which
# the decoder must apply per sample. whipper's default is `-5` (`-l 8`); `-8` is
# `-l 12`. A higher order = more multiply-accumulates per sample to DECODE, so a
# `-8` file costs a little more CPU/battery to play back. Historically (the ~2015
# logic) this mattered on low-power portable players; on modern phones/desktops
# it's largely negligible, but it's a real reason a library aimed at mobile
# playback might prefer to leave files at whipper's `-5`. Both `-5` and `-8` stay
# inside the FLAC "Subset" (max LPC order 12 at <=48kHz), so this is a decode-
# *effort* difference, never a hardware-compatibility one. Net: the smaller file
# trades a touch of playback cost — hence opt-in, with whipper's `-5` the safe,
# mobile-friendly default.
#
# We DO add the two further-but-still-lossless options the docs list —
# `-e/--exhaustive-model-search` and `-p/--qlp-coeff-precision-search`, both
# flagged "(expensive!)". The maintainer is fine trading encode time for size
# (2026-06-23), and crucially these keep `-l` at 12, so they squeeze a bit more
# out at the cost of (much) slower *encoding* only — they add **no decode cost**,
# which is the dimension that matters for playback. The gain over plain `-8` is
# small (typically well under 1%), but it's free in every dimension we care about
# (still lossless, still `--verify`'d, no extra playback cost), so when a user has
# opted in to re-compressing at all, we go all the way. To drop back to the plain
# `-8` preset, set `_EXTRA_FLAGS = ()` — nothing else changes.
_LEVEL: str = "-8"
_EXTRA_FLAGS: tuple[str, ...] = ("-e", "-p")
# A full re-encode is heavier than `--test`, and `-e -p` make it heavier still;
# give each file a generous bound (a long track on slow hardware can take a while
# under exhaustive search). The maintainer accepts the encode time.
_TIMEOUT_S: float = 600.0

Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class RecompressResult:
    """Outcome of re-compressing a set of FLAC files.

    ``reencoded`` is how many were rewritten; ``failures`` lists paths that could
    not be re-encoded (left untouched); ``error`` is set (rest empty) when the
    step could not run at all (e.g. ``flac`` missing). ``ok`` is True only when it
    ran and every file was rewritten.
    """

    reencoded: int = 0
    failures: tuple[Path, ...] = ()
    error: str = ""

    @property
    def ran(self) -> bool:
        return not self.error

    @property
    def ok(self) -> bool:
        return self.ran and not self.failures


def _default_runner(argv: list[str]) -> int:
    proc = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        timeout=_TIMEOUT_S,
    )
    return proc.returncode


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def recompress_flac_files(
    paths: Sequence[Path],
    *,
    binary: str = _FLAC_BINARY,
    runner: Runner | None = None,
) -> RecompressResult:
    """Re-encode each FLAC at ``-8`` with verify; return a :class:`RecompressResult`.

    Never raises. A missing ``flac`` binary (or any failure to run it) aborts with
    ``error`` set, leaving every file untouched. A per-file failure leaves that
    original in place (the temp is discarded, never swapped in). On success each
    file is replaced atomically (``os.replace`` of a sibling temp), so the rip is
    never left with a half-written FLAC.
    """
    run = runner or _default_runner
    failures: list[Path] = []
    reencoded = 0
    for path in paths:
        tmp = path.with_name(path.name + ".recompress.tmp")
        argv = [
            binary,
            _LEVEL,
            *_EXTRA_FLAGS,
            "--verify",
            "--silent",
            "-f",
            "-o",
            str(tmp),
            str(path),
        ]
        try:
            rc = run(argv)
        except FileNotFoundError:
            return RecompressResult(
                reencoded=reencoded,
                error=f"'{binary}' not found — cannot re-compress FLACs",
            )
        except subprocess.TimeoutExpired:
            log.warning("flac re-encode timed out on %s", path)
            _safe_unlink(tmp)
            failures.append(path)
            continue
        except OSError as exc:
            return RecompressResult(
                reencoded=reencoded, error=f"could not run {binary}: {exc}"
            )
        if rc != 0 or not tmp.exists():
            _safe_unlink(tmp)
            failures.append(path)
            continue
        try:
            os.replace(tmp, path)  # atomic swap-in (same directory)
        except OSError as exc:
            log.warning("could not swap in re-compressed %s: %s", path, exc)
            _safe_unlink(tmp)
            failures.append(path)
            continue
        reencoded += 1
    return RecompressResult(reencoded=reencoded, failures=tuple(failures))
