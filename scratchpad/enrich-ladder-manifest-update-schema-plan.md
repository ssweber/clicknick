# Enrich Ladder Fixture Manifest With Canonical Rung Rows and Verification Metadata

## Summary
Update `tests/fixtures/ladder_captures/manifest.json` from schema version `1` to `2`, adding per-entry description/rung-row metadata and verification flags, using checklist sources as truth.  
Do this via a deterministic regen script, and update ladder token parsing to support canonical wire tokens `T`, `-`, `|` while rejecting `+`.

## Public Interfaces / Schema Changes
1. Manifest schema bump:
- `tests/fixtures/ladder_captures/manifest.json` top-level `version`: `2`.

2. New entry fields on every manifest entry:
- `description: str`
- `rung_rows: list[str]`
- `verified: bool`
- `codec_generatable: bool`
- `metadata_todo: bool`

3. Token parsing behavior change:
- `src/clicknick/ladder/csv_token_parser.py`:
- `|` is parsed as vertical-wire token (same AST bucket currently used for vertical-mid).
- `+` is no longer treated as a vertical token and falls back to generic/unsupported.

## Implementation Plan
1. Add `devtools/update_ladder_capture_manifest.py` as the single source of truth for manifest enrichment.
- Inputs:
- `tests/fixtures/ladder_captures/manifest.json` (existing entry order and base fields retained)
- `scratchpad/capture-checklist.md`
- `scratchpad/instruction-capture-checklist.md`
- `scratchpad/instruction-matrix.json`
- Output:
- rewritten `tests/fixtures/ladder_captures/manifest.json` with new fields and version bump.

2. Parse source checklist data deterministically.
- Capture checklist:
- Extract 29 label rows with `Build in Click` as description source.
- Normalize escaped markdown vertical token `\|` to `|`.
- Instruction checklist:
- Extract 18 native-label rows (`native_label` + CSV).
- Description for these entries comes from matching `scenario` in `instruction-matrix.json` by `native_label`.

3. Build canonical `rung_rows` strings.
- Always include marker column:
- row 0 starts with `R`
- continuation rows start with empty marker (`""`)
- Canonical token set in stored rows: `T`, `-`, `|` (plus contacts/AF/instruction tokens, and trailing macros `...` or `->`).
- Normalize tokens:
- `t -> -`
- `r -> T`
- `\| -> |`
- Remove left-leading `...` when a specific column placement is intended by expanding explicit empty columns before the token.
- Ensure row contains `:` and AF; when checklist row omits AF (like `vert_b_3rows`), append `:,...`.

4. Use explicit column-placement overrides for ambiguous checklist shorthand rows.
- Apply row-specific absolute column hints for:
- `wire_c_only`
- `wire_a_and_e`
- `vert_b_only`
- `vert_b_with_horiz`
- `corner_b`
- `vert_d_only`
- `vert_b_3rows`
- `no_c_only`
- `no_a_no_c`
- `no_ae_only`
- `no_p_only`
- This guarantees requested transformations like:
- `no_c_only`: `...,X001,...,:,...` -> `R,,,X001,...,:,...`
- `vert_b_3rows`:  
  `R,,|,...,:,...`  
  `,,|,...,:,...`  
  `,,|,...,:,...`

5. Handle labels not present in the two checklist files.
- Exact labels:
- `nc_a_immediate_only`
- `no_a_immediate_only`
- `no_c_immediate_only`
- `pasteback_vert_b_with_horiz`
- For these four entries:
- `description = ""`
- `rung_rows = []`
- `metadata_todo = true`

6. Compute boolean fields.
- `verified = false` for all entries.
- `codec_generatable` uses structural equivalence semantics:
- Attempt `decode(fixture_bytes)` with `ClickCodec`.
- Re-encode decoded rung.
- Set true only if both:
- `header_structural_equal(generated, fixture)` is true
- `parse_wire_topology(generated) == parse_wire_topology(fixture)`
- Any decode/encode failure => `codec_generatable = false`.

7. Update parser behavior for token policy.
- In `csv_token_parser.parse_condition_token`:
- accept `|`
- remove `+` special-case parsing path.

8. Update tests.
- `tests/ladder/test_capture_fixtures.py`:
- Validate new schema fields/types on every entry.
- Validate `metadata_todo` contract:
- exact TODO label set above is `true`
- all other entries have non-empty `description` and non-empty `rung_rows`
- Validate `rung_rows` parse with `normalize_shorthand_row`.
- Validate marker rule (`R` on first row only).
- Add regression assertions for the two required normalization examples (`no_c_only`, `vert_b_3rows`).
- `tests/ladder/test_csv_token_parser.py`:
- Add condition-token tests:
- `|` parses as vertical token class
- `+` falls back to generic token class (rejected for structured vertical semantics).

9. Validation commands to run.
- `uv run python devtools/update_ladder_capture_manifest.py`
- `uv run pytest tests/ladder/test_capture_fixtures.py tests/ladder/test_csv_token_parser.py tests/ladder/test_csv_parser.py tests/ladder/test_csv_shorthand.py`

## Test Cases and Scenarios
1. Manifest integrity:
- fixture file set still exactly matches `.bin` files in directory.
- `source` remains `scratchpad/captures`.

2. Canonical row format:
- every stored row is valid shorthand row syntax (`marker,...,:,af`).
- no stored row contains `+`, `t`, or `r`.
- `|` is accepted token.

3. Required user-specified normalization:
- `no_c_only` starts at column C with explicit leading blanks.
- `vert_b_3rows` has exactly 3 rows with markers `R`, `""`, `""`, and includes `:,...` on each row.

4. TODO handling:
- exactly 4 entries have `metadata_todo=true` and empty description/rows.

5. Codec-generatable semantics:
- flag true only when generated payload is structurally equivalent to fixture by header+topology checks.

## Assumptions and Defaults
- Current pass scope is manifest/schema/parser/test updates only (no TUI implementation).
- Manifest update is script-driven (not manual one-off).
- Instruction-native descriptions use `instruction-matrix.json` `scenario` text.
- `verified` starts false for all fixtures to support future manual verification pass.
- Canonical wire token set is `T`, `-`, `|`; `+` is intentionally removed.
