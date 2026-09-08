"""Disposable-copy investigation, not a production sidecar or pytest suite."""
from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'tests/SC_.mdb'
HOST = Path(os.environ['SystemRoot']) / 'SysWOW64/WindowsPowerShell/v1.0/powershell.exe'
SCRIPT = (HERE / 'sidecar.ps1').read_text(encoding='utf-8')
FLAGS = subprocess.CREATE_NO_WINDOW
REPORT: dict = {'python_bits': struct.calcsize('P') * 8, 'source': str(SOURCE), 'checks': {}}


class Sidecar:
    def __init__(self, policy=None):
        self.started = time.perf_counter()
        argv = [str(HOST), '-NoLogo', '-NoProfile', '-NonInteractive']
        if policy:
            argv += ['-ExecutionPolicy', policy]
        argv += ['-EncodedCommand', base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                     creationflags=FLAGS, bufsize=1)
        self.lines = queue.Queue()
        self.errors = []
        self.serial = 0
        def read_stdout():
            for line in self.proc.stdout:
                self.lines.put(line)
            self.lines.put(None)
        def read_stderr():
            self.errors.extend(self.proc.stderr)
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

    def call(self, op, *, expect_error=False, **kwargs):
        self.serial += 1
        self.proc.stdin.write(json.dumps(dict(id=self.serial, op=op, **kwargs), ensure_ascii=False) + '\n')
        self.proc.stdin.flush()
        try:
            line = self.lines.get(timeout=15)
        except queue.Empty:
            self.proc.kill()
            raise RuntimeError(f'Sidecar timeout: {op}; stderr={self.errors}')
        if line is None:
            raise RuntimeError(f'Sidecar exited: {self.proc.poll()}; stderr={self.errors}')
        result = json.loads(line)
        assert result['id'] == self.serial, result
        if expect_error:
            assert not result['ok'], result
            return result['error']
        assert result['ok'], result
        return result['result']

    def stop(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        assert self.proc.returncode == 0, self.errors


def param(kind, value):
    return dict(type=kind, value=value)


def statement(sql, *parameters):
    return dict(op='execute', sql=sql, parameters=list(parameters))


def check(name, detail=True):
    REPORT['checks'][name] = detail
    print(name + ': PASS', flush=True)


class ConnectionAdapter:
    """Only the DB-API subset used by ClickNick; no production retry semantics."""
    def __init__(self, sidecar):
        self.sidecar = sidecar
        self.transaction = False

    def cursor(self):
        return CursorAdapter(self)

    def commit(self):
        if self.transaction:
            self.sidecar.call('commit')
            self.transaction = False

    def rollback(self):
        if self.transaction:
            self.sidecar.call('rollback')
            self.transaction = False

    def close(self):
        self.rollback()


class CursorAdapter:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, parameters=()):
        encoded = [param('Boolean' if isinstance(v,bool) else 'Integer' if isinstance(v,int) else 'LongVarWChar',v) for v in parameters]
        is_query = sql.lstrip().upper().startswith('SELECT')
        if not is_query and not self.connection.transaction:
            self.connection.sidecar.call('begin')
            self.connection.transaction = True
        result = self.connection.sidecar.call('query' if is_query else 'execute',sql=sql,parameters=encoded)
        self.rows = [tuple(row) for row in result.get('rows',[])]
        return self

    def executemany(self, sql, parameters):
        for values in parameters:
            self.execute(sql,values)

    def fetchall(self):
        rows,self.rows = self.rows,[]
        return rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.rows = []


def existing_api_probe(sidecar, db):
    from clicknick.utils import mdb_operations
    original_factory = mdb_operations.create_access_connection
    mdb_operations.create_access_connection = lambda path: ConnectionAdapter(sidecar)
    try:
        with mdb_operations.MdbConnection(str(db)) as connection:
            original = mdb_operations.load_all_addresses(connection)
            first = next(iter(original.values()))
            assert mdb_operations.save_changes(connection,[replace(first,nickname='SIDECAR_TEST')]) == 1
            assert mdb_operations.load_all_addresses(connection)[first.addr_key].nickname == 'SIDECAR_TEST'
            assert mdb_operations.save_changes(connection,[first]) == 1
        provision = mdb_operations.ensure_addresses_exist(str(db),['C1999'])
        assert provision['requested_count'] == 1
        with mdb_operations.MdbConnection(str(db)) as connection:
            rows = mdb_operations.load_all_addresses(connection)
            provisioned = [row for key,row in rows.items() if key not in original]
            # Exercise the existing deletion path, not just a direct DELETE command.
            if provisioned:
                mdb_operations.save_changes(connection,[replace(row,nickname='',comment='',initial_value='',used=False) for row in provisioned])
            assert mdb_operations.load_all_addresses(connection) == original
        check('unmodified_clicknick_load_save_provision_delete_through_adapter',provision)
    finally:
        mdb_operations.create_access_connection = original_factory


def policy_probe():
    path = HERE / 'policy_probe.ps1'
    path.write_text("Write-Output 'POLICY_OK'\n", encoding='ascii')
    records = {}
    for policy in ['Restricted', 'AllSigned', 'RemoteSigned']:
        for mode in ['file', 'inline']:
            suffix = ['-File', str(path)] if mode == 'file' else ['-EncodedCommand', base64.b64encode(path.read_text().encode('utf-16-le')).decode()]
            run = subprocess.run([str(HOST), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', policy, *suffix],
                                 capture_output=True, text=True, creationflags=FLAGS, timeout=15)
            records[f'{policy}/{mode}'] = {'exit': run.returncode, 'ran': 'POLICY_OK' in run.stdout}
    constrained = "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; New-Object System.Data.OleDb.OleDbConnection"
    run = subprocess.run([str(HOST), '-NoProfile', '-NonInteractive', '-EncodedCommand', base64.b64encode(constrained.encode('utf-16-le')).decode()],
                         capture_output=True, text=True, creationflags=FLAGS, timeout=15)
    records['simulated_constrained_language'] = {'exit': run.returncode, 'blocked': 'CannotCreateTypeConstrainedLanguage' in run.stderr}
    REPORT['policy_tests'] = records
    assert records['Restricted/file']['ran'] is False
    assert records['AllSigned/file']['ran'] is False
    assert records['Restricted/inline']['ran'] is True
    assert records['AllSigned/inline']['ran'] is True
    assert records['simulated_constrained_language']['blocked']
    check('execution_policy_matrix', records)


def main():
    import pyodbc
    initial_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    work = Path(tempfile.mkdtemp(prefix='jet-powershell-research-'))
    db = work / 'probe file.mdb'
    shutil.copy2(SOURCE, db)
    REPORT['copy'] = str(db)
    sidecars = []
    try:
        a = Sidecar()
        sidecars.append(a)
        hello = a.call('hello')
        REPORT['host'] = hello
        REPORT['startup_seconds'] = round(time.perf_counter() - a.started, 3)
        assert hello['bits'] == 32, hello
        check('x64_python_to_x86_powershell_under_current_policy', hello)
        REPORT['provider'] = a.call('open', path=str(db))
        REPORT['loaded_modules'] = a.call('modules')
        assert not any('aceoledb' in p.lower() for p in REPORT['loaded_modules']['paths'])
        schema = a.call('schema', collection='Columns')['rows']
        REPORT['schema'] = schema
        REPORT['tables'] = a.call('schema', collection='Tables')['rows']
        storage_sql = 'SELECT [Id],[Lv] FROM [MSysAccessStorage] ORDER BY [Id]'
        storage_before = a.call('query',sql=storage_sql)['rows']
        sql = 'SELECT AddrKey, MemoryType, Address, Nickname, Comment, Use, DataType, InitialValue, Retentive FROM address ORDER BY AddrKey'
        start = time.perf_counter()
        baseline = a.call('query', sql=sql)
        REPORT['read_seconds'] = round(time.perf_counter() - start, 3)
        REPORT['row_count'] = len(baseline['rows'])
        REPORT['address_columns'] = baseline['columns']
        ace = pyodbc.connect(f'DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db};', autocommit=True)
        try:
            reference = [list(row) for row in ace.cursor().execute(sql).fetchall()]
            assert baseline['rows'] == reference
        finally:
            ace.close()
        check('all_original_address_rows_equal_existing_x64_pyodbc', len(reference))
        assert a.call('query', sql='SELECT [AddrKey] FROM [address] WHERE [AddrKey]=-1')['rows'] == []
        assert a.call('query', sql='SELECT COUNT(*) FROM [address]')['rows'] == [[len(reference)]]
        check('empty_and_single_row_json_shapes')

        key = 2000000000
        text = "O'Brien; pump cafe\r\nline\t\\\"test"
        long_text = text * 300
        insert = statement('INSERT INTO [address] ([AddrKey],[MemoryType],[Address],[DataType],[Nickname],[Comment],[InitialValue],[Retentive]) VALUES (?,?,?,?,?,?,?,?)',
                           param('Integer',key),param('LongVarWChar','C'),param('LongVarWChar','999'),param('Integer',0),
                           param('LongVarWChar',text),param('LongVarWChar',long_text),param('LongVarWChar','0000123'),param('Boolean',True))
        a.call('batch', statements=[insert])
        query = dict(sql='SELECT [Nickname],[Comment],[InitialValue],[Retentive],[Use] FROM [address] WHERE [AddrKey]=?',parameters=[param('Integer',key)])
        row = a.call('query', **query)['rows'][0]
        assert row[:4] == [text,long_text,'0000123',True], row
        check('insert_english_apostrophe_newlines_memo_bool_initial_value', {'comment_characters':len(long_text),'default_use':row[4]})
        update = statement('UPDATE [address] SET [Nickname]=?,[Comment]=?,[InitialValue]=?,[Retentive]=? WHERE [AddrKey]=?',
                           param('LongVarWChar',''),param('LongVarWChar',None),param('LongVarWChar','-3.4028235E+38'),param('Boolean',False),param('Integer',key))
        a.call('begin')
        a.call(**update)
        assert a.call('query',**query)['rows'][0][:4] == ['',None,'-3.4028235E+38',False]
        a.call('rollback')
        assert a.call('query',**query)['rows'][0][:4] == [text,long_text,'0000123',True]
        check('empty_string_null_false_and_explicit_rollback')
        error = a.call('batch', statements=[update,insert], expect_error=True)
        assert a.call('query',**query)['rows'][0][:4] == [text,long_text,'0000123',True]
        check('duplicate_key_error_rolls_back_entire_batch',error)
        a.call('close')
        a.call('open',path=str(db))
        assert a.call('query',**query)['rows'][0][0] == text
        check('committed_write_survives_reopen')

        b = Sidecar()
        sidecars.append(b)
        b.call('open',path=str(db))
        a.call('begin')
        a.call(**update)
        lock_start = time.perf_counter()
        conflict = b.call('execute', sql='UPDATE [address] SET [Nickname]=? WHERE [AddrKey]=?',
                          parameters=[param('LongVarWChar','conflict'),param('Integer',key)],expect_error=True)
        lock_seconds = time.perf_counter() - lock_start
        a.call('rollback')
        check('second_process_write_lock_reports_error',dict(error=conflict,elapsed_seconds=round(lock_seconds,3)))
        b.call('batch',statements=[update])
        # Jet has a local page cache; measure visibility rather than assume immediate refresh.
        visibility_start = time.perf_counter()
        while a.call('query',**query)['rows'][0][0] != '':
            assert time.perf_counter()-visibility_start < 5
            time.sleep(.05)
        check('cross_process_commit_visible',round(time.perf_counter()-visibility_start,3))
        b.call('close')
        a.call('batch',statements=[statement('DELETE FROM [address] WHERE [AddrKey]=?',param('Integer',key))])
        assert a.call('query',sql=sql)['rows'] == baseline['rows']
        check('delete_and_original_rows_restored')

        a.call('execute',sql='CREATE TABLE [SidecarProbe] ([K] INTEGER PRIMARY KEY,[Payload] LONGBINARY,[Price] CURRENCY,[AtTime] DATETIME,[Measure] DOUBLE)')
        blob = bytes(range(256))*300
        a.call('batch',statements=[statement('INSERT INTO [SidecarProbe] VALUES (?,?,?,?,?)',param('Integer',1),
                    param('LongVarBinary',base64.b64encode(blob).decode()),param('Currency','123456789.1234'),
                    param('DBTimeStamp','2026-09-08T12:34:56'),param('Double',1.23456789012345))])
        typed = a.call('query',sql='SELECT * FROM [SidecarProbe]')['rows'][0]
        assert base64.b64decode(typed[1]['base64']) == blob
        assert typed[2] == {'kind':'decimal','value':'123456789.1234'}
        assert typed[3]['value'].startswith('2026-09-08T12:34:56')
        assert typed[4] == 1.23456789012345
        check('synthetic_blob_currency_datetime_double_roundtrip',{'blob_bytes':len(blob)})
        existing_api_probe(a,db)
        assert a.call('query',sql=storage_sql)['rows'] == storage_before
        check('existing_access_storage_blobs_unchanged',len(storage_before))
        # EOF must release an unfinished transaction and the database lock.
        a.call('begin')
        a.call('execute',sql='UPDATE [address] SET [Nickname]=? WHERE [AddrKey]=?',
               parameters=[param('LongVarWChar','EOF_ROLLBACK'),param('Integer',baseline['rows'][0][0])])
        a.stop()
        b.call('open',path=str(db))
        assert b.call('query',sql=sql)['rows'] == baseline['rows']
        b.call('close')
        check('stdin_eof_rolls_back_uncommitted_write')
        policy_probe()
    finally:
        for sidecar in sidecars:
            sidecar.stop()
        REPORT['source_unchanged'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest() == initial_hash
        REPORT['stderr'] = [s.errors for s in sidecars]
        (HERE/'latest-results.json').write_text(json.dumps(REPORT,indent=2,ensure_ascii=False),encoding='utf-8')
        assert REPORT['source_unchanged']


if __name__ == '__main__':
    main()
