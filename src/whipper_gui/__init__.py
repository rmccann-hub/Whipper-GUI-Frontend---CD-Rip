"""Whipper GUI — Linux GUI front-end for the whipper audio-CD ripping CLI."""

# ── Canonical version: the single source of truth ──────────────────────────
# This string is THE version of Whipper GUI. Bump it here and nowhere else:
#   * the build reads it via `[tool.setuptools.dynamic]` in pyproject.toml, so
#     the installed package metadata (`importlib.metadata.version`) matches;
#   * the running app imports it (`from whipper_gui import __version__`) for
#     the `--version` flag, the Help → About dialog, and the MusicBrainz
#     user-agent.
# To cut a release: bump this, add a CHANGELOG entry, then tag `vX.Y.Z`.
__version__: str = "0.3.4"
