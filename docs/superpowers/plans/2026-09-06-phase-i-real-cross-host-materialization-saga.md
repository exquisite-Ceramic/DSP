# Phase I Real Cross-Host Materialization Saga Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen Phase I architecture so one canonical `set_wall_thickness.v1` effect for `WALL-001` produces two REQUIRED materializations, executes sequentially against real AutoCAD and real Revit, preserves truthful partial-commit semantics, and reaches Saga `SUCCEEDED` only after provider-neutral cross-Host convergence is proved.

**Architecture:** Add versioned V2 contracts around the existing Step28–37 chain instead of changing V1 meanings in place. Step28 V2 binds an immutable topology snapshot before Step29 hashes the ChangeSet; a deterministic MaterializationPlan drives Step30 V2, Step31/32 materialization-aware binding and authority, an all-required readiness barrier, Step33 V2 durable reconciliation, and a provider-neutral exact convergence gate. Phase I uses separate V2 Saga persistence and separate materialized coordination statuses; existing Step33/Step37 V1 contracts remain unchanged.

**Tech Stack:** Python 3.11 dataclasses/enums/pytest; existing DSP Step28–37 Python packages; AutoCAD Python sidecar plus existing native Host command path; Revit 2027 C#/.NET 10 native plugin plus Python sidecar; SHA-256 canonical JSON hashing; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-06-phase-i-real-cross-host-materialization-saga-design.md`

## Global Constraints

- Preserve every existing V1 Step28/29/30/31/32/33/37 public contract, hash, store, and status meaning. Any changed semantic body gets a new V2 type/hash/validator/store path.
- Keep canonical operation identity exactly `set_wall_thickness.v1`, target semantics `ifc:IfcWall`, and canonical effect exactly `PROPERTIES`.
- Never clone the canonical operation. Fan-out exists only as immutable `MaterializationIntent` obligations.
- AutoCAD and Revit are both REQUIRED. Runtime availability may fail execution but may never rewrite the required set.
- Runtime Host type tokens use the repository lowercase convention: `autocad`, `revit`.
- Phase I MVP cardinality is exactly `1 semantic_id × 1 required Host slot = 1 native binding`.
- Revit persistent native identity is `Element.UniqueId`; `ElementId` is diagnostic only.
- `MaterializationTopologySnapshot` uses the exact field name `topology_environment_id`. It is a topology namespace identity, not a semantic environment identity.
- Readiness is observation only: no lock, no reservation, no XA/2PC, and no first Host mutation until every REQUIRED materialization is ready.
- Host mutation order is deterministic `autocad -> revit`; no parallel Host mutation.
- `COMMIT_STATE_UNKNOWN` remains materialized coordinator `RECOVERY_REQUIRED`; never fabricate `ActualDelta`, retry an ambiguous mutation, or relabel it `BEFORE_COMMIT`.
- No automatic compensation execution and no inverse native-command inference.
- Saga V2 `DIVERGED` is reachable only after every REQUIRED Slice is locally `SUCCEEDED`; divergence never rewrites local Slice history.
- Convergence consumes canonical post-execution evidence only. No AutoCAD Handle/LWPOLYLINE/ConstantWidth or Revit ElementId/UniqueId/feet/WallType vocabulary may leak into topology, materialization-planning, or convergence core.
- `SET_WALL_THICKNESS_V1.input_schema.properties.thickness.properties.unit.const` is `mm`. The ChangeSet root operation must carry `thickness.unit == "mm"` after canonical contract validation. The verification contract is `SEMANTIC_ASSERTIONS_V1` with `path = properties.dsp:WallThickness`, `operator = EQUALS_ARGUMENT`, `argument = thickness`, and no tolerance field. Phase I therefore uses canonical `mm` exact equality and must not invent tolerance or unit-conversion behavior.
- Step30 V2 resolves each materialization to one document-scoped `ExecutionSliceScopeRule` by exact closed-world matching. No missing rule, duplicate exact rule, wider rule, alternate document, or fallback candidate is admissible.
- Use TDD for every production change: write the failing test, run and observe RED, implement the smallest change, rerun GREEN, then commit.
- All new code comments must be Chinese.
- Never touch, delete, clean, or accidentally commit `docs/project-intro-storyboard.md`, `fixtures/`, or `scripts/`. Never run `git clean`.
- Live wall tests mutate controlled models. Do not save either controlled model after mutation; restore or close/reopen before the next live scenario.

---

## File Structure Map

- `platform/approval_scope`: owns Step28 V2 topology-bound approval integrity; V1 remains authoritative for V1 artifacts.
- `platform/materialization_topology`: owns immutable required-materialization topology snapshots and registry.
- `platform/changeset`: owns Step29 V2 integrity reconstruction against Step28 V2 without changing `CanonicalChangeSet` semantics.
- `platform/convergence`: owns versioned convergence profile, canonical evidence, and exact convergence verification.
- `platform/materialization_planning`: owns deterministic fan-out from one canonical operation to required materialization obligations.
- `platform/execution_planning`: owns Step30 V2 materialization-to-unit/slice projection and exact document-scope resolution.
- `platform/provider_binding`: owns Step31 V2 late binding and exact cross-materialization native identity checks.
- `platform/gateway_authorization`: owns Step32 V2 grants bound to exact materialization lineage.
- `platform/execution_reconciliation`: owns Step33 V2 local reconciliation plus an independent V2 durable Saga state/store path.
- `platform/execution_coordination`: owns readiness and materialized coordination; V1 `CoordinationStatus` remains unchanged.
- `hosts/autocad` and `hosts/revit`: own Host-specific readiness and mutation execution only.

---

### Task 1: Add Step28 V2 definition and boundary with content-addressed topology binding

**Files:**
- Modify: `platform/approval_scope/src/design_approval_scope/contracts.py`
- Modify: `platform/approval_scope/src/design_approval_scope/hashing.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Create: `tests/approval_scope/test_step28_materialization_v2.py`
- Modify: `tests/approval_scope/test_step28_hashing.py`

**Interfaces:**
- Consumes: existing `ApprovalScopeDefinition`, `ApprovalScopeBoundary`, `ExecutionSliceScopeRule`, and a validated lowercase 64-hex `topology_snapshot_hash`.
- Produces: `ApprovalScopeDefinitionV2`, `ApprovalScopeBoundaryV2`.
- Produces: `compute_scope_body_hash_v2(definition: ApprovalScopeDefinition, topology_snapshot_hash: str) -> str`.
- Produces: `bind_topology_snapshot_v2(definition: ApprovalScopeDefinition, topology_snapshot_hash: str) -> ApprovalScopeDefinitionV2`.
- Produces: `bind_changeset_v2(definition: ApprovalScopeDefinitionV2, changeset_hash: str, scope_id: str) -> ApprovalScopeBoundaryV2`.
- Produces: `validate_approval_scope_definition_v2(value: ApprovalScopeDefinitionV2) -> None` and `validate_approval_scope_boundary_v2(value: ApprovalScopeBoundaryV2) -> None`.
- Downstream guarantee: `ApprovalScopeDefinitionV2.scope_definition_id == f"ASD-{scope_body_hash[:12]}"`, where `scope_body_hash` is the V2 body hash, never the V1 body hash.

- [ ] **Step 1: Write RED V1/V2 identity tests**

Create a V1 definition, bind topology hash A and topology hash B, and prove the V2 content-addressed identity changes with topology while V1 stays byte-for-byte stable:

```python
v2_a = bind_topology_snapshot_v2(v1_definition, topology_hash_a)
v2_b = bind_topology_snapshot_v2(v1_definition, topology_hash_b)

assert v2_a.scope_body_hash != v1_definition.scope_body_hash
assert v2_a.scope_body_hash != v2_b.scope_body_hash
assert v2_a.scope_definition_id == f"ASD-{v2_a.scope_body_hash[:12]}"
assert v2_b.scope_definition_id == f"ASD-{v2_b.scope_body_hash[:12]}"
assert v2_a.scope_definition_id != v1_definition.scope_definition_id
```

Also prove V2 construction rejects malformed topology hashes and V1 validators reject V2 objects by type.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/approval_scope/test_step28_materialization_v2.py tests/approval_scope/test_step28_hashing.py -q -vv
```

Expected: V2 imports or V2 identity assertions fail; existing V1 hashing tests remain green.

- [ ] **Step 3: Implement V2 hashing and binding**

`compute_scope_body_hash_v2` must hash a version marker, the complete normalized V1 semantic body, and `topology_snapshot_hash`. `bind_topology_snapshot_v2` must derive the V2 `scope_definition_id` from that new body hash. `bind_changeset_v2` must bind `changeset_hash` to the V2 body and preserve the V2 definition id. Do not alter V1 `compute_scope_body_hash`, `bind_changeset`, or V1 validator behavior.

- [ ] **Step 4: Run GREEN**

```powershell
python -m pytest tests/approval_scope -q -vv
```

- [ ] **Step 5: Commit**

```powershell
git add platform/approval_scope tests/approval_scope
git commit -m "feat: add versioned materialization approval scope"
```

---

### Task 2: Add immutable Materialization Topology contracts and registry

**Files:**
- Create: `platform/materialization_topology/pyproject.toml`
- Create: `platform/materialization_topology/src/design_materialization_topology/__init__.py`
- Create: `platform/materialization_topology/src/design_materialization_topology/contracts.py`
- Create: `platform/materialization_topology/src/design_materialization_topology/hashing.py`
- Create: `platform/materialization_topology/src/design_materialization_topology/registry.py`
- Create: `tests/materialization_topology/test_contracts.py`
- Create: `tests/materialization_topology/test_hashing.py`
- Create: `tests/materialization_topology/test_registry.py`

**Interfaces:**
- Consumes: provider-neutral `semantic_target_ref`, lowercase required Host type, stable `document_ref`, and caller-supplied `topology_environment_id` plus non-negative `topology_revision`.
- Produces: `MaterializationRequirement.REQUIRED`, `MaterializationSlot`, `MaterializationTopologySnapshot`.
- `MaterializationTopologySnapshot` fields are exactly `topology_environment_id`, `topology_revision`, `slots`, `topology_snapshot_hash`.
- Produces: `compute_topology_snapshot_hash(snapshot_without_hash: MaterializationTopologySnapshot) -> str` through the package hashing implementation.
- Produces: `validate_materialization_topology_snapshot(snapshot: MaterializationTopologySnapshot) -> None`.
- Produces registry methods `register(snapshot: MaterializationTopologySnapshot) -> None` and `get(topology_environment_id: str, topology_revision: int) -> MaterializationTopologySnapshot`.
- Downstream guarantee: `host_instance_id` is absent from the topology contract and availability never changes `slots`.

- [ ] **Step 1: Write RED contract/hash tests**

Use this exact semantic shape:

```text
MaterializationTopologySnapshot
  topology_environment_id
  topology_revision
  slots
  topology_snapshot_hash

MaterializationSlot
  materialization_slot_id
  semantic_target_ref
  required_host_type
  document_ref
  requirement
```

Prove: only REQUIRED is accepted; blank fields and negative revision fail; duplicate `(semantic_target_ref, required_host_type, document_ref)` fails; slot order is hash-insensitive; semantic target, Host type, document, requirement, environment, or revision changes the hash.

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\materialization_topology\src"
python -m pytest tests/materialization_topology -q -vv
```

- [ ] **Step 3: Implement deterministic hashing and registry semantics**

Canonical slot order is semantic target, Host type, document, slot id. Identical registration of the same `(topology_environment_id, topology_revision)` and same hash is idempotent; conflicting content under the same key raises `MATERIALIZATION_TOPOLOGY_MISMATCH`. Registry never queries Host health or availability.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/materialization_topology -q -vv
git add platform/materialization_topology tests/materialization_topology
git commit -m "feat: add immutable materialization topology"
```

---

### Task 3: Teach Step29 integrity validation about V2 scope without changing ChangeSet semantics

**Files:**
- Create: `platform/changeset/src/design_changeset/integrity_v2.py`
- Modify: `platform/changeset/src/design_changeset/__init__.py`
- Create: `tests/changeset/test_step29_materialization_scope_v2.py`
- Modify: `tests/changeset/test_step29_integrity.py`

**Interfaces:**
- Consumes: existing `CanonicalChangeSet` and `ApprovalScopeBoundaryV2`.
- Produces: `validate_changeset_integrity_v2(changeset: CanonicalChangeSet, approval_scope_boundary: ApprovalScopeBoundaryV2) -> None`.
- Reuses: existing Step29 `compute_changeset_hash`, operation semantic hash reconstruction, and scope-rule fingerprint logic.
- Downstream guarantee: V2 validation reconstructs the same `CanonicalChangeSet` semantic body but joins it to the V2 `scope_body_hash`; no second ChangeSet hash algorithm exists.

- [ ] **Step 1: Write RED V2 structural/integrity tests**

Build a normal wall-thickness ChangeSet from a topology-bound Step28 V2 definition and assert:

```python
assert changeset.approval_scope_definition_ref.scope_body_hash == scope_v2.scope_body_hash
validate_changeset_integrity_v2(changeset, boundary_v2)
```

Tampering only the topology-bound scope body must fail integrity.

- [ ] **Step 2: Add RED V1 compatibility tests**

Prove `validate_changeset_integrity` still accepts historical V1 artifacts and rejects V2 boundary objects by type. Prove `validate_changeset_integrity_v2` accepts only V2 boundaries and does not change `CanonicalChangeSet`, `compute_changeset_hash`, or V1 outputs.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\approval_scope\src;$PWD\platform\changeset\src"
python -m pytest tests/changeset/test_step29_materialization_scope_v2.py tests/changeset/test_step29_integrity.py -q -vv
```

- [ ] **Step 4: Implement the V2 owner-side reconstruction**

Reuse the existing Step29 semantic body construction and rule lookup, substituting only the validated V2 boundary type/body hash. Do not reimplement canonical operation hashing or scope-rule fingerprints.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/changeset -q -vv
git add platform/changeset tests/changeset
git commit -m "feat: validate changesets against materialization scope v2"
```

---

### Task 4: Add exact canonical convergence-profile construction

**Files:**
- Create: `platform/convergence/pyproject.toml`
- Create: `platform/convergence/src/design_convergence/__init__.py`
- Create: `platform/convergence/src/design_convergence/profile.py`
- Create: `platform/convergence/src/design_convergence/hashing.py`
- Create: `tests/convergence/test_profile.py`
- Create: `tests/convergence/test_profile_hashing.py`

**Interfaces:**
- Consumes: integrity-validated `CanonicalChangeSet`, its exact `ApprovalScopeBoundaryV2`, and the canonical `CanonicalOperationDefinition` that matches the ChangeSet root operation.
- Produces: `ConvergenceComparisonMode.EXACT_CANONICAL_VALUE`.
- Produces: `ConvergenceFieldRule(subjects_from_argument: str, path: str, expected_argument: str, measurement_unit: str, comparison_mode: ConvergenceComparisonMode)`.
- Produces: `ConvergenceComparisonProfile(profile_version: str, field_rules: tuple, profile_hash: str)`.
- Produces request fields: `canonical_changeset: CanonicalChangeSet`, `approval_scope_boundary: ApprovalScopeBoundaryV2`, `canonical_operation_definition: CanonicalOperationDefinition` in `ConvergenceProfileBuildRequest`.
- Produces: `build_convergence_profile(request: ConvergenceProfileBuildRequest) -> ConvergenceComparisonProfile`.
- Downstream guarantee: for Phase I wall thickness, `measurement_unit == "mm"`, comparison mode is exact, and the profile contains no tolerance field.

- [ ] **Step 1: Write RED exact wall-contract tests**

Use the real `SET_WALL_THICKNESS_V1`. First validate the ChangeSet against Step28 V2. Require all three facts to agree:

```python
assert changeset.root_operation.arguments["thickness"]["unit"] == "mm"
assert definition.input_schema["properties"]["thickness"]["properties"]["unit"]["const"] == "mm"
assert "tolerance" not in definition.verification_contract
```

Then assert one profile rule with `subjects_from_argument = targets`, `path = properties.dsp:WallThickness`, `expected_argument = thickness`, `measurement_unit = mm`, and `comparison_mode = EXACT_CANONICAL_VALUE`.

- [ ] **Step 2: Add RED fail-closed tests**

Reject mismatched canonical operation identity/version, a ChangeSet whose `thickness.unit` disagrees with the canonical definition const, verification contracts other than `SEMANTIC_ASSERTIONS_V1/EQUALS_ARGUMENT`, and any contract that would require implicit unit conversion or undeclared tolerance. Use `CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH` for operation/unit mismatch and `CONVERGENCE_PROFILE_UNSUPPORTED` for unsupported verification shapes.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\convergence\src;$PWD\platform\changeset\src;$PWD\platform\approval_scope\src;$PWD\platform\orchestrator\src"
python -m pytest tests/convergence/test_profile.py tests/convergence/test_profile_hashing.py -q -vv
```

- [ ] **Step 4: Implement content-addressed exact profile construction**

Call `validate_changeset_integrity_v2` before reading root-operation arguments. Read the canonical unit from the validated ChangeSet and require it to equal the canonical definition schema const. Project only supported verification assertions into deterministic profile rules. Hash profile version plus normalized rules. Do not add tolerance or conversion branches.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/convergence/test_profile.py tests/convergence/test_profile_hashing.py -q -vv
git add platform/convergence tests/convergence
git commit -m "feat: add exact convergence comparison profiles"
```

---

### Task 5: Add deterministic Materialization Planning

**Files:**
- Create: `platform/materialization_planning/pyproject.toml`
- Create: `platform/materialization_planning/src/design_materialization_planning/__init__.py`
- Create: `platform/materialization_planning/src/design_materialization_planning/contracts.py`
- Create: `platform/materialization_planning/src/design_materialization_planning/hashing.py`
- Create: `platform/materialization_planning/src/design_materialization_planning/planner.py`
- Create: `tests/materialization_planning/conftest.py`
- Create: `tests/materialization_planning/test_planner.py`
- Create: `tests/materialization_planning/test_hashing.py`
- Create: `tests/materialization_planning/test_required_set.py`

**Interfaces:**
- Consumes: `CanonicalChangeSet`, `ApprovalScopeBoundaryV2`, `MaterializationTopologySnapshot`, `ConvergenceComparisonProfile`.
- Produces: `MaterializationIntent` with `materialization_id`, `source_operation_id`, `source_operation_hash`, `semantic_targets`, `materialization_slot_id`, `required_host_type`, `expected_effects`, `intent_hash`.
- Produces: `MaterializationPlan` with `changeset_hash`, `approved_scope_hash`, `topology_snapshot_hash`, `intents`, `required_set_hash`, `convergence_profile_hash`, `materialization_plan_hash`.
- Produces request fields: `canonical_changeset: CanonicalChangeSet`, `approval_scope_boundary: ApprovalScopeBoundaryV2`, `topology_snapshot: MaterializationTopologySnapshot`, `convergence_profile: ConvergenceComparisonProfile` in `MaterializationPlanningRequest`.
- Produces: `MaterializationPlanner.plan(request: MaterializationPlanningRequest) -> MaterializationPlan`.
- Downstream guarantee: one wall semantic operation plus AutoCAD/Revit REQUIRED slots yields exactly two immutable intents; availability is not an input.

- [ ] **Step 1: Write RED happy-path tests**

One `set_wall_thickness.v1` operation on `WALL-001` with two REQUIRED topology slots must yield exactly two intents sharing the same source operation id/hash and differing by `materialization_slot_id`/required Host.

- [ ] **Step 2: Add RED fail-closed matrix**

Reject V1 boundary; topology hash mismatch; topology target absent from ChangeSet; missing/duplicate required slot; extra materialization; unsupported cardinality with `UNSUPPORTED_MATERIALIZATION_CARDINALITY`; and profile hash substitution. Prove availability cannot shrink the required set.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\materialization_topology\src;$PWD\platform\materialization_planning\src;$PWD\platform\convergence\src"
python -m pytest tests/materialization_planning -q -vv
```

- [ ] **Step 4: Implement planner and deterministic hashes**

Validate Step28 V2, Step29 V2, topology, and convergence profile lineage first. Generate one intent per matching REQUIRED slot and compute a required-set hash from sorted required materialization identities. Compute the plan hash from exact ChangeSet/scope/topology/profile/intent/required-set lineage.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/materialization_planning tests/approval_scope tests/changeset -q -vv
git add platform/materialization_planning tests/materialization_planning
git commit -m "feat: add deterministic materialization planning"
```

---

### Task 6: Add Step30 V2 execution planning with exact document-scope resolution

**Files:**
- Create: `platform/execution_planning/src/design_execution_planning/v2.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Modify: `platform/execution_planning/pyproject.toml`
- Create: `tests/execution_planning/test_step30_materialization_v2.py`
- Create: `tests/execution_planning/test_step30_materialization_v2_hashing.py`
- Create: `tests/execution_planning/test_step30_materialization_v2_routing.py`
- Create: `tests/execution_planning/test_step30_materialization_v2_scope_resolution.py`
- Modify: `tests/execution_planning/test_step30_architecture.py`

**Interfaces:**
- Consumes: `CanonicalChangeSet`, `ApprovalScopeBoundaryV2`, `MaterializationPlan`, the exact `MaterializationTopologySnapshot` named by `materialization_plan.topology_snapshot_hash`, and `MaterializationRoutingEvidence`.
- Produces: `MaterializationRuntimeRoute`, `MaterializationRoutingEvidence`, `ExecutionUnitV2`, `ExecutionSliceV2`, `ExecutionPlanV2`.
- Produces request fields: `canonical_changeset: CanonicalChangeSet`, `approval_scope_boundary: ApprovalScopeBoundaryV2`, `materialization_plan: MaterializationPlan`, `topology_snapshot: MaterializationTopologySnapshot`, `runtime_routing_evidence: MaterializationRoutingEvidence` in `ExecutionPlanningRequestV2`.
- Produces: `plan_materialized_execution(request: ExecutionPlanningRequestV2) -> ExecutionPlanV2`.
- Produces: `validate_execution_plan_v2(plan: ExecutionPlanV2, topology_snapshot: MaterializationTopologySnapshot, boundary: ApprovalScopeBoundaryV2) -> None`.
- Downstream guarantee: `1 MaterializationIntent = 1 ExecutionUnitV2`; each Slice binds one exact materialization, one runtime route, one document, and one exact `ExecutionSliceScopeRule`.

- [ ] **Step 1: Write RED V2 routing/lineage tests**

Every Unit/Slice must bind `materialization_id` and `materialization_plan_hash`; the plan binds `required_set_hash` and ordering policy `stable_host_type_then_slot.v1`. Route by materialization id, never by bare semantic id.

- [ ] **Step 2: Write RED closed-world document-scope tests**

For each intent:

1. Resolve `materialization_slot_id` against the bound topology snapshot; exactly one slot must exist.
2. Treat that slot's `document_ref` as authoritative.
3. Require `HostRuntimeRef.document_ref == slot.document_ref` and `HostRuntimeRef.host_type == slot.required_host_type`.
4. Compute the operation's exact required Step28 scope-rule id sets.
5. Candidate `ExecutionSliceScopeRule` values must have exactly the same `document_ref` and exactly the same required existing/creation/deletion rule ids, with no missing or surplus authority.
6. Zero candidates fails `EXECUTION_SCOPE_UNCOVERED`.
7. More than one exact candidate fails `EXECUTION_SCOPE_AMBIGUOUS`.
8. Never fall back to another document, the V1 narrowest-superset behavior, or a wider rule.

The wall acceptance test must prove AutoCAD and Revit materializations resolve to their own document-scoped rules.

- [ ] **Step 3: Freeze deterministic ordering**

```python
assert tuple(item.host_runtime_ref.host_type for item in plan.execution_slices) == (
    "autocad",
    "revit",
)
```

- [ ] **Step 4: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\materialization_topology\src;$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src"
python -m pytest tests/execution_planning/test_step30_materialization_v2.py tests/execution_planning/test_step30_materialization_v2_hashing.py tests/execution_planning/test_step30_materialization_v2_routing.py tests/execution_planning/test_step30_materialization_v2_scope_resolution.py -q -vv
```

- [ ] **Step 5: Implement V2 planner/integrity**

Validate topology/plan/scope lineage before routing. Project each intent to one Unit and one Phase-I Slice. Store the selected exact `execution_slice_scope_rule_id` in the V2 approved-scope reference. V1 planner and V1 hash functions stay unchanged.

- [ ] **Step 6: Run GREEN and commit**

```powershell
python -m pytest tests/execution_planning -q -vv
git add platform/execution_planning tests/execution_planning
git commit -m "feat: add materialization-aware execution planning v2"
```

---

### Task 7: Add Step31 V2 provider/native binding with exact materialization lineage

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/v2.py`
- Modify: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Modify: `platform/provider_binding/pyproject.toml`
- Create: `tests/provider_binding/test_step31_materialization_v2.py`
- Create: `tests/provider_binding/test_step31_cross_materialization_identity.py`
- Modify: `tests/provider_binding/test_step31_architecture.py`

**Interfaces:**
- Consumes: `ExecutionSliceV2`, `MaterializationPlan`, exact `MaterializationSlot`, existing `NativeTargetBindingEvidence`, provider candidates, and runtime evidence.
- Produces: `ProviderExecutionSnapshotV2`, `ProviderBindingV2`, `ProviderBindingSetV2`.
- Produces: `resolve_provider_bindings_v2(execution_slice: ExecutionSliceV2, snapshot: ProviderExecutionSnapshotV2) -> ProviderBindingSetV2`.
- Produces: `validate_provider_binding_set_v2(binding_set: ProviderBindingSetV2, execution_slice: ExecutionSliceV2) -> None`.
- Produces: `validate_cross_materialization_identity(plan: MaterializationPlan, binding_sets: Sequence[ProviderBindingSetV2]) -> None`.
- Reuses: existing `NativeTargetBindingEvidence` and `compute_host_binding_fingerprint` unchanged.

- [ ] **Step 1: Write RED V2 lineage tests**

Require snapshot/binding hashes to include materialization id, materialization plan hash, V2 Slice hash, binding-set hash, Host runtime ref, and exact native target evidence. Never convert a V2 Slice into a fake V1 Slice/hash.

- [ ] **Step 2: Write RED identity/cardinality tests**

Reject missing target with `IDENTITY_BINDING_UNRESOLVED`; duplicate/conflicting native target with `IDENTITY_BINDING_CONFLICT`; semantic-id/Host/document/materialization mismatch with `MATERIALIZATION_BINDING_MISMATCH`; extra materialization; and changed Revit `UniqueId` under an old binding hash.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\approval_scope\src;$PWD\platform\changeset\src"
python -m pytest tests/provider_binding/test_step31_materialization_v2.py tests/provider_binding/test_step31_cross_materialization_identity.py -q -vv
```

- [ ] **Step 4: Implement V2 binding over shared provider-neutral candidate selection**

Extract only deterministic filtering/ranking/adaptation helpers needed by both V1 and V2. V1 public output and hashes must remain byte-for-byte compatible. V2 binding cannot add/remove intents, repartition execution, or widen scope.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/provider_binding -q -vv
git add platform/provider_binding tests/provider_binding
git commit -m "feat: bind providers to exact materializations"
```

---

### Task 8: Add Step32 V2 approval consumption and materialization-aware grants

**Files:**
- Create: `platform/gateway_authorization/src/design_gateway_authorization/v2.py`
- Create: `platform/gateway_authorization/src/design_gateway_authorization/store_v2.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Modify: `platform/gateway_authorization/pyproject.toml`
- Create: `tests/gateway_authorization/test_step32_materialization_approval.py`
- Create: `tests/gateway_authorization/test_step32_materialization_grants.py`
- Create: `tests/gateway_authorization/test_step32_materialization_authority.py`
- Modify: `tests/gateway_authorization/test_step32_architecture.py`

**Interfaces:**
- Consumes approval side: existing `ApprovalAdmission`, `CanonicalChangeSet`, exact `ApprovalScopeBoundaryV2`, and consumption time.
- Consumes grant side: authoritative stored `ApprovalRecord`, exact `ExecutionSliceV2`, exact `ProviderBindingSetV2`, exact `MaterializationPlan`, and issuance/admission times.
- Produces: `ApprovalConsumptionRequestV2`, `ExecutionGrantRequestV2`, `ExecutionGrantV2`, `AdmittedExecutionAuthorityV2`.
- Produces: `GatewayAuthorizationServiceV2.consume_approval(request: ApprovalConsumptionRequestV2) -> ApprovalRecord`.
- Produces: `GatewayAuthorizationServiceV2.issue_execution_grant(request: ExecutionGrantRequestV2) -> ExecutionGrantV2`.
- Produces: `GatewayAuthorizationServiceV2.admit_execution_grant(grant_hash: str, admitted_at: str) -> AdmittedExecutionAuthorityV2`.
- Produces a V2 store path whose grant lineage key binds approval hash plus V2 Slice/materialization lineage; V1 store/service remain unchanged.

- [ ] **Step 1: Write RED V2 approval-consumption tests**

Require exact join of admission `changeset_hash`, boundary `changeset_hash`, V2 `scope_hash`, and Step29 V2 integrity. Persist the existing `ApprovalRecord` shape only because its approved scope hash already identifies the V2 approval boundary. V1 service must continue rejecting V2 boundary objects.

- [ ] **Step 2: Write RED V2 grant/authority tests**

`ExecutionGrantV2` must bind at minimum `approval_id`, `approval_hash`, `changeset_hash`, `approved_scope_hash`, `materialization_plan_hash`, `materialization_id`, `execution_slice_id`, `execution_slice_hash`, `binding_set_hash`, `host_instance_id`, allowed operations, issue/expiry times, and grant hash. `AdmittedExecutionAuthorityV2` must preserve the same materialization lineage. Substitution of materialization, plan, binding, Slice, or Host fails `MATERIALIZATION_AUTHORITY_MISMATCH`.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src"
python -m pytest tests/gateway_authorization/test_step32_materialization_approval.py tests/gateway_authorization/test_step32_materialization_grants.py tests/gateway_authorization/test_step32_materialization_authority.py -q -vv
```

- [ ] **Step 4: Implement V2 authorization using owner validators**

Call `validate_approval_scope_boundary_v2`, `validate_changeset_integrity_v2`, `validate_execution_plan_v2`, and `validate_provider_binding_set_v2`; do not copy any owner hash algorithm. V2 grant hash includes exact materialization lineage. Preserve existing approval one-time consumption and grant idempotency semantics.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/gateway_authorization -q -vv
git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat: authorize exact materialization executions"
```

---

### Task 9: Add provider-neutral all-required readiness barrier without changing V1 coordination status

**Files:**
- Create: `platform/execution_coordination/src/design_execution_coordination/readiness_contracts.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/readiness.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Modify: `platform/execution_coordination/pyproject.toml`
- Create: `tests/execution_coordination/test_phase_i_readiness_contracts.py`
- Create: `tests/execution_coordination/test_phase_i_readiness_barrier.py`
- Create: `tests/execution_coordination/test_phase_i_v1_coordination_compatibility.py`

**Interfaces:**
- Consumes: `MaterializationPlan`, `ExecutionPlanV2`, one exact `ProviderBindingSetV2` and `AdmittedExecutionAuthorityV2` per required materialization, plus `HostReadinessRegistry`.
- Produces: `ReadinessStatus` with `READY` and `NOT_READY` only.
- Produces: `HostReadinessReceipt` binding materialization id/plan hash, Slice hash, binding-set hash, grant hash, runtime/document, observed revision, status, failure code, and receipt hash.
- Produces: `ReadinessBarrierStatus` with `READY` and `NOT_READY`.
- Produces: `ReadinessBarrierResult(status: ReadinessBarrierStatus, receipts: Sequence[HostReadinessReceipt], failure_ref: str | None)`.
- Produces: `HostReadinessPort.check(execution_slice: ExecutionSliceV2, authority: AdmittedExecutionAuthorityV2, binding_set: ProviderBindingSetV2) -> HostReadinessReceipt`.
- Produces: `HostReadinessRegistry.resolve(runtime_ref: HostRuntimeRef) -> HostReadinessPort`.
- Produces: `CrossHostReadinessBarrier.check_all(plan: MaterializationPlan, execution_plan: ExecutionPlanV2, binding_sets: Sequence[ProviderBindingSetV2], authorities: Sequence[AdmittedExecutionAuthorityV2]) -> ReadinessBarrierResult`.
- Downstream guarantee: readiness never returns a V1 `CoordinationResult` and never changes V1 `CoordinationStatus`.

- [ ] **Step 1: Write RED receipt/port tests**

Require one exact receipt per required materialization. Receipt lineage must match plan, Slice, binding, grant, Host type, host instance, and document. Any mismatch raises `READINESS_LINEAGE_MISMATCH`.

- [ ] **Step 2: Write RED barrier tests**

Any NOT_READY produces `ReadinessBarrierStatus.NOT_READY`; missing/extra receipts or authority/binding mismatch fail closed. Prove zero Host execution calls and zero Step33 Saga creation/admission occur before a READY barrier result.

- [ ] **Step 3: Write V1 compatibility RED guard**

Assert the exact existing V1 enum remains:

```python
assert tuple(item.value for item in CoordinationStatus) == (
    "SUCCEEDED",
    "FAILED",
    "PARTIALLY_COMMITTED",
    "RECOVERY_REQUIRED",
)
```

- [ ] **Step 4: Run RED, implement, run GREEN**

```powershell
$env:PYTHONPATH = "$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src;$PWD\platform\execution_coordination\src"
python -m pytest tests/execution_coordination/test_phase_i_readiness_contracts.py tests/execution_coordination/test_phase_i_readiness_barrier.py tests/execution_coordination/test_phase_i_v1_coordination_compatibility.py -q -vv
python -m pytest tests/execution_coordination -q -vv
```

- [ ] **Step 5: Commit**

```powershell
git add platform/execution_coordination tests/execution_coordination
git commit -m "feat: add all-required cross-host readiness barrier"
```

---

### Task 10: Implement AutoCAD read-only wall-thickness readiness adapter

**Files:**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/execution/readiness.py`
- Create: `tests/integration/test_phase_i_autocad_readiness_adapter.py`

**Interfaces:**
- Consumes: exact `ExecutionSliceV2`, `AdmittedExecutionAuthorityV2`, `ProviderBindingSetV2`, and existing AutoCAD `CommandDispatcher`.
- Produces: `AutoCadWallThicknessReadinessPort.check(execution_slice: ExecutionSliceV2, authority: AdmittedExecutionAuthorityV2, binding_set: ProviderBindingSetV2) -> HostReadinessReceipt`.
- Uses only: `CommandDispatcher.extract_design_facts([native_id])` and existing normalized read path.
- Downstream guarantee: no mutation, retry, or idempotency-completion API is called by readiness.

- [ ] **Step 1: Write RED adapter tests**

Required proof: exact Host/document/native id; exactly one target; `native_kind == "LWPOLYLINE"`; `autocad.property/LWPOLYLINE.ConstantWidth` exists; width unit is `mm`; target facts share one non-negative `source_revision`; current width is positive.

- [ ] **Step 2: Prove no mutation/retry occurs**

A fake dispatcher must raise if `set_wall_thickness`, mutation retry, or idempotency completion is invoked. Successful readiness must still return READY with the observed revision.

- [ ] **Step 3: Run RED, implement, run GREEN**

```powershell
$env:PYTHONPATH = "$PWD\contracts\python;$PWD\hosts\autocad\sidecar\src;$PWD\platform\execution_coordination\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src;$PWD\platform\materialization_planning\src"
python -m pytest tests/integration/test_phase_i_autocad_readiness_adapter.py -q -vv
python -m pytest tests/integration/test_phase_i_autocad_readiness_adapter.py tests/integration/test_step34_autocad_wall_thickness_reconciliation.py -q -vv
```

- [ ] **Step 4: Commit**

```powershell
git add hosts/autocad/sidecar/src/autocad_sidecar/execution/readiness.py tests/integration/test_phase_i_autocad_readiness_adapter.py
git commit -m "feat: add read-only autocad wall readiness"
```

---

### Task 11: Implement Revit read-only wall-thickness readiness and exact native routing

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessReadiness.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestExecutorRouter.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Native/PluginEntry.cs`
- Create: `hosts/revit/sidecar/src/revit_sidecar/readiness.py`
- Create: `hosts/revit/sidecar/tests/test_readiness.py`
- Modify: `tests/revit/test_revit_architecture.py`

**Interfaces:**
- Consumes: exact V2 Slice/authority/binding lineage and the existing Revit named-pipe HostCommand path.
- Produces sidecar: `RevitWallThicknessReadinessPort.check(execution_slice: ExecutionSliceV2, authority: AdmittedExecutionAuthorityV2, binding_set: ProviderBindingSetV2) -> HostReadinessReceipt`.
- Produces native operation: `READ/check_wall_thickness_readiness`.
- Produces router mapping `READ/check_wall_thickness_readiness` to `RevitWallThicknessReadiness` and `EXECUTE/set_wall_thickness` to `RevitWallThicknessMutation`.
- Reuses: `RevitWallTargetResolver`, `RevitWallIsolationProbe`, `RevitWallThicknessPlanBuilder`, `RevitWallSnapshotReader`, and `Element.UniqueId`.

- [ ] **Step 1: Write RED sidecar tests**

The sidecar builds one READ HostCommand, exchanges it through `named_pipe.py`, validates returned document/UniqueId/revision/current width, and emits an exact V2 readiness receipt.

- [ ] **Step 2: Write RED native architecture tests**

Require readiness to use the existing target/isolation/plan/snapshot readers; never construct `Transaction`; never duplicate/reassign WallType. Require the new router to implement `IRevitRequestExecutor`; `RevitExternalEventHandler.cs` remains the sole ExternalEvent execution boundary.

- [ ] **Step 3: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\contracts\python;$PWD\hosts\revit\sidecar\src;$PWD\platform\execution_coordination\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src;$PWD\platform\materialization_planning\src"
python -m pytest hosts/revit/sidecar/tests/test_readiness.py tests/revit/test_revit_architecture.py -q -vv
```

- [ ] **Step 4: Implement native readiness**

Readiness validates the same pre-transaction support conditions as mutation: target UniqueId resolution; supported Basic Wall; exclusive WallType; no inserts; no actual joins; associativity proof; vertically homogeneous structure; one editable non-membrane layer; requested width is plannable. It returns observed revision/current width/UniqueId and opens no transaction.

- [ ] **Step 5: Run Python/Core/native GREEN gates**

```powershell
python -m pytest hosts/revit/sidecar/tests/test_readiness.py tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj

cd C:\
dotnet build E:\DAPS\enterprise-design-agent\hosts\revit\plugin\Revit.AgentHost\Revit.AgentHost.csproj `
  -p:DspRevitVersion="2027" `
  -p:DspRevitTargetFramework="net10.0-windows" `
  -p:DspRevitApiDir="C:\Program Files\Autodesk\Revit 2027"
```

Expected native build: 0 errors; the three already-accepted Revit dependency-graph `MSB3277` warnings may remain and must not be suppressed.

- [ ] **Step 6: Commit**

```powershell
git add hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessReadiness.cs hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestExecutorRouter.cs hosts/revit/plugin/Revit.AgentHost/Native/PluginEntry.cs hosts/revit/sidecar/src/revit_sidecar/readiness.py hosts/revit/sidecar/tests/test_readiness.py tests/revit/test_revit_architecture.py
git commit -m "feat: add read-only revit wall readiness"
```

---

### Task 12: Add Step33 V2 local reconciliation with a separate durable Saga V2 store

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/v2.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_contracts_v2.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_state_v2.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_store_v2.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_v2.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/verifier.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Modify: `platform/execution_reconciliation/pyproject.toml`
- Create: `tests/execution_reconciliation/test_step33_v2_local_reconciliation.py`
- Create: `tests/execution_reconciliation/test_saga_v2_definition.py`
- Create: `tests/execution_reconciliation/test_saga_v2_store.py`
- Create: `tests/execution_reconciliation/test_saga_v2_diverged.py`
- Create: `tests/execution_reconciliation/test_saga_v2_compatibility.py`

**Interfaces:**
- Consumes local reconciliation: `CanonicalChangeSet`, `ApprovalScopeBoundaryV2`, `ExecutionSliceV2`, `AdmittedExecutionAuthorityV2`, existing provider-neutral `ActualDelta`, `ScopeComparisonResult`, `VerificationEvidenceBundle`, and `SemanticVerificationResult`.
- Produces: `ExecutionReconciliationServiceV2` using V2 lineage validation while reusing existing Slice comparison/verification semantics.
- Produces: `ExecutionSagaDefinitionV2` binding ChangeSet, approved scope, semantic environment, materialization plan hash, required-set hash, execution-plan hash, ordered Slice hashes, dependencies, validation assignments, and definition hash.
- Produces exact `ExecutionSagaStatusV2` values: `READY`, `EXECUTING`, `PARTIALLY_COMMITTED`, `CONVERGENCE_PENDING`, `SUCCEEDED`, `DIVERGED`, `FAILED`.
- Produces exact `SagaConvergenceOutcome` values: `CONVERGED`, `DIVERGED`.
- Produces: `StoredExecutionSagaV2`, `ExecutionSagaStoreV2`, `InMemoryExecutionSagaStoreV2`, `ExecutionSagaControllerV2`.
- Produces store method `create_saga(definition: ExecutionSagaDefinitionV2) -> StoredExecutionSagaV2`.
- Produces store method `get_saga(saga_id: str) -> StoredExecutionSagaV2 | None`.
- Produces store method `reserve_slice_admission(saga_id: str, execution_slice_hash: str, expected_revision: int, reserved_at: str) -> StoredExecutionSagaV2`.
- Produces store method `confirm_slice_admitted(saga_id: str, authority: AdmittedExecutionAuthorityV2, expected_revision: int) -> StoredExecutionSagaV2`.
- Produces store method `record_host_commit(saga_id: str, actual_delta: ActualDelta, expected_revision: int, committed_at: str) -> StoredExecutionSagaV2`.
- Produces store method `begin_reconciliation(saga_id: str, execution_slice_hash: str, expected_revision: int) -> StoredExecutionSagaV2`.
- Produces store method `record_scope_result(saga_id: str, result: ScopeComparisonResult, expected_revision: int) -> StoredExecutionSagaV2`.
- Produces store method `record_verification_result(saga_id: str, result: SemanticVerificationResult, expected_revision: int, reconciled_at: str) -> StoredExecutionSagaV2`.
- Produces store method `record_convergence_outcome(saga_id: str, outcome: SagaConvergenceOutcome, convergence_result_hash: str, expected_revision: int) -> StoredExecutionSagaV2`.
- Downstream guarantee: V1 `ExecutionSagaDefinition`, V1 `ExecutionSagaStatus`, V1 `StoredExecutionSaga`, `ExecutionSagaStore`, and `InMemoryExecutionSagaStore` remain untouched and continue accepting only V1 authority/definition types.

- [ ] **Step 1: Write RED V2 local-reconciliation tests**

Require exact V2 ChangeSet/scope/materialization/Slice/grant/binding lineage. Reuse existing ActualDelta, scope comparison, verification evidence, and semantic verification truth; only lineage contracts change.

- [ ] **Step 2: Write RED V2 definition/state tests**

All REQUIRED local Slices successful must transition the Saga to `CONVERGENCE_PENDING`, not `SUCCEEDED`. From `CONVERGENCE_PENDING`, `SagaConvergenceOutcome.CONVERGED` produces `SUCCEEDED` and `SagaConvergenceOutcome.DIVERGED` produces `DIVERGED`. `DIVERGED` must be impossible while any required Slice is not locally SUCCEEDED.

- [ ] **Step 3: Write RED V2 store-isolation tests**

Instantiate the existing V1 `InMemoryExecutionSagaStore` and the new `InMemoryExecutionSagaStoreV2` side by side. Prove V1 store rejects `ExecutionSagaDefinitionV2`, V2 store rejects V1 `ExecutionSagaDefinition`, and each store maintains independent CAS revisions. Prove V2 authority admission accepts only `AdmittedExecutionAuthorityV2` and verifies materialization/plan lineage before persisting it.

- [ ] **Step 4: Run RED**

```powershell
$env:PYTHONPATH = "$PWD\platform\execution_reconciliation\src;$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\gateway_authorization\src;$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\semantic_runtime\src"
python -m pytest tests/execution_reconciliation/test_step33_v2_local_reconciliation.py tests/execution_reconciliation/test_saga_v2_definition.py tests/execution_reconciliation/test_saga_v2_store.py tests/execution_reconciliation/test_saga_v2_diverged.py tests/execution_reconciliation/test_saga_v2_compatibility.py -q -vv
```

- [ ] **Step 5: Refactor only provider-neutral evaluator logic for V1/V2 reuse**

Keep existing V1 public functions and validation order. Extract only scope/semantic evaluation that occurs after lineage validation. Do not make the V1 store generic and do not widen V1 types to unions.

- [ ] **Step 6: Implement V2 contracts, store, controller, and transitions**

Mirror the proven V1 CAS/evidence-replay discipline in the separate V2 store, but persist V2 definition/authority lineage. Successful predecessor plus later pre-commit failure remains `PARTIALLY_COMMITTED`; commit uncertainty is surfaced to coordination as `RECOVERY_REQUIRED`; no compensation execution is added.

- [ ] **Step 7: Run GREEN and commit**

```powershell
python -m pytest tests/execution_reconciliation -q -vv
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat: add materialized saga v2 reconciliation"
```

---

### Task 13: Implement provider-neutral exact convergence evidence and verifier

**Files:**
- Create: `platform/convergence/src/design_convergence/contracts.py`
- Create: `platform/convergence/src/design_convergence/evidence.py`
- Create: `platform/convergence/src/design_convergence/verifier.py`
- Modify: `platform/convergence/src/design_convergence/hashing.py`
- Modify: `platform/convergence/src/design_convergence/__init__.py`
- Create: `tests/convergence/test_evidence.py`
- Create: `tests/convergence/test_verifier.py`
- Create: `tests/convergence/test_architecture.py`

**Interfaces:**
- Consumes: `MaterializationPlan`, `ConvergenceComparisonProfile`, one canonical post-execution evidence item per required materialization, and the same semantic environment/verification evidence already accepted by local Step33 V2 verification.
- Produces: `MaterializationCanonicalEvidence`, `ConvergenceEvidenceSet`, `ConvergenceResult`.
- Produces statuses: `CONVERGED`, `DIVERGED`, `EVIDENCE_INSUFFICIENT`.
- Produces: `CrossHostConvergenceVerifier.verify(plan: MaterializationPlan, profile: ConvergenceComparisonProfile, evidence_set: ConvergenceEvidenceSet) -> ConvergenceResult`.
- Downstream guarantee: verifier compares only profile-required canonical fields in canonical `mm` using exact equality; no tolerance, native Host value, or native unit enters the comparison.

- [ ] **Step 1: Write RED evidence contracts**

Every item binds materialization id, semantic id, Slice hash, ActualDelta hash, verification hash, semantic environment, post-execution projection, canonical kind, required verified fields, and evidence hash. Evidence set must cover exactly the immutable required set.

- [ ] **Step 2: Write RED exact verifier cases**

For the actual wall profile, `{value: 300, unit: mm}` vs `{value: 300, unit: mm}` is CONVERGED; `300 mm` vs `305 mm` is DIVERGED. Cross-unit evidence is EVIDENCE_INSUFFICIENT because Phase I has no conversion contract. Missing/duplicate evidence and plan/profile/required-set/semantic/environment mismatch fail closed. No synthetic tolerance case is added.

- [ ] **Step 3: Add architecture guards**

Production `platform/convergence` must contain none of `AutoCAD`, `LWPOLYLINE`, `ConstantWidth`, `Handle`, `Autodesk.Revit`, `ElementId`, `UniqueId`, `WallType`, or native feet conversion logic.

- [ ] **Step 4: Run RED, implement, run GREEN**

```powershell
$env:PYTHONPATH = "$PWD\platform\convergence\src;$PWD\platform\materialization_planning\src;$PWD\platform\changeset\src;$PWD\platform\semantic_runtime\src;$PWD\platform\execution_reconciliation\src"
python -m pytest tests/convergence -q -vv
```

- [ ] **Step 5: Commit**

```powershell
git add platform/convergence tests/convergence
git commit -m "feat: add provider-neutral exact cross-host convergence"
```

---

### Task 14: Add independent materialized Step37 coordination result/status and coordinator

**Files:**
- Create: `platform/execution_coordination/src/design_execution_coordination/materialized_contracts.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Modify: `platform/execution_coordination/pyproject.toml`
- Create: `tests/execution_coordination/test_phase_i_materialized_contracts.py`
- Create: `tests/execution_coordination/test_phase_i_materialized_success.py`
- Create: `tests/execution_coordination/test_phase_i_materialized_readiness_failed.py`
- Create: `tests/execution_coordination/test_phase_i_materialized_partial_commit.py`
- Create: `tests/execution_coordination/test_phase_i_materialized_unknown_commit.py`
- Create: `tests/execution_coordination/test_phase_i_materialized_divergence.py`
- Modify: `tests/execution_coordination/test_phase_i_v1_coordination_compatibility.py`

**Interfaces:**
- Consumes: exact `CanonicalChangeSet`, `ApprovalScopeBoundaryV2`, `MaterializationPlan`, `ExecutionPlanV2`, V2 binding sets, V2 admitted authorities, readiness barrier, Host execution registry, Step33 V2 reconciliation/store, convergence evidence port, and convergence verifier.
- Produces exact `MaterializedCoordinationStatus` values: `SUCCEEDED`, `FAILED`, `PARTIALLY_COMMITTED`, `RECOVERY_REQUIRED`, `READINESS_FAILED`, `DIVERGED`.
- Produces: `MaterializedCoordinationResult(saga_id: str, saga_revision: int, status: MaterializedCoordinationStatus, active_slice_hash: str | None, failure_ref: str | None, convergence_result_hash: str | None)`.
- Produces: `MaterializedHostExecutionPort.execute(execution_slice: ExecutionSliceV2, authority: AdmittedExecutionAuthorityV2, binding_set: ProviderBindingSetV2) -> HostExecutionResult`.
- Produces: `MaterializedHostExecutionRegistry.resolve(runtime_ref: HostRuntimeRef) -> MaterializedHostExecutionPort`.
- Produces: `ConvergenceEvidencePort.build_evidence(materialization_id: str, execution_slice: ExecutionSliceV2, actual_delta: ActualDelta, verification_result: SemanticVerificationResult, verification_bundle: VerificationEvidenceBundle, convergence_profile: ConvergenceComparisonProfile) -> MaterializationCanonicalEvidence`.
- Produces: `MaterializedExecutionSagaCoordinator.execute(canonical_changeset: CanonicalChangeSet, approval_scope_boundary: ApprovalScopeBoundaryV2, materialization_plan: MaterializationPlan, execution_plan: ExecutionPlanV2, binding_sets: Sequence[ProviderBindingSetV2], authorities: Sequence[AdmittedExecutionAuthorityV2], convergence_profile: ConvergenceComparisonProfile) -> MaterializedCoordinationResult`.
- Downstream guarantee: existing V1 `CoordinationStatus` and `CoordinationResult` are not modified; `READINESS_FAILED` and `DIVERGED` exist only on the materialized V2 coordination surface.

- [ ] **Step 1: Write RED V2 contract tests**

Require the exact materialized enum and result fields. Assert the V1 enum still has exactly the four historical values and V1 result construction is unchanged.

- [ ] **Step 2: Freeze coordinator call order**

```text
validate full V2 lineage and cross-materialization identity
-> run all-required readiness
-> if NOT_READY return MaterializedCoordinationStatus.READINESS_FAILED with zero Saga creation and zero Host commits
-> create/load Saga V2
-> AutoCAD execute -> ActualDelta -> scope compare -> semantic verify
-> Revit execute -> ActualDelta -> scope compare -> semantic verify
-> build canonical convergence evidence from successful verification bundles
-> exact convergence verify
-> finalize Saga V2 and return materialized result
```

- [ ] **Step 3: Write RED result matrix**

Success: Host order `autocad`, `revit`, once each; local Slices SUCCEEDED; convergence CONVERGED; Saga V2 and materialized result SUCCEEDED. Readiness failure: READINESS_FAILED, zero Host calls, zero active Step33 V2 Slice. Revit BEFORE_COMMIT after AutoCAD success: PARTIALLY_COMMITTED, no Revit ActualDelta, no compensation. Revit COMMIT_STATE_UNKNOWN: RECOVERY_REQUIRED, no retry/convergence. Both local success plus canonical mismatch: Saga/result DIVERGED, local successful Slice histories unchanged.

- [ ] **Step 4: Run RED, implement, run GREEN**

```powershell
$env:PYTHONPATH = "$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src;$PWD\platform\execution_reconciliation\src;$PWD\platform\execution_coordination\src;$PWD\platform\convergence\src;$PWD\platform\semantic_runtime\src"
python -m pytest tests/execution_coordination/test_phase_i_materialized_contracts.py tests/execution_coordination/test_phase_i_materialized_success.py tests/execution_coordination/test_phase_i_materialized_readiness_failed.py tests/execution_coordination/test_phase_i_materialized_partial_commit.py tests/execution_coordination/test_phase_i_materialized_unknown_commit.py tests/execution_coordination/test_phase_i_materialized_divergence.py -q -vv
python -m pytest tests/execution_coordination tests/execution_reconciliation -q -vv
```

Do not duplicate scope comparison, semantic verification, Host failure classification, or compensation logic.

- [ ] **Step 5: Commit**

```powershell
git add platform/execution_coordination tests/execution_coordination
git commit -m "feat: coordinate materialized cross-host sagas"
```

---

### Task 15: Add provider-neutral Phase I E2E proof, compatibility guards, and workflow triggers

**Files:**
- Create: `tests/integration/test_phase_i_materialization_pipeline.py`
- Create: `tests/integration/test_phase_i_convergence_divergence.py`
- Create: `tests/integration/test_phase_i_readiness_fail_closed.py`
- Create: `tests/architecture/test_phase_i_materialization_architecture.py`
- Modify: `.github/workflows/step28-approval-scope.yml`
- Modify: `.github/workflows/step29-immutable-changeset.yml`
- Modify: `.github/workflows/step30-execution-partitioning.yml`
- Modify: `.github/workflows/step31-provider-binding.yml`
- Modify: `.github/workflows/step32-gateway-authorization.yml`
- Modify: `.github/workflows/step33-execution-reconciliation.yml`
- Modify: `.github/workflows/step37-cross-host-saga-failure-injection.yml`

**Interfaces:**
- Consumes: all production V2 surfaces from Tasks 1–14 plus deterministic fake Host/readiness/evidence adapters.
- Produces: one offline positive proof, one divergence proof, one readiness fail-closed proof, and architecture/V1 compatibility guards.
- Produces no new production domain contract.
- Workflow guarantee: legacy Step28–37 workflows add only direct V2 package/test path triggers; they retain their existing test semantics and do not require desktop Hosts.

- [ ] **Step 1: Write offline positive pipeline**

Compose real V2 platform components with deterministic fake Hosts:

```text
V2 scope/topology -> Step29 ChangeSet -> exact convergence profile -> MaterializationPlan
-> Step30 V2 exact document-scope resolution -> Step31 V2 -> Step32 V2 -> readiness READY
-> AutoCAD local ActualDelta/scope/verification PASS
-> Revit local ActualDelta/scope/verification PASS
-> exact convergence CONVERGED -> Saga V2 SUCCEEDED -> materialized result SUCCEEDED
```

Assert all lineage hashes and both distinct document-scoped Step28 rules.

- [ ] **Step 2: Add offline fail-closed matrix**

Missing Revit readiness -> READINESS_FAILED and zero commits; missing/conflicting HostBinding -> zero commits; topology substitution rejected; binding substitution after grant rejected; availability cannot shrink required set; Step30 wrong-document/wider-rule fallback rejected; local success plus 300/305 canonical mismatch -> DIVERGED.

- [ ] **Step 3: Add architecture/compatibility guards**

Prove no availability discovery in Step30, no intent add/remove in Step31, no canonical-operation cloning in Step37, no Host-native vocabulary in topology/planning/convergence, no parallel mutation, no XA/2PC/distributed lock, no production failure flag, no inverse Host command API, V1 Step28–37 artifacts still validate through V1 paths, V1 Step33 store remains V1-typed, and V1 `CoordinationStatus` remains exactly unchanged.

- [ ] **Step 4: Update exact legacy workflow path filters only**

Add new V2 package/test paths to the seven listed workflows where they are direct dependencies. Do not add live desktop requirements to those legacy workflows.

- [ ] **Step 5: Run complete offline regression**

```powershell
$env:DSP_PHASE_I_LIVE = "0"
$env:DSP_REVIT_LIVE = "0"
$env:PYTHONPATH = "$PWD\contracts\python;$PWD\hosts\autocad\sidecar\src;$PWD\hosts\revit\sidecar\src;$PWD\platform\approval_scope\src;$PWD\platform\changeset\src;$PWD\platform\materialization_topology\src;$PWD\platform\materialization_planning\src;$PWD\platform\execution_planning\src;$PWD\platform\provider_binding\src;$PWD\platform\gateway_authorization\src;$PWD\platform\execution_reconciliation\src;$PWD\platform\execution_coordination\src;$PWD\platform\convergence\src;$PWD\platform\semantic_runtime\src;$PWD\platform\semantic_service\src;$PWD\platform\orchestrator\src"

python -m pytest `
  tests/materialization_topology `
  tests/materialization_planning `
  tests/convergence `
  tests/approval_scope `
  tests/changeset `
  tests/execution_planning `
  tests/provider_binding `
  tests/gateway_authorization `
  tests/execution_reconciliation `
  tests/execution_coordination `
  tests/integration/test_phase_i_materialization_pipeline.py `
  tests/integration/test_phase_i_convergence_divergence.py `
  tests/integration/test_phase_i_readiness_fail_closed.py `
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py `
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py `
  tests/integration/test_phase_h_revit_wall_thickness_live.py `
  tests/architecture/test_phase_i_materialization_architecture.py `
  -q -vv

dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Expected: offline suites green; live-only Revit gate explicitly skipped.

- [ ] **Step 6: Commit**

```powershell
git add tests .github/workflows/step28-approval-scope.yml .github/workflows/step29-immutable-changeset.yml .github/workflows/step30-execution-partitioning.yml .github/workflows/step31-provider-binding.yml .github/workflows/step32-gateway-authorization.yml .github/workflows/step33-execution-reconciliation.yml .github/workflows/step37-cross-host-saga-failure-injection.yml
git commit -m "test: prove phase i provider-neutral materialization pipeline"
```

---

### Task 16: Add real AutoCAD + Revit acceptance, deterministic partial commit, runbook, and Phase I workflow

**Files:**
- Create: `tests/integration/phase_i_live_host.py`
- Create: `tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py`
- Create: `docs/runbooks/phase-i-real-cross-host-wall-thickness.md`
- Create: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`

No fixture file or fixture manifest is modified by this plan. The live test receives fixture paths, expected hashes, AutoCAD native id, and Revit UniqueId through environment variables. Any future decision to commit fixture manifests requires separate explicit user approval.

**Interfaces:**
- Consumes: production AutoCAD/Revit readiness ports, production Host mutation adapters, all Tasks 1–14 platform V2 contracts/services, controlled fixture paths/hashes, AutoCAD native id, Revit UniqueId, and live Host endpoints.
- Produces test adapters: `AutoCadMaterializedExecutionPort`, `RevitMaterializedExecutionPort`, real readiness registry, and `PhaseIConvergenceEvidencePort`.
- Produces: gated real positive acceptance and deterministic real partial-commit acceptance.
- Produces: runbook and dedicated workflow only; no fixture content and no production failure-injection API.

- [ ] **Step 1: Create exact live adapter composition**

`AutoCadMaterializedExecutionPort` wraps existing `CommandDispatcher.set_wall_thickness` and production Step34 execution-result normalization. `RevitMaterializedExecutionPort` wraps existing `revit_sidecar.model_adapter`, `named_pipe`, and `execution_result_adapter` production paths. `PhaseIConvergenceEvidencePort` derives canonical evidence only from real D5/Semantic `VerificationEvidenceBundle` values, never native Host JSON.

- [ ] **Step 2: Write the gated live test skeleton**

```python
if os.environ.get("DSP_PHASE_I_LIVE") != "1":
    pytest.skip("set DSP_PHASE_I_LIVE=1 to run the real AutoCAD + Revit Phase I gate")
```

Required environment variables include AutoCAD endpoint/document/fixture hash/native id; Revit pipe/fixture hash/UniqueId/version/TFM/API dir; and expected 200 mm baseline.

- [ ] **Step 3: Implement real positive acceptance**

Require: required set `{autocad,revit}`; exact bindings; both readiness receipts READY; barrier READY; AutoCAD 200 -> 300 real commit/reconciliation; Revit 200 -> 300 one real transaction/reconciliation; both canonical post-state bundles expose `properties.dsp:WallThickness = {value:300, unit:mm}`; convergence CONVERGED; Saga V2 and materialized result SUCCEEDED.

Print one compact JSON evidence record containing ChangeSet/scope/topology/plan/required-set/Slice/binding/grant/readiness/ActualDelta/verification/convergence hashes and final statuses.

- [ ] **Step 4: Implement deterministic real partial-commit race without a debug flag**

After both readiness receipts pass and AutoCAD commits, issue a separate legitimate Revit `EXECUTE/set_wall_thickness` command outside the Saga against the same controlled target using the current revision and a unique idempotency key, changing 200 mm to 201 mm. This external concurrent edit advances `DocumentChanged`. Execute the Saga's already-frozen Revit command with the stale readiness-time revision.

Assert Revit returns `REVISION_CONFLICT / BEFORE_COMMIT`; Revit Slice has no ActualDelta; AutoCAD Slice remains SUCCEEDED; materialized result is PARTIALLY_COMMITTED; no convergence or automatic compensation executes. The 201 mm edit is test-harness concurrency evidence, not a Saga Slice.

- [ ] **Step 5: Add runbook with reset discipline**

Document exact Host versions/endpoints, fixture SHA-256 checks, binding IDs, Revit 2027 build command from `C:\`, all environment variables, positive/partial-commit commands, and `DO NOT SAVE` close/reopen restoration after every mutation. Record live evidence only from fresh complete command output.

- [ ] **Step 6: Add dedicated workflow**

`.github/workflows/phase-i-real-cross-host-materialization-saga.yml` has a GitHub-hosted offline V2/legacy/Core job with `DSP_PHASE_I_LIVE=0` and a `workflow_dispatch` real dual-Host job restricted to an explicitly configured Windows self-hosted runner label with `DSP_PHASE_I_LIVE=1`. It must not claim GitHub-hosted runners can launch desktop AutoCAD/Revit.

- [ ] **Step 7: Run full offline gate and Revit native build before live mutation**

Use Task 15's offline command, then:

```powershell
cd C:\
dotnet build E:\DAPS\enterprise-design-agent\hosts\revit\plugin\Revit.AgentHost\Revit.AgentHost.csproj `
  -p:DspRevitVersion="2027" `
  -p:DspRevitTargetFramework="net10.0-windows" `
  -p:DspRevitApiDir="C:\Program Files\Autodesk\Revit 2027"
```

- [ ] **Step 8: Run real positive gate, restore both fixtures, run real partial-commit gate, restore again**

Require fresh complete pytest output for each scenario. Never infer PASS from visible model state.

- [ ] **Step 9: Record exact live evidence and verify the exact implementation tree**

```powershell
$base = git merge-base main HEAD
git diff --check $base HEAD
git status --short
git rev-parse HEAD
```

Rerun the full offline Phase I gate plus Revit Core tests on final implementation HEAD. If production AutoCAD/Revit source changes after live evidence, rerun the affected native/live gate before completion claims.

- [ ] **Step 10: Commit**

```powershell
git add tests/integration/phase_i_live_host.py tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py docs/runbooks/phase-i-real-cross-host-wall-thickness.md .github/workflows/phase-i-real-cross-host-materialization-saga.yml
git commit -m "test: add phase i real cross-host acceptance gate"
```

---

## Final Verification Matrix

Collect fresh evidence for every row before calling Phase I complete:

```text
Step28 V1 hash compatibility                                      PASS
Step28 V2 scope_definition_id derives from V2 scope_body_hash     PASS
Step28 V2 scope binds topology before Step29                      PASS
Step29 V2 integrity binds V2 scope without changing V1            PASS
Topology field is topology_environment_id                         PASS
Topology required set immutable and availability-independent      PASS
One canonical operation -> two REQUIRED materialization intents   PASS
Convergence profile derives mm from validated ChangeSet/contract  PASS
Convergence profile has no undeclared tolerance                   PASS
MaterializationPlan binds scope/topology/convergence profile      PASS
Step30 V2 one intent -> one unit                                  PASS
Step30 exact document_ref -> exact scope rule                     PASS
Step30 missing/duplicate/wider scope candidate fails closed       PASS
Step30 deterministic order autocad -> revit                       PASS
Step31 exact 1:1 HostBinding cardinality                          PASS
Missing/conflicting binding fails closed                          PASS
Step32 V2 grant binds exact materialization/plan/binding          PASS
All-required readiness blocks first commit if any Host unready    PASS
Readiness performs zero Host mutations                            PASS
V1 CoordinationStatus exact four-member compatibility             PASS
Real AutoCAD readiness + mutation + local reconciliation          PASS
Real Revit readiness + mutation + local reconciliation            PASS
Step33 V2 uses independent V2 durable store/state                 PASS
Step33 V1 store remains V1-typed                                  PASS
Both real canonical post-states expose 300 mm                     PASS
Cross-host exact convergence positive case = CONVERGED            PASS
Positive Saga V2 = SUCCEEDED                                      PASS
Real post-readiness Revit revision race = BEFORE_COMMIT           PASS
Real partial-commit result = PARTIALLY_COMMITTED                  PASS
No false Revit ActualDelta on pre-commit failure                  PASS
COMMIT_STATE_UNKNOWN = RECOVERY_REQUIRED                          PASS
Provider-neutral mismatch yields Saga V2 DIVERGED                 PASS
DIVERGED preserves locally successful Slice histories             PASS
Materialized coordinator owns READINESS_FAILED and DIVERGED       PASS
No production failure injection                                   PASS
No automatic compensation execution                               PASS
No inverse native command inference                               PASS
No XA/2PC/distributed lock/parallel Host mutation                 PASS
No Host-native vocabulary in topology/planning/convergence core  PASS
Step28–37 V1 legacy regressions                                   PASS
Step34 AutoCAD wall-thickness regression                          PASS
Phase H Revit wall-thickness regression/live gate                 PASS
Final diff/check/status on exact implementation HEAD              PASS
```

## Expected Commit Sequence

```text
feat: add versioned materialization approval scope
feat: add immutable materialization topology
feat: validate changesets against materialization scope v2
feat: add exact convergence comparison profiles
feat: add deterministic materialization planning
feat: add materialization-aware execution planning v2
feat: bind providers to exact materializations
feat: authorize exact materialization executions
feat: add all-required cross-host readiness barrier
feat: add read-only autocad wall readiness
feat: add read-only revit wall readiness
feat: add materialized saga v2 reconciliation
feat: add provider-neutral exact cross-host convergence
feat: coordinate materialized cross-host sagas
test: prove phase i provider-neutral materialization pipeline
test: add phase i real cross-host acceptance gate
```

## Plan Self-Review Gate

Before implementation handoff, the plan branch itself must satisfy all of the following:

```text
Spec coverage: every frozen Phase I requirement maps to at least one Task
Interfaces: every Task contains explicit Consumes and Produces contracts
Placeholder scan: no implementation-placeholder signatures or vague deferred steps
Type consistency: V2 type/function names are identical across producing/consuming Tasks
Field consistency: topology_environment_id is used everywhere for topology namespace
V1 compatibility: no plan step changes V1 Step28/29/30/31/32/33/37 semantic meaning
Git history: spec commit + one final plan commit only
Tree diff vs main: only the frozen spec and this final plan document
Production code: unchanged on the design branch
```
