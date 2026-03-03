## Pre-Grid Candidate Ranking (2026-03-03)

- Region analyzed: `0x0000..0x0A5F`
- Failing target: `two_series_second_immediate` (`generated_v2` vs native)
- Working controls: `smoke_simple`, `smoke_immediate`, `smoke_two_series_short`

- Failing pre-grid mismatch count: `114`
- Unique-to-failing candidates (absent in controls): `4`

### Focus Offsets
- `0x006E`: generated=`0x00`, native=`0x61`
- `0x0072`: generated=`0x00`, native=`0x79`
- `0x0076`: generated=`0x00`, native=`0x65`
- `0x007E`: generated=`0x00`, native=`0x1E`
