# `output_reference/` — rip-output baselines for EAC parity

This directory holds **reference rip outputs** used to prove Whipper GUI's rips
are correct by comparing them against a known-good baseline.

**EAC is the baseline.** Exact Audio Copy is the gold standard this project is
measured against (see [`../docs/test-plan.md`](../docs/test-plan.md) → *EAC
output-parity check*). The EAC reference is committed here now. Outputs from the
other backends (whipper, cyanrip) are added **only once they reach parity with
EAC**, as proof — not before.

## What "parity" means here (and why there's no audio)

A rip is bit-perfect when its **per-track CRC matches EAC's**. EAC's log records,
for every track, a `Test CRC` and a `Copy CRC` (e.g. `Copy CRC B0D122E7`); when
those two match each other the rip is internally consistent, and when a ripper's
`Copy CRC` equals EAC's for the same track the two rips are **bit-identical**.
AccurateRip / CTDB confidence values in the log corroborate this against the
wider community database.

So the comparison is **log-to-log (CRCs)**, not audio-to-audio. That's why this
directory stores **logs and cue sheets, never the decoded audio**:

- **Copyright (project-wide rule — `CLAUDE.md` Critical rule #8).** This
  repository is public. The reference disc (*The Police — Every Breath You Take:
  The Classics*) is a commercial recording; committing its FLAC/WAV/MP3 audio
  here would publicly redistribute copyrighted material. Owning the disc does not
  grant that right. This applies to **any** copyrighted media **anywhere in the
  repo, even a temporary test file** — never `git add` one. `.gitignore` denies
  audio extensions as a backstop.
- **It isn't needed.** The CRCs in the log already prove bit-perfection.
- **Repo bloat.** Full-album audio is hundreds of MB and would live in git
  history forever.

If a test ever genuinely needs real PCM to exercise the decode/CRC path, use a
**short, freely-licensed or self-generated** sample (CC0 / public-domain / a
synthetic tone with a known CRC), and **Git LFS** for any binary — never a
commercial track.

## Layout — backend × format

EAC is the baseline for each format; the matching backend dirs hold a rip's
**log** only once it reaches parity. **Priority order: FLAC (1) → WAV (2) →
MP3 (3)** — FLAC is the v1 archival format; WAV and MP3 are P1 (see `TASKS.md`).

| | FLAC (priority 1) | WAV (priority 2) | MP3 (priority 3) |
|---|---|---|---|
| **EAC** (baseline) | `EAC_flac/` ✅ committed | `EAC_wav/` | `EAC_mp3/` 🟡 imperfect (12/14; see its README) |
| **whipper** | `whipper_flac/` ⬜ | `whipper_wav/` ⬜ | `whipper_mp3/` ⬜ |
| **cyanrip** | `cyanrip_flac/` ⬜ | `cyanrip_wav/` ⬜ | `cyanrip_mp3/` ⬜ |

The committed EAC baseline (`EAC_flac/eac_baseline_police_classics.log`) is the
canonical extraction reference. Its per-track **Copy CRC** is the CRC of the
ripped PCM, so it's the bit-perfect target for **both FLAC and WAV** (both are
lossless → decode to identical PCM → identical CRC). **MP3 is lossy**, so an MP3
encode is *not* bit-comparable; "MP3 parity" means the same extraction CRCs +
correct encoder/tag behaviour, not identical audio. `EAC_wav/` and `EAC_mp3/`
therefore reuse this same extraction baseline rather than duplicating it.

## How to add a parity proof (when a backend reaches it)

1. Rip the **same disc** (*The Police — …: The Classics*, AccurateRip offset
   +667 on the BDR-209D) with the backend, in the format you're proving.
2. Run the parity checker against the EAC baseline:
   ```
   python3 scripts/eac_parity.py \
       output_reference/EAC_flac/eac_baseline_police_classics.log \
       path/to/the/backend/Album.log
   ```
   It prints a per-track PASS/FAIL table and exits 0 only on full parity. (It
   auto-detects EAC / whipper / cyanrip log formats; the comparison logic is
   `whipper_gui.parity`.)
3. When it passes, drop the backend's `.log` (and `.cue`) into the matching
   directory above, and tick the task in `TASKS.md` with the date + result
   ("14/14 Copy CRCs match EAC").

That commit is the durable evidence the backend is bit-perfect against EAC.

> A second, unrelated EAC sample log (*Shark Tale* soundtrack) lives in
> `../tests/fixtures/rip_log_eac_reference.log`; it's a parser sample, not a
> parity baseline.
