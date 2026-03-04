# Random AND-Series Test Batches (2026-03-04)

Purpose:

- Manual Click pasteback stress testing with randomized contiguous AND-series rows.
- Current Click-safe encoder envelope is `1..2` contiguous contacts.

Seed:

- `20260304` (reproducible batch content)

## Batch A (`random_and_batch_a_20260304`)

Labels:

- `rand_and_a_01`
- `rand_and_a_02`
- `rand_and_a_03`
- `rand_and_a_04`
- `rand_and_a_05`
- `rand_and_a_06`
- `rand_and_a_07`
- `rand_and_a_08`
- `rand_and_a_09`
- `rand_and_a_10`

## Batch B (`random_and_batch_b_20260304`)

Labels:

- `rand_and_b_01`
- `rand_and_b_02`
- `rand_and_b_03`
- `rand_and_b_04`
- `rand_and_b_05`
- `rand_and_b_06`
- `rand_and_b_07`
- `rand_and_b_08`
- `rand_and_b_09`
- `rand_and_b_10`

## Quick Run Commands

One label at a time (interactive verify workflow):

```powershell
uv run clicknick-ladder-capture verify run --label rand_and_a_01
```

Show all random labels currently in manifest:

```powershell
uv run clicknick-ladder-capture entry list --type synthetic --json
```

Record crash/non-copied outcomes non-interactively (example):

```powershell
uv run clicknick-ladder-capture verify complete --label rand_and_a_01 --status blocked --clipboard-event crash --note "Click crash after paste"
```

## Notes

- `random_and_batch_a_20260304` and `random_and_batch_b_20260304` are now treated as exploratory/unsafe because `>2` contact payloads currently crash Click.
- Click-safe replacement batches were added under scenario `random_and_batch_two_series_20260304`:
  - `rand_and_2s_a_01` .. `rand_and_2s_a_10`
  - `rand_and_2s_b_01` .. `rand_and_2s_b_10`
- Sparse-valid X-address replacement batches were added under scenario `random_and_batch_two_series_sparse_x_20260304`:
  - `rand_and_2s_sparse_a_01` .. `rand_and_2s_sparse_a_10`
  - `rand_and_2s_sparse_b_01` .. `rand_and_2s_sparse_b_10`
- Sparse-valid X/Y ranges used:
  - `1-16`
  - `21-32`
  - `101-116`
  - `201-216`
  - `301-316`
  - `401-416`
  - `501-516`
  - `601-616`
  - `701-716`
  - `801-816`
- All replacement rows were pre-validated through encode/decode roundtrip using the same shorthand normalization path as the capture workflow.

## Sparse X Failure Triage (2026-03-04)

Scenario investigated: `random_and_batch_two_series_sparse_x_20260304`

Completed verify rows at pause:

- `rand_and_2s_sparse_a_01`: `verified_pass`
- `rand_and_2s_sparse_a_02`: `verified_fail` (`Only pasted X002.immediate`)
- `rand_and_2s_sparse_a_03`: `verified_fail` (`Only pasted X512.immediate`)
- `rand_and_2s_sparse_a_04`: `verified_fail` (`Has a RED outlined box where the ~X113 should be`)
- `rand_and_2s_sparse_a_05`: `cancelled`

Binary observations from copied-back captures:

- `a_02` and `a_03` back-captures contain only one valid instruction type marker (`0x2711` at `0x0A99`); second contact + coil markers are absent.
- `a_04` back-capture contains an `Err` contact block (UTF-16 `Err`) at the second-contact location with contact type `0x2712` but no decodable operand; coil remains present.
- The outgoing generated payloads for all three failing labels *did* contain the expected second-contact and coil markers before paste, so divergence happens during Click paste/normalize.

Current root-cause candidates:

1. Two-series family modeling is still incomplete for some variants (`first immediate`, `both immediate`, `NO -> NC`) outside the currently hardened second-immediate path.
2. Some sparse X addresses may still be invalid in the active Click project/module configuration even though they are globally valid in the nominal sparse ranges.

Discriminating re-test set (recommended next pass):

- Low-address controls for the same variants:
  - `X001.immediate,X002.immediate,->,:,out(Y001)`
  - `X001.immediate,X002,->,:,out(Y001)`
  - `X001,~X002,->,:,out(Y001)`
- High-address no-immediate control:
  - `X413,X314,->,:,out(Y001)`

Decision rule:

- If low-address controls fail similarly: prioritize encoder variant-byte fixes.
- If low-address controls pass but high-address controls fail: prioritize project-specific address-validity filtering for random batches.
