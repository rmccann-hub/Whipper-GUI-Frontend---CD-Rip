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

## Data: the full AccurateRip list is now bundled (works for any drive)

The canonical AccurateRip list — `DriveOffsets.bin` from
`accuraterip.com/accuraterip/DriveOffsets.bin` — is **imported and bundled**, so
lookup works for ~4,800 drives **offline**, not just the tested one.

- **Format (reverse-engineered + validated):** a flat array of 69-byte records,
  each `<int16 LE signed offset><67-byte null-padded ASCII name>`. The big risk
  with a binary format is a silent misparse, so the importer has a **validation
  gate**: it refuses to write the data module unless the Pioneer BDR-209D
  resolves to the known-correct **+667**. (That sentinel passed; spot-checks
  across LG/ASUS/Plextor/Optiarc are sane too.)
- **How it's stored:** `scripts/update_drive_offsets.py` parses the `.bin`,
  normalizes names with the *same* `normalize_drive_name` the lookup uses (so
  keys match whipper's vendor+model), drops names that normalize to conflicting
  offsets (never guess), and writes `adapters/accuraterip_offsets_data.py` — a
  gzip+base64 blob (~21 KB compressed). It's a **Python module, not packaged
  data**, so it ships reliably in the AppImage (dodging the `help_content`
  pitfall) and needs no network at runtime.
- **Refresh:** re-run `python3 scripts/update_drive_offsets.py` to pull a fresh
  list. (This is why a live runtime query is unnecessary: the list changes
  slowly, the bundled copy is offline + instant, and refreshing is one command.)
- **Layering:** user CSV (`~/.config/whipper-gui/drive_offsets.csv`) > a tiny
  in-code `_CURATED_OFFSETS` (hand-verified overrides) > the bundled full list.

## What's needed to do better in the future

1. **Periodically refresh the bundled list** (`scripts/update_drive_offsets.py`).
   The validation gate guards against a format change silently corrupting it.
2. **Confirm exotic offsets on real hardware.** The bundled values are
   AccurateRip's community data; the tested Pioneer is hardware-confirmed. Any
   drive a user finds wrong can be corrected via the user CSV, and genuinely
   verified values can graduate into `_CURATED_OFFSETS`.
3. **A confidence/source field.** AccurateRip's per-drive submission count isn't
   in `DriveOffsets.bin`; if a future source exposes it, the UI could flag
   low-confidence drives. Nice-to-have.
4. **Real from-scratch wizard run** remains the final proof of the end-to-end
   UX (the lookup + parse are unit-tested and the +667 sentinel is validated,
   but a live run on hardware confirms the wiring).

## Tests added

`tests/test_accuraterip_offsets.py` (normalization + lookup across the five
tiers, CSV overlay, a never-raises property test, and a **regression test
pinning the user's exact `PIONEER`/`BD-RW  BDR-209D` string → +667**), plus
`DrivePicker.current_drive()` cases and `DriveSetupDialog` prefill/save cases.
Suite 534 → 556.
