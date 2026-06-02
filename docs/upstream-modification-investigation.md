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
The CUETools Database client + server are **open source (LGPL)**. A native
Linux CLI, [`ctdb-cli`](https://github.com/Masterisk-F/ctdb-cli), already speaks
the protocol (verify, parity calc, repair, submit). Phase 1 is a read-only
"Verify with CTDB" button after a rip, behind a thin `CTDBClient` adapter
(Critical Rule #1). We can either wrap `ctdb-cli` or port the LGPL reference
client to Python. ~200–400 lines. **This is the prerequisite for repair.**

### 2. CTDB parity **repair** — HIGH (already P1, KDD-14 Phase 2) — the differentiator
CTDB stores whole-disc parity (~180 KB). On a rip that ends with uncorrectable
errors, the parity record can **reconstruct the damaged samples** and re-verify
— turning a scratched disc into a mathematically perfect file. This is the one
place we can genuinely *exceed* EAC's everyday workflow. Confirmed feasible:
`ctdb-cli` implements repair today. Plan (unchanged from KDD-14): **wrap
`ctdb-cli`** (don't reimplement the erasure coding), **bundle it in the
AppImage** (repair works on files + downloaded parity, no optical device → no
Distrobox involvement), **explicit "Attempt repair" trigger**, **submission
shelved**. Depends on #1.

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
