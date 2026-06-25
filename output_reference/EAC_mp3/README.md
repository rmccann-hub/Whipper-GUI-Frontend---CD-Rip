# EAC MP3 — reference (imperfect, replaceable)

Holds an EAC MP3 rip of the baseline disc (*The Police — Every Breath You Take:
The Classics*, BDR-209D, offset +667). **Text only — no audio** (Critical Rule #8;
the per-track CRCs are the proof).

- `eac_mp3_police_classics.log` / `.cue` — the EAC rip (2026-06-25).

## ⚠️ This is a starting point, not a clean baseline — improve/replace it later

This particular rip is **not a bit-perfect extraction**, so don't treat it as the
gold reference:

- **12/14 extraction CRCs match** `../EAC_flac/` (the clean FLAC baseline).
- **Tracks 3 and 4 have read errors this session** (Copy CRC differs from both the
  FLAC baseline and AccurateRip) — the disc's known marginal zone, not an MP3
  problem. (On track 4, EAC's *Test* CRC matched the baseline but the *Copy* pass
  picked up a transient error.)
- **Track 5** differs from AccurateRip but matches our FLAC baseline — the
  consistent disc/pressing quirk, not an error.

Run the checker to see it:

```
python3 scripts/eac_parity.py \
    output_reference/EAC_flac/eac_baseline_police_classics.log \
    output_reference/EAC_mp3/eac_mp3_police_classics.log
# → 12/14 tracks match — NOT parity (tracks 3, 4)
```

**To replace it:** re-rip the disc with EAC (clean the disc around tracks 3–4
first) in Test & Copy mode until all 14 match, then overwrite these files.

## Why it's still valuable

It documents **EAC's MP3 encoder configuration** — the real reason to keep it:

- Encoder: `lame3.100.1`, options **`-V 0`** (VBR, ~245 kbps transparent), ID3
  tags **on**.
- This **confirms our design** (`docs/mp3-wav-support.md` §3): VBR `-V0`,
  joint-stereo on. Our planned whipper-path transcode (`ffmpeg -q:a 0`, ==
  `-V0`) matches EAC's own MP3 settings.

## On format & encoding

MP3 is **lossy**, so the MP3 audio is never bit-comparable; only the shared
**extraction CRCs** (identical to `../EAC_flac/`) and the tag/structure compare —
see [`../README.md`](../README.md). EAC's native log encoding is **UTF-16**; this
copy was converted to UTF-8 for readability (like the FLAC baseline). The parity
checker reads either encoding (`whipper_gui.parity.decode_log_bytes`).
