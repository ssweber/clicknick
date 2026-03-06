# Grid RungComment Patch Companion Isolation Verify Queue (March 6, 2026)

Scenario: grid_rungcomment_patch_companion_isolation_20260306
Case count: 16
Payload source mode: file

## Why This Batch
- Phase 2 gate is still open after prior patch isolation (3 pass, 2 fail, 7 crash).
- Prior failures clustered on style transplants and max1400 replay.
- This batch isolates companion bytes beyond immediate payload end (0x030E..0x08FC).
- Design includes controls, full-window transplants, split-tail probes, and tail-only probes.

## Cases (inspect comment text/style in Click)
1. grcp2c_short_lpp_control_from_no - short plain control: copy len+payload only (0x0294-0x030D) from short donor onto no-comment baseline [ranges: 0x0294-0x030D] (expect comment='A1', style='plain'; focus: reconfirm short control baseline)
2. grcp2c_short_tail_only_030e_08fc_from_no - short plain tail-only: copy post-payload companion window (0x030E-0x08FC) from short donor [ranges: 0x030E-0x08FC] (expect comment='(probe)', style='plain'; focus: test whether tail alone has effect or destabilizes)
3. grcp2c_short_full_0294_08fc_from_no - short plain full window: copy 0x0294-0x08FC from short donor onto no-comment baseline [ranges: 0x0294-0x08FC] (expect comment='A1', style='plain'; focus: control for full companion window transplant)
4. grcp2c_bold_lpp_control_from_plain - bold control: copy len+payload only (0x0294-0x031C) from bold donor onto plain baseline [ranges: 0x0294-0x031C] (expect comment='STYLE_PROBE', style='bold'; focus: reproduce prior crash control)
5. grcp2c_bold_full_0294_08fc_from_plain - bold full window: copy 0x0294-0x08FC from bold donor onto plain baseline [ranges: 0x0294-0x08FC] (expect comment='STYLE_PROBE', style='bold'; focus: test if full companion window restores stable style replay)
6. grcp2c_bold_lpp_plus_tail_031d_03ff_from_plain - bold split-tail A: len+payload plus near tail (0x031D-0x03FF) [ranges: 0x0294-0x031C, 0x031D-0x03FF] (expect comment='STYLE_PROBE', style='bold'; focus: isolate near-tail companion contribution)
7. grcp2c_bold_lpp_plus_tail_0400_08fc_from_plain - bold split-tail B: len+payload plus far tail (0x0400-0x08FC) [ranges: 0x0294-0x031C, 0x0400-0x08FC] (expect comment='STYLE_PROBE', style='bold'; focus: isolate far-tail companion contribution)
8. grcp2c_bold_lpp_plus_tail_031d_05ff_from_plain - bold split-tail C: len+payload plus mid tail (0x031D-0x05FF) [ranges: 0x0294-0x031C, 0x031D-0x05FF] (expect comment='STYLE_PROBE', style='bold'; focus: narrow companion requirement lower-half)
9. grcp2c_bold_lpp_plus_tail_0600_08fc_from_plain - bold split-tail D: len+payload plus upper tail (0x0600-0x08FC) [ranges: 0x0294-0x031C, 0x0600-0x08FC] (expect comment='STYLE_PROBE', style='bold'; focus: narrow companion requirement upper-half)
10. grcp2c_italic_full_0294_08fc_from_plain - italic full window: copy 0x0294-0x08FC from italic donor onto plain baseline [ranges: 0x0294-0x08FC] (expect comment='STYLE_PROBE', style='italic'; focus: check if full-window transplant generalizes to italic)
11. grcp2c_underline_full_0294_08fc_from_plain - underline full window: copy 0x0294-0x08FC from underline donor onto plain baseline [ranges: 0x0294-0x08FC] (expect comment='STYLE_PROBE', style='underline'; focus: check if full-window transplant generalizes to underline)
12. grcp2c_max_lpp_control_from_no - max1400 control: copy len+payload only (0x0294-0x0883) from max donor onto no-comment baseline [ranges: 0x0294-0x0883] (expect comment='MAX1400_BODY', style='plain'; focus: reproduce prior max crash control)
13. grcp2c_max_full_0294_08fc_from_no - max1400 full window: copy 0x0294-0x08FC from max donor onto no-comment baseline [ranges: 0x0294-0x08FC] (expect comment='MAX1400_BODY', style='plain'; focus: test if max replay needs post-payload companions)
14. grcp2c_max_lpp_plus_tail_0884_08bc_from_no - max1400 split-tail A: len+payload plus first tail chunk (0x0884-0x08BC) [ranges: 0x0294-0x0883, 0x0884-0x08BC] (expect comment='MAX1400_BODY', style='plain'; focus: narrow max companion requirement lower-tail chunk)
15. grcp2c_max_lpp_plus_tail_08bd_08fc_from_no - max1400 split-tail B: len+payload plus second tail chunk (0x08BD-0x08FC) [ranges: 0x0294-0x0883, 0x08BD-0x08FC] (expect comment='MAX1400_BODY', style='plain'; focus: narrow max companion requirement upper-tail chunk)
16. grcp2c_max_tail_only_0884_08fc_from_no - max1400 tail-only: copy post-payload tail (0x0884-0x08FC) from max donor onto no-comment baseline [ranges: 0x0884-0x08FC] (expect comment='(probe)', style='plain'; focus: test if max tail alone perturbs baseline)

## Operator Run Path
1. uv run clicknick-ladder-capture tui
2. 3 (Verify run)
3. g (guided queue)
4. f (payload source override = file)
5. Scenario filter: grid_rungcomment_patch_companion_isolation_20260306

For copied events:
- paste in Click
- inspect displayed comment text/style and whether UI shows raw RTF tokens
- copy back in Click
- press c

For crash events:
- press crash path in guided flow
- include short note if a specific dialog/message appears (for example Out of Memory)

## Verify Discipline
- Keep notes concise and high-signal: raw RTF, style lost, OOM, comment empty, etc.
- Record clipboard_len for copied cases.
- Do not manually edit manifest entries.

Send done when complete.
