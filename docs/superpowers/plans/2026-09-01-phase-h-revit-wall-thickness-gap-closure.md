# Phase H Revit Wall Thickness Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one real Revit Host path for the already-frozen `set_wall_thickness.v1` canonical action, prove an exclusive isolated Basic Wall can be changed to 300 mm through the existing Step27-37 governance/reconciliation chain, and fail closed before mutation whenever the Revit native model cannot prove the change stays inside the approved single-wall `PROPERTIES` scope.

**Architecture:** Add `hosts/revit` as a new Host family without changing canonical/Core semantics. Keep all Autodesk Revit API references inside `hosts/revit/plugin/**/Native/**`; put deterministic request, idempotency, evidence, and thickness-planning logic in a Revit-free .NET core project and Python sidecar. Native execution is queued through `ExternalEvent`, uses one Revit transaction after all preflight checks pass, reads back the committed WallType width, emits Revit `NormalizedDesignFact` evidence, then reuses the existing Step33 `ActualDelta`, `ScopeComparator`, `VerificationEvidenceBundle`, `SemanticVerifier`, and Saga lifecycle.

**Tech Stack:** Python 3.11, pytest, DSP `host_contracts` / `design_fact_contracts`, DSP Steps 23/27-33/37 Python packages, C#/.NET, Autodesk Revit API for one explicitly pinned installed Revit release, Named Pipes, GitHub Actions for Revit-free checks only.

**Spec:** `docs/superpowers/specs/2026-09-01-phase-h-revit-wall-thickness-gap-closure-design.md`

## Global Constraints

- Canonical operation remains exactly `set_wall_thickness.v1`; canonical target remains `ifc:IfcWall`; canonical effects remain exactly `PROPERTIES`.
- The MVP supports exactly one approved Revit wall target per execution.
- The target must be a Basic Wall with one exclusive `WallType`; the provider must not duplicate or reassign WallTypes.
- The supported `CompoundStructure` is non-null, not vertically compound, and has exactly one editable non-membrane layer.
- Before transaction start, compute the editable layer width as `requested_total_internal - sum(fixed_layer_widths)`; reject non-finite/non-positive/illegal results and verify the reconstructed total equals the requested total within the pinned-version native tolerance.
- Actual join participation must be checked from real join participants (`LocationCurve.ElementsAtJoin(0)` / `(1)` or the pinned release's equivalent API). `WallUtils.IsWallJoinAllowedAtEnd` must never be used as proof that an endpoint is currently unjoined.
- Supported hosted inserts/openings and any provider-supported dependency that can mutate another design element cause a before-commit rejection.
- `Element.UniqueId` is the durable Revit native binding identity; `ElementId` is diagnostic only.
- All `Autodesk.Revit.*` source references are confined to `hosts/revit/plugin/**/Native/**`; the native `.csproj` may reference `RevitAPI.dll` / `RevitAPIUI.dll`.
- Background pipe listeners, Python sidecar code, Tasks, worker threads, and timers must never call the Revit API directly. Asynchronous native work enters via `ExternalEvent` / `IExternalEventHandler.Execute(UIApplication)`.
- The Revit document revision is session-scoped and monotonically owned by `ControlledApplication.DocumentChanged`; command execution must not increment a second revision counter.
- A successful Host API call is not sufficient. Success requires post-commit native read-back of the target width and evidence sufficient to construct a truthful provider-neutral `ActualDelta`.
- Host-internal geometry regeneration entailed solely by the approved thickness property is not a separate canonical `GEOMETRY` change. Any independently observable extra canonical entity/aspect must be reported rather than hidden.
- A confirmed commit with a wider side effect that cannot be truthfully normalized is a design stop. Do not fabricate a clean `ActualDelta`, do not label it `BEFORE_COMMIT`, and do not overload `COMMIT_STATE_UNKNOWN`.
- Ambiguous commit certainty maps only to the existing `COMMIT_STATE_UNKNOWN` behavior and is not blindly retried.
- Same idempotency key + identical effective command fingerprint returns the stored result without a second transaction; same key + different fingerprint fails closed.
- Revit transport for this phase is Named Pipe only. Do not generalize or rename the existing AutoCAD gRPC service.
- `NormalizedDesignFact`, shared HostCommand JSON schema, D4, Step27-33, Step37, and AutoCAD production semantics are read-only. If implementation proves one of those public contracts is insufficient, stop and reopen the design.
- Enterprise mappings added in this phase are exactly:
  - `revit.builtin_category / OST_Walls -> ifc:IfcWall`
  - `revit.property / WallType.CompoundStructure.TotalWidth -> dsp:WallThickness`
- Multi-target execution, shared-type duplication, multi-layer redistribution, vertically compound/stacked/curtain walls, generalized Revit dependency policy, automatic rollback, gRPC transport, and multi-version packaging are non-goals.
- The native Revit project must not guess a target framework. A real-host build requires three explicit machine inputs: `DspRevitVersion`, `DspRevitTargetFramework`, and `DspRevitApiDir`. The operator must set them from the exact installed Revit release and its official runtime requirement before any live build/acceptance task.

---

## Planned File Structure

```text
hosts/revit/
  plugin/
    Revit.AgentHost.Core/
      Revit.AgentHost.Core.csproj
      Contracts/
        HostCommandEnvelope.cs
        HostResultEnvelope.cs
        WallThicknessContracts.cs
      Execution/
        CommandFingerprint.cs
        IdempotencyStore.cs
        WallThicknessPlanner.cs
    Revit.AgentHost.Core.Tests/
      Revit.AgentHost.Core.Tests.csproj
      CommandFingerprintTests.cs
      IdempotencyStoreTests.cs
      WallThicknessPlannerTests.cs
    Revit.AgentHost/
      Revit.AgentHost.csproj
      Ipc/
        NamedPipeServer.cs
        RequestDispatcher.cs
      Native/
        PluginEntry.cs
        ExternalEvents/
          RevitRequestQueue.cs
          RevitExternalEventHandler.cs
        Revision/
          DocumentRevisionTracker.cs
        Walls/
          RevitWallTargetResolver.cs
          RevitWallIsolationProbe.cs
          RevitWallThicknessMutation.cs
          RevitWallSnapshotReader.cs
  sidecar/
    pyproject.toml
    src/revit_sidecar/
      __init__.py
      models.py
      named_pipe.py
      model_adapter.py
      design_fact_adapter.py
      execution_result_adapter.py
    tests/
      test_model_adapter.py
      test_design_fact_adapter.py
      test_execution_result_adapter.py
providers/semantics/enterprise_mapping/
  src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml
tests/revit/
  test_revit_architecture.py
  test_revit_enterprise_mapping.py
tests/integration/
  test_phase_h_revit_wall_thickness_reconciliation.py
  test_phase_h_revit_wall_thickness_live.py
docs/runbooks/
  revit-wall-thickness-gap-closure.md
.github/workflows/
  phase-h-revit-wall-thickness.yml
```

The `.NET Core` project is intentionally Revit-free so its deterministic logic can run in ordinary CI. `Revit.AgentHost` is the only project that references Autodesk assemblies, and its native build is an explicit real-host prerequisite rather than a simulated CI claim.

---

## Task 1: Freeze the Revit build boundary and architecture guard

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj`
- Create: `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj`
- Create: `tests/revit/test_revit_architecture.py`

**Interfaces:**
- Consumes: repository Python test runner; the approved Native confinement rule.
- Produces: one Revit-free `net8.0` core test target; one native Revit host project whose `TargetFramework` and Autodesk reference paths come only from explicit MSBuild properties.

- [ ] **Step 1: Write the architecture RED**

Create `tests/revit/test_revit_architecture.py` with assertions that:
1. `hosts/revit/plugin/Revit.AgentHost.Core/**` contains no `Autodesk.Revit`;
2. `hosts/revit/sidecar/**` contains no `Autodesk.Revit`;
3. every C# source file containing `Autodesk.Revit` is under `hosts/revit/plugin/Revit.AgentHost/Native/`;
4. the native project contains no hard-coded `net8.0-windows`, `net10.0-windows`, `2025`, or `2026` as a universal Revit target claim;
5. platform Step27-37 production directories contain no new `revit`, `WallType`, `OST_Walls`, `CompoundStructure`, or `ExternalEvent` branch.

Use a baseline path allow-list for existing unrelated text so the guard fails only on new architecture leakage.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/revit/test_revit_architecture.py -q
```

Expected: FAIL because `hosts/revit` projects do not exist.

- [ ] **Step 3: Add the minimal Revit-free core project**

`Revit.AgentHost.Core.csproj` is:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
</Project>
```

`Revit.AgentHost.Core.Tests.csproj` targets `net8.0`, references `Revit.AgentHost.Core.csproj`, and pins:
- `Microsoft.NET.Test.Sdk` `17.11.1`;
- `xunit` `2.9.2`;
- `xunit.runner.visualstudio` `2.8.2` with `PrivateAssets="all"`.

- [ ] **Step 4: Add the native project with explicit machine-supplied baseline**

`Revit.AgentHost.csproj` must read:

```xml
<TargetFramework>$(DspRevitTargetFramework)</TargetFramework>
```

and fail before compile when any of these are empty:

```text
DspRevitVersion
DspRevitTargetFramework
DspRevitApiDir
```

Reference:

```text
$(DspRevitApiDir)\RevitAPI.dll
$(DspRevitApiDir)\RevitAPIUI.dll
```

with `Private=false`, and reference `../Revit.AgentHost.Core/Revit.AgentHost.Core.csproj`.

Do not source-control a concrete Revit version, installation path, or guessed native TFM in this task.

- [ ] **Step 5: GREEN the offline boundary**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
python -m pytest tests/revit/test_revit_architecture.py -q
```

Expected: PASS without Revit installed.

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/plugin tests/revit/test_revit_architecture.py
git commit -m "build: establish revit native boundary"
```

---

## Task 2: Add Revit-free HostCommand, fingerprint, and idempotency contracts

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/HostCommandEnvelope.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/HostResultEnvelope.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/WallThicknessContracts.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Execution/CommandFingerprint.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Execution/IdempotencyStore.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/CommandFingerprintTests.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/IdempotencyStoreTests.cs`

**Interfaces:**
- Consumes: unchanged `contracts/schemas/host-command.schema.json`.
- Produces:
  - `HostCommandEnvelope` with JSON fields `command_id`, `document_id`, `mode`, `operation`, `target_native_refs`, `arguments`, `preconditions`, `idempotency_key`, `deadline_at`;
  - `CommandFingerprint.Compute(HostCommandEnvelope) -> string`;
  - `IdempotencyStore.TryGet(string key, string fingerprint, out HostResultEnvelope result)`;
  - `IdempotencyStore.Store(string key, string fingerprint, HostResultEnvelope result)`;
  - stable conflict code `IDEMPOTENCY_KEY_CONFLICT`.

- [ ] **Step 1: Write RED serialization/fingerprint tests**

Freeze a single execution command:

```json
{
  "command_id": "CMD-REVIT-001",
  "document_id": "DOC-REVIT-001",
  "mode": "EXECUTE",
  "operation": "set_wall_thickness",
  "target_native_refs": [
    {
      "document_id": "DOC-REVIT-001",
      "native_id": "wall-unique-id",
      "native_type": "Wall"
    }
  ],
  "arguments": {
    "thickness": {
      "value": 300.0,
      "unit": "mm"
    }
  },
  "preconditions": [
    {"revision": 10}
  ],
  "idempotency_key": "IDEMP-REVIT-001"
}
```

Assert canonical fingerprinting is insensitive to JSON object key order but changes for target, requested thickness, document, revision, operation, or mode.

- [ ] **Step 2: Write RED idempotency tests**

Freeze these cases:
- first key/fingerprint is absent;
- storing and replaying same key/fingerprint returns the exact stored result;
- same key/different fingerprint throws/returns `IDEMPOTENCY_KEY_CONFLICT`;
- replay does not invoke an execution delegate a second time.

- [ ] **Step 3: Run RED**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj --filter "CommandFingerprintTests|IdempotencyStoreTests"
```

Expected: FAIL because contracts/store do not exist.

- [ ] **Step 4: Implement deterministic core contracts**

Use `System.Text.Json` names matching the existing HostCommand schema exactly. `CommandFingerprint.Compute` must canonicalize a semantic body containing all effective mutation authority inputs and SHA-256 it; it must exclude transport-only formatting.

`IdempotencyStore` stores:

```csharp
public sealed record IdempotencyEntry(
    string Fingerprint,
    HostResultEnvelope Result
);
```

and rejects a key whose stored `Fingerprint` differs.

- [ ] **Step 5: GREEN**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/plugin/Revit.AgentHost.Core hosts/revit/plugin/Revit.AgentHost.Core.Tests
git commit -m "feat: add revit host command idempotency core"
```

---

## Task 3: Add the Revit Named Pipe sidecar and canonical-to-native command adapter

**Files:**
- Create: `hosts/revit/sidecar/pyproject.toml`
- Create: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/models.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/named_pipe.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/model_adapter.py`
- Create: `hosts/revit/sidecar/tests/test_model_adapter.py`

**Interfaces:**
- Consumes: `host_contracts.HostCommand` and one already-admitted Revit `ProviderBinding`.
- Produces:
  - `RevitHostAdapter.build_set_wall_thickness_command(command_id, document_id, wall_unique_id, expected_revision, thickness_mm, idempotency_key) -> HostCommand`;
  - `NamedPipeTransport.request(command: HostCommand) -> dict`;
  - Host operation string exactly `set_wall_thickness`.

- [ ] **Step 1: Write RED adapter test**

Given:
- document `DOC-REVIT-001`;
- bound native `UniqueId="wall-unique-id"`, `native_kind="Wall"`;
- expected revision `10`;
- canonical thickness `{value: 300.0, unit: "mm"}`;
- idempotency key `IDEMP-REVIT-001`;

assert the emitted `HostCommand` is `mode="EXECUTE"`, `operation="set_wall_thickness"`, contains exactly one native ref, carries the canonical millimetre measurement, and carries the revision only as an existing Host precondition.

Also assert the payload contains none of:

```text
ifc:IfcWall
ApprovalScopeBoundary
ExecutionGrant
WallType
CompoundStructure
ElementId
```

- [ ] **Step 2: Write RED transport test**

Use a fake pipe endpoint and prove the sidecar only performs the existing length-prefixed/JSON Named Pipe request-response pattern selected for Revit. There must be no gRPC import or fallback path in `revit_sidecar`.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_model_adapter.py -q
```

Expected: import/module failure.

- [ ] **Step 4: Implement the thin sidecar**

`pyproject.toml` requires Python `>=3.11`, depends on `host-contracts>=0.1.0`, and puts `pywin32>=306` behind a Windows pipe optional dependency if needed. Do not add `grpcio`, protobuf stubs, MCP surface, or transport selection logic in this phase.

Keep the adapter signature explicit:

```python
def build_set_wall_thickness_command(
    *,
    command_id: str,
    document_id: str,
    wall_unique_id: str,
    expected_revision: int,
    thickness_mm: float,
    idempotency_key: str,
) -> HostCommand:
    return HostCommand(
        command_id=command_id,
        document_id=document_id,
        mode="EXECUTE",
        operation="set_wall_thickness",
        target_native_refs=(
            {"document_id": document_id, "native_id": wall_unique_id, "native_type": "Wall"},
        ),
        arguments={"thickness": {"value": thickness_mm, "unit": "mm"}},
        preconditions=({"revision": expected_revision},),
        idempotency_key=idempotency_key,
    )
```

The adapter rejects non-finite/non-positive `thickness_mm` before transport.

- [ ] **Step 5: GREEN**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_model_adapter.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/sidecar
git commit -m "feat: add revit named pipe sidecar"
```

---

## Task 4: Normalize Revit wall facts and add enterprise semantic mappings

**Files:**
- Create: `hosts/revit/sidecar/src/revit_sidecar/design_fact_adapter.py`
- Create: `hosts/revit/sidecar/tests/test_design_fact_adapter.py`
- Modify: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`
- Create: `tests/revit/test_revit_enterprise_mapping.py`

**Interfaces:**
- Consumes: a Revit-native snapshot dictionary with `document_id`, `host_instance_id`, `source_revision`, `native_id`, `native_kind`, `builtin_category`, and `wall_thickness_mm`.
- Produces: deterministic `NormalizedDesignFact` values using the frozen shared contract.

- [ ] **Step 1: Write RED fact tests**

For one snapshot, assert exactly these minimum facts:

```text
IDENTITY
  predicate = native_kind
  value = Wall
  native_id = <Element.UniqueId>
  native_kind = Wall

CLASSIFICATION
  predicate = builtin_category
  source_scheme = revit.builtin_category
  source_code = OST_Walls
  value = OST_Walls

PROPERTY
  predicate = wall_thickness
  source_scheme = revit.property
  source_code = WallType.CompoundStructure.TotalWidth
  value = 300.0
  unit = mm
```

Fact IDs must use the existing deterministic tuple:

```text
document_id + source_revision + native_id + fact_kind + predicate
```

serialized/canonicalized exactly the same way as the AutoCAD thin adapter.

- [ ] **Step 2: Write RED mapping tests**

Load the real enterprise mapping catalog and assert:

```text
revit.builtin_category / OST_Walls
    -> ifc:IfcWall

revit.property / WallType.CompoundStructure.TotalWidth
    -> dsp:WallThickness
```

Also assert the existing AutoCAD `A-WALL*` and `LWPOLYLINE.ConstantWidth` rules still resolve unchanged.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_design_fact_adapter.py tests/revit/test_revit_enterprise_mapping.py -q
```

- [ ] **Step 4: Implement the adapter and exact mapping rules**

Reuse `design_fact_contracts.NormalizedDesignFact`, `DesignFactHostRef`, and `NativeSubjectRef`; do not add fields to those shared types.

Add only two exact Revit mapping entries to `enterprise_mappings_v1.yaml`; do not put Revit-specific branches in D5/IFC provider code.

- [ ] **Step 5: GREEN mapping + regression**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_design_fact_adapter.py tests/revit/test_revit_enterprise_mapping.py -q
python -m pytest providers/semantics/enterprise_mapping -q
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/sidecar providers/semantics/enterprise_mapping tests/revit/test_revit_enterprise_mapping.py
git commit -m "feat: map revit wall facts to canonical semantics"
```

---

## Task 5: Add ExternalEvent dispatch and a single DocumentChanged revision owner

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost/Ipc/NamedPipeServer.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Ipc/RequestDispatcher.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/PluginEntry.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestQueue.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitExternalEventHandler.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Revision/DocumentRevisionTracker.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Execution/RevisionGate.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/RevisionGateTests.cs`

**Interfaces:**
- Consumes: pipe-decoded `HostCommandEnvelope`.
- Produces:
  - queue entry completed exactly once by the ExternalEvent handler;
  - `DocumentRevisionTracker.Get(documentKey) -> long`;
  - `DocumentRevisionTracker.OnDocumentChanged(documentKey) -> long`;
  - pure `RevisionGate.RequireExpected(current, expected)`.

- [ ] **Step 1: RED the pure revision gate**

Assert equality passes; mismatch returns stable `REVISION_CONFLICT`; negative revisions are invalid.

- [ ] **Step 2: RED the native architecture by inspection**

Extend `tests/revit/test_revit_architecture.py` to assert:
- `NamedPipeServer.cs` never imports `Autodesk.Revit`;
- the only source that subscribes to `ControlledApplication.DocumentChanged` is `DocumentRevisionTracker`/`PluginEntry` wiring;
- no command handler contains `revision++` or another independent mutation revision update.

- [ ] **Step 3: Run RED**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj --filter RevisionGateTests
python -m pytest tests/revit/test_revit_architecture.py -q
```

- [ ] **Step 4: Implement queue/event ownership**

The pipe thread may enqueue a request and call `ExternalEvent.Raise()`, but only `RevitExternalEventHandler.Execute(UIApplication)` resolves the active document and dispatches native reads/mutations.

`DocumentRevisionTracker` subscribes during plugin startup and increments exactly once per observed Revit `DocumentChanged` event for the matching document session. Command execution reads this counter before and after; it never increments it directly.

- [ ] **Step 5: Compile on the pinned Revit machine**

Before this command, the operator must set real values from the installed release:

```powershell
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
```

Expected: build succeeds only when those three values identify the exact installed Revit API/runtime. If the machine values are unavailable, do not fake this GREEN; stop this task before the native commit.

- [ ] **Step 6: GREEN offline guards**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
python -m pytest tests/revit/test_revit_architecture.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add hosts/revit/plugin tests/revit/test_revit_architecture.py
git commit -m "feat: dispatch revit commands through external events"
```

---

## Task 6: Implement fail-closed wall identity, exclusivity, insert, and real-join preflight

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/WallIsolationEvidence.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Execution/WallIsolationDecision.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/WallIsolationDecisionTests.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallTargetResolver.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallIsolationProbe.cs`

**Interfaces:**
- Consumes: exactly one native ref and current `Document`.
- Produces:
  - target resolution by `Element.UniqueId`;
  - `WallIsolationEvidence` with `wallUniqueId`, `wallTypeUniqueId`, `sameTypeWallUniqueIds`, `insertUniqueIds`, `joinEnd0UniqueIds`, `joinEnd1UniqueIds`, `unsupportedDependencyUniqueIds`;
  - pure `WallIsolationDecision.Evaluate(evidence)` returning eligible or one stable before-commit code.

- [ ] **Step 1: Write RED pure isolation cases**

Freeze failures:
- target count != 1 -> `TARGET_COUNT_OUTSIDE_MVP`;
- missing/wrong native kind/wrong document -> `TARGET_RESOLUTION_FAILED`;
- non-Basic Wall -> `UNSUPPORTED_WALL_KIND`;
- same type used by another wall -> `SHARED_WALL_TYPE_OUTSIDE_SCOPE`;
- supported insert/opening exists -> `WALL_INSERTS_OUTSIDE_MVP`;
- either endpoint has an actual join participant -> `WALL_JOIN_OUTSIDE_MVP`;
- dependency probe cannot prove isolation -> `WALL_ASSOCIATIVITY_UNPROVEN`.

The success fixture contains exactly the approved wall in `sameTypeWallUniqueIds` and empty inserts/joins/unsupported dependencies.

- [ ] **Step 2: RED the specific join API guard**

Extend `tests/revit/test_revit_architecture.py` to require the native probe to reference:

```text
ElementsAtJoin(0)
ElementsAtJoin(1)
```

and to reject any implementation that treats `IsWallJoinAllowedAtEnd` as the current-join predicate.

- [ ] **Step 3: Run RED**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj --filter WallIsolationDecisionTests
python -m pytest tests/revit/test_revit_architecture.py -q
```

- [ ] **Step 4: Implement native evidence collection**

`RevitWallTargetResolver` resolves the requested `UniqueId` in the execution document and requires a `Wall`.

`RevitWallIsolationProbe`:
1. verifies `WallKind.Basic`;
2. enumerates all `Wall` instances whose `GetTypeId()` equals the target type id and records their `UniqueId`s;
3. uses the pinned release's supported Wall insert/opening API and records returned design elements;
4. casts `wall.Location` to `LocationCurve`, reads `ElementsAtJoin(0)` and `ElementsAtJoin(1)`, and records real participants other than the target;
5. runs only the explicitly supported dependency probe; uncertainty yields `WALL_ASSOCIATIVITY_UNPROVEN`.

Do not mutate, duplicate, unjoin, suppress, or temporarily detach anything during preflight.

- [ ] **Step 5: GREEN pure + pinned native build**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
python -m pytest tests/revit/test_revit_architecture.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/plugin tests/revit/test_revit_architecture.py
git commit -m "feat: fail closed on nonisolated revit walls"
```

---

## Task 7: Freeze deterministic CompoundStructure thickness planning and unit conversion

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/WallLayerSnapshot.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Execution/WallThicknessPlanner.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/WallThicknessPlannerTests.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitLengthUnitConverter.cs`

**Interfaces:**
- Consumes: requested canonical millimetres and a list of layer snapshots in native order.
- Produces:
  - `WallThicknessPlan(editableLayerIndex, requestedTotalInternal, newEditableLayerWidthInternal)`;
  - stable errors `VERTICALLY_COMPOUND_WALL_UNSUPPORTED`, `AMBIGUOUS_WALL_THICKNESS_LAYER`, `INVALID_WALL_THICKNESS`.

- [ ] **Step 1: Write RED planner tests**

Cover:
1. one editable layer + no fixed layers -> editable width becomes target total;
2. one editable layer + fixed layers -> `new = target - fixed sum`;
3. zero editable layers -> `AMBIGUOUS_WALL_THICKNESS_LAYER`;
4. two editable layers -> same error;
5. membrane layers are never selected as editable thickness layers;
6. requested total <= fixed sum -> `INVALID_WALL_THICKNESS`;
7. non-finite/zero/negative requested value -> `INVALID_WALL_THICKNESS`;
8. calculated width must be positive and finite;
9. `fixed sum + new editable width` equals requested total within the native tolerance supplied to the planner.

Use integer-like internal fixtures in the pure tests; do not encode a fake mm-to-feet constant into Core.

- [ ] **Step 2: Run RED**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj --filter WallThicknessPlannerTests
```

- [ ] **Step 3: Implement the pure planner**

Expose:

```csharp
public static WallThicknessPlan Plan(
    double requestedTotalInternal,
    IReadOnlyList<WallLayerSnapshot> layers,
    double tolerance
)
```

The planner never calls Revit and never chooses among multiple editable layers.

- [ ] **Step 4: Implement pinned-version native conversion**

`RevitLengthUnitConverter` uses the installed release's supported `UnitUtils` / millimetre unit identifier to implement:

```text
MillimetersToInternal(300.0)
InternalToMillimeters(nativeWidth)
```

The implementation is compiled only against the explicitly pinned Revit release from Task 1.

- [ ] **Step 5: Native read/write shape check**

When building a plan from a `CompoundStructure`:
- reject `IsVerticallyCompound`;
- enumerate `GetLayers()` in native order;
- classify membrane/non-editable layers;
- pass only immutable layer snapshots into `WallThicknessPlanner`;
- before transaction, clone/construct the candidate structure, set only the selected layer width, and verify candidate `GetWidth()` matches `requestedTotalInternal` within tolerance.

- [ ] **Step 6: GREEN**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
```

- [ ] **Step 7: Commit**

```powershell
git add hosts/revit/plugin
git commit -m "feat: plan deterministic revit wall thickness"
```

---

## Task 8: Commit exactly one Revit transaction and retain truthful native evidence

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost.Core/Contracts/WallThicknessEvidence.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessMutation.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallSnapshotReader.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Ipc/RequestDispatcher.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitExternalEventHandler.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/WallThicknessEvidenceTests.cs`

**Interfaces:**
- Consumes: validated `HostCommandEnvelope`, current revision, resolved isolated wall, and `WallThicknessPlan`.
- Produces: `WallThicknessEvidence` carrying wall/type identity, selected layer, width before/after, target identity/location/relationship invariants, revision before/after, and transaction/document-change attribution evidence.

- [ ] **Step 1: RED result/evidence invariants**

Assert a successful evidence object cannot be created unless:
- wall UniqueId and WallType UniqueId are non-empty;
- post width is finite/positive;
- post width equals requested width within the provided tolerance;
- `revision_after > revision_before`;
- identity/location/relationship invariant evidence is present;
- transaction attempt count is exactly one.

Also assert an idempotent replay returns the stored successful envelope without constructing a new mutation request.

- [ ] **Step 2: Run RED**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj --filter WallThicknessEvidenceTests
```

- [ ] **Step 3: Implement native success flow in exact order**

Inside `IExternalEventHandler.Execute(UIApplication)`:

```text
deserialize + validate command
compute fingerprint
idempotency lookup
resolve execution document
require expected revision
resolve exactly one Wall by UniqueId
run Basic/exclusive/isolation preflight
read CompoundStructure
build deterministic thickness plan
capture pre-state evidence
start one Revit Transaction
apply candidate via WallType.SetCompoundStructure(candidateStructure)
commit
observe/read revision owned by DocumentChanged
read WallType.GetCompoundStructure().GetWidth()
read target identity/location/relationship invariants
convert read-back width to mm
build successful evidence/result
store idempotency result
complete queued request
```

No Revit transaction starts before all preflight checks and candidate validation pass.

- [ ] **Step 4: Freeze failure phase behavior**

Before transaction commit: return stable before-commit Host failure and no `ActualDelta`.

If the transaction may have committed but the plugin loses certainty: return the Host result that the integration adapter maps to `COMMIT_STATE_UNKNOWN`; never auto-retry.

If commit is known and post-read exposes a wider effect that cannot be normalized truthfully: return a dedicated integration-stop error/evidence state such as `COMMITTED_EFFECT_UNNORMALIZABLE`; do not mislabel it `BEFORE_COMMIT` or `COMMIT_STATE_UNKNOWN`.

- [ ] **Step 5: GREEN core + native build**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/plugin
git commit -m "feat: execute isolated revit wall thickness mutation"
```

---

## Task 9: Translate Revit commit evidence into truthful Step33 ActualDelta or failure

**Files:**
- Create: `hosts/revit/sidecar/src/revit_sidecar/execution_result_adapter.py`
- Create: `hosts/revit/sidecar/tests/test_execution_result_adapter.py`

**Interfaces:**
- Consumes: admitted authority lineage, execution slice/document identity, approved semantic wall id, and Revit Host result/evidence.
- Produces:
  - `ActualDelta` only for a confirmed truthfully normalized commit;
  - `HostFailed(phase=HostFailurePhase.BEFORE_COMMIT, failure_ref="WALL_JOIN_OUTSIDE_MVP", failed_at="2026-09-01T00:00:00Z")` for actual precommit failures;
  - `HostFailed(phase=HostFailurePhase.COMMIT_STATE_UNKNOWN, failure_ref="REVIT_COMMIT_STATE_UNKNOWN", failed_at="2026-09-01T00:00:00Z")` only for actual commit uncertainty;
  - a raised integration design-stop error for known committed but unnormalizable wider effects.

- [ ] **Step 1: RED the positive projection**

A normal isolated success must yield exactly one signed change:

```python
ActualChange(
    change_kind=ActualChangeKind.MODIFY,
    semantic_id="WALL-001",
    canonical_kind="ifc:IfcWall",
    changed_aspects=(CanonicalAspect.PROPERTIES,),
    actual_change_hash="0" * 64,
)
```

and one signed `ActualDelta` with exact grant/binding/slice/changeset/scope lineage and real revision before/after.

Assert these native concepts are absent from `ActualDelta`:

```text
WallType
CompoundStructure
ElementId
Revit API
layer index
```

- [ ] **Step 2: RED wider-effect/failure cases**

Freeze:
- normal BRep/solid regeneration entailed only by thickness -> no extra `GEOMETRY`;
- independently observed placement/relationship/another entity -> include a corresponding extra `ActualChange` when it can be normalized;
- known commit + unnormalizable wider effect -> raise `COMMITTED_EFFECT_UNNORMALIZABLE`;
- preflight failure -> `BEFORE_COMMIT`;
- uncertain commit -> `COMMIT_STATE_UNKNOWN`.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_execution_result_adapter.py -q
```

- [ ] **Step 4: Implement with Step33-owned hashing**

Use only:

```python
compute_actual_change_hash(change)
compute_actual_delta_hash(delta)
```

from `design_execution_reconciliation`. Do not copy their hash bodies.

- [ ] **Step 5: GREEN**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_execution_result_adapter.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/sidecar
git commit -m "feat: normalize revit execution evidence"
```

---

## Task 10: Prove the provider-neutral Revit reconciliation chain offline

**Files:**
- Create: `tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py`

**Interfaces:**
- Consumes: existing `SET_WALL_THICKNESS_V1`, Steps 27-32 fixtures/pipeline, Revit `ProviderBinding`, Revit `ActualDelta`, and reconstructed Revit facts.
- Produces: the same Step33 statuses already proven by Step34 AutoCAD.

- [ ] **Step 1: Build the Revit transaction fixture through existing Steps 23/27-32**

Follow `tests/integration/test_step34_autocad_wall_thickness_reconciliation.py`, changing only Host/provider-native evidence:

```text
HostRuntimeRef("revit", "HOST-REVIT-A", "DOC-REVIT")
provider_server = "revit-local"
provider_tool = "revit.set_wall_thickness"
native_id = "wall-unique-id"
native_kind = "Wall"
provider_arguments thickness = 300 mm
```

Keep:
- canonical operation `set_wall_thickness.v1`;
- `CanonicalAspect.PROPERTIES`;
- the real Step28 boundary;
- real ChangeSet/ExecutionPlan/Gateway authorization APIs.

- [ ] **Step 2: RED the successful path**

Construct a signed Revit `ActualDelta` and a real `VerificationEvidenceBundle` whose subject proves:

```python
classification=("ifc:IfcWall",)
properties={
    "dsp:WallThickness": {"value": 300.0, "unit": "mm"}
}
```

Drive:

```text
create_saga
reserve_slice_admission
confirm_slice_admitted
record_host_commit
begin_reconciliation
compare_scope
record_scope_result
verify_semantics
record_verification_result
```

Expected:
- `ScopeComparisonStatus.WITHIN_SCOPE`;
- `VerificationStatus.PASSED`;
- final `ExecutionSagaStatus.SUCCEEDED`.

- [ ] **Step 3: RED negative reconciliation cases**

In the same file:
- reconstructed `299 mm` -> `VerificationStatus.FAILED`, Slice `VERIFY_FAILED`, Saga not `SUCCEEDED`;
- truthful extra `GEOMETRY` aspect -> `SCOPE_BREACH`, Saga not `SUCCEEDED`;
- another semantic entity -> scope breach;
- Host success flag without post-execution semantic evidence cannot produce `PASSED`.

- [ ] **Step 4: Run RED**

```powershell
python -m pytest tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py -q
```

Expected: fail until Revit adapters/mappings from Tasks 3-9 are wired.

- [ ] **Step 5: Minimal integration wiring only**

Reuse existing Step33 public classes:
`ActualChange`, `ActualDelta`, `ScopeComparator`, `VerificationEvidenceBundle`, `SemanticVerificationRequest`, `ExecutionReconciliationService`.

Do not modify `platform/execution_reconciliation/**`, Step31, Step32, or Step37 production code to make the fixture pass.

- [ ] **Step 6: GREEN with AutoCAD parity regression**

```powershell
python -m pytest `
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py `
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py `
  -q
```

- [ ] **Step 7: Commit**

```powershell
git add tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py
git commit -m "test: prove revit wall thickness reconciliation parity"
```

---

## Task 11: Add the controlled live Revit acceptance harness and runbook

**Files:**
- Create: `tests/integration/test_phase_h_revit_wall_thickness_live.py`
- Create: `docs/runbooks/revit-wall-thickness-gap-closure.md`

**Interfaces:**
- Consumes: one running pinned Revit instance with the plugin loaded and one controlled RVT fixture.
- Produces: real-host evidence for the positive 300 mm mutation and required precommit/retry negative cases.

- [ ] **Step 1: Write the live test gate**

The test is skipped unless all are present:

```text
DSP_REVIT_LIVE=1
DSP_REVIT_VERSION
DSP_REVIT_TFM
DSP_REVIT_API_DIR
DSP_REVIT_PIPE
DSP_REVIT_FIXTURE
```

A normal CI run must report this test as skipped, not simulated green.

- [ ] **Step 2: Freeze fixture assertions before any mutation**

The fixture must prove:
- exactly one approved Basic Wall target;
- target pre-read is not 300 mm;
- target WallType is exclusive;
- supported CompoundStructure shape has exactly one editable non-membrane layer;
- no supported insert/opening;
- `ElementsAtJoin(0/1)` has no external wall participant;
- no supported dependency probe indicates wider mutation.

If any assertion fails, the live acceptance test stops without mutating the model.

- [ ] **Step 3: Add positive live path**

Send the real HostCommand with 300 mm and assert:
1. exactly one Revit transaction commits;
2. post-read native wall width converts to 300 mm;
3. revision advances from the DocumentChanged-owned counter;
4. sidecar emits Revit facts mapping to `ifc:IfcWall + dsp:WallThickness=300 mm`;
5. `ActualDelta` is only target `MODIFY / PROPERTIES`;
6. Step33 scope result is `WITHIN_SCOPE`;
7. SemanticVerifier is `PASSED`;
8. Saga is `SUCCEEDED`.

- [ ] **Step 4: Add required live negative scenarios**

The runbook defines deterministic fixture variants/procedures and the test asserts:
- second unapproved wall shares WallType -> `SHARED_WALL_TYPE_OUTSIDE_SCOPE`, no transaction;
- hosted insert/opening or actual endpoint join -> before-commit reject, no transaction;
- stale expected revision -> no transaction;
- same idempotency key/fingerprint replay -> same success result, no second transaction/revision increment;
- same key/different fingerprint -> `IDEMPOTENCY_KEY_CONFLICT`, no second transaction.

The Step33 wrong-width and extra-aspect negatives remain provider-neutral tests from Task 10; do not intentionally corrupt a live Revit model merely to synthesize them.

- [ ] **Step 5: Document exact machine baseline procedure**

The runbook requires the operator to record:
- exact Revit product/build shown on the acceptance machine;
- official runtime/TFM for that exact release;
- exact `RevitAPI.dll` directory;
- plugin build command;
- `.addin` deployment location used locally;
- RVT fixture path;
- Named Pipe identifier;
- commands and captured results for every live acceptance case.

No machine-specific path/value is committed as a universal default.

- [ ] **Step 6: Run the live RED/GREEN cycle on the real host**

First run before native mutation wiring is complete or before loading the new plugin must fail/skip for a concrete missing behavior, not pass through a fake.

Final live command:

```powershell
$env:DSP_REVIT_LIVE = "1"
python -m pytest tests/integration/test_phase_h_revit_wall_thickness_live.py -vv -s
```

Expected final result on the pinned Revit machine: positive and negative live cases pass with recorded evidence.

- [ ] **Step 7: Commit**

```powershell
git add tests/integration/test_phase_h_revit_wall_thickness_live.py docs/runbooks/revit-wall-thickness-gap-closure.md
git commit -m "test: add live revit wall thickness acceptance"
```

---

## Task 12: Add Revit-free CI, run the full regression gate, and close the gap only on evidence

**Files:**
- Create: `.github/workflows/phase-h-revit-wall-thickness.yml`
- Modify only if execution evidence needs appending: `docs/runbooks/revit-wall-thickness-gap-closure.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: an ordinary CI gate for Revit-free tests plus a documented external live Revit acceptance gate.

- [ ] **Step 1: Add the CI RED**

The workflow runs on repository-supported Python and .NET hosts and executes only:
- Revit-free Core .NET tests;
- Revit sidecar tests;
- Revit architecture guard;
- Revit enterprise mapping tests;
- offline Revit Step33 reconciliation;
- existing AutoCAD Step34 reconciliation parity.

It must not install fake Autodesk assemblies, hard-code a Revit version, or report live Revit acceptance from GitHub-hosted CI.

- [ ] **Step 2: Run focused offline gate locally**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
python -m pytest `
  hosts/revit/sidecar/tests `
  tests/revit `
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py `
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py `
  -q
```

- [ ] **Step 3: Run repository architecture/lint gates**

Use the repository's current Ruff command against all changed Python files, then run the existing architecture guard suites including Step36 and Step37:

```powershell
python -m pytest `
  tests/integration/test_step36_architecture.py `
  tests/integration/test_step37_architecture.py `
  tests/revit/test_revit_architecture.py `
  -q
```

- [ ] **Step 4: Run the full repository Python suite**

```powershell
python -m pytest -q
```

Record exact pass/skip/fail counts. Existing live AutoCAD/Revit skips are acceptable only when their documented external prerequisites are absent; any non-live regression must be fixed before closeout.

- [ ] **Step 5: Run the pinned native build and live Revit gate**

On the acceptance machine:

```powershell
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"

$env:DSP_REVIT_LIVE = "1"
python -m pytest tests/integration/test_phase_h_revit_wall_thickness_live.py -vv -s
```

Do not call the Phase H Revit gap closed unless both native build and live gate have fresh passing evidence.

- [ ] **Step 6: Verify production-boundary diff**

Run:

```powershell
git diff --name-only main...HEAD
```

Confirm production changes are limited to:
- `hosts/revit/**`;
- the two enterprise mapping entries;
- focused tests/docs/workflow.

Confirm no production changes under:
- D4;
- `platform/impact`;
- `platform/approval_scope`;
- `platform/changeset`;
- `platform/execution_planning`;
- `platform/provider_binding`;
- `platform/gateway_authorization`;
- `platform/execution_reconciliation`;
- `platform/execution_coordination`;
- `hosts/autocad`.

Any production change there requires a design re-open before merge.

- [ ] **Step 7: Append execution evidence to the runbook**

Record:
- exact branch/head;
- exact Revit product/build + TFM;
- native build result;
- focused offline test counts;
- full repository test counts;
- live acceptance counts;
- positive 300 mm before/after evidence;
- shared-type, join/insert, stale revision, and replay evidence;
- `WITHIN_SCOPE`, `PASSED`, and final `SUCCEEDED` evidence.

- [ ] **Step 8: Commit closeout evidence/workflow**

```powershell
git add .github/workflows/phase-h-revit-wall-thickness.yml docs/runbooks/revit-wall-thickness-gap-closure.md
git commit -m "ci: verify phase h revit gap closure"
```

---

## Implementation Stop Conditions

Execution must stop and return to design review instead of improvising if any of these occurs:

1. A real Revit release cannot compile the Native project without changing shared/Core semantic contracts.
2. Thickness mutation of the controlled isolated fixture produces another canonical entity/aspect that is not already truthfully reportable by `ActualDelta`.
3. A transaction is confirmed committed but the integration boundary cannot truthfully normalize the observed wider effect.
4. Revit requires the platform Core to understand `WallType`, `CompoundStructure`, `OST_Walls`, `ExternalEvent`, internal units, or Revit transaction APIs.
5. Step31/32/33/37 public APIs cannot carry the exact existing lineage/failure semantics without production changes.
6. The only way to pass is to duplicate/reassign a WallType, hide a real join/insert/association, silently roll back, or broaden the approved scope.
7. The installed Revit version/runtime cannot be identified exactly enough to choose the official native target framework.
8. A supposed join-isolation implementation only checks whether joins are allowed rather than reading actual join participants.

## Final Acceptance Matrix

The implementation is complete only when fresh evidence proves every row:

| Gate | Required result |
|---|---|
| Real Revit Host under `hosts/revit` | PASS |
| Exact existing `set_wall_thickness.v1` reused | PASS |
| Canonical effects remain `PROPERTIES` | PASS |
| Native API confined to plugin `Native/**` | PASS |
| Named Pipe only; no Revit gRPC expansion | PASS |
| ExternalEvent owns async API entry | PASS |
| DocumentChanged owns revision increment | PASS |
| Durable target identity uses `Element.UniqueId` | PASS |
| Exactly one target enforced | PASS |
| Shared WallType rejected before commit | PASS |
| Hosted insert/opening rejected before commit | PASS |
| Actual wall join participant rejected before commit | PASS |
| Unsupported associativity fails closed | PASS |
| Deterministic single editable layer math | PASS |
| No hidden WallType duplication/CREATE | PASS |
| Real 300 mm mutation commits once | PASS |
| Native post-read is 300 mm | PASS |
| Idempotent replay performs no second transaction | PASS |
| Revit facts map to `ifc:IfcWall + dsp:WallThickness` | PASS |
| Truthful `ActualDelta` is target `MODIFY / PROPERTIES` | PASS |
| `ScopeComparator == WITHIN_SCOPE` | PASS |
| `SemanticVerifier == PASSED` | PASS |
| Saga reaches `SUCCEEDED` only after both gates | PASS |
| Wrong reconstructed width -> `VERIFY_FAILED` | PASS |
| Extra canonical aspect/entity -> `SCOPE_BREACH` | PASS |
| Stale revision -> no mutation | PASS |
| Same key/different fingerprint -> conflict/no mutation | PASS |
| Existing AutoCAD Step34 parity remains green | PASS |
| Step27-33/37 production semantics unchanged | PASS |
| Full non-live repository regression green | PASS |
| Pinned Revit native build + live acceptance green | PASS |
