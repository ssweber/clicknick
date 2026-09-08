# ClickNick's x86 Jet worker. Keep stdout exclusively for JSON responses.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
Add-Type -AssemblyName System.Data
$columns = '[AddrKey],[MemoryType],[Address],[Nickname],[Comment],[Use],[DataType],[InitialValue],[Retentive]'

function New-DbCommand($connection, $transaction, $sql, $values, $types) {
    $command = $connection.CreateCommand()
    $command.CommandText = $sql
    $command.CommandTimeout = 5
    if ($null -ne $transaction) { $command.Transaction = $transaction }
    for ($i = 0; $i -lt $values.Count; $i++) {
        $parameter = $command.CreateParameter()
        $parameter.OleDbType = [Enum]::Parse([System.Data.OleDb.OleDbType], $types[$i])
        if ($null -eq $values[$i]) { $parameter.Value = [DBNull]::Value }
        else { $parameter.Value = $values[$i] }
        [void]$command.Parameters.Add($parameter)
    }
    return $command
}

function Set-DbValues($command, $values) {
    for ($i = 0; $i -lt $values.Count; $i++) {
        if ($null -eq $values[$i]) { $command.Parameters[$i].Value = [DBNull]::Value }
        else { $command.Parameters[$i].Value = $values[$i] }
    }
}

while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $null
    $connection = $null
    try {
        if ($line.Length -gt 8388608) { throw 'Database request is too large.' }
        $request = ConvertFrom-Json -InputObject $line
        if ($request.op -eq 'hello') {
            if ([IntPtr]::Size -ne 4) { throw 'Jet requires 32-bit Windows PowerShell.' }
            if ($null -eq [Type]::GetTypeFromProgID('Microsoft.Jet.OLEDB.4.0')) {
                throw 'Microsoft Jet OLE DB 4.0 is not registered.'
            }
            $result = @{ bits = 32; version = 1 }
        } else {
            $builder = New-Object System.Data.OleDb.OleDbConnectionStringBuilder
            $builder['Provider'] = 'Microsoft.Jet.OLEDB.4.0'
            $builder['Data Source'] = [string]$request.path
            $builder['Mode'] = 'Share Deny None'
            $builder['OLE DB Services'] = -2
            $connection = New-Object System.Data.OleDb.OleDbConnection($builder.ConnectionString)
            $connection.Open()
            switch ($request.op) {
                { $_ -in @('probe', 'read') } {
                    $sql = 'SELECT ' + $columns + ' FROM [address] ORDER BY [AddrKey]'
                    if ($request.op -eq 'probe') { $sql = 'SELECT TOP 1 ' + $columns + ' FROM [address]' }
                    $command = New-DbCommand $connection $null $sql @() @()
                    try {
                        $reader = $command.ExecuteReader()
                        try {
                            $rows = New-Object 'System.Collections.Generic.List[object]'
                            while ($reader.Read()) {
                                $row = New-Object object[] $reader.FieldCount
                                for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                                    if (-not $reader.IsDBNull($i)) { $row[$i] = $reader.GetValue($i) }
                                }
                                $rows.Add($row)
                            }
                            $result = @{ rows = $rows.ToArray() }
                        } finally { $reader.Dispose() }
                    } finally { $command.Dispose() }
                }
                'save' {
                    $transaction = $connection.BeginTransaction()
                    $commands = @()
                    try {
                        $delete = New-DbCommand $connection $transaction 'DELETE FROM [address] WHERE [AddrKey]=?' @($null) @('Integer')
                        $commands += $delete
                        $exists = New-DbCommand $connection $transaction 'SELECT COUNT(*) FROM [address] WHERE [AddrKey]=?' @($null) @('Integer')
                        $commands += $exists
                        $update = New-DbCommand $connection $transaction 'UPDATE [address] SET [Nickname]=?,[Comment]=?,[InitialValue]=?,[Retentive]=? WHERE [AddrKey]=?' @($null,$null,$null,$null,$null) @('LongVarWChar','LongVarWChar','LongVarWChar','Boolean','Integer')
                        $commands += $update
                        $insert = New-DbCommand $connection $transaction 'INSERT INTO [address] ([AddrKey],[MemoryType],[Address],[DataType],[Nickname],[Comment],[InitialValue],[Retentive]) VALUES (?,?,?,?,?,?,?,?)' @($null,$null,$null,$null,$null,$null,$null,$null) @('Integer','LongVarWChar','LongVarWChar','Integer','LongVarWChar','LongVarWChar','LongVarWChar','Boolean')
                        $commands += $insert
                        foreach ($key in $request.deletes) {
                            Set-DbValues $delete @($key)
                            [void]$delete.ExecuteNonQuery()
                        }
                        foreach ($row in $request.upserts) {
                            Set-DbValues $exists @($row[0])
                            if ($exists.ExecuteScalar() -gt 0) {
                                Set-DbValues $update @($row[4],$row[5],$row[6],$row[7],$row[0])
                                [void]$update.ExecuteNonQuery()
                            } else {
                                Set-DbValues $insert $row
                                [void]$insert.ExecuteNonQuery()
                            }
                        }
                        $transaction.Commit()
                        $result = @{ count = $request.deletes.Count + $request.upserts.Count }
                    } catch {
                        $transaction.Rollback()
                        throw
                    } finally {
                        foreach ($command in $commands) { $command.Dispose() }
                        $transaction.Dispose()
                    }
                }
                default { throw 'Unknown database operation.' }
            }
        }
        $response = @{ id = $request.id; ok = $true; result = $result }
    } catch {
        $exception = $_.Exception
        while ($null -ne $exception.InnerException) { $exception = $exception.InnerException }
        $response = @{ id = $request.id; ok = $false; error = $exception.Message }
    } finally {
        if ($null -ne $connection) { $connection.Dispose() }
    }
    [Console]::WriteLine((ConvertTo-Json -InputObject $response -Depth 8 -Compress))
    [Console]::Out.Flush()
}
