# Changelog

**This is the single, authoritative record of all notable changes to
Platterpus** — add an entry to `[Unreleased]` in the *same commit* as any change.
Format follows [Keep a Changelog](https://keepachangelog.com/); the project
adheres to [Semantic Versioning](https://semver.org/); dates are ISO-8601
(YYYY-MM-DD). The version itself is single-sourced from
`src/platterpus/__init__.py` (`__version__`); at release time the `[Unreleased]`
entries move under a dated `## [X.Y.Z]` heading. (Design decisions live in
`PLANNING.md` KDDs and the CLAUDE.md session log — not here.)

## [Unreleased]

### Added
- **The `.platterpus.json` is now the single debug record for a rip** — the only
  files a rip leaves are the EAC-compliant `.log`, the `.cue`, and this one JSON.
  It now folds in **all** post-rip verification: the CTDB verdict (as before) plus
  the **FLAC-integrity** decode result and the **transcode** outcome, and a
  **per-file SHA256** map for long-term integrity checking (bit-rot) — embedded
  here rather than a separate `checksums.sha256` sidecar. The report is re-written
  as each async check finishes, so the final file always reflects every one.

### Changed
- **Every rip now fully verifies the bit-perfect FLAC master before deriving any
  format.** Verification used to be format-dependent (CTDB only ran under the
  Archival goal). Now all three goals — and a fresh install — run the full suite
  on the master: **AccurateRip** (always) + **CTDB** whole-disc + **FLAC-integrity
  decode**, *before* any MP3/WavPack/WAV transcode. So a portable MP3 is derived
  from a master that's had exactly the same proof as an archival FLAC. The FLAC
  master is always kept. CTDB is now on by default (a network lookup + a decode
  per rip; it fails safe and off-thread, and is still toggleable). The goals now
  differ only in *output* and *compression effort*, never in how hard they check.

### Added
- **File-naming presets with a live preview.** Settings has a new "Naming
  scheme" dropdown offering the layouts the popular tools use — *Artist / Album
  / 01 - Title* (the clean default, à la Picard/beets/Plex), a no-dash variant,
  *Artist / Album (Year)* (Plex/Jellyfin media-server style), *Artist / Year -
  Album* (foobar2000 chronological), and a compilation layout that keeps the
  per-track artist. Picking one fills the template fields; hand-editing flips it
  to "Custom". An **Example** line renders the real resulting filename live
  (against a metadata-heavy sample) so you see exactly what you'll get — colons
  and all — before committing.

### Changed
- **The default filename layout is now the clean `Artist/Album/01 - Title`.** The
  old default repeated the album and artist in every filename and tacked the full
  release date on the end (`01 - Roxanne - Every Breath You Take… - The Police -
  1995-09-12.flac`). Existing configs still on that default auto-upgrade on load;
  a hand-edited template is never touched.
- The **album-artist field** now has a tooltip explaining it fills every track's
  Artist column and that individual rows can be overridden (for compilations or
  featured guests).

### Fixed
- **Dialogs now centre over the main window even when they're a plain message
  box.** The 0.4.4 centering only covered our own dialog subclasses, so the
  first-run "add to menu", shortcut, and update prompts (plain `QMessageBox`)
  could still open on another monitor. An application-wide filter now centres
  every dialog — message boxes and file pickers included — on the window that
  opened it. (Still a no-op under native Wayland, where clients can't position
  themselves; the app prefers XWayland, where it works.)
- **The main-window splitter is draggable at the normal window size, not only
  when maximized.** The three stacked panes' minimum heights summed to nearly
  the whole default window, so the splitter handles showed the resize cursor but
  had no slack to move (real-user report on 0.4.4). The scrollable areas (track
  list, rip log, AccurateRip table) now keep a small minimum height, so the
  splitter can always redistribute space. (The default window size is unchanged
  — making it taller would overflow 1366×768 laptops.)

## [0.4.4] — 2026-06-30

### Added
- **Accessibility pass.** Keyboard and screen-reader coverage of the everyday
  surfaces: the album artist/title/year fields and the disc-info values (drive,
  disc IDs, MusicBrainz match, AccurateRip, read offset) now carry accessible
  names — a screen reader announces each by what it holds instead of reading
  anonymous text boxes — and Quit / Settings / User Guide gained the
  platform-standard keyboard shortcuts. (Builds on the verdict/progress surfaces,
  which already named themselves and never signal trust by colour alone.)

### Changed
- **The Start button now explains why it's greyed out.** A disabled button with
  no explanation reads as broken; hovering Start now says exactly what's missing
  and how to fix it — "Insert a disc and choose a drive," then "Identify the disc
  first: pick a MusicBrainz match, or use File → Rip as Unknown Album," and once
  ready, "Start ripping the disc in the selected drive." (general UX principle:
  never leave the user guessing why a control is dead.)
- **The "optional components" prompt no longer looks like a contradiction.**
  After a clean dependency check the app used to show "0 missing/needs-attention"
  and then *immediately* pop a separate "Install optional components?" question —
  which read as "nothing's wrong… so why are you asking me to install something?"
  (real-user report on 0.4.2). Now, when everything required is present, a single
  outcome-first dialog leads with "✓ Everything required is installed — you're
  ready to rip," then lists each optional extra with *what it does for you*
  (e.g. "Picard — auto-launched on unknown discs") and offers to install it. No
  more back-to-back popups.

### Fixed
- **The app no longer freezes while installing a dependency.** Installing an
  optional component (e.g. the Picard Flatpak) ran the install **on the UI
  thread**, so the whole window locked up — unclickable, not repainting — until
  the download finished (real-user report on 0.4.2). The install now runs on a
  worker thread, so the dialog stays live and shows per-row progress; the window
  never freezes. The dialog also refuses to close mid-install (the title-bar ✕
  is gated too, not just Cancel) and is wider so its text no longer truncates.
  Container tools still install through the setup wizard (which has always had
  its own off-thread progress), and only that wizard — not the install loop —
  ever opens on the UI thread.
- **Dialogs now open over the main window, not on another monitor.** On a
  multi-monitor desktop a first-run modal could pop up on a *different* screen
  from the main window; because it was application-modal it correctly refused
  input on the main screen, so the app *looked* frozen even though it was just
  waiting for an unanswered prompt the user couldn't see (real-user report on
  0.4.2). Every dialog now centres itself on the window that opened it the first
  time it's shown, so the prompt appears where you're already looking. (No-op
  under native Wayland, where clients can't position themselves.)

## [0.4.2] — 2026-06-30

### Added
- **The rip report is now a self-contained debug record.** The
  `.platterpus.json` beside the FLACs now embeds this session's log — everything
  since the app launched (setup, dependency probes, the MusicBrainz lookup, the
  read offset, the rip itself) — with **other albums' rips filtered out**, so a
  single file has the full picture for *that* album without the noise of others
  ripped in the same session. The on-disk `log.txt` is unchanged (it stays the
  always-on rolling log, including every rip — the catch-all for problems that
  happen with no rip to attach to, like a failed setup or a crash before any rip
  completes).
- **Two new post-rip buttons** in the results pane, beside "View log": **"View
  report"** opens the `.platterpus.json`, and **"Open rip folder"** reveals the
  album folder (FLACs + `.log` + `.json` + `.cue`). All three stay greyed out
  until a rip finishes.

## [0.4.1] — 2026-06-30

### Removed
- **whipper is gone — cyanrip is the sole ripping backend.** After confirming
  cyanrip needs nothing structural for EAC parity (it already hits AccurateRip
  confidence 200 / bit-perfect on real hardware) and that whipper had no
  functional advantage — only the drive-dependent >587 read-offset *bug* that
  always favoured cyanrip — the whipper backend, its Settings dropdown, its
  whipper-only options (CD-R allow, force-overread, keep-going, the whipper-path
  field), and its container install/export were all removed. The setup wizard
  now installs cyanrip + flac + metaflac only. The drive-setup wizard saves the
  detected read offset to Platterpus's own settings (cyanrip is fed it as `-s`;
  it reads no config file of its own). A legacy `whipper.conf` offset is still
  shown for reference. The backend interface (`RipBackend` ABC) stays so another
  engine could be slotted in later. The `setup-host.sh` / `install.sh` scripts
  install cyanrip + flac (not whipper) now, and the docs (README, DEPENDENCIES,
  PLANNING KDD-18, the user guide, the locked Critical Rules) were updated.

### Added
- **The rip record now captures cyanrip's secure-rerip detail.** A `-Z N` rip of
  a marginal disc writes information the parser previously dropped; it's now
  surfaced in the `.platterpus.json` report (and, where it matters, on screen):
  per-track **rip count** ("after N rips" — how many read passes a track
  needed), the **+450-frame offset-variant** AccurateRip match (`offset_450`;
  cyanrip's "partially accurately ripped" — recorded as data, never counted as a
  plain exact match so the verdict can't over-claim), the **"Tracks ripped
  partially accurately"** summary, the disc's **audio duration** ("Total time"),
  and the **Paranoia status counts** (READ/VERIFY/FIXUP_ATOM/OVERLAP — the
  error-correction activity that explains a slow rip). The status-line fidelity
  summary now notes partially-accurate tracks, so a "12/14 verified" result
  reads as a pressing-offset quirk rather than a bad rip.
- **The rip record now shows actual elapsed time vs the ripper's estimate.**
  cyanrip's on-screen ETA is computed from the current read pass only, so it
  can't see secure re-read passes (`-Z N`) and badly under-estimates marginal
  discs (a real 14-track disc took 2h45m while the ETA sat at "~35m"). The app
  log now records the *actual* wall-clock the rip took — the figure only the GUI
  can measure, since cyanrip logs the disc's audio length and a finish timestamp
  but never its own run time — alongside cyanrip's first ETA so the gap is
  auditable. The `.platterpus.json` report gains a `timing` section
  (`elapsed_seconds`/`elapsed_human`, `started_at`/`finished_at`, and the
  estimate when one was seen).
- **The Platterpus logo now appears in the About dialog** (Help → About), above
  the version and environment details.
- **One dependency dialog instead of several.** A fresh install used to pop a
  separate dialog for each missing piece (the ripper *and* metaflac each opened
  their own). Now every installable missing dependency is a single checkbox row
  (ticked by default) in one "Pending installs" dialog: tick what you want,
  press Install, and watch each row's progress. The dismiss button stays greyed
  out until the install actually completes. Container tools (cyanrip, flac,
  metaflac) install via the one setup wizard — opened at most once even when
  several are missing — and packaged deps (Picard) install in place.
- **The UI locks down during a rip.** While a rip is running, the drive
  selector (and its Refresh/Rescan/Eject), the editable track list, and the
  conflicting menu actions (Settings, Set up drive/Platterpus, Rip as Unknown,
  Check for updates, Uninstall, …) grey out — so nothing can be changed
  mid-rip. Only Cancel, Force stop, and Quit stay available; **quitting during a
  rip force-stops it** (kills the reader so the drive isn't left spinning).
- **`scripts/ctdb_verify.py --calibrate`** — a hardware-validation helper that,
  for a disc that's in CTDB, sweeps candidate offset-guard trims over the
  decoded PCM and reports which reproduces the database CRC, pinning the CTDB
  CRC algorithm against a real disc (`platterpus.ctdb.calibrate`). Developer
  tooling toward flipping CTDB from experimental to verified (KDD-16).

### Fixed
- **CTDB verification now reaches the database.** The lookup was hardcoded to
  `https://db.cuetools.net`, which fails with a TLS hostname mismatch (the host
  serves no valid certificate). It now queries over `http://` like the reference
  CUETools client — correct for a read-only public CRC lookup whose trust comes
  from comparing the returned CRC locally. (CTDB matches still show as
  *experimental* until the CRC algorithm is hardware-validated — KDD-16.) *This
  fixes the `lookup_error` seen on 0.4.0.*
- **Release workflow no longer publishes before its assets finish uploading.**
  The release was made visible (and so seen by the in-app update checker) the
  instant it was created, while the 237 MB AppImage was still uploading — so the
  small `.sha256` the updater fetches first could 404 for anyone who checked in
  that window ("couldn't fetch the update checksum: HTTP Error 404", seen on
  v0.4.0). The release is now created as a **draft**, all assets attached, then
  published atomically — closing the window.
- **`uninstall.sh` now removes the menu entry and icon the AppImage actually
  installs.** It deleted `platterpus.desktop` / `platterpus.png`, but the
  AppImage integrates them under the freedesktop app-id
  (`io.github.rmccann_hub.Platterpus.*`), so the menu entry and icon were left
  behind. It now removes both names, plus any pre-rename `whipper-gui` config,
  logs, desktop entries, and AppImage — for a genuinely clean slate.
- **Documentation and on-screen text now match the cyanrip-only app.** A
  post-removal audit caught text that still described whipper as the live
  ripper: the README's manual-install offset steps told you to run
  `whipper offset find` and hand-edit `whipper.conf` (both gone — replaced with
  the in-app drive-setup-wizard flow and a note that cyanrip uses no config
  file), a stale "Ripping backends: whipper (default)" section, a setup-complete
  message that said "whipper is installed," and a drive-failure hint that cited
  a whipper-only cd-paranoia bug and a removed "Keep going" setting. Many
  code comments that claimed whipper's *current* behaviour were corrected to
  describe cyanrip (with whipper kept only as accurate history).
- **The Tools menu said "Set up Whipper GUI…"** — a leftover from before the
  rename. It's now "Set up Platterpus…".

### Changed
- **The main window's panels are now resizable.** The disc-info panel, track
  list, and the controls + progress/log block sit in a vertical splitter — drag
  the dividers to give more room to the track list or the log, in both normal
  and maximized windows.
- **cyanrip is no longer labelled "experimental."** It's the hardware-validated
  backend (and the recommended one for drives with a read offset over 587, like
  the Pioneer BDR-209D, where whipper has a known bug). The Settings entry and
  help now drop the tag and keep only the real caveats (install it in the
  container; restart after switching). CTDB verification stays *experimental*
  until its CRC algorithm is hardware-validated (KDD-16) — that one is accurate.

## [0.4.0] — 2026-06-29

### Added
- **A machine-readable JSON rip report is now saved beside every rip log**
  (`<name>.platterpus.json`). It captures the drive/rip settings, each track's
  CRCs and AccurateRip result, the overall verification verdict, and (if you ran
  it) the CTDB result — the structured companion to the human-readable log, for
  re-verification, scripting, or attaching to a report. It's re-written to include
  the CTDB verdict once that check finishes. `scripts/rip_report.py` regenerates
  it from any rip log.
- **Settings → Goal presets.** A single "Goal" choice at the top of Settings
  anchors the rest to your intent: *Fast verified* (lossless, AccurateRip-checked
  — the recommended default), *Archival exact* (also CTDB-verify + smallest
  lossless files), or *Portable* (an MP3 copy). Picking one snaps the
  format/verification/quality controls to good values; editing any of them
  switches the Goal to *Custom*. The default matches the previous behaviour, so
  nothing changes unless you choose a different goal.
- **Accessibility pass on the rip screen.** Screen readers now announce every
  status surface by name (the two progress bars, rip status, log output, the
  verification verdict banner, the per-track AccurateRip table, the CTDB result,
  the drive selector, and the track list). The verification verdict is conveyed
  by a leading symbol **and** text (✓ verified / ⚠ partial / ⓘ not-in-database),
  never by colour alone — so colour-blind and screen-reader users get the same
  signal as the green/amber/grey tint.

### Added
- **Per-drive trust line: where your read offset came from, and how sure.**
  The disc panel now shows a "Read offset" row for the selected drive — e.g.
  *"+667 — from the AccurateRip list (medium confidence)"* or *"measured on
  this drive (high confidence)"* — so you can see at a glance whether the offset
  is a measurement of your actual drive or a model-list lookup to confirm. If a
  second identical drive is connected, or the recorded offset disagrees with
  what whipper.conf will apply, a plain-text ⚠ warning appears there too — the
  "silent wrong-offset rip" (the classic identical-drive bug) becomes visible
  instead of silent. (UX gap #6.)

  Under the hood this is a new drive-profile ledger (`drive_profiles.py` +
  `drive_profile_store.py`, `~/.config/platterpus/drive_profiles.json`) keyed by
  a stable hardware fingerprint (WWN → serial → vendor/model). It is a **trust
  ledger only**: `whipper.conf` and the `--offset` override remain the sole
  authorities for the offset a rip actually uses (PLANNING.md KDD-23).
  *Applying* a remembered offset per drive (true multi-drive correctness) is a
  separate, hardware-gated change and is not done here.

### Removed
- **The one-time `~/.config/whipper-gui` → `~/.config/platterpus` settings
  migration** (the project-rename compatibility shim) is gone, along with its
  `LEGACY_APP_NAME`/`LEGACY_CONFIG_DIR` constants and tests. The rename has
  shipped; there's nothing left to migrate.

### Changed
- **In-app User Guide refreshed** to match the current app: both backends
  (whipper + cyanrip), multiple output formats, and the Output format,
  Verify/Re-compress FLACs, and per-drive read-offset trust-line features.
- **README** now shows the rasterized PNG logo (renders reliably on GitHub) and
  its status reflects v0.3.x with current feature highlights.
- **Clearer, outcome-first wording on two technical Settings/setup labels.**
  The overread toggle now reads "Read past the last track to catch any final
  samples (overread)" (under a "Disc lead-out" label) instead of leading with
  the jargon "Force overread into the lead-out". The drive-setup wizard's
  audio-cache result now explains the *effect* first — "this drive caches
  audio, so Platterpus will read around the cache to keep rips bit-perfect" /
  "this drive doesn't cache audio, so its reads are already trustworthy" —
  instead of "will be defeated for secure rips" / "doesn't need cache-defeating".
  (UX gap #5 — lead with the effect, then the term.)
- **Internal: the backend abstract base class is renamed `WhipperBackend` →
  `RipBackend`** (contributor-facing only; no behaviour change). It is the
  backend-neutral interface that *both* the whipper backend
  (`WhipperHostExportedImpl`) and the cyanrip backend (`CyanripImpl`) implement,
  so naming it after one of its two implementations was misleading legacy. The
  whipper backend itself, `WhipperError`, the `whipper_backend.py` module, and
  the `~/.local/bin/whipper` / `whipper.conf` routing are unchanged.
- **Project renamed to Platterpus** (was "Whipper GUI" /
  `Whipper-GUI-Frontend---CD-Rip`). New tagline: *a secure, EAC-style CD ripper
  for Linux (FLAC, WAV, WavPack, MP3)*. The Python package is now `platterpus`,
  the command and config/cache dir are `platterpus`
  (`~/.config/platterpus`, `~/.local/share/platterpus`), and the freedesktop
  app-id / `.desktop` / AppStream id is `io.github.rmccann_hub.Platterpus`.
  **Your settings carry over automatically:** on first launch Platterpus copies
  an existing `~/.config/whipper-gui` into `~/.config/platterpus` if the new dir
  doesn't exist yet. The `whipper` (and `cyanrip`) *backend* is unchanged — only
  the front-end was renamed. Added a project logo (`assets/platterpus-logo.svg`),
  now used as the window/app icon. The rasterized icon bitmaps are now committed
  too — the 512px `build/python-appimage/io.github.rmccann_hub.Platterpus.png`
  the AppImage bundles, and the hicolor/favicon set under `assets/icons/`
  (16–512px), all regenerated from the SVG by `build/make_icon.py`.

### Added
- **`scripts/render_eac_log.py` — render a rip log into an EAC-*layout*
  comparison log.** Turns a cyanrip/whipper rip log into text that mirrors EAC's
  section/per-track layout so you can `diff`/`meld` it against a real EAC log and
  see the per-track Copy CRCs line up (the readable companion to
  `scripts/eac_parity.py`). It is **clearly attributed and never signed** — the
  first line says it was generated by Platterpus and is not a genuine EAC log,
  and the footer carries an explicit "not signed by Exact Audio Copy" marker in
  place of EAC's checksum. It only ever renders real rip data and refuses to
  fabricate an EAC signature (see `docs/eac-log-and-repair-feasibility.md`).

### Fixed
- **The post-rip status line now reports AccurateRip the same way the verdict
  banner does.** When per-track AccurateRip data is available it counts verified
  tracks with the same confidence ≥ 1 rule as the banner (e.g. "AccurateRip:
  12/14 verified") instead of paraphrasing the log's summary line, so the
  one-line status and the banner can't disagree. The in-app User Guide now also
  explains the verdict banner (what green/amber/grey mean) and the new "Re-rip
  until reads match" and "Verify with CTDB" settings.
- **The "AccurateRip" line in the disc panel now agrees with the results-pane
  verdict — and correctly counts cyanrip verifications.** It previously decided a
  track was verified by looking for the words "exact match" in the log, with no
  confidence check. That meant (a) it could disagree with the new verdict banner
  on the same screen, and (b) — because cyanrip writes "accurately ripped,
  confidence N" with no "exact match" wording — it showed "not in database" for a
  disc cyanrip had *fully verified*. Both surfaces now use one shared rule
  (AccurateRip confidence ≥ 1), so the panel and the banner can never contradict
  each other and a cyanrip rip's verification is reported honestly.

### Added
- **At-a-glance verification verdict banner above the results table.** A single
  bold, colour-coded headline now summarises whether the rip is trustworthy
  without reading every row: green "✓ Bit-perfect: all N tracks verified against
  AccurateRip (confidence X+)" when every audio track matched the shared
  database, amber when only some matched, grey for a disc nobody has submitted
  (e.g. a CD-R — where the per-track Copy CRCs still prove a secure read). The
  wording never over-claims — it only ever reports what AccurateRip actually
  returned (a confidence of 0 / "not present" never counts as verified). The
  CTDB result line below it is now colour-coded the same way (green only for a
  hardware-validated match; an experimental match stays amber).
- **Settings → "Re-rip until reads match" for damaged or marginal discs (cyanrip
  only).** Maps to cyanrip's `-Z N`: each track is re-ripped until that many reads
  produce the same checksum, so a shaky read converges to the bit-perfect result
  instead of landing on a near-miss against the AccurateRip consensus (the
  Track-3-class gap in the EAC-parity work). Off by default — a clean disc doesn't
  need it and it costs time, so the normal secure read (paranoia + retries) still
  handles those. Try **2** if a track won't verify against AccurateRip. The whipper
  backend has no equivalent flag, so the control is greyed out (your value is kept)
  when whipper is selected.

### Fixed
- **A colon in an album/track title now ends up as a real `:` in the FLAC tags
  (cyanrip backend).** cyanrip's command line can't carry a literal colon, so the
  app feeds it a look-alike (`∶`) to keep the rip working and the folder name
  clean; a post-rip step now rewrites the *tags* back to a real `:` (e.g. the
  album tag reads "Every Breath You Take: The Classics", not "…∶ The Classics").
  It only runs when a name actually contains a colon, and only the affected tags
  are rewritten — everything cyanrip set (genre, MusicBrainz ID, ISRC, cover art)
  is left untouched. The folder name keeps the `∶` (a real colon in a path is
  best avoided across tools). To fix tags on an album you ripped before this
  release, re-rip it, or run `metaflac` to set the album tag by hand.

## [0.3.9] — 2026-06-27

### Fixed
- **The window no longer goes black during a rip on KDE Plasma 6 (Wayland).**
  This Qt build doesn't repaint a window region that was covered by another
  window and then re-exposed while a rip is running — it went black until you
  interacted with it. On a Wayland session the app now prefers **XWayland**
  (`QT_QPA_PLATFORM=xcb;wayland`), which repaints correctly; the value is a
  fallback list, so if XWayland can't load it drops straight back to native
  Wayland (it can never stop the app from launching). Set
  `QT_QPA_PLATFORM=wayland` yourself to force native Wayland. As a belt, the
  window also forces a full redraw a couple of times a second *while a rip is
  running*, so any stray black region self-heals. (Earlier 0.3.8 throttle helped
  a different, flood-driven case; this is the Wayland repaint cause.)

## [0.3.8] — 2026-06-27

### Fixed
- **Cancel now actually stops a cyanrip rip.** The force-stop only ever targeted
  whipper and its readers (cdparanoia/cdrdao), so cancelling a *cyanrip* rip left
  the in-container cyanrip running — the disc kept ripping after Cancel. cyanrip
  is its own reader, so it's now killed by name too.
- **The window no longer goes black when another window is dragged over it during
  a rip.** cyanrip redraws its progress many times a second, and forwarding every
  redraw to the log pane flooded the GUI's event loop so it couldn't repaint. The
  log pane now updates at most ~10×/second (the progress bar and ETA still move
  smoothly); errors and phase changes are never delayed.
- **The app now relaunches reliably after an in-app update.** The new AppImage was
  being started with the *old* AppImage's environment (`LD_LIBRARY_PATH`,
  `PYTHONHOME`, …), which made the new instance crash silently on launch — the
  "it closed but didn't reopen" report. It now starts with a clean environment.
- **Installing a dependency no longer re-scans the disc.** Finishing setup only
  re-lists drives when none is selected yet (first-time setup); a later install
  (e.g. adding flac) leaves your disc scan alone.

## [0.3.7] — 2026-06-27

### Fixed
- **Albums with a colon in the title no longer produce a corrupted folder name
  on the cyanrip backend.** "Every Breath You Take: The Classics" was coming out
  as a folder named `Every Breath You Take∶album_artist= The Classics` (and the
  rip failed). Cause: cyanrip's command-line metadata parser splits on `:`
  *before* honoring backslash-escaping, so any colon inside a value got
  mis-parsed and injected a spurious key. The colon is now substituted with the
  identical-looking `∶` (U+2236 — the same character cyanrip uses when putting a
  colon in a path), so folders are clean and the parser can't choke. *(Restoring
  the literal `:` in the FLAC tags themselves is a follow-up.)*

### Changed
- **The post-update relaunch is now logged.** After an in-app update, the log
  records when the app spawns the new version, and a spawn that fails now tells
  you (instead of silently closing) so you're never left with no window. The new
  AppImage cold-extracts on first launch, so the new window can take 20-30s to
  appear — that delay is normal, not a failure.

## [0.3.6] — 2026-06-27

### Added
- **Tools → Check dependencies can now install the *optional* components.** When
  Picard or `flac` show as "optional, not installed," the check offers to install
  them on the spot — Picard installs automatically (Flatpak); `flac` is set up in
  the ripping container via the one-click wizard. Both route through the existing
  dependency subsystem (no separate install path). Previously the check only
  *reported* optional components with no way to act.

## [0.3.5] — 2026-06-27

### Fixed
- **The setup now installs the `flac` decoder where the app can find it.** The
  setup wizard installed `flac` in the container (the "whipper + flac" step) but
  never exported it to `~/.local/bin`, so it showed as "optional, not installed"
  and `flac --test` integrity verification (used for rips a backend doesn't
  self-verify, i.e. cyanrip) and the CTDB audio cross-check couldn't run. The
  export step now exports `flac`, and re-running **Tools → Set up Platterpus…**
  repairs an existing install.

### Added
- **Force stop now works during a stuck disc *scan*, not just a rip.** A slow
  drive's table-of-contents read can hold the drive open (the in-container
  reader keeps spinning even after the scan times out, because the kill signal
  doesn't cross into the container). Force stop is now enabled during a scan and
  frees the drive **without ejecting**, so the disc stays in for a Rescan; a scan
  that times out frees the drive automatically. No more dropping to a terminal
  to recover a wedged drive.
- **Help → Open logs folder…** opens the folder containing `log.txt` in your
  file manager — one click to grab logs when reporting a problem, no terminal.

## [0.3.4] — 2026-06-27

### Fixed
- **The first disc scan of a session no longer fails with "whipper timed out
  after 30s."** The first `whipper` call has to start the Distrobox `ripping`
  container (podman cold-start), which on first use after a boot routinely takes
  longer than the old 30s scan / 10s launch-probe caps — both were calibrated
  for a *warm* system. They now budget for a cold container (120s scan, 60s
  launch probe), so the launch probe waits for the container to come up — which
  **warms it** — and the disc scan that follows runs warm and fast. If a scan
  still times out, it now shows a plain-language message pointing at **Rescan
  disc** (a retry against the now-warm container almost always succeeds) instead
  of the raw timeout line. (Real-user report, Bazzite + Pioneer BDR-209D.)

## [0.3.3] — 2026-06-27

### Fixed
- **The in-app updater no longer freezes the window ("Not Responding").** The
  download worker's `progress`, `status`, and `finished` signals were connected
  to local closures / a lambda, which Qt delivers as *direct* connections — so
  they ran on the **worker thread** and updated the progress dialog (and popped
  the restart prompt) from off the GUI thread. Touching widgets off the GUI
  thread is illegal in Qt and deadlocked the window — the freeze that looked like
  "hanging on 100%". They're now **bound methods**, which Qt queues to the GUI
  thread (the same fix already applied to the launch dependency check). **Note:**
  because the *running* version drives the update, this only takes effect once
  you're on 0.3.3 — install 0.3.3 directly (download it from the releases page)
  this one time to escape the loop; in-app updates work normally from there.
- **Update progress bar reflects what's happening.** It shows the real download
  percentage while downloading, then switches to a moving "busy" indicator for
  the quick verify/install steps instead of sitting at a frozen-looking 100%.

## [0.3.2] — 2026-06-26

### Fixed
- **The uninstaller no longer stops at the first problem.** Its steps are
  independent (removing the AppImage doesn't depend on removing the container),
  but a single failing step — most often `distrobox rm` when the container is
  busy — used to cancel everything after it, leaving the AppImage, whipper.conf,
  and shortcuts behind ("uninstall didn't do all"). It's now best-effort: it
  removes everything it can and reports exactly what failed. Your settings + logs
  are still kept if anything failed, so the log survives to debug with — re-run
  the uninstall once the issue is resolved.
- **Missing whipper/metaflac now offer the one-click setup, not a search string
  to paste.** When a tool the app installs itself (whipper, metaflac, flac) is
  missing, the dialog now has a **"Set it up automatically…"** button that opens
  the setup wizard — no terminal, no copying. The copyable search string stays as
  a last-resort fallback. (Previously you got a tier-(c) "copy this and search"
  dialog for tools the app is supposed to install for you.)
- **The setup wizard no longer looks frozen during container preparation.** After
  creating the `ripping` container, the first container entry runs a one-time
  initialization that can take a minute or two; the status line used to sit on the
  previous step's text the whole time, looking stuck. It now shows "checking the
  container…" during that step, and the download/install steps say up front that
  they can take **several minutes** on the first run — so you don't give up partway
  and end up with the rip tool installed in the container but not finished exporting
  to the host (exactly the state the report behind this fix ended in).

## [0.3.1] — 2026-06-26

### Changed
- Maintenance release — **no functional changes since 0.3.0.** Cut so installs
  on 0.3.0+ can exercise the now-fixed in-app updater end-to-end (the KDE
  menu-cache freeze that affected pre-0.2.6 builds is gone — the update flow
  stays responsive through download → verify → install → restart).

### Documentation
- Added the multi-format output (FLAC/WavPack/MP3/WAV) on-hardware validation
  procedure to the test plan as **Test 11**.

## [0.3.0] — 2026-06-26

### Fixed
- **WavPack output now actually works (caught pre-release).** The new WavPack
  transcode passed the wrong ffmpeg output-format name (`-f wavpack`; the muxer
  is `wv`), so real ffmpeg aborted and wrote no `.wv` — the unit tests stub
  ffmpeg, so only a real-binary run exposed it. Fixed to `-f wv` and added a
  real-ffmpeg integration test (skipped when ffmpeg/flac are absent) that proves
  each lossless target decodes back to the FLAC's exact PCM. Same `[Unreleased]`
  cycle as the feature, so no user ever saw it.
- **EAC-parity checker now reads real EAC logs (UTF-16).** EAC writes its
  `.log` as UTF-16-with-BOM; `scripts/eac_parity.py` read it as UTF-8, so every
  character became a replacement char, the parser found zero Copy CRCs, and the
  tool reported a false "NOT parity (0/N)" on a perfectly good rip. Reading is
  now byte-sniffed (`platterpus.parity.decode_log_bytes`: UTF-16 LE/BE BOM,
  UTF-8 BOM, a NUL-heavy heuristic for BOM-less UTF-16, else UTF-8; never
  raises). Found running a real EAC MP3 log through the checker; regression
  tests added (the committed baseline had been converted to UTF-8, which hid it).
- **`--doctor` no longer crashes when the ripper backend is unreachable.** When
  the backend probe failed (e.g. whipper not installed) and no diagnostic host
  was injected — the normal command-line path — the failure-diagnosis code built
  a `HostSetup()` without its required `runner`, raising an uncaught `TypeError`
  that aborted the doctor with a traceback. Ironically this happened exactly when
  the backend wasn't set up, which is the case the doctor exists to diagnose. It
  now constructs `HostSetup(runner=SubprocessRunner())`, so the broken link in
  the host→container→backend chain is named in a clean FAIL report. Regression
  test added (the previously-untested `host=None` production path).
- **Cancel now reliably stops a rip even in the startup window.** If you hit
  Cancel in the brief moment while the rip subprocess was still being spawned,
  the cancel only set a flag — the subprocess wasn't stopped, so the worker
  blocked waiting for the rip to finish on its own (only the 5-second
  force-stop backstop eventually caught it). The worker now re-checks the
  cancel flag the instant it has a process handle and stops it, so Cancel
  takes effect immediately regardless of timing.
- **Launch dependency check now applies its result on the GUI thread.** The
  off-thread launch check connected its `finished` signal to a lambda, which Qt
  delivers as a direct connection — so the result handler (which builds the
  "install this dependency" resolver dialogs) ran on the *worker* thread,
  creating widgets off the GUI thread (a real crash risk; Qt logged
  "QObject::setParent: … in a different thread"). It now connects a bound method,
  which Qt queues to the GUI thread. Found by a headless smoke-run of the real
  startup path.

### Changed
- **Packaging metadata corrected.** `pyproject.toml` now declares
  `Development Status :: 4 - Beta` (was the stale `1 - Planning`, untouched since
  the project was scaffolded — the app has shipped public releases since v0.1.0)
  and adds the `Programming Language :: Python :: 3.13` classifier to match the
  3.11–3.13 CI matrix the package is actually tested on. PyPI display only; no
  code or dependency change.
- **Internal refactor (no behaviour change).** A whole-codebase pass to cut
  redundancy and improve readability, with the test suite green and branch
  coverage held at every step: a shared composition root (`composition.py`) the
  GUI and `--doctor` both build adapters through; a `deps/step_engine.py` module
  for the step-engine types the setup and teardown engines share (the teardown
  engine no longer imports its core types from the setup engine); one
  `workers.start_worker_thread()` helper for the QThread lifecycle wiring that
  eight call sites had each open-coded; and DRY cleanups in `offset_config`
  (one section scanner) and the two ripper backends (one `run_capture`). See
  PLANNING.md KDD-21.

### Added
- **Choose your output format — FLAC, WavPack, MP3, or WAV (new "Output format"
  setting).** Every rip still produces FLAC as the lossless archival **master**;
  when you pick another format the app keeps that FLAC and creates the selected
  format alongside it (a quick background transcode), so you never lose the
  lossless copy. **FLAC** and **WavPack** (`.wv`) are lossless; **MP3** is
  best-quality VBR (`-V0`, ~245 kbps) with tags and embedded cover art; **WAV** is
  raw PCM and can't carry tags or art (the Settings page warns you, and points you
  at WavPack for lossless-with-tags). The transcode runs off the GUI thread, writes
  each file atomically, and never costs you the master if it fails. Uses `ffmpeg`
  (already present wherever the cyanrip backend is), routed through the existing
  dependency subsystem — no new install path. Cover art is embedded in FLAC and
  MP3; WavPack/WAV can't embed it (a tooling limit), so the front cover is always
  saved beside the tracks as `cover.<ext>` for those — every format gets a visible
  cover (see docs/mp3-wav-support.md). New `Config.output_format`.
- **Enforced safety layer (contributor-facing).** New `.githooks/pre-commit`
  hard-blocks committing audio/copyrighted media (Critical Rule #8) — even via
  `git add -f` — so the rule is a guarantee, not just guidance (`dev-setup.sh`
  activates it via `core.hooksPath`; `--no-verify` bypasses for a verified
  CC0/self-generated sample). New committed `.claude/settings.json` adds
  permission `deny` rules for destructive commands (`rm -rf`, force-push) and
  secret reads, plus a session-level audio-staging guard. No end-user-facing
  change.
- **Optional post-rip FLAC re-compression (new "Re-compress FLACs" setting, off
  by default).** whipper encodes FLAC at the tool default (`-5`); turning this on
  re-encodes each output FLAC at maximum effort (`flac -8 -e -p --verify` —
  exhaustive model + coefficient search) after the rip to shrink the files as far
  as flac can. `-e -p` cost a lot of *encode* time for a small extra gain but add
  **no** decode cost (they keep `-l 12`), so they're free in the dimension that
  matters for playback. It's **lossless and verified** — the audio stays
  bit-identical — and `flac` preserves the tags and embedded cover art when it
  re-encodes, so nothing the rip wrote is lost. Each file is swapped in
  atomically, so a failure (or a crash) leaves the original untouched; the step
  is best-effort and runs off the GUI thread (folded into the existing post-rip
  tag/cover thread, so it runs *after* tagging and art). It's skipped for cyanrip,
  which already encodes at maximum compression — the Settings toggle is greyed out
  there with an explanation. **Off by default for a real reason, not just the
  modest size gain:** `-8` uses a higher LPC prediction order (`-l 12`) than
  whipper's `-5` (`-l 8`), which costs a little more CPU/battery to *decode* on
  playback — negligible on modern phones/PCs, but the lighter choice for low-power
  portable players (both levels stay inside the FLAC Subset, so it's a decode-
  effort difference, never a compatibility one). New
  `Config.recompress_flac_after_rip` and a
  `WhipperBackend.produces_max_compression_flac()` capability flag. Shipped flags
  (`-8 -e -p --verify --silent -f -o`) verified current against the xiph spec.
- **Post-rip FLAC integrity verification (new "Verify FLACs" setting, on by
  default).** whipper proves every track decodes back to the read PCM by passing
  `flac --verify` during the rip; cyanrip (FFmpeg) does not, so a cyanrip rip
  lacked that guarantee. After a successful rip the GUI now runs `flac --test` on
  each output FLAC (decode + stored-MD5 check) off the GUI thread, and surfaces a
  loud warning if any file fails. It's skipped for whipper (already self-verified)
  — the Settings toggle is greyed out there with an explanation — and is
  best-effort (a missing `flac` is reported, never fatal). New
  `Config.verify_flac_after_rip`.
- **Richer tags on cyanrip rips (genre, disc number, per-track ISRC).** The
  cyanrip backend was fed only album/artist/title/year/MBID + per-track
  title/artist, so its rips were tagged more sparsely than whipper's. The
  MusicBrainz lookup now also carries the top genre tag, the disc numbering, and
  each recording's ISRC, and these flow to cyanrip's `-a`/`-t` (FFmpeg
  `genre`/`disc`/`isrc`). They are **silent passthroughs** — read from the
  identified MusicBrainz release, not editable in the track table — and
  best-effort (empty when MB has nothing). whipper rips are unaffected (whipper
  tags itself from `--release-id`).
- **Settings + `--doctor` now show the read offset whipper will *actually*
  apply.** Previously the Settings field showed only the GUI's stored copy of
  the read offset; when the whipper backend rips without "Override", the
  authoritative value lives in `whipper.conf` (written by the drive-setup
  wizard or hand-edited) and the two can drift — and a wrong read offset
  silently corrupts every rip. Settings now displays the live `whipper.conf`
  per-drive offset beneath the field, and `--doctor` gained a "Read offset"
  check that reports it (or warns "none set — whipper will refuse to rip"),
  with cyanrip noted as applying the offset directly (`-s`). New never-raises
  `whipper.conf` parser in `offset_config.py`. `--doctor` also now **warns when
  a whipper drive's effective offset is above 587** — the threshold of
  whipper's cd-paranoia bug (KDD-18) — and points to cyanrip, which avoids it
  (advice only; the backend is never silently switched).
- **Preflight / "doctor" check — first-pass test of the rip environment, no CD
  needed.** Run `platterpus --doctor` (or `python scripts/preflight.py`) to
  verify everything the rip pipeline needs *except* the disc read itself: the
  Distrobox→whipper routing actually reaches the backend, the optical drive is
  detected and accessible (a drive lists fine with no disc), the dependency
  tools are present, and the host can reach MusicBrainz / the Cover Art Archive
  / CTDB. Prints a clear pass / warn / blocker report and exits non-zero on a
  hard blocker. When the backend is unreachable it **pinpoints which link is
  broken** (Distrobox not installed / no container backend / the `ripping`
  container missing / the backend not installed-in-container or not exported /
  present-but-misconfigured) instead of a bare "unreachable", so the fix is
  obvious. It knocks out the boring environmental failure modes before you
  insert a disc — a bit-perfect rip still needs a real disc on real hardware.
- **Documentation-currency enforcement (contributor-facing).** `CLAUDE.md` gained
  Critical Rule #7 ("Documentation currency is part of Done") as the always-loaded
  anchor that daisy-chains to the rest; `docs/testing.md §6` Definition of Done
  gained the matching CHANGELOG + session-log/graduation checklist items; and CI
  gained a `changelog` job that fails a push/PR carrying no `CHANGELOG.md` entry
  (opt out with `[skip changelog]` for pure historical-record commits). Keeps the
  project's record from drifting behind the code.
- **App startup smoke test (contributor-facing).** `tests/test_app_smoke.py`
  runs the real `app.main()` entry point headless (offscreen Qt, hermetic — a
  fresh empty config with the subprocess probes + drive listing stubbed) and
  asserts the app composes and comes up (menus + widgets present, clean exit)
  and that the launch dependency check applies its result **on the GUI thread**
  with no cross-thread Qt warnings. This is what would have caught the
  off-thread-apply bug above automatically; nothing previously exercised the
  real entry point.
- **`output_reference/` — EAC parity baselines + checker (contributor-facing).** A
  home for reference rip outputs used to prove bit-perfect parity against Exact
  Audio Copy, laid out as a backend × format matrix (EAC / whipper / cyanrip ×
  FLAC / WAV / MP3). The EAC baseline (extraction **log + cue** for the Police
  test disc) is committed under `EAC_flac/`; the backend dirs are populated
  **only** once a rip's per-track Copy CRCs match EAC's, as proof (priority order
  FLAC → WAV → MP3, tracked in `TASKS.md`). Policy in
  `output_reference/README.md`: comparisons are CRC/log-based and **no commercial
  audio is committed** (public repo + copyright + bloat) — the logs' CRCs prove
  bit-perfection.
- **Parity checker.** `scripts/eac_parity.py` (+ `platterpus.parity` and a
  minimal `parsers/eac_log.py`) auto-detects EAC/whipper/cyanrip log formats and
  diffs per-track Copy CRCs, printing a PASS/FAIL table and exiting non-zero
  unless every track matches — so proving and committing a backend's parity is
  one command. Golden-tested against the committed EAC baseline (14/14 tracks).

## [0.2.8] — 2026-06-18

### Fixed
- **Closing the window during a CTDB verify can no longer crash the app.** The
  opt-in post-rip CTDB verify ran on a `QThread`; if you closed the window while
  it was still looking up / decoding (which can take far longer than the close
  wait), the still-running thread was destroyed and the app aborted. It now runs
  on a daemon thread that reports back via a queued signal and isn't joined on
  close — the same safe pattern as the post-rip tagging and cover-art work.
- **PyPI publishing now actually triggers on a release (CI; contributor-facing).**
  `release.yml` creates the GitHub Release with the default `GITHUB_TOKEN`, and
  GitHub suppresses the events such a token generates — so `publish-pypi.yml`'s
  `release: published` trigger never fired, and v0.2.4–v0.2.7 shipped with no
  PyPI publish attempt. `release.yml` now explicitly dispatches `publish-pypi.yml`
  (a `workflow_dispatch`, the documented exception that always runs) on the
  release tag; the publish runs in its own job so a PyPI problem still can't
  block the AppImage release. (Going live on PyPI still needs the one-time
  Trusted Publisher setup — test-plan Test 7.)

## [0.2.7] — 2026-06-18

### Added
- **CTDB verification after a rip (opt-in, experimental).** A new Settings
  toggle, "Verify with CTDB after a rip", checks a finished rip against the
  CUETools Database — a second, TOC-keyed verification path alongside
  AccurateRip. The result appears as a one-line verdict beneath the
  AccurateRip table. It runs entirely off the GUI thread (the network lookup
  and the local FLAC decode), needs the `flac` decoder for the audio check,
  and is **off by default** (it's a network call). Until the audio-CRC
  algorithm is confirmed bit-exact on real hardware, a match is labelled
  **EXPERIMENTAL** rather than "verified" — the check can only ever
  under-claim (report "no match"), never fabricate a verification.
- **`flac` is now a recognised (optional) dependency.** The dependency check
  (at launch and via Settings → Check dependencies) now lists the `flac`
  decoder used by the CTDB audio check, with guidance to install or export it
  — so enabling CTDB verify without `flac` points somewhere instead of being a
  dead end. It's optional: absent only disables the CTDB audio check.

### Fixed
- **The window no longer freezes while tagging an unknown-album rip.** Writing
  the FLAC tags after a rip (a `metaflac` subprocess per track) used to run on
  the GUI thread, so a multi-track album showed "Not Responding" for tens of
  seconds right when the rip finished. Tagging now runs off the GUI thread,
  sequentially with the post-rip cover-art embed on one background thread (so
  the two never touch the same file at once), keeping the window responsive.

### Changed
- **Test hardening + coverage floor raised to 90% (contributor-facing only;
  no app behaviour change).** Added regression tests for previously-untested
  error/edge paths in the self-update installer (download + install-swap
  failures clean up after themselves), the in-app uninstaller dialog and
  engine (already-running guard, close-while-running teardown, tree-removal
  failures, container-probe failure), and the setup workers (the host-setup
  worker had no tests; drive-setup cancel/partial paths). CI's
  `--cov-fail-under` ratchets 88 → 90.
- **Documentation consolidation (contributor-facing only; no app behaviour
  change).** `docs/` reduced from 15 files to 9 + an `archive/`: `best-practices.md`
  merged into `architecture.md` (one canonical home per engineering pattern);
  `release-testing.md` merged into `test-plan.md` (now "Manual & release
  testing", with the EAC CRC baseline stated once); the research-rerun prompt
  folded into `platterpus-session-start.md` (Step 0); the three dated
  investigation write-ups moved to `docs/archive/` with their durable
  conclusions graduated into KDDs / `DEPENDENCIES.md` / adapter comments.
  `PLANNING.md §3` now points at `DEPENDENCIES.md` instead of duplicating it.

## [0.2.6] — 2026-06-14

### Added
- **Debug logging toggle (Settings).** Off by default; when on, the log file at
  `~/.local/share/platterpus/log.txt` records verbose DEBUG detail (every
  probe, command, and parse step) — turn it on, reproduce a problem, and attach
  the log to a bug report. Applies immediately and on next launch.
- **Launch is fully responsive.** All three startup operations that enter the
  Distrobox container — the dependency check, the drive listing, and reading
  the inserted disc — now run off the GUI thread, so the window appears and
  stays interactive immediately even while a cold container spins up (no more
  "Not Responding" on first launch or when selecting a drive).

### Fixed
- **Disc info from a drive you switched away from no longer overwrites the new
  drive's display.** A late disc-probe result for a previous drive selection is
  now ignored.
- **More GUI-thread freezes removed (proactive, same class as the update
  freeze).** Marking a desktop shortcut trusted (`gio`, GNOME) and the menu
  refresh both ran synchronously inside `integrate()` on the GUI thread; they
  are now fire-and-forget. The launch-time dependency check (which shells out
  to `whipper`, entering the Distrobox container — slow on a cold start) was
  moved to *after* the window is shown, so the window appears immediately
  instead of waiting on a subprocess.
- **In-app update no longer freezes the window ("Not Responding") after the
  download (real-user report).** The post-download menu-cache refresh
  (`kbuildsycoca6`, which can take tens of seconds) was run synchronously on
  the GUI thread, blocking the event loop — so the progress dialog sat frozen
  at 100%, the Cancel button "did nothing", and closing took a long time. The
  refresh is now fire-and-forget, and the updater reports each phase
  ("Verifying…", "Installing — almost done, please don't close…") instead of
  sitting at "Downloading 100%". The Cancel button is retired once the
  un-cancellable install phase begins rather than lingering as a dead button.
- **`uninstall.sh --full` now removes the whole `~/.config/whipper/` directory**
  instead of just `whipper.conf`, so the drive-setup wizard's
  `whipper.conf.bak` backup no longer survives a full uninstall (a real user
  found this leftover after a "fresh" reset). Matches what the in-app
  uninstaller already does.

## [0.2.5] — 2026-06-13

### Added
- **Backend-independent cover art.** When the ripper can't fetch art itself —
  cyanrip rips (the app supplies the tags and bypasses cyanrip's own
  MusicBrainz lookup), and whipper's no-network `--unknown` re-rips — the app
  now fetches the front cover from the Cover Art Archive after the rip and
  embeds it in the FLACs and/or saves it as `cover.jpg`, following the
  existing Cover art setting. The setting is no longer greyed out under
  cyanrip. Art is best-effort: a missing cover never affects the rip.

## [0.2.4] — 2026-06-12

### Changed
- **Releases can be cut by dispatching the Release workflow** (Actions → 
  Release → Run workflow → enter the tag). The workflow creates the tag
  itself, pinned to the built commit — no local tag push needed.

### Fixed
- **The menu offer now fires for an update saved over the old file's path
  (real-user report).** Downloading a new version onto the exact path an
  existing menu entry pointed at made the app think it was fully installed
  — no prompt, no move to `~/Applications`, no desktop icon, and deleting
  the Downloads file then broke the launcher ("Could not find the
  program…"). Integration is now offered whenever the running file isn't
  settled in `~/Applications`, even if a menu entry already matches it.

## [0.2.3] — 2026-06-10

### Added
- **True in-app updates (real-user request).** "Check for updates" no longer
  sends you to a download page: when a newer release exists, the app
  downloads it in the background (progress bar, cancellable), **verifies it
  against the release's published `.sha256`**, installs it atomically over
  `~/Applications/platterpus-x86_64.AppImage`, repoints the menu entries,
  and offers to **restart itself into the new version** (the old session
  closes). A failed or cancelled download changes nothing. Source/pipx
  installs still get the release page (their files can't be swapped).

### Fixed
- **Updates re-offer their menu shortcuts (real-user report).** The
  "add to menu?" offer was suppressed forever after being answered once, so
  a freshly downloaded new version never asked to remake its shortcuts and
  the old menu entry kept launching the old file. Declining is now
  remembered **per file**: any not-yet-integrated AppImage (an update, or
  one whose shortcuts you deleted) gets the offer again.

## [0.2.2] — 2026-06-10

### Added
- **The AppImage installs itself to `~/Applications` (real-user feedback,
  2026-06-10).** Accepting "Add to your applications menu?" (or Tools → Add
  app shortcut) now also MOVES the AppImage out of Downloads into
  `~/Applications` — the standard home AppImageLauncher uses — and points
  the menu/desktop entries there, so clearing your Downloads folder can no
  longer delete the installed app. The running session keeps working after
  the move; future launches come from the menu. If the move fails the app
  integrates where it is (never raises, never loses the file). The
  uninstaller now also removes the `~/Applications` copy even when launched
  from somewhere else.
- **"Rescan disc" button** next to Refresh/Eject (real-user request,
  2026-06-10). Re-runs the disc scan + MusicBrainz lookup for the selected
  drive — the retry for transient scan failures and for discs inserted
  after launch. (Refresh only reloads the drive *list* and keeps the
  selection, so it never re-triggered the scan; previously the only retry
  was restarting the app.)

### Changed
- **Plain-language message for the disc-scan flake.** whipper's known
  cdrdao read-toc failure ("FileNotFoundError: …cdrdao.read-toc.whipper.task",
  typically the disc still spinning up) now reads "The drive couldn't read
  the disc's table of contents — … Click 'Rescan disc' to try again"
  instead of a raw traceback line. Unrecognized errors still pass through
  verbatim.

## [0.2.1] — 2026-06-10

### Fixed
- **v0.2.0's release build uploaded no files.** Two packaging bugs: the
  build script looked for python-appimage's cached `appimagetool` with a
  glob that skipped its dot-prefixed cache directory, so the zsync
  update-information embed was silently skipped; the release upload then
  failed on the missing `.zsync` and aborted before attaching anything.
  The glob now matches the dot-form, and a dedicated "Verify update
  artifacts" workflow step fails early with a clear message if the
  `.zsync` is ever missing again. *(v0.2.0 was superseded without
  artifacts; v0.2.1 is identical plus this fix.)*

## [0.2.0] — 2026-06-09

### Added
- **AppImage self-update (the last zero-CLI slice, KDD-17b).** The AppImage
  now embeds standard zsync update-information
  (`gh-releases-zsync|…|platterpus-x86_64.AppImage.zsync`) and releases ship
  the `.zsync` file, so any AppImageUpdate-compatible tool can fetch only the
  changed blocks and verify them. In-app: **Help → Check for updates…** asks
  GitHub (off-thread) whether a newer release exists; if so it hands off to
  `appimageupdatetool`/`AppImageUpdate` when installed, or opens the release
  page — the app never downloads update payloads itself. The `.sha256`
  checksum is generated after the update info is embedded, so it always
  covers the shipped file.
- **`setup-host.sh --cyanrip`.** The CLI bootstrap now mirrors the GUI
  wizard's cyanrip step: enables the GPG-checked COPR inside the container
  only, installs cyanrip, and exports it to `~/.local/bin/cyanrip`.
- **"Uninstall Platterpus" menu entry + `--uninstall` mode.** AppImage
  self-integration now also installs an uninstaller launcher in the
  application menu (under System, not next to the app in Multimedia) that
  opens just the uninstaller via the new `platterpus --uninstall` flag — so
  removal needs neither a terminal nor the main app. Verified all our
  `.desktop` entries already file the app itself under Multimedia
  (`Categories=AudioVideo;Audio;`).
- **In-app Uninstaller (Tools → Uninstall Platterpus…).** Removes everything
  the app installed — menu/desktop shortcuts, host-exported
  whipper/metaflac/cyanrip, the `ripping` container, optionally `whipper.conf`
  and the AppImage file itself, and finally the app's own settings + logs —
  with live per-step progress, a confirmation gate, and per-piece checkboxes.
  **Never touched: your music, and Distrobox/podman themselves.** Settings +
  logs are removed last so a failed step still leaves the log to debug with;
  on success the app offers to close itself. `uninstall.sh` now also removes
  the host-exported cyanrip wrapper (parity).
- **Fidelity verdict + AccurateRip table for cyanrip rips (KDD-18).** New
  `parsers/cyanrip_log.py` parses cyanrip's rip log (EAC CRC32 per track,
  AccurateRip v1/v2 + confidence, preemphasis, drive/offset, ripping-error
  count) into the shared `RipLog`, with format auto-detection — a folder can
  hold logs from either ripper. The post-rip summary is worded around what
  cyanrip actually checks ("all N tracks ripped cleanly, no read errors" +
  "AccurateRip: N/M") instead of claiming whipper's Test/Copy CRC pass, and
  the per-track AccurateRip results table now fills in on both backends.
- **Live progress bars during cyanrip rips (KDD-18).** The rip worker now
  parses cyanrip's `\r`-redrawn progress lines ("Ripping track N, progress -
  X%, ETA - …"), so the overall + task bars move, the current track row is
  highlighted, and the status line shows percentage + ETA — same behaviour as
  whipper rips. Per-track completion lines peg that track's slice of the
  overall bar.
- **cyanrip rips are now driven entirely by the GUI's metadata (KDD-18).**
  The rip snapshots the track table (the MusicBrainz release you picked plus
  any edits) and feeds it to cyanrip via `-a`/`-t`, with MusicBrainz always
  disabled (`-N`): no wrong-release risk, no in-container network needed,
  values with `:`/`=`/`'` safely escaped, and the release MBID recorded as a
  tag. The folder/file naming templates now apply to cyanrip too — whipper
  `%A/%d/%t/%n/%y/%N/%a` tokens are translated to cyanrip's `-D`/`-F`
  `{…}` schemes, so both backends produce the same library layout.
- **One unified Settings page across backends.** Options the selected
  backend doesn't support (under cyanrip: CD-R switch, cover art, overread,
  keep-going, the whipper path) grey out instead of disappearing, with a
  tooltip explaining why and that switching the Ripping backend back to
  whipper re-enables them. Greyed-out values are kept, never cleared.
- **cyanrip backend now identifies discs (KDD-18).** `CyanripImpl.disc_info`
  runs `cyanrip -I -N` (info-only, offline — cyanrip computes the
  MusicBrainz DiscID and CDDB ID locally from the TOC) and the new
  `parsers/cyanrip_info.py` parses the report into the backend-neutral
  `DiscInfo` (IDs, track count, MB submission URL), so the disc panel and
  the GUI's host-side MusicBrainz lookup work identically on both backends.
  Includes a property-based "never raises" test per the testing rules.
- **Host-setup wizard can install the cyanrip backend (KDD-18).** When
  Settings → Ripping backend is set to cyanrip, the setup wizard (and the
  Tools → Set up Platterpus… flow) gains a step that installs cyanrip into
  the `ripping` container and host-exports it to `~/.local/bin/cyanrip`.
  Research finding (2026-06-09): Fedora does **not** package cyanrip (nor
  does RPM Fusion); the install uses the GPG-checked COPR
  `barsnick/non-fed` (cyanrip 0.9.3.1 built for Fedora 42–44 + rawhide) via
  a version-generic `.repo` file — no `dnf copr` plugin needed. Switching
  the backend in Settings now offers to run the wizard if cyanrip is
  missing, and the app prefers the host-exported absolute path when
  constructing the cyanrip backend (desktop launches have a minimal PATH).
- **Institutionalized testing strategy + stronger test infrastructure.** New
  [`docs/testing.md`](docs/testing.md) codifies the approach (testing trophy +
  an explicit real-hardware gate, a five-tier case taxonomy, property/golden/
  fault-injection/mutation guidance, the non-negotiable rules, and a Definition
  of Done). Concretely: **property-based tests** (`hypothesis`) lock in the
  "parsers never raise on arbitrary input" invariant
  (`tests/test_parsers_property.py`); CI now runs **branch coverage with a hard
  `--cov-fail-under=88` gate** (baseline ~91%, ratchets up) across a **Python
  3.11–3.13 matrix**; `pytest-cov` + `hypothesis` added to the `dev` extra and
  `mutmut` documented as a periodic audit. Suite is now 534 tests.
- **Ruff linter + formatter.** Adopted `ruff` (config in `pyproject.toml`:
  rules `E,F,W,I,B,UP`, `E501` off; `ruff>=0.15` in the `dev` extra) with a
  parallel `lint` job in CI running `ruff check` + `ruff format --check`. Fixed
  all findings and raised coverage; the suite is now 525 tests.
- **CTDB verify (Phase 1 — library + validation script).** Clean-room (KDD-16)
  CUETools Database lookup client (`adapters/ctdb_client.py`) and verify logic
  (`platterpus/ctdb/`), plus a standalone `scripts/ctdb_verify.py` to validate
  on real hardware. The `toc=` wire format and the audio CRC are
  hardware-validation-gated (both fail safe — never a false "verified"); the
  GUI wiring is deferred until they're confirmed. See `docs/test-plan.md`
  Test 1. PCM decode uses the host `flac` if present (optional dependency).
- **Manual / hardware test plan** (`docs/test-plan.md`) — a step-by-step
  checklist for everything that can't be validated in CI (CTDB verify/repair,
  `drive analyze`/`offset find` success strings, GUI screenshot, Picard UX,
  PyPI go-live).
- **Automated PyPI publishing.** A new `.github/workflows/publish-pypi.yml`
  builds the wheel + sdist and publishes them to PyPI when a release is
  published (i.e. on every `v*` tag, alongside the AppImage). Uses PyPI
  Trusted Publishing (OIDC) — no stored token. One-time PyPI-side setup is
  documented in the workflow header. It's a separate workflow from
  `release.yml`, so a PyPI misconfiguration can't block the AppImage release.

### Changed
- **README leads with a no-terminal install.** A new "Easiest — download one
  file, no terminal" section: download the AppImage, do the one-time "allow
  executing" step (GUI instructions for KDE/GNOME), double-click, and answer the
  first-run prompts (menu integration + the host-setup wizard). The scripted/
  CLI paths remain below for testers and developers; Method A notes that
  `install-appimage.sh` is no longer required (self-integration replaces it).

### Changed
- **Clear, actionable message when a track can't be read.** When whipper gives up
  on a track after its retries (scratched/dirty disc, or the cd-paranoia
  >587-offset upstream bug), the status now says which track failed and what to
  do — clean the disc, or turn on "Keep going" in Settings to rip the readable
  tracks — instead of a bare "Rip failed".

### Added
- **Settings → Ripping backend toggle (cyanrip, Phase 2 start).** You can now
  pick the backend (whipper | cyanrip) in Settings; it's wired to
  `Config.ripper_backend` and applied on next launch. cyanrip is marked
  experimental and still needs to be installed in the container (provisioning is
  the next phase). Completes the user-facing half of making cyanrip selectable.
- **cyanrip backend — Phase 1 (KDD-18).** A second ripping backend
  (`adapters/cyanrip_backend.py`, `CyanripImpl`) behind the existing
  `WhipperBackend` ABC, selectable via `Config.ripper_backend = "cyanrip"`
  (app.py picks the backend; default stays whipper). cyanrip is the actively
  maintained successor and — critically — applies the read offset with its own
  paranoia (`-s`), avoiding whipper's cd-paranoia bug at offsets > 587 that
  fails tracks on the Pioneer BDR-209D (+667). Phase 1 ships the tested core:
  the rip argv builder (`-d/-s/-o flac/-r/-N/-G`), `version`, `find_offset`
  (`-f`), and a backend-independent `/dev`+sysfs drive scan; disc-info parsing
  and naming-template mapping are tracked as the remaining phases in
  `docs/archive/ecosystem-audit-2026-06.md`. Not yet user-selectable in the GUI.
- **Autonomous heal when the ripper can't reach MusicBrainz.** whipper inside the
  container aborts (`unable to retrieve disc metadata, --unknown argument not
  passed`) when it has no network — even for a known disc, because it fetches the
  release online. The GUI already has the metadata from its own host-side lookup,
  so on that specific failure it now **automatically re-rips as an unknown-album
  rip** (`--unknown`, no release-id → no network needed) and tags the FLACs
  locally from the on-screen track list. One retry per Start; surfaced in the
  status line. The `RipWorker` watches whipper's output for the marker.

### Changed
- **Ripping no longer demands the wizard when the drive's offset is already
  known.** If you hit Start without a saved offset but your drive is in the
  bundled AccurateRip list, the GUI now **applies that offset automatically**
  (your Pioneer → +667), tells you once where it came from, and lets the rip
  proceed — instead of blocking and sending you to the drive-setup wizard. Only
  a genuinely unknown drive still needs the wizard. (The manual/wizard-saved
  offset path is unchanged: set it once, then you're good.)
- **Host-setup wizard: live progress + honest end states (no more "frozen / done
  too soon").** The bootstrap engine now emits a **"⏳ currently doing X…"**
  status *before* each step runs — so during a multi-minute image pull or
  in-container `dnf install` the wizard shows what's happening instead of a
  static bar that looks hung. Slow steps say "this can take a few minutes". The
  finish message now distinguishes **"Everything was already set up — you're
  ready to rip"** (the common Bazzite case, which previously flashed by and
  looked like nothing happened) from a setup that actually installed things, and
  surfaces the failed step otherwise.

### Added
- **App shortcut: Desktop icon + a re-runnable menu action.** Self-integration
  now also drops a clickable icon in your **Desktop folder** (not just the
  applications menu), and there's a **Tools → Add app shortcut** action so you
  can (re)create the menu + desktop shortcut any time — the first-run offer was
  one-shot, so a dismissed prompt previously left no way to redo it. GNOME
  desktop icons are marked trusted (best-effort) so they launch on double-click.
- **AppImage self-integration on first run — no terminal (KDD-17, step 2).** The
  first time the AppImage runs, it offers to add Platterpus to your
  applications menu (writes a `.desktop` entry pointing at the AppImage, drops
  the icon, refreshes the menu caches) and makes the AppImage executable — so
  after the first double-click it launches from the menu like any installed
  app. Supersedes the manual `install-appimage.sh` for the common case; no-op
  on source/pipx installs. New `appimage_integration.py`; one-time/dismissible
  (`Config.appimage_integration_prompted`).
- **First-run host setup from the GUI — no terminal (KDD-17, step 1).** A new
  **Tools → Set up Platterpus…** wizard (also offered automatically on first
  launch when whipper isn't installed yet) does what `setup-host.sh` did by
  hand: installs Distrobox + a container backend, creates the `ripping`
  container, installs whipper into it, and exports it to the host — with live
  per-step progress and idempotent re-runs. System-package installs use a
  graphical **polkit** prompt (`pkexec`) instead of `sudo`, so no terminal is
  needed; on Bazzite/Silverblue the runtime is preinstalled, so those steps are
  skipped and nothing is prompted. Engine: `deps/host_setup.py` (injectable
  runner, dry-run, fully unit-tested); UI: `ui/host_setup_dialog.py` +
  `workers/host_setup_worker.py`.
- **Read offset is now looked up by drive model (full AccurateRip list, bundled).**
  whipper's `offset find` is unreliable (it failed on a Pioneer BDR-209D even with
  a disc that's in AccurateRip). The drive-setup wizard now resolves the offset the
  way EAC/dBpoweramp do — by the drive's vendor+model — and pre-fills it for
  one-click save, **with no disc and no whipper probe**. The **entire AccurateRip
  drive-offset list (~4,800 drives)** is imported and bundled in-code
  (`adapters/accuraterip_offsets_data.py`, a ~21 KB gzip blob), so it works offline
  for any drive — refreshable via `scripts/update_drive_offsets.py` (which validates
  the parse against the known BDR-209D = +667 before writing). Layered: user CSV
  (`~/.config/platterpus/drive_offsets.csv`) > curated overrides > bundled list.
  whipper's `offset find` is kept as optional verification. New
  `adapters/accuraterip_offsets.py` (`OffsetDatabase`). See
  `docs/archive/offset-investigation-2026-06.md`.

### Fixed
- **Saving Settings no longer resets the one-time first-run flags.** `to_config`
  rebuilt `Config` from scratch and dropped `drive_setup_prompted` /
  `host_setup_prompted` / `appimage_integration_prompted`, so after saving
  Settings the first-run offers could re-appear on the next launch. Preserved now.
- **Ripping without a configured read offset now stops with a clear popup**
  instead of failing cryptically inside whipper. If no offset is set (neither
  whipper.conf nor the GUI's `--offset` override), Start shows a warning that
  explains an accurate offset is required and offers to open the drive-setup
  wizard — which fills the offset in automatically when the drive model is
  known, or detects it from a CD that's in the AccurateRip database.
- **The app no longer vanishes silently on a startup error.** Drive listing
  (and the rest of startup) ran after the window was shown but outside any
  guard, so an unexpected error — e.g. the drive-list parser choking on
  unhandled whipper output — let the window appear and then immediately
  disappear with nothing logged on screen. Startup is now wrapped: any
  unexpected error (including ones raised inside a Qt slot during the event
  loop, via a `sys.excepthook`) is logged **and shown in a dialog** with the
  log-file path, instead of aborting the process. `DrivePicker.refresh()` also
  now degrades any non-`WhipperError` to an "(error: …)" placeholder so a
  drive-listing hiccup leaves a usable window.
- **Drive-setup wizard:** the manual read-offset spinbox (and its up/down
  arrows) and the **Save offset** button are now locked while detection is
  running, so a value can't be edited/saved mid-detection and race what whipper
  writes. They re-enable when detection finishes.

### Changed
- **Documentation audit (2026-06-09).** PLANNING.md caught up with the code
  (directory tree + per-module list now include the host-setup wizard,
  AppImage self-integration, AccurateRip offset lookup, and the cyanrip
  backend/parser; the pre-implementation "future CyanripImpl" sketch replaced
  with the as-built design). TASKS.md gained a **Current plan & priorities**
  section — the live, ordered queue with difficulty estimates — and the
  zero-CLI checkboxes were corrected to match what shipped. README gained a
  "Ripping backends" section; the in-app User Guide documents the backend
  toggle; the hardware test plan gained Test 8 (cyanrip install + parity run).

## [0.1.0] — 2026-06-01

### Added
- **One-command installer (`install.sh`).** A single downloadable file (also a
  release asset) that takes a machine from nothing to a launchable app: sets up
  the host stack (Distrobox + `ripping` container + whipper, via
  `setup-host.sh --no-gui`), downloads the published AppImage, and adds the
  desktop shortcut **plus an "Uninstall Platterpus" shortcut**. Flags:
  `--yes`, `--dry-run`, `--no-host`, `--appimage PATH`, `--build`. The
  uninstall shortcut runs the comprehensive `uninstall.sh` (interactive, with
  options); `uninstall.sh` now also removes the AppImage, its icon, and the
  shortcuts, so it cleanly handles both the source and AppImage installs.
- **AppImage built on every push to `main`** (`.github/workflows/appimage.yml`),
  not just at release time, so a broken build recipe is caught immediately. It
  also runs on demand (`workflow_dispatch`) on any branch, uploading a
  downloadable AppImage artifact for testing branches that have no release yet.
  See `docs/appimage-testing.md`.
- **Help menu.** A new **Help → About** dialog shows the version number plus
  support-relevant info (Python/Qt/PySide6 versions, config/log/whipper paths,
  project & issue links), and **Help → User Guide** opens a built-in,
  task-oriented guide (`platterpus/help_content.py`).
- **Force-stop for a runaway drive.** Cancelling a rip kills the host-side
  process, but the reader runs inside the `ripping` container and podman
  doesn't forward the signal, so the drive could keep spinning for minutes with
  no way to stop it. Cancel now auto-escalates after a short countdown (and
  there's a manual **Force stop** button): it kills the **whipper orchestrator**
  (which otherwise just respawns the reader), `fuser -k`'s the device, and
  ejects — a deliberate, user-approved exception to the "never call into the
  container" rule, scoped to this case only. Validated on real hardware: Cancel
  now stops the drive within a few seconds.
- **Desktop integration for the AppImage** (`install-appimage.sh`, shipped as
  a release asset): adds an app-menu entry + Desktop icon for a downloaded
  AppImage (which otherwise installs no shortcut), with `--uninstall`.
- **First-run read-offset onboarding.** whipper refuses to rip until a read
  offset is configured; a fresh user (especially one with only CD-Rs, who
  can't run AccurateRip auto-detection) would otherwise hit a cryptic error.
  On first launch, if no offset is set (neither in `whipper.conf` nor as the
  GUI's `--offset` override), the GUI now offers the drive-setup wizard once —
  dismissible, and never re-nagged (afterwards it lives on Tools → Set up
  drive…). The wizard gains a **manual-entry fallback**: when auto-detection
  can't run, enter your drive's published offset by hand (linked to
  AccurateRip's list); it's applied via `--offset`, so `whipper.conf` is never
  hand-authored (KDD-15).

### Fixed
- **CI on `main` was red.** Since the T32 change that auto-creates the output +
  working directories before a rip, the whipper-backend argv tests created
  `/music`, which fails as non-root on the CI runner (it only passed in a
  root dev container). The argv-only tests no longer touch the filesystem; the
  one test that asserts directory creation uses a writable temp path.

## [0.0.1] — 2026-05-31

**First public test release.** A Linux GUI front-end for the `whipper` CD-ripping
CLI, aiming for EAC-equivalent archival quality. Validated on real Bazzite
hardware: a full 16-track rip *through the published AppImage*, with every
track's Test CRC matching its Copy CRC and "no errors occurred".

### What works

- **End-to-end FLAC ripping** through the host-exported `~/.local/bin/whipper`
  (Distrobox routing), with per-track AccurateRip confidence and Test/Copy CRC
  verification reported in the UI.
- **MusicBrainz disc identification** via a dedicated adapter — whipper's
  interactive TTY prompt never surfaces; a release picker handles multiple
  matches, and unknown discs fall back to editable `Track NN` placeholder rows.
- **Drive setup wizard** (Tools → Set up drive…) runs whipper's own
  `drive analyze` + `offset find` and writes `whipper.conf` for you — no more
  hand-editing read offsets.
- **Drive-access diagnostics** (Tools → Diagnose drive access…) classify the
  "no drive" case and hand you the exact `usermod` fix when it's a permissions
  problem.
- **EAC parity Settings:** cover art (fetch/embed/save), force-overread,
  max-retries, keep-going, CD-R support, and a manual read-offset override.
- **Progress + fidelity UX:** an overall progress bar plus a current-task bar,
  an animated pre-track disc scan, and an end-of-rip fidelity verdict.
- **Single-file AppImage** bundling Python + Qt + dependencies (the GUI side
  needs nothing else installed), plus a `pipx`/source path for developers.

### Install & uninstall

- **`setup-host.sh`** — one command bootstraps the entire host stack (Distrobox
  → `ripping` container → whipper + flac → host export), idempotent, with
  `--dry-run` / `--yes` / `--no-gui`.
- **`uninstall.sh`** — layered, safest-first teardown; never removes ripped
  music or the repo without an explicit flag and a typed confirmation.
- `dev-setup.sh` installs a KDE app-menu entry and a desktop launcher; both are
  cleaned up by `uninstall.sh`.

### Known limitations

- The **host stack is required** — the AppImage cannot rip on its own (this is
  intentional; whipper runs inside Distrobox).
- **FLAC only** in v1 (MP3/WAV are backlog). FLAC compression level is fixed at
  whipper's upstream default (`-5`); see the README for a post-rip re-encode
  recipe if you want `-8`.
- `setup-host.sh` is verified by `--dry-run` and smoke tests; the full
  hardware-bootstrap path has had limited real-world runs.
- Linux x86-64 only.

[Unreleased]: https://github.com/rmccann-hub/Platterpus/compare/v0.4.4...HEAD
[0.4.4]: https://github.com/rmccann-hub/Platterpus/compare/v0.4.2...v0.4.4
[0.4.2]: https://github.com/rmccann-hub/Platterpus/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/rmccann-hub/Platterpus/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.10...v0.4.0
[0.3.10]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.9...v0.3.10
[0.3.9]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.8...v0.3.9
[0.3.8]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.7...v0.3.8
[0.3.7]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.6...v0.3.7
[0.3.6]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.5...v0.3.6
[0.3.5]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/rmccann-hub/Platterpus/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.8...v0.3.0
[0.2.8]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/rmccann-hub/Platterpus/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rmccann-hub/Platterpus/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rmccann-hub/Platterpus/releases/tag/v0.1.0
[0.0.1]: https://github.com/rmccann-hub/Platterpus/releases/tag/v0.0.1
