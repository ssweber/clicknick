# Grid AF NOP Patch Isolation Verify Queue (March 6, 2026)

Scenario: `grid_af_nop_patch_isolation_20260306`  
Case count: `17`  
Payload source mode: `file`

## Why This Batch
- Prove minimal decisive bytes for AF NOP placement, including non-first-row rows.
- Distinguish sufficiency/necessity for candidate offsets: target row `col31 +0x1D`, target row `col0 +0x15`, and row0 `col0 +0x15` clear.
- Use verified native captures as donor truth and replay from empty baselines.

## Cases
1. `gafnp01r0_hright_only` - rows1 synthetic: set row0 col31 +0x1D only
2. `gafnp09r0_hright_only` - rows9 synthetic: set row0 col31 +0x1D only
3. `gafnp02r1_full_griddiff` - rows2 row1 NOP: full 3-byte grid diff control
4. `gafnp02r1_hright_only` - rows2 row1 NOP: set row1 col31 +0x1D only
5. `gafnp02r1_hright_target15` - rows2 row1 NOP: set row1 +0x15 and row1 col31 +0x1D
6. `gafnp02r1_hright_target15_clearrow0` - rows2 row1 NOP: set row1 +0x15/+0x1D and clear row0 +0x15
7. `gafnp02r1_target15_only` - rows2 row1 NOP: set row1 +0x15 only
8. `gafnp02r1_target15_clearrow0` - rows2 row1 NOP: set row1 +0x15 and clear row0 +0x15
9. `gafnp02r1_clearrow0_only` - rows2 row1 NOP: clear row0 +0x15 only
10. `gafnp09r4_full_griddiff` - rows9 row4 NOP: full 3-byte grid diff control
11. `gafnp09r4_hright_only` - rows9 row4 NOP: set row4 col31 +0x1D only
12. `gafnp09r4_hright_target15` - rows9 row4 NOP: set row4 +0x15 and row4 col31 +0x1D
13. `gafnp09r4_hright_target15_clearrow0` - rows9 row4 NOP: set row4 +0x15/+0x1D and clear row0 +0x15
14. `gafnp09r8_full_griddiff` - rows9 row8 NOP: full 3-byte grid diff control
15. `gafnp09r8_hright_only` - rows9 row8 NOP: set row8 col31 +0x1D only
16. `gafnp09r8_hright_target15` - rows9 row8 NOP: set row8 +0x15 and row8 col31 +0x1D
17. `gafnp09r8_hright_target15_clearrow0` - rows9 row8 NOP: set row8 +0x15/+0x1D and clear row0 +0x15

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_af_nop_patch_isolation_20260306`

For copied events:
- paste in Click
- copy back in Click
- press `c`

## Verify Discipline
- Record `status`, `event`, and `clipboard_len` for each case.
- If observed rows diverge from expected, enter exact observed rows.
- Add a short note for ambiguous/operator-limitation cases.

Send `done` when complete.
