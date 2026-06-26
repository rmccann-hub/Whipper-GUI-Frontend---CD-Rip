# Multi-format output (FLAC · WavPack · MP3 · WAV) — research + design (P1)

**Status:** **shipped (2026-06-26, maintainer sign-off).** The **product decisions are
locked** (§5); the **encoder facts and args are verified current** against the upstream
docs (§3); the **feature is built, wired, and tested** (§6). This flipped the original
Critical Rule #4 ("FLAC-only for v1") — FLAC is now the default and the archival
*master*, with WavPack/MP3/WAV as derived outputs (see CLAUDE.md Critical Rule #4).
This doc remains the design-of-record; the one open item is embedding cover art *inside*
`.wv` (a documented limitation in §6, not a blocker).

The maintainer's directive that shaped the locked decisions (2026-06-26):

> "make sure flac and wv are lossless, use best practices for mp3, i do not expect
> perfect losses as it is not for that use. but tags for metadata, images, etc. i
> want for all if possible. and it should still be either ripped or transcoded
> correctly. this is best effort for the highest quality result which can then be
> verified by other users."

Companion: `output_reference/README.md` (parity baselines), `whipper_gui/parity.py`
(the checker), `TASKS.md` (the EAC parity matrix + the P1 encoder item).

---

## 1. Parity semantics per format (what "correct" means)

The integrity proof is the per-track **Copy CRC**, computed on the *extracted
PCM* — **before, and independent of, the output encoder**. So one parity check
(`whipper_gui.parity`, `scripts/eac_parity.py`) covers every format:

| Format | Lossless? | Parity target | What "parity" proves |
|---|---|---|---|
| **FLAC** (default, master) | yes | EAC Copy CRC (the committed baseline) | byte-identical audio |
| **WavPack** (`.wv`) | yes | **the same EAC FLAC baseline** | byte-identical audio |
| **WAV** | yes | **the same EAC FLAC baseline** | byte-identical audio |
| **MP3** | **no** | the same EAC **extraction** CRC | the *read* was bit-perfect; the encode is a separate concern |

Consequences:

- **The lossless formats need no separate EAC baseline.** Lossless → identical PCM
  → identical Copy CRC, so a WavPack/WAV rip is proven against the existing
  `output_reference/EAC_flac/` baseline. (A native EAC WavPack/WAV log is nice
  confirmation, not a requirement.) WAV is pinned by
  `tests/test_parity.py::test_wav_rip_parities_against_the_committed_flac_baseline`;
  WavPack gets the same invariant when the encode path lands.
- **"Lossless" is provable end-to-end, not just at read time.** FLAC `--verify`
  and WavPack `-v` re-decode during the encode and compare to the source PCM, and
  both store a source MD5 (FLAC STREAMINFO MD5 / WavPack `-m`). So "FLAC and wv are
  lossless" is a guarantee a third party can re-check from the file alone — exactly
  the "verified by other users" bar the maintainer set.
- **MP3 parity is extraction-CRC + encoder/tag behaviour**, never an audio
  bit-compare (lossy). The CRC still proves the disc read was clean; the encoder
  config (below) is what makes the MP3 itself good. Pinned by
  `tests/test_parity.py::test_mp3_rip_parities_on_extraction_crc`.

The parser/checker already work for every format because they key on
format-independent log fields (EAC `Copy CRC`, whipper `Copy CRC:`, cyanrip
`EAC CRC32`). **One residual check (hardware):** confirm cyanrip prints the same
per-track success line + `EAC CRC32` for `-o wavpack`/`-o wav`/`-o mp3` as it does
for `-o flac` — the cyanrip log parser's track-start regex keys on the literal
"ripped and encoded successfully!" wording (`parsers/cyanrip_log.py`). Strongly
expected (the CRC is computed pre-encode), but verify against a real
non-FLAC cyanrip log before claiming it.

---

## 2. How each backend produces formats (verified 2026-06-23)

- **whipper is FLAC-only.** Configurable encode profiles were removed in v0.5.0;
  output is hardcoded FLAC. → For the whipper backend, **every other format must be a
  post-rip re-encode** from the FLAC it produces, not a native option.
  ([whipper README](https://github.com/whipper-team/whipper/blob/master/README.md),
  [issue #247](https://github.com/whipper-team/whipper/issues/247))
- **cyanrip is natively multi-format** via `-o` (comma-separated; one rip can emit
  several): `flac, tta, opus, aac, wavpack, alac, mp3, vorbis, wav, alac_mp4,
  aac_mp4, opus_mp4, pcm`. Lossy bitrate via **`-b <kbps>` (default 256)**;
  lossless formats are always max compression (no knob); WAV is standard 16-bit LE
  PCM. EAC CRC32 / AccurateRip are computed from the decoded PCM and logged
  regardless of `-o`.
  ([cyanrip README](https://github.com/cyanreg/cyanrip/blob/master/README.md))
  *Caveat: the format list grew over time — confirm `wavpack`/`wav`/`mp3` exist in
  the cyanrip version the container actually ships.*

So the two backends want **different shapes**: cyanrip = pick the format(s) at rip
time; whipper = always FLAC, then transcode. A subtlety that steers two of the §5
decisions: **cyanrip's lossy MP3 is CBR/ABR (`-b`), not VBR** — so the best-practice
VBR-`-V0` MP3 (§3) is only reachable through the transcode path or a future cyanrip
VBR flag; and **cyanrip's WavPack uses its own (max-compression) settings**, so the
finest control over WavPack tags/art/verify also lives on the transcode path.

---

## 3. Encoder facts + the exact args to ship (verified against upstream docs)

Sources used for this pass (maintainer-supplied 2026-06-25/26):
[xiph FLAC tools manual](https://xiph.org/flac/documentation_tools_flac.html) +
[FLAC release index](https://ftp.osuosl.org/pub/xiph/releases/flac/),
[LAME links / HydrogenAudio Recommended LAME](https://lame.sourceforge.io/links.php),
[WavPack documentation](https://www.wavpack.com/wavpack_doc.html).

### FLAC (archival master, lossless) — `flac` / libavcodec FLAC

- **Latest stable is FLAC 1.5.0 (2025-02-10).** New since 1.4.x: **`-j N` /
  `--threads N` multithreaded encoding** — *same bitstream, faster wall-clock*.
  It is **version-gated**: older `flac` errors on an unknown `-j`, so only pass it
  after probing `flac --version ≥ 1.5.0` (the dependency subsystem already parses
  the version tuple). Treat it as a pure speed win, never a quality/compatibility
  change. Optional future enhancement to `flac_recompress.py`; not shipped yet.
- **Shipped re-compress flag set: `-8 -e -p --verify --silent -f -o`** (see
  `adapters/flac_recompress.py`). Decoded:
  - `-8` is the max built-in preset = `-l 12 -b 4096 -m -r 6 -A "subdivide_tukey(3)"`.
  - `-e` = exhaustive search of the LPC/fixed model space; `-p` = exhaustive search
    of the `qlp_coeff_precision`. **Both cost only *encode* time** — they refine the
    encoder's *search*, not the resulting `-l`/`-b`, so they add **zero decode-time
    cost**. (This is the distinction the maintainer cares about — see the mobile note
    below.) Added 2026-06-23 on the maintainer's "always fine to add encoding time."
  - `--verify` re-decodes each frame during the encode and compares to the input —
    the bit-perfect guarantee. `--silent`/`-f`/`-o` are plumbing (quiet, overwrite,
    output path).
- **Decode-cost note (the maintainer's 2015 mobile concern, kept honest):** decode
  work scales with the **LPC order `-l`**, not with `-e`/`-p`. `-5` uses `-l 8`; `-8`
  uses `-l 12`, so `-8` *itself* is marginally heavier to decode than `-5` — a real
  but small cost the maintainer accepted ("yes, at least for now… this may have
  changed a bit since 2015"). `-e`/`-p` ride for free at playback time.
- **cyanrip path:** encodes FLAC at libavcodec maximum compression already and
  exposes no level flag, so the re-compress step is a whipper-only no-op (gated by
  `produces_max_compression_flac()`).

### WavPack (`.wv`, lossless + tags + art) — `wavpack` / libavcodec wavpack

- **Lossless is the default** — no flag needed; the lossy/hybrid mode is opt-in
  (`-b`), which we never use. So "wv is lossless" is the out-of-the-box behaviour.
- **Quality / compression:** `-h` (high) and `-hh` (very high) trade encode time for
  a smaller file with **no decode penalty for the *normal* decoder**; `-x[1-6]` adds
  "extra" encode-time processing (`-x` = level 1, up to `-x6`) for a last fraction of
  size, again **encode-time only**. Mirrors FLAC's `-e`/`-p` philosophy.
- **Integrity, the WavPack analogues of FLAC's guarantees:**
  - `-m` stores an **MD5 of the source PCM** in the file (≈ FLAC's STREAMINFO MD5) —
    lets anyone re-verify bit-perfection later.
  - `-v` runs a **verify pass** (re-decode + compare during encode) — the direct
    analogue of `flac --verify`.
- **Tags + cover art:** WavPack uses **APEv2** tags. `-w "Field=Value"` writes a text
  field; **cover art is a binary APEv2 tag** (`Cover Art (Front)`), which the
  standalone `wavpack` tool writes (e.g. via `--import-id3` from a tagged source, or
  an explicit binary-tag import). This is why the transcode path should prefer the
  **standalone `wavpack` encoder over ffmpeg's wavpack muxer** for the whipper case:
  ffmpeg's wavpack metadata/cover support is thinner than native APEv2. *(Impl detail
  to confirm at build time — see §5 note 7.)*
- **Reference point:** the maintainer's EAC WavPack config used `-h -m` (high + MD5,
  no verify, no extra). Our archival default goes further — **`-hh -m -v -x`**
  (very-high, MD5, verify pass, extra processing): maximal lossless quality + a
  self-checkable integrity hash + a verified encode, all at encode-time cost only.

### MP3 (lossy "convenience" output, best-practice VBR) — LAME / libmp3lame

- **Use VBR `-V`, not CBR.** LAME 3.100 (2017) is the last release; its modern VBR
  engine (`--vbr-new`, default since 3.98) is the recommended path on
  [HydrogenAudio's Recommended LAME](https://wiki.hydrogenaudio.org/index.php/LAME)
  (the canonical reference linked from LAME's own
  [links page](https://lame.sourceforge.io/links.php)).
- **Quality ladder:** `-V2` ≈ 190 kbps (= `--preset standard`) is HA's
  *transparency* recommendation — the point most listeners can't ABX from source.
  `-V0` ≈ 245 kbps (= `--preset extreme`) is the **highest** VBR setting. 320 CBR is
  **not** demonstrated to beat top VBR audibly, and costs more bits — so it is not a
  better archival-of-lossy choice, just a bigger one.
- **We ship `-V0`** — a notch above HA's transparency floor — to satisfy the
  maintainer's "highest quality result" directive, and because it **matches the
  maintainer's own EAC MP3 rip** of the baseline disc (EAC command line:
  `lame3.100.1 … -V 0 %source% %dest%`, ID3 on; confirmed 2026-06-25).
- **Stereo:** leave **joint stereo ON** (LAME's default; it picks lossless mid/side
  per frame). Forcing `-m s` only wastes bits.
- **The LAME `-q 0…3` / `noise_shaping_amp` bug ([#516](https://sourceforge.net/p/lame/bugs/516/))
  is CBR/ABR-only — VBR is unaffected**, so `-V0` sidesteps it entirely. Frame the
  `-q` workaround as "only relevant if we ever ship CBR/ABR."
- **ffmpeg mapping** (our transcode path, and cyanrip's encode path):
  `-q:a N` = VBR = lame `-V N` (so **`-q:a 0` == `-V0`**); `-b:a` = CBR/ABR;
  `joint_stereo` defaults on. The standalone-lame *algorithm-quality* `-q` maps to
  ffmpeg's separate `compression_level`, so #516 stays a non-issue for `-q:a` VBR.
  **Re-encode whipper FLAC → MP3:**
  `ffmpeg -i in.flac -map_metadata 0 -id3v2_version 3 -c:a libmp3lame -q:a 0 out.mp3`
  (carries tags; cover art rides as an ID3 APIC frame — empirically confirmed
  2026-06-25 that the transcode output carries both tags and embedded front cover).
  ([FFmpeg codecs](https://ffmpeg.org/ffmpeg-codecs.html))
- **MP3 is "transparent," not "archival."** FLAC/WavPack stay the lossless formats;
  MP3 is the convenience/portability output ("not for that use"). Say so in the UI.

### WAV (raw interchange only) — `pcm_s16le`

- **No RF64/Wave64 needed at CD scope.** A full 80-min CD ≈ 800 MB, under the 4 GiB
  RIFF ceiling; per-track files are tiny. Skip RF64.
  ([WAV](https://en.wikipedia.org/wiki/WAV), [RF64](https://en.wikipedia.org/wiki/RF64))
- **WAV can't carry rich tags or cover art.** RIFF has only the limited `INFO` chunk
  (no Vorbis/APEv2/ID3, no reliable embedded art). This collides head-on with the
  maintainer's "tags + images for all if possible" — so **WavPack, not WAV, is the
  recommended lossless-with-metadata format**, and WAV is kept only as a raw
  interchange option **with a clear warning** that its tags/art won't travel.
  ([RIFF tags](https://exiftool.org/TagNames/RIFF.html))

---

## 4. Design — routing through the existing seams (no new subsystems)

Two existing seams do all the work; **no bespoke per-encoder install code**
(Critical Rule #6) and **no new GUI plumbing** beyond a format selector.

**(a) Config.** `output_format: str = "flac"` (`"flac" | "wavpack" | "wav" | "mp3"`),
plus the MP3 quality knob (`mp3_vbr_quality: int = 0` → `-V0`/`-q:a 0`). Default FLAC.
The dataclass+`asdict` round-trips new fields for free (as the FLAC toggles did).
*(Built today for `flac`/`wav`/`mp3`; `wavpack` is the one value still to add.)*

**(b) Implementation decision — transcode-always (built 2026-06-26).** Rather than
branch on `WhipperBackend.native_output_formats()` (which stays as a *reserved*
capability seam), the GUI uses **one uniform path for both backends**: every rip
produces FLAC (whipper natively; cyanrip is invoked with `-o flac`), and a non-FLAC
choice is a **post-rip transcode** of that FLAC. Why this over per-backend native
encode:
- **Best-practice MP3 on *both* backends.** cyanrip's native MP3 is CBR/ABR (`-b`),
  not VBR; routing MP3 through ffmpeg `-q:a 0` gives the `-V0` VBR we want regardless
  of backend (§2, §3).
- **FLAC master always exists** (decision 2) — uniform, no special-casing.
- **One code path to test**, identical for whipper and cyanrip; no native-vs-transcode
  fork. The tiny extra encode time is acceptable ("fine to add encoding time").

`native_output_formats()` is kept as a documented seam for a future "skip the
transcode and let cyanrip encode natively" optimization, but nothing consumes it for
the rip in v1 of this feature.

**(c) Post-rip transcode adapter** (`adapters/transcode.py`), modelled on
`adapters/flac_recompress.py`: `transcode_files(paths, *, fmt, ...) ->
TranscodeResult` — never raises, best-effort, runs **off the GUI thread folded into
the existing post-rip daemon thread** (after tag/cover, like re-compress), reports via
a queued signal. Writes a *sibling* file (`01 - x.mp3`/`.wv` next to `01 - x.flac`)
and **keeps the FLAC as the archival master** (§5 decision 2). *Today it supports
`mp3`/`wav` via ffmpeg; `wavpack` is the remaining encoder to add (via the standalone
`wavpack` tool for full APEv2 tag/art control — §3).*

**(d) Dependency subsystem** (Critical Rule #6). Route every encoder through the
single `DependencyManager`:
- **MP3 + WAV:** `ffmpeg` (libmp3lame / pcm_s16le) — one dep, already present
  wherever cyanrip is (FFmpeg-based). Registered as optional/manual
  (`deps/checks.py::check_ffmpeg`, `deps/registry.py`). **Approved (§5 decision 1).**
- **WavPack:** the standalone **`wavpack`** encoder for best APEv2 tag/cover control
  (ffmpeg's wavpack muxer is the fallback). Register it the same way when the encode
  path lands — *new optional dep, route through the subsystem, add a
  `DEPENDENCIES.md` row.*
- **FLAC→WAV** decode needs only `flac -d` (already a dep) or ffmpeg.

**(e) Tags & art.** FLAC (Vorbis comments + PICTURE), MP3 (ID3v2 + APIC), WavPack
(APEv2 + binary `Cover Art (Front)`) **all carry full tags + embedded cover** — reuse
the existing cover-art fetch (`adapters/cover_art.py`). **WAV gets neither** → the §3
warning; don't pretend otherwise. This satisfies "tags + images for all if possible":
*possible* for three of four formats, impossible for WAV by the container's design.

**(f) Parity proof.** Unchanged — rip the baseline disc to the format, run
`scripts/eac_parity.py` against `output_reference/EAC_flac/…`, commit the passing
**log** (never audio) under `output_reference/<backend>_<format>/` (Critical Rule
#8). For lossless formats "pass" = identical Copy CRC; for MP3 "pass" = extraction
CRCs match (§1).

---

## 5. Decisions (LOCKED 2026-06-26 — maintainer sign-off)

These were the open gates in the prior draft; the maintainer's directive (top of
file) resolves them. Recorded here as the contract the build implements.

1. **Encoder dependencies — APPROVED.** `ffmpeg` is the MP3/WAV dep (covers both,
   already in cyanrip's stack). `wavpack` (standalone) is added for WavPack so its
   APEv2 tags + binary cover art are fully controllable. Both route through the
   dependency subsystem with `DEPENDENCIES.md` rows. *(ffmpeg already registered;
   wavpack to be registered with its encode path.)*
2. **Keep FLAC as the master — YES.** When the user picks WavPack/WAV/MP3, the FLAC
   is kept and the chosen format is derived *alongside* it. The north star is the
   archival library; the lossy/interchange copy is additive, never a replacement.
3. **Formats shipped: FLAC + WavPack + MP3** as the first-class trio, **WAV** kept
   as a raw-interchange extra (warned). Rationale: the maintainer named *flac, wv,
   mp3*; WavPack is the lossless-**with-metadata** answer that WAV can't be.
4. **Lossless means provably lossless.** FLAC `-8 -e -p --verify` (+ optional `-j` on
   1.5.0); WavPack `-hh -m -v -x`. Both carry a source-MD5 and a verify pass so a
   third party can re-confirm — the "verified by other users" requirement.
5. **MP3 = best-practice VBR `-V0`** (= ffmpeg `-q:a 0`), joint-stereo on, tags +
   APIC cover. Lossy is acceptable here ("not for that use"); `-V0` is the
   highest-quality VBR and matches the maintainer's EAC rip. The `-V` level stays
   **fixed at 0** for now (config field exists for a future Settings exposure).
6. **Multi-format at once (cyanrip `-o flac,mp3`):** allowed by the engine, but the
   first build ships **one format at a time** (simpler UI + uniform whipper/cyanrip
   behaviour). A "FLAC + MP3" combo is a fast follow once the single-format path is
   proven.
7. **Tags + art for all where the container allows — YES.** FLAC/MP3/WavPack: full
   tags + embedded cover. WAV: not possible (RIFF) → explicit warning, not silent
   data loss. *(Build-time confirm: the exact `wavpack`/APEv2 invocation that embeds
   the front cover, since this is the one path not yet empirically proven — MP3/FLAC
   already are.)*
8. **Hardware confirm (still gated, not blocking the build):** rip the baseline disc
   to `-o flac` *and* `-o wavpack`/`-o mp3`/`-o wav` with cyanrip; diff the logged
   EAC/AccurateRip CRCs to prove format-independence directly, and confirm the
   cyanrip success-line wording for the parser (§1). Test-plan candidate.

---

## 6. Build status

**Prep + facts (2026-06-23, refreshed 2026-06-26):**
- Parity tooling proven format-agnostic; WAV/MP3 invariants pinned by tests
  (`tests/test_parity.py`), semantics documented in `whipper_gui.parity` and
  `output_reference/README.md`.
- Encoder facts + exact args verified against the current upstream docs (§3) so the
  build starts from facts, not 2015-era rules of thumb. FLAC 1.5.0 / `-j`, LAME `-V0`
  (with the HydrogenAudio citation), and the full WavPack arg set all recorded.
- The EAC parity matrix in `TASKS.md` already lists the WAV/MP3 proof rows.

**Foundation built (2026-06-23, unreachable / default-FLAC so v1 is unchanged):**
- **§4(a) Config** — `output_format` + `mp3_vbr_quality` (`config.py`), round-trips
  like the rest. *(WavPack value still to add.)*
- **§4(b) Capability flag** — `WhipperBackend.native_output_formats()` (ABC default
  `{"flac"}`; cyanrip overrides).
- **§4(c) Transcode adapter** — `adapters/transcode.py` (`transcode_files(...) ->
  TranscodeResult`): per-FLAC ffmpeg re-encode to a sibling MP3/WAV, atomic swap-in,
  FLAC kept, never raises. MP3 = libmp3lame VBR `-q:a 0` + tags/APIC cover; WAV =
  `pcm_s16le`. Full test coverage (`tests/test_transcode.py`).
- **§4(d) Dependency** — `ffmpeg` registered in the single subsystem
  (`deps/checks.py::check_ffmpeg`, `deps/registry.py`, `DEPENDENCIES.md`), optional,
  manual tier.

**Feature shipped — user-facing (2026-06-26, maintainer sign-off; flips Critical
Rule #4):**
- **WavPack output** added to `transcode.py` (ffmpeg `-c:a wavpack`, lossless,
  APEv2 text tags; writes `.wv`). Empirically confirmed bit-identical PCM
  round-trip (lossless) and that text tags carry over.
- **Rip-flow integration** — the transcode is folded into the existing post-rip
  daemon thread (after tag → cover → re-compress, so it reads the final FLACs),
  reported via a new `transcode_done` queued signal. Transcode-always model
  (§4(b)); FLAC kept as the master.
- **Settings UI** — the **Output format** selector (FLAC / WavPack / MP3 / WAV)
  and a live WAV "no tags/art" warning. `to_config()` now round-trips
  `output_format` (and preserves `mp3_vbr_quality`, which had been silently reset).
- Tests across the adapter, the settings dialog, and the post-rip finish handler
  (skip-for-flac, run-for-non-flac, quality passthrough, slot rendering).

**Known limitation / future enhancement (not blocking):**
- **Embedded cover art inside `.wv`.** ffmpeg's WavPack muxer accepts only a single
  (audio) stream, so it can't embed the front cover *in* the `.wv`. The album-folder
  `cover.<ext>` (written by the cover-art step) is the universal image, so WavPack
  rips still get "a good cover image" — just not embedded. Embedding it requires the
  standalone `wavpack` tool (APEv2 binary `Cover Art (Front)` tag), a `wavpack`
  dependency to register through the subsystem; deferred until it can be
  hardware-validated. WAV embeds nothing by design (RIFF).
- **MP3 `-V` level** stays fixed at 0 (config field exists for a future Settings
  spinbox).
