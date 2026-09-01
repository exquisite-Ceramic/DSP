# Phase H — Revit Wall Thickness Live Acceptance Runbook

This runbook is the **external real-Revit gate** for Phase H wall-thickness gap closure.

GitHub-hosted CI can prove only the Revit-free contracts, architecture guards, sidecar behavior, enterprise mappings, and provider-neutral reconciliation chain. It **must not** be used as evidence that Autodesk Revit itself accepted the mutation. Phase H is not closed until this runbook has fresh passing evidence from the pinned acceptance machine.

## 1. Required acceptance baseline

Record the exact machine baseline before running anything:

| Field | Required evidence |
|---|---|
| Git branch / HEAD | exact feature branch and commit SHA |
| Revit product | exact product/version displayed by Revit |
| Revit build | exact build/file version |
| `DSP_REVIT_VERSION` | exact Revit major version |
| `DSP_REVIT_TFM` | official target framework for that exact Revit release |
| `DSP_REVIT_API_DIR` | directory containing the exact `RevitAPI.dll` / `RevitAPIUI.dll` used by the installed product |
| Plugin DLL | exact built `Revit.AgentHost.dll` path |
| `.addin` file | exact local deployment path |
| RVT fixture | exact controlled `.rvt` path |
| RVT SHA-256 | exact hash recorded in the fixture manifest |
| Named Pipe | exact pipe identifier for the running Revit process |

Do not treat an example path or a value from another machine as authoritative. Re-record these values on every acceptance machine.

Set the machine-specific environment values in the current PowerShell session:

```powershell
$env:DSP_REVIT_VERSION = "<exact Revit major version>"
$env:DSP_REVIT_TFM = "<official TFM for that release>"
$env:DSP_REVIT_API_DIR = "<directory containing RevitAPI.dll>"
$env:DSP_REVIT_FIXTURE = "<absolute path to the controlled Phase H .rvt>"
```

## 2. Build against the installed Revit

From the repository root:

```powershell
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
```

Acceptance requires **0 errors**. Do not suppress reference-version warnings merely to make the build look clean; record them separately and keep the exact build output.

## 3. Deploy the application locally

Create a local Revit application `.addin` file in the normal per-user Revit Addins directory for the exact installed version. This file is machine-local and is not committed as a universal repository default.

Use this shape, substituting the exact built assembly path and a locally assigned stable GUID:

```xml
<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>DSP Revit AgentHost</Name>
    <Assembly>ABSOLUTE_PATH_TO_Revit.AgentHost.dll</Assembly>
    <AddInId>LOCAL-STABLE-GUID</AddInId>
    <FullClassName>Revit.AgentHost.Native.PluginEntry</FullClassName>
    <VendorId>DSP</VendorId>
    <VendorDescription>DSP Phase H Revit AgentHost</VendorDescription>
  </AddIn>
</RevitAddIns>
```

Start Revit after deploying the `.addin`. The plugin creates a process-scoped pipe named:

```text
EnterpriseDesignAgent.Revit.<machine>-<processId>
```

On Windows, inspect the pipe namespace and record the exact matching name:

```powershell
Get-ChildItem \\.\pipe\ |
  Where-Object { $_.Name -like "EnterpriseDesignAgent.Revit.*" } |
  Select-Object -ExpandProperty Name
```

`DSP_REVIT_PIPE` must contain the pipe **name only**, not the `\\.\pipe\` prefix:

```powershell
$env:DSP_REVIT_PIPE = "<EnterpriseDesignAgent.Revit....>"
```

## 4. Prepare the controlled RVT fixture

Use one controlled `.rvt` that contains four **distinct** Basic Wall targets. The fixture is deliberately structured so each failure has one dominant cause and stable error precedence.

### 4.1 Isolated positive wall

The `isolated_wall_unique_id` target must satisfy all of these before the live test starts:

- exactly one approved wall target;
- `WallKind.Basic`;
- current thickness is **not** 300 mm;
- its `WallType` is used by no other Wall;
- supported `CompoundStructure` has exactly one editable non-membrane layer;
- no supported insert/opening;
- no external actual participant in `LocationCurve.ElementsAtJoin(0)`;
- no external actual participant in `LocationCurve.ElementsAtJoin(1)`;
- no supported attachment/host-wall dependency that makes associativity unproven.

### 4.2 Shared-type rejection wall

The `shared_type_wall_unique_id` target must:

- be a Basic Wall;
- share its `WallType` with at least one **other** unapproved Wall;
- otherwise avoid inserts, joins, and additional supported dependencies that could mask the intended stable failure.

Expected code:

```text
SHARED_WALL_TYPE_OUTSIDE_SCOPE
```

### 4.3 Insert/opening rejection wall

The `insert_wall_unique_id` target must:

- be a Basic Wall with an otherwise exclusive supported type;
- contain a supported insert/opening visible to `HostObject.FindInserts(...)`;
- avoid actual endpoint joins and unrelated supported dependencies.

Expected code:

```text
WALL_INSERTS_OUTSIDE_MVP
```

### 4.4 Actual-join rejection wall

The `join_wall_unique_id` target must:

- be a Basic Wall with an otherwise exclusive supported type;
- have an **actual** external wall participant at endpoint 0 or 1;
- avoid inserts/openings and unrelated supported dependencies.

Expected code:

```text
WALL_JOIN_OUTSIDE_MVP
```

The live gate intentionally proves the current join participants via production preflight semantics. Join allowance alone is not evidence of a join.

## 5. Pin the fixture bytes and UniqueIds

Save the prepared RVT, close/reopen it if needed, and do **not** save the 300 mm mutation back over the canonical fixture after an acceptance run.

Record the four `Element.UniqueId` values using a trusted local Revit inspection mechanism such as RevitLookup or an equivalent local debugger/inspection tool. This is fixture authoring only; it is not part of the runtime DSP transport.

Calculate the fixture hash:

```powershell
$fixtureHash = (Get-FileHash -Algorithm SHA256 $env:DSP_REVIT_FIXTURE).Hash.ToLowerInvariant()
$fixtureHash
```

Next to the RVT, create a sibling manifest whose name replaces `.rvt` with `.phase-h.json`.

Example naming only:

```text
ControlledPhaseH.rvt
ControlledPhaseH.phase-h.json
```

Manifest contract:

```json
{
  "rvt_sha256": "<lowercase sha256>",
  "isolated_wall_unique_id": "<Element.UniqueId>",
  "shared_type_wall_unique_id": "<Element.UniqueId>",
  "insert_wall_unique_id": "<Element.UniqueId>",
  "join_wall_unique_id": "<Element.UniqueId>"
}
```

The live test refuses to run if:

- the RVT is missing;
- the manifest is missing;
- the fixture bytes do not match `rvt_sha256`;
- any required UniqueId is blank;
- the four scenario UniqueIds are not distinct.

## 6. Open the exact fixture in the running Revit instance

Before running pytest:

1. Ensure the plugin is loaded in the same Revit process whose pipe was recorded.
2. Open **exactly** `DSP_REVIT_FIXTURE` as the active Revit document.
3. Do not perform unrelated edits after establishing the baseline.
4. Do not save a previous 300 mm acceptance mutation over the canonical fixture.
5. If rerunning the acceptance gate, reload the canonical fixture bytes first.

The Host uses `Element.UniqueId` for target resolution. If another document is active, the controlled UniqueIds should fail to resolve and the acceptance test must fail rather than silently target another model.

## 7. Python prerequisites

Use the repository environment that already runs the Phase H sidecar and reconciliation tests. On the Windows live machine, the Named Pipe client also needs pywin32.

Install only if absent:

```powershell
python -m pip install pytest PyYAML pywin32
```

Do not install fake Autodesk assemblies for this test.

## 8. Run the live acceptance gate

Set the explicit live switch only on the real acceptance machine:

```powershell
$env:DSP_REVIT_LIVE = "1"

python -m pytest `
  tests/integration/test_phase_h_revit_wall_thickness_live.py `
  -vv -s
```

Without `DSP_REVIT_LIVE=1` and all of these variables, the test must report **SKIPPED**, never simulated success:

```text
DSP_REVIT_VERSION
DSP_REVIT_TFM
DSP_REVIT_API_DIR
DSP_REVIT_PIPE
DSP_REVIT_FIXTURE
```

## 9. What the live test proves

The single live acceptance scenario runs in a deterministic sequence.

### 9.1 Safe revision baseline

The test first sends a command with an intentionally impossible expected revision. Production `RevisionGate` must return:

```text
REVISION_CONFLICT
commit_state = BEFORE_COMMIT
```

The returned `revision_after` becomes the live baseline. This happens before target mutation or `Transaction.Start()` and therefore provides a safe current-revision probe without adding a separate Revit read protocol.

### 9.2 Required zero-transaction failures

At the same baseline revision the test checks:

| Scenario | Required Host result |
|---|---|
| shared WallType | `SHARED_WALL_TYPE_OUTSIDE_SCOPE` |
| insert/opening | `WALL_INSERTS_OUTSIDE_MVP` |
| actual endpoint join | `WALL_JOIN_OUTSIDE_MVP` |
| stale expected revision | `REVISION_CONFLICT` |

Each must be:

```text
status = ERROR
commit_state = BEFORE_COMMIT
revision_after = unchanged
```

After every rejection, another safe revision probe verifies that the document revision did not advance.

### 9.3 Positive 300 mm mutation

The isolated target then executes with the exact current revision and a fresh idempotency key.

Required evidence:

- `status = OK`;
- `replayed = false`;
- `transaction_attempt_count = 1`;
- returned wall `UniqueId` equals the reviewed isolated target;
- width before differs from width after;
- `width_after_mm = 300` within the frozen tolerance;
- `revision_after > revision_before`;
- `identity_invariant_proven = true`;
- `location_invariant_proven = true`;
- `relationship_invariant_proven = true`;
- `document_change_observed = true`.

This is the only mutation transaction expected in the live test.

### 9.4 Revit facts and enterprise mappings

The live post-read width and target identity are fed through the existing Revit `DesignFactAdapter`. The emitted live facts must resolve through the reviewed enterprise mapping catalog to:

```text
ifc:IfcWall
dsp:WallThickness = 300 mm
```

### 9.5 Provider-neutral reconciliation

The same real Host success envelope is passed through `RevitExecutionResultAdapter`, then through the existing Step28/Step33/Step37 proof fixture.

Required result:

```text
ActualDelta:
  one MODIFY
  semantic_id = WALL-001
  canonical_kind = ifc:IfcWall
  changed_aspects = PROPERTIES only

ScopeComparisonStatus = WITHIN_SCOPE
VerificationStatus = PASSED
ExecutionSagaStatus = SUCCEEDED
```

The live test does **not** invent `GEOMETRY` merely because Revit regenerated native geometry.

### 9.6 Replay and conflict

The exact successful command is sent again:

```text
replayed = true
revision_after = unchanged
no second revision increment
```

Then the same idempotency key is reused with a different thickness fingerprint:

```text
IDEMPOTENCY_KEY_CONFLICT
commit_state = BEFORE_COMMIT
revision_after = unchanged
```

A final revision probe proves no second mutation occurred.

## 10. Provider-neutral negative cases stay offline

Do not intentionally corrupt a real Revit model just to synthesize reconciliation failures already covered by Task 10.

These remain provider-neutral offline tests:

- reconstructed width `299 mm` -> `VerificationStatus.FAILED` / `VERIFY_FAILED`;
- truthful extra `GEOMETRY` -> `SCOPE_BREACH`;
- truthful extra semantic entity -> `SCOPE_BREACH`;
- Host success without post-execution semantic evidence -> cannot produce `PASSED`.

## 11. Required captured evidence

Run pytest with `-s`. On success, the live test prints one JSON summary. Preserve:

- exact git HEAD;
- exact Revit product/build;
- exact TFM and Revit API directory;
- exact native build output;
- fixture path and SHA-256;
- fixture manifest;
- pipe identifier;
- complete pytest output;
- baseline and committed revisions;
- `width_after_mm`;
- negative stable codes;
- `transaction_attempt_count`;
- `WITHIN_SCOPE`;
- `PASSED`;
- `SUCCEEDED`;
- `replayed = true`;
- `IDEMPOTENCY_KEY_CONFLICT`.

Do not mark Task 11 or Phase H complete from a default CI skip.

## 12. Failure policy

Stop and return to design review instead of weakening the gate if any live run shows:

- a native compile requirement that forces shared platform semantic changes;
- the isolated mutation truthfully changes an additional canonical entity/aspect that cannot be normalized;
- a known commit whose wider effect cannot be normalized;
- a supposedly isolated wall requires type duplication, unjoin, insert suppression, or temporary detach;
- actual current joins can only be “proven” by checking join allowance;
- a precommit rejection advances document revision;
- replay starts a second transaction or advances revision;
- the real installed Revit runtime cannot be identified exactly.

## 13. Execution evidence

Append fresh execution evidence here only after the real-host run.

```text
Branch / HEAD:
Revit product:
Revit build:
DSP_REVIT_VERSION:
DSP_REVIT_TFM:
DSP_REVIT_API_DIR:
Native build:
RVT fixture:
RVT SHA-256:
Named Pipe:
Live pytest:
Revision before:
Revision after:
Width after:
Shared-type result:
Insert result:
Join result:
Stale-revision result:
Replay result:
Conflict result:
Scope result:
Verification result:
Saga result:
```
