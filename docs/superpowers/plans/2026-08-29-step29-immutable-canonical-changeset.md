# Step 29 Immutable Canonical ChangeSet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase-2 HostDelta placeholder with a provider-neutral immutable canonical ChangeSet that is cryptographically bound to the exact D6 operation material, Step27 impact result, and Step28 approval-scope body.

**Architecture:** Step29 reclaims `platform/changeset` as the canonical logical-transaction package under `design_changeset`. The workflow supplies provider-neutral evidence projected from Step23/D6; Step29 validates those inputs against the exact `ImpactAnalysis` and `ApprovalScopeDefinition`, materializes one root operation plus explicit derived operations, computes a deterministic `changeset_hash`, and then allows Step28's existing pure `bind_changeset` function to create the final `ApprovalScopeBoundary`. A minimal Step27 hardening adds `bound_operation_fingerprint` without changing the existing `analysis_fingerprint` algorithm.

**Tech Stack:** Python 3.11, frozen dataclasses, `jsonschema`, SHA-256 canonical JSON, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step29-immutable-canonical-changeset-design.md`

## Global Constraints

- Base is `main@130d61072ab561ce3fb013433ceca3edd803c0e0` plus the approved Step29 design commits on `feat/step29-immutable-canonical-changeset`.
- Step29 is provider-neutral and MUST NOT import Host products, provider packages, ProviderBinding, HostCommand, ApprovalRecord, ExecutionGrant, policy/risk owners, Step30 execution DTOs, or Step33 runtime DTOs.
- `CanonicalChangeSet` and all nested value contracts are immutable/frozen and defensively normalize mutable inputs.
- Step29 v1 has exactly one root operation.
- `expected_effects` is derived only from exact Step23 canonical operation contract evidence; callers cannot override it.
- Step29 v1 permits mutation membership only through Step28 explicit-entity selectors; predicate-only membership fails closed.
- Step29 does not activate creation/deletion authority.
- Derived operations require exact Step27 `PropagationBundle` + `proposed_change_hash` evidence and exact Step23 canonical operation contract evidence.
- Every admitted deterministic Step27 proposal must be materialized exactly once; advisory-only and Host-native verification-only impacts do not become derived mutation nodes.
- `changeset_hash` excludes opaque construction ids and final `ApprovalScopeBoundary.scope_hash`; it includes all semantic transaction material listed in the spec.
- Existing Step27 `analysis_fingerprint` payload/algorithm MUST remain unchanged for equivalent input.
- Step30's future contract consumes only `CanonicalChangeSet + ApprovalScopeBoundary`; Step29 MUST NOT create `ExecutionSlice` or `ExecutionUnit` production DTOs.

---

## File Map

### New canonical ChangeSet package

- `platform/changeset/src/design_changeset/contracts.py` — frozen public value contracts and stable `ChangeSetError`.
- `platform/changeset/src/design_changeset/hashing.py` — canonical JSON, evidence fingerprints, proposed-change fingerprints, operation/body hashing.
- `platform/changeset/src/design_changeset/builder.py` — fail-closed cross-input validation and deterministic transaction materialization.
- `platform/changeset/src/design_changeset/__init__.py` — explicit public API via `__all__`.

### Step27 hardening

- `platform/impact/src/design_impact/contracts.py` — add `ImpactAnalysis.bound_operation_fingerprint`.
- `platform/impact/src/design_impact/analyzer.py` — compute the shared material-operation fingerprint without changing `analysis_fingerprint`.
- `docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md` — record the new public binding field.

### Package/config migration

- `platform/changeset/pyproject.toml` — remove `host-contracts`, update package description, keep Python `>=3.11`.
- `pyproject.toml` — add `platform/changeset/src` to pytest `pythonpath`.
- Delete the five legacy Phase-2 files under `platform/changeset/src/changeset/`.

### Tests / CI

- `tests/changeset/test_step29_step27_binding.py`
- `tests/changeset/test_step29_contracts.py`
- `tests/changeset/test_step29_hashing.py`
- `tests/changeset/test_step29_builder.py`
- `tests/changeset/test_step29_architecture.py`
- `.github/workflows/step29-immutable-changeset.yml`

---

### Task 1: Expose a verifiable D6 material-operation fingerprint from Step27

**Files:**
- Modify: `platform/impact/src/design_impact/contracts.py`
- Modify: `platform/impact/src/design_impact/analyzer.py`
- Modify: `docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md`
- Modify: `docs/superpowers/specs/2026-08-29-step29-immutable-canonical-changeset-design.md`
- Create: `tests/changeset/test_step29_step27_binding.py`

**Interfaces:**
- Produces: `ImpactAnalysis.bound_operation_fingerprint: str`
- Produces: shared semantic algorithm `SHA256(canonical_json({canonical_operation, canonical_operation_version, arguments}))`
- Preserves: existing `ImpactAnalysis.analysis_fingerprint` value for the same request.

- [ ] **Step 1: Write the failing Step27 binding tests**

Create tests that prove the new field is absent before implementation and that the old `analysis_fingerprint` remains unchanged by the hardening:

```python
def test_impact_analysis_exposes_bound_operation_fingerprint():
    result = ImpactAnalyzer().analyze(_request(bound=_bound_move()))
    assert result.bound_operation_fingerprint == _material_operation_hash(
        "move.v1",
        "1.0.0",
        {"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]},
    )


def test_material_argument_change_changes_bound_operation_fingerprint():
    first = ImpactAnalyzer().analyze(_request(bound=_bound_move(displacement=(100.0, 0.0, 0.0))))
    second = ImpactAnalyzer().analyze(_request(bound=_bound_move(displacement=(101.0, 0.0, 0.0))))
    assert first.bound_operation_fingerprint != second.bound_operation_fingerprint


def test_step27_analysis_fingerprint_algorithm_remains_unchanged():
    request = _request(bound=_bound_move())
    expected = _legacy_analysis_fingerprint_reference(request)
    assert ImpactAnalyzer().analyze(request).analysis_fingerprint == expected
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/changeset/test_step29_step27_binding.py
```

Expected: FAIL because `ImpactAnalysis` has no `bound_operation_fingerprint` field yet.

- [ ] **Step 3: Add the field to `ImpactAnalysis`**

Add the field immediately before `analysis_fingerprint` and validate it as required non-empty text:

```python
@dataclass(frozen=True, slots=True)
class ImpactAnalysis:
    ...
    bound_operation_fingerprint: str = ""
    analysis_fingerprint: str = ""
```

- [ ] **Step 4: Compute the shared material-operation fingerprint in Step27**

Add a helper whose payload is exactly:

```python
{
    "canonical_operation": bound.operation.canonical_operation,
    "canonical_operation_version": bound.operation.version,
    "arguments": _jsonable(bound.arguments),
}
```

Use the existing canonical SHA-256 helper and pass the result into `ImpactAnalysis`. Do not add the new field to `_analysis_fingerprint`'s payload.

- [ ] **Step 5: Record the contract hardening in both design specs**

Amend the Step27 output shape with `bound_operation_fingerprint` and amend Step29 `BoundOperationEvidence` to include the D6 `planning_requirements` projection, because Step29 preconditions are derived from it:

```text
BoundOperationEvidence {
  ...
  planning_requirements
  binding_evidence
  bound_operation_fingerprint
  bound_operation_evidence_fingerprint
}
```

- [ ] **Step 6: Run Step27 binding + existing impact regressions**

Run:

```bash
pytest -q tests/changeset/test_step29_step27_binding.py tests/impact
```

Expected: all pass, including existing Step27 fingerprint determinism tests.

- [ ] **Step 7: Commit**

```bash
git add platform/impact/src/design_impact/contracts.py \
  platform/impact/src/design_impact/analyzer.py \
  tests/changeset/test_step29_step27_binding.py \
  docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md \
  docs/superpowers/specs/2026-08-29-step29-immutable-canonical-changeset-design.md
git commit -m "feat: expose Step27 bound operation fingerprint"
```

---

### Task 2: Replace the legacy ChangeSet package shell with immutable provider-neutral contracts

**Files:**
- Modify: `platform/changeset/pyproject.toml`
- Modify: `pyproject.toml`
- Create: `platform/changeset/src/design_changeset/contracts.py`
- Create: `platform/changeset/src/design_changeset/__init__.py`
- Create: `tests/changeset/test_step29_contracts.py`

**Interfaces:**
- Produces: `ChangeSetError(code: str, message: str)`
- Produces enums: `OperationOrigin`, `OperationSourceKind`, `PreconditionKind`, `ValidationTaskKind`
- Produces immutable DTOs: `CanonicalOperationContractEvidence`, `BoundOperationEvidence`, `ApprovalScopeDefinitionRef`, `OperationSourceEvidence`, `CanonicalChangeOperation`, `DerivedOperationMaterialization`, `ChangeDependency`, `ChangePrecondition`, `SemanticImpactEvidence`, `ValidationTask`, `CanonicalChangeSet`, `ChangeSetBuildRequest`.

- [ ] **Step 1: Write failing import/immutability tests**

Representative assertions:

```python
def test_changeset_contracts_are_frozen():
    evidence = CanonicalOperationContractEvidence(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema=MOVE_SCHEMA,
        effects=("PLACEMENT", "GEOMETRY"),
        verification_contract={"type": "HOST_READ_BACK"},
        definition_fingerprint="a" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        evidence.canonical_operation = "other.v1"


def test_build_request_does_not_accept_expected_effects():
    assert "expected_effects" not in DerivedOperationMaterialization.__dataclass_fields__
```

Also assert mappings are defensive/read-only and tuple fields normalize deterministically.

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_contracts.py
```

Expected: import failure because `design_changeset` does not exist.

- [ ] **Step 3: Update package metadata and root pythonpath**

Use:

```toml
[project]
name = "design-changeset"
version = "0.1.0"
description = "Provider-neutral immutable canonical ChangeSet contracts for DSP."
requires-python = ">=3.11"
dependencies = ["jsonschema>=4.20"]
```

Add `platform/changeset/src` to root pytest `pythonpath`.

- [ ] **Step 4: Implement the frozen contracts**

Key exact fields:

```python
@dataclass(frozen=True, slots=True)
class BoundOperationEvidence:
    canonical_operation: str
    canonical_operation_version: str
    arguments: Mapping[str, Any]
    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str
    semantic_environment_id: str
    planning_requirements: Mapping[str, tuple[Mapping[str, Any], ...]]
    binding_evidence: Mapping[str, Mapping[str, Any]]
    bound_operation_fingerprint: str
    bound_operation_evidence_fingerprint: str
```

```python
@dataclass(frozen=True, slots=True)
class CanonicalChangeSet:
    changeset_id: str
    task_id: str
    project_id: str | None
    planning_snapshot_ref: Any
    snapshot_set_ref: Any
    semantic_environment_ref: Any
    impact_analysis_fingerprint: str
    bound_operation_fingerprint: str
    approval_scope_definition_ref: ApprovalScopeDefinitionRef
    root_operation: CanonicalChangeOperation
    derived_operations: tuple[CanonicalChangeOperation, ...]
    change_dependencies: tuple[ChangeDependency, ...]
    preconditions: tuple[ChangePrecondition, ...]
    affected_entities: tuple[str, ...]
    semantic_impacts: tuple[SemanticImpactEvidence, ...]
    validation_tasks: tuple[ValidationTask, ...]
    changeset_hash: str
```

`ChangeSetBuildRequest` contains `task_id`, optional `project_id`, `bound_operation_evidence`, `impact_analysis`, `approval_scope_definition`, `canonical_operation_contracts`, and `derived_materializations`.

- [ ] **Step 5: Freeze the explicit public API**

`design_changeset/__init__.py` imports and exposes the intended contract classes only through explicit `__all__`.

- [ ] **Step 6: Run contract tests**

```bash
pytest -q tests/changeset/test_step29_contracts.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/changeset/pyproject.toml pyproject.toml \
  platform/changeset/src/design_changeset \
  tests/changeset/test_step29_contracts.py
git commit -m "feat: add immutable Step29 changeset contracts"
```

---

### Task 3: Add deterministic hashing and evidence fingerprints

**Files:**
- Create: `platform/changeset/src/design_changeset/hashing.py`
- Create: `tests/changeset/test_step29_hashing.py`
- Modify: `platform/changeset/src/design_changeset/__init__.py`

**Interfaces:**
- Produces: `canonical_hash(payload: object) -> str`
- Produces: `compute_bound_operation_fingerprint(...) -> str`
- Produces: `compute_bound_operation_evidence_fingerprint(...) -> str`
- Produces: `compute_contract_definition_fingerprint(...) -> str`
- Produces: `compute_proposed_change_hash(change: Mapping[str, object]) -> str`
- Produces: `compute_changeset_hash(...) -> str`

- [ ] **Step 1: Write failing hashing tests**

Cover:

```python
def test_semantically_equivalent_mapping_order_has_same_hash(): ...
def test_material_argument_change_changes_bound_operation_hash(): ...
def test_scope_body_hash_change_changes_changeset_hash(): ...
def test_snapshot_or_environment_change_changes_changeset_hash(): ...
def test_construction_ids_do_not_change_changeset_hash(): ...
def test_proposed_change_hash_is_order_independent(): ...
```

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_hashing.py
```

Expected: import/function failures.

- [ ] **Step 3: Implement canonical JSON normalization**

Normalize enums by `.value`, mappings by lexicographically sorted string keys, tuples/lists to arrays, immutable mapping proxies by content, and hash UTF-8 JSON using:

```python
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

- [ ] **Step 4: Implement semantic fingerprints**

The shared material-operation hash payload is exactly:

```python
{
    "canonical_operation": canonical_operation,
    "canonical_operation_version": version,
    "arguments": normalized_arguments,
}
```

The full D6 evidence fingerprint additionally commits to context snapshot evidence, semantic environment id, normalized planning requirements, and binding evidence.

The Step23 contract fingerprint commits to operation/version, argument schema, effects, and verification contract.

- [ ] **Step 5: Implement ChangeSet semantic-body hashing**

Exclude `changeset_id`, operation ids, validation task ids, `scope_definition_id`, and raw Step28 rule ids. Replace referenced scope rule ids with semantic coverage fingerprints derived from each referenced Step28 `ExistingEntityRule`.

Include all semantic fields required by the design: task/project refs, planning/snapshot/environment refs, impact/bound-operation fingerprints, scope body hash, operation bodies, source evidence semantic fingerprints, DAG semantics, preconditions, affected entities, semantic impacts, and validation obligations.

- [ ] **Step 6: Run hashing tests**

```bash
pytest -q tests/changeset/test_step29_hashing.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/changeset/src/design_changeset/hashing.py \
  platform/changeset/src/design_changeset/__init__.py \
  tests/changeset/test_step29_hashing.py
git commit -m "feat: add deterministic Step29 hashing"
```

---

### Task 4: Materialize and validate the root canonical operation

**Files:**
- Create: `platform/changeset/src/design_changeset/builder.py`
- Create: `tests/changeset/test_step29_builder.py`
- Modify: `platform/changeset/src/design_changeset/__init__.py`

**Interfaces:**
- Produces: `ChangeSetBuilder.build(request: ChangeSetBuildRequest) -> CanonicalChangeSet`
- Consumes: public `design_impact.ImpactAnalysis` and `design_approval_scope.ApprovalScopeDefinition` contracts only.

- [ ] **Step 1: Write failing root-materialization tests**

Cover exact rejection codes:

```python
CHANGESET_INPUT_INVALID
CHANGESET_SNAPSHOT_MISMATCH
CHANGESET_SEMANTIC_ENVIRONMENT_MISMATCH
CHANGESET_IMPACT_MISMATCH
CHANGESET_SCOPE_MISMATCH
CHANGESET_CANONICAL_OPERATION_UNKNOWN
CHANGESET_CANONICAL_OPERATION_VERSION_MISMATCH
CHANGESET_ARGUMENTS_INVALID
CHANGESET_TARGET_MISMATCH
CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED
CHANGESET_SCOPE_EFFECT_EXCEEDED
```

Also prove:

```python
assert result.root_operation.expected_effects == (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT)
```

and that the caller never supplies that field.

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_builder.py -k 'root or scope or argument or impact'
```

Expected: failures because builder does not exist.

- [ ] **Step 3: Implement request/type and cross-input validation**

Validate:

```text
bound operation name == ImpactAnalysis.canonical_operation
recomputed bound_operation_fingerprint == ImpactAnalysis.bound_operation_fingerprint
ImpactAnalysis fingerprint == ApprovalScopeDefinition.impact_analysis_fingerprint
planning/snapshot/environment refs exactly match Step28 definition
bound semantic_environment_id == ImpactAnalysis environment id
bound document_ref == ImpactAnalysis planning snapshot document_ref
normalized bound targets == ImpactAnalysis.direct_targets
Step23 contract name/version == bound operation name/version
Step23 effects == Step28 CanonicalEffectEvidence allowed_aspects
```

Map `jsonschema.ValidationError`/`SchemaError` into `ChangeSetError("CHANGESET_ARGUMENTS_INVALID", ...)`.

- [ ] **Step 4: Implement explicit-entity scope coverage**

For every `(target, expected_effect)` pair, collect only `ExistingEntityRule` values with `selector.entities` containing that target. Predicate selectors never prove membership. Require the union of allowed aspects to cover all contract effects.

- [ ] **Step 5: Materialize the root operation**

Generate expected effects from the exact contract evidence, compute a semantic operation fingerprint, derive:

```text
operation_id = COP-{operation_hash[:12]}
```

and create `OperationSourceEvidence(ROOT_BOUND_OPERATION, bound_operation_evidence_fingerprint)`.

- [ ] **Step 6: Run focused root tests**

```bash
pytest -q tests/changeset/test_step29_builder.py -k 'root or scope or argument or impact'
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/changeset/src/design_changeset/builder.py \
  platform/changeset/src/design_changeset/__init__.py \
  tests/changeset/test_step29_builder.py
git commit -m "feat: materialize Step29 root operation"
```

---

### Task 5: Materialize deterministic derived operations and the v1 Change DAG

**Files:**
- Modify: `platform/changeset/src/design_changeset/builder.py`
- Modify: `tests/changeset/test_step29_builder.py`

**Interfaces:**
- Consumes: `ImpactAnalysis.propagation_bundles`, Step28 `propagation_bundle_ids`, `DerivedOperationMaterialization`.
- Produces: `derived_operations[]`, `change_dependencies[]`.

- [ ] **Step 1: Write failing derived-operation tests**

Cover:

```text
CHANGESET_DERIVED_BUNDLE_UNKNOWN
CHANGESET_DERIVED_PROPOSAL_UNKNOWN
CHANGESET_DERIVED_PROPOSAL_DUPLICATE
CHANGESET_DERIVED_MATERIALIZATION_MISSING
CHANGESET_DERIVED_OPERATION_INVALID
CHANGESET_DAG_INVALID
```

Tests must show:

- unknown bundle fails;
- unknown `proposed_change_hash` fails;
- one proposal cannot be materialized twice;
- every proposed change in an admitted deterministic `SEMANTIC_RUNTIME` mutation bundle is materialized exactly once;
- Host-native `requires_verification=True` impact creates no derived mutation;
- only root→derived edges are generated;
- caller cannot inject derived→derived causality.

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_builder.py -k 'derived or proposal or dag'
```

Expected: FAIL on missing behavior.

- [ ] **Step 3: Index Step27 bundle/proposal evidence deterministically**

Compute `proposed_change_hash` for each bundle proposal and reject duplicate hashes within the same analysis if they would make identity ambiguous.

- [ ] **Step 4: Validate each materialization against both evidence sources**

Require exact bundle/proposal match, exact canonical contract name/version, valid arguments, target alignment with the proposal's `affected_semantic_id`, and complete explicit Step28 scope coverage.

- [ ] **Step 5: Enforce admitted deterministic proposal completeness**

For each bundle id admitted by `ApprovalScopeDefinition.propagation_bundle_ids`, materialize every deterministic platform-owned proposal exactly once. Do not require derived mutation for Host-native verification-only impacts or advisory-only impacts.

- [ ] **Step 6: Generate the v1 DAG**

For each derived operation generate exactly one evidence-backed edge from root to derived. Derive edge semantic identity from root op semantic fingerprint + derived op semantic fingerprint + bundle/proposal evidence. Validate acyclicity defensively even though v1 topology is constrained.

- [ ] **Step 7: Run derived/DAG tests**

```bash
pytest -q tests/changeset/test_step29_builder.py -k 'derived or proposal or dag'
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add platform/changeset/src/design_changeset/builder.py tests/changeset/test_step29_builder.py
git commit -m "feat: materialize Step29 derived operations"
```

---

### Task 6: Project preconditions, semantic impacts, validation obligations, final hash, and Step28 binding

**Files:**
- Modify: `platform/changeset/src/design_changeset/builder.py`
- Modify: `platform/changeset/src/design_changeset/hashing.py`
- Modify: `tests/changeset/test_step29_builder.py`
- Modify: `tests/changeset/test_step29_hashing.py`

**Interfaces:**
- Produces deterministic `preconditions`, `affected_entities`, `semantic_impacts`, `validation_tasks`, `changeset_hash`, `changeset_id`.
- Integrates with existing `design_approval_scope.bind_changeset(scope_definition, changeset_hash, scope_id)`.

- [ ] **Step 1: Write failing projection/binding tests**

Cover:

```python
def test_affected_entities_is_direct_plus_all_predicted_entities(): ...
def test_semantic_impact_is_evidence_not_mutation_permission(): ...
def test_planning_requirements_become_closed_precondition_kinds(): ...
def test_move_contract_generates_host_read_back_validation_obligation(): ...
def test_host_native_predicted_impact_generates_dependency_validation_obligation(): ...
def test_equivalent_input_order_yields_same_changeset_hash(): ...
def test_generated_hash_binds_through_step28_without_body_change(): ...
```

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_builder.py tests/changeset/test_step29_hashing.py
```

Expected: failures for missing projections/final hash.

- [ ] **Step 3: Project D6 planning requirements into preconditions**

Map the three D6 requirement collections to the closed enum values:

```text
operation_freshness_requirements -> OPERATION_FRESHNESS
coverage_requirements -> COVERAGE
assurance_requirements -> ASSURANCE
```

Hash each normalized requirement body into an evidence ref; do not preserve free-form policy authority.

- [ ] **Step 4: Project Step27 predicted impacts and affected entities**

`affected_entities` is the sorted unique union of direct targets and every `PredictedImpact.affected_semantic_id`. `semantic_impacts` is a one-to-one normalized evidence projection and never influences mutation admission.

- [ ] **Step 5: Generate validation obligations**

For every materialized canonical operation with a non-empty verification contract create a `CANONICAL_OPERATION` validation task whose `contract_ref` is a deterministic fingerprint of that exact verification contract.

For every `PredictedImpact.requires_verification == True`, create a `DEPENDENCY_VERIFICATION` task bound to the exact `dependency_ref` and affected entity.

Derive `validation_task_id = VT-{validation_semantic_hash[:12]}`.

- [ ] **Step 6: Compute the final transaction hash and id**

Call `compute_changeset_hash` only after the complete semantic body exists, then derive:

```text
changeset_id = CS-{changeset_hash[:12]}
```

Callers never provide `changeset_hash` or `changeset_id` to the builder.

- [ ] **Step 7: Prove Step28 binding is pure**

Test:

```python
boundary = bind_changeset(scope_definition, changeset.changeset_hash, "SCOPE-FINAL")
assert boundary.changeset_hash == changeset.changeset_hash
assert boundary.scope_body_hash == scope_definition.scope_body_hash
assert boundary.existing_entity_rules == scope_definition.existing_entity_rules
assert boundary.creation_rules == scope_definition.creation_rules
assert boundary.deletion_rules == scope_definition.deletion_rules
assert boundary.propagation_bundle_ids == scope_definition.propagation_bundle_ids
```

- [ ] **Step 8: Run all Step29 functional tests**

```bash
pytest -q tests/changeset/test_step29_contracts.py \
  tests/changeset/test_step29_hashing.py \
  tests/changeset/test_step29_builder.py \
  tests/changeset/test_step29_step27_binding.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add platform/changeset/src/design_changeset/builder.py \
  platform/changeset/src/design_changeset/hashing.py \
  tests/changeset
git commit -m "feat: finalize immutable Step29 changeset"
```

---

### Task 7: Remove the HostDelta placeholder and enforce architecture boundaries

**Files:**
- Delete: `platform/changeset/src/changeset/model.py`
- Delete: `platform/changeset/src/changeset/builder.py`
- Delete: `platform/changeset/src/changeset/execution_slice.py`
- Delete: `platform/changeset/src/changeset/execution_unit.py`
- Delete: `platform/changeset/src/changeset/verification.py`
- Create: `tests/changeset/test_step29_architecture.py`

**Interfaces:**
- Produces: one unambiguous public ChangeSet meaning under `design_changeset`.

- [ ] **Step 1: Write failing architecture guards**

Assert:

```python
def test_legacy_changeset_placeholder_is_removed():
    assert not (ROOT / "src" / "changeset").exists()


def test_step29_has_no_host_provider_runtime_leakage():
    forbidden = (
        "host_contracts",
        "HostCommand",
        "ProviderBinding",
        "provider_tool",
        "native_id",
        "AutoCAD",
        "Revit",
        "Tekla",
        "ApprovalRecord",
        "ExecutionGrant",
        "PolicySnapshot",
        "ExecutionSlice",
        "ExecutionUnit",
        "ActualDelta",
        "VerificationReport",
    )
```

Also assert explicit `__all__`, frozen dataclasses, no public builder input fields named `expected_effects`, `changeset_hash`, or `changeset_id`.

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/changeset/test_step29_architecture.py
```

Expected: FAIL because legacy files still exist.

- [ ] **Step 3: Delete all five legacy Phase-2 files**

Delete the files listed above. Do not add aliases or compatibility shims.

- [ ] **Step 4: Run architecture + functional tests**

```bash
pytest -q tests/changeset
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A platform/changeset/src tests/changeset/test_step29_architecture.py
git commit -m "refactor: retire HostDelta changeset placeholder"
```

---

### Task 8: Add Step29 CI, regression gates, lint, and full-repository verification

**Files:**
- Create: `.github/workflows/step29-immutable-changeset.yml`
- Modify: `docs/superpowers/plans/2026-08-29-step29-immutable-canonical-changeset.md` only to check completed boxes if desired; no semantic redesign.

**Interfaces:**
- Produces: PR-triggered proof that Step29 and all relevant upstream contracts remain green.

- [ ] **Step 1: Add the Step29 workflow with an exact diff boundary**

Allow only:

```text
.github/workflows/step29-immutable-changeset.yml
docs/superpowers/specs/2026-08-29-step29-immutable-canonical-changeset-design.md
docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md
docs/superpowers/plans/2026-08-29-step29-immutable-canonical-changeset.md
platform/impact/src/design_impact/contracts.py
platform/impact/src/design_impact/analyzer.py
platform/changeset/pyproject.toml
platform/changeset/src/design_changeset/__init__.py
platform/changeset/src/design_changeset/contracts.py
platform/changeset/src/design_changeset/hashing.py
platform/changeset/src/design_changeset/builder.py
platform/changeset/src/changeset/model.py
platform/changeset/src/changeset/builder.py
platform/changeset/src/changeset/execution_slice.py
platform/changeset/src/changeset/execution_unit.py
platform/changeset/src/changeset/verification.py
pyproject.toml
tests/changeset/test_step29_step27_binding.py
tests/changeset/test_step29_contracts.py
tests/changeset/test_step29_hashing.py
tests/changeset/test_step29_builder.py
tests/changeset/test_step29_architecture.py
```

Deleted legacy paths must be accepted by the diff-boundary regex.

- [ ] **Step 2: Add focused and regression jobs**

Run in this order:

```bash
pytest -q tests/changeset/test_step29_step27_binding.py
pytest -q tests/changeset/test_step29_contracts.py
pytest -q tests/changeset/test_step29_hashing.py
pytest -q tests/changeset/test_step29_builder.py
pytest -q tests/changeset/test_step29_architecture.py
pytest -q tests/approval_scope
pytest -q tests/impact
pytest -q tests/orchestrator/test_step25_parameter_binder.py tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_step26_interactive_binding.py tests/interaction/test_step26_interaction_coordinator.py tests/interaction/test_step26_architecture.py
ruff check platform/changeset/src/design_changeset platform/impact/src/design_impact tests/changeset
pytest -q --import-mode=importlib
```

- [ ] **Step 3: Run fresh local/sandbox verification before claiming completion**

Run every command above in a repository-capable environment. If the current environment cannot clone GitHub, reproduce focused RED/GREEN locally only where trustworthy and treat GitHub Actions as the final repository truth.

- [ ] **Step 4: Inspect failures using systematic debugging**

Any test, lint, import, or full-suite failure blocks completion. Diagnose the root cause before changing code; do not weaken tests or diff guards to force green.

- [ ] **Step 5: Commit CI**

```bash
git add .github/workflows/step29-immutable-changeset.yml
git commit -m "ci: verify Step29 immutable changeset"
```

- [ ] **Step 6: Final diff-boundary review**

Compare the branch against `main@130d61072ab561ce3fb013433ceca3edd803c0e0` and verify no files outside this plan changed.

- [ ] **Step 7: Independent review request**

Request a code review on the completed PR. If the configured reviewer is unavailable or rate-limited, record that fact explicitly rather than claiming an independent review passed.

- [ ] **Step 8: Completion criteria**

Do not call Step29 complete until all of the following are evidenced at the same final head SHA:

```text
focused Step29 tests: PASS
Step28 regressions: PASS
Step27 regressions: PASS
Step25/26 relevant regressions: PASS
Ruff: PASS
full repository pytest: PASS (except pre-existing documented live-host skips)
architecture/diff boundary: PASS
```

---

## Plan Self-Review

### Spec coverage

- Package reclamation and legacy deletion: Tasks 2 and 7.
- Verifiable D6→Step27 join: Task 1.
- Provider-neutral Step23/D6 evidence: Tasks 2–4.
- Exactly one root operation: Tasks 2 and 4.
- Explicit derived materialization/completeness: Task 5.
- Explicit-entity scope membership and effect coverage: Task 4 and reused in Task 5.
- No create/delete bypass: Task 4/5 scope validation and architecture tests.
- Final Change DAG: Task 5.
- Preconditions, affected entities, semantic impacts, validation tasks: Task 6.
- Deterministic semantic hashing and opaque-id exclusion: Task 3 and Task 6.
- Step28 pure final binding: Task 6.
- Step30/31/32/33 ownership exclusions: Task 7.
- CI/full regressions: Task 8.

### Placeholder scan

The plan contains no TBD/TODO implementation placeholders. Every task names concrete files, interfaces, failing tests, implementation behavior, verification commands, and commit boundaries.

### Type/name consistency

The plan consistently uses `CanonicalChangeSet`, `ChangeSetBuildRequest`, `CanonicalOperationContractEvidence`, `BoundOperationEvidence`, `DerivedOperationMaterialization`, `ApprovalScopeDefinitionRef`, `OperationSourceEvidence`, and the existing Step27/Step28 field names `planning_snapshot_ref`, `snapshot_set_ref`, `semantic_environment_ref`, `analysis_fingerprint`, `scope_body_hash`.
