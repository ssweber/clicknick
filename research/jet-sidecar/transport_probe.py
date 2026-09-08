"""Exercise long JSON lines through the built-in x86 host, without a database."""
import base64
import json
import os
from pathlib import Path
import subprocess

script = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
while ($null -ne ($line = [Console]::ReadLine())) {
    $request = ConvertFrom-Json -InputObject $line
    [Console]::WriteLine((ConvertTo-Json -InputObject @{id=$request.id; payload=$request.payload} -Depth 20 -Compress))
    [Console]::Out.Flush()
}
'''
sizes = [1024, 65536, 1048576, 4194304]
requests = [dict(id=i, payload='A'*size) for i, size in enumerate(sizes)]
wire = ''.join(json.dumps(request,separators=(',',':'))+'\n' for request in requests)
host = Path(os.environ['SystemRoot'])/'SysWOW64/WindowsPowerShell/v1.0/powershell.exe'
run = subprocess.run([str(host),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',
                      base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
                     input=wire,text=True,encoding='utf-8',capture_output=True,
                     creationflags=subprocess.CREATE_NO_WINDOW,timeout=60)
assert run.returncode == 0, run.stderr
responses = [json.loads(line) for line in run.stdout.splitlines()]
assert responses == requests
assert not run.stderr, run.stderr
for size in sizes:
    print(f'JSON line round trip with {size} payload characters: PASS')
Path(__file__).with_name('transport_results.json').write_text(
    json.dumps(dict(payload_sizes=sizes,all_passed=True,policy_override=False),indent=2),encoding='ascii')
