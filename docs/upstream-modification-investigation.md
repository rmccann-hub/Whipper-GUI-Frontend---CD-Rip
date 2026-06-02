# Upstream open-source modification — EAC-parity investigation

**Status: investigation only (2026-06-02).** No code here. This records what
could be gained by *modifying the open-source programs underneath us* (not just
wrapping them, which is all we've done so far), how feasible each is, and — just
as importantly — which gaps are **not worth revisiting** so a future session
doesn't re-litigate them.

The yardstick is **Exact Audio Copy (EAC)** on Windows: the de-facto gold
standard for archival CD ripping. "Perfect use case vs Windows" means matching
or beating EAC.

## TL;DR

- Most of EAC's *correctness* features are **already delivered by whipper**
  (secure test+copy, AccurateRip verify, read-offset + overread, cache defeat,
  gap detection, HTOA). We don't need to modify anything to match EAC there.
- The one genuine "beyond EAC" win that needs new low-level work — **CTDB
  parity repair** — does **not** require modifying whipper. It's a *separate*
  LGPL tool (`ctdb-cli`) we wrap behind an adapter. Already planned (KDD-14);
  this investigation confirms it's feasible.
- **Modifying whipper itself is discouraged.** whipper is unmaintained (last
  release 2021), installed from the distro package inside the Distrobox
  container, and treated as a black box behind `WhipperBackend` (Critical Rule
  #1). A fork would have to be built into the container and maintained forever,
  against a tool whose own successor is `cyanrip`. Prefer **upstream PRs** or
  **wrapping a separate tool** over forking.
- A few items are **permanently non-feasible** (policy/trust-gated, not code
  problems) or **not worth the effort** (marginal gain for a rewrite). They're
  listed at the bottom so we stop revisiting them.

## What EAC does, and where we already stand

| EAC capability | Our status | Needs upstream modification? |
|---|---|---|
| Secure mode: test + copy pass, re-read on mismatch | ✅ whipper does this per track; we surface "Test/Copy CRCs match" | No |
| AccurateRip **verification** | ✅ whipper queries it; parser + UI show v1/v2 confidence | No |
| Read-offset correction + overread into lead-in/out | ✅ whipper (`-x`); our drive-setup wizard calibrates it | No |
| Defeat audio cache | ✅ whipper | No |
| Gap / pregap detection (subchannel) | ✅ whipper via `cdrdao` | No |
| HTOA (Hidden Track One Audio) | ✅ whipper detects + rips non-silent HTOA | No (edge-case accuracy bugs exist upstream) |
| CUE / LOG / M3U / TOC sidecars | ✅ whipper writes all four | No |
| MusicBrainz metadata | ✅ via our `MusicBrainzClient` | No |
| **CTDB parity verify** | ❌ not present | New tool, not a whipper change |
| **CTDB parity repair** | ❌ not present | New tool, not a whipper change |
| AccurateRip **submission** | ❌ and can't be fixed | N/A — policy-gated |
| C2 error-pointer reading | ❌ (cdparanoia doesn't use C2 meaningfully) | Yes — deep, not worth it |

The headline takeaway: **the rip engine is already bit-perfect-capable.** EAC's
remaining edge over us is the CUETools Database (CTDB) repair path, which is an
*additive* tool, not a modification of our existing stack.

---

## Feasible — added to TASKS.md with priority

### 1. CTDB verify (read-only) — HIGH (already P1, KDD-14 Phase 1)
The CUETools Database server is **open source (LGPL)**; the protocol is
derivable from it, and a Python reference client exists
([`bmwalters/python-cuetoolsdb`](https://github.com/bmwalters/python-cuetoolsdb)).
Phase 1 is a read-only "Verify with CTDB" verdict after a rip, behind a thin
`CTDBClient` adapter (Critical Rule #1). **It is a pure-Python client — NOT a
wrap of `ctdb-cli`** (see the correction below). Concrete plan in
[CTDB Phase-1 implementation spec](#ctdb-phase-1-implementation-spec). **This is
the prerequisite for repair.**

> **Cannot be finished in the cloud dev environment.** Verification means
> computing a CTDB CRC over the *decoded FLAC audio* and comparing it to the DB
> — correctness-critical code that needs a real CD whose disc is actually in
> CTDB to validate (a T32-style hardware confirmation). And a licensing
> question must be resolved first (see below). So this is implemented in a
> focused, hardware-validated follow-up, not blindly here.

### 2. CTDB parity **repair** — HIGH (already P1, KDD-14 Phase 2) — the differentiator
CTDB stores whole-disc parity (~180 KB). On a rip that ends with uncorrectable
errors, the parity record can **reconstruct the damaged samples** and re-verify
— turning a scratched disc into a mathematically perfect file. This is the one
place we can genuinely *exceed* EAC's everyday workflow. Plan (from KDD-14):
**wrap `ctdb-cli`** (`ctdb-cli verify|repair <cue>`, `--xml` for parseable
output) rather than reimplement the Reed-Solomon erasure coding; **explicit
"Attempt repair" trigger**; **submission shelved**. Depends on #1.

> **Correction — `ctdb-cli` is C#/.NET 10, not C.** KDD-14 (and an earlier
> research note) called `ctdb-cli` "a C tool, cheap to vendor." The repo
> ([`Masterisk-F/ctdb-cli`](https://github.com/Masterisk-F/ctdb-cli)) builds
> with `./configure && make` but is **C# on .NET 10**. That makes bundling it
> in the AppImage **heavy** (it drags in the .NET runtime), not cheap — a real
> change to the Phase-2 cost/benefit. Options to weigh when Phase 2 starts:
> (a) bundle `ctdb-cli` + a trimmed/self-contained .NET publish in the AppImage;
> (b) route repair through the dependency subsystem as an *optional* tool the
> user installs (like Picard), rather than bundling; (c) revisit a pure-Python
> `CUETools.Parity` port (previously rejected as high-risk). No decision needed
> now — recorded so Phase 2 starts from the real facts.

### CTDB Phase-1 implementation spec

What a future, hardware-validated PR needs to build. Grounded in the
`python-cuetoolsdb` reference (modules: `network.py`, `verify.py`,
`zlib_crc.py`, `cdda.py`, `types.py`).

- **Adapter:** `adapters/ctdb_client.py` — `CTDBClient` ABC shaped like
  `MusicBrainzClient` (PLANNING §6), plus `CtdbHttpImpl`. Mandatory adapter
  layer per Critical Rule #1.
- **Disc identity:** the CD **TOC** (track offsets + lead-out), same input
  AccurateRip uses. We already have it from the rip (`.toc`/`.cue`/the parsed
  log), so no extra optical read.
- **Lookup:** HTTP GET to the CTDB server (the `db.cuetools.net` lookup
  endpoint) keyed by the TOC; response lists entries with **confidence** and
  **CRC(s)**. Set a descriptive `User-Agent` (MB-client convention).
- **Local CRC:** compute CTDB's CRC over the ripped audio and compare to the
  DB entry to produce the verdict + confidence. **The exact algorithm lives in
  the reference's `zlib_crc.py`/`verify.py` — read it when implementing; do not
  guess.** Requires decoding FLAC → PCM (via `flac -d`/`soundfile`); the FLAC
  files are already on disk next to the rip.
- **Worker + UI:** `workers/ctdb_worker.py` (off-thread, emits
  `verified(result)`/`error`), and a "Verify with CTDB" affordance in
  `ui/rip_progress.py` populated after a rip — next to the AccurateRip column.
- **No new bundled dependency** (pure-Python; bundles trivially) — the opposite
  of Phase 2.
- **⚠️ License gate (resolve before writing code):** `python-cuetoolsdb` is
  **GPL-2.0**; this project is **GPL-3.0-only** (KDD-10). If it is GPL-2.0-*only*
  we **cannot port its code** — the two are one-way incompatible. Mitigation:
  reimplement the protocol clean-room from the **LGPL** server reference
  (`gchudov/cuetools.net`), using `python-cuetoolsdb` only as documentation,
  **or** confirm the reference is GPL-2.0-*or-later* (then it's usable under
  GPL-3.0).
- **Validation:** a real CD that is present in CTDB → "verified, confidence N";
  a CD not in CTDB → "not in database" (the no-match path). This is the
  T32-equivalent acceptance test and can only be done on hardware.

### 3. Upstream whipper bug fixes — contribute, don't fork — LOW/MEDIUM
Two known upstream defects we currently work around:
- `whipper cd info` exits non-zero on discs not in MusicBrainz/FreeDB (the
  `Info` subcommand rejects `--unknown` even though `_CD.do()` requires it). Our
  adapter already catches this and returns an empty `DiscInfo`.
- HTOA detection false-positives / CRC mismatches on drives without "official"
  HTOA support (whipper issues #75, #82).

These are small Python patches, but whipper is installed from the distro package
in the container, so the *clean* path is an **upstream PR**, not a maintained
fork. Value is low because our adapter already handles the first and the second
is a niche accuracy edge. **Priority: LOW** — open upstream PRs opportunistically;
do not fork.

### 4. EAC-style log checksum (scene-trust) — LOW, GUI-side (no upstream change)
EAC appends a signed checksum so a `.log` can be proven untampered (valued by
archival/"scene" communities). whipper already SHA-256s its log and our parser
captures it. We could additionally emit an EAC-compatible logsigner checksum
*from our own code* over whipper's log — **no upstream modification needed.**
Niche; **priority LOW.**

---

## Non-feasible / not worth it — do **not** revisit without a rethink

Recorded so we don't burn time here again. If we ever do revisit, the note says
what it would actually take.

1. **AccurateRip submission — PERMANENTLY NON-FEASIBLE (policy, not code).**
   AccurateRip's operators accept submissions only from EAC and dBpoweramp. Any
   Linux tool implementing the upload protocol has its submissions rejected. No
   amount of code fixes this. *Verification already works and stays in scope.*

2. **CTDB submission — NON-FEASIBLE (trust-gate).** Almost certainly subject to
   the same client-allowlist/trust gate as AccurateRip submission. Verify and
   repair are fine; uploading is shelved indefinitely.

3. **C2 error-pointer reading — NOT WORTH IT (effectively a rewrite).** EAC uses
   drive C2 pointers for fast error location. `cdparanoia`/`libcdio` deliberately
   *don't* rely on C2 (they use overlapping reads + statistical agreement), and
   C2 quality is wildly drive-firmware-dependent. Adding real C2 support means
   deep C-level surgery on `libcdio`/`cd-paranoia` for a *marginal* gain —
   whipper already reaches bit-perfect via overlap + AccurateRip/CRC. To revisit
   would mean **modifying or replacing the C read engine** — treat as
   build-from-scratch.

4. **Literal two-full-pass "Test & Copy" of the whole disc — NOT WORTH IT.**
   whipper already does a test read and a copy read *per track* and compares
   CRCs (our fidelity summary reports it). EAC's two *separate whole-disc passes*
   add marginal assurance at 2× rip time. Would require forking whipper's rip
   loop. Parked unless a user explicitly demands the two-pass behavior.

5. **Byte-for-byte EAC log format parity — NOT WORTH IT.** Matching EAC's exact
   log layout (beyond the optional checksum in feasible #4) chases a moving,
   semi-proprietary target for little benefit. Our log + the structured parser
   already capture the archival facts.

6. **A separate drive-offset / drive-feature database — REDUNDANT.** EAC ships
   its own community DB. The open equivalent is AccurateRip's offset list, which
   whipper already uses and our wizard reads. Building/maintaining a parallel DB
   is build-from-scratch and redundant.

7. **Replacing whipper with an in-house ripper — OUT OF SCOPE (build-from-
   scratch).** Already an explicit out-of-scope item. If whipper finally breaks
   on `pkg_resources` removal, the migration target is **`cyanrip`** via
   `WhipperBackend.CyanripImpl` (the adapter exists for exactly this), *not* a
   from-scratch ripper.

---

## Architectural guardrail for any future "modify upstream" work

If a feature ever truly requires changing a program underneath us, prefer in
this order:

1. **Wrap a separate, already-maintained tool** behind a new adapter (how CTDB
   repair is planned). Zero change to whipper; honours Critical Rule #1.
2. **Upstream PR** to the project (whipper/libcdio/etc.) and consume the released
   version. No private fork to maintain.
3. **Maintained fork — last resort.** This would mean building our fork *into
   the Distrobox container* instead of the distro package, and owning it
   indefinitely. Given whipper is already unmaintained with `cyanrip` as its
   successor, a whipper fork is almost never the right call — migrate the adapter
   instead.

Sources: [whipper](https://github.com/whipper-team/whipper) ·
[whipper HTOA issue #75](https://github.com/whipper-team/whipper/issues/75) ·
[ctdb-cli](https://github.com/Masterisk-F/ctdb-cli) ·
[CUETools Database](http://cue.tools/wiki/CUETools_Database) ·
[cuetools.net (LGPL client/server)](https://github.com/gchudov/cuetools.net)
