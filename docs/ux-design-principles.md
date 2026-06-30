# UX design principles — trust-first CD ripping

**Status:** living guidance (2026-06-28). Distilled from three independent
deep-research reports on *why Exact Audio Copy made bit-perfect ripping usable*
and how to design a modern ripper (provided as research input this session).
This is the **why** behind Platterpus's UX decisions and the bar new features
are held to. Companion to [`architecture.md`](architecture.md) (the *how*).

## The core thesis

EAC's breakthrough was **not** minimalism — consumer rippers (iTunes, Windows
Media Player) were always fewer clicks. EAC won a *different* job: letting an
ordinary person on ordinary hardware produce a rip they could **defend as
correct**, without auditioning every track. It did that by turning hidden
hardware problems (jitter, caching, C2 reliability, read offset, pregaps) into a
**guided workflow, visible status, and auditable logs**.

So the north star for Platterpus is the same as the maintainer's
("good music, good cover image, good everything" + *prove it*):

> The user's real goal is not to *finish* the rip — it's to **know whether the
> result can be trusted**. Treat trust as a first-class UI object, not a backend
> detail.

EAC's own weaknesses are equally instructive — and are things to *avoid*:
its defaults could still be unsafe (burst mode), its learnability lived
*outside* the app (no official docs; a community wiki was effectively required),
and important settings were scattered across many dialogs.

## The principles (and how Platterpus measures up)

1. **Make verification first-class and legible.** Show trust states — *Verified
   / Secure-but-unverified / Suspicious / Inaccurate / Aborted* — in the main
   workflow, with the "why" one click away. *Platterpus:* ✅ the colour-coded
   verdict banner + AccurateRip/CTDB, one honest `confidence ≥ 1` rule shared by
   every surface.
2. **Default to the safest true path.** If the promise is bit-perfect, the first
   rip after install must already be on a defensible path; never let the fast
   mode masquerade as the trustworthy one. *Platterpus:* ✅ secure by default;
   `-Z N` re-rip is opt-in for marginal discs.
3. **Progressive disclosure, two axes.** Defer advanced controls by *task phase*
   (setup → rip → verify) and by *expertise* (basic → advanced → forensic) — but
   the beginner path must still produce a trustworthy result. *Platterpus:*
   ✅ first-run wizard; ⚠️ no explicit **goal presets** yet (gap #1 below).
4. **Outcome-oriented terminology.** Lead with the *effect*, then the term:
   "Drive caches audio — needs slower secure reads," not "Cache defeat."
   *Platterpus:* ✅ goal presets + the format/verdict labels already lead with
   the effect; the two remaining jargon-first surfaces (overread, the
   drive-setup cache verdict) were reworded effect-first (gap #5, 2026-06-29).
5. **Localize failure.** Report the exact time positions of anomalies and let the
   user play them back; for every error say *what happened / what it means for
   the output / what the software already tried / what to do next*. *Platterpus:*
   ⚠️ partial — we surface per-track status; no timestamp-level playback (gap #3).
6. **Two logs, always — and tamper-evident.** A human-readable narrative *and* a
   machine-readable structure. *Platterpus:* ✅ human log + the EAC-layout
   renderer, **plus** the per-rip `.platterpus.json` (the machine-readable log,
   gap #2 — shipped 2026-06-28; it embeds this session's log so one file is a
   self-contained debug record, 0.4.2).
7. **Per-drive profiles, keyed by stable hardware identity.** Separate
   learned-once drive facts (offset, cache, C2) from per-disc session state, with
   *provenance + confidence* on each detection. *Platterpus:* ✅ a drive-profile
   ledger (`drive_profiles.py`, 2026-06-29) keyed by a stable fingerprint
   (WWN → serial → vendor/model) records each offset's source + confidence and
   shows it as a trust line, and guards the identical-drive / offset-disagreement
   cases. It is a **record/display/guard layer** — `whipper.conf` + the
   `--offset` override stay authoritative (KDD-23); *applying* a remembered
   offset per drive is the deferred, hardware-gated piece.
8. **Metadata = reviewable suggestions, not truth.** Auto-fetch and prefill;
   surface confidence/disagreement; never force manual tagging nor silently
   accept a low-confidence match. *Platterpus:* ✅ MusicBrainz pick + editable
   track table.
9. **Documentation lives in the product.** Tooltips, in-context term
   explanations, log explanations — community guides are *supplemental*, not the
   happy path. *Platterpus:* ✅ in-app User Guide + tooltips.
10. **Accessibility from the start.** Accessible names on every control, keyboard
    access to every action, status conveyed by **text/symbol, never colour
    alone**, focus-safe live updates. *Platterpus:* 🟡 much improved (gap #4,
    pass shipped 0.4.4): the status/verdict surfaces, the metadata fields, and
    the disc-info values all carry accessible names; trust is signalled by
    text + symbol, never colour alone; menus have mnemonics and the everyday
    actions (Quit/Settings/User Guide) have platform-standard shortcuts. Still
    open: a full keyboard-reachability sweep of every control and focus-safe
    *live* announcements as a rip progresses.

## Gap backlog (ranked) — tracked in [`TASKS.md`](../TASKS.md)

The reports converge on six things Platterpus does **not** yet do. Ranked by
user impact ÷ effort:

| # | Gap | Why it matters | Rough size |
|---|---|---|---|
| 1 | **Goal presets** ("Fast verified" / "Archival exact" / "Portable") | Anchors all config to user *intent* instead of asking novices to reason about abstract toggles first (EAC's "accuracy vs speed" was this, bluntly). | M |
| 2 | ✅ **Machine-readable (JSON) log** beside the human one (`platterpus.rip_report` → `<name>.platterpus.json`; 2026-06-28) | Powers QA, re-verification, repair tooling, support; "two outputs every time." | S–M |
| 3 | **Timestamp-localized anomalies + one-click playback** of flagged regions | The single most "friendly to demanding users" EAC trait — review only where confidence broke, not the whole disc. | M (HW-gated) |
| 4 | 🟡 **Accessibility pass** (names on status/metadata/disc-info surfaces, text+symbol status, menu mnemonics + standard shortcuts; 0.4.4) | Accessible names, keyboard coverage, non-colour-only status, focus-safe live updates. Reports rank this the #1 modern gap. *Remaining:* full keyboard-reachability sweep + focus-safe live announcements. | S–M |
| 5 | ✅ **Outcome-oriented wording** across Settings/labels (overread + drive-setup cache verdict reworded effect-first; 2026-06-29) | Cuts the learning cost without removing the precise term. | S |
| 6 | ✅ **Drive profiles keyed by stable fingerprint** + detection provenance/confidence (record/display/guard ledger shipped 2026-06-29; per-drive offset *application* deferred as hardware-gated — KDD-23) | Identical-drive collisions and silent wrong-offset rips are the classic *state* bugs (EAC hit exactly this in 2007). | M |

**Status:** gaps #1, #2, #5 shipped 2026-06-28; #6 shipped 2026-06-29 (the
record/display/guard ledger; per-drive offset *application* deferred as
hardware-gated); #4 had its first substantive pass in 0.4.4 (🟡 — accessible
names on the status/metadata/disc-info surfaces, text+symbol status, menu
mnemonics + standard shortcuts; a full keyboard-reachability sweep and
focus-safe live announcements remain). Only #3 (timestamp-localized anomalies +
one-click playback) is untouched — it is hardware-gated (needs real
anomaly-bearing rip output to write a position-level parser against, and a real
FLAC + CC0 sample to validate playback).

## The bar for new features

Before a rip-related feature is "done," ask: does it make trust **more visible**,
keep the **safe path the default**, and explain failure in the **four layers**
(what / meaning / tried / next)? If a feature needs a wiki tour to use, it isn't
finished — put the explanation *in the product*.
