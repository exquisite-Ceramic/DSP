# Step 27 Impact Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral deterministic Impact Layer that consumes a fully bound canonical operation plus pinned planning-state refs and structured dependency/constraint evidence, and returns `ImpactAnalysis` with predicted impacts, deterministic propagation bundles, and an exception set without creating or executing a ChangeSet.

**Architecture:** Add a standalone `platform/impact/src/design_impact` package. `contracts.py` owns immutable/value-oriented Step27 DTOs and frozen enums; `rules.py` owns deterministic structured constraint evaluation and normalization helpers; `analyzer.py` validates pinned planning state, traverses only explicit dependency edges, classifies impacts, groups safe deterministic propagation, extracts exceptions, and computes a stable fingerprint. The package may depend on the platform D6 `BoundOperationProposal` contract but must not import Host/provider product packages, `HostCommand`, or `platform/changeset`.

**Tech Stack:** Python 3.11, dataclasses/enums, stdlib `hashlib`/`json`, pytest. No graph database and no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md`

## Global Constraints

- Keep Relationship Graph, Dependency Graph, Constraint/Invariant Graph, Change Impact Graph, and Change DAG conceptually distinct.
- `RelationshipEvidence` alone MUST NOT create a predicted impact.
- Dependency strength is exactly `HARD | SOFT | ADVISORY`.
- Propagation owner is exactly `HOST_NATIVE | SEMANTIC_RUNTIME | AGENT`.
- Propagation action is exactly `AUTO_MUTATE | RECOMPUTE | REVALIDATE | MARK_DIRTY | REPLAN | BLOCK`.
- `AUTO_MUTATE` in Step27 is planning metadata only; Step27 MUST NOT mutate Host/model state.
- `HOST_NATIVE` predicts and requires later verification; it MUST NOT create a platform mutation proposal.
- `AGENT` ownership MUST enter the Exception Set and MUST NOT be silently converted to deterministic propagation.
- A valid HARD constraint that evaluates `FAIL` creates a blocking exception; malformed/un-evaluable required rule input fails closed.
- `IntentBoundary` is machine-readable: direct targets, allowed canonical effects, and allowed derived rule refs.
- Impact output MUST bind exact PlanningSnapshot/SnapshotSet/SemanticEnvironment refs/hashes.
- `design_impact` MUST NOT import AutoCAD, Revit, Tekla, HostCommand, ChangeSetBuilder, ProviderBinding, or execution paths.
- Step27 MUST NOT implement ApprovalScopeBoundary, immutable ChangeSet, ExecutionSlice/ExecutionUnit, ProviderBinding, ExecutionGrant, Host mutation, graph database storage, or Change DAG execution planning.

---

## File Structure

Create:

```text
platform/impact/src/design_impact/__init__.py
platform/impact/src/design_impact/contracts.py
platform/impact/src/design_impact/rules.py
platform/impact/src/design_impact/analyzer.py

tests/impact/test_step27_contracts.py
tests/impact/test_step27_analyzer.py
tests/impact/test_step27_constraints.py
tests/impact/test_step27_architecture.py
tests/impact/test_step27_d6_integration.py

.github/workflows/step27-impact-layer.yml
```

Modify:

```text
pyproject.toml
```

Responsibilities:

- `contracts.py` — enums, snapshot/environment bindings, dependency/constraint evidence DTOs, intent boundary, predicted impact/bundle/exception/output DTOs, stable Step27 domain error.
- `rules.py` — deterministic constraint operators/evaluation and canonical normalization utilities used by fingerprinting/grouping.
- `analyzer.py` — pure deterministic analysis; no network, no Host calls, no persistence.
- `__init__.py` — narrow public API only.
- Step27 tests — RED/GREEN contract, analyzer, constraint, architecture, and D6 integration proof.
- Step27 workflow — exact changed-file boundary + focused tests + Step25/26 and semantic freshness regressions + relevant full Python regression.

---

### Task 1: Freeze Step27 contracts and package boundary

**Files:**
- Create: `tests/impact/test_step27_contracts.py`
- Create: `tests/impact/test_step27_architecture.py`
- Create: `platform/impact/src/design_impact/contracts.py`
- Create: `platform/impact/src/design_impact/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**

Produces these exact public names:

```python
class ImpactError(ValueError):
    code: str

class DependencyStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"

class PropagationOwner(str, Enum):
    HOST_NATIVE = "HOST_NATIVE"
    SEMANTIC_RUNTIME = "SEMANTIC_RUNTIME"
    AGENT = "AGENT"

class PropagationAction(str, Enum):
    AUTO_MUTATE = "AUTO_MUTATE"
    RECOMPUTE = "RECOMPUTE"
    REVALIDATE = "REVALIDATE"
    MARK_DIRTY = "MARK_DIRTY"
    REPLAN = "REPLAN"
    BLOCK = "BLOCK"

class ConstraintStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"

class ConstraintOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"
    IN = "IN"

class ConstraintOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
```

Planning-state reference DTOs:

```python
@dataclass(frozen=True, slots=True)
class SemanticEnvironmentBinding:
    environment_id: str
    content_hash: str

@dataclass(frozen=True, slots=True)
class PlanningSnapshotBinding:
    snapshot_id: str
    snapshot_hash: str
    document_ref: str
    semantic_environment: SemanticEnvironmentBinding

@dataclass(frozen=True, slots=True)
class SnapshotSetBinding:
    snapshot_set_id: str
    snapshot_set_hash: str
    member_snapshot_ids: tuple[str, ...]
    semantic_environment: SemanticEnvironmentBinding
```

Long-lived evidence / rules:

```python
@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    relationship_id: str
    source_semantic_id: str
    target_semantic_id: str
    relationship_type: str
    evidence_refs: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class DependencyEdge:
    dependency_id: str
    source_semantic_id: str
    target_semantic_id: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    rule_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ConstraintEvaluationSpec:
    fact_key: str
    operator: ConstraintOperator
    expected_value: object

@dataclass(frozen=True, slots=True)
class ConstraintRule:
    constraint_id: str
    applies_to: tuple[str, ...]
    strength: ConstraintStrength
    evaluation_spec: ConstraintEvaluationSpec
    evidence_refs: tuple[str, ...] = ()
```

Task input/output contracts:

```python
@dataclass(frozen=True, slots=True)
class IntentBoundary:
    direct_targets: tuple[str, ...]
    allowed_canonical_effects: tuple[str, ...] = ()
    allowed_derived_rule_refs: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class PredictedImpact:
    source_semantic_id: str
    affected_semantic_id: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    dependency_ref: str
    evidence_refs: tuple[str, ...]
    requires_verification: bool

@dataclass(frozen=True, slots=True)
class PropagationBundle:
    bundle_id: str
    rule_ref: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    source_entities: tuple[str, ...]
    affected_entities: tuple[str, ...]
    deterministic: bool
    proposed_changes: tuple[Mapping[str, object], ...]

@dataclass(frozen=True, slots=True)
class ImpactException:
    exception_id: str
    reason_code: str
    source_entities: tuple[str, ...]
    affected_entities: tuple[str, ...]
    strength: str
    propagation_owner: str
    requested_action: str
    blocking: bool
    evidence_refs: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ImpactAnalysis:
    analysis_id: str
    canonical_operation: str
    direct_targets: tuple[str, ...]
    planning_snapshot_ref: PlanningSnapshotBinding
    snapshot_set_ref: SnapshotSetBinding
    semantic_environment_ref: SemanticEnvironmentBinding
    predicted_impacts: tuple[PredictedImpact, ...]
    propagation_bundles: tuple[PropagationBundle, ...]
    exceptions: tuple[ImpactException, ...]
    analysis_fingerprint: str
```

- [ ] **Step 1: Write RED contract tests**

Add tests that import the exact public names above and assert:

```python
def test_frozen_dependency_vocabularies_reject_unknown_values():
    with pytest.raises(ValueError):
        DependencyStrength("CRITICAL")
    with pytest.raises(ValueError):
        PropagationOwner("PROVIDER")
    with pytest.raises(ValueError):
        PropagationAction("EXECUTE")


def test_relationship_is_not_dependency_type():
    relationship = RelationshipEvidence(
        relationship_id="REL-1",
        source_semantic_id="WALL-001",
        target_semantic_id="OPENING-001",
        relationship_type="HAS_OPENING",
    )
    assert not isinstance(relationship, DependencyEdge)
```

Also assert all id/ref tuples are normalized to immutable tuples, duplicate semantic ids are rejected where uniqueness is required, mappings in propagation proposed changes are defensively copied, and public DTO fields reject blank ids.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/impact/test_step27_contracts.py tests/impact/test_step27_architecture.py
```

Expected: collection fails with `ModuleNotFoundError: design_impact`.

- [ ] **Step 3: Implement minimal contracts and public exports**

Use `dataclass(frozen=True, slots=True)`, `Enum`, `deepcopy`, `MappingProxyType`, and small `_required_text` / unique tuple helpers. `ImpactError` constructor must be:

```python
class ImpactError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
```

Do not import Host or changeset modules.

- [ ] **Step 4: Add pytest path**

Append only:

```toml
"platform/impact/src",
```

to `[tool.pytest.ini_options].pythonpath` in root `pyproject.toml`.

- [ ] **Step 5: Run GREEN contract tests**

```bash
pytest -q tests/impact/test_step27_contracts.py tests/impact/test_step27_architecture.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 6: Commit**

Commit message:

```text
feat(step27): add impact layer contracts
```

---

### Task 2: Deterministic dependency traversal and predicted impact

**Files:**
- Create: `tests/impact/test_step27_analyzer.py`
- Create: `platform/impact/src/design_impact/analyzer.py`
- Modify: `platform/impact/src/design_impact/__init__.py`

**Interfaces:**

Consumes:

```python
from design_orchestrator.parameter_binder import BoundOperationProposal
```

Produces:

```python
@dataclass(frozen=True, slots=True)
class ImpactAnalysisRequest:
    bound_operation: BoundOperationProposal
    planning_snapshot_ref: PlanningSnapshotBinding
    snapshot_set_ref: SnapshotSetBinding
    semantic_environment_ref: SemanticEnvironmentBinding
    dependency_edges: tuple[DependencyEdge, ...] = ()
    constraint_rules: tuple[ConstraintRule, ...] = ()
    relationship_evidence: tuple[RelationshipEvidence, ...] = ()
    observed_facts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    intent_boundary: IntentBoundary = ...

class ImpactAnalyzer:
    def analyze(self, request: ImpactAnalysisRequest) -> ImpactAnalysis: ...
```

The analyzer extracts direct targets from `request.bound_operation.arguments["targets"]`. For Step27 MVP, missing/non-list-like targets must fail closed with `ImpactError("IMPACT_INPUT_INVALID", ...)`.

- [ ] **Step 1: Write RED analyzer tests**

Freeze the MOVE vertical:

```python
# direct target WALL-001
# explicit dependencies:
# HARD WALL-001 -> OPENING-001, HOST_NATIVE, REVALIDATE
# SOFT WALL-001 -> ANNOTATION-002, SEMANTIC_RUNTIME, RECOMPUTE, rule_ref="RULE-ANN"
# SOFT WALL-001 -> MEP-008, AGENT, REPLAN, rule_ref="RULE-MEP"
```

Tests must prove:

1. relationship evidence alone yields no predicted impact;
2. explicit dependency edges yield exactly the three predicted targets;
3. `HOST_NATIVE` sets `requires_verification=True`;
4. non-HOST_NATIVE impacts set `requires_verification=False` in the MVP;
5. edge ordering does not change predicted-impact ordering or final fingerprint;
6. analyzer never mutates the `BoundOperationProposal` arguments.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/impact/test_step27_analyzer.py
```

Expected: import failure for `ImpactAnalyzer` / `ImpactAnalysisRequest`.

- [ ] **Step 3: Implement request validation and dependency traversal**

Algorithm skeleton:

```python
def analyze(self, request):
    self._validate_bindings(request)
    direct_targets = self._direct_targets(request.bound_operation)
    edges = self._reachable_edges(direct_targets, request.dependency_edges)
    predicted = tuple(self._to_predicted(edge) for edge in edges)
    ...
```

For the MVP, traversal is deterministic breadth-first over explicit directional edges and may continue from newly affected targets. De-duplicate by `dependency_id`; normalize sort by `(source_semantic_id, target_semantic_id, dependency_id)` before output.

`RelationshipEvidence` is accepted for provenance only and MUST NOT be traversed.

- [ ] **Step 4: Implement planning-state binding validation**

Fail with structured codes:

```text
SNAPSHOT_MISMATCH
SEMANTIC_ENVIRONMENT_MISMATCH
IMPACT_INPUT_INVALID
DEPENDENCY_INVALID
```

Rules:

- `planning_snapshot_ref.snapshot_id` must be present in `snapshot_set_ref.member_snapshot_ids`;
- planning/snapshot-set/request semantic environment ids and content hashes must be identical;
- `intent_boundary.direct_targets` must equal the normalized direct targets from the bound operation;
- duplicate `dependency_id` values fail closed;
- a dependency with blank/malformed ids has already failed during DTO construction.

- [ ] **Step 5: Run GREEN analyzer tests**

```bash
pytest -q tests/impact/test_step27_contracts.py tests/impact/test_step27_analyzer.py tests/impact/test_step27_architecture.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```text
feat(step27): analyze explicit dependency impact
```

---

### Task 3: Constraint evaluation, propagation bundles, and exception-first review

**Files:**
- Create: `tests/impact/test_step27_constraints.py`
- Create: `platform/impact/src/design_impact/rules.py`
- Modify: `platform/impact/src/design_impact/analyzer.py`
- Modify: `platform/impact/src/design_impact/__init__.py`

**Interfaces:**

`rules.py` produces:

```python
def evaluate_constraint(
    rule: ConstraintRule,
    *,
    observed_facts: Mapping[str, Mapping[str, object]],
) -> tuple[ConstraintOutcome, tuple[str, ...]]:
    ...
```

The returned entity tuple is the applicable entity set that was evaluated.

Operator semantics:

```text
EQ: actual == expected
NE: actual != expected
GT: actual > expected
GE: actual >= expected
LT: actual < expected
LE: actual <= expected
IN: actual in expected_collection
```

Missing `fact_key` for an entity to which a required rule applies is invalid evidence/input and raises `ImpactError("CONSTRAINT_INVALID", ...)`; it is not `NOT_APPLICABLE`. `NOT_APPLICABLE` means none of `rule.applies_to` are in the current direct/predicted affected set.

- [ ] **Step 1: Write RED constraint tests**

Cover:

```python
HARD valid rule + PASS -> no exception
HARD valid rule + FAIL -> blocking HARD_CONSTRAINT_FAILED exception
SOFT valid rule + FAIL -> non-blocking CONSTRAINT_REVIEW_REQUIRED exception
ADVISORY valid rule + FAIL -> non-blocking ADVISORY_CONSTRAINT exception
missing required fact -> ImpactError.code == "CONSTRAINT_INVALID"
invalid comparison types -> ImpactError.code == "CONSTRAINT_INVALID"
```

- [ ] **Step 2: Write RED propagation/exception tests**

Freeze these behaviors:

```text
SEMANTIC_RUNTIME + RECOMPUTE + same rule_ref
→ one deterministic PropagationBundle

SEMANTIC_RUNTIME + AUTO_MUTATE + allowed rule_ref
→ one planning-only PropagationBundle with canonical proposed_changes metadata

HOST_NATIVE
→ predicted impact only, no PropagationBundle

AGENT or REPLAN
→ ImpactException(reason_code="REPLAN_REQUIRED")

BLOCK
→ blocking ImpactException(reason_code="PROPAGATION_BLOCKED")

target outside intent boundary and rule_ref not in allowed_derived_rule_refs
→ ImpactException(reason_code="INTENT_SCOPE_EXPANSION")
```

`proposed_changes` for deterministic bundles must stay canonical and generic, for example:

```python
{
    "affected_semantic_id": "ANNOTATION-002",
    "action": "RECOMPUTE",
    "rule_ref": "RULE-ANN",
}
```

No Host/provider/native field may appear.

- [ ] **Step 3: Verify RED**

```bash
pytest -q tests/impact/test_step27_constraints.py tests/impact/test_step27_analyzer.py
```

Expected: failures for missing rule evaluator/bundling/exception behavior.

- [ ] **Step 4: Implement structured constraint evaluation**

Implement only the seven frozen operators. Catch `TypeError` from incompatible ordered comparisons and convert to `ImpactError("CONSTRAINT_INVALID", ...)`.

- [ ] **Step 5: Implement deterministic propagation grouping**

Bundle only when all are true:

```text
owner == SEMANTIC_RUNTIME
and action in {AUTO_MUTATE, RECOMPUTE, REVALIDATE, MARK_DIRTY}
and rule_ref is non-empty
and rule_ref is allowed by IntentBoundary.allowed_derived_rule_refs
```

Group key:

```python
(strength.value, owner.value, action.value, rule_ref)
```

Sort source/affected entities and generate stable `bundle_id` from a SHA-256 digest of the normalized group payload.

- [ ] **Step 6: Implement exception extraction**

Minimum reason codes:

```text
REPLAN_REQUIRED
PROPAGATION_BLOCKED
INTENT_SCOPE_EXPANSION
HARD_CONSTRAINT_FAILED
CONSTRAINT_REVIEW_REQUIRED
ADVISORY_CONSTRAINT
```

Generate stable `exception_id` from normalized reason/source/affected/rule evidence. Multiple independent reasons may produce separate exceptions; identical normalized exceptions de-duplicate.

- [ ] **Step 7: Run GREEN focused suite**

```bash
pytest -q tests/impact/test_step27_contracts.py tests/impact/test_step27_analyzer.py tests/impact/test_step27_constraints.py tests/impact/test_step27_architecture.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```text
feat(step27): classify propagation and impact exceptions
```

---

### Task 4: Stable fingerprint and D6/PlanningSnapshot integration proof

**Files:**
- Create: `tests/impact/test_step27_d6_integration.py`
- Modify: `platform/impact/src/design_impact/analyzer.py`
- Modify: `platform/impact/src/design_impact/rules.py`

**Interfaces:**

Add internal canonical serialization helper:

```python
def canonical_json_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
```

`analysis_fingerprint` must bind at least:

```text
canonical operation id/version
material bound canonical arguments
direct targets
PlanningSnapshot id/hash/document
SnapshotSet id/hash/member ids
SemanticEnvironment id/hash
normalized dependency edges
normalized constraint rules
IntentBoundary
```

`analysis_id = "IA-" + analysis_fingerprint[:12]`.

- [ ] **Step 1: Write integration RED tests using the real Step25 D6 DTO**

Construct a real `BoundOperationProposal` with:

```python
CanonicalOperationRef("move.v1", "1.0.0")
arguments={"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]}
```

and valid Step25 evidence/context/planning requirements.

Prove:

1. identical semantic request in different dependency/rule input ordering yields identical `analysis_fingerprint`;
2. changing displacement changes fingerprint;
3. changing direct target changes fingerprint;
4. changing planning snapshot hash changes fingerprint;
5. changing snapshot-set hash changes fingerprint;
6. changing semantic environment hash changes fingerprint;
7. output canonical operation remains `move.v1`;
8. output contains no provider/native execution metadata.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/impact/test_step27_d6_integration.py
```

Expected: fingerprint assertions fail until normalized hashing is complete.

- [ ] **Step 3: Implement normalized fingerprint payload**

Do not hash `repr(dataclass)` or memory-order-dependent mappings. Serialize explicit primitive payloads only.

- [ ] **Step 4: Add fail-closed environment/snapshot mismatch tests**

Assertions:

```python
with pytest.raises(ImpactError) as exc:
    analyzer.analyze(request_with_mixed_environment)
assert exc.value.code == "SEMANTIC_ENVIRONMENT_MISMATCH"

with pytest.raises(ImpactError) as exc:
    analyzer.analyze(request_with_snapshot_not_in_set)
assert exc.value.code == "SNAPSHOT_MISMATCH"
```

- [ ] **Step 5: Run GREEN integration suite**

```bash
pytest -q tests/impact/test_step27_d6_integration.py tests/impact/test_step27_analyzer.py tests/impact/test_step27_constraints.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```text
test(step27): prove D6 to impact analysis binding
```

---

### Task 5: CI boundary, prior-step regressions, and closeout

**Files:**
- Create: `.github/workflows/step27-impact-layer.yml`
- Modify only if required by discovered real regression: existing test/workflow files directly affected by the new `platform/impact` path. Do not broaden production scope.

**Interfaces:**

The workflow must install the same stack needed for Step23–26/semantic-runtime tests and run Step27 without importing `platform/changeset` as an implementation dependency.

- [ ] **Step 1: Add exact Step27 diff guard**

Allowed paths at first freeze:

```text
.github/workflows/step27-impact-layer.yml
docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md
docs/superpowers/plans/2026-08-29-step27-impact-layer.md
platform/impact/src/design_impact/__init__.py
platform/impact/src/design_impact/contracts.py
platform/impact/src/design_impact/rules.py
platform/impact/src/design_impact/analyzer.py
pyproject.toml
tests/impact/test_step27_contracts.py
tests/impact/test_step27_analyzer.py
tests/impact/test_step27_constraints.py
tests/impact/test_step27_architecture.py
tests/impact/test_step27_d6_integration.py
```

If a legitimate existing caller/CI test requires compatibility migration, add that exact file deliberately rather than weakening the regex to a whole directory.

- [ ] **Step 2: Add architecture guards**

Source-level/import guards must assert `platform/impact/src/design_impact` contains none of:

```text
AutoCAD
Revit
Tekla
HostCommand
ChangeSetBuilder
ProviderBinding
ExecutionGrant
platform.changeset
from changeset
import changeset
```

Also assert no public Step27 contract field name includes provider-native ids such as `handle`, `element_id`, `provider_tool`, or `native_id`.

- [ ] **Step 3: Add focused workflow steps**

Run in this order:

```bash
pytest -q tests/impact/test_step27_contracts.py
pytest -q tests/impact/test_step27_architecture.py
pytest -q tests/impact/test_step27_analyzer.py
pytest -q tests/impact/test_step27_constraints.py
pytest -q tests/impact/test_step27_d6_integration.py
```

- [ ] **Step 4: Run prior-step regressions**

At minimum:

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_step26_interactive_binding.py
pytest -q tests/interaction/test_step26_interaction_coordinator.py tests/interaction/test_step26_architecture.py
pytest -q tests/orchestrator/test_step24_semantic_eligibility.py tests/orchestrator/test_operation_resolver.py
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
```

- [ ] **Step 5: Run relevant full Python regression**

Use the same importlib mode that proved stable in Step26:

```bash
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/interaction \
  tests/impact \
  tests/semantic_runtime
```

- [ ] **Step 6: Create/update Draft PR and verify final head only**

The PR body must state:

```text
Step27 owns deterministic ImpactAnalysis only.
No ApprovalScopeBoundary, ChangeSet, execution planning, ProviderBinding, ExecutionGrant, or Host mutation is implemented.
```

Final completion evidence must be attached to one exact final head SHA. Historical RED commits are expected to show failed checks and are not final quality evidence.

- [ ] **Step 7: Review final diff against spec**

Checklist:

```text
Relationship != Dependency preserved
explicit dependency traversal only
constraints deterministic
HOST_NATIVE prediction only
SEMANTIC_RUNTIME deterministic bundles only
AGENT -> exception
BLOCK -> blocking exception
intent-scope expansion -> exception
snapshot/environment bound
stable fingerprint
no Host/native ids
no changeset/execution implementation
```

- [ ] **Step 8: Commit CI/closeout changes**

```text
ci(step27): verify deterministic impact layer
```
