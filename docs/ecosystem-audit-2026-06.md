# Ecosystem audit & backend-successor plan (2026-06)

**Why this exists.** Real-hardware testing on a Pioneer BDR-209D hit whipper's
offset-find failing ("could not detect the read offset", slow), which prompted
the question: *is whipper the right foundation long-term, and should we fork,
contribute, or integrate something else?* This is the researched answer, with
dated facts and a recommendation. It complements
[upstream-modification-investigation.md](upstream-modification-investigation.md)
(which covers EAC-parity feature gaps) and PLANNING.md **KDD-18**.

---

## Findings (verified June 2026)

### whipper — our current backend — is effectively stalled
- **Last release: v0.10.0, 2021-05-17 — ~5 years ago.** No tagged release since
  ([releases](https://github.com/whipper-team/whipper/releases)). whipper is
  itself a continuation of `morituri` (which had stopped); whipper now shows the
  same pattern.
- **Python cliff.** whipper imports `pkg_resources`. `pkg_resources` is removed
  from `setuptools` ≥81 and absent in Python 3.14; we already work around this
  by installing `python3-setuptools` in the `ripping` container, and Fedora
  still ships a `pkg_resources`-providing setuptools — **but that is borrowed
  time**, not a fix. If/when the container's distro drops it, whipper breaks.
- **`offset find` is weak** — whipper's own docs call its detection "primitive";
  confirmed on real hardware (it failed on a disc that *is* in AccurateRip and
  took a long time). Our manual-offset fallback exists precisely for this.
- **Verdict:** works today (Fedora packages 0.10.0 and it rips correctly), but
  it is in deep maintenance hibernation with a known compatibility time-bomb.

### cyanrip — the strategic successor — is alive and accurate
- **Last release: v0.9.3.1, 2024-06-05; actively maintained** (382★, ongoing
  issues/commits — [repo](https://github.com/cyanreg/cyanrip)).
- **C + FFmpeg, LGPL-2.1.** We invoke rippers as subprocesses (no linking), so
  LGPL-2.1 is fine against our GPL-3.0-only, exactly as whipper's GPL is.
- **Accuracy features:** AccurateRip **v1 and v2** verification, **EAC CRC32**,
  MusicBrainz tagging, `cd-paranoia` error recovery + drive-offset compensation,
  HDCD decode, CD de-emphasis, cover-art embed/download, ReplayGain v2, many
  output formats (flac/opus/mp3/alac/wavpack/…) via FFmpeg.
- **Gap vs. whipper:** **no CTDB**, and **no AccurateRip submission** (same as
  whipper). Being C/FFmpeg, it has **no Python-version cliff**.
- **Packaging (open item):** in the **AUR** for Arch; **Fedora availability is
  unconfirmed** (likely COPR or a source build — must be verified before a
  Fedora-toolbox container can `dnf install` it). This is the main feasibility
  unknown for the migration.

### CTDB is backend-independent — it is *ours*, not whipper's
Neither whipper nor cyanrip does CTDB. Our clean-room `CTDBClient` +
`whipper_gui/ctdb/` verify library (KDD-16) sits **above** whichever ripper we
use, so the backend choice does not affect the CTDB feature at all.

### AccurateRip / CTDB submission — still permanently out
Unchanged from prior investigation: submission is operator-trust-gated
(EAC/dBpoweramp for AccurateRip). *Verification* works and stays in scope.

### Python 3.14 — our GUI is fine
Our code uses no `pkg_resources`; PySide6 ships abi3 wheels that load on 3.14
(confirmed on the user's machine: venv on Python 3.14, PySide6 6.11.1). The only
3.14 exposure is **whipper-in-container**, above.

### Other tools considered
- **riprip** (Blobfolio, Rust) — specialised for *track recovery* from damaged
  discs; niche, not a general accurate-ripper replacement. Worth remembering for
  the damaged-disc story, not as the primary backend.
- **CUETools/CUERipper** — Windows/.NET; the CTDB reference, not a Linux backend.

---

## The decision: contribute vs. integrate vs. fork

| Option | Verdict | Why |
|---|---|---|
| **Stay on whipper, contribute upstream** | **Yes, short-term only** | It works now and the adapter already isolates it. But a 5-year release gap means PRs are unlikely to ship, so contributing is low-leverage. |
| **Integrate cyanrip as a second backend (`CyanripImpl`)** | **Yes — the strategic plan** | Active, accurate, C (no Python cliff), LGPL-compatible. The `WhipperBackend` ABC already exists for exactly this. CTDB rides along unchanged. |
| **Fork whipper** | **No — rejected** | Forking a 5-years-stale Python tool inherits its maintenance burden *and* the `pkg_resources` cliff. The project guardrail already says: never fork whipper; migrate to cyanrip if forced. |
| **Integrate our GUI *into* whipper upstream** | **No** | whipper is stalled; upstreaming a Qt GUI into a hibernating CLI helps nobody. |
| **Write our own ripper** | **No** | `cd-paranoia`-level work for marginal gain; both whipper and cyanrip already wrap it well. |

**Recommendation:**
1. **Now:** keep whipper (it rips correctly). Keep the adapter boundary clean
   (done). Treat the `pkg_resources` situation as a *monitored risk*, not a fire.
2. **Near-term UX win (backend-independent):** add **drive-model → read-offset
   auto-lookup from the AccurateRip offset list**, so a user never has to know
   their offset number. This is what would have prevented today's friction —
   independent of whipper vs. cyanrip.
3. **Medium-term:** build **`CyanripImpl`** behind the existing `WhipperBackend`
   ABC as the strategic successor backend, selectable in Settings. Sequence it
   as a real project (below), not a someday-contingency.
4. **Never fork whipper.** If ripper-level changes are ever needed, contribute
   to **cyanrip** (active, will merge) instead.
5. **CTDB stays ours** regardless of backend.

---

## `CyanripImpl` migration plan (phased — start when picked up)

1. **Feasibility spike (no code-commit risk).** Confirm cyanrip packaging for
   the `ripping` container (Fedora COPR? build? switch container base to Arch?),
   and run `cyanrip` by hand on the Police disc: capture its CLI surface, its
   verify/CRC output, and its log/cue/sidecar files. Decide what maps to our
   `DiscInfo` / `RipLog` / `RipParameters`.
2. **`adapters/cyanrip_backend.py`** implementing the `WhipperBackend` ABC
   (`list_drives`, `disc_info`, `rip`, `version`, optional `analyze_drive`/
   `find_offset`). Same host-routing principle (call a host-exported binary).
3. **`parsers/cyanrip_*.py`** for its output (named-group regexes, per the
   project rule), feeding the existing `RipLog`/AccurateRip UI.
4. **Backend selector** in Settings (`Config.ripper_backend`, default whipper),
   so the choice is a config switch — no GUI rewrite.
5. **Parity tests** — easy/edge/unexpected cases for the new parser + adapter,
   matching the whipper suite's depth.
6. **Hardware parity run** — same disc through both backends; compare CRCs.

**Open feasibility unknowns to resolve in step 1:** cyanrip Fedora packaging;
whether cyanrip exposes everything we surface (pregap/HTOA, CD-TEXT, per-track
test+copy CRC, the sidecars); offset handling (cyanrip also needs an offset —
reinforcing the auto-lookup win above).

---

## Sources
- [whipper releases](https://github.com/whipper-team/whipper/releases) (v0.10.0, 2021-05-17)
- [whipper repo](https://github.com/whipper-team/whipper)
- [cyanrip repo + README](https://github.com/cyanreg/cyanrip) (v0.9.3.1, 2024-06-05, LGPL-2.1)
- [setuptools history — pkg_resources removal](https://setuptools.pypa.io/en/stable/history.html)
- [riprip (track recovery)](https://github.com/Blobfolio/riprip)
- [CUETools Database](http://cue.tools/wiki/CUETools_Database)
