# EAC WAV — baseline (shared extraction)

WAV is lossless, so its bit-perfect target is the **same per-track Copy CRC** as
FLAC. The canonical EAC extraction baseline already lives in
[`../EAC_flac/eac_baseline_police_classics.log`](../EAC_flac/) — there's no
separate WAV log to keep here (the extraction is identical; only the container
differs). A `whipper_wav/` or `cyanrip_wav/` rip is parity when its Copy CRCs
match that baseline. See [`../README.md`](../README.md). No audio is committed.
