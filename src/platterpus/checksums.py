"""Per-file SHA256 digests — a long-term integrity record for a rip.

The ``.log`` carries EAC-style CRC32s that prove *bit-perfection at rip time*.
SHA256 digests answer a different question: **has anything changed since?** —
bit-rot, a bad disk, or a careless re-tag years later. They complement (don't
replace) the AccurateRip/CTDB rip-time proof.

Per the maintainer's "one debug file" rule, these digests are **embedded in the
`.platterpus.json` report**, not written as a separate `checksums.sha256`
sidecar — the only files a rip leaves are the EAC-compliant ``.log``, the
``.cue``, and that one JSON. To verify later, a digest can be re-computed with
:func:`sha256_file` (or the value pasted into any SHA256 checker).

Pure and never-raises: a hashing/IO error on one file is recorded against that
file rather than aborting — a partial record still protects the files it could
read.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Audio extensions we fingerprint — the FLAC master plus every format the
# transcode adapter can derive. Lower-cased; matched case-insensitively.
_AUDIO_SUFFIXES: frozenset[str] = frozenset({".flac", ".mp3", ".wav", ".wv", ".m4a"})

# Read files in 1 MiB chunks so a long album never loads a whole track into RAM.
_CHUNK: int = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA256 of `path`, streaming it in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def audio_files(rip_dir: Path) -> list[Path]:
    """Every audio file under `rip_dir`, sorted, for a stable digest order."""
    try:
        return sorted(
            p
            for p in rip_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
        )
    except OSError:
        # A missing/unreadable directory yields no files rather than raising —
        # this backs a best-effort report section, never a gate.
        return []


def compute_digests(rip_dir: Path) -> dict[str, str]:
    """Map each audio file (relative POSIX path) to its SHA256, for the report.

    Never raises: a file that can't be read maps to ``"unreadable: <error>"``
    instead of aborting the whole set. Streams each file, so it's safe on large
    albums — but it still does real disk I/O, so callers must run it OFF the GUI
    thread (it's invoked from the post-rip worker, after any transcode, so the
    derived files are included too).
    """
    digests: dict[str, str] = {}
    for path in audio_files(rip_dir):
        rel = path.relative_to(rip_dir).as_posix()
        try:
            digests[rel] = sha256_file(path)
        except OSError as exc:
            digests[rel] = f"unreadable: {exc}"
    return digests
