"""Adapter layer over external dependencies.

Per CLAUDE.md Critical Rule #1, every call into an unmaintained
dependency goes through a thin adapter so a future replacement is
feasible without rewriting the GUI. The adapters in this package:

- `whipper_backend` — wraps the host-exported `whipper` CLI. Replacement
  target if needed: `cyanrip`.
- `musicbrainz_client` — wraps `musicbrainzngs`. Replacement target:
  direct `requests` against MusicBrainz's JSON REST endpoint.
- `metaflac` — wraps the `metaflac` CLI from the FLAC project. Not on
  the unmaintained list, but kept consistent with the adapter pattern
  so subprocess details stay out of the GUI.
"""
