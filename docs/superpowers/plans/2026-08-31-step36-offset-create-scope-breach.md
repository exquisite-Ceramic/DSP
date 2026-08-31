# Step36 OFFSET CREATE / CreationRule / SCOPE_BREACH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit canonical CREATE authority for `offset.v1`, carry that authority without widening through Steps 27-32, execute one real AutoCAD wall offset, and prove Step33 accepts exactly one authorized creation but reports `CREATION_COUNT_EXCEEDED -> SCOPE_BREACH` for two creations against `max_count = 1`.

**Architecture:** CREATE/DELETE remain separate from `CanonicalAspect`. `offset.v1` carries `CanonicalExistenceEffect.CREATE` plus a closed canonical creation envelope (`ifc:IfcWall`, `max_count=1`, `RULE-OFFSET-WALL`); Step27 carries the intent boundary, Step28 admits only equal-or-narrower `CreationRule` authority, Step29 and Step30 commit that rule into immutable operation/unit hashes, and unchanged Step31/32 preserve the admitted lineage. AutoCAD receives only source-native geometry intent; the orchestration boundary turns the created Host entity into provider-neutral `ActualChange.CREATE`, which the existing Step33 `ScopeComparator` evaluates.

**Tech Stack:** Python 3.11, pytest/pytest-asyncio, JSON Schema, DSP Steps 23/27-33 Python packages, AutoCAD 2025 .NET 8 plugin, Autodesk AutoCAD .NET API, C#/.NET 8, MCP 2.x.

**Spec:** `docs/superpowers/specs/2026-08-31-step36-offset-create-scope-breach-design.md`

## Global Constraints

- `CREATE` and `DELETE` MUST NOT become `CanonicalAspect` values.
- Step36 enables `CREATE` only; deletion remains deny-by-default.
- Frozen `offset.v1` creation envelope: `entity_kinds=("ifc:IfcWall",)`, `max_count=1`, `required_derivation="RULE-OFFSET-WALL"`.
- Frozen canonical intent uses one existing source semantic target, positive `distance` in `mm`, and provider-neutral `side_point` in `mm`; signed native offset direction is provider-owned.
- Step28 may admit only equal-or-narrower creation authority; it must never silently widen or normalize an over-broad request.
- Step29 `scope_rule_ids` stays generic; one rule ID must resolve to exactly one Step28 rule across Existing/Creation/Deletion namespaces.
- Step30 routes the existing source target only and selects an already-declared `ExecutionSliceScopeRule`; it never synthesizes creation authority.
- Empty/default existence fields MUST leave legacy `move.v1` and `set_wall_thickness.v1` Step23/27/28/29/30 semantic hashes unchanged.
- Existing `ExistingEntityRule` fingerprint payload MUST remain byte-for-byte compatible with the pre-Step36 algorithm.
- AutoCAD Step36 supports only explicit millimetre documents and exactly one `Polyline`/`LWPOLYLINE` source fixture on the enterprise wall convention.
- Host wire MUST NOT contain Step28 rules, Step32 grants, `ifc:*`, or DSP semantic IDs for the newly created entity.
- A successful Host command is not an `ActualDelta`; orchestration constructs provider-neutral `ActualChange.CREATE` using real Host provenance.
- Step36 does not add a CREATE-specific semantic-verification language or a new semantic-identity assignment protocol.
- TDD is mandatory: no production behavior may be added before the focused missing behavior has been observed RED. Real AutoCAD production mutation code requires an observed live RED first.

---

## File Structure

### Canonical existence authority

- Modify `platform/orchestrator/src/design_orchestrator/canonical_operations.py` — add `CanonicalExistenceEffect`, `CanonicalCreationContract`, and `OFFSET_V1` while leaving legacy definitions semantically unchanged.
- Modify `platform/orchestrator/src/design_orchestrator/parameter_binder.py` — add the target-selection binding recipe for `offset.v1`.
- Modify `tests/orchestrator/test_canonical_operations.py` and `tests/orchestrator/test_parameter_binder.py` — freeze schema, slot ownership, CREATE envelope, and provider-neutrality.

### Step27 intent

- Modify `platform/impact/src/design_impact/contracts.py` — add `IntentBoundary.allowed_existence_effects`.
- Modify `platform/impact/src/design_impact/analyzer.py` — commit non-empty existence intent into the Step27 fingerprint while omitting empty values from legacy payloads.
- Modify `tests/impact/test_step27_contracts.py` and `tests/impact/test_step27_analyzer.py` — prove normalization and legacy fingerprint compatibility.

### Step28 creation admission

- Modify `platform/approval_scope/src/design_approval_scope/contracts.py` — extend `CanonicalEffectEvidence` with existence authority and canonical creation envelope; permit empty aspect authority only when existence authority is present.
- Modify `platform/approval_scope/src/design_approval_scope/planner.py` — admit closed-world `CreationRule` values for CREATE while keeping DELETE unsupported.
- Modify `platform/approval_scope/src/design_approval_scope/hashing.py` — hash non-empty existence semantics without changing legacy payloads.
- Modify `platform/approval_scope/src/design_approval_scope/__init__.py` — export any new public construction helper/type.
- Modify `tests/approval_scope/test_step28_contracts.py`, `test_step28_planner.py`, `test_step28_hashing.py`, and `test_step28_integrity.py` — prove authority narrowing, deterministic rule identity, slice coverage, and compatibility.

### Step29 immutable ChangeSet

- Modify `platform/changeset/src/design_changeset/contracts.py` — add existence semantics to exact contract evidence and canonical operations without making existing effects mandatory for CREATE-only operations.
- Modify `platform/changeset/src/design_changeset/hashing.py` — type-aware rule fingerprints and optional existence hash material.
- Modify `platform/changeset/src/design_changeset/builder.py` — resolve one unique `CreationRule` for `offset.v1` and do not create a canonical verification task when the verification contract is empty.
- Modify `platform/changeset/src/design_changeset/integrity.py` if required by recomputation of the new fields.
- Modify tests under `tests/changeset/` — creation coverage, duplicate ambiguity rejection, and legacy hashes.

### Step30 execution planning

- Modify `platform/execution_planning/src/design_execution_planning/contracts.py` — add `ExecutionUnit.expected_existence_effects` and allow CREATE-only units.
- Modify `platform/execution_planning/src/design_execution_planning/hashing.py` — commit non-empty existence effects while omitting the field for legacy units.
- Modify `platform/execution_planning/src/design_execution_planning/planner.py` — resolve generic rule IDs across all Step28 rule kinds and select slices using the union of rule IDs.
- Modify `platform/execution_planning/src/design_execution_planning/integrity.py` if required for new unit hash recomputation.
- Modify `tests/execution_planning/test_step30_planner.py`, `test_step30_scope_selection.py`, `test_step30_hashing.py`, and `test_step30_integrity.py`.

### End-to-end governance proof

- Add `tests/integration/test_step36_offset_creation_authority.py` — construct the real Step27-32 authority chain with public APIs, then feed one/two provider-neutral CREATE changes into Step33.
- Reuse unchanged Step31 ProviderBinding and Step32 gateway APIs; production changes there are forbidden unless a RED proves an existing contract cannot carry the exact Step36 lineage.

### AutoCAD provider and Host

- Modify `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py` — add native OFFSET capability/profile metadata.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py` — expose `cad.offset` / canonical `offset.v1` metadata.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/adapter/model_adapter.py` — serialize the exact Host wire.
- Modify `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py` — public `offset(...)` dispatch with existing idempotency/retry semantics.
- Add `tests/integration/test_step36_autocad_offset_command.py` — freeze capability and HostCommand wire offline.
- Add `tests/integration/test_step36_live_autocad_offset_create.py` — live RED/GREEN for actual native creation, revision, source immutability, and replay.
- Add `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Model/OffsetHandler.cs` — strict command parsing and lock orchestration.
- Add `hosts/autocad/plugin/AutoCAD.AgentHost/Verification/OffsetVerifier.cs` — Host-local result/postcondition verification.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs` — one-transaction supported Polyline offset helper.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs` — register `offset.v1`.

### Final live reconciliation and CI

- Add `tests/integration/test_step36_live_offset_scope_acceptance.py` — use the real created Host ref and real revisions in provider-neutral Step33 comparison.
- Add `.github/workflows/step36-offset-create-scope-breach.yml` — focused offline authority/provider/reconciliation tests plus full regression/import/lint/diff gates; real AutoCAD remains a local explicit acceptance gate.

---

### Task 1: Define canonical existence effects and `offset.v1`

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `platform/orchestrator/src/design_orchestrator/parameter_binder.py`
- Test: `tests/orchestrator/test_canonical_operations.py`
- Test: `tests/orchestrator/test_parameter_binder.py`

**Interfaces:**
- Produces: `CanonicalExistenceEffect.CREATE` / `.DELETE`.
- Produces: `CanonicalCreationContract(entity_kinds: tuple[str, ...], max_count: int, required_derivation: str)`.
- Produces: `OFFSET_V1: CanonicalOperationDefinition`.
- Produces: `OFFSET_V1_BINDING_RECIPE: OperationBindingRecipe`.
- `CanonicalOperationDefinition.existence_effects` defaults to `()` and `creation_contract` defaults to `None` so legacy definitions remain source-compatible.

- [ ] **Step 1: Write the failing contract tests**

Add tests that import the new symbols and freeze the exact contract:

```python
from design_orchestrator.canonical_operations import (
    CanonicalExistenceEffect,
    OFFSET_V1,
    SlotBindingClass,
)


def test_offset_v1_has_closed_create_envelope_and_no_native_direction_semantics():
    op = OFFSET_V1
    assert op.canonical_operation == "offset.v1"
    assert op.version == "1.0.0"
    assert op.category == "MODEL_OPERATION"
    assert op.effects == ()
    assert op.existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert op.creation_contract.entity_kinds == ("ifc:IfcWall",)
    assert op.creation_contract.max_count == 1
    assert op.creation_contract.required_derivation == "RULE-OFFSET-WALL"
    assert op.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert op.slot_binding_policy["distance"] is SlotBindingClass.INTENT
    assert op.slot_binding_policy["side_point"] is SlotBindingClass.INTENT
    assert op.input_schema["properties"]["targets"]["maxItems"] == 1
    material = repr(op.input_schema) + repr(op.canonical_entity_constraints)
    assert "LWPOLYLINE" not in material
    assert "GetOffsetCurves" not in material
```

Also test invalid combinations:

```python
def test_create_requires_a_creation_contract():
    with pytest.raises(ValueError, match="creation_contract"):
        CanonicalOperationDefinition(
            canonical_operation="bad.v1",
            version="1.0.0",
            title="bad",
            description="bad",
            category="MODEL_OPERATION",
            input_schema={"type": "object", "properties": {}, "required": []},
            slot_binding_policy={},
            verification_contract={},
            effects=(),
            existence_effects=(CanonicalExistenceEffect.CREATE,),
        )
```

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
python -m pytest tests/orchestrator/test_canonical_operations.py -q
```

Expected: import/attribute failure for `CanonicalExistenceEffect`, `CanonicalCreationContract`, or `OFFSET_V1`, not an environment failure.

- [ ] **Step 3: Add minimal canonical value contracts and validation**

Implement normalized immutable contracts:

```python
class CanonicalExistenceEffect(str, Enum):
    CREATE = "CREATE"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class CanonicalCreationContract:
    entity_kinds: tuple[str, ...]
    max_count: int
    required_derivation: str

    def __post_init__(self) -> None:
        kinds = tuple(sorted({_required_text(v, field_name="entity_kind") for v in self.entity_kinds}))
        if not kinds:
            raise ValueError("entity_kinds requires at least one canonical kind")
        if not isinstance(self.max_count, int) or isinstance(self.max_count, bool) or self.max_count <= 0:
            raise ValueError("max_count must be a positive integer")
        object.__setattr__(self, "entity_kinds", kinds)
        object.__setattr__(self, "required_derivation", _required_text(self.required_derivation, field_name="required_derivation"))
```

Extend `CanonicalOperationDefinition` with defaulted `existence_effects` / `creation_contract`; normalize/sort existence effects and enforce:

```python
if not self.effects and not existence_effects:
    raise ValueError("canonical operation requires an aspect effect or existence effect")
if CanonicalExistenceEffect.CREATE in existence_effects and self.creation_contract is None:
    raise ValueError("CREATE requires creation_contract")
if self.creation_contract is not None and CanonicalExistenceEffect.CREATE not in existence_effects:
    raise ValueError("creation_contract requires CREATE existence effect")
```

- [ ] **Step 4: Add `OFFSET_V1` and binding recipe**

Use the frozen schema:

```python
OFFSET_V1 = CanonicalOperationDefinition(
    canonical_operation="offset.v1",
    version="1.0.0",
    title="Offset wall",
    description="Create one wall-like entity offset from one source wall on the side indicated by a canonical point.",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 1},
            "distance": {
                "type": "object",
                "properties": {"value": {"type": "number", "exclusiveMinimum": 0}, "unit": {"const": "mm"}},
                "required": ["value", "unit"],
                "additionalProperties": False,
            },
            "side_point": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}, "unit": {"const": "mm"}
                },
                "required": ["x", "y", "z", "unit"],
                "additionalProperties": False,
            },
        },
        "required": ["targets", "distance", "side_point"],
        "additionalProperties": False,
    },
    slot_binding_policy={"targets": SlotBindingClass.CONTEXT, "distance": SlotBindingClass.INTENT, "side_point": SlotBindingClass.INTENT},
    canonical_entity_constraints=("ifc:IfcWall",),
    effects=(),
    existence_effects=(CanonicalExistenceEffect.CREATE,),
    creation_contract=CanonicalCreationContract(("ifc:IfcWall",), 1, "RULE-OFFSET-WALL"),
    verification_contract={},
)
```

Add `OFFSET_V1` to `MVP_CANONICAL_OPERATIONS`, add an `OperationBindingRecipe` that resolves only `targets` from context selection, and add `OFFSET_V1_BINDING_RECIPE` to the MVP recipes.

- [ ] **Step 5: Run orchestrator regression**

```powershell
python -m pytest tests/orchestrator -q
```

Expected: PASS; legacy move/wall tests remain unchanged.

- [ ] **Step 6: Commit**

```powershell
git add platform/orchestrator/src/design_orchestrator/canonical_operations.py platform/orchestrator/src/design_orchestrator/parameter_binder.py tests/orchestrator
git commit -m "feat: define canonical offset create action"
```

---

### Task 2: Carry CREATE intent through Step27 without changing legacy fingerprints

**Files:**
- Modify: `platform/impact/src/design_impact/contracts.py`
- Modify: `platform/impact/src/design_impact/analyzer.py`
- Test: `tests/impact/test_step27_contracts.py`
- Test: `tests/impact/test_step27_analyzer.py`

**Interfaces:**
- Consumes: `CanonicalExistenceEffect` from Task 1.
- Produces: `IntentBoundary.allowed_existence_effects: tuple[CanonicalExistenceEffect, ...] = ()`.
- Produces: Step27 analysis fingerprint that includes `allowed_existence_effects` only when non-empty.

- [ ] **Step 1: Write RED contract/fingerprint tests**

Add:

```python
def test_intent_boundary_normalizes_existence_effects():
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_existence_effects=("CREATE", "CREATE"),
    )
    assert tuple(v.value for v in intent.allowed_existence_effects) == ("CREATE",)
```

In the analyzer test, define the pre-Step36 intent payload helper exactly as the old implementation:

```python
def _legacy_intent_payload(intent):
    return {
        "direct_targets": list(intent.direct_targets),
        "allowed_canonical_effects": list(intent.allowed_canonical_effects),
        "allowed_derived_rule_refs": list(intent.allowed_derived_rule_refs),
    }
```

Build the same legacy analysis fixture twice: once with the new default field omitted and once by recomputing the old payload/hash helper used in the test. Assert they are identical. Build a second fixture with `allowed_existence_effects=(CREATE,)` and assert its analysis fingerprint differs.

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
python -m pytest tests/impact/test_step27_contracts.py tests/impact/test_step27_analyzer.py -q
```

Expected: constructor/import failure for `allowed_existence_effects` or fingerprint mismatch.

- [ ] **Step 3: Implement normalized intent field**

Add the field after existing default fields and normalize via the Task 1 enum:

```python
allowed_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
```

Store a deterministic tuple ordered by `.value`.

- [ ] **Step 4: Make fingerprint serialization backward compatible**

Construct intent payload exactly as before, then conditionally add:

```python
existence = [value.value for value in request.intent_boundary.allowed_existence_effects]
if existence:
    payload["intent_boundary"]["allowed_existence_effects"] = existence
```

Do not add an empty key.

- [ ] **Step 5: Run Step27 suite**

```powershell
python -m pytest tests/impact -q
```

Expected: PASS, including the legacy payload equivalence assertion.

- [ ] **Step 6: Commit**

```powershell
git add platform/impact/src/design_impact/contracts.py platform/impact/src/design_impact/analyzer.py tests/impact
git commit -m "feat: carry creation intent through impact analysis"
```

---

### Task 3: Admit a closed `CreationRule` in Step28

**Files:**
- Modify: `platform/approval_scope/src/design_approval_scope/contracts.py`
- Modify: `platform/approval_scope/src/design_approval_scope/planner.py`
- Modify: `platform/approval_scope/src/design_approval_scope/hashing.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Test: `tests/approval_scope/test_step28_contracts.py`
- Test: `tests/approval_scope/test_step28_planner.py`
- Test: `tests/approval_scope/test_step28_hashing.py`
- Test: `tests/approval_scope/test_step28_integrity.py`

**Interfaces:**
- Consumes: Task 1 canonical existence enum/envelope and Task 2 intent boundary.
- Produces: `CanonicalEffectEvidence.allowed_existence_effects`, `.creation_contract`.
- Produces: deterministic `creation_rule_id(rule: CreationRule) -> str` or equivalent planner-owned construction ID.
- Produces: Step28 `ApprovalScopeDefinition.creation_rules` containing only admitted, exact-or-narrower CREATE authority.

- [ ] **Step 1: Write RED tests for CREATE evidence and empty aspect authority**

Add:

```python
def test_create_effect_evidence_may_have_no_existing_entity_aspects():
    evidence = CanonicalEffectEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        allowed_aspects=(),
        allowed_existence_effects=("CREATE",),
        creation_contract=CanonicalCreationContract(("ifc:IfcWall",), 1, "RULE-OFFSET-WALL"),
    )
    assert evidence.allowed_aspects == ()
```

Also prove `allowed_aspects=(), allowed_existence_effects=()` is rejected and `creation_contract` without CREATE is rejected.

- [ ] **Step 2: Write RED planner tests for narrowing and fail-closed expansion**

Use one direct target `WALL-001`, no existing-entity effects, CREATE intent, and one requested rule:

```python
requested = CreationRule(
    rule_id="REQUEST-1",
    canonical_operation="offset.v1",
    source_selector=EntitySelector(entities=("WALL-001",)),
    entity_kinds=("ifc:IfcWall",),
    max_count=1,
    required_derivation="RULE-OFFSET-WALL",
)
```

Assert planning admits one rule and that the slice rule references its final deterministic ID. Add parameterized negative cases:

```python
("wrong operation", replace(requested, canonical_operation="copy.v1"), "SCOPE_RULE_INVALID")
("extra source", replace(requested, source_selector=EntitySelector(entities=("WALL-001", "WALL-999"))), "SCOPE_RULE_INVALID")
("wider kind", replace(requested, entity_kinds=("ifc:IfcWall", "ifc:IfcDoor")), "SCOPE_RULE_INVALID")
("missing count", replace(requested, max_count=None), "SCOPE_RULE_INVALID")
("larger count", replace(requested, max_count=2), "SCOPE_RULE_INVALID")
("wrong derivation", replace(requested, required_derivation="RULE-OTHER"), "SCOPE_RULE_INVALID")
```

Also assert DELETE still raises `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`.

- [ ] **Step 3: Run focused Step28 tests and observe RED**

```powershell
python -m pytest tests/approval_scope/test_step28_contracts.py tests/approval_scope/test_step28_planner.py -q
```

Expected: current planner raises `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` for the valid CREATE request.

- [ ] **Step 4: Implement CREATE evidence and planner admission**

Change evidence normalization so aspect authority is allowed to be empty only when existence authority is non-empty. In planner, split the old blanket check:

```python
if request.requested_deletion_rules:
    _error("SCOPE_EXISTENCE_EFFECT_UNSUPPORTED", "Step36 does not admit deletion authority")
```

For each requested creation rule, require CREATE in both canonical evidence and intent, explicit entity source selector, subset kinds, `max_count is not None and <= envelope.max_count`, exact derivation, and exact canonical operation. Rebuild the admitted `CreationRule` using deterministic construction identity from its semantic payload; never silently alter authority fields.

Validate `ExecutionSliceScopeRule.creation_rule_ids` against the admitted rule IDs and require full closed-world coverage, alongside existing rule coverage.

- [ ] **Step 5: Preserve Step28 legacy hash payloads**

In `hashing.py`, keep `_canonical_effect_payload()` and `_intent_payload()` byte-equivalent for empty existence fields. Add keys only when non-empty:

```python
if evidence.allowed_existence_effects:
    payload["allowed_existence_effects"] = [item.value for item in evidence.allowed_existence_effects]
if evidence.creation_contract is not None:
    payload["creation_contract"] = {
        "entity_kinds": list(evidence.creation_contract.entity_kinds),
        "max_count": evidence.creation_contract.max_count,
        "required_derivation": evidence.creation_contract.required_derivation,
    }
```

Do the same conditional serialization for intent. In tests, reconstruct the old Step28 payload algorithm for a legacy `move.v1` fixture and assert the new hash equals it; then assert a Step36 scope changes when `max_count` or derivation changes.

- [ ] **Step 6: Run all Step28 regressions**

```powershell
python -m pytest tests/approval_scope -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add platform/approval_scope/src/design_approval_scope tests/approval_scope
git commit -m "feat: admit closed creation scope"
```

---

### Task 4: Make Step29 creation-rule aware and hash CREATE semantics

**Files:**
- Modify: `platform/changeset/src/design_changeset/contracts.py`
- Modify: `platform/changeset/src/design_changeset/hashing.py`
- Modify: `platform/changeset/src/design_changeset/builder.py`
- Modify: `platform/changeset/src/design_changeset/integrity.py`
- Test: `tests/changeset/test_step29_contracts.py`
- Test: `tests/changeset/test_step29_hashing.py`
- Test: `tests/changeset/test_step29_builder.py`
- Test: `tests/changeset/test_step29_integrity.py`

**Interfaces:**
- Produces defaulted `CanonicalOperationContractEvidence.existence_effects` and `.creation_contract`.
- Produces defaulted `CanonicalChangeOperation.expected_existence_effects`.
- `compute_scope_rule_fingerprint(rule)` accepts Existing/Creation/Deletion rules but retains the exact old Existing payload.
- `compute_operation_semantic_hash(..., expected_existence_effects=())` conditionally commits CREATE semantics.

- [ ] **Step 1: Write RED type/fingerprint compatibility tests**

Add a legacy fingerprint helper that exactly reproduces the current Existing rule payload:

```python
def _legacy_existing_rule_fingerprint(rule):
    selector = {"entities": list(rule.selector.entities)}
    return canonical_hash({
        "selector": selector,
        "allowed_aspects": sorted(item.value for item in rule.allowed_aspects),
    })
```

Assert the new generic function still equals this value for an Existing rule. Add a Creation rule assertion:

```python
fingerprint = compute_scope_rule_fingerprint(creation_rule)
assert fingerprint != compute_scope_rule_fingerprint(existing_rule)
assert fingerprint == compute_scope_rule_fingerprint(replace(creation_rule, rule_id="DIFFERENT-ID"))
```

- [ ] **Step 2: Write RED builder test for one unique CreationRule**

Build exact `CanonicalOperationContractEvidence` for `offset.v1` with no aspect effects, CREATE existence effect, the frozen creation contract, and empty verification contract. Build a Step28 scope definition containing one creation rule. Assert the root operation has:

```python
assert changeset.root_operation.expected_effects == ()
assert tuple(v.value for v in changeset.root_operation.expected_existence_effects) == ("CREATE",)
assert changeset.root_operation.scope_rule_ids == (creation_rule.rule_id,)
assert changeset.validation_tasks == ()
```

Create a second equally compatible CreationRule for the same operation/source and assert builder fails with stable code `CHANGESET_SCOPE_MEMBERSHIP_AMBIGUOUS` rather than choosing arbitrarily.

- [ ] **Step 3: Run focused tests and observe RED**

```powershell
python -m pytest tests/changeset/test_step29_hashing.py tests/changeset/test_step29_builder.py -q
```

Expected: current rule fingerprint accesses `.selector/.allowed_aspects` on `CreationRule` or current builder fails because only Existing rules can cover targets.

- [ ] **Step 4: Extend exact contract and operation contracts**

Append defaulted fields so old constructors continue to work:

```python
@dataclass(frozen=True, slots=True)
class CanonicalOperationContractEvidence:
    ...
    definition_fingerprint: str
    existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
    creation_contract: Mapping[str, Any] | None = None

@dataclass(frozen=True, slots=True)
class CanonicalChangeOperation:
    ...
    source_evidence: OperationSourceEvidence
    expected_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
```

Permit `effects=()` only when existence effects are non-empty. Require CREATE contract evidence when CREATE is present.

- [ ] **Step 5: Implement conditional contract/operation hashing**

Keep the existing payload construction, then add existence keys only when non-empty. For rule fingerprints, branch by concrete type. The Existing branch must preserve the pre-Step36 payload exactly; Creation payload must contain:

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

Deletion may get a typed payload for completeness but remains unadmitted.

- [ ] **Step 6: Implement unique CREATE scope coverage**

Split root scope resolution by exact contract authority:

```python
if contract.existence_effects:
    return _cover_creation_scope(...)
return _cover_existing_scope(...)
```

`_cover_creation_scope` must select rules whose operation matches, whose explicit source selector exactly covers the bound source target(s), and whose envelope is within the exact contract. Require exactly one compatible rule; zero => `CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED`, more than one => `CHANGESET_SCOPE_MEMBERSHIP_AMBIGUOUS`.

Do not allocate a created semantic ID. Do not add a canonical validation task when `verification_contract` is empty.

- [ ] **Step 7: Update integrity recomputation and run Step29 suite**

Ensure integrity recomputes contract definition and operation hashes with conditional existence fields.

```powershell
python -m pytest tests/changeset -q
```

Expected: PASS, including legacy fingerprint-equivalence tests.

- [ ] **Step 8: Commit**

```powershell
git add platform/changeset/src/design_changeset tests/changeset
git commit -m "feat: bind creation authority into changesets"
```

---

### Task 5: Carry CREATE authority into Step30 execution units and slice selection

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/contracts.py`
- Modify: `platform/execution_planning/src/design_execution_planning/hashing.py`
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Modify: `platform/execution_planning/src/design_execution_planning/integrity.py`
- Test: `tests/execution_planning/test_step30_planner.py`
- Test: `tests/execution_planning/test_step30_scope_selection.py`
- Test: `tests/execution_planning/test_step30_hashing.py`
- Test: `tests/execution_planning/test_step30_integrity.py`

**Interfaces:**
- Consumes: Task 4 generic `scope_rule_ids` and `expected_existence_effects`.
- Produces: `ExecutionUnit.expected_existence_effects=()`.
- Resolves generic scope IDs across all Step28 rule kinds.
- Selects a pre-existing Step28 slice rule using the union of existing/creation/deletion rule IDs.

- [ ] **Step 1: Write RED planner/scope-selection tests**

Using a Step29 `offset.v1` ChangeSet with one CreationRule, route only `WALL-001` to one AutoCAD runtime and assert:

```python
plan = ExecutionPlanner().plan(request)
unit = plan.execution_slices[0].execution_units[0]
assert unit.targets == ("WALL-001",)
assert unit.expected_effects == ()
assert tuple(v.value for v in unit.expected_existence_effects) == ("CREATE",)
assert plan.execution_slices[0].approved_scope_ref.execution_slice_scope_rule_id == creation_slice.slice_scope_rule_id
```

Add a negative case where the document's slice rule omits the CreationRule ID and assert `EXECUTION_SLICE_SCOPE_UNCOVERED`.

Add a boundary with the same `rule_id` reused by Existing and Creation rules and assert `EXECUTION_SCOPE_MISMATCH`.

- [ ] **Step 2: Run focused tests and observe RED**

```powershell
python -m pytest tests/execution_planning/test_step30_planner.py tests/execution_planning/test_step30_scope_selection.py -q
```

Expected: current `_validate_scope_binding()` reports unknown rule because it indexes only Existing rules, or current unit rejects empty expected effects.

- [ ] **Step 3: Extend ExecutionUnit and its hash compatibly**

Append:

```python
expected_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
```

Allow `expected_effects=()` only when the existence tuple is non-empty. In `compute_execution_unit_hash`, preserve the old payload and conditionally add:

```python
if expected_existence_effects:
    payload["expected_existence_effects"] = sorted(v.value for v in expected_existence_effects)
```

Add a test helper reproducing the old execution-unit hash for a legacy move fixture and assert equality.

- [ ] **Step 4: Resolve rule IDs through a closed union**

Build indexes for all three Step28 rule types; reject duplicate IDs across the union. Return a generic map used only for fingerprint resolution. `_source_operation_hash()` must call the Task 4 generic fingerprint function.

- [ ] **Step 5: Select slice authority from the union**

Change coverage in `_select_slice_scope()` from:

```python
required.issubset(candidate.existing_rule_ids)
```

to:

```python
authority = set(candidate.existing_rule_ids) | set(candidate.creation_rule_ids) | set(candidate.deletion_rule_ids)
if not required.issubset(authority):
    continue
```

Keep least-authority surplus calculation/tie-breaking intact. Do not synthesize or rewrite the slice rule.

- [ ] **Step 6: Update unit/integrity construction and run Step30 suite**

Copy `operation.expected_existence_effects` into the unit, include it in unit hash recomputation, and run:

```powershell
python -m pytest tests/execution_planning -q
```

Expected: PASS with legacy hash compatibility.

- [ ] **Step 7: Commit**

```powershell
git add platform/execution_planning/src/design_execution_planning tests/execution_planning
git commit -m "feat: partition creation-authorized execution"
```

---

### Task 6: Prove the provider-neutral Step27-33 creation authority chain offline

**Files:**
- Create: `tests/integration/test_step36_offset_creation_authority.py`
- Modify production: none unless a focused RED identifies a real missing Step31/32 lineage capability.

**Interfaces:**
- Consumes public Step27 Impact, Step28 scope, Step29 ChangeSet, Step30 plan, Step31 ProviderBinding, Step32 admission, Step33 `ActualDelta`/`ScopeComparator` APIs.
- Produces deterministic proof of `WITHIN_SCOPE` for one create and `CREATION_COUNT_EXCEEDED` for two creates.

- [ ] **Step 1: Build one exact public-API fixture and write the one-create assertion**

The fixture must use:

```python
SOURCE = "WALL-001"
CREATED_KIND = "ifc:IfcWall"
DERIVATION = "RULE-OFFSET-WALL"
```

Create the canonical bound operation, Step27 intent with CREATE, Step28 one CreationRule/max_count=1, Step29 ChangeSet, Step30 AutoCAD route/slice, a Step31 binding for the **source** native ref only, and a real Step32 admitted authority using the existing public store/admission APIs.

Construct one provider-neutral change:

```python
one = ActualChange(
    change_kind=ActualChangeKind.CREATE,
    actual_change_hash="<computed with Step33 helper>",
    canonical_kind=CREATED_KIND,
    canonical_operation="offset.v1",
    source_execution_unit_hash=unit.execution_unit_hash,
    source_semantic_id=SOURCE,
    source_canonical_kind="ifc:IfcWall",
    derivation_rule=DERIVATION,
    host_entity_ref=HostEntityRef(document_id="DOC-A", native_id="C01", native_type="Polyline"),
)
```

Use the existing Step33 hash constructor rather than a literal digest. Assert:

```python
result = ScopeComparator().compare(request_with((one,)))
assert result.status is ScopeComparisonStatus.WITHIN_SCOPE
assert len(result.matched_changes) == 1
assert result.matched_changes[0].rule_id == creation_rule.rule_id
```

- [ ] **Step 2: Add the two-create SCOPE_BREACH proof**

Create a second change identical in canonical authority but with another Host entity ref/hash:

```python
result = ScopeComparator().compare(request_with((one, two)))
assert result.status is ScopeComparisonStatus.SCOPE_BREACH
assert [v.reason_code for v in result.violations] == ["CREATION_COUNT_EXCEEDED"]
```

Also add focused wrong-kind, wrong-source, and wrong-derivation assertions and freeze their existing Step33 reason codes.

- [ ] **Step 3: Run the new integration test and observe any remaining RED**

```powershell
python -m pytest tests/integration/test_step36_offset_creation_authority.py -q
```

Expected after Tasks 1-5: one-create and two-create cases PASS without Step31/32 production changes. If it fails in Step31/32, stop and prove the failure is a contract gap before modifying those packages; do not broaden authority speculatively.

- [ ] **Step 4: Run Step28-33 regressions**

```powershell
python -m pytest tests/approval_scope tests/changeset tests/execution_planning tests/provider_binding tests/gateway_authorization tests/execution_reconciliation -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/integration/test_step36_offset_creation_authority.py
git commit -m "test: prove Step36 creation scope authority"
```

---

### Task 7: Add the AutoCAD OFFSET provider surface and freeze Host wire offline

**Files:**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/model_adapter.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py`
- Test: `tests/integration/test_step36_autocad_offset_command.py`

**Interfaces:**
- Produces provider capability canonical operation `offset.v1`, native source constraint `LWPOLYLINE`/Polyline-compatible profile, existence effect CREATE.
- Produces `CommandDispatcher.offset(handles, distance, side_point, *, idempotency_key, revision)`.
- Frozen Host operation: `offset.v1`.
- Frozen Host arguments contain only `distance` and `sidePoint`; targets are Host native refs.

- [ ] **Step 1: Write the offline RED capability/wire test**

Use a fake transport that records one `HostCommand`. Assert:

```python
result = await dispatcher.offset(
    ["2C6"],
    {"value": 300.0, "unit": "mm"},
    {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
    idempotency_key="step36-offset-1",
    revision=7,
)
command = transport.commands[0]
assert command.operation == "offset.v1"
assert [target.native_id for target in command.targets] == ["2C6"]
assert command.arguments == {
    "distance": {"value": 300.0, "unit": "mm"},
    "sidePoint": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
}
wire = repr(command.to_dict())
assert "CreationRule" not in wire
assert "grant" not in wire.lower()
assert "ifc:IfcWall" not in wire
```

Assert same key/content replays using existing sidecar semantics and mismatched content/key remains protected by existing idempotency rules.

- [ ] **Step 2: Run RED test**

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py -q
```

Expected: missing `offset` dispatcher/capability behavior.

- [ ] **Step 3: Implement minimal provider metadata and wire projection**

Expose `cad.offset` with canonical metadata `offset.v1`; keep native constraints provider-local. In `ModelAdapter`, require exactly one source native target and serialize:

```python
operation="offset.v1"
arguments={"distance": distance, "sidePoint": side_point}
```

Do not serialize semantic source IDs or the creation envelope to Host.

- [ ] **Step 4: Implement public dispatcher and strict argument validation**

Validate literal `mm`, positive finite distance, finite side-point coordinates, one handle, revision/idempotency as existing command dispatcher patterns require. Reuse the current retry/idempotency mechanism rather than creating Step36-specific caches.

- [ ] **Step 5: Run offline sidecar regressions**

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py tests/integration/test_step34_autocad_wall_thickness_command.py -q
```

If the exact Step34 command test filename differs, use the existing Step34 sidecar command test selected by `python -m pytest tests/integration -k "wall_thickness and command" -q`.

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add hosts/autocad/sidecar/src/autocad_sidecar tests/integration/test_step36_autocad_offset_command.py
git commit -m "feat: expose AutoCAD offset command"
```

---

### Task 8: Capture the required real AutoCAD OFFSET RED before C# production code

**Files:**
- Create: `tests/integration/test_step36_live_autocad_offset_create.py`
- Production C#: no changes in this task.

**Interfaces:**
- Consumes the shared dynamic-pipe live helper already established by Step34.
- Fixture: exactly one selected `A-WALL` Polyline/LWPOLYLINE in a document whose `INSUNITS=4` (millimetres).
- Expected first RED: Host returns unknown command type `offset.v1` (or equivalent missing-handler error) after fixture/revision checks pass.

- [ ] **Step 1: Write the gated live test**

Gate with `AGENT_HOST_TEST=1`. Discover the dynamic pipe through the existing shared helper. Preflight current document/revision, exactly one selected Polyline, A-WALL classification fact, and record source bounds/width evidence. Choose a side point that is unambiguously on one side of the fixture and call:

```python
result = await dispatcher.offset(
    [handle],
    {"value": 300.0, "unit": "mm"},
    SIDE_POINT,
    idempotency_key=f"step36-live-offset-{uuid.uuid4()}",
    revision=revision_before,
)
assert result.ok, result.error
```

The GREEN assertions (not yet reachable) must require one returned `createdEntityRef`, revision +1, source evidence unchanged, and created entity readable on A-WALL.

- [ ] **Step 2: Run only offline collection first**

```powershell
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected without `AGENT_HOST_TEST=1`: SKIPPED, proving collection/import is clean.

- [ ] **Step 3: Run the real test against the current Step34 plugin and observe RED**

This is the first Step36 step that requires the user/real AutoCAD runtime:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected: fixture preflight passes, request reaches Host, and Host fails because `offset.v1` is not registered. Record the exact RED before writing C# production code.

- [ ] **Step 4: Commit the RED test unchanged**

```powershell
git add tests/integration/test_step36_live_autocad_offset_create.py
git commit -m "test: capture Step36 live offset RED"
```

---

### Task 9: Implement atomic AutoCAD native OFFSET and Host handler

**Files:**
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADEntityApi.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Model/OffsetHandler.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Verification/OffsetVerifier.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs`
- Test: `tests/integration/test_step36_live_autocad_offset_create.py`

**Interfaces:**
- Produces native helper conceptually:
  `OffsetPolyline(string handle, double distanceMm, Point3d sidePoint) -> (HostEntityRef Created, evidence...)`.
- Host command operation: `offset.v1`.
- Success payload includes exactly one created Host entity ref and Host-local verification data.
- Revision advances only after one transaction commits.

- [ ] **Step 1: Implement strict handler wire parsing only after Task 8 RED**

Parse exactly:

```csharp
arguments.distance.value
arguments.distance.unit == "mm"
arguments.sidePoint.x / y / z
arguments.sidePoint.unit == "mm"
```

Reject non-finite/non-positive distance, non-finite coordinates, target count other than one, and unsupported units with deterministic Host errors. Acquire the existing document lock before invoking native mutation.

- [ ] **Step 2: Implement one-transaction native offset helper**

Inside one AutoCAD transaction:

1. require active document and `Database.Insunits == UnitsValue.Millimeters`;
2. resolve the one Handle and require `Polyline`;
3. call native offset candidate generation for both `+distance` and `-distance` without mutating the source;
4. filter to supported Polyline results;
5. score candidate side using minimum distance from `sidePoint` (or another deterministic geometric measure explicitly implemented in the helper), reject ties within a fixed tolerance such as `1e-6`;
6. require exactly one selected supported result;
7. set the created entity layer to the source layer;
8. append it to the source owner `BlockTableRecord` and register it with the transaction;
9. verify source geometry/evidence has not been modified and created entity is valid/readable;
10. commit once, then bump revision, then return its real Handle/HostEntityRef.

Dispose unselected transient offset DBObjects to avoid unmanaged leaks. Never commit an ambiguous/multi-result candidate set.

- [ ] **Step 3: Add Host-local `OffsetVerifier`**

Verifier receives source-before/source-after evidence, requested distance/side point, and created entity evidence. It must at minimum assert one created entity, source unchanged under the frozen evidence fields, created entity is supported Polyline, and created layer equals source layer. Return a DTO with `ok`, message, and deterministic details; do not use this DTO as Step33 semantic success.

- [ ] **Step 4: Register handler and build locally**

```powershell
dotnet build .\hosts\autocad\plugin\AutoCAD.AgentHost\AutoCAD.AgentHost.csproj -c Debug
```

Expected: `Build succeeded`, 0 errors. This build does not prove Autodesk runtime behavior.

- [ ] **Step 5: Run non-AutoCAD regressions**

```powershell
python -m pytest tests/integration/test_step36_autocad_offset_command.py -q
python -m pytest tests/integration/test_step34_autocad_wall_thickness_command.py -q
```

Use `-k` selection if the exact existing Step34 command filename differs. Expected: PASS.

- [ ] **Step 6: Commit production C#**

```powershell
git add hosts/autocad/plugin/AutoCAD.AgentHost hosts/autocad/sidecar/src/autocad_sidecar tests/integration/test_step36_autocad_offset_command.py
git commit -m "feat: execute atomic AutoCAD offset creation"
```

---

### Task 10: Prove real AutoCAD creation, source immutability, revision, and idempotency

**Files:**
- Modify: `tests/integration/test_step36_live_autocad_offset_create.py`
- Production: only if a new observed live RED identifies a specific defect.

**Interfaces:**
- Real Host success returns exactly one actual `HostEntityRef`.
- Same idempotency key/content replays the same result and creates no second entity.
- Source remains unchanged under the pre/post native evidence used by the live test.

- [ ] **Step 1: Rebuild/reload the new plugin and rerun the exact Task 8 test**

After user rebuild/restart/NETLOAD, use the same real fixture and run:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected: `1 passed`. If it fails, apply systematic debugging; do not weaken fixture/assertions to obtain green.

- [ ] **Step 2: Extend the live test with replay proof**

Use a single generated key for two identical calls in one test. After the first success, capture the created ref and revision. Repeat exactly the same command/key and assert:

```python
assert replay.ok
assert replay.replayed is True
assert replay.revision_after == first.revision_after
assert replay.payload["createdEntityRef"] == first.payload["createdEntityRef"]
```

Re-read the source/created entities and prove no second created entity appears in the command's returned evidence. If Host exposes no collection query adequate to count all entities, the invariant is the same created ref + unchanged revision on replay; do not invent a new enumeration API for Step36.

- [ ] **Step 3: Add stale-revision and non-mm negative cases using the existing Step34 pattern**

Stale revision must fail before mutation and leave revision/source evidence unchanged. Non-mm must return the deterministic existing `UNSUPPORTED_DOCUMENT_UNITS` class before commit. Keep these as separate test functions so fixture changes are explicit.

- [ ] **Step 4: Run the live tests and record GREEN**

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_autocad_offset_create.py -q
```

Expected: all enabled Step36 live Host tests PASS.

- [ ] **Step 5: Commit test refinements/fixes**

```powershell
git add tests/integration/test_step36_live_autocad_offset_create.py hosts/autocad/plugin/AutoCAD.AgentHost
git commit -m "test: prove live AutoCAD offset creation"
```

---

### Task 11: Feed the real created Host ref into Step33 scope acceptance

**Files:**
- Create: `tests/integration/test_step36_live_offset_scope_acceptance.py`
- Reuse: public Step27-33 APIs and shared live AutoCAD helper.

**Interfaces:**
- Consumes real `document_ref`, `host_instance_id`, source Handle, created Handle, `revision_before`, `revision_after`.
- Produces provider-neutral `ActualDelta.CREATE` with `canonical_operation="offset.v1"`, `canonical_kind="ifc:IfcWall"`, `source_semantic_id="WALL-001"`, `derivation_rule="RULE-OFFSET-WALL"`.
- Must not put `LWPOLYLINE`, signed native distance, or raw source Handle into canonical comparator fields.

- [ ] **Step 1: Write the gated live acceptance test before changing production**

Build the exact Step27-32 authority chain in the test (same public APIs as Task 6), bind the real selected source Handle in Step31, execute the real `offset.v1`, then construct `ActualChange.CREATE` from the actual returned created `HostEntityRef` and real revisions.

Assert provider-neutral boundary:

```python
assert actual_change.change_kind is ActualChangeKind.CREATE
assert actual_change.canonical_operation == "offset.v1"
assert actual_change.canonical_kind == "ifc:IfcWall"
assert actual_change.source_semantic_id == "WALL-001"
assert actual_change.derivation_rule == "RULE-OFFSET-WALL"
assert actual_change.host_entity_ref.native_id == created_ref.native_id
assert "LWPOLYLINE" not in repr(actual_delta)
assert "GetOffsetCurves" not in repr(actual_delta)
```

Then:

```python
comparison = ScopeComparator().compare(scope_request)
assert comparison.status is ScopeComparisonStatus.WITHIN_SCOPE
assert comparison.violations == ()
```

This is the Step36 live success criterion; do not add a fake SemanticVerifier task just to force Saga `SUCCEEDED`.

- [ ] **Step 2: Verify offline collection/skip**

```powershell
python -m pytest tests/integration/test_step36_live_offset_scope_acceptance.py -q
```

Expected without live flag: SKIPPED and clean collection.

- [ ] **Step 3: Run the real acceptance**

With a reset single-source fixture and loaded Step36 plugin:

```powershell
$env:AGENT_HOST_TEST="1"
python -m pytest tests/integration/test_step36_live_offset_scope_acceptance.py -q
```

Expected: PASS and Step33 `WITHIN_SCOPE` using the real created Host ref.

- [ ] **Step 4: Re-run the offline two-create breach proof**

```powershell
python -m pytest tests/integration/test_step36_offset_creation_authority.py -q
```

Expected: one CREATE `WITHIN_SCOPE`; two CREATEs `CREATION_COUNT_EXCEEDED` / `SCOPE_BREACH`.

- [ ] **Step 5: Commit**

```powershell
git add tests/integration/test_step36_live_offset_scope_acceptance.py
git commit -m "test: reconcile real offset creation scope"
```

---

### Task 12: Add Step36 CI and perform final verification

**Files:**
- Create: `.github/workflows/step36-offset-create-scope-breach.yml`
- Modify only if required: test configuration/path filters that must include Step36 files.

**Interfaces:**
- Offline CI is authoritative for Python contracts/governance/provider behavior.
- Real AutoCAD acceptance remains an explicit local acceptance proof recorded separately; GitHub runners do not emulate AutoCAD.

- [ ] **Step 1: Add dedicated workflow**

Trigger on the Step36 branch/PR paths covering:

```text
platform/orchestrator/**
platform/impact/**
platform/approval_scope/**
platform/changeset/**
platform/execution_planning/**
hosts/autocad/sidecar/**
hosts/autocad/plugin/AutoCAD.AgentHost/**
tests/orchestrator/**
tests/impact/**
tests/approval_scope/**
tests/changeset/**
tests/execution_planning/**
tests/integration/test_step36_*.py
docs/superpowers/specs/2026-08-31-step36-offset-create-scope-breach-design.md
docs/superpowers/plans/2026-08-31-step36-offset-create-scope-breach.md
```

Workflow must run at least:

```powershell
python -m pytest tests/orchestrator -q
python -m pytest tests/impact -q
python -m pytest tests/approval_scope -q
python -m pytest tests/changeset -q
python -m pytest tests/execution_planning -q
python -m pytest tests/integration/test_step36_offset_creation_authority.py tests/integration/test_step36_autocad_offset_command.py -q
python -m pytest tests/execution_reconciliation -q
python -m pytest --import-mode=importlib -q
ruff check --select E,F,I platform hosts/autocad/sidecar tests
```

Live tests remain skipped when `AGENT_HOST_TEST` is absent.

- [ ] **Step 2: Add an architecture guard for existence/native separation**

Add focused assertions to an existing Step36 integration/architecture test that canonical/Core files do not contain `GetOffsetCurves`, AutoCAD Handle assumptions, or `LWPOLYLINE` as canonical created kind, while provider/Host files may contain them. Also assert `CanonicalAspect("CREATE")` raises.

- [ ] **Step 3: Run focused offline verification locally**

```powershell
python -m pytest tests/orchestrator tests/impact tests/approval_scope tests/changeset tests/execution_planning tests/integration/test_step36_offset_creation_authority.py tests/integration/test_step36_autocad_offset_command.py tests/execution_reconciliation -q
```

Expected: PASS.

- [ ] **Step 4: Run full import-mode regression and lint**

```powershell
python -m pytest --import-mode=importlib -q
ruff check --select E,F,I platform hosts/autocad/sidecar tests
git diff --check main...HEAD
```

Expected: all PASS / no diff whitespace errors.

- [ ] **Step 5: Verify branch boundary**

```powershell
git log --oneline main..HEAD
git diff --name-only main...HEAD
```

Expected: only Step36 spec/plan, existence-authority packages/tests, AutoCAD offset provider/Host, Step36 live/integration tests, and Step36 CI. No Revit work and no unrelated refactor.

- [ ] **Step 6: Verify real AutoCAD evidence is still tied to the final functional HEAD**

Before PR creation, ensure no production AutoCAD/authority code changed after the last successful live acceptance. If production code changed, rerun the affected real AutoCAD test(s); documentation/CI-only commits do not require rebuilding the plugin.

- [ ] **Step 7: Commit CI/finalization**

```powershell
git add .github/workflows/step36-offset-create-scope-breach.yml tests
git commit -m "ci: verify Step36 offset creation scope"
```

- [ ] **Step 8: Final completion gate**

Do not mark Step36 implementation complete until all are true:

```text
canonical CREATE envelope: PASS
legacy Step23/27/28/29/30 hash compatibility: PASS
Step28 creation authority narrowing negatives: PASS
Step29 unique CreationRule binding: PASS
Step30 union-based slice selection: PASS
Step27-32 real public authority chain: PASS
one provider-neutral CREATE -> WITHIN_SCOPE: PASS
two CREATEs with max_count=1 -> CREATION_COUNT_EXCEEDED / SCOPE_BREACH: PASS
AutoCAD real offset creates exactly one entity: PASS
source immutability / revision / idempotency: PASS
real created Host ref -> Step33 WITHIN_SCOPE: PASS
full offline regression / importlib / lint / diff check: PASS
```

Only after this gate should the branch enter PR review. Do not merge without explicit user instruction.
