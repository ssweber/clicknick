"""Disposable full-address-space benchmark for pre-commit review."""
import os
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from clicknick.models.address_row import AddressRow
from clicknick.utils import jet_sidecar, mdb_operations
from pyclickplc.banks import BANKS

os.environ.setdefault('CLICKNICK_DB_BACKEND', 'jet')
jet_sidecar.SAVE_TIMEOUT = float(os.environ.get('BENCH_JET_SAVE_TIMEOUT', str(jet_sidecar.SAVE_TIMEOUT)))
print('backend', os.environ['CLICKNICK_DB_BACKEND'], 'save_timeout', jet_sidecar.SAVE_TIMEOUT, flush=True)
rows = []
for name, bank in BANKS.items():
    ranges = bank.valid_ranges or ((bank.min_addr, bank.max_addr),)
    addresses = [a for lo, hi in ranges for a in range(lo, hi + 1)]
    if name in {'XD', 'YD'}:
        addresses = [0, 1, *range(2, 17, 2)]
    for address in addresses:
        rows.append(AddressRow(memory_type=name, address=address, nickname=f'BENCH_{name}_{address}', comment='C' * 128, data_type=int(bank.data_type)))

with tempfile.TemporaryDirectory(prefix='clicknick-review-bulk-') as directory:
    path = Path(directory) / 'SC_.mdb'
    shutil.copy2(Path(__file__).resolve().parents[2] / 'tests/SC_.mdb', path)
    try:
        with mdb_operations.MdbConnection(str(path)) as connection:
            for label, batch in [('insert', rows), ('update', [replace(row, comment='U' * 128) for row in rows])]:
                start = time.monotonic()
                try:
                    count = mdb_operations.save_changes(connection, batch)
                    print(label, count, round(time.monotonic()-start, 3), flush=True)
                except Exception as exc:
                    print(label, type(exc).__name__, str(exc), round(time.monotonic()-start, 3), flush=True)
                    break
            start = time.monotonic()
            loaded = mdb_operations.load_all_addresses(connection)
            print('read', len(loaded), round(time.monotonic()-start, 3), flush=True)
    finally:
        jet_sidecar._worker.close()
