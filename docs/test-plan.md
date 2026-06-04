# Manual / hardware test plan

The remaining work can't be validated in the cloud build environment — it needs
a real CD + drive, a desktop session, or a maintainer credential. This document
is the **step-by-step checklist** for running those validations on real
hardware, one at a time. Each test is self-contained: do the steps, record the
result in the **Record** box, and follow **If it fails**.

Everything here is already *implemented* (or, for the upstream-blocked items,
*decided*) — these tests confirm reality matches intent and capture the real
output the docs still need.

Status marker in each test's heading (same convention as `TASKS.md`): `[ ]` = not yet run · `[x]` = passed · `[?]` = failed / needs rework (note it in the **Record** box).

---

## Walkthrough — a recognized CD end-to-end

A **recognized CD** (in MusicBrainz, and ideally in AccurateRip + CTDB — a popular
album works best) exercises almost the whole plan in one sitting. Do these in
order; each links to the detailed test for what to capture.

1. **Calibrate the drive** with the disc inserted (it's in AccurateRip, so
   offset-find works) — **Tests 3 & 4** below. Capture the `drive analyze` and
   `offset find` output.
2. **Rip it** from the GUI: MusicBrainz identifies the disc → **Start** → confirm
   every track's **Test CRC == Copy CRC** and the AccurateRip confidence. Take a
   screenshot — **Test 5**.
3. **CTDB-verify the rip** — **Test 1**, the highest-value step:
   ```bash
   source .venv/bin/activate
   python3 scripts/ctdb_verify.py "$HOME/Music/rips/<Artist>/<Album>/"
   ```
   Paste the full output (TOC, lookup URL, verdict). This is what validates — or
   corrects — the `toc=` wire format and the CRC.
4. If you have a second recognized disc, repeat step 3 on it: a standard studio
   album is the cleanest CTDB data point, so two discs disambiguate "wrong wire
   format" (both fail) from "this pressing isn't in CTDB" (one fails).

> CTDB's CRC needs host `flac`. If `flac --version` fails, export it from the
> container once: `distrobox enter ripping -- distrobox-export --bin /usr/bin/flac`.
> Even without it, the **lookup half** of Test 1 still validates the wire format —
> run it and paste the result anyway.

---

## Test 1 — [ ] CTDB verify: wire format + CRC (KDD-16)

**Goal:** confirm (or correct) the CTDB lookup wire format and the audio-CRC
algorithm, which were written clean-room from the spec and are unvalidated.
This unblocks wiring CTDB verify into the GUI.

**Preconditions**
- A pressed commercial CD that is very likely in CTDB (a well-known album).
- The disc ripped to FLAC through the GUI (a folder of `NN - Title.flac`).
- Host has `flac` and `metaflac` (`flac --version`); network reachable.
- A checkout with the package importable (`pip install -e .`, or prefix the
  command with `PYTHONPATH=src`).

**Steps**
1. Run the standalone verifier against the ripped album folder:
   ```bash
   python3 scripts/ctdb_verify.py "~/Music/rips/<Artist>/<Album>/"
   ```
2. Read the printed **Disc TOC** and **Lookup URL**.
3. Open the Lookup URL in a browser (or `curl` it) and compare to the script's
   parsed verdict.

**Record**
- Disc TOC string: `__________`
- Verdict (`not_in_db` / `no_match` / `match` / `no_decoder` / `lookup_error`):
  `__________`
- Confidence: `____` · Our CRC: `________` · A DB CRC: `________`

**Interpreting the result**
- **`lookup_error`** → transport/parse problem. Capture the URL + raw response;
  the issue is in `adapters/ctdb_client.py` (transport) or `parse_lookup_response`.
- **`not_in_db` for a disc you're sure is in CTDB** → the **`toc=` wire format
  is wrong**. This is the most likely first failure. Compare our TOC string to
  what CUERipper/CUETools sends for the same disc (Wireshark, or CUETools' log).
  Likely culprits: the +150 lead-in (`toc.LEAD_IN_SECTORS`), how the lead-out is
  expressed, or per-track vs. cumulative offsets (`disc_toc_from_files`). Fix
  `ctdb/toc.py` and re-run.
- **`no_match` (disc found, CRC differs)** → the lookup format is right; the
  **CRC algorithm needs the bit-exact fix**. Read the **LGPL**
  `CUETools.AccurateRip` (`AccurateRipVerify.CTDBCRC`) + `CUETools.Parity` for
  the polynomial/init/reflection and the ±2939 offset sweep, then replace
  `ctdb/crc.py:ctdb_crc_offset0` (the single seam). **Do not read
  `python-cuetoolsdb`** (GPL-2.0; KDD-16). Re-run until it matches a DB CRC.
- **`match`** → success. Implement the ±2939 offset sweep if not already, set
  `crc.CRC_VALIDATED = True`, add a regression test with the real CRC vector,
  and proceed to Test 1b.

**If it fails:** record the URL, raw XML, and TOC; the fix lives in `ctdb/toc.py`
(format) or `ctdb/crc.py` (CRC) — both are isolated for exactly this.

### Test 1b — [ ] wire CTDB verify into the GUI

Once Test 1 yields a trustworthy `match`:
- Add a `workers/ctdb_worker.py` (off-thread, emits `verified(result)`/`error`)
  and a CTDB verdict next to the AccurateRip result in `ui/rip_progress.py`.
- Add a Settings toggle "Verify with CTDB after a rip" (default off — it's a
  network call).
- Tests: worker signal flow with a fake client; UI renders each `Verdict`.

---

## Test 2 — [ ] CTDB repair direction (Phase 2, KDD-14)

**Goal:** decide and prototype parity repair. **Depends on Test 1 passing.**

**Open decision (needs your call):** `ctdb-cli` is **C#/.NET 10**, so bundling
it in the AppImage is heavy. Choose: (a) bundle a self-contained .NET publish,
(b) route it through the dependency subsystem as an *optional* user-installed
tool (like Picard), or (c) revisit a pure-Python `CUETools.Parity` port.

**Steps (exploratory, on a disc that ends with uncorrectable errors)**
1. Install `ctdb-cli` (`github.com/Masterisk-F/ctdb-cli`, `./configure && make`).
2. Run `ctdb-cli verify <cue>` then `ctdb-cli repair <cue>` on the damaged rip;
   capture the exact CLI surface + `--xml` output shape.
3. Record whether repair reconstructs + re-verifies, and the parity download size.

**Record:** chosen bundling option `____`; `ctdb-cli` CLI/output notes `____`.

---

## Test 3 — [ ] `whipper drive analyze` success output

**Goal:** capture the verbatim success output so the README/wizard can show
"you should see this."

**Steps**
1. Insert any audio CD. Run `Tools → Set up drive…` in the GUI (and/or
   `whipper drive analyze` in the `ripping` container directly).
2. Copy the full successful output.

**Record:** paste the success lines here, then add them to README Step 5 and the
drive-setup wizard's help text:
```
__________
```

---

## Test 4 — [ ] `whipper offset find` success output

**Goal:** capture the final offset line (e.g. `Read offset of drive is N
samples`) and confirm the auto path matches the manual AccurateRip lookup.

**Steps**
1. Insert a CD that is in AccurateRip. Run the wizard's offset step (or
   `whipper offset find`).
2. Record the final offset message and the numeric offset.
3. Compare to the offset from the AccurateRip drive-offset list for your drive.

**Record:** offset message `__________`; auto offset `____`; manual offset
`____`; match? `____`. Add the message to README Step 5.

---

## Test 5 — [ ] GUI screenshot

**Goal:** confirm the GUI looks right on Bazzite KDE Plasma 6 and add a
screenshot to the top of the README.

**Steps**
1. Launch the published AppImage on Bazzite/KDE.
2. Screenshot the main window (ideally mid-rip, with the track table populated
   and the current track highlighted).
3. Save to `docs/img/whipper-gui.png` and embed it near the top of `README.md`.

**Record:** screenshot committed? `____`; any layout issues `__________`.

---

## Test 6 — [ ] Picard auto-launch UX

**Goal:** verify the unknown-disc → Picard flow end-to-end and document what the
toggle actually does.

**Steps**
1. Enable "Launch MusicBrainz Picard on unknown discs" in Settings (Picard
   installed via the GUI's dependency manager).
2. Rip a disc MusicBrainz can't identify (or use *File → Rip as Unknown Album…*).
3. Observe whether Picard launches with the ripped files on finish.

**Record:** Picard launched? `____`; files loaded? `____`; UX notes `__________`.
Update README Step 6 with the real behaviour.

---

## Test 7 — [ ] PyPI go-live (maintainer credential)

**Goal:** make `pipx install whipper-gui` work from PyPI. The
`publish-pypi.yml` workflow is already in place (Trusted Publishing).

**Steps**
1. On PyPI: **Publishing → add a pending publisher** with — project
   `whipper-gui`, owner `rmccann-hub`, repository
   `Whipper-GUI-Frontend---CD-Rip`, workflow `publish-pypi.yml`, environment
   `pypi`.
2. Bump `__version__` in `src/whipper_gui/__init__.py`, add a `CHANGELOG.md`
   entry, commit.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. Watch the **Publish to PyPI** action; confirm the release on PyPI.
5. On a clean machine: `pipx install whipper-gui` and launch `whipper-gui`.

**Record:** published version `____`; `pipx install` works? `____`. Then drop
the "if it's not on PyPI yet" caveat from the README.

---

## After a test passes

- Update the heading marker (`[ ]` → `[x]`, or `[?]` on failure) with the date and any notes.
- Land the follow-up the test unblocks (Test 1 → GUI wiring; Tests 3/4/5/6 →
  README updates; Test 7 → README caveat removal).
- Update `TASKS.md` and `CHANGELOG.md`.
