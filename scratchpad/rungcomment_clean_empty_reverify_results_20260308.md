# Clean Empty-Rung Comment Re-Verification Results (March 8, 2026)

## Scenario

- Scenario: `grid_rungcomment_clean_empty_reverify_20260308`
- Queue doc: `scratchpad/grid_rungcomment_clean_empty_reverify_verify_queue_20260308.md`
- Case spec: `scratchpad/phase2_rungcomment_clean_empty_reverify_case_specs_20260308.json`
- Tooling audit: `scratchpad/rungcomment_tooling_audit_20260308.md`

## Outcome Summary

- `8/8` cases completed `verified_pass`
- all verify events: `copied`
- all native payload lengths: `8192`
- all verify-back payload lengths: `8192`

Fresh native labels:
- `grcecr_empty_native_20260308`
- `grcecr_short_native_20260308`
- `grcecr_medium_native_20260308`
- `grcecr_max1400_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

## Immediate Decision

The clean re-verification round disproves the old fallback explanation that empty-baseline comment issues should be treated as a generic "shows after reopen" UI quirk.

New accepted truth:
- native plain comments on a truly empty 1-row rung work at:
  - short length
  - medium length (`256`)
  - max tested length (`1400`)
- the visible rung stays empty in the native clean-baseline lane
- but comment support is **not** metadata-only
- comment support remains **structurally coupled** to bytes outside the immediate payload window

So the right classification is:
- native plain comments on empty rungs: **proven working**
- comment synthesis model: **still unresolved**

## Payload Presence Check

Comment payload evidence from the new native captures:
- empty control:
  - `0x0294 = 0`
- short:
  - `0x0294 = 121`
  - RTF-like ANSI payload begins at `0x0298`
- medium:
  - `0x0294 = 372`
  - RTF-like ANSI payload begins at `0x0298`
- max1400:
  - `0x0294 = 1516`
  - RTF-like ANSI payload begins at `0x0298`

Important note:
- the manifest row text for `grcecr_max1400_native_20260308` does not include the full comment line
- but the captured bytes do contain the max1400 RTF payload and the operator recorded `verified_pass`
- for this case, payload bytes are the decisive source of truth

## Empty Control Versus Commented Native Captures

Diff counts versus `grcecr_empty_native_20260308`:

### Short comment

- metadata band `0x0254..0x0A5F`: `677`
- row0 band `0x0A60..0x125F`: `669`
- row1 band `0x1260..0x1A5F`: `20`
- full `8192`: `1366`

### Medium comment

- metadata band `0x0254..0x0A5F`: `904`
- row0 band: `603`
- row1 band: `576`
- full `8192`: `2679`

### Max1400 comment

- metadata band `0x0254..0x0A5F`: `1682`
- row0 band: `681`
- row1 band: `421`
- full `8192`: `3275`

Interpretation:
- the comment delta is not confined to the metadata band
- both the row0 band and the row1 band participate structurally
- for these 1-row captures, that does **not** mean a second GUI row exists
- it means the second row-sized byte band also changes even when the rendered rung stays visibly empty

## Wire-Flag Check

Compared against the empty native control:
- row0 band wire-flag changes at `+0x19/+0x1D/+0x21`: `0` for short, medium, and max1400
- row1 band wire-flag changes at `+0x19/+0x1D/+0x21`: `0` for short, medium, and max1400

Interpretation:
- the clean empty-rung comment lane is topology-neutral in rendered wire terms
- but it is still structurally coupled through non-wire bytes in the row0/row1 bands

This resolves the prior ambiguity:
- the old failures were not evidence that comments must change visible topology
- but they also were not metadata-only

## Native Versus Verify-Back

Diff counts by region:

### Empty control

- metadata: `0`
- gap `0x0A54..0x0A5F`: `0`
- row0 band: `0`
- row1 band: `572`

### Short comment

- metadata: `0`
- gap: `0`
- row0 band: `0`
- row1 band: `548`

### Medium comment

- metadata: `0`
- gap: `0`
- row0 band: `0`
- row1 band: `540`

### Max1400 comment

- metadata: `0`
- gap: `0`
- row0 band: `0`
- row1 band: `167`

Interpretation:
- Click preserved metadata, the 12-byte gap, and the row0 band byte-exactly in all four clean empty-baseline cases
- the row1 band remains regeneration-sensitive, even for the empty control
- so row1-band companion bytes should still be treated as part of the structural family, but not as a visible-topology failure signal by themselves

## 12-Byte Gap Characterization (`0x0A54..0x0A5F`)

Observed native values:

- empty:
  - `00 00 00 00 01 00 00 00 00 01 00 00`
- short:
  - `00 00 00 00 00 00 1E 00 00 00 00 00`
- medium:
  - `00 1A 00 00 00 00 00 00 00 01 01 FC`
- max1400:
  - `00 01 01 FC 00 FF FF FF FF 01 00 00`

These values round-trip exactly in verify-back for all four cases.

Interpretation:
- the 12-byte gap is **not padding**
- it behaves like a comment-length-sensitive trailer or separator structure
- it should be treated as part of the comment-coupled structural family

## Metadata Slots Versus Row0 Band Cells

Selected-offset comparison on native comment captures supports a narrow conclusion:

- both regions reuse the same `0x40` slot shape
- both regions use many of the same relative offsets
- but equal relative offsets do **not** imply equal meaning across the whole region

Best current interpretation:
- metadata slots are a mixed region:
  - early slots are overwritten by RTF payload bytes for comment-bearing captures
  - later slots and trailer-adjacent slots retain structural descriptor roles
- the row0 band remains a structural descriptor surface in this lane
- the strongest overlap is therefore:
  - **descriptor-slot shape**
  - not a simple one-to-one field identity at every listed offset

High-confidence distinction:
- visible wire-flag semantics in the row0 band at `+0x19/+0x1D/+0x21` stay neutral in the clean comment lane
- metadata-region values at the same offsets are often payload or trailer bytes instead

## Conservative Phase 2 Classification

What is now proven:
- plain native comments on truly empty rungs work at short, medium, and max1400 lengths
- rendered empty topology stays correct on paste/copy-back
- the earlier malformed-rung explanation was real in at least some older lanes

What is still unresolved:
- a deterministic synthesis model for the row0/row1 band companion bytes and gap bytes
- exact semantics of the row1-band regeneration-sensitive companion family
- a robust file/shorthand synthesis path for comment-bearing payloads

Therefore:
- native behavior question: **answered**
- synthesis question / Phase 2 codec gate: **still open**

## Fresh Canonical Baseline Set

These captures can now serve as the clean canonical references requested for future work:

1. `grcecr_empty_native_20260308`
2. `grcecr_short_native_20260308`
3. `grcecr_medium_native_20260308`
4. `grcecr_max1400_native_20260308`
5. `grcecr_fullwire_native_20260308`
6. `grcecr_fullwire_nop_native_20260308`
7. `grcecr_rows2_empty_native_20260308`
8. `grcecr_rows2_vert_horiz_native_20260308`

These are cleaner reference donors than the mixed historical comment lanes.

## Recommended Next Step

Move Phase 3 onto the fresh canonical set:
- use the March 8 empty/fullwire/two-row captures as wireframe donors
- keep comment synthesis out of the production path until the comment companion family is modeled explicitly
