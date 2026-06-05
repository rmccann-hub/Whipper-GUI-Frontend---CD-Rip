# Read-offset subsystem — investigation & refactor (2026-06)

**Trigger:** on a from-scratch test with a *recognizable* CD, auto-detect of the
drive read offset failed. This is a complete investigation of the offset
subsystem, the refactor that fixed it, and what remains hardware/data-gated.

## How offsets reached whipper before

Two sources, both surfaced in `offset_config.py`:
1. **`whipper.conf`** — written by the drive-setup wizard running whipper's own
   `whipper offset find`. whipper is authoritative for this file (KDD-15).
2. **GUI `--offset` override** (`Config.read_offset` + `override_read_offset`) —
   a manual value passed at rip time.

The wizard (`DriveSetupDialog` → `DriveSetupWorker` → `WhipperBackend.find_offset`)
called `whipper offset find`, parsed `Read offset of device is: N`, and on
failure showed *"Could not detect the read offset. Insert a popular commercial
CD…"*. A manual spinbox was the only fallback.

## Root cause — the architecture leaned entirely on a tool that doesn't work here

`whipper offset find` rips trial offsets and compares them to AccurateRip **for
the inserted disc**, inside the container. It is documented upstream as
"primitive," and it failed on the tested Pioneer BDR-209D *even with a disc
that is in AccurateRip* (network reachability from inside the container, the
specific pressing being matched, and whipper's own detection quality all have
to line up). So the headline "auto-detect" path was unreliable by design.

**The missed opportunity:** the read offset is a property of the **drive model**,
not the disc. AccurateRip publishes a canonical drive→offset list, and EAC /
dBpoweramp resolve the offset by *looking the drive up in that list* — no disc
involved. We already parse the drive's vendor + model from `whipper drive list`
into `DriveDescriptor`… and then threw it away.

## The refactor (implemented)

- **New adapter `adapters/accuraterip_offsets.py`** — `OffsetDatabase` maps a
  normalized `vendor + model` to a read offset. The matching core
  (`normalize_drive_name`) collapses whitespace (whipper emits the
  double-spaced `BD-RW  BDR-209D`), uppercases, and strips an `ATAPI` tag, so
  whipper's string and AccurateRip's name agree. A model-only fallback resolves
  unambiguous single hits. **Never raises** (property-tested).
- **`DrivePicker.current_drive()`** — exposes the selected `DriveDescriptor`
  (vendor/model), so the offset can be looked up without re-running `drive list`.
- **`DriveSetupDialog`** gains `known_offset` / `drive_label`: when the offset is
  known for the drive, the wizard **pre-fills it and calls it out prominently**
  ("✓ Known read offset for PIONEER … BDR-209D: +667 — click Save offset"). One
  click, **no disc, no whipper probe.**
- **`MainWindow._on_drive_setup`** does the lookup (`OffsetDatabase.load_default`)
  and passes the result in. whipper's `offset find` (the Detect button) is
  **demoted to optional verification**, not the primary path.

Net effect: the tested Pioneer now gets the correct +667 instantly. The flaky
disc-probe is still available but no longer the only road.

## Safety

A wrong offset silently corrupts a rip, so the lookup only ever **suggests**:
it pre-fills the field and the user clicks Save (and can cross-check the value
against the accuraterip.com link already in the dialog). Nothing auto-applies.

## Data: curated now, full list is the gated part

`_CURATED_OFFSETS` is a small, **high-confidence** table kept in code (not as
packaged data — same AppImage pitfall that put `help_content` in code). It is
led by the Pioneer BD family (`BDR-209D = +667`, confirmed on real hardware).
It is intentionally small because shipping a wrong value is harmful.

**Extension without code changes:** a user can drop the full AccurateRip list
as `~/.config/whipper-gui/drive_offsets.csv` (`name,offset` rows); it overlays
and overrides the curated seed.

## What's needed to do better in the future (hardware/data-gated)

1. **Import the full AccurateRip offset list (~tens of thousands of drives).**
   The canonical source is the binary `DriveOffsets.bin` at
   `accuraterip.com/accuraterip/DriveOffsets.bin`. A parser for it could either
   ship a generated CSV at build time or read the `.bin` at runtime. *Gated*
   because the binary format must be confirmed bit-exactly against a known drive
   before we trust it to write offsets — and that needs real hardware + a couple
   of known-good drives to validate against. Until then the curated table +
   user CSV cover the tested hardware.
2. **Confirm offsets for drives other than the Pioneer family** on real
   hardware before adding them to the curated table. Each unverified entry is a
   silent-corruption risk; the bar for the in-code table is "verified or
   universally published," everything else goes through the user CSV.
3. **Auto-offer on drive detection.** Once a drive is selected and its offset is
   known, the GUI could pre-stage the value even before the wizard is opened
   (still behind a confirm). Deferred to keep a human in the loop while the data
   set is small.
4. **A model→offset confidence/source field.** When the full list lands,
   recording where each offset came from (AccurateRip submission count) would let
   the UI flag low-confidence drives. Nice-to-have, not required.

## Tests added

`tests/test_accuraterip_offsets.py` (normalization + lookup across the five
tiers, CSV overlay, a never-raises property test, and a **regression test
pinning the user's exact `PIONEER`/`BD-RW  BDR-209D` string → +667**), plus
`DrivePicker.current_drive()` cases and `DriveSetupDialog` prefill/save cases.
Suite 534 → 556.
