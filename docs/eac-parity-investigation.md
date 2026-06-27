# EAC parity investigation — can Whipper GUI output be bit-identical to EAC?

**Status:** research + plan (2026-06-27). Triggered by the maintainer's goal:
*"this program needs to essentially output the exact same files, bit by bit, as
EAC."* This document marks every axis where our output can deviate from EAC,
says whether closing the gap is **possible**, and lays out a prioritized plan.

Evidence base: a real hardware rip of **The Police — *Every Breath You Take: The
Classics*** (cyanrip 0.9.3, Pioneer BDR-209D, +667 offset) compared against the
EAC V1.8 baseline of the same disc. Logs/cues live in
[`output_reference/`](../output_reference/) (`EAC_flac/` vs `cyanrip_flac/`).

## TL;DR — two very different goals

1. **Bit-identical *audio* (the PCM samples) — ACHIEVABLE, and ~90% there.**
   This is the real meaning of "archival/EAC-quality": the *samples* equal the
   AccurateRip consensus, proven by the per-track CRC. Our cyanrip rip already
   matched EAC **byte-for-byte on 12 of 14 tracks**, with an identical TOC and
   AccurateRip confidence 200. This is the goal worth chasing, and it's nearly
   met.

2. **Bit-identical *files* (the `.flac`/`.cue`/`.log` byte-for-byte) — NOT
   ACHIEVABLE, and not the right target.** A FLAC file's bytes are *encoder-
   determined*: EAC pipes PCM to `flac.exe -8`; we use FFmpeg/libavcodec. Even
   with **identical PCM**, the two encoders choose different block sizes,
   prediction, stereo decorrelation, padding, seektable, and vendor string, so
   the `.flac` files never hash-match (Xiph FLAC format overview; Xiph FAQ). The
   `.cue`/`.log` are different tools' formats entirely. **This is expected and
   fine** — lossless means *same audio*, and the durable proof is the decoded-PCM
   CRC, never the file hash (exactly why Critical Rule #8 / `output_reference/`
   commit CRCs, not audio).

So we reframe the maintainer's goal to the one that is both meaningful and
attainable: **match EAC's extracted PCM (AccurateRip-verified), not EAC's file
bytes.**

## Deviation matrix (EAC ↔ our cyanrip output)

| Axis | EAC | Our cyanrip | Same? | Possible to close? |
|---|---|---|---|---|
| Read offset | +667 | +667 (`-s 667`) | ✅ identical | n/a |
| Drive / disc | BDR-209D | BDR-209D | ✅ | n/a |
| TOC (track sectors) | — | — | ✅ identical (all 14) | n/a |
| Secure / re-read | Secure | paranoia max | ✅ equivalent | n/a |
| Gap handling **audio** | append-to-previous | default merge-to-previous | ✅ (12/14 prove it) | n/a |
| Per-track **PCM** | baseline | 12/14 byte-identical | ⚠️ mostly | **Yes** — see T3/T5 |
| Overread lead-in/out | No | +2 frames, silence-fill | ⚠️ config differs | harmless here (T1/T14 matched); alignable |
| **Pre-gap markers in cue** (`INDEX 00`) | Yes (10/14) | **No** | ❌ deviates | **Hard** — see §Pregaps |
| FLAC **file bytes** | flac.exe `-8` | libavcodec | ❌ differ | **No** (encoder-determined) — and unnecessary |
| Tag **values** | EAC set | cyanrip set + colon-restore | ✅ matchable | minor work if needed |
| Tag/file **byte layout** | EAC | FFmpeg | ❌ differ | **No** — unnecessary |
| `.log` / `.cue` format | EAC | cyanrip | ❌ differ | **No** — different tools |
| Single-file disc image+cue | optional | **unsupported** | ❌ | needs another tool |

## The two audio tracks that differ (the only real audio gap)

- **Track 5 — a defect on this physical disc, not a ripper fault.** EAC *also*
  could not verify track 5 ("1 track could not be verified"); its CTDB pass says
  "differs in 3 samples @02:24:59." cyanrip rates it partially-accurate (offset-
  450). Both tools hit the same ~3 samples. **A tie; nothing to fix in software.**
- **Track 3 — a genuine near-miss.** EAC matched the main AccurateRip DB;
  cyanrip matched only the offset-450 *pressing-detector* CRC ("partially
  accurate") and applied 58 `FIXUP_ATOM` corrections. Per AccurateRip semantics,
  matching only the 450 variant means **a small number of differing samples** vs
  the consensus — a near-miss, not a quality grade. **Fixable** by (a) a re-rip
  (may be transient) or (b) CUETools/CTDB **Repair**, which uses whole-disc
  parity to correct small errors back to the consensus (needs the full disc).

## Pre-gaps in the cue (the "Detect Gaps" question) — why it's hard

EAC runs a **Detect Gaps** pass that reads the disc **subchannel** to find
index-00 pre-gaps, and records them as `INDEX 00` in its cue (10 of 14 tracks
here). Our cyanrip cue has none — every track is plain `INDEX 01 00:00:00`.

Findings:
- cyanrip's cue writer (`cue_writer.c`) **can** emit `INDEX 00`, but only when a
  track has a *merged pregap* recorded, and our rip's log says **"Gaps: None
  signalled"** / per-track **"Pregap LSN: none"** — i.e. cyanrip did **not detect
  the pre-gaps EAC found**. There is no evidence cyanrip reads the P-W subchannel
  for index detection the way EAC does (cyanrip issue #117 confirms INDEX-00
  emission exists but is pre-gap-gated; nothing about subchannel index scanning).
- Crucially, this is a **cue-metadata** gap, **not an audio** gap: both tools use
  append/merge-to-previous, so the pre-gap audio is already in the previous
  track's file the same way (that's *why* 12/14 PCM match). EAC merely *documents*
  the index points; cyanrip doesn't.
- It only matters for a **single-file disc image** or a **gapless re-burn** — not
  for tagged per-track FLACs, where the audio is already equivalent.

So writing EAC-style `INDEX 00` pre-gaps is **blocked on pre-gap detection**,
which cyanrip doesn't currently do on this path. Options are in the plan.

## Plan (prioritized)

**P0 — Reframe + lock the achievable bar (docs only).**
Adopt "**AccurateRip/CRC-identical PCM**" as the parity definition (this doc).
Stop implying byte-identical files are a goal — they're impossible across
encoders and unnecessary. (No code.)

**P1 — Make parity measurable and routine.**
We already have `whipper_gui.parity` + `scripts/eac_parity.py` (compares per-track
Copy CRC, format-agnostic). Wire a documented step / optional check that runs the
candidate rip's log against the committed EAC baseline and reports the match
count — so "did this rip match EAC?" is one command. (Small; mostly done.)

**P2 — Close Track-3-class near-misses (the real audio gap).**
- (a) Add cyanrip **`-Z N`** ("re-rip until checksums match N times") as a
  secure-rip option for marginal discs — strengthens reads so a near-miss track
  converges to the consensus. Hardware-gated test required.
- (b) Document the **CUETools Repair** workflow as the authoritative fix for a
  "partially accurate (450)" track, and evaluate a future in-app CTDB-repair
  step (large; CTDB verify already exists, repair does not).
- (c) First, simply **re-rip track 3** to see if the near-miss was transient.

**P3 — Pre-gaps / `INDEX 00` in the cue (decision-gated).**
- (a) Hardware-test cyanrip's **`-p`** modes (`-p default`/`merge`) to see if any
  makes it record `INDEX 00` for this disc; if so, pass it and we get EAC-style
  pre-gap markers for free.
- (b) If cyanrip won't detect subchannel pre-gaps, the only routes are a cyanrip
  feature request, the whipper/cdrdao path (cdrdao reads full TOC incl. gaps —
  but whipper is offset->587-buggy and cdrdao stalls on this BD drive), or
  generating the cue ourselves from a subchannel read we don't currently do.
- (c) **Decision gate:** is `INDEX 00` worth it given the audio is already
  equivalent and per-track FLACs don't use it? Likely **only** pursue if we add a
  single-file-image output mode.

**P4 — Config alignment (minor).**
Optionally align overread to EAC's setting; expose it. Low value (audio matched).

**P5 — Single-file image + cue (future, large).**
EAC's image+cue mode isn't supported by cyanrip (one FILE per track, no image
mode). Would need a different tool or post-assembly. Only justified if users want
a burnable disc image; revisit with KDD-18 (ripper-engine strategy).

## Bottom line

- **Audio parity with EAC is achievable and 12/14 already met** — the path to
  14/14 is re-rip + CUETools-repair-class tooling for the marginal tracks (P2),
  not a format change.
- **File-byte identity with EAC is impossible across encoders and is the wrong
  goal** — lossless audio + AccurateRip CRC is the archival standard, and we meet
  it where the disc allows.
- **EAC-style pre-gap cue markers are a metadata nicety, currently blocked on
  cyanrip pre-gap detection**, and only matter for disc-image use (P3/P5).
