# Dependencies

All dependencies, with last upstream release date and replacement plan. Reviewed on the cadence below.

## Python packages (bundled in the AppImage)

| Name | Pinned version | Last upstream release | License | Status | Planned replacement |
|---|---|---|---|---|---|
| PySide6 | `>=6.7,<7` (current: 6.11.1) | 2026-05-13 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Active | — |
| musicbrainzngs | `==0.7.1` | 2020-01-11 | BSD-2-Clause (one file ISC) | Unmaintained (>12mo) | direct `requests` against `https://musicbrainz.org/ws/2/` via `MusicBrainzClient.RequestsJsonImpl` |
| tomli-w | `>=1.0,<2` (current: 1.2.0) | 2025-01-15 | MIT | Active | — (stdlib `tomllib` is read-only, `tomli-w` is the canonical writer) |

## Python packages (dev / build only — not bundled)

| Name | Pinned version | Last upstream release | License | Status | Planned replacement |
|---|---|---|---|---|---|
| python-appimage | `>=1.4,<2` (current: 1.4.5) | 2025-07-02 | GPL-3.0 (package itself); MIT for files under `python_appimage/data` | Active | `appimage-builder` only if `python-appimage` cannot express a required build step (CLAUDE.md Critical Rule #2). The recipe must avoid `appimage-builder`-specific features so swapping back is cheap. |
| pytest | `>=8,<9` | (per PyPI at first install) | MIT | Active | — |

## System dependencies (user-system, surfaced via the dependency subsystem)

| Name | Where it comes from | Version constraint | Status | Replacement plan |
|---|---|---|---|---|
| whipper | Distrobox container `ripping`, host-exported to `~/.local/bin/whipper` | `>=0.10.0` | Unmaintained (>12mo) | `cyanrip` via `WhipperBackend.CyanripImpl` (ABC contract documented in PLANNING.md §5) |
| metaflac | Distrobox container `ripping` (same export route) | (whatever ships with the container's `flac` package) | Active (FLAC project) | — |
| libdiscid | System library; on Bazzite via `rpm-ostree install libdiscid` + reboot | `>=0.6` (if needed at all — see PLANNING.md KDD-06) | Active | — |
| MusicBrainz Picard | Flathub: `flatpak install --user flathub org.musicbrainz.Picard` | latest | Active | — |

### Notes on the unmaintained items

**whipper (0.10.0, 2021-05-17)** — Last release on PyPI/GitHub. Still works on Bazzite's Distrobox-hosted Fedora 40 container per the project brief's confirmed setup. Community-recognized active successor is `cyanrip`. Our `WhipperBackend` adapter (PLANNING.md §5) lets a swap happen without touching the GUI layer. Brief Critical Rule #1 codifies this.

**musicbrainzngs (0.7.1, 2020-01-11)** — Last PyPI release. The underlying MusicBrainz `ws/2` REST API is stable. Risk is library bitrot (e.g., dropped Python compatibility on a future interpreter, not a server-side break). Our `MusicBrainzClient` adapter (PLANNING.md §6) lets us replace with raw `requests` against the JSON endpoint. Brief Critical Rule #1.

**appimage-builder (Snyk-flagged inactive)** — Not used. Listed here so it's tracked: CLAUDE.md Critical Rule #2 forbids reaching for it without explicit user approval. `python-appimage` (above) is the active builder.

## Review cadence

- Before every tagged release
- After every meaningful dependency bump
- At least quarterly even when nothing changes (so retirement signals don't pile up unseen)

## Retirement trigger

Any row whose "Last upstream release" exceeds 12 months requires a review of:

1. The adapter wrapping that dependency (does it still isolate the GUI from the dep?)
2. The "Planned replacement" column (is it still the right replacement?)
3. Whether to act on the retirement now or wait

A retirement review is recorded inline below as a dated bullet so future-you can see what was decided and when.

## Retirement review log

*(empty — first review will be at v0.1.0 tag)*
