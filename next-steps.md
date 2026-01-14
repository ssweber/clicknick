# Refactoring Progress: Unidirectional Data Flow Architecture

## Completed Refactoring
---

## Remaining Refactoring Items

### High Priority (Reduces complexity in Views)

| File | Current State | Target Refactoring | Effort |
| :--- | :--- | :--- | :--- |
| **panel.py** | `_on_sheet_modified` contains column-to-field mapping and BIT "1"/"0" conversion logic. | Move to `AddressRow.set_field_value(col, raw_value)` or a **FieldMapper** service. View passes raw data, model handles normalization. | Medium |
| **window.py** | `_on_rename` uses `panel.sheet.regex_replace_all_direct` which modifies display first. | Create **RenameService** that modifies `AddressRow` objects directly within `edit_session`. UI updates via observer. | Medium |

### Medium Priority (Improves testability)

| File | Current State | Target Refactoring | Effort |
| :--- | :--- | :--- | :--- |
| **panel.py** | `_build_row_display_data` knows how to format all columns (Used, Init Value masking, Retentive pairing). | Move to a **RowPresenter** or **DisplayBuilder** service. Panel just calls `presenter.format_row(row)`. | Medium |
| **panel.py** | `_apply_filters` builds `_displayed_rows` list with complex logic. | Extract to **FilterService.apply_filters(rows, filter_text, row_filter)** returning indices. | Medium |

### Lower Priority (Nice to have)

| File | Current State | Target Refactoring | Effort |
| :--- | :--- | :--- | :--- |
| **window.py** | `_on_fill_down_clicked` and `_on_clone_structure_clicked` ask user about incrementing initial values (duplicate pattern). | Extract to helper or make RowService accept a flag from UI. Already partially done. | Easy |

---

## Architecture Observations

1. **Model Locking:** `AddressRow` correctly raises `RuntimeError` if modified outside `edit_session`.
2. **Passive Views:** `AddressPanel` is mostly passive but still knows too much about display formatting.
3. **Service Purity:** `RowService` now handles pre-validation. `window.py` is thinner but still formats block tags inline.

---

## Suggested Next Steps

2. **Medium win:** Create RenameService to replace `regex_replace_all_direct` pattern
3. **Bigger refactor:** Simplify `_on_sheet_modified` by moving normalization to model
