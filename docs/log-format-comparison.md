# Rip log format: whipper vs EAC

The brief promises "EAC-equivalent archival quality" — so the rip log should be a reasonable archival substitute for EAC's. This document compares the two formats field-by-field, identifies what each captures, and notes the small gaps.

## Side-by-side fixtures

Both are in `tests/fixtures/`:

- `rip_log_real_whipper_0_7.log` — pulled verbatim from upstream whipper-team/whipper's own test fixture (`whipper/test/test_result_logger.log`). Used by the parser tests.
- `rip_log_eac_reference.log` — a representative EAC v1.6 log. Hand-authored to match the format documented on the Hydrogenaudio and CueTools wikis. **Not** used by the parser; stored for reference.

## Field-by-field comparison

### Archival header (drive + settings)

| Field | EAC | whipper | Notes |
|---|---|---|---|
| Tool version | `Exact Audio Copy V1.6 from 23. November 2020` | `Log created by: whipper 0.7.4.dev...` | Both clearly identify the ripping tool. |
| Date | `EAC extraction logfile from 16. October 2023, 14:30` | `Log creation date: 2019-10-26T14:25:02Z` | EAC uses local time/locale; whipper uses ISO 8601 UTC. **whipper better for archival.** |
| Drive identification | `Used drive  : PIONEER BD-RW BDR-209D   Adapter: 1  ID: 0` | `Drive: HL-DT-ST BD-RE WH14NS40 (revision 1.03)` | EAC includes adapter/ID; whipper includes firmware revision. **Roughly equivalent.** |
| Extraction engine | (implicit in EAC binary) | `Extraction engine: cdparanoia cdparanoia III 10.2 libcdio 2.0.0 ...` | Whipper names cdparanoia + libcdio versions. **whipper better for reproducibility.** |
| Read mode | `Read mode : Secure` | (implicit — whipper always uses cdparanoia with verification) | EAC offers Burst mode; whipper doesn't. Not a gap for archival. |
| Defeat audio cache | `Defeat audio cache : Yes` | `Defeat audio cache: true` | Equivalent. |
| C2 pointers | `Make use of C2 pointers : No` | (not exposed) | Whipper doesn't use C2 — see Linux quality gap in the brief. Not actionable here. |
| Read offset correction | `Read offset correction : 667` | `Read offset correction: 6` | Equivalent. |
| Overread lead-in/out | `Overread into Lead-In and Lead-Out : No` | `Overread into lead-out: false` | EAC includes lead-in too; whipper only mentions lead-out. Minor. |
| Gap detection | `Gap handling : Appended to previous track` | `Gap detection: cdrdao 1.2.4` | Different metadata: EAC describes the *strategy*, whipper names the *tool*. Both useful. |
| Null samples in CRC | `Null samples used in CRC calculations : Yes` | (not exposed) | Whipper's behavior is fixed; doesn't need to record it. |
| CD-R detected | (not in EAC log) | `CD-R detected: false` | Whipper adds; useful for archival ("is this a pressed disc?"). |

### Per-track block

| Field | EAC | whipper | Notes |
|---|---|---|---|
| Track header | `Track  1` | `1:` | Cosmetic. |
| Filename | `Filename C:\...\01. Title.wav` | `Filename: ./.../01. Title.flac` | Both capture. |
| Pre-gap length | `Pre-gap length  0:00:02.00` | (in TOC section, not per-track field) | EAC repeats per-track; whipper consolidates in TOC. Equivalent archivally. |
| Peak level | `Peak level 90.0 %` | `Peak level: 0.90036` | Different units (percentage vs 0..1 decimal). Same data. |
| Extraction speed | `Extraction speed 7.0 X` | `Extraction speed: 7.0 X` | Identical. |
| Track quality | `Track quality 100.0 %` | `Extraction quality: 100.00 %` | Identical (label differs). |
| Test CRC | `Test CRC 0025D726` | `Test CRC: 0025D726` | Identical. |
| Copy CRC | `Copy CRC 0025D726` | `Copy CRC: 0025D726` | Identical. |
| AccurateRip v1 result | `Accurately ripped (confidence 14)  [95E6A189]  (AR v1)` | `AccurateRip v1: \n  Result: Found, exact match \n  Confidence: 14 \n  Local CRC: 95E6A189 \n  Remote CRC: 95E6A189` | Whipper's format is more verbose and machine-friendly. **whipper better for parsing.** |
| AccurateRip v2 result | `Accurately ripped (confidence 11)  [113FA733]  (AR v2)` | (same structure as v1) | Same as above. |
| Pre-emphasis flag | (not in EAC log) | `Pre-emphasis:` (yes/no/empty) | Whipper extra. Useful for archival pre-emphasis-encoded discs. |
| Per-track status | `Copy OK` | `Status: Copy OK` | Identical. |

### Summary / status report

| Field | EAC | whipper | Notes |
|---|---|---|---|
| Overall AccurateRip outcome | `All tracks accurately ripped` | `AccurateRip summary: All tracks accurately ripped` | Identical. |
| Error summary | `No errors occurred` | `Health status: No errors occurred` | Identical. |
| EOF marker | `End of status report` | `EOF: End of status report` | Identical. |

### Log integrity

| Aspect | EAC | whipper | Notes |
|---|---|---|---|
| Footer | `==== Log checksum <HEX> ====` | `SHA-256 hash: <hex>` | EAC uses a proprietary signed checksum (validated by EAC's own log-verify tool and by CueTools/CTDB); whipper uses a plain SHA-256. **EAC is stronger** — its checksum is computed over a canonicalized form of the log and would detect tampering that whipper's plain hash wouldn't. This is a real gap. |

## Verdict on EAC-equivalence

**Archival content: equivalent.** Every field EAC captures that bears on whether the rip is bit-perfect (drive, offset, cache defeat, per-track CRCs, AccurateRip confidence v1+v2) is also captured by whipper. Whipper additionally records the extraction-engine version and CD-R detection.

**Format parseability: whipper is better.** Whipper's YAML-style indented structure parses cleanly with a state machine; EAC's free-form `key value` lines need more regex per field.

**Log integrity: EAC is stronger.** EAC's signed checksum is a known-trusted forensic signal in the audiophile/archival community (forums and CTDB accept "EAC-verified logs"). Whipper's SHA-256 covers the file contents but isn't widely recognized as a forensic signal in the same way. This is a real gap but **not actionable from the GUI side** — closing it would require whipper itself to implement an EAC-equivalent checksum scheme.

## Implications for the GUI

1. **The `RippingInfo` block on `RipLog` mirrors EAC's archival header** so the GUI can surface drive/offset/cache in a "Rip details" panel that gives the user the same archival confidence EAC users get.
2. **The per-track display** can render whipper's AR v1 / v2 confidence the same way EAC does ("Accurately ripped (confidence 14) [95E6A189] (AR v1)"), even though the underlying log structure differs.
3. **We don't need to export EAC-format logs.** No P0/P1 feature requires it. If a user demands "submit-to-AccurateRip"-compatible logs in the future, that's a separate feature (and Linux can't submit to AccurateRip anyway per the brief's confirmed quality gap).

## How this was verified

- Real whipper log: pulled from `whipper-team/whipper` master at `whipper/test/test_result_logger.log` (commit `b71ec9f` referenced in the log itself, 2019-10-26).
- EAC format: cross-referenced against the Hydrogenaudio Knowledgebase EAC article and CueTools' AccurateRip log parser documentation, both stable public references for the format.

If T32's smoke test produces a log from a current whipper version (0.10.0+) that differs structurally from the 0.7.4 fixture used here, update both this document and the parser tests accordingly.
