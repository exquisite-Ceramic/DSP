# Step34 AutoCAD Wall Thickness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the complete approved DSP execution chain against a real AutoCAD Host by changing one semantic wall from `dsp:WallThickness = 200 mm` to `300 mm` and reaching Step33 `SUCCEEDED` only after scope reconciliation and independent semantic verification.

**Architecture:** Add one platform-owned canonical operation (`set_wall_thickness.v1`), preserve AutoCAD-native constraints in the provider/Host layer, normalize `LWPOLYLINE.ConstantWidth` through the existing `NormalizedDesignFact.PROPERTY` contract, project it to `dsp:WallThickness`, execute a revision-guarded Host mutation, then feed provider-neutral `ActualDelta` and reconstructed semantic evidence into the unchanged Step33 reconciliation service. The live harness must discover the dynamic AutoCAD pipe and must never restore the obsolete global fixed pipe.

**Tech Stack:** Python 3.11, pytest/pytest-asyncio, JSON Schema, DSP Step18-33 Python packages, AutoCAD 2025 .NET 8 plugin, Autodesk AutoCAD .NET API, C#/.NET 8, MCP 2.x.

**Spec:** `docs/superpowers/specs/2026-08-30-step34-autocad-wall-thickness-design.md`

## Global Constraints

- Step34 Host order is AutoCAD first; Revit remains deferred.
- Frozen AutoCAD wall convention: `A-WALL` + `LWPOLYLINE` + `Polyline.ConstantWidth`.
- Step34 mutation support requires an AutoCAD document explicitly using millimetres; no implicit unit conversion.
- Canonical property is `dsp:WallThickness`; native `LWPOLYLINE`, Handle, layer, and `ConstantWidth` must not enter DSP Core, D4 semantic eligibility, or Step33 `ActualDelta`.
- Canonical operation effects are exactly `PROPERTIES`.
- Successful `ActualDelta` is exactly `MODIFY / PROPERTIES` for the target semantic wall.
- Host `OK` is insufficient; `ScopeComparator == WITHIN_SCOPE` and independent `SemanticVerifier == PASS` are required before Step33 `SUCCEEDED`.
- Do not change Step18 `NormalizedDesignFact`, Step28/29/30/32/33 contracts, `ScopeComparator`, or `SemanticVerifier` semantics.
- Keep the plugin's multi-instance dynamic pipe naming; live tests must discover/select the real pipe.
- TDD is mandatory: no production change before its focused test has been observed failing for the expected missing behavior.

---

## File Structure

### Platform canonical action

- Modify `platform/orchestrator/src/design_orchestrator/canonical_operations.py` — define/export `SET_WALL_THICKNESS_V1` and include it in `MVP_CANONICAL_OPERATIONS`.
- Modify `platform/orchestrator/src/design_orchestrator/parameter_binder.py` — add the deterministic context-selection binding recipe for `targets`.
- Modify/add focused orchestrator tests under `tests/orchestrator/` — freeze schema, slot ownership, wall-only canonical constraint, `PROPERTIES` effect, semantic verification contract, and binding behavior.

### AutoCAD read/normalization

- Modify `tests/integration/test_autocad_native_fact_command.py` — first RED test for `properties.constantWidth` -> `FactKind.PROPERTY`.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py` — accept the optional native property object and emit the existing Step18 property fact.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADNativeFactApi.cs` — expose `Polyline.ConstantWidth` only with truthful millimetre unit evidence.

### Enterprise semantic projection

- Modify `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/projection.py` — project supported `PROPERTY` facts by carrying value/unit through to `SemanticClaim`.
- Modify `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml` — add the exact AutoCAD property mapping to `dsp:WallThickness`.
- Modify/add provider tests under `providers/semantics/enterprise_mapping/tests/` and `tests/integration/test_step21_d5_canonical_projection.py` — prove classification regressions stay unchanged and the property projects canonically.

### AutoCAD provider execution surface

- Modify `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py` — expose `cad.set_wall_thickness` with canonical operation metadata, native `LWPOLYLINE` constraint, `PROPERTIES` effect, and Host read-back verification metadata.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/adapter/model_adapter.py` — emit the Host command `set_wall_thickness.v1`.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py` — add idempotent/retry-aware public dispatch.
- Add/update focused sidecar tests in `tests/integration/` — assert the exact wire shape and no leakage of Step32 authority into `HostCommand`.

### AutoCAD plugin mutation

- Add `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Model/SetWallThicknessHandler.cs` — parse/validate request and orchestrate lock/read/mutate/read/verify.
- Add `hosts/autocad/plugin/AutoCAD.AgentHost/Verification/WallThicknessVerifier.cs` — deterministic Host-local equality verification.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs` — minimal native helpers to read/set polyline constant width and reject non-polylines.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs` — register the new handler.
- Add a live pytest under `tests/integration/` — prove real width mutation, revision advance, stale revision rejection, and unsupported-unit rejection.

### Step34 reconciliation proof

- Add `tests/integration/test_step34_autocad_wall_thickness_reconciliation.py` — deterministic Step28-33 proof using public APIs and a controlled Host result/read-back fixture.
- Add `tests/integration/test_step34_autocad_wall_thickness_live.py` — real AutoCAD acceptance test gated by `AGENT_HOST_TEST=1` and dynamic pipe discovery.
- Add `.github/workflows/step34-autocad-wall-thickness.yml` — focused Linux/Python contract suite plus Windows-independent checks; real AutoCAD remains an explicit local/manual acceptance gate.

---

### Task 1: Freeze the canonical `set_wall_thickness.v1` action

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `platform/orchestrator/src/design_orchestrator/parameter_binder.py`
- Test: `tests/orchestrator/test_canonical_operations.py`
- Test: `tests/orchestrator/test_parameter_binder.py`

**Interfaces:**
- Produces: `SET_WALL_THICKNESS_V1: CanonicalOperationDefinition`
- Produces: `SET_WALL_THICKNESS_V1_BINDING_RECIPE: OperationBindingRecipe`
- Canonical arguments: `targets: list[str]`, `thickness: {value: number > 0, unit: "mm"}`
- Canonical effect: `PROPERTIES`
- Verification path: `properties.dsp:WallThickness`

- [ ] **Step 1: Write the failing canonical-contract test**

```python
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1, SlotBindingClass


def test_set_wall_thickness_v1_is_provider_neutral_and_semantically_verified():
    op = SET_WALL_THICKNESS_V1
    assert op.canonical_operation == "set_wall_thickness.v1"
    assert op.version == "1.0.0"
    assert op.category == "MODEL_OPERATION"
    assert op.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert op.slot_binding_policy["thickness"] is SlotBindingClass.INTENT
    assert op.canonical_entity_constraints == ("ifc:IfcWall",)
    assert op.effects == ("PROPERTIES",)
    assert op.verification_contract == {
        "type": "SEMANTIC_ASSERTIONS_V1",
        "version": "1.0.0",
        "assertions": [
            {
                "subjects": {"from_argument": "targets"},
                "path": "properties.dsp:WallThickness",
                "operator": "EQUALS_ARGUMENT",
                "argument": "thickness",
            }
        ],
    }
    serialized = repr(op.input_schema) + repr(op.canonical_entity_constraints)
    assert "LWPOLYLINE" not in serialized
    assert "ConstantWidth" not in serialized
```

- [ ] **Step 2: Run the focused test and observe RED**

Run:

```powershell
python -m pytest tests/orchestrator/test_canonical_operations.py -q
```

Expected: collection/import failure for missing `SET_WALL_THICKNESS_V1`, not an unrelated environment error.

- [ ] **Step 3: Add the minimal canonical operation definition**

Add to `canonical_operations.py`:

```python
SET_WALL_THICKNESS_V1 = CanonicalOperationDefinition(
    canonical_operation="set_wall_thickness.v1",
    version="1.0.0",
    title="Set wall thickness",
    description="Set the canonical wall thickness for selected wall entities.",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "thickness": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "exclusiveMinimum": 0},
                    "unit": {"const": "mm"},
                },
                "required": ["value", "unit"],
                "additionalProperties": False,
            },
        },
        "required": ["targets", "thickness"],
        "additionalProperties": False,
    },
    slot_binding_policy={
        "targets": SlotBindingClass.CONTEXT,
        "thickness": SlotBindingClass.INTENT,
    },
    canonical_entity_constraints=("ifc:IfcWall",),
    operation_freshness_requirements=(
        {"aspect": "PROPERTIES", "required_state": "FRESH"},
    ),
    effects=("PROPERTIES",),
    verification_contract={
        "type": "SEMANTIC_ASSERTIONS_V1",
        "version": "1.0.0",
        "assertions": [
            {
                "subjects": {"from_argument": "targets"},
                "path": "properties.dsp:WallThickness",
                "operator": "EQUALS_ARGUMENT",
                "argument": "thickness",
            }
        ],
    },
)

MVP_CANONICAL_OPERATIONS = (MOVE_V1, SET_WALL_THICKNESS_V1)
```

- [ ] **Step 4: Add and test deterministic target binding**

Add:

```python
SET_WALL_THICKNESS_V1_BINDING_RECIPE = OperationBindingRecipe(
    canonical_operation=SET_WALL_THICKNESS_V1.canonical_operation,
    slots=(
        SlotBindingRecipe(
            slot="targets",
            resolver_kind=BindingResolverKind.CONTEXT_SELECTION,
        ),
    ),
)

MVP_BINDING_RECIPES = (
    MOVE_V1_BINDING_RECIPE,
    SET_WALL_THICKNESS_V1_BINDING_RECIPE,
)
```

Test binding with an `OperationProposal("set_wall_thickness.v1", {"thickness": {"value": 300.0, "unit": "mm"}})` and a context selection `("WALL-001",)`; assert the bound arguments contain the semantic target and no provider-native values.

- [ ] **Step 5: Run focused orchestrator regressions**

```powershell
python -m pytest tests/orchestrator -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add platform/orchestrator/src/design_orchestrator/canonical_operations.py platform/orchestrator/src/design_orchestrator/parameter_binder.py tests/orchestrator
git commit -m "feat: add canonical wall thickness action"
```

---

### Task 2: Normalize AutoCAD `ConstantWidth` as an existing PROPERTY fact

**Files:**
- Modify: `tests/integration/test_autocad_native_fact_command.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py`

**Interfaces:**
- Consumes native optional entity field: `properties.constantWidth = {value: number, unit: "mm"}`
- Produces `NormalizedDesignFact(fact_kind=PROPERTY, predicate="constant_width", source_scheme="autocad.property", source_code="LWPOLYLINE.ConstantWidth", unit="mm")`
- Does not modify `design_fact_contracts`.

- [ ] **Step 1: Write the first Step34 RED test**

Extend the existing `SNAPSHOT` fixture's `LWPOLYLINE` entity with:

```python
"properties": {
    "constantWidth": {
        "value": 200.0,
        "unit": "mm",
    }
},
```

Then add:

```python
@pytest.mark.asyncio
async def test_dispatcher_normalizes_lwpolyline_constant_width_as_property_fact():
    dispatcher = CommandDispatcher(HostAdapter(transport=NativeFactTransport()))

    batch = await dispatcher.extract_design_facts(["A31"])

    properties = [fact for fact in batch.facts if fact.fact_kind is FactKind.PROPERTY]
    assert len(properties) == 1
    fact = properties[0]
    assert fact.predicate == "constant_width"
    assert fact.value == 200.0
    assert fact.unit == "mm"
    assert fact.source_scheme == "autocad.property"
    assert fact.source_code == "LWPOLYLINE.ConstantWidth"
    assert fact.subject_native_ref.native_kind == "LWPOLYLINE"
```

- [ ] **Step 2: Run the one test and observe RED**

```powershell
python -m pytest tests/integration/test_autocad_native_fact_command.py::test_dispatcher_normalizes_lwpolyline_constant_width_as_property_fact -q
```

Expected: FAIL because `DesignFactAdapter` currently rejects the unknown entity field `properties` (or produces no `PROPERTY` fact). This is the required TDD RED.

- [ ] **Step 3: Implement the minimum strict native-property parser**

In `design_fact_adapter.py` extend `_ENTITY_FIELDS` with `properties`, define exact allowed nested keys, validate finite positive numeric value and literal `mm`, and emit:

```python
self._fact(
    host_ref=host_ref,
    subject=subject,
    revision=revision,
    fact_kind=FactKind.PROPERTY,
    predicate="constant_width",
    value=constant_width["value"],
    value_type=ValueType.NUMBER,
    unit="mm",
    source_scheme="autocad.property",
    source_code="LWPOLYLINE.ConstantWidth",
    provenance=provenance,
)
```

Extend `_fact(...)` with `unit: str | None = None` and pass it to `NormalizedDesignFact` instead of hardcoding `unit=None`.

Do not accept arbitrary property names in Step34.

- [ ] **Step 4: Add strict negative tests**

Add cases proving:

```python
{"constantWidth": {"value": -1.0, "unit": "mm"}}  # rejected
{"constantWidth": {"value": 200.0, "unit": "m"}}  # rejected for Step34
{"unknown": {"value": 1.0, "unit": "mm"}}         # rejected
```

- [ ] **Step 5: Run focused and Step19 regressions**

```powershell
python -m pytest tests/integration/test_autocad_native_fact_command.py -q
python -m pytest contracts/python/tests -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add tests/integration/test_autocad_native_fact_command.py hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py
git commit -m "feat: normalize AutoCAD wall width property"
```

---

### Task 3: Project the property fact to `dsp:WallThickness`

**Files:**
- Modify: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/projection.py`
- Modify: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`
- Modify/add: enterprise mapping tests
- Modify: `tests/integration/test_step21_d5_canonical_projection.py`

**Interfaces:**
- Consumes `FactKind.PROPERTY` with source scheme/code `autocad.property` / `LWPOLYLINE.ConstantWidth`.
- Produces `SemanticClaim(predicate="property", canonical_term_id="dsp:WallThickness", value=<number>, unit="mm")`.

- [ ] **Step 1: Write a failing property-projection test**

Construct a `NormalizedDesignFact` with:

```python
fact_kind=FactKind.PROPERTY
predicate="constant_width"
value=200.0
value_type=ValueType.NUMBER
unit="mm"
source_scheme="autocad.property"
source_code="LWPOLYLINE.ConstantWidth"
```

Project it through the real enterprise catalog and assert exactly one claim:

```python
assert claim.predicate == "property"
assert claim.canonical_term_id == "dsp:WallThickness"
assert claim.value == 200.0
assert claim.unit == "mm"
assert claim.assurance == "RULE_DERIVED"
```

- [ ] **Step 2: Run and observe RED**

Expected: no property claim because `project_facts_for_catalog` currently skips every non-`CLASSIFICATION` fact.

- [ ] **Step 3: Add the YAML rule**

Add the exact rule specified by the design:

```yaml
- mapping_id: autocad-lwpolyline-constant-width-wall-thickness
  source_scheme: autocad.property
  match_type: EXACT
  pattern: LWPOLYLINE.ConstantWidth
  case_sensitive: true
  target_term_id: dsp:WallThickness
  assurance: RULE_DERIVED
```

- [ ] **Step 4: Generalize projection only for supported fact kinds**

Refactor the current early filter so `CLASSIFICATION` and `PROPERTY` use the same rule matching/conflict detection, then create claim fields as:

```python
if fact.fact_kind is FactKind.CLASSIFICATION:
    predicate, value, unit = "classification", None, None
elif fact.fact_kind is FactKind.PROPERTY:
    predicate, value, unit = "property", fact.value, fact.unit
else:
    continue
```

Do not weaken existing source scheme/code requirements.

- [ ] **Step 5: Extend the Step21 integration proof**

Add a fake AutoCAD snapshot carrying `A-WALL` + `LWPOLYLINE.ConstantWidth=200 mm`; assert the semantic pipeline contains both canonical results:

```text
ifc:IfcWall
dsp:WallThickness = 200 mm
```

- [ ] **Step 6: Run provider and D5 regressions**

```powershell
python -m pytest providers/semantics/enterprise_mapping/tests -q
python -m pytest tests/integration/test_step21_d5_canonical_projection.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add providers/semantics/enterprise_mapping tests/integration/test_step21_d5_canonical_projection.py
git commit -m "feat: project AutoCAD width to wall thickness"
```

---

### Task 4: Add the AutoCAD provider capability and exact HostCommand wire shape

**Files:**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/model_adapter.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py`
- Test: `tests/integration/test_design_capability_profile.py`
- Add: `tests/integration/test_autocad_wall_thickness_command.py`

**Interfaces:**
- MCP tool: `cad.set_wall_thickness`
- Provider metadata canonical op: `set_wall_thickness.v1`
- Native entity constraint: `LWPOLYLINE`
- Provider effect: `PROPERTIES`
- Host operation: `set_wall_thickness.v1`
- Host arguments: `{"width": 300.0, "unit": "mm"}`

- [ ] **Step 1: Write the capability RED test**

Assert the tool definition contains:

```python
assert tool["name"] == "cad.set_wall_thickness"
assert tool["_meta"]["com.company.design/operation"] == "set_wall_thickness.v1"
assert tool["_meta"]["com.company.design/entities"] == ["LWPOLYLINE"]
assert tool["_meta"]["com.company.design/effects"] == ["PROPERTIES"]
```

Also assert the canonical operation definition from Task 1 contains none of those AutoCAD-native strings.

- [ ] **Step 2: Write the HostCommand RED test**

Use a fake transport and call:

```python
result = await dispatcher.set_wall_thickness(
    ["A31"],
    {"value": 300.0, "unit": "mm"},
    idempotency_key="step34-001",
    revision=7,
)
```

Assert the sent HostCommand is:

```python
assert sent["mode"] == "EXECUTE"
assert sent["operation"] == "set_wall_thickness.v1"
assert sent["target_native_refs"] == [
    {"document_id": "C:/models/demo.dwg", "native_id": "A31"}
]
assert sent["arguments"] == {"width": 300.0, "unit": "mm"}
assert sent["preconditions"] == [{"type": "revision", "expected": 7}]
```

Assert there is no `grant_hash`, `approved_scope_hash`, or semantic ID in the HostCommand payload.

- [ ] **Step 3: Run the two tests and observe RED**

Expected: missing tool/dispatcher method.

- [ ] **Step 4: Implement minimal sidecar emission**

Add `ModelAdapter.set_wall_thickness(...)` mirroring `move(...)` and validate canonical measurement before constructing the HostCommand. Add `CommandDispatcher.set_wall_thickness(...)` using the existing idempotency/retry pattern.

- [ ] **Step 5: Register the MCP tool**

Input schema should accept `handles`, canonical `thickness` measurement, optional idempotency key, and optional revision. Tool execution forwards only the translated numeric width and unit to the Host command adapter.

- [ ] **Step 6: Run sidecar regressions**

```powershell
python -m pytest tests/integration/test_design_capability_profile.py tests/integration/test_autocad_wall_thickness_command.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add hosts/autocad/sidecar/src/autocad_sidecar tests/integration/test_design_capability_profile.py tests/integration/test_autocad_wall_thickness_command.py
git commit -m "feat: add AutoCAD wall thickness capability"
```

---

### Task 5: Make real AutoCAD snapshots expose truthful `ConstantWidth`

**Files:**
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADNativeFactApi.cs`
- Add: `tests/integration/test_step34_autocad_wall_thickness_live.py` (initial read-only portion)
- Reuse: `tools/host_test_client/main.py` discovery behavior

**Interfaces:**
- Real Host read must return optional `properties.constantWidth.value/unit` for an `LWPOLYLINE` in an explicitly millimetre document.

- [ ] **Step 1: Create the real AutoCAD fixture**

In a disposable DWG:

```text
INSUNITS = millimetres
Layer = A-WALL
Entity = LWPOLYLINE
ConstantWidth = 200
```

Select exactly that polyline and record its Handle from `python tools/host_test_client/main.py selection`.

- [ ] **Step 2: Write the live read RED test before changing C#**

Gate with:

```python
pytestmark = pytest.mark.skipif(
    os.getenv("AGENT_HOST_TEST") != "1",
    reason="requires a real AutoCAD AgentHost",
)
```

Use dynamic pipe discovery to build the HostAdapter, call `CommandDispatcher.extract_design_facts([handle])`, and assert a `PROPERTY` fact with value `200.0`, unit `mm`, and source code `LWPOLYLINE.ConstantWidth` exists.

- [ ] **Step 3: Run against the currently loaded plugin and observe RED**

Expected: no wall-thickness property because current `AutoCADNativeFactApi.Extract` emits only native id/kind/layer/bounds.

- [ ] **Step 4: Implement the minimum native read**

In `AutoCADNativeFactApi.cs`, when the opened entity is `Autodesk.AutoCAD.DatabaseServices.Polyline` and the active database insertion units are explicitly `UnitsValue.Millimeters`, add:

```csharp
snapshot["properties"] = new
{
    constantWidth = new
    {
        value = polyline.ConstantWidth,
        unit = "mm",
    },
};
```

For non-polylines, do not emit this property. Do not fabricate `mm` for other/unspecified units.

- [ ] **Step 5: Build and NETLOAD the new plugin**

```powershell
dotnet build hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj -c Debug
```

Reload the generated DLL in AutoCAD.

- [ ] **Step 6: Re-run the live read test and focused offline tests**

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step34_autocad_wall_thickness_live.py -q -k native_read
python -m pytest tests/integration/test_autocad_native_fact_command.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADNativeFactApi.cs tests/integration/test_step34_autocad_wall_thickness_live.py
git commit -m "feat: read AutoCAD polyline wall width"
```

---

### Task 6: Implement revision-guarded real wall-thickness mutation

**Files:**
- Add: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Model/SetWallThicknessHandler.cs`
- Add: `hosts/autocad/plugin/AutoCAD.AgentHost/Verification/WallThicknessVerifier.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs`
- Extend: `tests/integration/test_step34_autocad_wall_thickness_live.py`

**Interfaces:**
- Command type: `set_wall_thickness.v1`
- Request arguments: numeric positive finite `width`, literal unit `mm`
- Success payload: `updated`, `widths` keyed by Handle
- Host verification: all post widths equal requested width
- Unsupported unit error: deterministic `UNSUPPORTED_DOCUMENT_UNITS`

- [ ] **Step 1: Add the live mutation RED test**

Start from fixture width `200`, capture `revision_before`, dispatch `set_wall_thickness(...300 mm..., revision=revision_before)`, then assert:

```python
assert result.ok
assert result.verification["ok"] is True
assert result.revision_after == revision_before + 1
```

Read design facts again and assert native/normalized width is `300 mm`.

- [ ] **Step 2: Run and observe RED**

Expected: Host returns unknown command type `set_wall_thickness.v1`.

- [ ] **Step 3: Add minimal native helpers**

Add helpers that resolve Handles as writable `Polyline`, read constant widths, and set constant width inside the existing document-lock/transaction conventions. Reject a target that is not the required polyline type before applying a partial mutation.

- [ ] **Step 4: Add `WallThicknessVerifier`**

Implement deterministic comparison over the post-read width map and requested width, returning the existing verification DTO shape used by `MoveVerifier`.

- [ ] **Step 5: Add and register `SetWallThicknessHandler`**

Mirror the proven `MoveHandler` sequence:

```text
parse -> document lock -> validate units -> read before -> mutate -> read after -> verify -> result
```

Register `new Model.SetWallThicknessHandler()` in `HostCommandHandlerRegistry`.

- [ ] **Step 6: Add negative live cases**

Prove:

1. stale expected revision is rejected and width does not change;
2. non-`LWPOLYLINE` target is rejected;
3. non-mm document is rejected before mutation;
4. repeat with the same idempotency key replays the original success without a second semantic mutation.

- [ ] **Step 7: Build/reload and run live tests**

```powershell
dotnet build hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj -c Debug
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step34_autocad_wall_thickness_live.py -q -k "host_mutation or stale_revision or unsupported_units"
```

- [ ] **Step 8: Commit**

```powershell
git add hosts/autocad/plugin/AutoCAD.AgentHost tests/integration/test_step34_autocad_wall_thickness_live.py
git commit -m "feat: mutate AutoCAD wall thickness"
```

---

### Task 7: Repair live pytest transport selection without regressing multi-instance Host identity

**Files:**
- Add: `tests/integration/autocad_live_host.py`
- Modify: `tests/integration/test_current_selection.py`
- Modify: `tests/integration/test_move.py`
- Modify: `tests/integration/test_step34_autocad_wall_thickness_live.py`

**Interfaces:**
- Produces a test helper that discovers the one running `EnterpriseDesignAgent.*` pipe using the same semantics as `tools/host_test_client/main.py` and returns `HostAdapter(pipe_name=<discovered>)`.

- [ ] **Step 1: Write a helper test around discovery selection**

Factor the discovery logic into one importable test utility rather than copy/pasting it across tests. The helper must fail clearly on zero or multiple pipes and allow an explicit pipe override for deterministic debugging.

- [ ] **Step 2: Replace direct `HostAdapter()` in live tests**

Use the helper in `test_current_selection.py`, `test_move.py`, and Step34 live tests.

- [ ] **Step 3: Run the previously failing live baselines**

With AutoCAD/plugin running:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_current_selection.py -q
python -m pytest tests/integration/test_move.py -q
```

Expected: they connect to the dynamic pipe instead of `\\.\pipe\EnterpriseDesignAgent`.

- [ ] **Step 4: Commit**

```powershell
git add tests/integration/autocad_live_host.py tests/integration/test_current_selection.py tests/integration/test_move.py tests/integration/test_step34_autocad_wall_thickness_live.py
git commit -m "test: discover live AutoCAD host pipe"
```

---

### Task 8: Prove Step28-33 success and negative reconciliation without changing Step33

**Files:**
- Add: `tests/integration/test_step34_autocad_wall_thickness_reconciliation.py`
- Reuse only public APIs from `design_approval_scope`, `design_changeset`, `design_execution_planning`, `design_provider_binding`, `design_gateway_authorization`, and `design_execution_reconciliation`.

**Interfaces:**
- Canonical action: `set_wall_thickness.v1`
- Target semantic ID: `WALL-001`
- Approved direct effect: `PROPERTIES`
- Provider binding native evidence: `LWPOLYLINE` is allowed only in ProviderBinding evidence
- Actual change: `MODIFY / PROPERTIES`
- Verification evidence property: `{"dsp:WallThickness": {"value": 300.0, "unit": "mm"}}`

- [ ] **Step 1: Build the transaction through real Step28-30 APIs**

Follow the public-API pattern in `tests/execution_reconciliation/conftest.py`, but use `SET_WALL_THICKNESS_V1`, `IntentBoundary(allowed_canonical_effects=("PROPERTIES",))`, one `DirectEntityEffect("WALL-001", (CanonicalAspect.PROPERTIES,))`, and one execution slice.

- [ ] **Step 2: Build ProviderBinding and Step32 admitted authority**

Use `NativeTargetBindingEvidence` with:

```text
semantic_id = WALL-001
native_kind = LWPOLYLINE
native_id = A31
```

Then create/consume the grant through `GatewayAuthorizationService`; do not directly fabricate an admitted authority.

- [ ] **Step 3: Construct the successful provider-neutral ActualDelta**

Create exactly one `ActualChange`:

```python
ActualChange(
    change_kind=ActualChangeKind.MODIFY,
    semantic_id="WALL-001",
    changed_aspects=(CanonicalAspect.PROPERTIES,),
    ...
)
```

Bind the delta to the real grant/binding/slice/changeset/scope hashes and revision transition.

- [ ] **Step 4: Build post-execution semantic evidence**

Use `VerificationSubjectEvidence` with:

```python
properties={
    "dsp:WallThickness": {
        "value": 300.0,
        "unit": "mm",
    }
}
evidence_aspects=(CanonicalAspect.PROPERTIES,)
```

Bind the evidence bundle to the exact Step29 validation task, post-execution snapshot/projection, semantic environment, and ActualDelta revision.

- [ ] **Step 5: Drive the Step33 lifecycle and assert success**

Use `ExecutionReconciliationService` public methods in the same order enforced by existing Step33 tests. Assert:

```text
scope comparison = WITHIN_SCOPE
semantic verification = PASSED
final slice state = SUCCEEDED
```

- [ ] **Step 6: Add wrong-value negative proof**

Change only evidence value to `299.0 mm`; assert semantic verification fails and the slice cannot become `SUCCEEDED`.

- [ ] **Step 7: Add extra-scope negative proof**

Add an extra actual canonical aspect outside `PROPERTIES`; assert `SCOPE_BREACH` and no `SUCCEEDED`.

- [ ] **Step 8: Run Step33 + Step34 reconciliation tests**

```powershell
python -m pytest tests/execution_reconciliation -q
python -m pytest tests/integration/test_step34_autocad_wall_thickness_reconciliation.py -q
```

Expected: Step33 remains 115+ passing with no semantic change to its implementation.

- [ ] **Step 9: Commit**

```powershell
git add tests/integration/test_step34_autocad_wall_thickness_reconciliation.py
git commit -m "test: prove wall thickness reconciliation"
```

---

### Task 9: Run the real full Step34 acceptance and add focused CI guards

**Files:**
- Extend: `tests/integration/test_step34_autocad_wall_thickness_live.py`
- Add: `.github/workflows/step34-autocad-wall-thickness.yml`

**Interfaces:**
- Real fixture starts at `A-WALL / LWPOLYLINE / ConstantWidth=200 / mm`.
- Real Host ends at `ConstantWidth=300`.
- Platform proof still uses canonical `WALL-001`, `dsp:WallThickness`, and `MODIFY / PROPERTIES` only.

- [ ] **Step 1: Add the live end-to-end test wrapper**

The test must:

1. discover the real AutoCAD Host;
2. confirm selected entity is `LWPOLYLINE`;
3. read/normalize pre-state `200 mm`;
4. execute the already-admitted wall-thickness Host command at the expected revision;
5. read/normalize post-state `300 mm`;
6. use the same Step34 helper that constructs provider-neutral ActualDelta/evidence;
7. run scope comparison and independent semantic verification;
8. assert the Step33 slice reaches `SUCCEEDED` only after both pass.

- [ ] **Step 2: Run the full offline suite before live acceptance**

```powershell
python -m pytest tests/execution_reconciliation -q
python -m pytest tests/integration/test_autocad_native_fact_command.py -q
python -m pytest tests/integration/test_step21_d5_canonical_projection.py -q
python -m pytest tests/integration/test_autocad_wall_thickness_command.py -q
python -m pytest tests/integration/test_step34_autocad_wall_thickness_reconciliation.py -q
```

- [ ] **Step 3: Run the real Host acceptance**

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step34_autocad_wall_thickness_live.py -q
Remove-Item Env:AGENT_HOST_TEST
```

Expected: real entity width `200 -> 300`, revision advances, Host verifier passes, `ActualDelta` is only `MODIFY / PROPERTIES`, scope is within approval, independent semantic verifier passes, final Step33 state is `SUCCEEDED`.

- [ ] **Step 4: Add CI boundary checks**

The Step34 workflow must install the same editable package stack as Step33 plus the AutoCAD sidecar/semantic providers; run the focused offline Step34 tests, Step28-33 regressions, Ruff, and `git diff --check`. It must not pretend to run AutoCAD in GitHub-hosted Linux CI.

- [ ] **Step 5: Run full repository importlib suite**

```powershell
python -m pytest -q --import-mode=importlib
```

- [ ] **Step 6: Commit**

```powershell
git add tests/integration/test_step34_autocad_wall_thickness_live.py .github/workflows/step34-autocad-wall-thickness.yml
git commit -m "ci: verify Step34 wall thickness proof"
```

---

## Final Verification Gate

Before opening the PR, run from a clean Step34 branch with the CI-aligned `.venv` active:

```powershell
python -m pytest tests/orchestrator -q
python -m pytest tests/integration/test_autocad_native_fact_command.py -q
python -m pytest tests/integration/test_step21_d5_canonical_projection.py -q
python -m pytest tests/integration/test_autocad_wall_thickness_command.py -q
python -m pytest tests/integration/test_step34_autocad_wall_thickness_reconciliation.py -q
python -m pytest tests/execution_reconciliation -q
python -m pytest -q --import-mode=importlib
ruff check platform/orchestrator/src/design_orchestrator hosts/autocad/sidecar/src/autocad_sidecar providers/semantics/enterprise_mapping/src tests/orchestrator tests/integration

git diff --check main...HEAD
```

Then, with the real disposable AutoCAD fixture and newly built/reloaded plugin:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_current_selection.py -q
python -m pytest tests/integration/test_step34_autocad_wall_thickness_live.py -q
Remove-Item Env:AGENT_HOST_TEST
```

Do not claim Step34 complete unless both the offline verification stack and the real Host acceptance are green.