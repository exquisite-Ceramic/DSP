# Step36 OFFSET CREATE / CreationRule / SCOPE_BREACH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit canonical CREATE authority for `offset.v1`, carry it without widening through Steps 27-32, execute one real AutoCAD offset creation, and prove Step33 accepts exactly one authorized creation while two creations against `max_count=1` produce `CREATION_COUNT_EXCEEDED -> SCOPE_BREACH`.

**Architecture:** CREATE/DELETE remain separate from `CanonicalAspect`. `offset.v1` carries `CanonicalExistenceEffect.CREATE` plus the closed creation envelope `ifc:IfcWall / max_count=1 / RULE-OFFSET-WALL`. Step27 carries user/agent existence intent, Step28 admits only equal-or-narrower `CreationRule` authority, Step29 binds exactly one rule into the immutable ChangeSet, Step30 carries the existence effect into the hashed execution unit and selects a predeclared slice scope, Step31/32 remain unchanged lineage/admission layers, and Step33 compares provider-neutral `ActualChange.CREATE` evidence. AutoCAD native concepts stay in Provider/Host code.

**Tech Stack:** Python 3.11, pytest/pytest-asyncio, JSON Schema, DSP Steps 23/27-33 Python packages, AutoCAD 2025 .NET 8 plugin, Autodesk AutoCAD .NET API, C#/.NET 8, MCP 2.x.

**Spec:** `docs/superpowers/specs/2026-08-31-step36-offset-create-scope-breach-design.md`

## Frozen constraints

- `CanonicalAspect("CREATE")` and `CanonicalAspect("DELETE")` must remain invalid.
- Step36 enables CREATE only; DELETE remains deny-by-default.
- `offset.v1`: one existing source target, positive `distance` in `mm`, `side_point` in `mm`, `effects=()`, `existence_effects=(CREATE,)`.
- Creation envelope: `entity_kinds=("ifc:IfcWall",)`, `max_count=1`, `required_derivation="RULE-OFFSET-WALL"`.
- Step28 never widens a requested CreationRule.
- Step29 `scope_rule_ids` remains generic, but each ID must resolve to exactly one Step28 rule across Existing/Creation/Deletion namespaces.
- Step30 routes the source entity only; it never invents a route or identity for the not-yet-created entity.
- Empty existence fields must not change legacy semantic hashes for `move.v1` and `set_wall_thickness.v1` in Steps 23/27/28/29/30.
- ExistingEntityRule fingerprints must remain byte-for-byte compatible with the pre-Step36 payload.
- Step31 and Step32 production code are read-only for this plan. If the public API cannot carry the exact Step36 lineage, stop implementation and return to design instead of editing Step31/32 ad hoc.
- AutoCAD supports only explicit millimetre documents and exactly one selected `Polyline`/`LWPOLYLINE` source fixture on `A-WALL`.
- Host wire carries native target refs plus distance/side point only; it must not carry Step28 rules, Step32 grants, `ifc:*`, or a fabricated created semantic ID.
- Real AutoCAD C# mutation code may be written only after an observed live RED reaches the Host with unknown `offset.v1` behavior.
- Step36 does not introduce CREATE-specific SemanticVerifier syntax or a new semantic-identity assignment protocol.

---

## Task 1: Add canonical existence effects and `offset.v1`

**Files**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Modify: `platform/orchestrator/src/design_orchestrator/parameter_binder.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Test: `tests/orchestrator/test_canonical_operations.py`
- Test: `tests/orchestrator/test_operation_resolver.py`
- Test: `tests/orchestrator/test_parameter_binder.py`

**Public interfaces**

```python
class CanonicalExistenceEffect(str, Enum):
    CREATE = "CREATE"
    DELETE = "DELETE"

@dataclass(frozen=True, slots=True)
class CanonicalCreationContract:
    entity_kinds: tuple[str, ...]
    max_count: int
    required_derivation: str
```

Append defaulted fields to `CanonicalOperationDefinition`:

```python
existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
creation_contract: CanonicalCreationContract | None = None
```

`ResolvedOperation` gains `existence_effects`, sourced from the **canonical definition**, not provider metadata. `llm_action_space()` exposes it as a list so CREATE is visible as platform-owned canonical semantics.

- [ ] Write RED tests importing `CanonicalExistenceEffect`, `CanonicalCreationContract`, `OFFSET_V1`, and asserting `CanonicalAspect("CREATE")` is not involved anywhere.
- [ ] Freeze `OFFSET_V1` exactly:

```python
assert OFFSET_V1.canonical_operation == "offset.v1"
assert OFFSET_V1.version == "1.0.0"
assert OFFSET_V1.effects == ()
assert OFFSET_V1.existence_effects == (CanonicalExistenceEffect.CREATE,)
assert OFFSET_V1.creation_contract == CanonicalCreationContract(
    entity_kinds=("ifc:IfcWall",),
    max_count=1,
    required_derivation="RULE-OFFSET-WALL",
)
```

The schema is exactly one source target plus:

```json
{
  "distance": {"value": 300.0, "unit": "mm"},
  "side_point": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"}
}
```

with `targets.maxItems = 1`, `distance.value > 0`, literal `mm`, finite values enforced by binder/provider validation, `targets=CONTEXT`, `distance/side_point=INTENT`, canonical entity constraint `ifc:IfcWall`, and empty verification contract.

- [ ] Run RED:

```powershell
python -m pytest tests/orchestrator/test_canonical_operations.py tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_parameter_binder.py -q
```

Expected: missing symbols/fields/definition.

- [ ] Implement enum/contract normalization. A MODEL_OPERATION must have at least one existing-entity effect or existence effect. CREATE requires `creation_contract`; a creation contract without CREATE is invalid. DELETE has no creation contract.
- [ ] Add `OFFSET_V1` to `MVP_CANONICAL_OPERATIONS`; add `OFFSET_V1_BINDING_RECIPE` with only one deterministic `targets -> CONTEXT_SELECTION` recipe; export public symbols.
- [ ] Extend resolver output with canonical `existence_effects` without comparing provider schemas/native constraints.
- [ ] GREEN:

```powershell
python -m pytest tests/orchestrator -q
```

- [ ] Commit:

```powershell
git add platform/orchestrator/src/design_orchestrator tests/orchestrator
git commit -m "feat: define canonical offset create action"
```

---

## Task 2: Carry CREATE intent through Step27 without legacy fingerprint drift

**Files**
- Modify: `platform/impact/src/design_impact/contracts.py`
- Modify: `platform/impact/src/design_impact/analyzer.py`
- Test: `tests/impact/test_step27_contracts.py`
- Test: `tests/impact/test_step27_analyzer.py`

Append to `IntentBoundary`:

```python
allowed_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
```

- [ ] RED contract test: duplicate strings normalize to `(CanonicalExistenceEffect.CREATE,)`.
- [ ] RED fingerprint test: use the same legacy fixture and a test-local helper that reproduces the **pre-Step36 intent payload** exactly:

```python
def legacy_intent_payload(intent):
    return {
        "direct_targets": list(intent.direct_targets),
        "allowed_canonical_effects": list(intent.allowed_canonical_effects),
        "allowed_derived_rule_refs": list(intent.allowed_derived_rule_refs),
    }
```

Recompute the old analysis payload/hash in the test and assert the new implementation with empty `allowed_existence_effects` equals it. A second fixture with CREATE must differ.
- [ ] Run RED:

```powershell
python -m pytest tests/impact/test_step27_contracts.py tests/impact/test_step27_analyzer.py -q
```

- [ ] Implement normalized enum tuple and conditional fingerprint serialization:

```python
intent_payload = legacy_intent_payload(intent)
if intent.allowed_existence_effects:
    intent_payload["allowed_existence_effects"] = [v.value for v in intent.allowed_existence_effects]
```

Never serialize an empty key into legacy hash material.
- [ ] GREEN:

```powershell
python -m pytest tests/impact -q
```

- [ ] Commit:

```powershell
git add platform/impact/src/design_impact tests/impact
git commit -m "feat: carry creation intent through impact analysis"
```

---

## Task 3: Admit a closed CreationRule in Step28

**Files**
- Modify: `platform/approval_scope/src/design_approval_scope/contracts.py`
- Modify: `platform/approval_scope/src/design_approval_scope/planner.py`
- Modify: `platform/approval_scope/src/design_approval_scope/hashing.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Test: `tests/approval_scope/test_step28_contracts.py`
- Test: `tests/approval_scope/test_step28_planner.py`
- Test: `tests/approval_scope/test_step28_hashing.py`
- Test: `tests/approval_scope/test_step28_integrity.py`

Extend `CanonicalEffectEvidence` with defaulted `allowed_existence_effects` and `creation_contract`. `allowed_aspects=()` is valid only when existence authority is non-empty.

Add deterministic public helper:

```python
def creation_rule_id(rule: CreationRule) -> str:
    material = canonical semantic payload excluding rule_id
    return f"CR-{sha256(material).hexdigest()[:12]}"
```

- [ ] RED: a valid CREATE-only evidence object can have `allowed_aspects=()`; evidence with neither aspect nor existence authority fails.
- [ ] RED: current planner rejects a valid requested CreationRule with `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`.
- [ ] Valid requested rule fixture:

```python
CreationRule(
    rule_id="REQUEST-1",
    canonical_operation="offset.v1",
    source_selector=EntitySelector(entities=("WALL-001",)),
    entity_kinds=("ifc:IfcWall",),
    max_count=1,
    required_derivation="RULE-OFFSET-WALL",
)
```

- [ ] Parameterize fail-closed cases: wrong operation; source selector includes `WALL-999`; kind adds `ifc:IfcDoor`; `max_count=None`; `max_count=2`; wrong derivation; CREATE absent from canonical evidence; CREATE absent from intent; creation rule omitted from slice scope. Expected stable Step28 codes are `SCOPE_RULE_INVALID` or `SCOPE_SLICE_RULE_INVALID` as appropriate. DELETE still returns `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`.
- [ ] Run RED:

```powershell
python -m pytest tests/approval_scope/test_step28_contracts.py tests/approval_scope/test_step28_planner.py -q
```

- [ ] Implement admission: requested rule must exactly match operation/direct source semantics, kinds must be subset of canonical kinds, `max_count` must be present and `<=` canonical count, derivation must exactly match. Rebuild the admitted rule using deterministic `CR-*` construction ID; do not alter authority fields.
- [ ] Validate closed-world slice coverage separately for existing and creation rule IDs; every admitted rule must be covered, no unknown rule IDs permitted.
- [ ] Preserve Step28 hash compatibility by leaving old `_canonical_effect_payload()` / `_intent_payload()` output unchanged when new fields are empty and conditionally adding only non-empty existence data. Existing `_creation_payload()` remains the rule semantic body.
- [ ] Add legacy Step28 hash-equivalence test using a pre-Step36 payload helper, plus Step36 sensitivity tests for `max_count` and derivation.
- [ ] GREEN:

```powershell
python -m pytest tests/approval_scope -q
```

- [ ] Commit:

```powershell
git add platform/approval_scope/src/design_approval_scope tests/approval_scope
git commit -m "feat: admit closed creation scope"
```

---

## Task 4: Bind CREATE authority into Step29 ChangeSet semantics

**Files**
- Modify: `platform/changeset/src/design_changeset/contracts.py`
- Modify: `platform/changeset/src/design_changeset/hashing.py`
- Modify: `platform/changeset/src/design_changeset/builder.py`
- Modify: `platform/changeset/src/design_changeset/integrity.py`
- Test: `tests/changeset/test_step29_contracts.py`
- Test: `tests/changeset/test_step29_hashing.py`
- Test: `tests/changeset/test_step29_builder.py`
- Test: `tests/changeset/test_step29_integrity.py`

Append defaults:

```python
CanonicalOperationContractEvidence.existence_effects = ()
CanonicalOperationContractEvidence.creation_contract = None
CanonicalChangeOperation.expected_existence_effects = ()
```

CREATE-only operations may have `effects=()` / `expected_effects=()` only when existence effects are non-empty.

- [ ] RED fingerprint test: `compute_scope_rule_fingerprint(existing_rule)` equals a test-local copy of the exact pre-Step36 Existing payload; `CreationRule` currently fails because the function assumes `.selector/.allowed_aspects`.
- [ ] RED builder test: exact `offset.v1` contract + one Step28 CreationRule must produce root operation with:

```python
expected_effects == ()
expected_existence_effects == (CanonicalExistenceEffect.CREATE,)
scope_rule_ids == (creation_rule.rule_id,)
validation_tasks == ()
```

A second equally compatible CreationRule must fail `CHANGESET_SCOPE_MEMBERSHIP_AMBIGUOUS`, never choose one by sort order.
- [ ] Run RED:

```powershell
python -m pytest tests/changeset/test_step29_hashing.py tests/changeset/test_step29_builder.py -q
```

- [ ] Make `compute_scope_rule_fingerprint()` type-aware. Existing rule branch must retain the old payload byte-for-byte. Creation branch must hash:

```python
{
  "rule_kind": "CREATION",
  "canonical_operation": rule.canonical_operation,
  "source_selector": selector_payload,
  "entity_kinds": list(rule.entity_kinds),
  "max_count": rule.max_count,
  "required_derivation": rule.required_derivation,
}
```

Construction `rule_id` is excluded. Deletion receives a typed payload for collision safety but remains unadmitted by Step36.
- [ ] Extend `compute_contract_definition_fingerprint()` and `compute_operation_semantic_hash()` by adding existence keys **only when non-empty**. Empty/default calls must return the same legacy digest as before.
- [ ] Implement `_cover_creation_scope()`: exact operation; explicit source selector exactly covers bound source targets; rule envelope is within exact contract; exactly one compatible rule. Zero => `CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED`; >1 => `CHANGESET_SCOPE_MEMBERSHIP_AMBIGUOUS`.
- [ ] Keep `_canonical_validation_task()` behavior: empty verification contract returns `None`.
- [ ] Update `integrity.py` recomputation to include conditional contract/operation existence fields.
- [ ] GREEN:

```powershell
python -m pytest tests/changeset -q
```

- [ ] Commit:

```powershell
git add platform/changeset/src/design_changeset tests/changeset
git commit -m "feat: bind creation authority into changesets"
```

---

## Task 5: Carry CREATE into Step30 ExecutionUnit and slice selection

**Files**
- Modify: `platform/execution_planning/src/design_execution_planning/contracts.py`
- Modify: `platform/execution_planning/src/design_execution_planning/hashing.py`
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Modify: `platform/execution_planning/src/design_execution_planning/integrity.py`
- Test: `tests/execution_planning/test_step30_planner.py`
- Test: `tests/execution_planning/test_step30_scope_selection.py`
- Test: `tests/execution_planning/test_step30_hashing.py`
- Test: `tests/execution_planning/test_step30_integrity.py`

Append:

```python
ExecutionUnit.expected_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
```

- [ ] RED: an offset ChangeSet using one CreationRule currently fails `_validate_scope_binding()` because it indexes only Existing rules and/or fails because `expected_effects` is empty.
- [ ] Assert source routing only:

```python
unit.targets == ("WALL-001",)
unit.expected_effects == ()
unit.expected_existence_effects == (CanonicalExistenceEffect.CREATE,)
```

- [ ] Add duplicate-ID negative: same `rule_id` reused across Existing and Creation rules => `EXECUTION_SCOPE_MISMATCH`.
- [ ] Add slice negative: correct document but CreationRule ID absent from the union => `EXECUTION_SLICE_SCOPE_UNCOVERED`.
- [ ] Run RED:

```powershell
python -m pytest tests/execution_planning/test_step30_planner.py tests/execution_planning/test_step30_scope_selection.py -q
```

- [ ] Build one closed rule index across `existing_entity_rules + creation_rules + deletion_rules`; reject duplicate IDs across kinds. `_source_operation_hash()` uses the generic Step29 rule fingerprint.
- [ ] `_select_slice_scope()` tests required operation rule IDs against:

```python
set(candidate.existing_rule_ids) |
set(candidate.creation_rule_ids) |
set(candidate.deletion_rule_ids)
```

Keep least-authority surplus/tie-breaking unchanged.
- [ ] Copy `operation.expected_existence_effects` into the ExecutionUnit. `compute_execution_unit_hash()` adds `expected_existence_effects` only when non-empty; a test-local pre-Step36 helper proves a legacy move unit digest is unchanged.
- [ ] Update `integrity.py` to normalize/recompute the new field and exact unit hash.
- [ ] GREEN:

```powershell
python -m pytest tests/execution_planning -q
```

- [ ] Commit:

```powershell
git add platform/execution_planning/src/design_execution_planning tests/execution_planning
git commit -m "feat: partition creation-authorized execution"
```

---

## Task 6: Prove Step27-33 creation authority offline with public APIs

**Files**
- Create: `tests/integration/test_step36_offset_creation_authority.py`
- Production: none. Step31/32 are regression-only in Step36; an unexpected contract failure there is a design stop condition.

- [ ] Build one fixture using actual public APIs for Step27 Impact, Step28 scope, Step29 ChangeSet, Step30 plan, Step31 source ProviderBinding, Step32 admitted authority, and Step33 comparison.
- [ ] Build CREATE hashes with the exact public helper, not literals:

```python
draft = ActualChange(
    change_kind=ActualChangeKind.CREATE,
    actual_change_hash="0" * 64,
    canonical_kind="ifc:IfcWall",
    canonical_operation="offset.v1",
    source_execution_unit_hash=unit.execution_unit_hash,
    source_semantic_id="WALL-001",
    source_canonical_kind="ifc:IfcWall",
    derivation_rule="RULE-OFFSET-WALL",
    host_entity_ref=HostEntityRef(document_id="DOC-A", native_id="C01", native_type="Polyline"),
)
one = replace(draft, actual_change_hash=compute_actual_change_hash(draft))
```

Construct `ActualDelta` the same way: draft with `actual_delta_hash="0" * 64`, then `replace(..., actual_delta_hash=compute_actual_delta_hash(draft_delta))`.
- [ ] One creation:

```python
result = ScopeComparator().compare(request_with((one,)))
assert result.status is ScopeComparisonStatus.WITHIN_SCOPE
assert result.violations == ()
assert result.matched_changes[0].rule_id == creation_rule.rule_id
```

- [ ] Two distinct created Host refs under the same rule:

```python
assert result.status is ScopeComparisonStatus.SCOPE_BREACH
assert [v.code for v in result.violations] == ["CREATION_COUNT_EXCEEDED"]
```

- [ ] Freeze wrong-kind/source/derivation violations as `CREATION_KIND_FORBIDDEN`, `CREATION_SOURCE_FORBIDDEN`, and `CREATION_DERIVATION_MISMATCH`.
- [ ] Run:

```powershell
python -m pytest tests/integration/test_step36_offset_creation_authority.py -q
python -m pytest tests/approval_scope tests/changeset tests/execution_planning tests/provider_binding tests/gateway_authorization tests/execution_reconciliation -q
```

If Step31/32 public APIs cannot carry the source-only lineage, stop and return to the Step36 design; do not modify those production packages inside this task.
- [ ] Commit:

```powershell
git add tests/integration/test_step36_offset_creation_authority.py
git commit -m "test: prove Step36 creation scope authority"
```

---

## Task 7: Add AutoCAD OFFSET provider surface and freeze Host wire offline

**Files**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/model_adapter.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py`
- Test: `tests/integration/test_step36_autocad_offset_command.py`

Add provider metadata key `com.company.design/existence_effects`; parser field defaults to `()` so all old profiles remain source-compatible. Offset profile advertises native source constraint `LWPOLYLINE`, `effects=[]`, `existence_effects=["CREATE"]`, canonical operation `offset.v1`. D4 still receives canonical existence semantics from the platform definition; provider metadata remains a provider claim for later binding/audit.

- [ ] RED fake-transport test for:

```python
await dispatcher.offset(
    ["2C6"],
    {"value": 300.0, "unit": "mm"},
    {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
    idempotency_key="step36-offset-1",
    revision=7,
)
```

Exact Host wire:

```python
operation == "offset.v1"
target_native_refs == [{"document_id": "Drawing1.dwg", "native_id": "2C6"}]
arguments == {
    "distance": {"value": 300.0, "unit": "mm"},
    "sidePoint": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
}
```

Serialized command must not contain `CreationRule`, `grant_hash`, `approved_scope_hash`, `execution_slice_hash`, `ifc:IfcWall`, or `RULE-OFFSET-WALL`.
- [ ] Run RED:

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py -q
```

- [ ] Implement profile/parser, MCP tool, ModelAdapter, and CommandDispatcher validation: exactly one handle; literal `mm`; positive finite distance; finite x/y/z; existing revision and idempotency patterns.
- [ ] Prove replay uses existing sidecar idempotency and sends one Host mutation request for identical key/content.
- [ ] GREEN regression:

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py tests/integration/test_step34_autocad_wall_thickness_command.py -q
```

- [ ] Commit:

```powershell
git add hosts/autocad/sidecar/src/autocad_sidecar tests/integration/test_step36_autocad_offset_command.py
git commit -m "feat: expose AutoCAD offset command"
```

---

## Task 8: Capture the mandatory real AutoCAD RED

**Files**
- Create: `tests/integration/test_step36_live_autocad_offset_create.py`
- Production C#: none.

Use the shared Step34 dynamic-pipe helper. Gate with `AGENT_HOST_TEST=1`.

Live fixture is explicit:
- exactly one selected A-WALL Polyline/LWPOLYLINE;
- `INSUNITS=4`;
- geometric-extents fact exists;
- fixture must be axis-dominant: `abs((max_x-min_x) - (max_y-min_y)) > 1e-6`.

Derive a deterministic side point from bounds so no hand-picked coordinate is required:

```python
width = max_x - min_x
height = max_y - min_y
cx = (min_x + max_x) / 2
cy = (min_y + max_y) / 2
cz = (min_z + max_z) / 2
if height > width:
    side_point = {"x": max_x + 4 * distance, "y": cy, "z": cz, "unit": "mm"}
else:
    side_point = {"x": cx, "y": max_y + 4 * distance, "z": cz, "unit": "mm"}
```

- [ ] Test preflight records source bounds/layer/native type and current revision, then calls `dispatcher.offset(...)` with a unique UUID idempotency key.
- [ ] GREEN assertions are already written but initially unreachable: result OK; verification dict `ok=True`; exactly one `createdEntityRef`; `revision_after == revision_before + 1`; source bounds and layer unchanged on read-back; created entity readable and on A-WALL.
- [ ] Offline collection:

```powershell
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected without `AGENT_HOST_TEST`: SKIPPED.
- [ ] **User/real AutoCAD only:** run against the current Step34 plugin and record the formal RED:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected: fixture and revision checks pass, request reaches Host, and Host returns unknown command type `offset.v1` (or the existing registry-equivalent missing-handler error).
- [ ] Commit the observed RED test unchanged:

```powershell
git add tests/integration/test_step36_live_autocad_offset_create.py
git commit -m "test: capture Step36 live offset RED"
```

---

## Task 9: Implement atomic AutoCAD offset creation after the live RED

**Files**
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Model/OffsetHandler.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Verification/OffsetVerifier.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs`

Define in `AutoCADEntityApi.cs`:

```csharp
public sealed record OffsetNativeResult(
    HostEntityRef Source,
    HostEntityRef Created,
    Extents3d SourceBoundsBefore,
    Extents3d SourceBoundsAfter,
    string SourceLayer,
    string CreatedLayer);

public static OffsetNativeResult OffsetPolyline(
    string handle,
    double distanceMm,
    Point3d sidePoint);
```

- [ ] Handler parses exactly `distance.value`, literal `distance.unit="mm"`, `sidePoint.x/y/z`, literal `sidePoint.unit="mm"`, and exactly one target. Invalid input returns deterministic Host error before mutation. Reuse Step34 `UNSUPPORTED_DOCUMENT_UNITS` mapping for non-mm documents.
- [ ] Native helper uses one transaction. Resolve one `Polyline`; record source bounds/layer; call `source.GetOffsetCurves(+distanceMm)` and `source.GetOffsetCurves(-distanceMm)`. **Each sign must yield exactly one `Polyline`; zero, multiple, or unsupported objects fail closed.**
- [ ] Side selection algorithm is frozen: for each candidate `Curve`, compute `candidate.GetClosestPointTo(sidePoint, false).DistanceTo(sidePoint)`. If `abs(plusDistance - minusDistance) <= 1e-6`, fail `OFFSET_SIDE_AMBIGUOUS`; otherwise select the candidate with lower distance. Dispose all unselected/transient DBObjects.
- [ ] Set selected entity layer to source layer; open `source.OwnerId` as `BlockTableRecord` for write; `AppendEntity(selected)`; `transaction.AddNewlyCreatedDBObject(selected, true)`.
- [ ] Before commit, read source bounds again and require per-coordinate difference <= `1e-6`; require created layer equals source layer and created object is a valid Polyline. Only then commit, bump document revision once, and return the real created Handle.
- [ ] `OffsetVerifier.Verify(OffsetNativeResult)` returns `{ok,message,details}` and independently checks source-bounds equality, source/created layer equality, and distinct source/created native refs. Handler returns OK only when verifier passes.
- [ ] Register `offset.v1`.
- [ ] Build:

```powershell
dotnet build .\hosts\autocad\plugin\AutoCAD.AgentHost\AutoCAD.AgentHost.csproj -c Debug
```

Expected: Build succeeded, 0 errors.
- [ ] Offline regressions run by assistant:

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py tests/integration/test_step34_autocad_wall_thickness_command.py -q
```

- [ ] Commit:

```powershell
git add hosts/autocad/plugin/AutoCAD.AgentHost
git commit -m "feat: execute atomic AutoCAD offset creation"
```

---

## Task 10: Prove live AutoCAD GREEN, replay, stale revision, and non-mm rejection

**Files**
- Modify: `tests/integration/test_step36_live_autocad_offset_create.py`
- Planned production changes: none. A live failure after Task 9 starts a separate systematic-debugging/TDD micro-cycle before this task continues.

- [ ] **User/real AutoCAD only:** rebuild/restart/NETLOAD Task9 DLL and rerun the exact Task8 test. Do not weaken fixture/assertions.
- [ ] Extend replay proof using one generated idempotency key for two identical calls:

```python
assert replay.ok
assert replay.replayed is True
assert replay.revision_after == first.revision_after
assert replay.payload["createdEntityRef"] == first.payload["createdEntityRef"]
```

Same returned created ref + unchanged revision proves no second committed mutation through the idempotent command path.
- [ ] Add stale-revision negative using the Step34 pattern; it must return `REVISION_CONFLICT` and preserve source evidence/revision.
- [ ] Add non-mm negative using the Step34 pattern; it must return `UNSUPPORTED_DOCUMENT_UNITS` before commit and preserve source evidence/revision.
- [ ] **User/real AutoCAD only:** run:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected: all Step36 live Host tests PASS.
- [ ] Commit test refinements and any separately TDD-justified production fix:

```powershell
git add tests/integration/test_step36_live_autocad_offset_create.py hosts/autocad/plugin/AutoCAD.AgentHost
git commit -m "test: prove live AutoCAD offset creation"
```

---

## Task 11: Reconcile the real created Host ref through Step33

**Files**
- Create: `tests/integration/test_step36_live_offset_scope_acceptance.py`

- [ ] Build the same public Step27-32 authority chain as Task6, but bind the **real selected source Handle** in Step31 and execute the real Host offset.
- [ ] Build `ActualChange.CREATE` from real `document_ref`, `host_instance_id`, created Handle, source execution unit hash, and real revisions. Hash it with `compute_actual_change_hash`; hash delta with `compute_actual_delta_hash`.
- [ ] Provider-neutral assertions:

```python
assert change.canonical_operation == "offset.v1"
assert change.canonical_kind == "ifc:IfcWall"
assert change.source_semantic_id == "WALL-001"
assert change.source_canonical_kind == "ifc:IfcWall"
assert change.derivation_rule == "RULE-OFFSET-WALL"
assert "LWPOLYLINE" not in repr(actual_delta)
assert "GetOffsetCurves" not in repr(actual_delta)
```

`HostEntityRef.native_id` is permitted only as existing provenance/instance identity.
- [ ] Offline collection:

```powershell
python -m pytest tests/integration/test_step36_live_offset_scope_acceptance.py -q
```

Expected: SKIPPED without live flag.
- [ ] **User/real AutoCAD only:** reset to one source fixture and run:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_offset_scope_acceptance.py -q
```

Expected: `ScopeComparator == WITHIN_SCOPE`, no violations, matched CreationRule.
- [ ] Re-run offline two-create breach proof:

```powershell
python -m pytest tests/integration/test_step36_offset_creation_authority.py -q
```

Expected: synthetic second CREATE produces only `CREATION_COUNT_EXCEEDED -> SCOPE_BREACH`; no real unauthorized second entity is created.
- [ ] Commit:

```powershell
git add tests/integration/test_step36_live_offset_scope_acceptance.py
git commit -m "test: reconcile real offset creation scope"
```

---

## Task 12: Add dedicated CI, architecture guard, and final verification

**Files**
- Create: `.github/workflows/step36-offset-create-scope-breach.yml`
- Create: `tests/integration/test_step36_architecture.py`

- [ ] Architecture test asserts:
  - `CanonicalAspect("CREATE")` raises;
  - canonical/Core source files do not contain `GetOffsetCurves` or an AutoCAD Handle contract;
  - `OFFSET_V1.canonical_entity_constraints == ("ifc:IfcWall",)` and contains no `LWPOLYLINE`;
  - provider/Host source may contain `LWPOLYLINE`/`GetOffsetCurves`.
- [ ] Workflow path triggers cover Step36 spec/plan, orchestrator, impact, approval scope, changeset, execution planning, AutoCAD sidecar/plugin, Step36 tests, and Step33 reconciliation.
- [ ] Workflow runs:

```powershell
python -m pytest tests/orchestrator -q
python -m pytest tests/impact -q
python -m pytest tests/approval_scope -q
python -m pytest tests/changeset -q
python -m pytest tests/execution_planning -q
python -m pytest tests/integration/test_step36_offset_creation_authority.py tests/integration/test_step36_autocad_offset_command.py tests/integration/test_step36_architecture.py -q
python -m pytest tests/execution_reconciliation -q
python -m pytest --import-mode=importlib -q
ruff check --select E,F,I platform hosts/autocad/sidecar tests
git diff --check main...HEAD
```

Live tests remain skipped because GitHub runners do not have AutoCAD.
- [ ] Assistant runs all offline verification locally before claiming completion:

```powershell
python -m pytest tests/orchestrator tests/impact tests/approval_scope tests/changeset tests/execution_planning tests/provider_binding tests/gateway_authorization tests/execution_reconciliation tests/integration/test_step36_offset_creation_authority.py tests/integration/test_step36_autocad_offset_command.py tests/integration/test_step36_architecture.py -q
python -m pytest --import-mode=importlib -q
ruff check --select E,F,I platform hosts/autocad/sidecar tests
git diff --check main...HEAD
```

- [ ] Verify branch boundary:

```powershell
git log --oneline main..HEAD
git diff --name-only main...HEAD
```

Expected scope: Step36 spec/plan, existence-authority changes/tests, AutoCAD offset provider/Host, Step36 live/integration tests, Step36 CI. No Revit and no unrelated refactor.
- [ ] Before PR creation, compare final functional HEAD with the HEAD that passed live AutoCAD acceptance. If any AutoCAD/authority production file changed afterward, rerun the affected live test(s). Documentation/CI-only commits do not require DLL rebuild.
- [ ] Commit CI:

```powershell
git add .github/workflows/step36-offset-create-scope-breach.yml tests/integration/test_step36_architecture.py
git commit -m "ci: verify Step36 offset creation scope"
```

## Final completion gate

Do not call Step36 complete until every line is proven:

```text
canonical CREATE envelope: PASS
legacy Step23/27/28/29/30 hash compatibility: PASS
Step28 authority narrowing negatives: PASS
Step29 unique CreationRule binding: PASS
Step30 union-based slice selection + CREATE unit hash: PASS
Step27-32 public authority chain: PASS
one provider-neutral CREATE -> WITHIN_SCOPE: PASS
two CREATEs/max_count=1 -> CREATION_COUNT_EXCEEDED/SCOPE_BREACH: PASS
real AutoCAD creates exactly one entity: PASS
source unchanged + revision +1 + replay idempotent: PASS
stale revision + non-mm fail precommit: PASS
real created Host ref -> Step33 WITHIN_SCOPE: PASS
full offline regression/importlib/lint/diff check: PASS
```

Only after this gate may the branch enter PR review. Do not merge without explicit user instruction.
