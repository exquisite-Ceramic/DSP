# AutoCAD gRPC Real-Host Smoke Gate

This runbook is the real-host rollout gate for ADR-004 (`gRPC over loopback for AutoCAD IPC`).
It validates the opt-in gRPC transport against AutoCAD 2025 before any separate change switches
the default transport away from Named Pipe.

Current default transport: Named Pipe
Opt-in migration transport: gRPC over loopback
Default-switch gate: `docs/runbooks/autocad-grpc-smoke.md`

A failed or unverified item below blocks the default switch. It does **not** require reverting the
dual-stack implementation. Named Pipe remains available during the migration phase.

## Supported validation environment

Record the exact environment used for a validation session:

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

The machine must also have a compatible `Microsoft.AspNetCore.App` 8.x runtime installed:

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

## Discovery and Python setup

Discovery records live under:

```powershell
$discovery = Join-Path $env:LOCALAPPDATA 'EnterpriseDesignAgent\hosts'
Get-ChildItem $discovery -Filter *.json
```

Expected record properties:

- `host == 127.0.0.1`
- `port > 0`
- `transport == grpc-h2c`
- PID belongs to the loaded AutoCAD process
- record appears only after the listener is usable

Never paste or attach bearer token values to reviews or logs. Record only boolean authentication
evidence such as `tokens_distinct=true` or `cross_token_rejected=true`.

Install the local Python packages when using module entry points:

```powershell
python -m pip install -e .\contracts\python
python -m pip install -e .\hosts\autocad\sidecar
```

The repository test client bootstraps its own source roots; no manual `PYTHONPATH` is required.

## Gate checklist

### 1. Plugin load and discovery publication

**Pass criteria:** AutoCAD remains responsive after `NETLOAD`; a discovery record for the process
appears; the endpoint accepts gRPC.

### 2. Sidecar status with exact instance id

```powershell
python -m autocad_sidecar.main `
    --transport grpc `
    --instance-id $instance `
    status
```

**Pass criteria:** exit code 0 and state `ready` or `busy`.

### 3. CurrentDocument

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    document
```

**Pass criteria:** `status='OK'`, active document id/name, and current revision.

### 4. CurrentSelection

Select a real entity in AutoCAD, then:

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id $instance `
    selection
```

**Pass criteria:** `status='OK'` and at least one real entity reference.

### 5. MOVE once with revision and verification

Run a MOVE with the current revision and a new idempotency key.

**Pass criteria:** `status='OK'`, `moved == 1`, `verification.ok == True`, revision increments by
exactly one, and the selected entity moves exactly once.

### 6. Replay the same idempotency key without a second mutation

Replay the exact MOVE with the same idempotency key and original revision.

**Pass criteria:** cached result is returned with `replayed=True`; position is unchanged from the
first result and revision does not increment a second time.

### 7. Stale revision remains a DSP business error

Send a new MOVE idempotency key with the stale pre-MOVE revision.

**Pass criteria:** RPC completes normally; DSP result is `status='ERROR'` with
`error_code='REVISION_CONFLICT'`; no mutation occurs.

### 8. Short transport deadline returns DEADLINE_EXCEEDED safely

Send a valid read-only `context.current_document` envelope through `GrpcTransport.exchange()` with
an intentionally tiny transport timeout such as `1e-9` seconds.

**Pass criteria:** `grpc.StatusCode.DEADLINE_EXCEEDED`; no mutation and AutoCAD remains responsive.

### 9. Two simultaneous AutoCAD processes are isolated

Start two independent AutoCAD 2025 processes and load the plugin into both.

**Pass criteria:** two live endpoints have distinct `instance_id`, PID, port, and bearer token;
each endpoint independently returns a ready document/status result. Record only
`tokens_distinct=true`, never token values.

### 10. Token A cannot authenticate to instance B

Use instance A's bearer token against instance B's raw gRPC `Ping` endpoint.

**Pass criteria:** `StatusCode.UNAUTHENTICATED`; no DSP command is dispatched.

### 11. Single-process multi-document isolation

In one AutoCAD process, open two different DWGs. Keep the same gRPC instance and switch active
documents A -> B -> A -> B.

**Pass criteria:** same PID/instance/port are retained; A and B have distinct `documentId` values;
a DSP MOVE in B increments only B's revision; A's revision remains unchanged; switching back to B
preserves B's revision.

Change-capture implementation must also rebind database event handlers on
`DocumentManager.DocumentActivated`. The source regression for this behavior is required because
the current public DSP command surface does not expose `EventQueue` state for a direct live-host
assertion that an arbitrary manual edit was consumed by the queue.

### 12. Normal AutoCAD exit removes its discovery record

While AutoCAD is still running, first prove the selected process is alive and its discovery record
exists. Then close that AutoCAD process normally from the UI and observe both process exit and
record removal.

**Pass criteria:** precondition proves live process + live record; after normal exit,
`process_exited=true` and `record_removed=true`.

## Current evidence on `feat/grpc-loopback-transport`

Evidence captured during the AutoCAD 2025 validation session on 2026-08-28 (UTC+8):

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. Load + discovery | PASS | `NETLOAD` returned without blocking; discovery was published and the endpoint subsequently served authenticated gRPC requests. |
| 2. Sidecar status | PASS | `state='ready'`, document `Drawing1.dwg`, process exit code `0`. |
| 3. CurrentDocument | PASS | gRPC returned real active document `Drawing1.dwg`, including revision changes observed during the session. |
| 4. CurrentSelection | PASS | gRPC returned a real AutoCAD `Line` entity reference/handle. |
| 5. MOVE once | PASS | Real Line MOVE returned `moved=1`, `verification.ok=True`, and revision incremented exactly once. |
| 6. Idempotent replay | PASS | First/second results had identical position and `revision_after=2`; second result reported `replayed=True`; scenario exit code `0`. |
| 7. Revision conflict | PASS | Stale request returned DSP `REVISION_CONFLICT` (`expected revision 1, current is 2`) with scenario exit code `0`; no second mutation. |
| 8. Deadline | PASS | First real-host attempt returned `StatusCode.DEADLINE_EXCEEDED`; gate exit code `0`; request was read-only. |
| 9. Two processes | PASS | PID `2576` / instance `b059b136-4897-4f4d-b78d-04c7e9eadd55` / port `59505` and PID `55080` / instance `07a7a664-6648-408d-aa1c-3c5586620b3c` / port `62248`; instance IDs, PIDs, ports, and tokens all distinct; both states `ready`. |
| 10. Cross-token rejection | PASS | Token from process A against process B returned `StatusCode.UNAUTHENTICATED`; `cross_token_rejected=true`; no token value recorded. |
| 11. One process, two documents | PASS | On PID `52824`, instance `ec7791b8-77a0-4bb7-9861-371d9e9dae90`, A=`Drawing22.dwg` revision `0`; B=`Drawing11.dwg` revision `0 -> 1` after MOVE; switching back to A kept revision `0`; switching again to B kept revision `1`. |
| 12. Discovery cleanup | PASS | Retry precondition proved PID `58444`, instance `07375240-bdf5-4d39-a226-6eccf93a36bd`, port `58002` was alive with a live record; normal UI exit produced `process_exited=true`, `record_removed=true`, `GATE12_PASS`. |

### Validation notes

- The Gate 6 replay flag exposed a real Sidecar bug: cached results were returned without
  `replayed=True`. A regression was added first, the failure was observed in CI, and
  `IdempotencyStore.recall()` was fixed to return a replay-marked copy.
- The multi-document review exposed a real AutoCAD lifecycle gap: change handlers were bound only
  to the database active at plugin start. A regression was added first and observed failing
  (`1 failed, 116 passed, 4 skipped`), then the native wrapper was changed to rebind on
  `DocumentActivated` and unsubscribe on detach.
- The latest AutoCAD-specific fix commit used for Gate 11/12 was
  `157c54d88fc401ede20944c5d477dbb3e0d95bf6`. The AutoCAD 2025 SDK build of that head completed
  successfully before the Gate 11 live-host run.
- Gates captured earlier in the same session were on the same feature line before the
  document-activation rebinding change. That later change is limited to native change-handler
  lifecycle; the impacted multi-document and shutdown paths were rerun on the latest plugin.
- Named Pipe document/selection/move/fit smoke also passed during the session.
- Direct test-client execution works without manual `PYTHONPATH`.
- Pipe auto-discovery works when `--pipe` is omitted.
- Known AutoCAD SDK build warnings remain the existing MSB3277 assembly-version warnings; the
  validated plugin build had no errors.

## Default-switch decision

All 12 real-host gates are now recorded as PASS for the dual-stack feature validation.

This does **not** switch the repository default transport. Merge/review of the dual-stack feature,
a later default change from Named Pipe to gRPC, and eventual Named Pipe removal are separate
reviews.

Before merging the dual-stack feature, verify the latest branch head has green repository CI and
is not behind `main`. A later default-switch review should change only transport-selection defaults
and related documentation. Named Pipe cleanup must remain a separately approved later review after
the agreed gRPC validation window.
