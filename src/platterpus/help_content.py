"""User-facing help text (Help → User Guide) plus shared project metadata.

This lives as a module-level string rather than a packaged data file on
purpose: it is then available identically from a source checkout, a `pipx`
install, and the single-file AppImage with zero package-data/MANIFEST wiring
(this project has been bitten by AppImage packaging gaps before — see the
CA-cert and recipe-bug notes in CLAUDE.md). To edit the guide, edit the string
below; the Help dialog renders it as Markdown.
"""

from __future__ import annotations

# Project metadata, also shown in the About dialog.
REPO_URL: str = "https://github.com/rmccann-hub/Platterpus"
ISSUES_URL: str = f"{REPO_URL}/issues"
LICENSE_NAME: str = "GPL-3.0-only"
TAGLINE: str = "EAC-equivalent archival-quality audio-CD ripping for Linux."

# The user guide, rendered as Markdown by HelpDialog. Keep it task-oriented and
# in step with the actual UI — when a feature changes, update the relevant
# section here too.
USER_GUIDE: str = """\
# Platterpus — User Guide

A friendly front-end for the **whipper** and **cyanrip** CD-ripping tools. It
rips audio CDs at archival quality (EAC-equivalent), naming and tagging tracks
from **MusicBrainz** and verifying the result against AccurateRip and CTDB.
Every rip produces a lossless **FLAC** master; you can also have **WavPack**,
**MP3**, or **WAV** derived from it (see *Output format* in Settings).

## How it's wired

The GUI runs on your desktop and calls the host-exported `~/.local/bin/whipper`,
which transparently does the actual ripping inside the `ripping` Distrobox
container. You don't interact with the container directly — the GUI handles it.

## Ripping a CD — the basics

1. **Insert an audio CD** and pick your drive in the drive selector.
2. The GUI looks the disc up on MusicBrainz and fills in the album, artist, and
   track list. If several releases match, choose the right one.
3. Check or edit the album/artist/track fields — your edits are written to the
   FLAC tags.
4. Click **Start rip**. Progress shows an overall bar plus the current task.
5. When it finishes, the status line reports a fidelity verdict and the results
   pane shows a verification banner (see below). Files land under your output
   folder (see Settings).

## Understanding the results — is my rip trustworthy?

After a rip, a bold **verification banner** sits above the per-track table and
tells you at a glance whether the rip can be trusted:

- 🟢 **Green — "Bit-perfect: all N tracks verified against AccurateRip"** —
  every track's audio matches the shared AccurateRip database. This is the
  archival gold standard: other people's rips of the same disc produced the
  exact same audio.
- 🟡 **Amber — "M of N tracks verified"** — some tracks matched and some didn't.
  The unmatched ones either aren't in the database or read differently this
  time; check the per-track table and consider re-ripping (the **Re-rip until
  reads match** setting helps marginal discs).
- ⚪ **Grey — "no tracks matched the database"** — normal for a disc nobody has
  submitted (a home-burned CD-R, or an obscure pressing). It does *not* mean a
  bad rip: the per-track **Copy CRC** still proves the disc was read securely;
  AccurateRip simply has nothing to compare against.

A track counts as "verified" only when AccurateRip reports a **confidence of 1
or more** (how many submitted rips share its checksum) — the app never calls a
track verified on a guess. If you enabled **Verify with CTDB**, its result
appears just below, colour-coded the same way (green only once its checksum is
hardware-confirmed; an experimental match shows amber).

Alongside the rip, two records are saved next to your music: the backend's
human-readable **`.log`**, and a **`.platterpus.json`** report with the same
results in a machine-readable form (per-track CRCs, AccurateRip/CTDB outcomes,
the verdict) — handy for scripting, re-verifying later, or attaching to a report.

## Unknown discs

If MusicBrainz has no match (or you're offline), use **File → Rip as Unknown
Album…**. The track list is filled with placeholders you can edit; the folder is
named from the album artist/title you type.

## Stopping a rip

- **Cancel** stops the current rip. Because the reader runs inside the
  container, the drive can take a moment to spin down.
- If the drive keeps spinning, **Force stop** ejects and kills the reader. After
  Cancel the GUI also auto-escalates to a force-stop after a few seconds.
- **A disc *scan* can get stuck too** (a slow drive's table-of-contents read
  holding the drive). **Force stop** is available during a scan as well — it
  frees the drive without ejecting, so the disc stays in for a **Rescan disc**.
  A scan that times out frees the drive on its own.

## Settings (Tools → Settings)

- **Goal** — pick what you want the rip to be and the format/verification/quality
  options snap to good values for it: *Fast verified* (lossless, AccurateRip-
  checked — the recommended default), *Archival exact* (also CTDB-verify and
  smallest lossless files), or *Portable* (an MP3 copy for phones). You can still
  tweak any individual option below — that switches the Goal to *Custom*.
- **Output format** — *FLAC* (the lossless archival master, always produced),
  *WavPack* (also lossless, with tags), *MP3* (best-quality VBR for phones), or
  *WAV* (raw PCM — no tags or cover art). Non-FLAC formats are derived from the
  FLAC master, which is always kept, so you never lose the archival copy.
- **Output folder** and **file-name templates** (separate templates for known
  and unknown discs).
- **Continue on CD-R** — needed to rip home-burned discs.
- **Cover art** — off, embedded, or saved as a file. Works with both
  backends: whipper fetches it itself; with cyanrip this app fetches the
  front cover from the Cover Art Archive after the rip.
- **Force overread**, **max retries**, **keep going on errors** — EAC-parity
  read options.
- **Re-rip until reads match** — for a damaged or marginal disc, re-read each
  track until this many passes agree on the checksum, so a shaky read converges
  to the bit-perfect result. Leave it at *Off* for clean discs (the normal
  secure read already handles those); try **2** if a track won't verify against
  AccurateRip. This is a cyanrip feature — it greys out under the whipper
  backend, which has no equivalent.
- **Verify with CTDB after a rip** — a second, whole-disc verification against
  the CUETools Database, alongside AccurateRip. A network check, off by default,
  and labelled *experimental* until its checksum is confirmed on real hardware
  (it can only ever under-claim, never falsely say "verified").
- **Verify FLACs after a rip** — decode each FLAC back and check it against its
  stored checksum (on by default; greyed out for whipper, which verifies as it
  encodes). **Re-compress FLACs** optionally re-encodes them at maximum effort
  to shrink the files — lossless, with tags and art preserved (off by default;
  greyed out for cyanrip, which already maxes compression).
- **Read offset override** — set the drive read-offset by hand (the drive-setup
  wizard is the recommended way to set it).
- **Eject after a successful rip** — automatically eject the disc when a rip
  finishes (off by default). You can always eject by hand with the **Eject**
  button next to the drive picker.
- **Ripping backend** — *whipper* (default) or *cyanrip*. cyanrip avoids a
  whipper bug that can fail tracks on drives with a read offset over 587
  samples, so it's the better choice on affected drives (e.g. the Pioneer
  BDR-209D). Picking cyanrip offers to install it for you; restart the app
  after switching. Options one backend doesn't support grey
  out with a tooltip explaining why — your values are kept, and switching
  back re-enables them. The rest of the app works the same either way.

## Where the app lives

When you accept the "Add to your applications menu?" offer, the app
moves itself from Downloads to `~/Applications` and the menu entry
points there — so cleaning out Downloads never removes it.

## Updates (Help → Check for updates)

Asks GitHub whether a newer release exists. If one does, the app updates
itself: the new version downloads in the background (with a progress
bar you can cancel), is verified against the release's published
checksum, and installs to `~/Applications` — then the app offers to
restart into the new version. Nothing changes if the download fails or
you cancel.

## Uninstalling (Tools → Uninstall Platterpus)

Removes everything the app installed: shortcuts, the whipper/metaflac/cyanrip
commands, the ripping container, optionally your drive calibration
(whipper.conf) and the AppImage file, and the app's own settings and logs.
**Your music is never touched**, and Distrobox/podman stay installed (other
containers keep working). You'll confirm before anything is removed.

## Drive setup (Tools → Set up drive)

Sets your drive's **read offset** — the one calibration that makes rips
bit-perfect. For most drives the wizard already knows the right value (from
the bundled AccurateRip drive list) and pre-fills it, so it's a single
**Save offset** click — no disc needed. If your drive isn't in the list,
insert a popular commercial CD and click **Detect**, or type the offset by
hand. The value is saved as the app's offset override (and `whipper.conf` is
backed up first if it's touched). Do this once per drive.

The disc panel shows a **Read offset** line for the selected drive telling you
*where* the offset came from and how confident we are — measured on your drive
(high), looked up from the AccurateRip list (medium), or entered by hand. If two
identical drives are connected, or the recorded offset disagrees with what
whipper will apply, a warning appears there so a wrong offset can't pass
unnoticed.

## Troubleshooting

- **Disc not detected, or the first scan failed** → click **Rescan disc**
  (next to Refresh). The first read sometimes happens while the disc is
  still spinning up; a rescan almost always works.
- **No drive found** → *Tools → Diagnose drive access*. If it's a permissions
  problem it will tell you the exact `usermod` command to run (then log out and
  back in).
- **Drive keeps spinning after Cancel (or during a stuck scan)** → click
  **Force stop**.
- **Window goes black during a rip (KDE Plasma 6 / Wayland)** → the app now runs
  through XWayland automatically to avoid this. If you ever want native Wayland
  instead, launch with `QT_QPA_PLATFORM=wayland`.
- **Disc not identified** → check your network; you can still rip via *Rip as
  Unknown Album* and tag later.
- **Something else** → the log has the details; please attach it when reporting
  an issue. The quickest way to find it is **Help → Open logs folder…**, which
  opens the folder containing `log.txt` in your file manager. For a *verbose*
  log, turn on **Debug logging** in Settings, reproduce the problem, then attach
  that file — it records every step (off by default to keep the log light).

## More

- Project & issues: see **Help → About** for links.
- Dependencies (whipper, MusicBrainz Picard, etc.) are checked automatically at
  launch and from the Settings dialog.
"""
