       Ladder Encoder Architecture Review

       I've conducted a thorough review of the ladder encoder architecture across all key files. Here's my detailed
        report:

       How encode.py is Actually Called

       Call chain:
       1. CLI entry: clicknick-ladder-capture command (via capture_cli.py:main())
       2. Workflow: Routes to CaptureWorkflow in capture_workflow.py
       3. Encoding: CaptureWorkflow._load_payload() calls ClickCodec().encode_rows() for "shorthand" mode
       4. Shim layer: codec.py:ClickCodec.encode_rows() → _encode_compiled() → encode.py:encode_rung()
       5. Pipeline: encode_rung() calls synthesize_empty_multirow() (step 1-2), then applies comment, wire flags,
       and NOP (steps 3-5)

       Key integration point in codec.py (line 257-260):
       if header_seed is not None and not has_comment:
           out = bytearray(payload)
           header_seed.apply_to_buffer(out)
           payload = bytes(out)
       This correctly skips header seed for comment rungs (matches CLAUDE.md documented pattern).

       ---
       Dead Code and Unused Imports

       No dead code found in current files. All imports are used:
       - encode.py: All imports from empty_multirow, topology are actively used
       - codec.py: normalize_shorthand_row is used in _compile_rows()
       - __init__.py: All re-exports are valid public API

       Historical references (not dead code, properly documented):
       - Lines 148-179 in encode.py document what will be deleted when replacing the old encoder
       - These are comments documenting future cleanup, not code to remove now
       - References to "codec_v2", "phase-B", "WIREFRAME", "mod-36" are all in documentation sections, not active
       code

       ---
       Naming and Organization Issues

       1. Undocumented parameter: legacy_fallback
       - Location: codec.py lines 292, 322
       - Status: Parameter exists but is unused (silently ignored with _ = legacy_fallback)
       - Issue: Not mentioned in CLAUDE.md or any docstrings
       - Not breaking, but confusing for new developers
       - Appears to be a leftover API compatibility stub

       2. Offset inconsistency in comments vs. documentation
       - In encode.py lines 603-604: Comments say "left wire: slot_base + 0x21, right wire: slot_base + 0x25"
       - In DEFINITIONS.md lines 71-74: Says "slot_base + 0x21 — left wire, slot_base + 0x25 — right wire"
       - Actual code (lines 629-633): Correctly uses these offsets
       - ✓ No bug, just confusing comment wording — should say "phase-A left/right offsets" not "slot offsets"

       3. Comment accumulation logic is opaque
       - In codec.py:_compile_rows() lines 175, comment rows are appended to comment_lines: list[str]
       - Later converted to single string via rung.comment_text() (line 62: "\n".join(self.comment_lines))
       - But in encode.py:encode_rung(), the comment parameter is a single str, not a sequence
       - Confusing transition: Multi-line comment list → single-string conversion → single-line validation in
       encoder
       - CLAUDE.md correctly documents: "Only single-line comments are supported" (STATUS.md line 24)
       - However, the multi-line accumulation in codec feels like it supports multi-line, when it will fail

       ---
       Inconsistencies Between DEFINITIONS.md and Code

       All major definitions are accurate. Examples:

       ✓ NOP encoding (DEFINITIONS.md line 98) matches code (encode.py lines 271-275):
       - "col31 +0x1D = 1" (code: CELL_AF_NOP_OFFSET = 0x1D)
       - "col0 +0x15 = 1 for non-first rows" (code: CELL_NOP_ROW_ENABLE_OFFSET = 0x15)

       ✓ Wire flag offsets (DEFINITIONS.md lines 62-65) match topology.py:
       - +0x19 → CELL_HORIZONTAL_LEFT_OFFSET
       - +0x1D → CELL_HORIZONTAL_RIGHT_OFFSET
       - +0x21 → CELL_VERTICAL_DOWN_OFFSET

       ✓ Multi-row comment continuation stream (DEFINITIONS.md lines 168-174) matches _write_continuation_stream()
       exactly

       One minor inconsistency:
       - DEFINITIONS.md says trailer byte 0x0A59 is "zero for wire-only rungs, 0x01 for comment rungs"
       - But encode.py never sets it to 0x01 for comment rungs (line 576 zeros everything after phase-A)
       - This byte lives inside the phase-A stream for 1-row rungs and shouldn't be touched
       - ✓ No bug — the documentation is overly specific about a byte that's managed by the resource file

       ---
       Inconsistencies with CLAUDE.md

       Excellent alignment overall. One item that could be clearer:

       CLAUDE.md line 27: "Applies header seed for non-comment rungs. _encode_compiled() is the integration point."
       - ✓ Correct. Header seed application is at codec.py line 259, only for non-comment rungs
       - However, _encode_compiled() is an internal function, not mentioned in the public API docs
       - NEW DEVELOPERS might be confused about where to start reading

       CLAUDE.md line 32: Lists resource files but doesn't mention smoke_simple_native.scaffold.bin
       - This file exists in resources/ but isn't imported or used anywhere
       - Should either be documented as historical/reference or deleted

       CLAUDE.md line 56: "Multi-row comments with vertical wire (T on row 0, receiving wire on row 1; native
       capture exists but not yet verified as synthetic)"
       - STATUS.md line 44 says this is NOT tested ("[x] Comment + sparse wire on both rows (2-row)")
       - But a "T junction from row 0 to row 1" scenario isn't specifically listed
       - Minor documentation gap, not a code issue

       ---
       Developer Confusion Points

       1. Phase-A stride model (rows 0 vs. 1+ in comment rungs)
       - Location: encode.py lines 599-648
       - Issue: This is the hardest part to understand. Comments explain it well, but the offset calculations are
       different enough that new developers might write cell_offset(0, col) instead of the phase-A formula
       - Recommendation: Add a helper function phase_a_wire_slot(col_idx, wire_type) to encapsulate the magic
       offsets

       2. The continuation stream is separate from the cell grid
       - Location: encode.py lines 634-647 and _write_continuation_stream() lines 347-399
       - Issue: The continuation stream records (after phase-A) have the same cell format (64 bytes each) as the
       grid, but Click reads them differently based on the comment length
       - DEFINITIONS.md explains this perfectly, but code comments are brief

       3. Why synthesize_empty_multirow exists as a separate module
       - Current state: It's step 1-2 of the pipeline, called once per rung
       - Concern: New developers might think it's a general multi-row scaffold builder, when it's actually tightly
       coupled to the empty-rung family
       - Recommendation: Document in CLAUDE.md that this is step 1-2, not a generic scaffold

       4. Unused legacy_fallback parameter
       - Location: codec.py lines 292, 322
       - Status: Parameter is accepted but ignored with _ = legacy_fallback
       - Issue: No docstring explaining why it exists or what it was for
       - Recommendation: Either remove it or add a docstring explaining it's for backward compatibility

       ---
       Resource Files Status

       ┌───────────────────────────────────────────────┬──────┬────────────────────────────────────────────────────
       ──────┐
       │                     File                      │ Used │                         Purpose
             │
       ├───────────────────────────────────────────────┼──────┼────────────────────────────────────────────────────
       ──────┤
       │ comment_phase_a.bin                           │ ✓    │ Phase-A continuation stream template (encode.py
       line     │
       │                                               │ Yes  │ 307)
             │
       ├───────────────────────────────────────────────┼──────┼────────────────────────────────────────────────────
       ──────┤
       │ empty_multirow_rule_minimal.scaffold.bin      │ ✓    │ Empty rung template (empty_multirow.py line 51)
             │
       │                                               │ Yes  │
             │
       ├───────────────────────────────────────────────┼──────┼────────────────────────────────────────────────────
       ──────┤
       │ grcecr_empty_native_20260308.bin              │ ✗ No │ Reference capture (not imported, only mentioned in
       docs) │
       ├───────────────────────────────────────────────┼──────┼────────────────────────────────────────────────────
       ──────┤
       │ phase3_wireframe_band_templates_20260308.json │ ✗ No │ Not imported anywhere
             │
       ├───────────────────────────────────────────────┼──────┼────────────────────────────────────────────────────
       ──────┤
       │ smoke_simple_native.scaffold.bin              │ ✗ No │ Not imported anywhere
             │
       └───────────────────────────────────────────────┴──────┴────────────────────────────────────────────────────
       ──────┘

       Recommendation: Document which files are kept for reference vs. which are actually used.

       ---
       Documentation Accuracy Summary

       ┌────────────────────┬────────────────┬─────────────────────────────────────────────────────────────────────
       ──────┐
       │      Document      │     Status     │                                  Issues
             │
       ├────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────
       ──────┤
       │ CLAUDE.md          │ ✓ Accurate     │ 1 missing resource file listing, unclear about _encode_compiled()
       being   │
       │                    │                │ internal
             │
       ├────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────
       ──────┤
       │ DEFINITIONS.md     │ ✓ Very         │ 1 overly-specific trailer byte claim, could use phase-A offset
       diagrams   │
       │                    │ accurate       │
             │
       ├────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────
       ──────┤
       │ STATUS.md          │ ✓ Current      │ Good operational summary
             │
       ├────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────
       ──────┤
       │ encode.py          │ ✓ Clear        │ Minor: offset names in comments could be more consistent
             │
       │ docstring          │                │
             │
       └────────────────────┴────────────────┴─────────────────────────────────────────────────────────────────────
       ──────┘

       ---
       Summary for New Developers

       To understand the encoder, read in this order:

       1. DEFINITIONS.md — Learn the grid geometry and offsets (10 min)
       2. encode.py docstring (lines 1-188) — Understand the pipeline steps and checklist (5 min)
       3. encode.py:encode_rung() signature (lines 444-476) — See the public API (2 min)
       4. codec.py:_encode_compiled() (lines 231-268) — See how shorthand is compiled (5 min)
       5. encode.py main steps (lines 540-693) — Step through the implementation (20 min)

       Beware of:
       - Phase-A stride math uses different offsets than cell grid
       - Continuation stream records are similar to cells but read by Click differently
       - Header seed must be skipped for comment rungs
       - At most one NOP per rung (validated at line 519-521)

       ---
       Final Assessment

       Overall: Architecture is well-designed and documented.

       - ✓ Clear separation of concerns (scaffold, comment, wire, NOP)
       - ✓ Good documentation with examples and terminology
       - ✓ All code matches the documented patterns
       - ✓ No dead code or broken imports
       - ✓ Proper integration through codec shim layer

       Minor issues (none blocking):
       - Undocumented legacy_fallback parameter
       - Unused resource files should be documented
       - Phase-A offset naming could be more explicit in comments
       - Multi-line comment handling in codec looks like it supports multi-line but doesn't

       These are all documentation/clarity improvements, not code bugs.