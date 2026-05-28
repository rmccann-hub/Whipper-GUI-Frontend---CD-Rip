"""Whipper GUI's dependency self-management subsystem.

All "is this dependency present and is it the right version?" logic lives
under this package — there are no ad-hoc `shutil.which()` calls anywhere
else in the codebase (CLAUDE.md Critical Rule #6).

Public surface:

- `deps.manager.DependencyManager` — the orchestrator
- `deps.registry.SPECS` — declarative list of every dependency
- `deps.checks` — probe functions (one per dep)
- `deps.resolvers` — three resolvers, one per tier (auto / queued / manual)
- `deps.version` — version-string parsing helpers
"""
