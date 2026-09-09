# Jet sidecar research

Maintainer notes from the 2026-09-08 investigation. User setup guidance is in
[connection help](../../docs/help/index.md#database-connection).

## Implemented backend

ClickNick keeps native Access ODBC as the first choice and can use built-in x86
Windows PowerShell with Jet 4.0 when the driver is unavailable. The production
worker is [jet_sidecar.ps1](../../src/clicknick/resources/jet_sidecar.ps1), with
[Python transport](../../src/clicknick/utils/jet_sidecar.py) and
[regression tests](../../tests/test_jet_sidecar.py).

Each operation opens and closes its own MDB connection. A save uses one
transaction with reused parameterized commands. Startup/reads have a 30-second
deadline; saves have 180 seconds. An interrupted save is never replayed
automatically because its commit outcome may be unknown. Initial backend
selection and store loading run off the UI thread. The existing synchronous
Save action can still pause the UI during large batches.

The JSON limits are 8 MiB per request and 32 MiB per response. The 4 MiB result
below is a tested transport size, not a protocol limit.

## Evidence

- [Historical findings](FINDINGS.md) contain source references, schema details,
  execution-policy results, locking behavior, and caveats.
- [Initial results](results.json) record the prototype checks on a disposable copy
  of the 408-row CLICK fixture, including comparison with native ACE.
- [Transport results](transport_results.json) record successful single-line JSON
  round trips up to 4 MiB.
- The production suite tests all 13,340 valid address slots through insert,
  update, delete, and rollback after an error at the end of a batch. It also
  tests a registered but unloadable ODBC driver, stale connection results,
  parameter reuse with nulls/variable-length text, and timeout handling.

Before the fixes, the full-sheet Jet insert took about 48 seconds and exceeded
its former 30-second deadline. The corrected full-sheet regression completed
all operations in about 79 seconds total on the development machine. These are
local observations, not performance guarantees.

## Reproduce

Run normal production checks from the repository root with `make test`.
See [development setup](../../development.md#working-with-local-pyrung) if working
with paired local dependency checkouts.

The standalone probes use the repository's `.venv` and disposable MDB copies:

```powershell
make -C research/jet-sidecar probe
make -C research/jet-sidecar transport
make -C research/jet-sidecar benchmark
```

`probe.py` and `sidecar.ps1` are the original feasibility prototype, not the
shipping backend. A new probe run writes `latest-results.json`, preserving the
recorded initial results. The probe needs native Access ODBC as an independent reference
reader; production Jet does not. `benchmark.py` uses the production API and
honors `CLICKNICK_DB_BACKEND`, defaulting to `jet`. Set
`BENCH_JET_SAVE_TIMEOUT` only when deliberately measuring a different save deadline.

## Remaining checks

The local tests ran on Windows 11 x64. Clean Windows 10/11 machines without
Office/ACE, representative managed policies, and simultaneous editing in CLICK
still need broader validation. Jet registration, file permissions, and path
compatibility should not be inferred from successful PowerShell launch alone.

[Issue #17 replacement](issue-17-release-draft.md) is ready to publish with the
release that includes this backend.
