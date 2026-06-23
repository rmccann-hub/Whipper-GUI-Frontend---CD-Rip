# Archived investigations

Point-in-time investigation write-ups, kept for their audit trail. Their
**durable conclusions have already graduated** into the living docs — read
those first; these are the dated narrative behind them.

| Archived file | Durable conclusions now live in |
|---|---|
| [`ecosystem-audit-2026-06.md`](ecosystem-audit-2026-06.md) — whipper-stalled / cyanrip-successor audit, contribute-vs-fork decision, phased `CyanripImpl` plan | **PLANNING.md KDD-18** (the decision + rationale) and **DEPENDENCIES.md** (whipper/cyanrip rows, the COPR `barsnick/non-fed` packaging detail, the `pkg_resources`/Python-3.14 time-bomb) |
| [`offset-investigation-2026-06.md`](offset-investigation-2026-06.md) — why whipper's `offset find` is unreliable; the AccurateRip offset-by-drive-model refactor | **`adapters/accuraterip_offsets.py`** (the `DriveOffsets.bin` 69-byte format, the +667 validation gate, the layering precedence, and the `scripts/update_drive_offsets.py` refresh procedure) |
| [`upstream-modification-investigation.md`](upstream-modification-investigation.md) — EAC-parity "modify upstream?" audit; the **CTDB Phase-1 wire-format/CRC spec**; the `ctdb-cli`-is-.NET correction; the "do not revisit" non-feasible list | **PLANNING.md KDD-14 / KDD-16** point here for the unbuilt CTDB Phase-1 spec; the non-feasible list overlaps the brief's *Out of scope* |

These files are not maintained going forward. If a conclusion here ever
conflicts with a living doc, the living doc wins.

## External reference material

Third-party references kept for context — *not* our own investigations, so they
carry no "graduated conclusions" row. Treat them as parity targets/principles to
mine, not as authority over the living docs.

| Archived file | What it is |
|---|---|
| [`archival-extraction-guide-2026-06.md`](archival-extraction-guide-2026-06.md) — a user-supplied EAC 1.8 / FLAC 1.5 / WavPack / LAME master guide | EAC/Windows-centric archival pipeline reference. Its actionable items (FLAC `-V` verify + compression level, the LAME `-q 4` `noise_shaping_amp` gotcha for future MP3, RF64/Wave64 for WAV >4 GB, richer metadata, AcoustID/lyrics) feed the **2026-06-23 gap analysis** in `docs/session-log.md`; several claims are flagged *verify before relying*. |
</content>
