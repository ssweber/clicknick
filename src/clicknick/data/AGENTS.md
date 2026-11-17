# The address store, Sync and undo

These notes cover `AddressStore` (`data/address_store.py`), its edit sessions, Sync, undo and block
colors. Read the seven rules in the root `AGENTS.md` first. Rules 1 to 5 are about this store. The store's
tests are listed in `tests/AGENTS.md`.

## The three layers

The store keeps three layers:

1. The base layer (`base_state`) is the latest snapshot from the external database. It is the source of
   truth.
2. The overlay layer (`user_overrides`) holds the unsaved edits. It maps each `addr_key` to a read-only
   `{field: value}` that holds only the fields that the user set. It holds no copies of rows and no dirty
   markers.
3. The visible layer (`visible_state`) is the base with the overrides applied. The store computes it.

The base rows and the user's overrides are the inputs. One method, `AddressStore._derive()`, computes
everything else. That is the visible rows, validation, the dirty fields, the nickname index and the block
colors. It computes them in one fixed order after every change. A change is an edit, an undo, a redo, a
Discard, a save or an external reload.

When the database refreshes, the store updates the base layer and keeps the user's overrides.

## Dirty state

To check for unsaved edits, call `store.is_dirty(addr_key)` or `store.is_field_dirty(addr_key, "nickname")`.
`_derive` first drops each override field that the base already holds. So a field is dirty exactly when it
is in its row's override.

## Edit sessions

1. Code opens an edit session with `AddressStore.edit_session(description)`. Views open most sessions. Some
   services open their own (`nickname_staging`, `comment_upgrade_service`, `system_nickname_service`). So do
   `live/dispatch.py`, `live/tag_commands.py` and the store's own Trim spaces session. A service such as
   `row_service` or `import_service` receives the session from its caller.
2. Whoever holds the session writes each change with `session.set_field(addr_key, field, value)`. The
   session keeps one `MutableRowBuilder` per row. All the changes in one session make one undo frame. Filling
   down 500 rows is one undo step.
3. When the session exits cleanly, the store applies the cascades and freezes the builders into overrides.
   It stores a nickname or comment without a space at either end (`trim_entry`). CLICK stores them the same
   way. If the overrides changed, the store pushes an undo frame that holds the overrides from before, and it
   clears redo. Then it runs `_derive()` and notifies the observers. A session that changes nothing is not
   an undo step.
4. If the session exits with an exception, the store commits nothing. If the commit itself fails,
   `_commit_session` restores the overrides and the undo and redo stacks, derives again from them, and
   raises the error again.
5. Every view receives the changed `addr_keys` and refreshes only those rows.

## Cascades

`AddressStore._apply_cascades` runs the cascades when a session commits.

- A Retentive change mirrors across the T/TD or CT/CTD pair.
- A row's block tag can change. The store judges that by the old tag against the new tag, not by the
  comment text. Then `_apply_cascades` updates the matching open or close tag and the `_D` tags of the pairs.
  `BlockService.matching_tag_comment` and `BlockService.pair_tag_comment` return the new comments, and
  `_apply_cascades` writes them. They rename the tags in place or remove them. If the pair has no tag and the
  tag was added or renamed, they append one to the pair.
- When a tag's colour or kind changes, `pair_tag_comment` gives the pair's tag the new colour or kind too.
  `matching_tag_comment` leaves the matching open or close tag as it is.
- `_apply_cascades` records which fields the caller set before any cascade runs. A cascade never writes one
  of those fields.

## Observers

Call `add_observer(callback)` to listen to the store. The store calls `callback(store, changed_keys)`, where
`changed_keys` (`set[int] | None`) holds the affected `addr_key`s. Before it notifies, the store replaces the
changed rows in the shared unified view. The store logs any exception that an observer raises.

## Sync

`save_all_changes` writes the edits. With no edits it returns at once. It raises when the data source is
read-only. When there are edits and any row has a reportable validation error, it writes nothing and raises
`RuntimeError`. This holds for every caller. For the database, it first reads SC_.mdb, because CLICK writes
that file while it is connected. So the rows that it writes hold CLICK's current values in the fields that the
user did not change.

CLICK's ladder paints nicknames from a table that TagDB.dll keeps in memory. CLICK shows the names from a
Sync only after that table reloads, and no window message reloads it. `services/click_redraw.py` forces the
reload. It imports a header-only CSV through CLICK's File > Import > Nickname (WM_COMMAND 32900, CLICK
2.60-4.00) in Merge (Project priority) mode. The import leaves SC_.mdb as it was, but CLICK then counts the
project as changed. The redraw starts only while CLICK shows its main window alone, enabled and answering. It
presses only the mode's radio button, Open and the one button of the "Completed!" box. It recognises the
import's Open dialog by its three import modes and its control ids, never by Windows' own strings. If the
redraw fails while that dialog is the only other window open, it cancels the dialog. It leaves any other
window to the user, including an Open dialog that it did not recognise. The tests drive it through a fake
`ClickDesktop`. The redraw works after a Sync on CLICK 2.60, 3.43, 3.71, 3.92 and 4.00. `save_all_changes`
calls the store's sync listeners (`add_sync_listener`) once it has written rows into the database. Every Sync
path goes through `save_all_changes`: the Address Editor's Sync and Sync and Close, and Yes to a save prompt.
The app's listener runs the redraw for the connected window off the Tk thread
(`ConnectionController.redraw_nicknames`). If a redraw is asked for while one runs, the request waits and runs
once, after that redraw ends. Tools > Redraw Nicknames in CLICK works the same way. A redraw's result and a
waiting request belong to the CLICK window (its hwnd). If another window is connected, or none, ClickNick drops
them. A skipped or failed redraw shows as a status line and never fails the Sync.

## Nicknames loaded with an error

`loaded_with_error` marks an X, SC or SD nickname from CLICK that breaks ClickNick's nickname rules. The store
still validates the nickname. While the visible row has the flag, ClickNick reports none of that row's
validation errors (`AddressRow.should_ignore_validation_error`, `has_reportable_error`). One helper,
`_flag_loaded_error`, sets the flag on every base row, on load, reload and Sync alike.

## Trim spaces

One edit session, "Trim spaces" (`_stage_trims`), trims a loaded nickname or comment that has a space at either
end. It covers the rows that a load or a read of the data source changed. The file monitor and Sync's
pre-read both read the data source. It also covers every row after a Discard.

- Sync writes the trim.
- An undone trim comes back only when the data source changes that row.
- The session leaves a field that the user edits as it is.
- It trims a nickname flagged `loaded_with_error` too. Once the row shows the trimmed nickname, the flag is
  off. `_validate_row` then skips only the format check for it, so its duplicates are reported
  (`_is_trimmed_loaded_nickname`).
- No SC or SD name in pyclickplc's table has a space at either end. CLICK generates the X `_IO` names. No
  table lists them, so nothing shows that they have no space at either end.
- Rows that the store reads while a session is open wait until that session ends (`_pending_trims`).

## Undo and redo

- Undo and Redo track only the overlay layer, which is the user's intent. They keep up to `MAX_UNDO_DEPTH`
  (50) frames.
- A successful Sync or Save, or a Discard, clears Undo and Redo, because the frames hold override snapshots
  and not old values. A CLICK save does not clear them.
- When the database comes to match an unsaved field, that field stops being an edit (`_rebase_override`,
  which `_derive` runs).

## Block colors

- The store keeps block colors in `AddressStore.block_colors`, not in `AddressRow`. They are not part of undo
  and redo. Read one with `store.get_block_color(addr_key)`, which returns a color name or None.
- `compute_block_colors` is the one implementation that derives them from the comments (block tags).
- When two blocks share a name, the first definition in address order is valid. ClickNick flags the later
  ones.
