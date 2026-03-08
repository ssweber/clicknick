# Phase 3 Comment Synthesis Readiness (March 8, 2026)

## Scope

Assess how close the March 8 clean empty-rung lane is to plain comment synthesis, using the now-solved no-comment wireframe baseline as the control.

Claim boundary:
- this is a plain-comment readiness assessment only
- no styled-comment synthesis is claimed here
- no production codec behavior is changed here

## New Offline Helper

Helper:
- `devtools/march8_comment_synthesis_readiness.py`

Purpose:
- verify whether the plain comment payload window is already deterministic from text
- quantify the remaining companion-byte surface by band
- check whether any remaining bands can already reuse the solved March 8 no-comment band templates

## Plain Payload Window Status

The helper verifies an exact March 8 plain payload envelope for all three clean empty-rung comment captures:
- short
- medium
- max1400

Exact envelope:
- payload length dword at `0x0294`
- payload bytes start at `0x0298`
- fixed RTF prefix length: `105`
- fixed suffix length: `11`
- exact form:
  - `payload = prefix + plain_text_cp1252 + suffix`

Exact fixed prefix preview:

```text
{\rtf1\ansi\ansicpg1252\deff0\deflang1033{\fonttbl{\f0\fnil\fcharset0 Arial;}}
\viewkind4\uc1\pard\fs20 
```

Exact fixed suffix preview:

```text
\r\n\par }\r\n\0
```

Conservative interpretation:
- the March 8 plain-comment payload window is effectively solved for this lane
- the remaining blocker is not the basic plain RTF body wrapper

## Region Counts Versus Empty 1-Row Control

Using `grcecr_empty_native_20260308` as the control:

### Short

- prefix band: `0`
- metadata pre-payload: `0`
- payload window: `576`
- metadata post-payload window: `98`
- gap band: `3`
- row0 band: `669`
- row1 band: `20`
- tail band: `0`

### Medium

- prefix band: `0`
- metadata pre-payload: `0`
- payload window: `792`
- metadata post-payload window: `108`
- gap band: `4`
- row0 band: `603`
- row1 band: `576`
- tail band: `596`

### Max1400

- prefix band: `0`
- metadata pre-payload: `0`
- payload window: `1561`
- metadata post-payload window: `113`
- gap band: `8`
- row0 band: `681`
- row1 band: `421`
- tail band: `491`

Immediate implications:
- the prefix band is untouched in all three plain-comment cases
- metadata before the payload length dword is untouched in all three plain-comment cases
- the unresolved companion problem starts after the payload window and continues through row0, and for larger comments also through row1 and the tail band

## Reuse Against Solved No-Comment Bands

Reference no-comment family:
- `grcecr_fullwire_native_20260308`

Row1 and tail reuse results:

### Short

- row1 band exact match to fullwire row1 band: `false`
- tail band exact match to fullwire tail band: `false`
- row1 overlap count with fullwire row1 band: `3`
- tail overlap count with fullwire tail band: `0`

### Medium

- row1 band exact match to fullwire row1 band: `false`
- tail band exact match to fullwire tail band: `false`
- row1 overlap count with fullwire row1 band: `213`
- tail overlap count with fullwire tail band: `418`

### Max1400

- row1 band exact match to fullwire row1 band: `true`
- tail band exact match to fullwire tail band: `true`
- row1 overlap count with fullwire row1 band: `421`
- tail overlap count with fullwire tail band: `491`

Conservative interpretation:
- the March 8 max1400 plain-comment lane can already reuse the solved fullwire row1 band and shared tail band exactly
- the short and medium plain-comment lanes still carry distinct companion-band families
- medium is the least converged clean plain-comment case because it introduces both a large row1 family and a distinct tail family

## Remaining Companion Surface After Known Pieces

This accounting treats two things as already available:
- exact plain payload-window synthesis from text
- exact reuse of fullwire row1/tail templates only when the match is exact

Remaining unresolved companion-byte counts:

- short: `790`
- medium: `1887`
- max1400: `802`

By interpretation:
- short is blocked mainly by row0 band plus a small row1 companion family
- medium is still blocked by a large row0 band, a large row1 band, and a distinct tail band
- max1400 is materially closer than medium because its row1 band and tail band are already reusable from the solved fullwire no-comment family

## Practical Readiness Answer

How close the repo is today:

- close to exact plain payload-window synthesis for the clean March 8 empty-rung lane:
  - **yes**
- close to full plain-comment synthesis for short comments:
  - **not yet**
- close to full plain-comment synthesis for medium comments:
  - **no**
- close to full plain-comment synthesis for max1400 comments:
  - **closer than the other two, but still not done**

The main unresolved blocker is now narrower:
- it is primarily the comment companion family after the payload window
- especially the row0 band for all lengths
- plus the medium/short row1 family and the medium tail family

## Recommended Next Move

Keep the work offline and target the remaining companion bands in this order:

1. max1400 row0 band, because row1 and tail already collapse to solved fullwire templates
2. short row0 band plus its small row1 companion family
3. medium tail band
4. medium row1 band

Do not treat this as comment synthesis complete until those remaining companion-band families are explicit and verified.
