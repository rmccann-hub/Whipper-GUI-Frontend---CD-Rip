# Whipper GUI

A Linux GUI front-end for the [`whipper`](https://github.com/whipper-team/whipper) audio-CD ripping CLI. Aims for EAC-equivalent (Exact Audio Copy) archival quality on Linux, packaged as a single-file AppImage.

> **Status: pre-alpha.** The application is implemented end-to-end and has 280+ unit tests, but it has not yet been validated against a real CD on a real Bazzite system. See [TASKS.md](TASKS.md) — T32 (end-to-end smoke test) is the only remaining P0 task.

## At a glance

- **Linux only.** Primary target is Bazzite KDE Plasma 6; should work on any modern desktop Linux running Qt 6 (Fedora, Arch, Ubuntu, Tumbleweed).
- **Runs whipper inside Distrobox.** The GUI calls the host-exported `whipper` binary; it never bundles whipper or tries to install it. This is intentional — see [PLANNING.md §8 KDD-07](PLANNING.md).
- **Single-file AppImage** for the GUI itself; no system-level installs required.
- **Bypasses whipper's interactive prompt** by querying MusicBrainz directly and passing `--release-id` to whipper. You never see a terminal prompt.
- **Distribution model:** AppImage primary, `pipx` secondary.

---

## Installation

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
sudo apt install distrobox
```

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

Picard is what you'll use to manually fix tags for discs MusicBrainz doesn't recognize. The GUI offers to install it automatically when you first need it, but you can pre-install if you'd rather:

```bash
flatpak install --user flathub org.musicbrainz.Picard
```

Verify:

```bash
flatpak run org.musicbrainz.Picard --version
```

Whipper GUI will auto-launch Picard with the rip folder when you mark a disc as Unknown Album, *if* you enable the toggle in Settings.

### Step 7 — Install Whipper GUI

> **As of right now (pre-alpha), only Method C works.** The AppImage and `pipx` wheel aren't published yet. Method C clones the source and runs the GUI directly. The other methods are documented for the future and explain themselves with a "not yet" callout at the top.

Pick **one** of the methods below.

#### Method A — AppImage (recommended for end users)

> The AppImage is not yet published as a release artifact. Until it is, use Method B or Method C below to build one yourself or run from source.

When the AppImage is available:

```bash
chmod +x whipper-gui-x86_64.AppImage
./whipper-gui-x86_64.AppImage
```

To integrate it with KDE's application menu, drop it in `~/Applications/` and use [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) or KDE's "Install AppImage" right-click option.

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

> The wheel is not yet published to PyPI. Until it is, install from a local checkout: `git clone …` then `pipx install .` from inside the repo.

Run with `whipper-gui` from any terminal.

#### Method C — From source (for developers / current state)

> The repository is currently private during pre-alpha development. Until it's flipped to Public on GitHub, you'll need to authenticate before cloning — GitHub stopped accepting passwords over HTTPS in 2021. The fastest path is the GitHub CLI:
>
> ```bash
> sudo dnf install gh      # if not already present
> gh auth login            # web-browser login; choose HTTPS → web browser
> ```
>
> After that, `git clone` over HTTPS works transparently because `gh` stores the token in your git credential helper. If you prefer SSH, set up an SSH key on your GitHub account and swap the clone URL for `git@github.com:rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git`.

```bash
git clone https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git
cd Whipper-GUI-Frontend---CD-Rip
pip install -e .
whipper-gui
```

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

**Coming in P1** (toggles EAC exposes that whipper supports but we don't yet surface):

- Cover art (fetch + embed in FLAC, or save next to it)
- Force overread into lead-out
- Max retries per track
- Keep going on track failure
- Continue ripping CD-Rs

Each is a small Settings dialog field — you can track them in [TASKS.md](TASKS.md) under "EAC bit-perfect parity gaps".

---

## First run

When you launch Whipper GUI for the first time:

1. **Dependency check.** The GUI verifies whipper, metaflac, and Picard are reachable. If anything's missing, it pops a dialog with one of three resolutions:
   - **Auto-install** (Picard): one OK and it runs `flatpak install --user`.
   - **Pending installs:** a checklist for items that need batching or confirmation.
   - **Manual install:** a copyable search string for items like `libdiscid` that need root + reboot.

2. **Pick a drive.** The dropdown at the top of the window lists everything `whipper drive list` returns. Click Refresh if you plug in a drive after launch.

3. **Insert a CD.** The GUI fetches the disc's MusicBrainz ID, looks it up, and shows the match status. If multiple releases match, a picker dialog appears (this is the GUI's substitute for whipper's interactive TTY prompt — you'll never see whipper itself ask you anything).

4. **Edit metadata.** The track table is editable. Fix any tags that look wrong before you rip.

5. **Click "Start rip."** Progress and per-track AccurateRip confidence appear as the rip runs. You can cancel mid-rip.

6. **View the log.** When the rip finishes, the "View log" button opens the rip log in your default text editor.

For discs MusicBrainz doesn't recognize, use the Unknown Album flow from the menu — the GUI rips with placeholder `Track NN` tags and optionally launches Picard for you to fix them up.

---

## Troubleshooting

### `git clone` fails with "Password authentication is not supported"

GitHub deprecated HTTPS password auth in 2021. If the repository is currently private (it is, during pre-alpha), you need to authenticate first. The fastest path on Bazzite:

```bash
sudo dnf install gh    # if not already present
gh auth login          # web-browser login; choose HTTPS → web browser
git clone https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip.git
```

`gh auth login` stores a token in your git credential helper so subsequent clones / pushes work without re-authenticating. Alternative: clone via SSH (`git@github.com:…`) if you have an SSH key on your GitHub account.

Once the repo is flipped to Public on GitHub, no authentication will be needed for read-only clones.

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

## Where things live

| Path | Contents |
|------|----------|
| `~/.local/bin/whipper` | The Distrobox-exported wrapper. **Don't edit.** |
| `~/.local/bin/metaflac` | Same. |
| `~/.config/whipper/whipper.conf` | Drive offsets and cache settings. Shared with the container. |
| `~/.config/whipper-gui/config.toml` | The GUI's own settings (output dir, templates, toggles). |
| `~/.local/share/whipper-gui/log.txt` | GUI log file. Check here when something goes sideways. |
| `~/Music/rips/` *(default)* | Where rips land. Configurable in Settings. |

---

## Documentation for contributors

- [`PLANNING.md`](PLANNING.md) — architecture, module design, design decisions
- [`TASKS.md`](TASKS.md) — active task checklist
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — dependency table, last release dates, replacement plans
- [`CLAUDE.md`](CLAUDE.md) — project rules and conventions (read before contributing)
- [`docs/log-format-comparison.md`](docs/log-format-comparison.md) — whipper-log vs EAC-log field comparison

---

## License

TBD. The project is in early bootstrap and a license has not been chosen yet. PySide6 is LGPL-3.0, which makes MIT, Apache-2.0, BSD, or GPL-3.0 all viable for the project's own code.

See [PLANNING.md §8 KDD-10](PLANNING.md) for the open license question.
