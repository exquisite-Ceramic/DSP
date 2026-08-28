# AutoCAD Native Fact Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only AutoCAD native snapshot extraction path and a thin sidecar adapter that emits the frozen Step 18 `NormalizedDesignFactBatch` without introducing Step 20 semantic mapping.

**Architecture:** The AutoCAD plugin reads requested entities inside the existing Autodesk-only `Native/` boundary and returns one Host-local snapshot batch at one document revision through the existing `HostCommandResult.payload` path. The Python sidecar normalizes that AutoCAD-specific payload into `design_fact_contracts.NormalizedDesignFactBatch`; it preserves handle/native kind/layer/bounds evidence and never interprets `A-WALL` as IFC or enterprise meaning.

**Tech Stack:** C# AutoCAD .NET plugin source, Python 3.11, pytest, existing `host_contracts`, frozen `design_fact_contracts`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-autocad-native-fact-extractor-design.md`

## Global Constraints

- AutoCAD native SDK access remains confined to `hosts/autocad/plugin/AutoCAD.AgentHost/Native/*` according to ADR-001.
- `NormalizedDesignFact` / `NormalizedDesignFactBatch` from Step 18 MUST NOT be modified to make Step 19 easier.
- `host_type` is exactly `autocad`.
- `producer` is exactly `autocad.sidecar.design_fact_adapter.v1`.
- Layer evidence uses `source_scheme="autocad.layer"` and `source_code=<actual layer>`.
- Step 19 MUST NOT contain `A-WALL -> IfcWall`, `ifc:IfcWall`, Metro mapping, enterprise mapping, Semantic Service behavior, or D5 reconstruction behavior.
- One extraction response represents one frozen document revision; every emitted fact copies that revision to `source_revision`.
- Requested malformed, missing, erased, or unreadable handles fail closed rather than being silently omitted.
- Empty `handles` is valid and produces an empty normalized batch.
- `fact_id` is SHA-256 over the UTF-8 canonical key `autocad-design-fact-v1\n<document_id>\n<source_revision>\n<native_id>\n<fact_kind>\n<predicate>`, encoded as lowercase hexadecimal.
- No new Host MCP or Semantic MCP tool is introduced in Step 19; the proof path is existing HostCommand READ plus a typed sidecar entry point.

---

### Task 1: Freeze the Python snapshot-to-NDF adapter behavior

**Files:**
- Create: `tests/contracts/test_autocad_design_fact_adapter.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py`
- Modify: `hosts/autocad/sidecar/pyproject.toml`

**Interfaces:**
- Consumes: Step 18 `DesignFactHostRef`, `NativeSubjectRef`, `NormalizedDesignFact`, `NormalizedDesignFactBatch`, `FactKind`, `ValueType` from `design_fact_contracts`.
- Produces: `DesignFactAdapter.normalize_snapshot(payload: Mapping[str, Any]) -> NormalizedDesignFactBatch` and `deterministic_fact_id(...) -> str`.

- [ ] Write failing tests with an empty batch and one `A31/LWPOLYLINE/A-WALL` entity containing bounds.
- [ ] Run `PYTHONPATH=. pytest -q tests/contracts/test_autocad_design_fact_adapter.py` and verify RED because the module is absent.
- [ ] Implement strict payload validation; reject unknown batch/entity fields and malformed values rather than coercing.
- [ ] Emit facts in deterministic order: `IDENTITY/native_kind`, `CLASSIFICATION/layer`, optional `BOUNDS/geometric_extents`.
- [ ] Implement fact IDs exactly as:

```python
def deterministic_fact_id(document_id, source_revision, native_id, fact_kind, predicate):
    canonical = "\n".join([
        "autocad-design-fact-v1",
        document_id,
        str(source_revision),
        native_id,
        fact_kind.value,
        predicate,
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- [ ] Freeze producer `autocad.sidecar.design_fact_adapter.v1` and provenance `autocad://<host_instance_id>/<urlquoted-document-id>/<native_id>@<revision>`.
- [ ] Prove A-WALL remains `source_scheme="autocad.layer"`, `source_code="A-WALL"`, with no `semantic_id` or `ifc:IfcWall`.
- [ ] Add fail-closed tests for blank identities, invalid revision, non-array entities, unknown fields, blank native fields, malformed bounds, and non-finite bounds numbers.
- [ ] Run the adapter tests GREEN.
- [ ] Commit `feat(autocad): normalize native snapshots into design facts`.

### Task 2: Add the Host READ command path without exposing Autodesk SDK objects

**Files:**
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADNativeFactApi.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Design/ExtractNativeSnapshotHandler.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs`
- Create: `tests/contracts/test_autocad_native_fact_architecture.py`

**Interfaces:**
- Produces Host READ operation `design.extract_native_snapshot` with payload `{hostInstanceId, documentId, revision, entities}`.

- [ ] Write source tests requiring the new files, command registration, Native delegation, and absence of Autodesk references outside `Native/`.
- [ ] Verify RED.
- [ ] In `AutoCADNativeFactApi.cs`, generate one process/session id via `private static readonly string HostInstanceId = $"autocad-{Guid.NewGuid():N}";`.
- [ ] Validate/deduplicate requested handles preserving first-seen order.
- [ ] Freeze document id and revision, use one read transaction, resolve every requested handle, and fail closed on unresolved/erased/unreadable entities.
- [ ] Capture `nativeId=Handle`, `nativeKind=entity.GetRXClass().DxfName`, `layer=entity.Layer`, and optional geometric extents.
- [ ] Implement `ExtractNativeSnapshotHandler` with command type `design.extract_native_snapshot`, READ-only validation, existing document lock, Native delegation, and JSON payload serialization.
- [ ] Register `new Design.ExtractNativeSnapshotHandler()`.
- [ ] Prove source contains no `A-WALL`, `ifc:IfcWall`, Semantic Service, Metro, Enterprise mapping, or `SemanticId` logic.
- [ ] Run architecture tests GREEN and commit `feat(autocad): extract host-native entity snapshots`.

### Task 3: Wire the typed sidecar extraction path through existing HostCommand transport

**Files:**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py`
- Create: `tests/integration/test_autocad_native_fact_command.py`

**Interfaces:**
- Produces `CommandDispatcher.extract_design_facts(handles: list[str]) -> NormalizedDesignFactBatch`.

- [ ] Write fake-transport test that calls `extract_design_facts(["A31"])` and asserts outgoing READ HostCommand operation/arguments.
- [ ] Verify RED because the method does not exist.
- [ ] Add `self._design_facts = DesignFactAdapter()` and implement the typed method using existing `HostAdapter.send_command`.
- [ ] Raise with Host error message on non-OK result; let snapshot contract errors propagate.
- [ ] Prove the normalized result contains identity/classification/bounds evidence.
- [ ] Add a test that `build_tool_definitions()` still contains neither `design.extract_native_snapshot` nor `design.extract_facts`, proving no MCP expansion.
- [ ] Run Task 1 + integration tests GREEN and commit `feat(autocad): add typed design fact extraction path`.

### Task 4: Add Step 19 CI gating and run relevant regression

**Files:**
- Modify: `.github/workflows/normalized-design-fact-contract.yml` or create the smallest dedicated AutoCAD native-fact workflow if clearer.

- [ ] Add path filters for the new plugin/sidecar/tests.
- [ ] Add pure CI command:

```bash
PYTHONPATH=. pytest -q \
  tests/contracts/test_autocad_design_fact_adapter.py \
  tests/contracts/test_autocad_native_fact_architecture.py \
  tests/integration/test_autocad_native_fact_command.py
```

- [ ] Run frozen Step 18 tests: `PYTHONPATH=. pytest -q contracts/python/tests`.
- [ ] Run relevant Python regression: `contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service`.
- [ ] Run `.NET` Step 18 regression: `dotnet test contracts/dotnet/DesignFactContracts.Tests/DesignFactContracts.Tests.csproj --configuration Release`.
- [ ] Run leakage scan proving no new AutoCAD branch in Semantic Service/D5 and no IFC/enterprise mapping in extractor.
- [ ] Commit `ci(autocad): gate native fact extraction`.

### Task 5: Final Step 19 acceptance review and PR preparation

- [ ] Compare branch to `main`; diff must be limited to Step 19 docs, AutoCAD plugin native/read path, thin sidecar adapter, tests, and CI.
- [ ] Verify synthetic A31/LWPOLYLINE/A-WALL@rev7 becomes identity + `autocad.layer/A-WALL` classification + optional bounds, with no SemanticId/IfcWall.
- [ ] Verify final CI at the actual branch head; do not reuse evidence from an earlier commit.
- [ ] Prepare PR against `main` stating Step 19 only, one-revision semantics, fail-closed behavior, no MCP expansion, and no Step 20-22 work.
- [ ] Keep PR unmerged until the user explicitly requests merge.
