# MP3 & WAV output — research + design (P1, pre-build)

**Status:** research + design only. **Critical Rule #4 still holds — FLAC is the
only v1 output; MP3/WAV are P1 backlog.** This doc is the prep so the eventual
encoder PR doesn't reship known bugs or bolt on ad-hoc install code. Nothing here
is implemented yet; the **build is gated on maintainer sign-off** of the open
questions in §5 (a new dependency is involved → Deviation policy "must ask").

Companion: `output_reference/README.md` (parity baselines), `whipper_gui/parity.py`
(the checker), `TASKS.md` (the EAC parity matrix + the P1 encoder item).

---

## 1. Parity semantics per format (what "correct" means)

The integrity proof is the per-track **Copy CRC**, computed on the *extracted
PCM* — **before, and independent of, the output encoder**. So one parity check
(`whipper_gui.parity`, `scripts/eac_parity.py`) covers all three formats:

| Format | Lossless? | Parity target | What "parity" proves |
|---|---|---|---|
| **FLAC** (v1) | yes | EAC Copy CRC (the committed baseline) | byte-identical audio |
| **WAV** | yes | **the same EAC FLAC baseline** | byte-identical audio |
| **MP3** | **no** | the same EAC **extraction** CRC | the *read* was bit-perfect; the encode is a separate concern |

Consequences:

- **WAV needs no separate EAC baseline.** Lossless → identical PCM → identical
  Copy CRC, so a WAV rip is proven against the existing
  `output_reference/EAC_flac/` baseline. (An EAC WAV log is nice confirmation, not
  a requirement.) Pinned by `tests/test_parity.py::test_wav_rip_parities_against_the_committed_flac_baseline`.
- **MP3 parity is extraction-CRC + encoder/tag behaviour**, never an audio
  bit-compare (lossy). The CRC still proves the disc read was clean; the encoder
  config (below) is what makes the MP3 itself good. Pinned by
  `tests/test_parity.py::test_mp3_rip_parities_on_extraction_crc`.

The parser/checker already work for all three because they key on
format-independent log fields (EAC `Copy CRC`, whipper `Copy CRC:`, cyanrip
`EAC CRC32`). **One residual check (hardware):** confirm cyanrip prints the same
per-track success line + `EAC CRC32` when `-o wav`/`-o mp3` is selected as it does
for `-o flac` — the cyanrip log parser's track-start regex keys on the literal
"ripped and encoded successfully!" wording (`parsers/cyanrip_log.py`). Strongly
expected (the CRC is computed pre-encode), but verify against a real WAV/MP3
cyanrip log before claiming it.

---

## 2. How each backend produces formats (verified 2026-06-23)

- **whipper is FLAC-only.** Configurable encode profiles were removed in v0.5.0;
  output is hardcoded FLAC. → For the whipper backend, **MP3/WAV must be a
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
  *Caveat: the format list grew over time — confirm `wav`/`mp3` exist in the
  cyanrip version the container actually ships.*

So the two backends want **different shapes**: cyanrip = pick the format at rip
time; whipper = always FLAC, then transcode.

---

## 3. Encoder facts to bake in (verified, with caveats)

### MP3 (LAME / libmp3lame)
- **The `noise_shaping_amp` / `-q 4` bug is real, still open (LAME 3.100.1 is the
  last release, 2017), but CBR/ABR-only — NOT VBR.** LAME bug
  [#516](https://sourceforge.net/p/lame/bugs/516/): with the new VBR psymodel
  applied to CBR/ABR, `-q 0…3` boosts bands the fixed bit-budget can't afford →
  metallic HF. VBR just spends more bits, so it's unaffected. The community patch
  was never released.
- **Recommendation: VBR `-V0` (~245 kbps), joint-stereo left ON** (LAME picks
  lossless mid/side per frame; forcing `-m s` only hurts). With `-V0` the `-q 4`
  workaround is moot — frame it as "only if we ever ship CBR/ABR," not a default.
  ([Hydrogenaudio LAME](https://wiki.hydrogenaudio.org/index.php/LAME),
  [Joint stereo](https://wiki.hydrogenaudio.org/index.php?title=Joint_stereo))
- **Empirically confirmed (2026-06-25):** the maintainer's EAC MP3 rip of the
  baseline disc uses exactly this — `lame3.100.1` with `-V 0` and ID3 tags on
  (EAC's command line: `-V 0 %source% %dest%`). So `-V0` is the right default,
  and our `ffmpeg -q:a 0` transcode (== `-V0`) matches EAC's own MP3 config.
- **FFmpeg libmp3lame mapping** (the path cyanrip uses, and the path a whipper
  re-encode would use): `-q:a N` = VBR = lame `-V N`; `-b:a` = CBR/ABR;
  `joint_stereo` defaults on. The standalone-lame *algorithm-quality* `-q` maps to
  FFmpeg's separate `compression_level` (a different option), so the #516 bug is a
  non-issue for `-q:a` VBR. **Re-encoding whipper FLAC → MP3:**
  `ffmpeg -i in.flac -codec:a libmp3lame -q:a 0 out.mp3` (= `-V0`), avoid CBR.
  ([FFmpeg codecs](https://ffmpeg.org/ffmpeg-codecs.html))
- **MP3 is "transparent," not "archival."** FLAC stays the archival format; MP3 is
  a convenience/portability output. Say so in the UI.

### WAV
- **No RF64/Wave64 needed at CD scope.** A full 80-min CD ≈ 800 MB, far under the
  4 GiB RIFF ceiling; per-track files are tiny. Skip the RF64 complexity.
  ([WAV](https://en.wikipedia.org/wiki/WAV), [RF64](https://en.wikipedia.org/wiki/RF64))
- **WAV can't carry rich tags or cover art.** RIFF has only the limited `INFO`
  chunk (no Vorbis/APEv2, no reliable embedded art). This collides with the
  project's "good cover image, good everything" north star — **surface a warning**
  when a user picks WAV (their tags/art won't travel with the file).
  ([RIFF tags](https://exiftool.org/TagNames/RIFF.html))

---

## 4. Design — routing through the existing seams (no new subsystems)

Two existing seams do all the work; **no bespoke per-encoder install code**
(Critical Rule #6) and **no new GUI plumbing** beyond a format selector.

**(a) Config.** Add `output_format: str = "flac"` (`"flac" | "wav" | "mp3"`), and
for MP3 a quality knob (`mp3_vbr_quality: int = 0` → `-V0`/`-q:a 0`). Default FLAC.
The dataclass+`asdict` round-trips new fields for free (as the FLAC toggles did).

**(b) Backend capability flag.** Extend the `WhipperBackend` ABC with
`native_output_formats() -> frozenset[str]` (default `{"flac"}`; cyanrip overrides
to its `-o` set). The GUI then chooses per backend:
- **cyanrip** (native) → pass `-o <format>` (and `-b` for MP3) at rip time. The
  `_build_rip_argv` + `_metadata_args` already exist; add the format/bitrate args.
- **whipper** (FLAC-only) → rip FLAC as today, then **post-rip transcode** the
  output to the chosen format.

**(c) Post-rip transcode adapter** (whipper path), modelled on the just-shipped
`adapters/flac_recompress.py`: a new `adapters/transcode.py` with
`transcode_files(paths, *, fmt, ...) -> TranscodeResult` — never raises,
best-effort, runs **off the GUI thread folded into the existing post-rip daemon
thread** (after tag/cover, like re-compress), reports via a queued signal. Unlike
re-compress it writes a *sibling* file (`01 - x.mp3` next to `01 - x.flac`) rather
than swapping in place, and decides whether to keep or remove the source FLAC
(probably keep FLAC as the archival master; MP3/WAV is the derived copy — matches
the north star).

**(d) Dependency subsystem** (Critical Rule #6). The transcode needs an encoder;
route it through the single `DependencyManager` like `flac`/`metaflac`:
- **MP3:** `ffmpeg` (libmp3lame) is the cleanest single dep — and it's *already*
  present wherever cyanrip is (FFmpeg-based). Register `ffmpeg` as an optional dep
  with a `check_ffmpeg` mirroring `check_flac`. (Alternative: `lame`, but ffmpeg
  covers both MP3 and WAV and matches cyanrip's stack — prefer one dep.)
- **WAV:** decoding FLAC→WAV needs only `flac -d` (already a dep) or ffmpeg; no new
  dependency strictly required for WAV.

**(e) Tags & art.** FLAC/MP3 carry full tags + embedded cover (MP3 via ID3 APIC —
reuse the cover-art fetch, write through ffmpeg/`-metadata`/an ID3 lib). **WAV
gets neither** → the §3 warning; don't pretend otherwise.

**(f) Parity proof.** Unchanged — rip the baseline disc to the format, run
`scripts/eac_parity.py` against `output_reference/EAC_flac/…`, commit the passing
**log** (never audio) under `output_reference/<backend>_<format>/` (Critical Rule
#8). For MP3, "pass" = extraction CRCs match (§1).

---

## 5. Open questions / decision gates (need maintainer sign-off before build)

1. **Encoder dependency:** adopt **`ffmpeg`** as the one transcode dep (covers MP3
   + WAV, already in cyanrip's stack)? — *Deviation policy: a new dep needs your
   OK and a `DEPENDENCIES.md` entry.*
2. **Keep FLAC as the master** when the user picks MP3/WAV (derive the lossy/WAV
   copy alongside), or replace it? (Recommended: keep FLAC — the north star is the
   archival library.)
3. **Multi-format at once?** cyanrip can `-o flac,mp3` in one pass; offer "FLAC +
   MP3" as a combo, or one format at a time?
4. **MP3 default:** VBR `-V0`? Expose the `-V` level in Settings or keep it fixed?
5. **WAV UX:** given no tags/art, is WAV even worth surfacing for v-next, or is MP3
   the only P1 lossy/portable target? (WAV is mostly useful as a raw interchange
   format.)
6. **Hardware confirm:** rip the baseline disc to `-o flac` *and* `-o mp3`/`-o wav`
   with cyanrip and diff the logged EAC/AccurateRip CRCs to prove
   format-independence directly (test-plan candidate), and confirm the cyanrip
   success-line wording for the parser (§1).

---

## 6. What's already done

**Prep (2026-06-23):**
- Parity tooling proven format-agnostic; WAV/MP3 invariants pinned by tests
  (`tests/test_parity.py`), semantics documented in `whipper_gui.parity` and
  `output_reference/README.md`.
- Encoder facts verified + recorded here (§3) so the build starts from facts, not
  the 2015-era rules of thumb.
- The EAC parity matrix in `TASKS.md` already lists the WAV/MP3 proof rows.

**Foundation built (2026-06-23, unreachable / default-FLAC so v1 is unchanged):**
- **§4(a) Config** — `output_format: str = "flac"` + `mp3_vbr_quality: int = 0`
  (`config.py`), round-trips like the rest.
- **§4(b) Capability flag** — `WhipperBackend.native_output_formats()` (ABC
  default `{"flac"}`; cyanrip overrides to add `wav`/`mp3`).
- **§4(c) Transcode adapter** — `adapters/transcode.py` (`transcode_files(...) ->
  TranscodeResult`): per-FLAC ffmpeg re-encode to a sibling MP3/WAV, atomic
  swap-in, FLAC kept, never raises. MP3 = libmp3lame VBR `-q:a` + tags/cover; WAV
  = `pcm_s16le`. Full test coverage (`tests/test_transcode.py`).
- **§4(d) Dependency** — `ffmpeg` registered in the single subsystem
  (`deps/checks.py::check_ffmpeg`, `deps/registry.py`, `DEPENDENCIES.md`),
  optional, manual tier.

**Not yet built (the §5-gated, decision-laden part):** the rip-flow integration
(cyanrip native `-o` argv + the whipper post-rip transcode call, folded into the
post-rip daemon thread) and the **Settings UI** format selector + the WAV
no-tags/art warning. These wire the feature to the user, which is where Critical
Rule #4 (FLAC-only for v1) and the §5 product decisions bite — held for sign-off.
