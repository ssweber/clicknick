# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Fixed

- Importing a nickname CSV no longer fails outright with `cannot assign to field 'nickname'`.
- Unchecking a block in the import dialog now actually excludes it — previously a tagged block sitting between untagged rows was imported anyway, under the wrong block's merge options.
- Rows no longer show as **Changed** with no visible edit, and are no longer rewritten to the database on save, when a value is written back unchanged (re-typing the same text, or importing a CSV that already matches the project).
- Editing a value back to its original now clears the row's **Changed** marker instead of leaving it flagged.
- A blank initial value and `0` now count as the same default on numeric addresses, so importing a Click CSV export no longer marks every numeric address changed; TXT still treats `0` as real content.
- A CSV that reuses a block name no longer has one block's import options clobber another's.

### Changed

- The import dialog's **Init Val** and **Retentive** columns are now a single **First Scan** column: the two are imported together, so importing a retentive setting can no longer silently shadow an initial value the program relies on.

## 2026-02-13

### Changed
- Restored local ownership of `export_cdv`, `get_dataview_folder`, and `list_cdv_files` in `clicknick.views.dataview_editor.cdv_file`.
- Added canonical `read_mdb_csv()` in `clicknick.data.data_source` returning `dict[int, AddressRow]`.

### Compatibility
- Kept `load_addresses_from_mdb_dump()` as a backward-compatible alias to `read_mdb_csv()`.
