# SPDX-License-Identifier: GPL-3.0-only
"""Post-rip transcode of the rip's FLAC output to MP3, WavPack, or WAV.

Both backends always rip to FLAC (whipper is FLAC-only; the cyanrip path is
invoked with ``-o flac``). When the user picks a different output format, the GUI
keeps that FLAC as the archival master and **derives** the chosen format from it
with a post-rip ffmpeg re-encode — this adapter. One uniform path for both
backends means the MP3 is always best-practice VBR (cyanrip's *native* MP3 is
only CBR), and there is always a lossless FLAC master (the north star).
See ``docs/mp3-wav-support.md``.

**The FLAC stays the archival master.** We write a NEW sibling file next to each
FLAC (``01 - x.flac`` → ``01 - x.mp3``/``.wv``/``.wav``) and never touch the
FLAC. The derived file is additive.

Per format (facts verified against upstream docs, docs/mp3-wav-support.md §3):
  * **MP3** (lossy) — libmp3lame VBR ``-q:a N`` (== lame ``-V N``; N=0 ≈ the
    highest VBR, ~245 kbps), joint-stereo left on (ffmpeg default). The LAME
    ``-q4`` noise-shaping bug is CBR/ABR-only, so VBR is unaffected. Tags **and**
    embedded cover art carry over (``-map_metadata 0`` + copying the
    attached-picture stream → ID3 APIC).
  * **WavPack** (``.wv``, lossless) — ``-c:a wavpack`` (lossless by default;
    verified bit-identical PCM round-trip). Text tags carry over to APEv2
    (``-map_metadata 0``), but ffmpeg's WavPack muxer can hold **only the audio
    stream** ("This muxer only supports a single WavPack stream"), so the
    embedded cover is dropped here — the front cover still lands in the album
    folder as ``cover.<ext>`` via the cover-art step (the universal image
    guarantee). Embedding art *inside* the ``.wv`` needs the standalone
    ``wavpack`` tool (APEv2 binary tag) — a documented future enhancement.
  * **WAV** — 16-bit LE PCM (CD format). RIFF carries **no** rich tags or cover
    art; the GUI warns about that separately (WavPack is the lossless-with-tags
    answer instead).

Each file is encoded to a sibling temp and then **atomically renamed in**, so a
failure (or a crash) never leaves a half-written output. Best-effort; **never
raises**.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_FFMPEG_BINARY: str = "ffmpeg"
# Formats this adapter knows how to produce, mapped to their file extension.
# Anything else (e.g. "flac") is a no-op — the rip already produced the FLAC,
# there's nothing to transcode. Note WavPack's extension is ".wv", not
# "wavpack", so we can't derive the suffix from the format name alone.
_FORMAT_EXT: dict[str, str] = {"mp3": "mp3", "wavpack": "wv", "wav": "wav"}
# Public so the GUI can tell whether a chosen output_format needs a transcode
# (anything here) or is the native rip format ("flac" → no-op).
SUPPORTED_FORMATS: frozenset[str] = frozenset(_FORMAT_EXT)
# Transcoding one CD track is quick (seconds), but give a generous per-file
# bound for slow hardware / long tracks.
_TIMEOUT_S: float = 300.0

# A runner takes the ffmpeg argv and returns its exit code (injectable so tests
# run without a real ffmpeg).
Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class TranscodeResult:
    """Outcome of transcoding a set of FLAC files to one target format.

    ``transcoded`` is how many sibling files were written; ``failures`` lists
    source paths that could not be transcoded (their FLAC is untouched and no
    output was left behind); ``error`` is set (rest empty) when the step could
    not run at all (e.g. ``ffmpeg`` missing, or an unsupported format). ``ok``
    is True only when it ran and every file was transcoded.
    """

    transcoded: int = 0
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


def _build_argv(
    binary: str, src: Path, tmp: Path, fmt: str, mp3_vbr_quality: int
) -> list[str]:
    """Build the ffmpeg argv for ``src`` → ``tmp`` in ``fmt``.

    ``tmp`` has a non-format extension (``.transcode.tmp``), so we always pass
    ``-f`` to force the container — ffmpeg can't infer it from the name.
    """
    base = [binary, "-nostdin", "-y", "-i", str(src)]
    if fmt == "mp3":
        return base + [
            "-map_metadata",
            "0",  # carry the Vorbis tags into ID3
            "-id3v2_version",
            "3",  # widest player compatibility
            "-c:v",
            "copy",  # copy the embedded cover (attached pic) → APIC
            "-c:a",
            "libmp3lame",
            "-q:a",
            str(mp3_vbr_quality),  # VBR; == lame -V N
            "-f",
            "mp3",
            str(tmp),
        ]
    if fmt == "wavpack":
        # WavPack: lossless by default. `-map 0:a` = audio only — ffmpeg's
        # WavPack muxer rejects more than one stream, so the embedded cover
        # can't ride along (the folder cover.<ext> covers the image). Text
        # tags carry over to APEv2 via -map_metadata.
        return base + [
            "-map_metadata",
            "0",
            "-map",
            "0:a",
            "-c:a",
            "wavpack",
            "-f",
            "wavpack",
            str(tmp),
        ]
    # WAV: 16-bit LE PCM (CD format). `-map 0:a` = audio only — explicitly
    # excludes any embedded cover (RIFF can't carry it), so a FLAC with art
    # transcodes cleanly. RIFF carries no tags either, so none mapped.
    return base + ["-map", "0:a", "-c:a", "pcm_s16le", "-f", "wav", str(tmp)]


def transcode_files(
    paths: Sequence[Path],
    *,
    fmt: str,
    mp3_vbr_quality: int = 0,
    binary: str = _FFMPEG_BINARY,
    runner: Runner | None = None,
) -> TranscodeResult:
    """Transcode each FLAC in ``paths`` to ``fmt`` (a sibling file); return a
    :class:`TranscodeResult`.

    Never raises. An unsupported ``fmt`` (e.g. "flac") is a clean no-op. A
    missing ``ffmpeg`` (or any failure to run it) aborts with ``error`` set,
    leaving every file untouched. A per-file failure leaves that FLAC in place
    and writes no output (the temp is discarded). On success each output is
    written atomically (``os.replace`` of a sibling temp), so the rip is never
    left with a half-written MP3/WAV. The source FLAC is always kept.
    """
    if fmt not in SUPPORTED_FORMATS:
        # "flac" or anything we don't transcode → nothing to do, cleanly.
        return TranscodeResult()

    run = runner or _default_runner
    failures: list[Path] = []
    transcoded = 0
    ext = _FORMAT_EXT[fmt]
    for src in paths:
        dest = src.with_suffix(f".{ext}")
        tmp = dest.with_name(dest.name + ".transcode.tmp")
        argv = _build_argv(binary, src, tmp, fmt, mp3_vbr_quality)
        try:
            rc = run(argv)
        except FileNotFoundError:
            return TranscodeResult(
                transcoded=transcoded,
                error=f"'{binary}' not found — cannot transcode to {fmt}",
            )
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg transcode timed out on %s", src)
            _safe_unlink(tmp)
            failures.append(src)
            continue
        except OSError as exc:
            return TranscodeResult(
                transcoded=transcoded, error=f"could not run {binary}: {exc}"
            )
        if rc != 0 or not tmp.exists():
            _safe_unlink(tmp)
            failures.append(src)
            continue
        try:
            os.replace(tmp, dest)  # atomic move into place (same directory)
        except OSError as exc:
            log.warning("could not move transcoded %s into place: %s", dest, exc)
            _safe_unlink(tmp)
            failures.append(src)
            continue
        transcoded += 1
    return TranscodeResult(transcoded=transcoded, failures=tuple(failures))
