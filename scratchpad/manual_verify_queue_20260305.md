# Manual Verify Queue (2026-03-05)

Generated from `scratchpad/ladder_capture_manifest.json`.

## Native: Capture Missing Payload First

- `session_counter_crossapp_a_recopy_native`

```powershell
uv run clicknick-ladder-capture entry capture --label session_counter_crossapp_a_recopy_native
```

- `session_counter_crossuid_yes_a_recopy_native`

```powershell
uv run clicknick-ladder-capture entry capture --label session_counter_crossuid_yes_a_recopy_native
```

- `grid_empty_row1_single_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_row1_single_native
```

- `grid_empty_row2_duplicate_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_row2_duplicate_native
```

- `grid_empty_rows1_2_combined_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_rows1_2_combined_native
```

- `grid_wire_a_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_a_native
```

- `grid_wire_ab_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_ab_native
```

- `grid_wire_full_row_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_full_row_native
```

- `grid_empty_width_default_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_width_default_native
```

- `grid_empty_width_narrow_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_width_narrow_native
```

- `grid_empty_width_wide_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_width_wide_native
```

- `grid_wire_ab_width_default_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_ab_width_default_native
```

- `grid_wire_ab_width_narrow_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_ab_width_narrow_native
```

- `grid_wire_ab_width_wide_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_wire_ab_width_wide_native
```

- `grid_empty_crossapp_a_source_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_crossapp_a_source_native
```

- `grid_empty_crossapp_b_pasteback_native`

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_crossapp_b_pasteback_native
```

## Native: Verify Run Queue (`--source file`)

```powershell
uv run clicknick-ladder-capture verify run --label two_series_nc_no_native --source file
uv run clicknick-ladder-capture verify run --label no_first_nc_second_native --source file
uv run clicknick-ladder-capture verify run --label two_series_nc_nc_native --source file
uv run clicknick-ladder-capture verify run --label nc_first_imm_no_second_native --source file
uv run clicknick-ladder-capture verify run --label no_first_nc_second_imm_native --source file
uv run clicknick-ladder-capture verify run --label nc_first_imm_nc_second_imm_native --source file
uv run clicknick-ladder-capture verify run --label c_first_no_second_native --source file
uv run clicknick-ladder-capture verify run --label no_first_c_second_native --source file
uv run clicknick-ladder-capture verify run --label no_first_rise_second_native --source file
uv run clicknick-ladder-capture verify run --label no_first_fall_second_native --source file
uv run clicknick-ladder-capture verify run --label rise_first_rise_second_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_row1_single_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_row2_duplicate_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_rows1_2_combined_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_mono_01_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_mono_02_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_mono_03_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_crossapp_a_source_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_crossapp_b_pasteback_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_crossapp_a_recopy_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_crossuid_yes_a_source_native --source file
uv run clicknick-ladder-capture verify run --label session_counter_crossuid_yes_a_recopy_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_row1_single_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_row2_duplicate_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_rows1_2_combined_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_a_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_ab_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_full_row_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_width_default_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_width_narrow_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_width_wide_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_ab_width_default_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_ab_width_narrow_native --source file
uv run clicknick-ladder-capture verify run --label grid_wire_ab_width_wide_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_crossapp_a_source_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_crossapp_b_pasteback_native --source file
```

## Synthetic: Verify Run Queue

```powershell
uv run clicknick-ladder-capture verify run --label two_series_harden_03_no_imm
uv run clicknick-ladder-capture verify run --label two_series_harden_04_imm_imm
uv run clicknick-ladder-capture verify run --label two_series_harden_05_no_nc
uv run clicknick-ladder-capture verify run --label two_series_harden_06_nc_no
uv run clicknick-ladder-capture verify run --label two_series_harden_07_sparse_no_no
uv run clicknick-ladder-capture verify run --label two_series_harden_08_sparse_imm_imm
uv run clicknick-ladder-capture verify run --label two_series_harden_09_sparse_no_nc
```

## Verify Note Tags (Grid Basics)

- ``[width=default|narrow|wide]``
- ``[window=A|B]``
- ``[context=row1|row2|rows1_2|crossapp]``

## Counts

- native_unverified: 36
- native_missing_payload: 16
- synthetic_unverified: 7
