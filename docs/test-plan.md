# Manual & release testing

> **Who this is for.** The maintainer running a full pre-release check, and the
> external testers coming on board. These are the validations that **can't run
> in CI** — they need a real CD + drive, a desktop session, or a maintainer
> credential.
>
> Two halves, in order of how you'll use them:
> - **Parts 0–D + Reporting** — the end-to-end *release/acceptance run*: a clean
>   uninstall → fresh install → rip → verify cycle, the **EAC output-parity**
>   check, and the **distribution + problem-permutation matrices** to spread
>   across testers.
> - **Single-feature cases (Test 1–9)** — the deep, individually-gated cases
>   (CTDB verify CRC, `drive analyze` / `offset find` strings, PyPI go-live, the
>   cyanrip parity run). Run one at a time and record the result.
>
> Everything here is already *implemented* (or, for upstream-blocked items,
> *decided*) — these tests confirm reality matches intent and capture the real
> output the docs still need.
>
> **Status marker** in each case heading (same convention as `TASKS.md`):
> `[ ]` = not yet run · `[x]` = passed · `[?]` = failed / needs rework (note it
> in the **Record** box).

## 0. Before you start — record your environment

Capture this once per tester/run; paste it at the top of every report:

```
Distro + version : (e.g. Bazzite 41 / Fedora Silverblue 41 / Ubuntu 24.04)
Desktop          : (KDE Plasma 6 / GNOME 46 / …)
CPU arch         : x86_64   (the only supported arch today)
Drive            : (vendor + model, e.g. PIONEER BD-RW BDR-209D)
Install method   : AppImage  (or pipx / source)
App version      : (Help → About, or `whipper-gui --version`)
Container backend: podman ___  / docker ___  (distrobox list)
```

A run is only meaningful with the **log** attached:
`~/.local/share/whipper-gui/log.txt` (and the rip's `.log` next to the FLACs).
For a hard-to-reproduce issue, turn on **Settings → Debug logging** first — it
raises the log file to verbose DEBUG.

---

## Part A — Full clean-cycle acceptance run

Do these in order. Each step has an **action**, the **expected** result, and a
box. Stop and file a report at the first hard failure.

### A1 — [ ] Uninstall to a clean slate
From a checkout (`git pull` first so you have the latest `uninstall.sh`):
```bash
cd ~/Whipper-GUI-Frontend---CD-Rip
git pull
bash uninstall.sh --full --yes
```
*Expected:* removes the AppImage in `~/Applications`, menu/desktop entries, the
`ripping` container, host-exported `whipper`/`metaflac`/`cyanrip`, `whipper.conf`,
Picard, and the app's config + logs. **Never** your music. (No checkout? Use the
app's **Tools → Uninstall Whipper GUI…** and tick the container + whipper.conf +
AppImage boxes.)

### A2 — [ ] Confirm the slate is clean
```bash
ls ~/Applications/whipper-gui* 2>/dev/null;            echo "---"
ls ~/.local/bin/whipper ~/.local/bin/cyanrip 2>/dev/null; echo "---"
distrobox list | grep ripping;                          echo "---"
ls ~/.config/whipper-gui ~/.config/whipper 2>/dev/null
```
*Expected:* only the `---` separators print (everything empty). Anything left →
`rm -rf` it (e.g. a stray `~/.config/whipper/whipper.conf.bak`) and note it.

### A3 — [ ] Fresh install (AppImage — the end-user path)
```bash
cd ~/Downloads
wget https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/latest/download/whipper-gui-x86_64.AppImage
chmod +x whipper-gui-x86_64.AppImage
./whipper-gui-x86_64.AppImage
```
*Expected:* the window appears **immediately** and **stays responsive** — no
"Not Responding" even while the container is cold (the launch probes run off the
GUI thread). On a FUSE-less host, run with `APPIMAGE_EXTRACT_AND_RUN=1`.

### A4 — [ ] First-run offers
*Expected, in order:* (1) "Add to your applications menu?" — say **Yes**; the
file moves to `~/Applications` and a menu entry appears. (2) The **host-setup
wizard** — say Yes; it builds the `ripping` container + installs whipper/flac
(+ cyanrip if that backend is selected) and exports them. **~20–40 min** the
first time (≈600 MB image pull); one polkit password prompt only if podman/
distrobox needs installing (none on Bazzite/Silverblue). (3) Picard offer — your
call. Record any wizard step that fails **verbatim**.

### A5 — [ ] Drive setup (read offset)
**Tools → Set up drive…** *Expected:* the offset is **pre-filled** from the
AccurateRip drive list (e.g. **+667** for a BDR-209D) — one **Save offset**
click, no disc. If your drive isn't in the list: insert a popular commercial CD,
click **Detect**, then Save (or type it). (To bank the verbatim success strings
for the docs, see **Test 3 / Test 4**.)

### A6 — [ ] Rip a recognized CD (whipper backend)
Insert a commercial CD → it's identified via MusicBrainz, the track list fills →
**Start rip**.
*Expected:* progress bars + current-track move; on finish the status reads a
**fidelity verdict** (*"all N tracks verified, Test/Copy CRCs match"*). Files
land under your output folder, tagged, with embedded cover art. Open the saved
`.log` (View log) — every track **Test CRC == Copy CRC**.

### A7 — [ ] EAC output-parity check  ⭐ (the headline)
If you have an EAC log for this exact disc + drive (we have one for *The Police —
Every Breath You Take: The Classics* on a BDR-209D at
`tests/fixtures/eac_baseline_police_classics.log`), compare. See **Part B** for
the full procedure, the per-track CRC baseline, and what "exact" means.

### A8 — [ ] cyanrip backend rip
Settings → **Ripping backend → cyanrip** → Save → accept the install offer →
restart. Re-rip the same disc. *Expected:* same files/tags/**cover art** (the
app fetches it from the Cover Art Archive for cyanrip), and a cyanrip fidelity
verdict. *This is the backend that avoids whipper's >587-offset bug.* For the
full parity checklist (track-3 fix, per-track CRC match), see **Test 8**.

### A9 — [ ] Edge discs
- **Unknown disc / offline:** *File → Rip as Unknown Album…* → placeholders →
  Start → FLACs tagged from what you typed, cover art fetched if a release was
  picked. *Expected:* no MusicBrainz TTY prompt ever surfaces. (Picard
  auto-launch flow: **Test 6**.)
- **CD-R (home-burned):** Settings → **Continue on CD-R** (whipper) → rips;
  cyanrip handles CD-Rs with no switch.

### A10 — [ ] In-app update (when a newer release exists)
**Help → Check for updates.** *Expected:* if newer, it downloads (cancellable
progress), shows phase labels (Downloading → Verifying → *"Installing — almost
done, please don't close…"*), verifies the checksum, installs to `~/Applications`,
and offers to **restart**. The window must **not** go "Not Responding," and
Cancel/✕ must stay responsive throughout (the 2026-06-13 freeze fixes).

### A11 — [ ] Uninstall again (clean removal)
Repeat A1 + A2. *Expected:* fully clean, music untouched, no leftovers. (For the
deeper no-terminal uninstaller verification, see **Test 9**.)

---

## Part B — EAC output parity (making the rip *exact*)

The product goal is a rip whose **audio is bit-identical to EAC's**, provable by
matching CRCs. UI differences don't matter; the bytes do.

**What must match the EAC baseline (`tests/fixtures/eac_baseline_police_classics.log`):**

| Field | EAC baseline | Where ours shows it |
|---|---|---|
| Per-track **CRC32** | the table below | whipper **Test/Copy CRC**; cyanrip **EAC CRC32** |
| Read **offset** | `667` | Settings / drive setup; printed in our `.log` |
| AccurateRip | confidence per track | our rip-log panel + `.log` |

**The per-track CRC32 baseline** (ground truth — a whipper or cyanrip rip of
this disc must reproduce these EXACTLY; EAC's "Copy CRC", whipper's Test/Copy
CRC, and cyanrip's "EAC CRC32" are the same algorithm). Disc: *The Police —
Every Breath You Take: The Classics*, EAC V1.8 on a BDR-209D at offset +667:

| Track | EAC CRC32 | | Track | EAC CRC32 |
|---|---|---|---|---|
| 1 | B0D122E7 | | 8 | D723C1B0 |
| 2 | 985AAE32 | | 9 | 6F6E4A5F |
| 3 | 59D352DD | | 10 | 3A33519F |
| 4 | 60D796AE | | 11 | 56BFC63D |
| 5 | E0036697 | | 12 | D78CEAEF |
| 6 | B32769D6 | | 13 | DA6A4DAF |
| 7 | CCBFF669 | | 14 | 787BA2D6 |

**Procedure:**
1. Rip the disc with our app (A6 whipper, A8 cyanrip).
2. Open both `.log`s and the EAC log. For each track, compare the CRC32 to the
   table above.
3. Record the comparison in the **Test 8** Record box.

**They should match exactly** when the rip is bit-perfect. If a track's CRC
differs, it's almost always one of these *parity variables* — check them before
assuming a bug:
- **Read offset** — must be the EAC value (**+667** here). A wrong offset shifts
  every sample → every CRC differs.
- **Gap/pregap handling** — EAC here used **"Appended to previous track."** If
  the ripper splits gaps differently, track *boundaries* move and per-track CRCs
  differ even though the audio is correct. ⚠️ **We don't currently set a gap
  mode** — the rip uses whipper's / cyanrip's default. So if a *clean* track's
  CRC differs (especially one adjacent to a pregap) while the offset is right,
  **gap handling is the prime suspect**, and the fix is to expose/force the
  EAC-matching gap mode (tracked in TASKS — the "EAC gap-handling parity" item).
  Tracks with no surrounding gap (most of a typical album) are unaffected.
- **Lead-in/out overread** — EAC: **No** overread here. Keep "Force overread"
  off to match.
- **Null samples in CRC** — EAC: **Yes**. (whipper/cyanrip CRC the decoded PCM,
  which includes nulls — consistent.)
- **A genuine disc defect** — e.g. our reference disc's **track 5** mismatches in
  *every* tool (CTDB: "differs in 3 samples"). A track that differs everywhere is
  the disc, not the ripper — don't chase it.

> **Known reference facts (banked from the EAC baseline):** track 3 rips *clean*
> in EAC, so whipper's historical track-3 failure was its **>587-offset bug**,
> not disc damage — cyanrip should clear it. Track 5 is a real disc quirk.

If CRCs match on whipper *and* cyanrip → **output parity achieved** for this
disc. Repeat on a few more discs (a clean pressing, a multi-disc set, a disc
with a known pregap) to generalize.

---

## Part C — Linux distribution matrix

Spread these across testers. The GUI needs Qt 6; ripping runs in a Fedora
container, so the host only needs Distrobox + a container backend. Minimum per
distro: **A3 (install) + A4 (wizard) + A6 (one rip)**.

| Distro family | Install path notes | Must pass | Priority |
|---|---|---|---|
| **Bazzite / Fedora Silverblue** | podman + distrobox preinstalled; zero host prompts | A1–A11 (primary target) | ⭐ highest |
| **Fedora Workstation / RHEL / CentOS** | dnf installs distrobox/podman if missing | A3–A6 | high |
| **Ubuntu / Debian 24.04+** | installer adds `podman` (distrobox only *recommends* it) | A3–A6 | high |
| **Linux Mint / Pop!_OS / elementary** | Ubuntu-based — same as Ubuntu | A3–A6 | medium |
| **Arch / Manjaro / EndeavourOS** | pacman installs distrobox + podman | A3–A6 | medium |
| **openSUSE Leap / Tumbleweed** | zypper installs distrobox + podman | A3–A6 | medium |
| **Other / older** | Distrobox's official installer; ensure podman/docker first | A3–A6, note fallbacks | low |

Record for each: did the window launch responsively (A3), did the wizard finish
(A4), did one rip complete with matching Test/Copy CRC (A6)?

---

## Part D — Problem-permutation matrix

Force each failure mode and confirm the app behaves as below (degrades loudly +
recovers, never hangs or silently fails). One row = one test.

| # | Force this | Expected behaviour | Recovery |
|---|---|---|---|
| D1 | **No drive / no disc** | Drive picker shows "(no drives found)"; *Tools → Diagnose drive access* explains why | insert disc / fix below |
| D2 | **Drive not readable** (user not in the drive's group) | Diagnosis names the exact `sudo usermod -aG … $USER` fix | run it, log out/in |
| D3 | **No FUSE** (minimal host) | AppImage won't mount | run `APPIMAGE_EXTRACT_AND_RUN=1 ./…AppImage` |
| D4 | **podman/distrobox absent** | Wizard offers to install them (one polkit prompt) | accept |
| D5 | **Container has no network** during a known rip | GUI auto-heals: re-rips as `--unknown`, tags from the on-screen metadata | none needed |
| D6 | **Cold container** (first launch after boot) | window appears + stays responsive; probes finish in the background | wait a few seconds |
| D7 | **Disc not ready** (scanned while spinning up) | friendly "couldn't read the TOC… click Rescan disc" — *not* a traceback | **Rescan disc** |
| D8 | **Disc unknown to MusicBrainz** | numbered blank rows + offer to *Rip as Unknown Album*; no TTY prompt | rip as unknown |
| D9 | **CD-R (home-burned)** | whipper: enable "Continue on CD-R"; cyanrip: just works | — |
| D10 | **Scratched / unreadable track** | clear "Track N couldn't be read… clean it / enable Keep going" hint | clean disc, or Keep going |
| D11 | **Drive offset unknown** (drive not in the list) | rip is blocked with a "set up your drive first" prompt → wizard | Detect from a CD, or type it |
| D12 | **Cancel mid-rip** | drive spins down; if not, auto-force-stop after a few seconds (or **Force stop**) | — |
| D13 | **Update downloaded over the old file's path** | integration still offered; menu entry/icon fixed | accept the offer |
| D14 | **Quit while a rip / wizard / update runs** | clean shutdown (threads joined); no crash/zombie | — |

Each D-row that misbehaves → file a report with the log.

---

# Single-feature cases (Test 1–9)

The individually-gated deep cases. Each is self-contained: do the steps, record
the result, follow **If it fails**. Several are unblocked by — or feed back
into — the acceptance run above and link to it rather than repeating it.

## Recognized-CD walkthrough (ties the cases together)

A **recognized CD** (in MusicBrainz, ideally in AccurateRip + CTDB — a popular
album works best) exercises almost everything in one sitting:

1. **Calibrate the drive** with the disc inserted — **Tests 3 & 4**. Capture the
   `drive analyze` and `offset find` output.
2. **Rip it** from the GUI → confirm every track's **Test CRC == Copy CRC** and
   the AccurateRip confidence. Screenshot — **Test 5**.
3. **CTDB-verify the rip** — **Test 1**, the highest-value step:
   ```bash
   source .venv/bin/activate
   python3 scripts/ctdb_verify.py "$HOME/Music/rips/<Artist>/<Album>/"
   ```
   Paste the full output (TOC, lookup URL, verdict) — this validates or corrects
   the `toc=` wire format and the CRC.
4. If you have a second recognized disc, repeat step 3: a standard studio album
   is the cleanest CTDB data point, so two discs disambiguate "wrong wire format"
   (both fail) from "this pressing isn't in CTDB" (one fails).

> CTDB's CRC needs host `flac`. If `flac --version` fails, export it from the
> container once: `distrobox enter ripping -- distrobox-export --bin /usr/bin/flac`.
> Even without it, the **lookup half** of Test 1 still validates the wire format.

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

### Test 1b — [x] wire CTDB verify into the GUI — BUILT 2026-06-17 (experimental seam)
The GUI wiring shipped ahead of the hardware validation, kept safe behind the
`crc.CRC_VALIDATED=False` seam (a match shows as **EXPERIMENTAL**, never
"verified"). As built: `workers/ctdb_worker.py::CtdbVerifyWorker` (off-thread
lookup + decode, emits `finished(result)`; joins the post-rip metaflac thread
first so it never decodes a file mid-rewrite); a CTDB verdict line under the
AccurateRip table in `ui/rip_progress.py` (`set_ctdb_status`/`set_ctdb_result`
+ the pure `ctdb_verdict_line` renderer); a `Config.ctdb_verify_after_rip`
Settings toggle (default off — it's a network call); tests for the worker
signal flow, the UI render (incl. experimental labelling), and the off-thread
MainWindow wiring.

**Remaining (depends on Test 1):** once Test 1 confirms the `toc=` wire format
and a trustworthy `match`, flip `crc.CRC_VALIDATED` → `True` (the single seam)
so matches read "verified ✓", and export host `flac` in the wizard for the
decoder.

## Test 2 — [ ] CTDB repair direction (Phase 2, KDD-14)

**Goal:** decide and prototype parity repair. **Depends on Test 1 passing.**

**Open decision (needs your call):** `ctdb-cli` is **C#/.NET 10**, so bundling
it in the AppImage is heavy. Choose: (a) bundle a self-contained .NET publish,
(b) route it through the dependency subsystem as an *optional* user-installed
tool (like Picard), or (c) revisit a pure-Python `CUETools.Parity` port. (Record
the choice in `TASKS.md` / KDD-14.)

**Steps (exploratory, on a disc that ends with uncorrectable errors)**
1. Install `ctdb-cli` (`github.com/Masterisk-F/ctdb-cli`).
2. Run `ctdb-cli verify <cue>` then `ctdb-cli repair <cue>` on the damaged rip;
   capture the exact CLI surface + `--xml` output shape.
3. Record whether repair reconstructs + re-verifies, and the parity download size.

**Record:** chosen bundling option `____`; `ctdb-cli` CLI/output notes `____`.

## Test 3 — [ ] `whipper drive analyze` success output

**Goal:** capture the verbatim success output so the README/wizard can show
"you should see this." (A5 does the functional check; this banks the strings.)

**Steps**
1. Insert any audio CD. Run `Tools → Set up drive…` (and/or `whipper drive
   analyze` in the `ripping` container directly).
2. Copy the full successful output.

**Record:** paste the success lines, then add them to README Step 5 and the
drive-setup wizard's help text:
```
__________
```

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

## Test 5 — [ ] GUI screenshot

**Goal:** confirm the GUI looks right on Bazzite KDE Plasma 6 and add a
screenshot to the top of the README.

**Steps**
1. Launch the published AppImage on Bazzite/KDE.
2. Screenshot the main window (ideally mid-rip, track table populated, current
   track highlighted).
3. Save to `docs/img/whipper-gui.png` and embed it near the top of `README.md`.

**Record:** screenshot committed? `____`; any layout issues `__________`.

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

## Test 7 — [ ] PyPI go-live (maintainer credential)

**Goal:** make `pipx install whipper-gui` work from PyPI. The `publish-pypi.yml`
workflow is already in place (Trusted Publishing).

**Steps**
1. On PyPI: **Publishing → add a pending publisher** with — project
   `whipper-gui`, owner `rmccann-hub`, repository
   `Whipper-GUI-Frontend---CD-Rip`, workflow `publish-pypi.yml`, environment
   `pypi`.
2. Cut a release the usual way (bump `__version__`, roll `CHANGELOG.md`, dispatch
   the Release workflow — see `CLAUDE.md` *CI / release*).
3. Watch the **Publish to PyPI** action; confirm the release on PyPI.
4. On a clean machine: `pipx install whipper-gui` and launch `whipper-gui`.

**Record:** published version `____`; `pipx install` works? `____`. Then drop
the "if it's not on PyPI yet" caveat from the README.

## Test 8 — [ ] cyanrip backend: install + parity run (KDD-18)

**Goal:** prove the cyanrip backend end-to-end on real hardware — the wizard
installs it, a rip completes with correct tags/paths, and it clears the track-3
failure whipper's >587-offset cd-paranoia bug causes on the BDR-209D.

**Steps**
1. Settings → Ripping backend → **cyanrip (experimental)** → Save. Accept the
   "Install cyanrip?" offer (or Tools → Set up Whipper GUI…).
2. Watch the wizard: the *cyanrip backend (in container)* step should enable the
   COPR (`barsnick/non-fed`) **inside the container only** and `dnf install
   cyanrip`; the export step should produce `~/.local/bin/cyanrip`. Record any
   step that fails verbatim.
3. Restart the app (backend choice is read at startup). Confirm the drive is
   detected and the disc panel fills in (DiscID/CDDB from `cyanrip -I -N`).
4. Rip the Police disc (the one whipper fails on track 3) as a known disc.
   - [ ] Output lands under `Artist/Album/` per the same template as whipper.
   - [ ] FLAC tags match the track table (album, artist, per-track titles, year,
         `MUSICBRAINZ_ALBUMID`).
   - [ ] **Track 3 rips and verifies** (the whole point).
   - [ ] Known cosmetic gap: progress bars don't move during the rip — confirm
         the rip still finishes and reports success.
5. **Parity:** compare its per-track **EAC CRC32** to the baseline table in
   **Part B** (and to a whipper rip of the same disc where both succeeded).
6. Record cyanrip's `.log` filename + a copy of its contents — it feeds the
   fidelity-verdict parser.

**Record:** cyanrip version `____`; track 3 verified? `____`; CRCs match the
Part B baseline? `____`; whipper? `____`; log file name `____`.

## Test 9 — [ ] In-app uninstaller: deep no-terminal run

**Goal:** prove the no-terminal uninstall on real hardware — everything the app
installed disappears; Distrobox/podman and music survive. (This is the deep
version of A1/A2/A11; do it LAST in a session, or on a sacrificial setup.)

**Steps**
1. Note what exists first: `ls ~/.local/bin/{whipper,metaflac,cyanrip,whipper-gui}`,
   `distrobox list`, the app menu entries, `~/.config/whipper{,-gui}`,
   `~/.local/share/whipper-gui`.
2. Launch the **Uninstall Whipper GUI** menu entry (tests `--uninstall` mode),
   or Tools → Uninstall Whipper GUI… inside the app.
3. Leave both checkboxes ticked → Uninstall → confirm. Watch the per-step log;
   record any ✗ verbatim.
4. Verify gone: all of step 1's items, the menu entries (may need a
   re-login/menu refresh), and — if launched from the AppImage — the AppImage
   file itself.
5. Verify KEPT: `distrobox --version` and `podman --version` still work; any
   other containers still listed; `~/Music/rips/` untouched.
6. Reinstall from the Release AppImage and confirm the first-run offers (menu
   integration, host wizard) come back fresh — proving the uninstall really
   removed the config flags.

**Record:** all removed? `____`; distrobox/podman intact? `____`; music intact?
`____`; reinstall clean? `____`.

---

## Reporting template

```
### Test report
Environment : (paste the §0 block)
Ran         : A1–A11 ✓/✗ per step  |  Part C row: ____  |  Part D rows: ____
EAC parity  : whipper CRCs match Part B baseline? ✓/✗   cyanrip? ✓/✗   (attach both .logs + EAC log)
Cases       : Test N ✓/✗ + Record-box values
Failures    : (step/case ID + what happened, verbatim)
Logs        : ~/.local/share/whipper-gui/log.txt  +  the rip .log
```

File issues at the repo's Issues page (Help → About has the link). Keep one
issue per distinct failure.

## After a test passes

- Update the marker (`[ ]` → `[x]`, or `[?]` on failure) with the date and notes.
- Land the follow-up the test unblocks (Test 1 → GUI wiring; Tests 3/4/5/6 →
  README updates; Test 7 → README caveat removal).
- Update `TASKS.md` and `CHANGELOG.md`.
</content>
