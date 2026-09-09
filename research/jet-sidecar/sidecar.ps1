# Research prototype: JSON-lines over pipes; SQL is supplied by the local test client.
# Production should expose bounded operations and enforce request size/time limits.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
Add-Type -AssemblyName System.Data
$connection = $null
$transaction = $null

function Convert-Cell($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return $null }
    if ($value -is [byte[]]) { return @{ kind = 'bytes'; base64 = [Convert]::ToBase64String($value) } }
    if ($value -is [datetime]) { return @{ kind = 'datetime'; value = $value.ToString('o') } }
    if ($value -is [decimal]) { return @{ kind = 'decimal'; value = $value.ToString([Globalization.CultureInfo]::InvariantCulture) } }
    if ($value -is [guid]) { return @{ kind = 'guid'; value = $value.ToString() } }
    return $value
}

function New-Command($request) {
    $command = $connection.CreateCommand()
    $command.CommandText = [string]$request.sql
    $command.CommandTimeout = 3
    if ($null -ne $transaction) { $command.Transaction = $transaction }
    foreach ($spec in $request.parameters) {
        $parameter = $command.CreateParameter()
        $parameter.OleDbType = [Enum]::Parse([System.Data.OleDb.OleDbType], $spec.type)
        if ($null -ne $spec.size) { $parameter.Size = [int]$spec.size }
        if ($null -eq $spec.value) { $parameter.Value = [DBNull]::Value }
        elseif ($spec.type -in @('Binary', 'VarBinary', 'LongVarBinary')) { $parameter.Value = [Convert]::FromBase64String($spec.value) }
        elseif ($spec.type -in @('Date', 'DBDate', 'DBTimeStamp')) { $parameter.Value = [datetime]::Parse($spec.value, [Globalization.CultureInfo]::InvariantCulture) }
        elseif ($spec.type -in @('Currency', 'Decimal', 'Numeric')) { $parameter.Value = [decimal]::Parse($spec.value, [Globalization.CultureInfo]::InvariantCulture) }
        else { $parameter.Value = $spec.value }
        [void]$command.Parameters.Add($parameter)
    }
    return $command
}

function Invoke-Statement($request) {
    $command = New-Command $request
    try {
        if ($request.op -eq 'execute') { return @{ affected = $command.ExecuteNonQuery() } }
        $reader = $command.ExecuteReader()
        try {
            $columns = @()
            for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                $columns += @{ name = $reader.GetName($i); type = $reader.GetFieldType($i).FullName; provider_type = $reader.GetDataTypeName($i) }
            }
            $rows = New-Object 'System.Collections.Generic.List[object]'
            while ($reader.Read()) {
                $row = New-Object object[] $reader.FieldCount
                for ($i = 0; $i -lt $reader.FieldCount; $i++) { $row[$i] = Convert-Cell ($reader.GetValue($i)) }
                $rows.Add($row)
            }
            return @{ columns = $columns; rows = $rows.ToArray() }
        } finally { $reader.Dispose() }
    } finally { $command.Dispose() }
}

try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        $request = $null
        try {
            $request = ConvertFrom-Json -InputObject $line
            $result = switch ($request.op) {
                'hello' {
                    @{ bits = [IntPtr]::Size * 8; powershell = $PSVersionTable.PSVersion.ToString(); language = $ExecutionContext.SessionState.LanguageMode.ToString(); policy = (Get-ExecutionPolicy).ToString(); dotnet = [Environment]::Version.ToString() }
                }
                'open' {
                    if ($null -ne $connection) { throw 'Connection already open' }
                    $builder = New-Object System.Data.OleDb.OleDbConnectionStringBuilder
                    $builder['Provider'] = 'Microsoft.Jet.OLEDB.4.0'
                    $builder['Data Source'] = [string]$request.path
                    $builder['Mode'] = 'Share Deny None'
                    $builder['OLE DB Services'] = -2
                    $connection = New-Object System.Data.OleDb.OleDbConnection($builder.ConnectionString)
                    $connection.Open()
                    @{ provider = $connection.Provider; version = $connection.ServerVersion }
                }
                'query' { Invoke-Statement $request }
                'execute' { Invoke-Statement $request }
                'schema' {
                    $table = $connection.GetSchema([string]$request.collection)
                    $rows = New-Object 'System.Collections.Generic.List[object]'
                    foreach ($row in $table.Rows) {
                        $entry = @{}
                        foreach ($column in $table.Columns) { $entry[$column.ColumnName] = Convert-Cell ($row[$column.ColumnName]) }
                        $rows.Add($entry)
                    }
                    @{ rows = $rows.ToArray() }
                }
                'begin' { $transaction = $connection.BeginTransaction(); @{ started = $true } }
                'commit' { $transaction.Commit(); $transaction.Dispose(); $transaction = $null; @{ committed = $true } }
                'rollback' { $transaction.Rollback(); $transaction.Dispose(); $transaction = $null; @{ rolled_back = $true } }
                'batch' {
                    if ($null -ne $transaction) { throw 'Batch cannot nest inside a transaction' }
                    $transaction = $connection.BeginTransaction()
                    try {
                        $results = @()
                        foreach ($statement in $request.statements) { $results += Invoke-Statement $statement }
                        $transaction.Commit()
                        @{ results = $results }
                    } catch {
                        $transaction.Rollback()
                        throw
                    } finally { $transaction.Dispose(); $transaction = $null }
                }
                'modules' {
                    @{ paths = @((Get-Process -Id $PID).Modules | Where-Object { $_.ModuleName -match 'jet|ace|oledb|System.Data' } | ForEach-Object { $_.FileName }) }
                }
                'close' {
                    if ($null -ne $transaction) { $transaction.Rollback(); $transaction.Dispose(); $transaction = $null }
                    if ($null -ne $connection) { $connection.Dispose(); $connection = $null }
                    @{ closed = $true }
                }
                default { throw 'Unknown operation' }
            }
            $response = @{ id = $request.id; ok = $true; result = $result }
        } catch {
            $exception = $_.Exception
            while ($null -ne $exception.InnerException) { $exception = $exception.InnerException }
            $errors = @()
            if ($exception -is [System.Data.OleDb.OleDbException]) {
                $errors = @($exception.Errors | ForEach-Object { @{ native = $_.NativeError; state = $_.SQLState; message = $_.Message } })
            }
            $response = @{ id = $request.id; ok = $false; error = @{ type = $exception.GetType().FullName; message = $exception.Message; details = $errors } }
        }
        [Console]::WriteLine((ConvertTo-Json -InputObject $response -Depth 20 -Compress))
        [Console]::Out.Flush()
    }
} finally {
    if ($null -ne $transaction) { $transaction.Rollback(); $transaction.Dispose() }
    if ($null -ne $connection) { $connection.Dispose() }
}
