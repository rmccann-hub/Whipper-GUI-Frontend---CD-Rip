# Whipper GUI

A Linux GUI front-end for the [`whipper`](https://github.com/whipper-team/whipper) audio-CD ripping CLI. Aims for EAC-equivalent (Exact Audio Copy) archival quality on Linux, packaged as a single-file AppImage.

> **Status: v0.1.0 — public test release.** Implemented end-to-end with 525 unit tests and validated on real Bazzite hardware: a full 16-track rip *through the published AppImage*, with every track's Test CRC matching its Copy CRC. Recent additions: a **Force stop** for runaway drives on cancel, AppImage **desktop integration** (`install-appimage.sh`), and a **Help menu** (About + User Guide). This is an early release for wider testing — expect rough edges, and please [open an issue](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/issues) for anything you hit.

## At a glance

- **Linux only.** Primary target is Bazzite KDE Plasma 6; should work on any modern desktop Linux running Qt 6 (Fedora, Arch, Ubuntu, Tumbleweed).
- **Runs whipper inside Distrobox.** The GUI calls the host-exported `whipper` binary; it never bundles whipper or tries to install it. This is intentional — see [PLANNING.md §8 KDD-07](PLANNING.md).
- **Single-file AppImage** for the GUI itself; no system-level installs required.
- **Bypasses whipper's interactive prompt** by querying MusicBrainz directly and passing `--release-id` to whipper. You never see a terminal prompt.
- **Distribution model:** AppImage primary, `pipx` secondary.

---

## Installation

### Quickstart for testers (the short version)

**One command installs everything** — the *host stack* (Distrobox + whipper, which does the actual ripping) and the *GUI* (the AppImage), plus an app-menu entry, a Desktop icon, and an **Uninstall Whipper GUI** shortcut:

```bash
curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/main/install.sh | bash
```

Prefer to download and run it yourself? Grab `install.sh` from the [Releases page](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/latest), then `bash install.sh`. Useful flags: `--dry-run` (preview), `--no-host` (GUI only, host stack already set up), `--appimage PATH` (use a local AppImage). First run takes ~20–40 min because it builds the container.

Then, inside the GUI: **Tools → Set up drive…** to calibrate your drive's read offset (one time), insert a CD, and rip. To remove everything later, use the **Uninstall Whipper GUI** shortcut (or see [Uninstalling](#uninstalling)).

> **Already have whipper + Distrobox set up** (e.g. re-installing on the same machine, or installing the GUI on a second box that shares the stack)? Skip the host build and just add the GUI: `curl -fsSL …/install.sh | bash -s -- --no-host` (or `bash install.sh --no-host`).

> Why two pieces under the hood? The GUI can't rip without the host stack — that's by design ([why](PLANNING.md)). `install.sh` just sets up both for you; you can still do each step by hand (below).

#### Supported distributions

The one-line installer works on any modern desktop Linux. It auto-detects your package manager to install Distrobox + podman; everything ripping-related runs in a Fedora container, so your host distro only needs Distrobox and a container backend.

| Distro family | Auto-handled by the installer? | Notes |
|---|---|---|
| **Fedora / Bazzite / Silverblue / RHEL / CentOS** | ✅ Fully | Bazzite & Silverblue ship Distrobox + podman already; nothing extra. |
| **Ubuntu / Debian (24.04+)** | ✅ Fully | Installs `podman` too (the `distrobox` package only *recommends* it). |
| **Linux Mint / Pop!_OS / elementary** | ✅ Fully | Ubuntu-based — same path as Ubuntu/Debian. |
| **Arch / Manjaro / EndeavourOS** | ✅ Fully | Installs `distrobox` + `podman` via `pacman`. |
| **openSUSE Leap / Tumbleweed** | ✅ Fully | Installs `distrobox` + `podman` via `zypper`. |
| **Other / older distros** | ⚠️ Fallback | Uses Distrobox's official installer. Make sure `podman` (or `docker`) is present first. |

If the installer can't set up the host stack on your distro, do [the manual steps](#manual-steps) once — they work everywhere and are the source of truth.

The rest of this section is the long form — read it if the quickstart hits a snag or you'd rather do each step by hand.

### Fast path — one command (Steps 1-4 + 7)

[`setup-host.sh`](setup-host.sh) automates the host setup: it installs Distrobox (if needed), creates the `ripping` container, installs whipper + flac inside it, exports the binaries to your host, then clones this repo and runs `dev-setup.sh` (venv + editable install + app-menu shortcut).

```bash
# From a fresh clone:
bash setup-host.sh

# …or straight from the web (no clone needed first):
curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/main/setup-host.sh | bash
```

Useful flags: `--dry-run` (print every command, change nothing), `--yes` (skip confirmations), `--no-gui` (host stack only). It's idempotent — safe to re-run. It does **not** calibrate your drive (do that in the GUI: **Tools → Set up drive…**) or install Picard (the GUI offers that on first run).

Prefer to do it by hand, or the script hit a snag? The manual steps below are the source of truth.

### Manual steps

There are five things to set up. Plan on **20-40 minutes** the first time. Once it's done, you don't touch most of it again.

| Step | What | Why |
|------|------|-----|
| 1 | Install Distrobox | Provides an isolated Fedora environment for whipper |
| 2 | Create a `ripping` container | Where whipper actually lives |
| 3 | Install whipper + flac in the container | The tools that do the ripping |
| 4 | Export them to the host | So Whipper GUI can find them |
| 5 | Detect your drive's read offset | One-time calibration for accurate rips |
| 6 | Install MusicBrainz Picard *(optional)* | Manual tag editing for unknown discs |
| 7 | Install Whipper GUI | This project |

> **If a step doesn't behave as written:** skip to the [Troubleshooting](#troubleshooting) section near the end of this README. The common surprises — missing `pkg_resources`, missing `whipper.conf`, HTTPS clone authentication failure — all have entries there.

### Step 1 — Install Distrobox

Distrobox lets you run a different Linux distribution's tools alongside your host system. It's the recommended way to run whipper on immutable distros like Bazzite.

> **Distrobox needs a container backend** — `podman` (recommended) or `docker`. Bazzite, Fedora Silverblue, and most atomic distros ship podman already. On **Ubuntu/Debian** it isn't guaranteed, so install it alongside Distrobox (the commands below do this). If `distrobox create` later fails with *"Cannot find a container manager"*, a missing backend is why — `sudo apt install podman` fixes it.

**On Bazzite (already pre-installed):**

```bash
distrobox --version
```

If you see a version, skip to Step 2.

**On Fedora / Fedora Silverblue:**

```bash
sudo dnf install distrobox
```

**On Arch / Manjaro:**

```bash
sudo pacman -S distrobox
```

**On Ubuntu / Debian (24.04+):**

```bash
sudo apt install distrobox podman
```

(Installing `podman` explicitly here is the Ubuntu-specific gotcha — the `distrobox` package only *recommends* it, so on minimal installs it can be absent and `distrobox create` then fails.)

**On Linux Mint / Pop!_OS / elementary OS:**

These are Ubuntu-based, so the Ubuntu command works:

```bash
sudo apt install distrobox podman
```

**On openSUSE Leap / Tumbleweed:**

```bash
sudo zypper install distrobox podman
```

(If your openSUSE version doesn't package `distrobox` yet, use the one-line installer under "older systems" below — but install `podman` with `zypper` first, since the installer doesn't pull a backend.)

**On older systems:**

Distrobox has a one-line installer:

```bash
curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh
```

Verify with `distrobox --version`.

### Step 2 — Create the `ripping` container

Create a Fedora-based container named `ripping`. The brief specifies Fedora 40; later Fedora versions also work — substitute `:41` or `:latest` if you prefer.

```bash
distrobox create --name ripping --image registry.fedoraproject.org/fedora-toolbox:latest
```

Distrobox will prompt to pull the image — type **Y** and press Enter. The download is about 600 MB the first time. Once it finishes:

```bash
distrobox enter ripping
```

You're now inside the container. The prompt should change to show you're in the `ripping` environment. To leave at any time, type `exit`.

> **Why `:latest` and not `:40`?** The brief specifies Fedora 40; newer Fedora releases (41, 42, 43, 44…) also work and ship newer security fixes. `:latest` resolves to whatever's current. If you specifically want to pin to Fedora 40 to match the brief exactly, swap `:latest` for `:40`.

### Step 3 — Install whipper and metaflac

Inside the container (your prompt should still show you're in `ripping`):

```bash
sudo dnf install whipper flac python3-setuptools
```

The `python3-setuptools` package is needed because whipper imports `pkg_resources` from setuptools, and recent Fedora releases (44+) don't pull it in automatically. Without it you'll see a `ModuleNotFoundError: No module named 'pkg_resources'` traceback when you try to run whipper.

Verify both tools are installed:

```bash
whipper --version
metaflac --version
```

`whipper` should report `0.10.0` or newer. `metaflac` is part of the `flac` package.

> **You'll see a deprecation warning above the version number** that looks like this:
>
> ```
> UserWarning: pkg_resources is deprecated as an API.
> ```
>
> That's normal. Whipper itself uses an old setuptools API; the warning is informational, the version number that follows means whipper still works. The GUI suppresses this when it calls whipper as a subprocess.

### Step 4 — Export the binaries to your host

Still inside the container, export both binaries:

```bash
distrobox-export --bin /usr/bin/whipper
distrobox-export --bin /usr/bin/metaflac
```

This creates wrapper scripts at `~/.local/bin/whipper` and `~/.local/bin/metaflac` on the **host** (not in the container). Those wrappers transparently enter the container when called, so from the host's perspective whipper looks like a regular installed program.

Now leave the container:

```bash
exit
```

You're back on the host. Verify the wrappers work:

```bash
which whipper
# → /home/<you>/.local/bin/whipper

whipper --version
# → whipper 0.10.0
```

If `which` returns nothing, your `~/.local/bin` isn't on `$PATH`. Most desktop Linux setups put it there automatically; if yours doesn't, add this to `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then open a new terminal.

### Step 5 — Detect your drive's read offset

Every optical drive reads audio slightly off from where it "should" — by a positive or negative number of samples. For bit-perfect archival rips that match AccurateRip's database, whipper needs to know your drive's offset.

> **Before you start:** insert a commercial audio CD into your optical drive (any common pressing — Pink Floyd, Beatles, Metallica, anything not a CD-R or burned mix). Both commands below need a real CD that's in [AccurateRip's database](https://www.accuraterip.com) — most retail discs are.

> **No commercial CD handy (e.g. you only have CD-Rs)?** You can skip this terminal step and set the offset from inside the GUI instead: the drive-setup wizard (offered on first launch, or **Tools → Set up drive…**) has a manual-entry field. Look your drive's offset up at [accuraterip.com/driveoffsets.htm](https://www.accuraterip.com/driveoffsets.htm) and type it in — the GUI applies it via `whipper --offset` without touching `whipper.conf`.

The settings whipper learns about your drive live in `~/.config/whipper/whipper.conf`. **This file does not exist yet** — it's created automatically the first time whipper writes to it (i.e., when you run one of the commands below). Looking for it before that point will turn up nothing, and that's normal.

> **Where `~` actually is on Bazzite/Silverblue:** `~` for your user expands to `/var/home/<username>` (not `/home/<username>`). `~/.config/whipper/whipper.conf` is the same as `/var/home/<username>/.config/whipper/whipper.conf` — just different ways of writing it. Distrobox passes your host home through to the container, so the file lives in one place visible from both sides.

**The easy way** — let whipper figure it out:

```bash
whipper drive analyze
whipper offset find
```

Both commands probe your drive and write results into `~/.config/whipper/whipper.conf` automatically, creating the file (and the `~/.config/whipper/` directory) on first write.

`offset find` is the longer-running one (a few minutes). It will **eject and re-ingest the disc several times** — that's expected, not a malfunction. Don't interrupt it, and don't close the terminal until it returns to a prompt.

After they finish, confirm the file landed:

```bash
ls -la ~/.config/whipper/
cat ~/.config/whipper/whipper.conf
```

You should see a `[drive:...]` section with `defeats_cache` and `read_offset` values.

**The manual way** — look up your drive in the [AccurateRip offset list](https://www.accuraterip.com/driveoffsets.htm), then create or edit `~/.config/whipper/whipper.conf` by hand:

```bash
mkdir -p ~/.config/whipper
${EDITOR:-nano} ~/.config/whipper/whipper.conf
```

Add a section like:

```ini
[drive:PIONEER :BD-RW   BDR-209D:1.51]
defeats_cache = True
read_offset = 667
```

The section header is `[drive:<vendor> :<model>:<firmware>]`. Get the exact string (including odd spacing) from `whipper drive list`:

```bash
whipper drive list
# → drive: /dev/sr0, vendor: PIONEER, model: BD-RW   BDR-209D, release: 1.51
```

The pattern is `drive:<vendor> :<model>:<release>` — note the space after the vendor name and before the colon.

`defeats_cache = True` means your drive supports the audio-cache defeat command (essential for accurate ripping). If `whipper drive analyze` couldn't confirm this for your drive, leave the line off — whipper will warn but still rip.

### Step 6 — Install MusicBrainz Picard *(optional)*

Picard is what you'll use to manually fix tags for discs MusicBrainz doesn't recognize. The GUI installs it as a Flatpak (it auto-launches it via `flatpak run`), and offers to do so automatically when you first need it.

> **Ubuntu/Debian prerequisite:** the GUI installs Picard through **Flatpak**, which isn't installed on Ubuntu by default. Install it once and the GUI's auto-install works as-is afterwards (the GUI's install command points at a `.flatpakref` that adds the Flathub remote for you, so you don't need a separate `flatpak remote-add` step):
>
> ```bash
> sudo apt install flatpak
> ```
>
> Bazzite, Fedora Silverblue, and most KDE/GNOME spins already ship Flatpak. Picard is optional — if you skip it, the GUI simply lists it as "Optional (not installed)" and never nags; you only need it for hand-editing tags on unrecognized discs.

To pre-install Picard yourself rather than letting the GUI do it:

```bash
flatpak install --user flathub org.musicbrainz.Picard
```

Verify:

```bash
flatpak run org.musicbrainz.Picard --version
```

Whipper GUI will auto-launch Picard with the rip folder when you mark a disc as Unknown Album, *if* you enable the toggle in Settings.

### Step 7 — Install Whipper GUI

> **Recommended: Method A (AppImage).** As of v0.1.0 it's published as a downloadable release asset — this is the simplest path for most people. Method B (`pipx` from PyPI) publishes automatically on each tagged release (Trusted Publishing); if it's not on PyPI yet, install from a checkout (see Method B). Method C runs the GUI from a source clone and is aimed at developers.

Pick **one** of the methods below.

#### Method A — AppImage (recommended for end users)

Download the latest `whipper-gui-x86_64.AppImage` from the **[Releases page](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/latest)**, then:

```bash
chmod +x whipper-gui-x86_64.AppImage
./whipper-gui-x86_64.AppImage
```

That's it — the AppImage bundles Python, Qt, and the GUI's dependencies, so there's nothing else to install on the GUI side. (You still need the host stack from Steps 1-4 for ripping to work.)

**Want a menu entry / desktop icon?** An AppImage doesn't add one itself. Use the `install-appimage.sh` helper (released alongside the AppImage):

```bash
bash install-appimage.sh                 # finds whipper-gui*.AppImage in . / ~/Downloads / ~/Applications
bash install-appimage.sh --uninstall     # remove the menu entry + desktop icon
```

It parks the AppImage in `~/Applications/`, adds an app-menu entry and a Desktop icon (using the bundled icon), and refreshes the KDE/GNOME menu cache. Alternatively, install [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) once and it offers to integrate any AppImage you double-click.

> **On a FUSE-less host** (rare on desktop Linux, but some minimal setups): run with `APPIMAGE_EXTRACT_AND_RUN=1 ./whipper-gui-x86_64.AppImage`, or see [AppImage won't launch](#appimage-wont-launch) in Troubleshooting.

#### Method B — pipx (recommended for technical users)

`pipx` installs Python applications in isolated environments and adds them to your `PATH`.

Install pipx if you don't have it (Bazzite ships with it):

```bash
sudo dnf install pipx     # Fedora / Bazzite
# or
sudo apt install pipx     # Ubuntu / Debian
```

Then install Whipper GUI:

```bash
pipx install whipper-gui
```

> Releases publish the wheel to PyPI automatically (via Trusted Publishing on each tagged release). If `pipx install whipper-gui` can't find it yet — e.g. before the first PyPI-published release — install from a local checkout instead: `git clone …` then `pipx install .` from inside the repo.

Run with `whipper-gui` from any terminal.

#### Method C — From source (for developers)

> The repository is **public**, so no authentication is needed to clone over HTTPS. (If you plan to push changes, set up SSH or `gh auth login` — but for just running from source, a plain clone works.)

Clone and install:

```bash
git clone https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git
cd Whipper-GUI-Frontend---CD-Rip
```

The default `main` branch contains the full source — no branch switch needed.

From here you have two options.

**Option 1 — one-shot setup script (recommended):**

```bash
bash dev-setup.sh
source .venv/bin/activate
whipper-gui
```

`dev-setup.sh` creates a venv, upgrades pip, and runs `pip install -e .` for you. Run it again later (after `git pull`) to refresh dependencies if anything's been added.

**Option 2 — manual steps (same effect, if you want to see each one):**

```bash
# Create a virtual environment. On Bazzite, Fedora 38+, Ubuntu 24.04+,
# and other distros with PEP 668 enforcement, this is required — a
# plain `pip install` against the system Python will refuse with
# "error: externally-managed-environment".
python3 -m venv .venv
source .venv/bin/activate

# pip in a fresh venv is usually outdated; upgrade before installing
# anything else. Avoids "WARNING: ... newer version of pip available."
pip install --upgrade pip

# Install the package in editable mode. From now on, anything you
# edit in src/whipper_gui/ is picked up the next time you run the GUI.
pip install -e .

# Run the GUI. The console-script entry point lives in .venv/bin
# (added to PATH by the `activate` line above).
whipper-gui
```

To re-enter the same environment in a future terminal session:

```bash
cd ~/Whipper-GUI-Frontend---CD-Rip
source .venv/bin/activate
whipper-gui
```

To leave the venv: `deactivate`.

To build an AppImage from your local checkout:

```bash
pip install --user build "python-appimage>=1.4,<2"
bash build/build_appimage.sh
```

The resulting `whipper-gui-x86_64.AppImage` appears at the repo root. See [`build/python-appimage/README.md`](build/python-appimage/README.md) for details.

---

## Audio output: what you get, what you don't

This GUI doesn't decide how audio is encoded — **whipper does**, and its encoder settings are hardcoded upstream. Worth knowing what those settings are.

### FLAC (v1, the only supported format)

Whipper invokes the `flac` binary with this exact command, once per track:

```
flac --silent --verify -o <outfile> -f <infile>
```

| Flag | What it does | Archival implication |
|------|--------------|----------------------|
| `--silent` | Suppress per-file progress chatter | Cosmetic |
| `--verify` | Re-decode the FLAC and confirm it matches the input | **The archival-quality bit.** Whipper proves every track is bit-perfect reversible. |
| `-o <outfile>` | Output path | Where the FLAC lands |
| `-f` | Force-overwrite | Required because whipper pre-creates the output file |

You'll notice no `-0` through `-8` compression flag. Whipper relies on `flac`'s default, which is **compression level 5** (balanced — slower than `-0`, smaller than `-0`, looser than `-8`).

**Compression level is not configurable** from this GUI, from `whipper.conf`, or from any whipper CLI flag. It's baked into `whipper/program/flac.py` upstream. If you specifically want `-8` (best compression — ~5% smaller files, slower encode), the realistic path is post-processing:

```bash
# Re-encode in place to -8 after a rip.
for f in *.flac; do
    flac -8 --best --verify -f "$f"
done
```

Why isn't this a bigger deal? **All FLAC compression levels are lossless.** `-0` and `-8` produce identical decoded audio — only file size differs. Whipper's `--verify` proves the bit-perfect property regardless of level. The choice of `-5` vs `-8` is purely a file-size tradeoff; archival fidelity is the same.

If this changes in the future (whipper exposes compression as a config knob, or someone forks it), the GUI's Settings dialog can grow a "FLAC compression level" field. The architecture supports it; whipper just doesn't.

The full FLAC encoder reference, including every flag whipper *isn't* using, is at [xiph.org/flac/documentation_tools_flac.html](https://xiph.org/flac/documentation_tools_flac.html).

### MP3 and WAV (P1 — not in v1)

The brief lists MP3 and WAV as backlog. Once v1 ships, the plan is:

- **WAV:** `sox` re-encodes the FLAC files to WAV after rip. No quality loss (FLAC is lossless; WAV is uncompressed PCM).
- **MP3:** `lame` re-encodes the FLAC files to MP3 with sensible defaults (probably VBR `-V0` for "indistinguishable from source") and optionally configurable.

Both encoder backends will be detected through the same dependency self-management subsystem as everything else — no bespoke install code. See [TASKS.md](TASKS.md) P1 section.

If you need MP3 *today* and don't want to wait for P1, you can transcode by hand after a rip:

```bash
# MP3 VBR V0 (transparent to source)
for f in *.flac; do
    lame -V 0 "$f" "${f%.flac}.mp3"
done

# WAV
for f in *.flac; do
    sox "$f" "${f%.flac}.wav"
done
```

### Compared to EAC's bit-perfect settings

The widely-cited [Perfect CD Ripping to FLAC with Exact Audio Copy guide](https://flemmingss.com/perfect-cd-ripping-to-flac-with-exact-audio-copy/) is the gold standard for archival rips on Windows. Here's how this GUI's pipeline maps to it. Full audit in [PLANNING.md KDD-13](PLANNING.md).

**Matches the guide today:**

- Secure read mode (cdparanoia, whipper's default)
- Defeat audio cache (per-drive, set by `whipper drive analyze`)
- Read offset calibration (per-drive, set by `whipper offset find`)
- AccurateRip verification (whipper queries; we render the v1/v2 confidence)
- High error-recovery quality (cdparanoia is always at maximum)
- No normalization
- FLAC `--verify` (proves bit-perfect reversibility)
- `.log` file written after every rip
- Gap detection in "Secure" mode (cdrdao)
- Status-report checksum (SHA-256)

**Not configurable from the GUI** (whipper hardcodes these upstream):

- **FLAC compression level.** EAC's guide says `-8 --best`; whipper uses flac's default (`-5`). Archival quality is identical at any compression level — only file size differs. See "FLAC (v1)" above for the post-rip re-encode workaround if you specifically want `-8`.

**Not possible on Linux today:**

- **C2 error pointers.** Cdparanoia is the Linux secure-read primitive; it doesn't use C2.
- **EAC-style signed log checksum.** Whipper writes SHA-256, which is weaker as a forensic signal. CTDB and audiophile forums historically recognize EAC's signed checksum specifically.
- **AccurateRip submission** (writing new entries to the database). Blocked by AccurateRip's operators, who accept submissions only from EAC and dBpoweramp. Verification (reading) works fine — see "AccurateRip" in the audit above.
- **CTDB metadata plugin.** CUETools' database is queryable in principle but no Linux client exists. CTDB verification is on the P1 backlog (see [TASKS.md](TASKS.md)).

**Now in Settings** (EAC toggles whipper supports, surfaced in the Settings dialog — all shipped in the v0.1.x line):

- Cover art — fetch + embed in FLAC, save next to it, or both (defaults to *embed*)
- Force overread into lead-out
- Max retries per track (default 5)
- Keep going on track failure
- Continue ripping CD-Rs
- Auto-eject after a successful rip, plus read-offset calibration via the drive-setup wizard

See [TASKS.md](TASKS.md) under "EAC bit-perfect parity gaps" for the history.

---

## First run

When you launch Whipper GUI for the first time:

1. **Dependency check.** The GUI verifies whipper, metaflac, and Picard are reachable. If anything's missing, it pops a dialog with one of three resolutions:
   - **Auto-install** (Picard): one OK and it runs `flatpak install --user`.
   - **Pending installs:** a checklist for items that need batching or confirmation.
   - **Manual install:** a copyable search string for items like `libdiscid` that need root + reboot.

2. **Drive offset (first launch only).** whipper can't rip until your drive's read offset is set. If none is configured yet, the GUI offers the drive-setup wizard once. You can **auto-detect** it (insert a commercial CD that's in AccurateRip) or **enter it by hand** (look your drive up at [accuraterip.com/driveoffsets.htm](https://www.accuraterip.com/driveoffsets.htm) — handy if you only have CD-Rs). It's a one-time, dismissible prompt; afterwards re-run it anytime from **Tools → Set up drive…**.

3. **Pick a drive.** The dropdown at the top of the window lists everything `whipper drive list` returns. Click Refresh if you plug in a drive after launch.

4. **Insert a CD.** The GUI fetches the disc's MusicBrainz ID, looks it up, and shows the match status. If multiple releases match, a picker dialog appears (this is the GUI's substitute for whipper's interactive TTY prompt — you'll never see whipper itself ask you anything).

5. **Edit metadata.** The track table is editable. Fix any tags that look wrong before you rip.

6. **Click "Start rip."** Progress and per-track AccurateRip confidence appear as the rip runs. You can cancel mid-rip.

7. **View the log.** When the rip finishes, the "View log" button opens the rip log in your default text editor.

For discs MusicBrainz doesn't recognize, use the Unknown Album flow from the menu — the GUI rips with placeholder `Track NN` tags and optionally launches Picard for you to fix them up.

---

## Troubleshooting

### `pip install` fails with "does not appear to be a Python project"

Make sure you're in the cloned repository directory (where `pyproject.toml` lives) and that the clone completed:

```bash
ls pyproject.toml    # should exist
```

Then re-run `pip install -e .` (or `bash dev-setup.sh`).

### `sudo dnf install gh` fails on Bazzite

Bazzite is an immutable distro — the host filesystem is read-only and `dnf` only works inside containers. Two paths:

- **Use SSH instead** (recommended for one-time auth setup). See Method C in the install instructions above.
- **Or install `gh` system-wide via rpm-ostree:** `rpm-ostree install gh && systemctl reboot`. Requires a reboot. After the reboot, `gh auth login` will work.

### `pip install` fails with "error: externally-managed-environment"

Bazzite, Fedora 38+, Ubuntu 24.04+, and other distros now ship a PEP 668 marker that blocks `pip install` against the system Python. The fix is to install into a virtual environment, which Method C already does for you:

```bash
cd Whipper-GUI-Frontend---CD-Rip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you tried `pip install -e .` without activating a venv first, no harm done — re-run with the venv active and it'll work.

### `git clone` fails with "Password authentication is not supported"

The repository is **public**, so a plain `git clone https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git` needs no authentication. If you only want to *run* the GUI, you don't need to clone at all — use the AppImage from the [Releases page](https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/releases/latest) (Method A).

If you plan to **push changes**, GitHub deprecated HTTPS password auth in 2021, so set up auth first — either an SSH key on your account (clone via `git@github.com:…`) or `gh auth login` (web-browser login; stores a token in your git credential helper).

### I can't find `~/.config/whipper/whipper.conf`

It doesn't exist until whipper writes to it. Running `whipper --version` or `whipper drive list` doesn't create the file — only commands that change settings do (`whipper drive analyze`, `whipper offset find`). Run one of those and it'll appear.

If you want to peek inside before whipper writes anything, you can pre-create an empty file:

```bash
mkdir -p ~/.config/whipper
touch ~/.config/whipper/whipper.conf
```

On Bazzite and Fedora Silverblue, `~` expands to `/var/home/<username>` (not `/home/<username>`). The file is the same either way.

### `ModuleNotFoundError: No module named 'pkg_resources'` when running whipper

Whipper imports `pkg_resources` from `setuptools`. On Fedora 44+ (Python 3.14), setuptools is no longer installed by default and Fedora's whipper RPM doesn't declare it as a dependency. Fix:

```bash
distrobox enter ripping
sudo dnf install python3-setuptools
exit
```

Then `whipper --version` should work from the host.

### `whipper: command not found`

Your `~/.local/bin` isn't on `$PATH`. Add this to `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Open a new terminal. Verify with `which whipper`.

### "no drives found" when launching the GUI

The Distrobox container can't see `/dev/sr0`. Bazzite, Fedora Silverblue, and most modern distros pass optical drives through automatically. If yours doesn't:

```bash
distrobox stop ripping
distrobox enter ripping
# inside the container:
sudo dnf install eudev
```

(Some minimal container bases don't include udev; this restores device-node passthrough.)

You can also confirm whipper can see the drive from inside the container:

```bash
distrobox enter ripping
whipper drive list
```

If whipper finds it inside but not from the host, the export wrapper isn't passing through device access. Re-run `distrobox-export --bin /usr/bin/whipper` from inside the container.

### "MusicBrainz error: rate limited"

MusicBrainz throttles unidentified queries. The GUI already sets a User-Agent at launch; if you're still hitting limits, you're sharing an IP with a busy network. Wait a minute and try again.

### AppImage won't launch

Most modern Linux distros have FUSE installed and AppImages just work. On Bazzite, no extra steps. If you see "AppImages require FUSE", either install FUSE or extract the AppImage:

```bash
./whipper-gui-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

### The GUI launches but freezes

Check the log at `~/.local/share/whipper-gui/log.txt`. The most common cause is whipper hanging on a defective disc — cancel from the GUI, eject, try a clean disc.

### `whipper offset find` says my disc isn't in AccurateRip

Try a well-known commercial CD (Pink Floyd, Beatles, Metallica — anything in the top 1000 records). Mix CDs and very obscure pressings often aren't in AccurateRip's database.

### "metaflac: command not found" only when ripping

You exported whipper but not metaflac. Re-enter the container:

```bash
distrobox enter ripping
distrobox-export --bin /usr/bin/metaflac
exit
```

---

## Updating

### Update Whipper GUI

- **AppImage:** download the new release, replace the old file.
- **pipx:** `pipx upgrade whipper-gui`
- **From source:** `git pull && pip install -e .`

### Update whipper or metaflac

```bash
distrobox enter ripping
sudo dnf upgrade whipper flac
exit
```

The host-exported wrappers don't change; they always run whatever is currently inside the container.

### Update the container's base Fedora version

```bash
distrobox enter ripping
sudo dnf system-upgrade download --refresh --releasever=41
sudo dnf system-upgrade reboot   # inside the container only
```

---

## Uninstalling

If you installed with `install.sh` (or `install-appimage.sh`), the easiest way is the **Uninstall Whipper GUI** shortcut in your application menu — it runs `uninstall.sh` in a terminal with all the options below.

The [`uninstall.sh`](uninstall.sh) script tears everything down in layers, safest-first: it removes the GUI (AppImage, config, logs, and all shortcuts) by default, then prompts about the broader stack. It **never** removes your ripped music or a source checkout without an explicit flag.

```bash
# Interactive — removes the GUI's venv/config/logs by default, then prompts
# you about the broader stack (Picard, the ripping container, whipper.conf,
# the host-exported binaries) one at a time.
bash uninstall.sh

# Preview only — print what would be removed, change nothing.
bash uninstall.sh --dry-run

# Everything except your music files and the cloned repo, no prompts.
bash uninstall.sh --full --yes

bash uninstall.sh --help   # full option list
```

If you installed via the **AppImage** with `install.sh`/`install-appimage.sh`, the **Uninstall Whipper GUI** shortcut (or running the staged `~/Applications/whipper-gui-uninstall.sh`) does all of the above — it removes the AppImage, its icon, and the shortcuts, then prompts about the host stack. To remove the host stack by hand instead:

```bash
distrobox rm ripping            # remove the container
rm ~/.local/bin/whipper ~/.local/bin/metaflac   # remove the host exports
rm -rf ~/.config/whipper ~/.config/whipper-gui ~/.local/share/whipper-gui
```

Your music at `~/Music/rips/` (or wherever Settings points) is never touched by any of this.

## Where things live

| Path | Contents |
|------|----------|
| `~/.local/bin/whipper` | The Distrobox-exported wrapper. **Don't edit.** |
| `~/.local/bin/metaflac` | Same. |
| `~/.config/whipper/whipper.conf` | Drive offsets and cache settings. Shared with the container. |
| `~/.config/whipper-gui/config.toml` | The GUI's own settings (output dir, templates, toggles). |
| `~/.local/share/whipper-gui/log.txt` | GUI log file. Check here when something goes sideways. |
| `~/Music/rips/` *(default)* | Where rips land, under `Artist/Album/`. Configurable in Settings. |
| `…/Artist/Album/` | The rip itself: the FLAC tracks **plus** the `.log`, `.cue`, `.m3u`, and `.toc` whipper writes next to them (confirmed on a real 16-track rip). |

---

## Documentation for contributors

Core project documents (in this directory):

- [`CLAUDE.md`](CLAUDE.md) — project rules and conventions (read before contributing); Project operations section has current build/run/test/uninstall commands
- [`PLANNING.md`](PLANNING.md) — architecture, directory tree, per-module responsibilities, keyed design decisions (KDD-01 through KDD-16)
- [`TASKS.md`](TASKS.md) — active task checklist. P0 (T01-T32, complete), P1.1 (install/uninstall ease), P1 (broader backlog), P2 (future), Out of scope.
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — pinned versions, last upstream release dates, replacement plans, retirement-review log

Source documents and reference material (in `docs/`):

- [`docs/README.md`](docs/README.md) — index of `docs/` contents + rebuild-from-scratch checklist
- [`docs/best-practices.md`](docs/best-practices.md) — engineering patterns & hard-won lessons (read before contributing code)
- [`docs/whipper-gui-research-brief-v2.1.md`](docs/whipper-gui-research-brief-v2.1.md) — the canonical project brief
- [`docs/whipper-gui-session-start.md`](docs/whipper-gui-session-start.md) — bootstrap instructions for a fresh Claude Code session
- [`docs/whipper-gui-research-rerun-prompt.md`](docs/whipper-gui-research-rerun-prompt.md) — Research-mode prompt for refreshing tool-choice validation
- [`docs/log-format-comparison.md`](docs/log-format-comparison.md) — whipper-log vs EAC-log field comparison

Build / dev tooling:

- [`setup-host.sh`](setup-host.sh) — one-command full bootstrap (Distrobox + container + whipper + export + clone + dev-setup)
- [`dev-setup.sh`](dev-setup.sh) — one-command post-clone setup (venv + pip + editable install + app-menu shortcut)
- [`uninstall.sh`](uninstall.sh) — tear-down counterpart (use `--help` for options)
- [`build/build_appimage.sh`](build/build_appimage.sh) — produce the AppImage locally
- [`build/make_icon.py`](build/make_icon.py) — regenerate the app icon
- [`build/python-appimage/README.md`](build/python-appimage/README.md) — AppImage recipe details
- **CI / releases:** `.github/workflows/ci.yml` runs the tests on every push/PR; `.github/workflows/release.yml` builds the AppImage and publishes it to a GitHub Release when a `vX.Y.Z` tag is pushed — so cutting a release is just `git tag vX.Y.Z && git push origin vX.Y.Z` (no local build or manual upload).

---

## License

[**GPL-3.0-only**](LICENSE). Chosen to align with the free-software CD-ripping ecosystem this builds on (whipper, cdparanoia, CUETools) and to keep the tool and any forks open. whipper and other GPL tools are invoked as separate processes (not linked), and PySide6 is used under its LGPL-3 option — so the combined work is cleanly GPL-3.0.

See [PLANNING.md KDD-10](PLANNING.md) for the rationale.
