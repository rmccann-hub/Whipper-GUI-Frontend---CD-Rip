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
REPO_URL: str = "https://github.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip"
ISSUES_URL: str = f"{REPO_URL}/issues"
LICENSE_NAME: str = "GPL-3.0-only"
TAGLINE: str = "EAC-equivalent archival-quality audio-CD ripping for Linux."

# The user guide, rendered as Markdown by HelpDialog. Keep it task-oriented and
# in step with the actual UI — when a feature changes, update the relevant
# section here too.
USER_GUIDE: str = """\
# Whipper GUI — User Guide

A friendly front-end for the **whipper** CD-ripping tool. It rips audio CDs to
**FLAC** at archival quality (EAC-equivalent), naming and tagging tracks from
**MusicBrainz**.

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
5. When it finishes, the status line reports a fidelity verdict (e.g. *"all N
   tracks verified, Test/Copy CRCs match"*). Files land under your output
   folder (see Settings).

## Unknown discs

If MusicBrainz has no match (or you're offline), use **File → Rip as Unknown
Album…**. The track list is filled with placeholders you can edit; the folder is
named from the album artist/title you type.

## Stopping a rip

- **Cancel** stops the current rip. Because the reader runs inside the
  container, the drive can take a moment to spin down.
- If the drive keeps spinning, **Force stop** ejects and kills the reader. After
  Cancel the GUI also auto-escalates to a force-stop after a few seconds.

## Settings (Tools → Settings)

- **Output folder** and **file-name templates** (separate templates for known
  and unknown discs).
- **Continue on CD-R** — needed to rip home-burned discs.
- **Cover art** — off, embedded, or saved as a file.
- **Force overread**, **max retries**, **keep going on errors** — EAC-parity
  read options.
- **Read offset override** — set the drive read-offset by hand (the drive-setup
  wizard is the recommended way to set it).
- **Eject after a successful rip** — automatically eject the disc when a rip
  finishes (off by default). You can always eject by hand with the **Eject**
  button next to the drive picker.

## Drive setup (Tools → Set up drive)

Runs whipper's own **drive analyze** and **offset find** and writes them to
`whipper.conf`. Do this once per drive for accurate, AccurateRip-comparable
rips. Your existing `whipper.conf` is backed up first.

## Troubleshooting

- **No drive found** → *Tools → Diagnose drive access*. If it's a permissions
  problem it will tell you the exact `usermod` command to run (then log out and
  back in).
- **Drive keeps spinning after Cancel** → click **Force stop**.
- **Disc not identified** → check your network; you can still rip via *Rip as
  Unknown Album* and tag later.
- **Something else** → the log at `~/.local/share/whipper-gui/log.txt` has the
  details; please attach it when reporting an issue.

## More

- Project & issues: see **Help → About** for links.
- Dependencies (whipper, MusicBrainz Picard, etc.) are checked automatically at
  launch and from the Settings dialog.
"""
