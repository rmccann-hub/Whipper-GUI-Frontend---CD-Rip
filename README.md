<p align="center">
  <img src="assets/icons/io.github.rmccann_hub.Platterpus-256.png" alt="Platterpus" width="120">
</p>

# Platterpus

**A secure, EAC-style CD ripper for Linux (FLAC, WAV, WavPack, MP3).** Aims for EAC-equivalent (Exact Audio Copy) archival quality on Linux, packaged as a single-file AppImage. It drives the [`cyanrip`](https://github.com/cyanreg/cyanrip) ripping engine and verifies every rip against AccurateRip and CTDB.

> **Status: v0.4.x — public pre-release.** Implemented end-to-end with 1,000+ tests (including a full-pipeline end-to-end test) at ~93% branch coverage, and validated on real Bazzite hardware: a full 16-track rip *through the published AppImage*, AccurateRip-verified bit-perfect. Highlights: **no-terminal first-run setup** (the AppImage adds itself to your menu; a guided wizard installs the ripping stack), **read-offset auto-detect** from the bundled AccurateRip drive list (no disc needed), **cyanrip as the single ripping backend** (actively maintained, no >587 read-offset bug — whipper was retired, see KDD-18), **multiple output formats** (FLAC is always the lossless master; WavPack/MP3/WAV are derived from it), **goal presets** (Fast verified / Archival exact / Portable) that anchor the settings to your intent, an at-a-glance **verification verdict** (AccurateRip + CTDB) with a machine-readable JSON rip report written beside the log, a per-drive **read-offset trust line** showing where the offset came from and how confident we are, **true in-app updates** (download → checksum-verify → self-restart), and **cover art** from the Cover Art Archive. This is an early release for wider testing — expect rough edges, and please [open an issue](https://github.com/rmccann-hub/Platterpus/issues) for anything you hit.

## At a glance

- **Linux only.** Primary target is Bazzite KDE Plasma 6; should work on any modern desktop Linux running Qt 6 (Fedora, Arch, Ubuntu, Tumbleweed).
- **Runs cyanrip inside Distrobox.** The GUI calls the host-exported `cyanrip` binary; it never bundles cyanrip or tries to install it itself (the guided wizard provisions the container). This is intentional — see [PLANNING.md §8 KDD-07](PLANNING.md).
- **Single-file AppImage** for the GUI itself; no system-level installs required.
- **No terminal prompts from the ripper** — the GUI queries MusicBrainz directly, then runs cyanrip offline with the chosen release's tags, so its interactive prompt never surfaces.
- **Choose your output format** — FLAC (default), WavPack, MP3, or WAV. FLAC is always produced as the lossless master; other formats are derived from it, so you never lose the archival copy. See [Audio output](#audio-output-what-you-get-what-you-dont).
- **Distribution model:** AppImage primary, `pipx` secondary.

---

## Installation

### Easiest — download one file, no terminal (recommended)

You don't need the command line. Download the GUI, double-click, and it sets
itself up by asking a couple of questions.

1. **Download** `platterpus-x86_64.AppImage` from the **[Releases page](https://github.com/rmccann-hub/Platterpus/releases/latest)** (one file).
2. **Allow it to run** (a one-time Linux step — a downloaded program isn't
   runnable until you say so):
   - **KDE (Dolphin):** right-click the file → **Properties** → **Permissions** → tick **Is executable** → OK.
   - **GNOME (Files):** right-click → **Properties** → **Permissions** → enable **Allow executing file as program**.
3. **Double-click it.** On first launch it will offer to:
   - **add Platterpus to your applications menu** (so next time you just click it in the menu), and
   - **set up the ripping tool** — a guided wizard installs everything ripping needs (it may ask for your password once; on Bazzite/Silverblue it's instant). No terminal.
4. Then in the app: **Tools → Set up drive…** — your drive's read offset is
   filled in automatically; click **Save offset**. Insert a CD and **Start**.

That's the whole thing: one download, a couple of clicks, answer the prompts.
(Updating later = download the new AppImage and replace the old one.)

### Easy second option — one command with pipx

Comfortable with a terminal? A single copy-paste installs Platterpus from PyPI
and puts it on your `PATH` (the GUI still runs the first-run wizard to set up the
ripping stack):

```bash
pipx install platterpus    # then run:  platterpus
```

Don't have pipx? `sudo dnf install pipx` (Fedora/Bazzite) or `sudo apt install
pipx` (Ubuntu/Debian). Upgrade later with `pipx upgrade platterpus`. (If it isn't
on PyPI yet — before the first published release — see
[Method B](#method-b--pipx-recommended-for-technical-users) for installing from a
checkout.)

> **Why a wizard?** Ripping runs through `cyanrip` inside a small container so
> it never touches your system ([why](PLANNING.md)). The first-run wizard sets
> that container up for you — the same work the scripts below do by hand.

### Quickstart for testers / scripted install

Prefer one command? This installs the *host stack* (Distrobox + cyanrip) **and**
the GUI, plus shortcuts:

```bash
curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Platterpus/main/install.sh | bash
```

Prefer to download and run it yourself? Grab `install.sh` from the [Releases page](https://github.com/rmccann-hub/Platterpus/releases/latest), then `bash install.sh`. Useful flags: `--dry-run` (preview), `--no-host` (GUI only, host stack already set up), `--appimage PATH` (use a local AppImage). First run takes ~20–40 min because it builds the container.

Then, inside the GUI: **Tools → Set up drive…** to calibrate your drive's read offset (one time), insert a CD, and rip. To remove everything later, use the **Uninstall Platterpus** shortcut (or see [Uninstalling](#uninstalling)).

> **Already have cyanrip + Distrobox set up** (e.g. re-installing on the same machine, or installing the GUI on a second box that shares the stack)? Skip the host build and just add the GUI: `curl -fsSL …/install.sh | bash -s -- --no-host` (or `bash install.sh --no-host`).

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

[`setup-host.sh`](setup-host.sh) automates the host setup: it installs Distrobox (if needed), creates the `ripping` container, installs cyanrip + flac inside it, exports the binaries to your host, then clones this repo and runs `dev-setup.sh` (venv + editable install + app-menu shortcut).

```bash
# From a fresh clone:
bash setup-host.sh

# …or straight from the web (no clone needed first):
curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Platterpus/main/setup-host.sh | bash
```

Useful flags: `--dry-run` (print every command, change nothing), `--yes` (skip confirmations), `--no-gui` (host stack only). It's idempotent — safe to re-run. It does **not** calibrate your drive (do that in the GUI: **Tools → Set up drive…**) or install Picard (the GUI offers that on first run).

Prefer to do it by hand, or the script hit a snag? The manual steps below are the source of truth.

### Manual steps

There are five things to set up. Plan on **20-40 minutes** the first time. Once it's done, you don't touch most of it again.

| Step | What | Why |
|------|------|-----|
| 1 | Install Distrobox | Provides an isolated Fedora environment for cyanrip |
| 2 | Create a `ripping` container | Where cyanrip actually lives |
| 3 | Install cyanrip + flac in the container | The tools that do the ripping |
| 4 | Export them to the host | So Platterpus can find them |
| 5 | Detect your drive's read offset | One-time calibration for accurate rips |
| 6 | Install MusicBrainz Picard *(optional)* | Manual tag editing for unknown discs |
| 7 | Install Platterpus | This project |

> **If a step doesn't behave as written:** skip to the [Troubleshooting](#troubleshooting) section near the end of this README. The common surprises — "no drives found", `cyanrip: command not found`, HTTPS clone authentication failure — all have entries there.

### Step 1 — Install Distrobox

Distrobox lets you run a different Linux distribution's tools alongside your host system. It's the recommended way to run cyanrip on immutable distros like Bazzite.

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

### Step 3 — Install cyanrip and flac

> **Easiest path:** run [`setup-host.sh`](setup-host.sh) (or the one-line installer above) — it adds cyanrip's COPR repo and installs everything for you. The manual steps below are only if you're doing it by hand.

Inside the container (your prompt should still show you're in `ripping`):

```bash
# flac provides both the `flac` decoder and `metaflac` (the tag editor).
sudo dnf install flac

# cyanrip isn't packaged by Fedora — add the barsnick COPR (GPG-checked), then install it:
sudo dnf copr enable barsnick/non-fed
sudo dnf install cyanrip
```

Verify the tools are installed:

```bash
cyanrip -V
metaflac --version
```

`cyanrip -V` should report a version such as `cyanrip 0.9.3` (note the capital `-V` — cyanrip has no `--version`). `metaflac` is part of the `flac` package.

### Step 4 — Export the binaries to your host

Still inside the container, export both binaries:

```bash
distrobox-export --bin /usr/bin/cyanrip
distrobox-export --bin /usr/bin/metaflac
```

This creates wrapper scripts at `~/.local/bin/cyanrip` and `~/.local/bin/metaflac` on the **host** (not in the container). Those wrappers transparently enter the container when called, so from the host's perspective cyanrip looks like a regular installed program.

Now leave the container:

```bash
exit
```

You're back on the host. Verify the wrappers work:

```bash
which cyanrip
# → /home/<you>/.local/bin/cyanrip

cyanrip -V
# → cyanrip 0.9.3
```

If `which` returns nothing, your `~/.local/bin` isn't on `$PATH`. Most desktop Linux setups put it there automatically; if yours doesn't, add this to `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then open a new terminal.

### Step 5 — Set your drive's read offset

Every optical drive reads audio slightly off from where it "should" — by a positive or negative number of samples. For bit-perfect archival rips that match AccurateRip's database, the offset for your drive has to be known so cyanrip can correct for it.

**This is a one-time, in-app step — there's no terminal command for it.** cyanrip reads no config file of its own; Platterpus stores the offset in its own config at `~/.config/platterpus/config.toml` and passes it to cyanrip at rip time via the `-s` flag. You set it through the **drive-setup wizard**, offered on first launch (or anytime from **Tools → Set up drive…**), which gives you three ways to get the value:

- **Automatic, no disc needed** — if Platterpus recognises your drive model, it fills the offset in from the bundled AccurateRip drive-offset list. Just click **Save offset**.
- **Detect from a CD** — insert a commercial audio CD that's in [AccurateRip's database](https://www.accuraterip.com) (any common retail pressing — Pink Floyd, Beatles, Metallica; not a CD-R or burned mix), click **Detect**, then **Save**.
- **Enter it by hand** — look your drive up in the [AccurateRip offset list](https://www.accuraterip.com/driveoffsets.htm) and type the value into the wizard's manual-entry field. Handy if you only have CD-Rs.

> **What about `~/.config/whipper/whipper.conf`?** If you ran an older whipper-based install, that file may still exist. It's **legacy, read-only reference only** — kept so an upgrading user can see their previous offset. cyanrip neither reads nor writes it; the live offset lives in Platterpus's own config. There's nothing to create or edit there.

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

Platterpus will auto-launch Picard with the rip folder when you mark a disc as Unknown Album, *if* you enable the toggle in Settings.

### Step 7 — Install Platterpus

> **Recommended: Method A (AppImage).** As of v0.1.0 it's published as a downloadable release asset — this is the simplest path for most people. Method B (`pipx` from PyPI) publishes automatically on each tagged release (Trusted Publishing); if it's not on PyPI yet, install from a checkout (see Method B). Method C runs the GUI from a source clone and is aimed at developers.

Pick **one** of the methods below.

#### Method A — AppImage (recommended for end users)

Download the latest `platterpus-x86_64.AppImage` from the **[Releases page](https://github.com/rmccann-hub/Platterpus/releases/latest)**, then:

```bash
chmod +x platterpus-x86_64.AppImage
./platterpus-x86_64.AppImage
```

That's it — the AppImage bundles Python, Qt, and the GUI's dependencies, so there's nothing else to install on the GUI side. (You still need the host stack for ripping to work — the first-run wizard sets it up.)

**Menu entry / desktop icon:** you don't need to do anything — on its **first run the AppImage offers to add itself to your applications menu** (and copies its icon), **moving itself to `~/Applications`** so it lives with your other apps instead of staying in Downloads. Just say yes. (The old `install-appimage.sh` helper still exists for scripted setups and offers an `--uninstall`, but it's no longer required. [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) also works if you prefer.)

**Updates:** use **Help → Check for updates…** — if a newer release exists the app downloads it in the background, verifies it against the release's published checksum, installs it to `~/Applications`, and restarts itself. (Releases also ship a `.zsync` file and the AppImage embeds standard update-information, so [AppImageUpdate](https://github.com/AppImageCommunity/AppImageUpdate) delta updates work too, for those who use it.)

> **On a FUSE-less host** (rare on desktop Linux, but some minimal setups): run with `APPIMAGE_EXTRACT_AND_RUN=1 ./platterpus-x86_64.AppImage`, or see [AppImage won't launch](#appimage-wont-launch) in Troubleshooting.

#### Method B — pipx (recommended for technical users)

`pipx` installs Python applications in isolated environments and adds them to your `PATH`.

Install pipx if you don't have it (Bazzite ships with it):

```bash
sudo dnf install pipx     # Fedora / Bazzite
# or
sudo apt install pipx     # Ubuntu / Debian
```

Then install Platterpus:

```bash
pipx install platterpus
```

> Releases publish the wheel to PyPI automatically (via Trusted Publishing on each tagged release). If `pipx install platterpus` can't find it yet — e.g. before the first PyPI-published release — install from a local checkout instead: `git clone …` then `pipx install .` from inside the repo.

Run with `platterpus` from any terminal.

#### Method C — From source (for developers)

> The repository is **public**, so no authentication is needed to clone over HTTPS. (If you plan to push changes, set up SSH or `gh auth login` — but for just running from source, a plain clone works.)

Clone and install:

```bash
git clone https://github.com/rmccann-hub/Platterpus.git
cd Platterpus
```

The default `main` branch contains the full source — no branch switch needed.

From here you have two options.

**Option 1 — one-shot setup script (recommended):**

```bash
bash dev-setup.sh
source .venv/bin/activate
platterpus
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
# edit in src/platterpus/ is picked up the next time you run the GUI.
pip install -e .

# Run the GUI. The console-script entry point lives in .venv/bin
# (added to PATH by the `activate` line above).
platterpus
```

To re-enter the same environment in a future terminal session:

```bash
cd ~/Platterpus
source .venv/bin/activate
platterpus
```

To leave the venv: `deactivate`.

To build an AppImage from your local checkout:

```bash
pip install --user build "python-appimage>=1.4,<2"
bash build/build_appimage.sh
```

The resulting `platterpus-x86_64.AppImage` appears at the repo root. See [`build/python-appimage/README.md`](build/python-appimage/README.md) for details.

---

## Ripping backend: cyanrip

The GUI drives a single ripping engine: [**cyanrip**](https://github.com/cyanreg/cyanrip) — actively maintained, EAC-equivalent archival quality. There's no backend setting or toggle; cyanrip is it. (The project originally used whipper, but its cd-paranoia has a known bug at read offsets **over 587 samples** that can fail tracks — e.g. the Pioneer BDR-209D's +667; cyanrip applies the offset correctly with its own paranoia even past that threshold, which is why we switched. See [KDD-18](PLANNING.md).)

The GUI does the MusicBrainz lookup itself and then runs cyanrip **offline** — with `-N` (no network metadata lookup) and the chosen release's tags fed in via `-a`/`-t` — so cyanrip's own interactive prompt never surfaces and the rip needs no in-container network. Cover art is fetched separately by the GUI from the Cover Art Archive.

## Audio output: what you get, what you don't

**Output format** is chosen in **Settings → Output format**: **FLAC** (default),
**WavPack** (`.wv`), **MP3**, or **WAV**. Every rip produces FLAC first — the lossless
archival *master* — and for any other choice the GUI **keeps that FLAC** and creates
the selected format alongside it (a quick post-rip transcode via ffmpeg). So you never
lose the lossless master, whatever you pick.

| Format | Lossless? | Tags | Cover art | Use it for |
|--------|-----------|------|-----------|------------|
| **FLAC** | ✅ (verified bit-perfect) | ✅ | ✅ embedded | The archive. The master copy. |
| **WavPack** (`.wv`) | ✅ | ✅ | folder `cover.jpg`¹ | A lossless library in a different container |
| **MP3** | ❌ best-quality VBR (~245 kbps) | ✅ | ✅ embedded | Phones, cars, portability |
| **WAV** | ✅ | ❌ | ❌ | Raw PCM interchange only (the GUI warns) |

¹ The front cover always lands in the album folder as an image file; ffmpeg can't embed
art *inside* a `.wv` (a known limitation — see `docs/mp3-wav-support.md`). For embedded
lossless art, FLAC is the choice.

The flag-by-flag detail below is about how each format is encoded.

*(cyanrip encodes FLAC through FFmpeg at maximum compression, and self-verifies the read with its own paranoia.)*

### FLAC (default — the lossless archival master)

cyanrip encodes each track to FLAC through FFmpeg at **maximum compression**, and verifies the read itself via its own paranoia engine — so every track is provably bit-perfect (and confirmed afterwards against AccurateRip and CTDB). There's no compression-level knob to set: it's already at the top.

**Historical context — the "Re-compress FLACs" setting.** Settings still lists a **"Re-compress FLACs"** toggle, but it is **inert and disabled** with cyanrip and does nothing: cyanrip already produces maximum-compression FLAC, so there's nothing to re-compress. (The control is kept only as a seam for a hypothetical future backend that *didn't* encode at max — for example, the old whipper backend relied on flac's default level 5, where a post-rip re-encode to `-8` would have shaved ~5% off file size. That no longer applies.) Don't expect flipping it to change anything.

For background: **all FLAC compression levels are lossless** — `-0` and `-8` decode to identical audio; only file size (and a little decode CPU) differ. cyanrip's max-compression output and its self-verification give you the smallest standard FLAC with the bit-perfect property already proven.

The full FLAC encoder reference is at [xiph.org/flac/documentation_tools_flac.html](https://xiph.org/flac/documentation_tools_flac.html).

### WavPack, MP3, and WAV (derived from the FLAC master)

When you pick a non-FLAC format, after each rip the GUI transcodes the FLAC master to
your choice with **ffmpeg**, keeping the FLAC. It runs in the background (never freezes
the window), writes each file atomically, and **never costs you the lossless master** —
a transcode failure just means you still have the FLAC to retry from. Per file:

```bash
# WavPack — lossless, tags carried over (APEv2)
ffmpeg -i <file>.flac -map_metadata 0 -map 0:a -c:a wavpack <file>.wv

# MP3 — best-quality VBR (== lame -V0, ~245 kbps), tags + embedded cover
ffmpeg -i <file>.flac -map_metadata 0 -id3v2_version 3 -c:v copy \
       -c:a libmp3lame -q:a 0 <file>.mp3

# WAV — raw 16-bit PCM (no tags or cover art — RIFF can't hold them)
ffmpeg -i <file>.flac -map 0:a -c:a pcm_s16le <file>.wav
```

`ffmpeg` is the single encoder dependency for all three (it's already present wherever
the cyanrip backend is — cyanrip is built on FFmpeg), detected through the same
dependency self-management subsystem as everything else — no bespoke install code. The
MP3 setting follows [HydrogenAudio's Recommended LAME](https://wiki.hydrogenaudio.org/index.php/LAME):
VBR `-V0` (joint-stereo on), the highest-quality VBR. Design + the full encoder-argument
rationale: [docs/mp3-wav-support.md](docs/mp3-wav-support.md).

### Compared to EAC's bit-perfect settings

The widely-cited [Perfect CD Ripping to FLAC with Exact Audio Copy guide](https://flemmingss.com/perfect-cd-ripping-to-flac-with-exact-audio-copy/) is the gold standard for archival rips on Windows. Here's how this GUI's pipeline maps to it. Full audit in [PLANNING.md KDD-13](PLANNING.md).

**Matches the guide today:**

- Secure read mode (cyanrip's own paranoia engine)
- Defeat audio cache (per-drive)
- Read offset calibration (per-drive, set in the GUI's drive-setup wizard and passed to cyanrip via `-s`)
- AccurateRip verification (the GUI/cyanrip query; we render the v1/v2 confidence)
- High error-recovery quality (cyanrip's paranoia is always at maximum)
- No normalization
- FLAC `--verify` (proves bit-perfect reversibility)
- `.log` file written after every rip
- Gap detection in "Secure" mode (cdrdao)
- Status-report checksum (SHA-256)

**Not configurable from the GUI** (cyanrip is already at the archival maximum):

- **FLAC compression level.** EAC's guide says `-8 --best`; cyanrip already encodes FLAC at maximum compression, so there's nothing to turn up. Archival quality is identical at any compression level — only file size differs — and cyanrip is at the smallest standard size already. (The legacy "Re-compress FLACs" toggle is inert with cyanrip — see "FLAC" above.)

**Not possible on Linux today:**

- **C2 error pointers.** Cdparanoia is the Linux secure-read primitive; it doesn't use C2.
- **A *tracker-accepted* EAC-signed log.** The EAC log checksum algorithm has been reverse-engineered, so a valid checksum is technically reproducible — but signing our log as if Exact Audio Copy produced it is **forging the rip's provenance** (a bannable "faked log" on gazelle trackers), and we won't do it. We rely on the open, tool-agnostic trust signals instead: AccurateRip + CTDB verification and an honest log. See [docs/eac-log-and-repair-feasibility.md](docs/eac-log-and-repair-feasibility.md).
- **AccurateRip submission** (writing new entries to the database). Blocked by AccurateRip's operators, who accept submissions only from EAC and dBpoweramp. Verification (reading) works fine — see "AccurateRip" in the audit above.

**Now in Settings** (surfaced in the Settings dialog):

- **Goal** preset — *Fast verified* / *Archival exact* / *Portable* snaps the format/verification/quality controls to your intent; editing any of them switches the goal to *Custom*
- **Output format** — FLAC (the lossless master, always produced), WavPack, MP3, or WAV
- Cover art — fetch + embed in FLAC, save next to it, or both (defaults to *embed*)
- Force overread into lead-out
- Max retries per track (default 5)
- Keep going on track failure
- **Re-rip until reads match** — for damaged/marginal discs, re-read each track until N passes agree on the checksum (cyanrip's `-Z`; off by default).
- Verify with CTDB after a rip (a second, whole-disc verification path alongside AccurateRip; experimental until the CRC is hardware-validated)
- Verify FLACs after a rip, and optionally re-compress them to `-8`
- Continue ripping CD-Rs
- Auto-eject after a successful rip, plus read-offset calibration via the drive-setup wizard

After a rip, the results pane shows an at-a-glance **verification verdict** (green = every track verified against AccurateRip, amber = partial, grey = not in the database) above the per-track table, plus the CTDB result.

See [TASKS.md](TASKS.md) under "EAC bit-perfect parity gaps" for the history.

---

## First run

When you launch Platterpus for the first time:

1. **Dependency check.** The GUI verifies cyanrip, metaflac, and Picard are reachable. If anything's missing, it pops a dialog with one of three resolutions:
   - **Auto-install** (Picard): one OK and it runs `flatpak install --user`.
   - **Pending installs:** a checklist for items that need batching or confirmation.
   - **Manual install:** a copyable search string for items like `libdiscid` that need root + reboot.

2. **Drive offset (first launch only).** Rips can't be made bit-perfect until your drive's read offset is set. If none is configured yet, the GUI offers the drive-setup wizard once. It can fill the offset in **automatically** from the bundled AccurateRip drive list (no disc needed), **detect** it (insert a commercial CD that's in AccurateRip), or take a value you **enter by hand** (look your drive up at [accuraterip.com/driveoffsets.htm](https://www.accuraterip.com/driveoffsets.htm) — handy if you only have CD-Rs). It's a one-time, dismissible prompt; afterwards re-run it anytime from **Tools → Set up drive…**.

3. **Pick a drive.** The dropdown at the top of the window lists the optical drives detected on your system. Click Refresh if you plug in a drive after launch.

4. **Insert a CD.** The GUI fetches the disc's MusicBrainz ID, looks it up, and shows the match status. If multiple releases match, a picker dialog appears. (The GUI does the MusicBrainz lookup itself and runs cyanrip offline, so the ripper never prompts you for anything — this picker is where any disambiguation happens.)

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
cd Platterpus
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you tried `pip install -e .` without activating a venv first, no harm done — re-run with the venv active and it'll work.

### `git clone` fails with "Password authentication is not supported"

The repository is **public**, so a plain `git clone https://github.com/rmccann-hub/Platterpus.git` needs no authentication. If you only want to *run* the GUI, you don't need to clone at all — use the AppImage from the [Releases page](https://github.com/rmccann-hub/Platterpus/releases/latest) (Method A).

If you plan to **push changes**, GitHub deprecated HTTPS password auth in 2021, so set up auth first — either an SSH key on your account (clone via `git@github.com:…`) or `gh auth login` (web-browser login; stores a token in your git credential helper).

### Where is my drive's read offset stored?

cyanrip uses **no config file** of its own. Platterpus stores your drive's read offset in its own config at `~/.config/platterpus/config.toml` and passes it to cyanrip at rip time. Set or change it in the GUI via **Tools → Set up drive…**. (A `~/.config/whipper/whipper.conf` left over from an older whipper install is legacy reference only — cyanrip doesn't read it.)

### `cyanrip: command not found`

Your `~/.local/bin` isn't on `$PATH`. Add this to `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Open a new terminal. Verify with `which cyanrip`.

### "no drives found" when launching the GUI

The Distrobox container can't see `/dev/sr0`. Bazzite, Fedora Silverblue, and most modern distros pass optical drives through automatically. If yours doesn't:

```bash
distrobox stop ripping
distrobox enter ripping
# inside the container:
sudo dnf install eudev
```

(Some minimal container bases don't include udev; this restores device-node passthrough.)

You can also confirm the container can see the drive device node from inside it:

```bash
distrobox enter ripping
ls -l /dev/sr*
```

If the device shows up inside the container but the GUI still finds no drives from the host, the export wrapper isn't passing through device access. Re-run `distrobox-export --bin /usr/bin/cyanrip` from inside the container.

### "MusicBrainz error: rate limited"

MusicBrainz throttles unidentified queries. The GUI already sets a User-Agent at launch; if you're still hitting limits, you're sharing an IP with a busy network. Wait a minute and try again.

### AppImage won't launch

Most modern Linux distros have FUSE installed and AppImages just work. On Bazzite, no extra steps. If you see "AppImages require FUSE", either install FUSE or extract the AppImage:

```bash
./platterpus-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

### The GUI launches but freezes

Check the log at `~/.local/share/platterpus/log.txt`. The most common cause is the ripper hanging on a defective disc — cancel from the GUI, eject, try a clean disc.

### The drive-setup wizard says my disc isn't in AccurateRip

When detecting the offset from a CD, try a well-known commercial CD (Pink Floyd, Beatles, Metallica — anything in the top 1000 records). Mix CDs and very obscure pressings often aren't in AccurateRip's database. If you can't get a detection, look your drive up at [accuraterip.com/driveoffsets.htm](https://www.accuraterip.com/driveoffsets.htm) and enter the value by hand in the wizard's manual-entry field.

### "metaflac: command not found" only when ripping

You exported cyanrip but not metaflac. Re-enter the container:

```bash
distrobox enter ripping
distrobox-export --bin /usr/bin/metaflac
exit
```

---

## Updating

### Update Platterpus

- **AppImage:** download the new release, replace the old file.
- **pipx:** `pipx upgrade platterpus`
- **From source:** `git pull && pip install -e .`

### Update cyanrip or metaflac

```bash
distrobox enter ripping
sudo dnf upgrade cyanrip flac
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

**Easiest — no terminal:** open the app and use **Tools → Uninstall Platterpus…**, or click the **Uninstall Platterpus** entry the AppImage adds to your application menu (under System). It removes everything the app installed — shortcuts, the cyanrip/metaflac commands (and any leftover whipper export from an older install), the `ripping` container, optionally the AppImage file itself, and the app's own settings and logs (including the stored read offset) — with a confirmation first and per-item checkboxes. **Never touched:** your music, and Distrobox/podman themselves (any other containers you have keep working). The same uninstaller can be launched from a terminal with `platterpus --uninstall`.

**Script alternative** (source checkouts, or if you prefer the terminal): the [`uninstall.sh`](uninstall.sh) script tears everything down in layers, safest-first — it also covers the dev `.venv/`, which the in-app uninstaller doesn't (a packaged app doesn't know your checkout's location). It **never** removes your ripped music or a source checkout without an explicit flag.

```bash
# Interactive — removes the GUI's venv/config/logs by default, then prompts
# you about the broader stack (Picard, the ripping container,
# the host-exported binaries) one at a time.
bash uninstall.sh

# Preview only — print what would be removed, change nothing.
bash uninstall.sh --dry-run

# Everything except your music files and the cloned repo, no prompts.
bash uninstall.sh --full --yes

bash uninstall.sh --help   # full option list
```

To remove the host stack fully by hand instead:

```bash
distrobox rm ripping            # remove the container
rm ~/.local/bin/cyanrip ~/.local/bin/metaflac   # host exports
rm -f ~/.local/bin/whipper      # leftover from an older whipper install, if present
rm -rf ~/.config/platterpus ~/.local/share/platterpus
rm -rf ~/.config/whipper        # legacy whipper config, if present
```

Your music at `~/Music/rips/` (or wherever Settings points) is never touched by any of this.

## Where things live

| Path | Contents |
|------|----------|
| `~/.local/bin/cyanrip` | The Distrobox-exported ripper wrapper. Always present. **Don't edit.** |
| `~/.local/bin/metaflac` | The Distrobox-exported tag-editor wrapper. **Don't edit.** |
| `~/.local/bin/whipper` | Legacy leftover from an older whipper install, if present — no longer used; safe to remove. |
| `~/Applications/platterpus-x86_64.AppImage` | The app itself, after menu integration moves it out of Downloads. |
| `~/.config/platterpus/config.toml` | The GUI's own settings (output dir, templates, toggles) **and your drive's read offset**. The real settings file. |
| `~/.config/whipper/whipper.conf` | Legacy offset reference only — cyanrip does not use it. Kept so an upgrading user can see their old offset. |
| `~/.local/share/platterpus/log.txt` | GUI log file. Check here when something goes sideways. |
| `~/Music/rips/` *(default)* | Where rips land, under `Artist/Album/`. Configurable in Settings. |
| `…/Artist/Album/` | The rip itself: the FLAC tracks **plus** the `.log`, `.cue`, and other sidecar files cyanrip writes next to them. |

---

## Documentation for contributors

Core project documents (in this directory):

- [`CLAUDE.md`](CLAUDE.md) — project rules and conventions (read before contributing); Project operations section has current build/run/test/uninstall commands
- [`PLANNING.md`](PLANNING.md) — architecture, directory tree, per-module responsibilities, keyed design decisions (KDD-01 through KDD-21)
- [`TASKS.md`](TASKS.md) — active task checklist. P0 (T01-T32, complete), P1.1 (install/uninstall ease), P1 (broader backlog), P2 (future), Out of scope.
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — pinned versions, last upstream release dates, replacement plans, retirement-review log

Source documents and reference material (in `docs/`):

- [`docs/README.md`](docs/README.md) — index of `docs/` contents, the single-source-of-truth map + rebuild-from-scratch checklist
- [`docs/architecture.md`](docs/architecture.md) — architecture & contributor guide: layered design, patterns & lessons, extension recipes, packaging/release/security (**read before contributing code**)
- [`docs/testing.md`](docs/testing.md) — testing strategy & standards; [`docs/test-plan.md`](docs/test-plan.md) — manual & release testing procedure
- [`docs/platterpus-research-brief-v2.1.md`](docs/platterpus-research-brief-v2.1.md) — the canonical project brief
- [`docs/platterpus-session-start.md`](docs/platterpus-session-start.md) — bootstrap instructions for a fresh Claude Code session (Step 0 = optional research-rerun prompt)
- [`docs/log-format-comparison.md`](docs/log-format-comparison.md) — whipper-log vs EAC-log field comparison

Build / dev tooling:

- [`setup-host.sh`](setup-host.sh) — one-command full bootstrap (Distrobox + container + cyanrip + export + clone + dev-setup)
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
