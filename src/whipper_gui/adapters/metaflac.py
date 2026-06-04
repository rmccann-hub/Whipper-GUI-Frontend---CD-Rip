"""Adapter over the `metaflac` CLI for FLAC tag reading and writing.

`metaflac` is part of the FLAC reference encoder package. We wrap it
rather than calling subprocess directly so the Unknown Album helper
(brief P0 #9) can stay focused on the UX flow.

The adapter writes via `--remove-tag=KEY` + `--set-tag=KEY=VALUE` so
existing values for a given key are replaced, not duplicated. Reading
uses `--export-tags-to=-` and parses the `KEY=VALUE` lines.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# A short timeout is fine — metaflac is fast.
_METAFLAC_TIMEOUT_S: float = 30.0


class MetaflacError(Exception):
    """Raised when a metaflac invocation fails actionably."""

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output: str = output


class MetaflacAdapter:
    """Thin wrapper around the `metaflac` CLI.

    - `read_tags(path)` returns the current Vorbis comments as a dict.
    - `write_tags(path, tags)` replaces any existing values for each
      provided key with the new value. Keys not in `tags` are left
      alone (call `read_tags` + dict update if you want full replace).
    """

    def __init__(self, binary_name: str = "metaflac") -> None:
        # `binary_name` is what we pass to subprocess; resolution is
        # PATH-based unless the caller passes an absolute path. The
        # config's `metaflac_path` is forwarded here at construction.
        self._binary: str = binary_name

    def read_tags(self, flac_path: Path) -> dict[str, str]:
        """Return the FLAC's Vorbis comments as a dict.

        Duplicate keys in the file collapse to the last value seen —
        matches metaflac's own preference. If you need to preserve
        duplicates, read the raw output via `metaflac --export-tags-to`
        yourself; we don't expose that here.
        """
        output = self._run(["--export-tags-to=-", str(flac_path)])
        tags: dict[str, str] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            tags[key.strip()] = value
        return tags

    def write_tags(self, flac_path: Path, tags: dict[str, str]) -> None:
        """Set each `key=value` in `tags` on `flac_path`.

        Existing values for the same key are removed first so we don't
        end up with multiple values per key (FLAC supports that, but
        the use case here — applying clean tag sets — wants single-value
        semantics).
        """
        if not tags:
            return

        # One subprocess invocation per file with all flags batched.
        # metaflac processes its flags in order, so --remove-tag pairs
        # are applied before their --set-tag counterparts.
        args: list[str] = []
        for key in tags:
            args.append(f"--remove-tag={key}")
        for key, value in tags.items():
            args.append(f"--set-tag={key}={value}")
        args.append(str(flac_path))

        self._run(args)
        log.debug("wrote %d tag(s) to %s", len(tags), flac_path)

    # --- Internals ---

    def _run(self, args: list[str]) -> str:
        """Invoke metaflac and return its stdout. Raises MetaflacError."""
        argv: list[str] = [self._binary, *args]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_METAFLAC_TIMEOUT_S,
            )
        except FileNotFoundError as exc:
            raise MetaflacError(f"metaflac binary not found ({self._binary})") from exc
        except subprocess.TimeoutExpired as exc:
            raise MetaflacError(
                f"metaflac timed out after {_METAFLAC_TIMEOUT_S:.0f}s"
            ) from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip().splitlines()
            last = stderr[-1] if stderr else f"rc={proc.returncode}"
            raise MetaflacError(
                f"metaflac failed: {last}",
                output=(proc.stdout or "") + (proc.stderr or ""),
            )
        return proc.stdout or ""
