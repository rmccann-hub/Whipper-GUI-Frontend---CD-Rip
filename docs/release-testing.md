# Release / acceptance testing procedure

> **Who this is for.** The maintainer running a full pre-release check, and the
> external testers about to come on board. It's the step-by-step "exactly what
> to do" for a clean uninstall → fresh install → rip → verify cycle, the
> **EAC output-parity** check, and the **distribution + problem-permutation
> matrices** to spread across testers.
>
> For the deep, single-feature hardware cases (CTDB verify CRC, `drive analyze`
> / `offset find` strings, PyPI go-live, the cyanrip parity run), see
> **[`test-plan.md`](test-plan.md)** — this document is the *end-to-end* run and
> the *coverage matrix*; that one is the individual gated cases.

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
click **Detect**, then Save (or type it).

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
the full procedure and what "exact" means. Record per-track CRCs side by side.

### A8 — [ ] cyanrip backend rip
Settings → **Ripping backend → cyanrip** → Save → accept the install offer →
restart. Re-rip the same disc. *Expected:* same files/tags/**cover art** (the
app fetches it from the Cover Art Archive for cyanrip), and a cyanrip fidelity
verdict. Compare its per-track **EAC CRC32** to the EAC baseline too (Part B).
*This is the backend that avoids whipper's >587-offset bug — see test-plan Test 8.*

### A9 — [ ] Edge discs
- **Unknown disc / offline:** *File → Rip as Unknown Album…* → placeholders →
  Start → FLACs tagged from what you typed, cover art fetched if a release was
  picked. *Expected:* no MusicBrainz TTY prompt ever surfaces.
- **CD-R (home-burned):** Settings → **Continue on CD-R** (whipper) → rips;
  cyanrip handles CD-Rs with no switch.

### A10 — [ ] In-app update (when a newer release exists)
**Help → Check for updates.** *Expected:* if newer, it downloads (cancellable
progress), shows phase labels (Downloading → Verifying → *"Installing — almost
done, please don't close…"*), verifies the checksum, installs to `~/Applications`,
and offers to **restart**. The window must **not** go "Not Responding," and
Cancel/✕ must stay responsive throughout (the 2026-06-13 freeze fixes).

### A11 — [ ] Uninstall again (clean removal)
Repeat A1 + A2. *Expected:* fully clean, music untouched, no leftovers.

---

## Part B — EAC output parity (making the rip *exact*)

The product goal is a rip whose **audio is bit-identical to EAC's**, provable by
matching CRCs. UI differences don't matter; the bytes do.

**What must match the EAC baseline (`tests/fixtures/eac_baseline_police_classics.log`):**

| Field | EAC baseline | Where ours shows it |
|---|---|---|
| Per-track **CRC32** | the table in EAC's log | whipper **Test/Copy CRC**; cyanrip **EAC CRC32** |
| Read **offset** | `667` | Settings / drive setup; printed in our `.log` |
| AccurateRip | confidence per track | our rip-log panel + `.log` |

**Procedure:**
1. Rip the disc with our app (A6 whipper, A8 cyanrip).
2. Open both `.log`s and the EAC log. For each track, compare the CRC32.
3. Record them in the table in [`test-plan.md`](test-plan.md) **Test 8**.

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

## Reporting template

```
### Test report
Environment : (paste the §0 block)
Ran         : A1–A11 ✓/✗ per step  |  Part C row: ____  |  Part D rows: ____
EAC parity  : whipper CRCs match EAC? ✓/✗   cyanrip? ✓/✗   (attach both .logs + EAC log)
Failures    : (step ID + what happened, verbatim)
Logs        : ~/.local/share/whipper-gui/log.txt  +  the rip .log
```

File issues at the repo's Issues page (Help → About has the link). Keep one
issue per distinct failure.
