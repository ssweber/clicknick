# Phase 3 Max1400 Payload-Only Template Probe Results (March 8, 2026)

## Scope

Evaluate the narrow hypothesis:
- start from clean `grcecr_max1400_native_20260308`
- replace only the shorter comment `len + payload` bytes
- keep all other sections from the clean `max1400` donor unchanged

This report is limited to the clean March 8 plain-comment lane.

## Probe Queue Outcome

Scenario:
- `grid_max1400_payload_only_template_20260308`

Cases:
- `grcmpt_short_len_payload_from_max_20260308`
- `grcmpt_medium_len_payload_from_max_20260308`

Verify outcomes:
- short:
  - `blocked`
  - clipboard event: `crash`
  - note: `'Out of Memory'`
- medium:
  - `blocked`
  - clipboard event: `crash`

Immediate conclusion:
- the clean March 8 `max1400` donor is not replay-safe if only the shorter `len + payload` section is replaced
- this is a stronger failure than wrong topology alone

## Exact Probe Rule

Payload-only mutations used:

### Short

- base donor:
  - `grcecr_max1400_native_20260308`
- copied from short native:
  - `0x0294..0x0310`
- kept from max1400 donor:
  - `0x0000..0x0293`
  - `0x0311..0x1FFF`

### Medium

- base donor:
  - `grcecr_max1400_native_20260308`
- copied from medium native:
  - `0x0294..0x040B`
- kept from max1400 donor:
  - `0x0000..0x0293`
  - `0x040C..0x1FFF`

## Offline Diff Accounting

Helper:
- `devtools/march8_max1400_template_probe.py`

### Short Native As Target

Pure payload-only probe versus clean short native:
- payload window: `1436`
- metadata post-payload window: `109`
- gap band: `8`
- row0 band: `635`
- row1 band: `436`
- tail band: `491`
- full: `3115`

If the target bytes are copied farther:

- through gap `0x0294..0x0A5F`:
  - full: `1562`
  - remaining mismatches:
    - row0 band: `635`
    - row1 band: `436`
    - tail band: `491`
- through row0 `0x0294..0x125F`:
  - full: `927`
  - remaining mismatches:
    - row1 band: `436`
    - tail band: `491`
- through row1 `0x0294..0x1A5F`:
  - full: `491`
  - remaining mismatches:
    - tail band: `491`

### Medium Native As Target

Pure payload-only probe versus clean medium native:
- payload window: `1177`
- metadata post-payload window: `87`
- gap band: `9`
- row0 band: `588`
- row1 band: `638`
- tail band: `457`
- full: `2956`

If the target bytes are copied farther:

- through gap `0x0294..0x0A5F`:
  - full: `1683`
  - remaining mismatches:
    - row0 band: `588`
    - row1 band: `638`
    - tail band: `457`
- through row0 `0x0294..0x125F`:
  - full: `1095`
  - remaining mismatches:
    - row1 band: `638`
    - tail band: `457`
- through row1 `0x0294..0x1A5F`:
  - full: `457`
  - remaining mismatches:
    - tail band: `457`

## Interpretation

What the crash likely means:
- stale `max1400` values in `0x08FD..0x0A5F` are not benign
- they appear structurally coupled to the payload length/body size strongly enough to destabilize paste

Why this is the most likely immediate cause:
- copying only `len + payload` leaves `109 + 8 = 117` stale bytes after the payload window for short
- copying only `len + payload` leaves `87 + 9 = 96` stale bytes after the payload window for medium
- when those post-payload and gap bytes are replaced too, the offline mismatch drops sharply:
  - short: `3115 -> 1562`
  - medium: `2956 -> 1683`

Conservative conclusion:
- the first mandatory companion surface after the payload window is:
  - metadata post-payload window `0x08FD..0x0A53`
  - gap band `0x0A54..0x0A5F`
- payload-only is therefore not a viable clean March 8 synthesis path

## Practical Next Step

If more online probes are attempted today, the next most defensible narrow probe is not payload-only.

Best next candidate:
- `max1400` donor with target bytes copied through the gap band:
  - `0x0294..0x0A5F`

Reason:
- it directly removes the most likely crash-causing stale descriptor surface
- it is still much narrower than copying row0/row1/tail
- it tests whether the remaining row0/row1/tail mismatch is survivable or merely causes wrong topology rather than crash

What this result does **not** prove:
- it does not prove that `through_gap` will pass
- it only shows that payload-only is structurally too incomplete
