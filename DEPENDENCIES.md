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
| build | `>=1,<2` | (per PyPI at first install) | MIT | Active | — (PEP 517 build frontend; used by `build/build_appimage.sh`) |
| pytest | `>=8,<9` | (per PyPI at first install) | MIT | Active | — |
| Pillow | (unpinned; per PyPI) | Active | HPND (PIL license) | Active | — **Optional, not required for normal builds.** Only `build/make_icon.py` uses it, to regenerate the committed app icon (`build/python-appimage/whipper-gui.png`). The icon is committed, so a normal AppImage build needs no image tooling. |

## System dependencies (user-system, surfaced via the dependency subsystem)

| Name | Where it comes from | Version constraint | Status | Replacement plan |
|---|---|---|---|---|
| whipper | Distrobox container `ripping`, host-exported to `~/.local/bin/whipper` | `>=0.10.0` | Unmaintained (>12mo) — see retirement review log | `cyanrip` via `WhipperBackend.CyanripImpl` (ABC contract documented in PLANNING.md §5) |
| metaflac | Distrobox container `ripping` (same export route) | (whatever ships with the container's `flac` package) | Active (FLAC project) | — |
| libdiscid | (not installed) | n/a | **Not needed on host** — whipper-in-container computes the disc ID; the GUI never calls libdiscid (KDD-06, confirmed T32 2026-05-29) | — |
| MusicBrainz Picard | Flathub via `.flatpakref` URL (see install_command in `deps/registry.py`) | latest | Active | — |

## System dependencies (build/runtime requirements inside the Distrobox container)

These aren't installed by our GUI but ARE required for whipper to work. They live inside the `ripping` Distrobox container alongside whipper itself. Documented here because real-user testing on Bazzite (2026-05-28) surfaced missing-dep issues that aren't obvious from the README.

| Name | Why it's needed | How to install (inside the container) |
|---|---|---|
| `python3-setuptools` | Whipper 0.10.0 imports `pkg_resources` from setuptools. Python 3.14 (shipped in Fedora 44) doesn't include setuptools by default, and Fedora's whipper RPM doesn't declare it as a dep. Without it, `whipper --version` raises `ModuleNotFoundError: No module named 'pkg_resources'`. | `sudo dnf install python3-setuptools` |
| `cdrdao` | Required by whipper for gap detection. Usually pulled in by `dnf install whipper` as a transitive dep, but worth noting in case of minimal container bases. | `sudo dnf install cdrdao` |

### Notes on the unmaintained items

**whipper (0.10.0, 2021-05-17)** — Last release on PyPI/GitHub. Still works in 2026 on Fedora 44 + Python 3.14 IF `python3-setuptools` is installed alongside it (the pkg_resources import is otherwise broken). Community-recognized active successor is `cyanrip`. Our `WhipperBackend` adapter (PLANNING.md §5) lets a swap happen without touching the GUI layer. CLAUDE.md Critical Rule #1 codifies this.

Whipper-on-newer-Python surfaces a `pkg_resources is deprecated` UserWarning on every invocation; this is cosmetic (the version number still prints) but signals that the clock is running. setuptools 81 is slated to remove `pkg_resources` entirely, at which point whipper will stop running until either upstream is patched or we migrate to `cyanrip`.

**musicbrainzngs (0.7.1, 2020-01-11)** — Last PyPI release. The underlying MusicBrainz `ws/2` REST API is stable. Risk is library bitrot (e.g., dropped Python compatibility on a future interpreter, not a server-side break). Our `MusicBrainzClient` adapter (PLANNING.md §6) lets us replace with raw `requests` against the JSON endpoint. CLAUDE.md Critical Rule #1.

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

- **2026-06-02 — Pre-release review for v0.1.0 (first public release).** Walked the table per the "before every tagged release" cadence. No dependency changes since the last review. PySide6 (6.11.1), tomli-w, python-appimage all current. whipper + musicbrainzngs remain unmaintained but functional; adapters still isolate them; replacement plans (`cyanrip`, `requests`-based MB client) unchanged. Separately confirmed during the EAC-parity investigation (see `docs/upstream-modification-investigation.md`) that the path off whipper, if forced, is the `cyanrip` adapter — **not** a maintained whipper fork. No action taken.
- **2026-05-28 — Real-user testing on Bazzite surfaced whipper deprecation canaries.** Whipper 0.10.0 is now 5 years old and showing real friction on current distros:
  - **`pkg_resources` removal countdown.** Whipper imports `pkg_resources` from setuptools, which prints a deprecation warning under setuptools 80.x. Setuptools 81 (already released as of the warning's "2025-11-30" cutoff) will remove `pkg_resources` entirely. When Fedora ships setuptools 81+, whipper will stop running. Worth a `cyanrip` migration plan but not an emergency yet — Fedora 44 still has setuptools 80.x.
  - **`whipper cd info` is broken for discs not in MB/FreeDB.** The `_CD.do()` method requires `--unknown` to be set when no metadata is found, but the `Info` subcommand doesn't accept `--unknown` (only `Rip` does). Adapter caught this with a fallback that returns an empty DiscInfo, but it's an upstream bug. Real fix would require patching whipper.
  - **Decision:** continue with whipper for v1; flag both issues in code comments on `WhipperHostExportedImpl`. The adapter pattern (Critical Rule #1) makes the `cyanrip` migration tractable when it becomes necessary.
