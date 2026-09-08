# Historical Jet feasibility report

These findings describe the initial prototype. For the implemented backend, current tests, and remaining validation, see [README.md](README.md).

**Conclusion: built-in x86 Windows PowerShell is a viable zero-install Jet sidecar for ClickNick on ordinary Windows x64 desktops.** The exact System.Data.OleDb approach passed the local investigation. Production should detect capability at runtime; this is not a guarantee for every managed or customized Windows image.

Investigation date: 2026-09-08. Scope: English-language ClickNick usage. These are research artifacts, not an integrated or production-ready backend.

**What was actually verified**

The parent was 64-bit Python. The child was `%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe`, Windows PowerShell 5.1.26100.9168, using full-framework System.Data.OleDb and Microsoft.Jet.OLEDB.4.0. The local Windows build is 26200.9168, version 25H2 (Windows 11). The registry's historical ProductName string says Windows 10 Pro; it should not be used alone to identify this OS.

All database mutations used a disposable copy of `tests/SC_.mdb`. The source SHA-256 remained unchanged. The current fixture has 408 address rows. No CLICK process or live temporary MDB was present during this investigation. Earlier work in this conversation read/wrote a copy of the then-running CLICK 3.71 MDB using ADO COM; this investigation separately tests the requested .NET OleDb implementation.

`make probe` passed all checks recorded in [results.json](results.json):

- Every original address value equals the result from ClickNick's existing 64-bit pyodbc/ACE backend.
- Insert, update, delete, explicit commit, close/reopen persistence, explicit rollback, and rollback of a batch after a duplicate-key error.
- English strings with apostrophes, quotes, tabs, backslashes, newlines, and a 9,300-character memo; empty string distinct from NULL; true and false booleans; initial values preserved as strings.
- Two independent PowerShell processes sharing one MDB. A conflicting write returned Jet error 3218 (`Could not update; currently locked.`); a later committed update became visible to the other process.
- 76,800 bytes of synthetic binary data, exact Currency/Decimal, DateTime, and Double round trips.
- The 23 existing MSysAccessStorage rows, including their binary payloads, remained unchanged after address operations.
- Closing stdin during an open transaction rolled back the uncommitted address update.
- ClickNick's existing `MdbConnection`, `load_all_addresses`, `save_changes`, and `ensure_addresses_exist` ran unchanged through a small Python connection/cursor adapter. Provisioning inserted C1999, and the existing deletion path removed it again.
- Empty query results remain `[]`; a single row/column remains a nested row array. All responses were JSON lines; successful runs emitted no stderr diagnostics.

64-bit ACE was used only as an independent reference reader in the test harness. The sidecar itself loaded System.Data, oledb32, msjetoledb40, and msjet40, with no ACE provider loaded. It needs neither pyodbc nor Python in the child process. It does not call CLICK DLLs.

**Windows 10/11 and provider availability**

Microsoft documents that Windows PowerShell 5.1 is preinstalled on Windows client 10 and higher, and explicitly confirms that Windows 11 contains the 32-bit PowerShell host. Its Desktop edition runs on .NET Framework. [PowerShell 5.1](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_windows_powershell_5.1?view=powershell-5.1), [32-bit host on Windows x64](https://learn.microsoft.com/en-us/powershell/scripting/learn/ps101/01-getting-started?view=powershell-7.5).

Microsoft documents Jet as 32-bit and usable under WOW64. [Jet architecture](https://learn.microsoft.com/en-us/sql/connect/connect-history?view=sql-server-ver17).

On this Windows 11 machine, the 32-bit Jet COM registration points to `C:\Windows\SysWOW64\msjetoledb40.dll`. The Windows component store also contains x86 Jet core manifests. The running sidecar successfully opens the MDB through that registered provider. Earlier static inspection of CLICK 3.92's TagDB.dll found the same `Provider=Microsoft.Jet.OLEDB.4.0` connection string, and the running CLICK 3.71 process loaded Jet system modules.

Inference: a Windows system on which these CLICK versions successfully perform MDB operations already has the required Jet capability. Merely having CLICK installed or its launcher opening is weaker evidence. Different process identities, application-control rules, damaged registration, or future CLICK versions can invalidate the inference.

This is strong evidence for the zero-install design, but not an empirical clean-image Windows 10 test. No Windows 10 VM or clean Windows installation without Office/ACE was tested. The local sidecar's provider selection and loaded modules show independence from ACE, not a full clean-image certification. A release claim should retain a startup/open capability probe.

**Launch and script packaging**

Recommended launch from Python, using an argument list with `shell=False`, redirected pipes, and CREATE_NO_WINDOW:

```text
%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe
    -NoLogo -NoProfile -NonInteractive -EncodedCommand <static-script-base64>
```

Store the maintained source as a bundled `.ps1` package resource. Python reads that trusted resource and passes its UTF-16LE/Base64 representation as the command. This keeps PowerShell out of a large escaped Python string while avoiding dependence on executing a script file under the default client policy. Request data, SQL parameters, and database paths travel through JSON stdin, not string interpolation into PowerShell source. Do not use `-Command -` for this protocol: that makes stdin the PowerShell command stream.

The prototype source is about 7.5 KB; its encoded command fits the Windows process command-line limit. Keep that limit in mind if the worker grows. EncodedCommand is quoting/transport, not encryption or a way around application-control policy. [powershell.exe arguments](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1).

The local policy was Restricted, with no MachinePolicy/UserPolicy set. The complete sidecar worked without `-ExecutionPolicy Bypass` or any persistent policy changes. Separate child-process probes produced:

| Process execution policy | Unsigned local `-File` | Inline `-EncodedCommand` |
|---|---|---|
| Restricted | Blocked | Worked |
| AllSigned | Blocked | Worked |
| RemoteSigned | Worked | Worked |

NonInteractive prevents prompts; it does not override policy. RemoteSigned behavior also depends on download-zone marking. Process execution-policy settings cannot override Group Policy. These tests used process policy flags, not an actual domain policy deployment. [Execution policies](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-7.6).

Application control is the harder boundary. A child placed in ConstrainedLanguage rejected OleDbConnection construction in the test. WDAC/AppLocker can constrain PowerShell or prevent launch; an enterprise may require an approved script or another permitted backend. A signed Microsoft powershell.exe does not automatically make arbitrary hosted code trusted. Do not attempt to relax or evade those controls. [Language modes and application control](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_language_modes?view=powershell-7.5).

**Data and locking details**

The actual Address schema exposes AddrKey as Int32, DataType as Byte, Use/Retentive as Boolean, and Address/MemoryType/Nickname/Comment/InitialValue as strings (long text). InitialValue must stay text: leading zeros and formatted numeric values matter. Its meaning depends on the separate DataType field.

Use positional `?` parameters in their SQL order and set OleDbType explicitly, especially for NULL, long text, binary values, and booleans. Use `[DBNull]::Value` for database NULL and normalize it back to JSON null. Avoid implicit AddWithValue inference. Bracket SQL identifiers such as `[Use]`. GetSchema works, but provider metadata differs from pyodbc: for example, long text may expose a maximum length of zero, not a usable field-size limit. [OleDb parameters](https://learn.microsoft.com/en-us/dotnet/api/system.data.oledb.oledbparameter).

Use explicit UTF-8 input/output encodings even for English text. ConvertTo-Json needs an explicit sufficient depth and stable arrays; do not serialize raw DataTables or DBNull objects. Reserve stdout for the protocol and drain stderr separately. Encode binary values as base64; transmit exact decimals and dates using tagged strings. The sidecar transports raw OLE/blob bytes; it does not interpret embedded Access objects.

An exploratory non-English filesystem path was rejected by Jet before the English-only scope was requested. English paths with spaces passed. Non-English Windows usernames and paths remain outside the verified scope; successful Unicode field storage would not by itself prove Unicode filename support.

Use shared access and ordinary Jet transactions. The prototype used `Mode=Share Deny None;OLE DB Services=-2` to avoid keeping pooled database connections alive after disposal. Keep transactions short, dispose readers/commands, and close the database between logical operations when possible while retaining the PowerShell process. The MDB directory must allow Jet's adjacent lock-file operations. Jet can lock pages and cache data across connections; successful IPC does not remove those database semantics. [Jet locking/cache properties](https://learn.microsoft.com/en-us/office/client-developer/access/desktop-database-reference/microsoft-ole-db-provider-for-microsoft-jet), [OLE DB pooling configuration](https://learn.microsoft.com/en-us/dotnet/api/system.data.oledb.oledbconnectionstringbuilder.oledbservices).

The observed lock-conflict response took about 2.3 seconds; the test is not a guarantee that CommandTimeout bounds every provider operation. Python must impose its own deadline and handle child exit. If the worker disappears after commit but before acknowledgement, the write outcome is unknown: do not blindly replay the batch. Re-read and reconcile. Closing the Python pipe normally is covered by the EOF rollback test; forced process termination/power loss was not tested.

**Automatic fallback behind ClickNick's API**

Yes. The existing application-level API can stay intact. The research adapter demonstrates the smaller cursor API also works, but one IPC round trip per execute/fetch will be inefficient for large saves. A production implementation should batch a complete load/save/provision transaction in one request, sharing the Python normalization and validation logic above the transport.

Suggested selection: retain working native x64 ODBC; when its Access driver is unavailable, start/probe the x86 Jet backend, then open the requested MDB. Report a clear backend error if neither works. Do not switch backends on arbitrary SQL, permission, corruption, or lock errors, and never switch in the middle of a write transaction.

Update `has_access_driver()` and the five app.py connection gates to check usable database capability. The About/status and ODBC warning dialogs also need to recognize the PowerShell backend. Updating only `create_access_connection()` would leave the current UI rejecting otherwise usable connections.

Keep the child alive, serialize access to its pipes, use request IDs, and do startup off the UI thread. The final measured startup was 3.864 seconds; reading all 408 original rows took 0.139 seconds after startup. These are prototype timings on this machine, not tuned benchmarks.

**Remaining release validation**

- Run this probe on clean Windows 10 x64 and Windows 11 x64 systems without ACE/Office.
- Exercise CLICK 3.92 while simultaneously editing, saving, closing, reopening, and switching projects; the current tests use two independent Jet clients rather than CLICK itself.
- Test process crashes, cancelled requests, pipe limits, large real projects, and representative enterprise application-control policies.

The research can be reproduced with `make probe` from this directory. It uses the existing ClickNick Python environment, pyodbc/ACE only for comparison, and copies the fixture into a new temporary directory. See [sidecar.ps1](sidecar.ps1) and [probe.py](probe.py). ClickNick production source was not modified during this initial investigation.
