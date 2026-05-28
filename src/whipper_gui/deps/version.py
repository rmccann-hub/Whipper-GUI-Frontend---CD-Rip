"""Version-string parsing and comparison.

Lightweight helpers used by the dependency probes to extract a numeric
version tuple from arbitrary CLI output. We don't pull in
`packaging.version` — it would be another runtime dependency for a job
a regex and tuple comparison handle cleanly.

The named-group regex pattern matches CLAUDE.md's "Subprocess output
parsing must be robust to whipper minor-version changes. Use named-group
regexes, not column-index splits" rule.
"""

from __future__ import annotations

import re
from typing import Pattern

# Generic semver-like matcher. Greedy on `\d+` so `0.10.0` parses to
# (0, 10, 0) rather than (0, 1, 0). Patch is optional so "1.4" and
# "1.4.3" both parse.
DEFAULT_VERSION_PATTERN: Pattern[str] = re.compile(
    r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?"
)


def parse_version(
    text: str, pattern: Pattern[str] | None = None
) -> tuple[int, ...] | None:
    """Return the first version-like substring in `text` as an int tuple.

    Returns None if no match. `pattern` must have named groups `major`,
    `minor`, and optionally `patch`. Defaults to `DEFAULT_VERSION_PATTERN`
    which covers the formats whipper, metaflac, flatpak, and most other
    CLI tools print.
    """
    if pattern is None:
        pattern = DEFAULT_VERSION_PATTERN
    match = pattern.search(text)
    if not match:
        return None

    parts: list[int] = [
        int(match.group("major")),
        int(match.group("minor")),
    ]
    # `patch` is optional; the group may be absent from the pattern
    # entirely (custom patterns) or present but unmatched (no third
    # component in the input). Both cases reach `if patch:` as None.
    try:
        patch = match.group("patch")
    except IndexError:
        patch = None
    if patch:
        parts.append(int(patch))

    return tuple(parts)


def meets_minimum(
    version: tuple[int, ...] | None, minimum: tuple[int, ...]
) -> bool:
    """True if `version >= minimum` component-wise.

    A `None` version (the probe couldn't determine one) returns False —
    we cannot claim a dep meets a minimum when we don't know what's
    installed.

    Tuples of different lengths are padded with zeros on the right so
    `(1, 2)` is treated as `(1, 2, 0)`. This avoids "1.2 < 1.2.0"
    surprises that bite the moment a tool drops trailing zeros.
    """
    if version is None:
        return False
    length = max(len(version), len(minimum))
    v_padded = version + (0,) * (length - len(version))
    m_padded = minimum + (0,) * (length - len(minimum))
    return v_padded >= m_padded
