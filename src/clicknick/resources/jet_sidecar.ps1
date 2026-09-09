# ClickNick's x86 Jet worker. Keep stdout exclusively for JSON responses.
# Console.WriteLine is deliberate: it emits raw UTF-8 lines with an explicit flush,
# bypassing host formatting, which is what a line-oriented JSON protocol needs.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '')]
param()
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
Add-Type -AssemblyName System.Data
$columns = '[AddrKey],[MemoryType],[Address],[Nickname],[Comment],[Use],[DataType],[InitialValue],[Retentive]'

function New-DbCommand {
    # Builds an in-process command object; it changes no system state, so ShouldProcess does not apply.
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '')]
    param(
        [Parameter(Mandatory)] [System.Data.OleDb.OleDbConnection] $Connection,
        [AllowNull()] [System.Data.OleDb.OleDbTransaction] $Transaction,
        [Parameter(Mandatory)] [string] $Sql,
        [AllowNull()] [AllowEmptyCollection()] [object[]] $Values = @(),
        [AllowEmptyCollection()] [string[]] $Types = @()
    )
    $command = $Connection.CreateCommand()
    $command.CommandText = $Sql
    $command.CommandTimeout = 5
    if ($null -ne $Transaction) { $command.Transaction = $Transaction }
    for ($i = 0; $i -lt $Values.Count; $i++) {
        $parameter = $command.CreateParameter()
        $parameter.OleDbType = [System.Data.OleDb.OleDbType]$Types[$i]
        if ($null -eq $Values[$i]) { $parameter.Value = [DBNull]::Value }
        else { $parameter.Value = $Values[$i] }
        [void]$command.Parameters.Add($parameter)
    }
    return $command
}

function Set-DbParameter {
    # Assigns values to an existing command's parameters; no system state changes here either.
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '')]
    param(
        [Parameter(Mandatory)] [System.Data.OleDb.OleDbCommand] $Command,
        [Parameter(Mandatory)] [AllowNull()] [AllowEmptyCollection()] [object[]] $Values
    )
    for ($i = 0; $i -lt $Values.Count; $i++) {
        if ($null -eq $Values[$i]) { $Command.Parameters[$i].Value = [DBNull]::Value }
        else { $Command.Parameters[$i].Value = $Values[$i] }
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
                    $command = New-DbCommand -Connection $connection -Transaction $null -Sql $sql
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
                    break
                }
                'save' {
                    $transaction = $connection.BeginTransaction()
                    $commands = @()
                    try {
                        $delete = New-DbCommand -Connection $connection -Transaction $transaction `
                            -Sql 'DELETE FROM [address] WHERE [AddrKey]=?' `
                            -Values @($null) -Types @('Integer')
                        $commands += $delete
                        $exists = New-DbCommand -Connection $connection -Transaction $transaction `
                            -Sql 'SELECT COUNT(*) FROM [address] WHERE [AddrKey]=?' `
                            -Values @($null) -Types @('Integer')
                        $commands += $exists
                        $update = New-DbCommand -Connection $connection -Transaction $transaction `
                            -Sql 'UPDATE [address] SET [Nickname]=?,[Comment]=?,[InitialValue]=?,[Retentive]=? WHERE [AddrKey]=?' `
                            -Values @($null, $null, $null, $null, $null) `
                            -Types @('LongVarWChar', 'LongVarWChar', 'LongVarWChar', 'Boolean', 'Integer')
                        $commands += $update
                        $insert = New-DbCommand -Connection $connection -Transaction $transaction `
                            -Sql 'INSERT INTO [address] ([AddrKey],[MemoryType],[Address],[DataType],[Nickname],[Comment],[InitialValue],[Retentive]) VALUES (?,?,?,?,?,?,?,?)' `
                            -Values @($null, $null, $null, $null, $null, $null, $null, $null) `
                            -Types @('Integer', 'LongVarWChar', 'LongVarWChar', 'Integer', 'LongVarWChar', 'LongVarWChar', 'LongVarWChar', 'Boolean')
                        $commands += $insert
                        foreach ($key in $request.deletes) {
                            Set-DbParameter -Command $delete -Values @($key)
                            [void]$delete.ExecuteNonQuery()
                        }
                        foreach ($row in $request.upserts) {
                            Set-DbParameter -Command $exists -Values @($row[0])
                            if ($exists.ExecuteScalar() -gt 0) {
                                Set-DbParameter -Command $update -Values @($row[4], $row[5], $row[6], $row[7], $row[0])
                                [void]$update.ExecuteNonQuery()
                            } else {
                                Set-DbParameter -Command $insert -Values $row
                                [void]$insert.ExecuteNonQuery()
                            }
                        }
                        $transaction.Commit()
                        $result = @{ count = $request.deletes.Count + $request.upserts.Count }
                    } catch {
                        # Rollback throws if the transaction already completed or the connection
                        # broke. Report it on stderr so the original Jet error still reaches the user.
                        try { $transaction.Rollback() }
                        catch { [Console]::Error.WriteLine('Rollback failed: ' + $_.Exception.Message) }
                        throw
                    } finally {
                        foreach ($command in $commands) { $command.Dispose() }
                        $transaction.Dispose()
                    }
                    break
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
