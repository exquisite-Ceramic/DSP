# AutoCAD gRPC Real-Host Smoke Gate

This runbook is the real-host rollout gate for ADR-004 (`gRPC over loopback for AutoCAD IPC`).
It validates the opt-in gRPC transport against a supported AutoCAD installation before any
separate change switches the default transport away from Named Pipe.

Current default transport: Named Pipe
Opt-in migration transport: gRPC over loopback
Default-switch gate: docs/runbooks/autocad-grpc-smoke.md

A failed or unverified item below blocks the default switch. It does **not** require reverting
the dual-stack implementation. Named Pipe remains available during this migration phase.

## Supported validation environment

Record the exact environment used for each evidence run:

| Field | Value |
| --- | --- |
| Date/time | `<YYYY-MM-DD HH:MM TZ>` |
| Windows | `<version/build>` |
| AutoCAD | `AutoCAD 2025` |
| .NET SDK | `<dotnet --version>` |
| .NET runtimes | `<relevant dotnet --list-runtimes lines>` |
| Plugin branch/commit | `<git rev-parse HEAD>` |
| AutoCAD PID | `<pid>` |
| gRPC instance_id | `<guid>` |
| gRPC port | `<port>` |
| Contract version | `<version>` |

### AutoCAD 2025 ASP.NET Core host prerequisite

The in-process gRPC host uses ASP.NET Core/Kestrel. On the validated AutoCAD 2025 installation,
`C:\Program Files\Autodesk\AutoCAD 2025\acdbmgd.runtimeconfig.json` also needs to reference
`Microsoft.AspNetCore.App` 8.0 in `runtimeOptions.frameworks`, in addition to the existing
`Microsoft.NETCore.App` and `Microsoft.WindowsDesktop.App` entries. Back up the file before
changing it; an AutoCAD repair/update may replace it.

The machine must also have a compatible `Microsoft.AspNetCore.App` 8.x runtime installed.
Verify with:

```powershell
dotnet --list-runtimes | Select-String 'Microsoft.AspNetCore.App'
```

## Build and load

From the repository root:

```powershell
git checkout feat/grpc-loopback-transport
git pull --ff-only

$env:AUTOCAD_ACAD_DIR = 'C:\Program Files\Autodesk\AutoCAD 2025'
dotnet build .\hosts\autocad\plugin\AutoCAD.AgentHost\AutoCAD.AgentHost.csproj
```

Start AutoCAD 2025 and `NETLOAD`:

```text
hosts\autocad\plugin\AutoCAD.AgentHost\bin\Debug\net8.0-windows\AutoCAD.AgentHost.dll
```

`NETLOAD` must return without blocking the AutoCAD UI.

## Discovery setup

After load, wait briefly and inspect discovery:

```powershell
$discovery = Join-Path $env:LOCALAPPDATA 'EnterpriseDesignAgent\hosts'

Get-ChildItem $discovery -Filter *.json |
    Sort-Object LastWriteTime -Descending |
    Select-Object Name, LastWriteTime

$recordFile = Get-ChildItem $discovery -Filter *.json |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$record = Get-Content $recordFile.FullName -Raw | ConvertFrom-Json
$instance = $record.instance_id
$record | Select-Object instance_id, pid, host, port, transport, contract_version
```

Expected:

- `host == 127.0.0.1`
- `port > 0`
- `transport == grpc-h2c`
- the PID belongs to the loaded AutoCAD process
- the record appears only after the gRPC listener is usable

Do not paste or attach `auth_token` to reviews or logs. Record only whether authentication tests
passed.

## Python setup

The repository test client bootstraps repository source roots itself, so no manual `PYTHONPATH`
is required:

```powershell
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
```

For the sidecar module entry point, install the local packages first:

```powershell
python -m pip install -e .\contracts\python
python -m pip install -e .\hosts\autocad\sidecar
```

## Gate checklist

### 1. Plugin load and discovery publication

**Pass criteria:** AutoCAD remains responsive after `NETLOAD`; one discovery record for this
process appears; the recorded loopback endpoint accepts gRPC.

Evidence to record: AutoCAD PID, `instance_id`, port, contract version, and pass/fail.

### 2. Sidecar Ping/status with exact instance id

```powershell
python -m autocad_sidecar.main `
    --transport grpc `
    --instance-id $instance `
    status
```

**Pass criteria:** exit code 0 and status state `ready` or `busy`. This proves discovery, bearer
authentication, Ping/open, Dispatch, contract decoding, command routing, and native document
access for the selected instance.

### 3. CurrentDocument

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    document
```

**Pass criteria:** `status='OK'`, with the active AutoCAD document id/name and current revision.
Record the revision as `$revisionBefore` for later mutation checks.

### 4. CurrentSelection

Create/select a real entity in AutoCAD, then:

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    selection
```

**Pass criteria:** `status='OK'` and at least one real entity reference. Record one handle as
`$handle`.

Example PowerShell values for following steps:

```powershell
$handle = '<native handle from selection>'
$revisionBefore = <revision from document/selection>
```

### 5. MOVE once with revision and verification

Use a fixed idempotency key and the current revision:

```powershell
$key = [guid]::NewGuid().ToString()

python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    move --handle $handle --dx 1 --dy 0 `
    --revision $revisionBefore `
    --idempotency-key $key
```

**Pass criteria:**

- `status='OK'`
- `moved == 1`
- `verification.ok == True`
- `revision_after == revisionBefore + 1`
- the entity moved exactly once in AutoCAD

Record the returned position and `revision_after` as `$revisionAfter`.

### 6. Replay the same idempotency key without a second mutation

Run the exact same MOVE command again with the same `$key` and original revision:

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    move --handle $handle --dx 1 --dy 0 `
    --revision $revisionBefore `
    --idempotency-key $key
```

**Pass criteria:** the cached/replayed result is returned, `replayed=True`, revision does not
increment again, and the entity position does not change a second time.

### 7. Stale revision remains a DSP business error

Use a **new** idempotency key with the now-stale `$revisionBefore`:

```powershell
$staleKey = [guid]::NewGuid().ToString()

python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    move --handle $handle --dx 1 --dy 0 `
    --revision $revisionBefore `
    --idempotency-key $staleKey
```

**Pass criteria:** the RPC itself completes normally, the DSP result is `status='ERROR'`, and
`error.error_code == 'REVISION_CONFLICT'`. The entity must not move.

### 8. Short transport deadline returns DEADLINE_EXCEEDED safely

This gate exercises the gRPC transport deadline directly with a valid DSP read command and an
intentionally tiny timeout. It must not mutate AutoCAD state.

Run from the repository root after local packages are installed:

```powershell
@'
import asyncio
import uuid

import grpc

from autocad_sidecar.ipc.discovery import default_discovery_dir
from autocad_sidecar.ipc.grpc_transport import GrpcTransport
from autocad_sidecar.ipc.serializer import request_to_bytes
from host_contracts.command import HostCommand
from host_contracts.envelope import RequestEnvelope

INSTANCE = r"__INSTANCE__"

async def main():
    transport = GrpcTransport(INSTANCE, discovery_dir=default_discovery_dir())
    await transport.open()
    try:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            mode="READ",
            operation="context.current_document",
        )
        envelope = RequestEnvelope(
            request_id=str(uuid.uuid4()),
            payload=command.to_dict(),
        )
        try:
            await transport.exchange(request_to_bytes(envelope), timeout_s=1e-9)
        except grpc.aio.AioRpcError as exc:
            print(exc.code())
            if exc.code() != grpc.StatusCode.DEADLINE_EXCEEDED:
                raise
        else:
            raise RuntimeError("request unexpectedly completed before the tiny deadline")
    finally:
        await transport.close()

asyncio.run(main())
'@.Replace('__INSTANCE__', $instance) | python -
```

**Pass criteria:** output includes `StatusCode.DEADLINE_EXCEEDED`; no mutation occurs and AutoCAD
remains responsive. If the request happens to complete before the intentionally tiny deadline,
repeat once; persistent completion means the gate needs a deterministic test harness before it
can be marked passed.

### 9. Two simultaneous AutoCAD instances are isolated

Start two AutoCAD 2025 processes and load the plugin into both. Then:

```powershell
$records = Get-ChildItem $discovery -Filter *.json |
    ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json }

$records | Select-Object instance_id, pid, host, port, contract_version
```

**Pass criteria:** at least two live records exist and the two selected AutoCAD processes have
distinct `instance_id`, PID, port, and bearer token values. Both endpoints independently pass
Gate 2 or Gate 3 using their own instance ids.

Do not print token values in review evidence; record only `tokens_distinct=true`.

### 10. Token A cannot authenticate to instance B

With two live records from Gate 9, use instance A's token against instance B's endpoint through a
raw generated stub. The request must be rejected before dispatch.

```powershell
@'
import asyncio
import json
from pathlib import Path

import grpc

from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb
from autocad_sidecar.ipc.generated import host_transport_v1_pb2_grpc as pb_grpc

DISCOVERY = Path(r"__DISCOVERY__")
records = [json.loads(p.read_text(encoding="utf-8")) for p in DISCOVERY.glob("*.json")]
if len(records) < 2:
    raise RuntimeError("two live discovery records are required")
a, b = records[0], records[1]

async def main():
    channel = grpc.aio.insecure_channel(f"{b['host']}:{b['port']}")
    try:
        stub = pb_grpc.AutoCadHostStub(channel)
        try:
            await stub.Ping(
                pb.PingRequest(instance_id=b['instance_id']),
                metadata=(("authorization", f"Bearer {a['auth_token']}"),),
            )
        except grpc.aio.AioRpcError as exc:
            print(exc.code())
            if exc.code() != grpc.StatusCode.UNAUTHENTICATED:
                raise
        else:
            raise RuntimeError("cross-instance token was unexpectedly accepted")
    finally:
        await channel.close()

asyncio.run(main())
'@.Replace('__DISCOVERY__', $discovery) | python -
```

**Pass criteria:** `StatusCode.UNAUTHENTICATED`. No DSP command is dispatched.

### 11. AutoCAD unload/exit removes its discovery record

Record the selected instance id, then close the corresponding AutoCAD process normally. After a
brief wait:

```powershell
$recordPath = Join-Path $discovery ($instance + '.json')
Test-Path $recordPath
```

**Pass criteria:** `False`. A surviving record after normal plugin termination blocks the gate.

## Current evidence on `feat/grpc-loopback-transport`

Evidence captured during the AutoCAD 2025 validation session on 2026-08-28 (UTC+8):

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. Load + discovery | PASS | `NETLOAD` returned; discovery record `6c32d101-44a6-430b-b268-d56f45d97810.json` appeared; gRPC endpoint subsequently served requests. |
| 2. Sidecar status | PENDING | gRPC open/Ping was exercised through `host_test_client`, but the exact `autocad_sidecar.main ... status` gate has not yet been recorded. |
| 3. CurrentDocument | PASS | gRPC returned `Drawing1.dwg`, revision 0 and later revision 1. |
| 4. CurrentSelection | PASS | gRPC returned real AutoCAD `Line` handle `2C4`. |
| 5. MOVE once | PASS | `moved=1`, `verification.ok=True`, `revision_after=1` on real `Line` `2C4`. |
| 6. Idempotent replay | PENDING | Not yet recorded over the real gRPC host. |
| 7. Revision conflict | PENDING | Not yet recorded over the real gRPC host. |
| 8. Deadline | PENDING | Automated conformance exists; real-host gate not yet recorded. |
| 9. Two instances | PENDING | Not yet recorded. |
| 10. Cross-token rejection | PENDING | Automated auth coverage exists; two-real-instance gate not yet recorded. |
| 11. Discovery cleanup | PENDING | Not yet recorded on normal AutoCAD exit/unload. |

Additional evidence already collected in the same session:

- Named Pipe document/selection/move/fit smoke passed.
- gRPC document/selection/move/fit smoke passed.
- direct test-client execution works without manual `PYTHONPATH`.
- Pipe auto-discovery works when `--pipe` is omitted.
- `python -m pytest`: 118 passed, 4 live-host tests skipped.
- AutoCAD 2025 plugin SDK build: 0 errors; existing MSB3277 assembly-version warnings remain.
- GitHub Actions `gRPC transport conformance` and `gRPC transport development verification` passed on the validated branch head.

## Default-switch decision

Do **not** change the repository default transport to gRPC until all 11 real-host gates are marked
PASS with evidence attached to the review.

After all gates pass, create a separate review that changes only transport selection defaults and
related documentation. After gRPC has operated successfully through the agreed validation window,
create another separately approved cleanup review for Named Pipe server/client framing, pipe-only
tests/dependencies, and ADR-002 historical/superseded status.
