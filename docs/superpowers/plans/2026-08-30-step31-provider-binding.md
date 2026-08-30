# Step 31 Provider Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic immutable Step31 late binding from an exact Step30 `ExecutionSlice` plus exact slice-scoped provider/native evidence into exactly one `ProviderBinding` per `ExecutionUnit` and one authorization-relevant `ProviderBindingSet` / `binding_set_hash` per Slice, without changing canonical semantics or performing Host execution.

**Architecture:** Step31 is a separate `design_provider_binding` package. It consumes only immutable Step30 execution contracts plus a caller-assembled `ProviderExecutionSnapshot`, validates closed-world native identity and provider-candidate evidence, deterministically selects one provider candidate per Unit, invokes an injected provider-specific `ProviderBindingAdapter`, validates returned native material, and computes canonical SHA-256 binding identities. Step31 never live-queries Host/provider services, never falls back after Adapter failure, never emits `ExecutionGrant`/`HostCommand`, and never branches on Host-specific types.

**Tech Stack:** Python 3.11, frozen dataclasses, `MappingProxyType`, `typing.Protocol`, Step29 `canonical_hash`, `jsonschema>=4.20`, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md`

## Global Constraints

- Base: `main@69dbe0886c7a2fe497ed58bf3b82676007a667dd`; branch: `feat/step31-provider-binding`.
- Distribution: `design-provider-binding`; source package: `design_provider_binding`.
- Step31 consumes Step30 `ExecutionSlice`, `ExecutionUnit`, and `HostRuntimeRef` as immutable upstream truth.
- v1 invariant: `1 ExecutionUnit = exactly 1 ProviderBinding`.
- v1 invariant: `1 ExecutionSlice = exactly 1 ProviderExecutionSnapshot + exactly 1 ProviderBindingSet`.
- Step31 MUST NOT split/merge/rewrite/reorder canonical Units or alter canonical operation, targets, arguments, expected effects, preconditions, or approved scope.
- Step31 MUST NOT live-query D3, HostBinding storage, Host sidecars, MCP sessions, health/license/certification services, policy engines, or Host APIs during resolution.
- `ProviderExecutionSnapshot` is slice-scoped immutable evidence assembled outside the deterministic resolver.
- Snapshot native bindings are closed-world for the union of Slice Unit targets: missing/conflicting/extraneous rows fail closed.
- `host_instance_id` belongs to Step30 `HostRuntimeRef`; persistent native binding evidence carries semantic id + host type + document + native id + native kind + fingerprint.
- Provider-native constraints are v1 declarative `native_kind EQ/IN` predicates only; generic Step31 compares opaque strings and contains no Host ontology.
- Candidate eligibility uses canonical operation/version, native constraints, trust, compatibility, health, license, and certification evidence; policy preference is already projected into deterministic integer `policy_priority`.
- Candidate winner ordering is `(policy_priority, provider_server, provider_tool, provider_version)` ascending.
- Same ranking identity among eligible candidates is ambiguous whether fingerprints are equal or different; do not use candidate fingerprint as a winner tie-breaker.
- After a winner is selected, Adapter failure MUST NOT fall back to the next candidate.
- Adapter registry is keyed by `provider_server`; generic Step31 contains no `if host_type == "AUTOCAD"/"REVIT"/...` branch and no dynamic Host-package imports.
- Adapter output can contain native targets, provider arguments, optional provider-native enforcement projections, and opaque execution-semantic metadata only.
- Optional provider-native preconditions may reference only real unique Step30 precondition fingerprints; complete translation of all Step30 planning preconditions is NOT required.
- Provider arguments MUST validate against selected candidate `provider_input_schema`.
- `binding_expires_at = snapshot.valid_until` in v1.
- `binding_hash` excludes construction id and snapshot id/hash; it binds exact selected provider/native execution material and expiry.
- `binding_set_hash = SHA256({execution_slice_hash, sorted(full 64-hex binding_hashes)})` and MUST NOT use `PB-<12-char>` construction ids as semantic material.
- `ProviderBindingSet` carries snapshot id/hash as provenance only; snapshot provenance is not authorization hash material.
- Changing an unused candidate may change snapshot hash but MUST NOT change binding/set hash when winner/native material/contracts/expiry are unchanged.
- Provider switch MUST leave Step29/30 ChangeSet/Unit/Slice hashes unchanged and change ProviderBinding/binding-set hashes.
- `admission_time` is explicit UTC input used only for expiry admission; resolver code MUST NOT read wall clock time.
- Step31 MUST NOT create/read approval IDs, `ApprovalRecord`, `ExecutionGrant`, `HostCommand`, dispatch/retry/idempotency state, ActualDelta, verification result, rollback execution, or Saga state.
- No production Step31 code changes outside `platform/provider_binding/`; root `pyproject.toml` only receives the Step31 pytest path. Tests live under `tests/provider_binding/`. CI lives in `.github/workflows/step31-provider-binding.yml`.

## Stable Step31 Error Codes

```text
PROVIDER_BINDING_INPUT_INVALID

PROVIDER_SLICE_MISMATCH
PROVIDER_SNAPSHOT_HASH_MISMATCH
PROVIDER_SNAPSHOT_EXPIRED

PROVIDER_NATIVE_BINDING_UNRESOLVED
PROVIDER_NATIVE_BINDING_CONFLICT
PROVIDER_NATIVE_BINDING_EXTRANEOUS

PROVIDER_CANDIDATE_INVALID
PROVIDER_CANDIDATE_UNAVAILABLE
PROVIDER_CANDIDATE_AMBIGUOUS
PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED

PROVIDER_ADAPTER_UNAVAILABLE
PROVIDER_ADAPTER_CONFLICT
PROVIDER_BINDING_ADAPTATION_FAILED

PROVIDER_NATIVE_TARGET_MISMATCH
PROVIDER_INPUT_SCHEMA_INVALID

PROVIDER_BINDING_HASH_MISMATCH
PROVIDER_BINDING_SET_INVALID
```

## File Map

### Production

- `platform/provider_binding/pyproject.toml` — package metadata and external `jsonschema` dependency.
- `platform/provider_binding/src/design_provider_binding/contracts.py` — frozen public DTOs, enums, normalization, UTC timestamp parsing, domain error.
- `platform/provider_binding/src/design_provider_binding/hashing.py` — HostBinding/candidate/snapshot/precondition/binding/set canonical hash helpers and public validation helpers.
- `platform/provider_binding/src/design_provider_binding/adapters.py` — Adapter Protocol, registry, v1 native-constraint evaluation.
- `platform/provider_binding/src/design_provider_binding/resolver.py` — snapshot integrity, candidate validation/filtering/ranking, Adapter invocation, binding/set construction.
- `platform/provider_binding/src/design_provider_binding/__init__.py` — public Step31 API.
- `pyproject.toml` — add `platform/provider_binding/src` to pytest `pythonpath`.

### Tests

- `tests/provider_binding/conftest.py` — real Step30 DTO/hash fixtures and deterministic fake Adapters.
- `tests/provider_binding/test_step31_contracts.py`
- `tests/provider_binding/test_step31_hashing.py`
- `tests/provider_binding/test_step31_adapters.py`
- `tests/provider_binding/test_step31_snapshot_and_selection.py`
- `tests/provider_binding/test_step31_resolver.py`
- `tests/provider_binding/test_step31_binding_set.py`
- `tests/provider_binding/test_step31_architecture.py`

### CI / docs

- `.github/workflows/step31-provider-binding.yml`
- `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md` — only final status line changes after all final verification gates pass.
- `docs/superpowers/plans/2026-08-30-step31-provider-binding.md` — this plan.

---

### Task 1: Package shell, immutable contracts, Step30 boundary fixtures

**Files:**
- Create: `platform/provider_binding/pyproject.toml`
- Create: `platform/provider_binding/src/design_provider_binding/contracts.py`
- Create: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/provider_binding/conftest.py`
- Create: `tests/provider_binding/test_step31_contracts.py`
- Create: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: `design_execution_planning.ExecutionSlice`, `ExecutionUnit`, `HostRuntimeRef`; `design_changeset.ChangePrecondition` through the Step30 Unit type.
- Produces: `ProviderBindingError`, `EligibilityState`, `NativeConstraintOperator`, `NativeConstraint`, `NativeTargetBindingEvidence`, `ProviderExecutionCandidate`, `ProviderExecutionSnapshot`, `ProviderPreconditionBinding`, `ProviderBindingMaterial`, `ProviderBinding`, `ProviderBindingSet`, `ProviderBindingRequest`.
- `ProviderResolver`, Adapter registry, and hash helpers are NOT exported in Task 1.

- [ ] **Step 1: Create the Step31 RED workflow and failing contract tests before the package exists**

Create `.github/workflows/step31-provider-binding.yml` initially with the following focused harness. Do not install `platform/provider_binding` yet, because the expected RED is the missing package import rather than pip installation failure:

```yaml
name: Step31 provider binding

on:
  push:
    paths:
      - "platform/provider_binding/**"
      - "tests/provider_binding/**"
      - "pyproject.toml"
      - "docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md"
      - "docs/superpowers/plans/2026-08-30-step31-provider-binding.md"
      - ".github/workflows/step31-provider-binding.yml"
  pull_request:
    paths:
      - "platform/provider_binding/**"
      - "tests/provider_binding/**"
      - "pyproject.toml"
      - "docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md"
      - "docs/superpowers/plans/2026-08-30-step31-provider-binding.md"
      - ".github/workflows/step31-provider-binding.yml"
  workflow_dispatch:

jobs:
  step31-provider-binding:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Step31 RED prerequisites
        run: |
          python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3 ruff
          python -m pip install \
            -e contracts/python \
            -e hosts/autocad/sidecar \
            -e platform/changeset \
            -e platform/execution_planning \
            -e platform/semantic_runtime \
            -e platform/semantic_service \
            -e platform/semantic_mcp \
            -e providers/semantics/dsp_core \
            -e providers/semantics/ifc43 \
            -e providers/semantics/metro_v32 \
            -e providers/semantics/enterprise_mapping
      - name: Run Step31 contract tests
        run: pytest -q tests/provider_binding/test_step31_contracts.py
```

Write contract tests that import the package and freeze the public shape:

```python
from dataclasses import FrozenInstanceError, fields

import pytest


def test_provider_binding_request_has_no_provider_choice_or_grant_fields():
    from design_provider_binding import ProviderBindingRequest

    names = {field.name for field in fields(ProviderBindingRequest)}
    assert names == {"execution_slice", "provider_execution_snapshot", "admission_time"}
    assert {"provider_server", "provider_tool", "approval_id", "execution_grant"}.isdisjoint(names)


def test_provider_binding_has_no_host_command_or_approval_fields():
    from design_provider_binding import ProviderBinding

    names = {field.name for field in fields(ProviderBinding)}
    assert {"command_id", "idempotency_key", "approval_id", "execution_grant"}.isdisjoint(names)


def test_native_constraint_normalizes_in_values():
    from design_provider_binding import NativeConstraint, NativeConstraintOperator

    constraint = NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Wall", "Wall", "Door"))
    assert constraint.values == ("Door", "Wall")


def test_binding_set_is_frozen(valid_binding_set):
    with pytest.raises(FrozenInstanceError):
        valid_binding_set.binding_set_id = "PBS-other"
```

Also test:

- only `native_kind` is accepted as `NativeConstraint.field`;
- `EQ` requires exactly one value; `IN` requires at least one;
- digest fields accept only lowercase 64-hex;
- `policy_priority` is an integer `>= 0` and rejects booleans;
- candidate state fields normalize to `EligibilityState`;
- mapping fields are defensively copied and exposed through read-only outer mappings;
- tuple fields reject wrong member types;
- UTC timestamps accept `...Z` and `+00:00`, normalize to `Z`, and reject naive/non-UTC offsets;
- `ProviderBindingRequest.admission_time` is normalized the same way;
- `ProviderBindingMaterial.provider_preconditions` may be empty;
- `ProviderBindingSet.bindings` requires at least one binding.

- [ ] **Step 2: Add a real Step30-contract fixture without reconstructing Step29**

In `tests/provider_binding/conftest.py`, use actual Step30 DTOs and Step30 hash helpers. Do not define fake Unit/Slice classes.

Use this structure:

```python
from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import CanonicalAspect
from design_changeset import ChangePrecondition, PreconditionKind, canonical_hash
from design_execution_planning import (
    ApprovedExecutionScopeRef,
    ExecutionSlice,
    ExecutionUnit,
    HostRuntimeRef,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
)


def digest(label: str) -> str:
    return canonical_hash({"step31_fixture": label})


def build_execution_slice() -> ExecutionSlice:
    changeset_hash = digest("changeset")
    definition_hash = digest("move-definition")
    preconditions = (
        ChangePrecondition(PreconditionKind.OPERATION_FRESHNESS, "move.v1", digest("freshness")),
        ChangePrecondition(PreconditionKind.COVERAGE, "move.v1", digest("coverage")),
    )

    def unit(source: str, target: str) -> ExecutionUnit:
        source_hash = digest(source)
        arguments = {"displacement": [100.0, 0.0, 0.0]}
        unit_hash = compute_execution_unit_hash(
            changeset_hash=changeset_hash,
            source_operation_hash=source_hash,
            canonical_operation="move.v1",
            canonical_operation_version="1.0.0",
            canonical_definition_fingerprint=definition_hash,
            targets=(target,),
            arguments=arguments,
            preconditions=preconditions,
            expected_effects=(CanonicalAspect.PLACEMENT,),
        )
        return ExecutionUnit(
            f"EU-{unit_hash[:12]}",
            f"COP-{source_hash[:12]}",
            source_hash,
            "move.v1",
            "1.0.0",
            definition_hash,
            (target,),
            arguments,
            preconditions,
            (CanonicalAspect.PLACEMENT,),
            unit_hash,
        )

    units = (unit("operation-wall", "WALL-001"), unit("operation-annotation", "ANNOTATION-002"))
    host_ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    scope_ref = ApprovedExecutionScopeRef("SCOPE-31", digest("scope"), "SLICE-SCOPE-31")
    slice_hash = compute_execution_slice_hash(
        changeset_hash=changeset_hash,
        scope_hash=scope_ref.scope_hash,
        execution_slice_scope_rule_id=scope_ref.execution_slice_scope_rule_id,
        host_runtime_ref=host_ref,
        execution_unit_hashes=(item.execution_unit_hash for item in units),
    )
    return ExecutionSlice(
        f"XS-{slice_hash[:12]}",
        "CS-31",
        changeset_hash,
        host_ref,
        scope_ref,
        units,
        slice_hash,
    )


@pytest.fixture
def execution_slice():
    return build_execution_slice()
```

`valid_binding_set` may initially be a contract-only fixture assembled from already-valid 64-hex placeholders; later tasks SHALL replace it with a resolver-produced fixture so final tests never rely on fake semantic hashes.

- [ ] **Step 3: Run RED**

Run locally when an isolated worktree is available:

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

For connector-only execution, push the test/workflow commit and inspect the Step31 run.

Expected RED: collection/import fails specifically because `design_provider_binding` does not exist. Existing Step30 imports/fixture construction must not fail first.

- [ ] **Step 4: Implement the package shell and exact frozen contracts**

Create `platform/provider_binding/pyproject.toml`:

```toml
[project]
name = "design-provider-binding"
version = "0.1.0"
description = "Deterministic immutable provider/native binding contracts for DSP."
requires-python = ">=3.11"
dependencies = ["jsonschema>=4.20"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add to root pytest `pythonpath` immediately after `platform/execution_planning/src`:

```toml
"platform/provider_binding/src",
```

In `contracts.py`, define:

```python
class ProviderBindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class EligibilityState(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


class NativeConstraintOperator(str, Enum):
    EQ = "EQ"
    IN = "IN"
```

Frozen dataclasses and exact fields:

```python
NativeConstraint(field, operator, values)
NativeTargetBindingEvidence(semantic_id, host_type, document_ref, native_id, native_kind, host_binding_fingerprint)
ProviderExecutionCandidate(
    provider_server, provider_tool, provider_version,
    canonical_operation, compatible_operation_versions,
    input_adapter_version,
    provider_native_constraints, provider_input_schema,
    verification_contract, rollback_contract,
    trust_state, compatibility_state, health_state, license_state, certification_state,
    policy_priority, candidate_fingerprint,
)
ProviderExecutionSnapshot(
    snapshot_id, execution_slice_id, execution_slice_hash, host_runtime_ref,
    native_target_bindings, provider_candidates, valid_until, snapshot_hash,
)
ProviderPreconditionBinding(source_precondition_fingerprint, provider_precondition)
ProviderBindingMaterial(native_targets, provider_arguments, provider_preconditions, native_binding_metadata)
ProviderBinding(
    binding_id,
    execution_unit_id, execution_unit_hash,
    execution_slice_id, execution_slice_hash,
    canonical_operation,
    provider_server, provider_tool, provider_version, selected_candidate_fingerprint,
    host_instance_id, document_ref, input_adapter_version,
    native_targets, provider_arguments, provider_preconditions, native_binding_metadata,
    verification_contract, rollback_contract,
    binding_expires_at, binding_hash,
)
ProviderBindingSet(
    binding_set_id, execution_slice_id, execution_slice_hash,
    provider_execution_snapshot_id, provider_execution_snapshot_hash,
    bindings, binding_set_hash,
)
ProviderBindingRequest(execution_slice, provider_execution_snapshot, admission_time)
```

Use `deepcopy(dict(value))` + `MappingProxyType` for mapping fields, matching current Step29/30 defensive-copy convention. Do not implement recursive immutable mapping types in Step31.

Timestamp helper behavior must be exact:

```python
def _utc_timestamp(value: object, field_name: str) -> str:
    raw = _text(value, field_name)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be RFC3339 UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be RFC3339 UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
```

Do not accept arbitrary constraint fields. `NativeConstraint.__post_init__` requires `field == "native_kind"`; `EQ` has exactly one normalized value; `IN` has at least one normalized unique sorted value.

- [ ] **Step 5: Export only contracts in Task 1**

`design_provider_binding.__all__` includes the domain error, enums, and DTO names above. It does not mention `ProviderResolver`, `ProviderBindingAdapter`, registry, or hash helpers yet.

- [ ] **Step 6: Update the workflow install step and run GREEN**

Rename the install step to `Install Step31 verification stack` and add:

```bash
-e platform/provider_binding \
```

after `-e platform/execution_planning`.

Run:

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

Expected: all contract tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  platform/provider_binding \
  tests/provider_binding/conftest.py \
  tests/provider_binding/test_step31_contracts.py \
  pyproject.toml \
  .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add immutable provider binding contracts"
```

---

### Task 2: Deterministic semantic hashing and supplied-hash validation

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/hashing.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_hashing.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Task 1 DTOs, Step29 public `design_changeset.canonical_hash`, Step30 `HostRuntimeRef` and `ChangePrecondition` values contained by Units.
- Produces: `compute_host_binding_fingerprint`, `compute_candidate_fingerprint`, `compute_provider_snapshot_hash`, `compute_precondition_fingerprint`, `compute_binding_hash`, `compute_binding_set_hash`, `validate_provider_binding`, `validate_provider_binding_set_hash`.

- [ ] **Step 1: Write hashing RED tests and add a workflow test step**

Add to workflow:

```yaml
      - name: Run Step31 hashing tests
        run: pytest -q tests/provider_binding/test_step31_hashing.py
```

Write tests that import the not-yet-created helpers and prove:

```python
def test_host_binding_fingerprint_is_order_stable(native_binding):
    from design_provider_binding import compute_host_binding_fingerprint

    assert compute_host_binding_fingerprint(native_binding) == native_binding.host_binding_fingerprint


def test_binding_set_hash_uses_full_binding_hashes(execution_slice, binding_a, binding_b):
    from design_provider_binding import compute_binding_set_hash

    full = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding_a.binding_hash, binding_b.binding_hash),
    )
    prefixes = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding_a.binding_id, binding_b.binding_id),
    )
    assert full != prefixes
```

Also test:

- candidate fingerprint changes when any selected semantic field changes;
- candidate constraint/input-schema ordering normalizes deterministically;
- snapshot hash is invariant to native-binding/candidate collection ordering but preserves row multiplicity;
- snapshot id is excluded from snapshot hash;
- precondition fingerprint binds kind/subject/evidence exactly;
- binding hash is invariant to native-target/provider-precondition ordering;
- binding hash changes when provider server/tool/version/candidate fingerprint/adapter version/host instance/document/native identity/provider arguments/provider-native preconditions/native metadata/verification/rollback/expiry changes;
- binding hash does not accept snapshot id/hash as inputs;
- binding set hash is invariant to binding ordering and changes when any full binding hash changes;
- `validate_provider_binding` rejects mismatched `binding_hash` or `binding_id` with `PROVIDER_BINDING_HASH_MISMATCH`;
- `validate_provider_binding_set_hash` rejects mismatched set hash/id with `PROVIDER_BINDING_SET_INVALID`.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_hashing.py
```

Expected: import failure for `design_provider_binding.hashing` / missing public hash helpers; Task 1 contracts remain green.

- [ ] **Step 3: Implement canonical payload helpers using Step29 `canonical_hash`**

Do not copy a second JSON encoder. Import:

```python
from design_changeset import ChangePrecondition, canonical_hash
```

Use exact payloads:

```python
def compute_host_binding_fingerprint(value: NativeTargetBindingEvidence) -> str:
    return canonical_hash({
        "semantic_id": value.semantic_id,
        "host_type": value.host_type,
        "document_ref": value.document_ref,
        "native_id": value.native_id,
        "native_kind": value.native_kind,
    })
```

Candidate payload includes every field frozen by the spec; normalize compatible versions and constraints. Constraint payload shape:

```python
{
    "field": constraint.field,
    "operator": constraint.operator.value,
    "values": list(constraint.values),
}
```

Snapshot hash payload:

```python
{
    "execution_slice_hash": snapshot.execution_slice_hash,
    "host_runtime_ref": {
        "host_type": snapshot.host_runtime_ref.host_type,
        "host_instance_id": snapshot.host_runtime_ref.host_instance_id,
        "document_ref": snapshot.host_runtime_ref.document_ref,
    },
    "native_target_bindings": sorted(full_native_binding_payloads, key=...),
    "provider_candidate_fingerprints": sorted(candidate.candidate_fingerprint for candidate in snapshot.provider_candidates),
    "valid_until": snapshot.valid_until,
}
```

Use sorted lists, not sets, so duplicate rows remain observable and can be rejected by validation.

Precondition fingerprint:

```python
canonical_hash({
    "kind": precondition.kind.value,
    "subject_ref": precondition.subject_ref,
    "evidence_ref": precondition.evidence_ref,
})
```

Binding hash payload is exactly spec §16.3 and excludes `binding_id`, snapshot id, and snapshot hash.

Normalize provider preconditions by `(source_precondition_fingerprint, canonical_hash(provider_precondition))` and native targets by full persistent binding identity.

Binding-set hash payload is exactly:

```python
canonical_hash({
    "execution_slice_hash": execution_slice_hash,
    "binding_hashes": sorted(binding_hashes),
})
```

Do not deduplicate the input list inside the hash helper; structural duplicate detection belongs to BindingSet validation.

- [ ] **Step 4: Implement public supplied-hash validators**

```python
def validate_provider_binding(binding: ProviderBinding) -> None:
    expected = compute_binding_hash(...all binding semantic fields...)
    if binding.binding_hash != expected or binding.binding_id != f"PB-{expected[:12]}":
        raise ProviderBindingError("PROVIDER_BINDING_HASH_MISMATCH", "provider binding hash/id mismatch")


def validate_provider_binding_set_hash(binding_set: ProviderBindingSet) -> None:
    expected = compute_binding_set_hash(
        execution_slice_hash=binding_set.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in binding_set.bindings),
    )
    if binding_set.binding_set_hash != expected or binding_set.binding_set_id != f"PBS-{expected[:12]}":
        raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "provider binding set hash/id mismatch")
```

These validators do not yet check exact Slice Unit coverage; Task 6 adds structural set validation.

- [ ] **Step 5: Export hash helpers and run GREEN**

Update `__init__.py`, then run:

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
```

Expected: both groups pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add platform/provider_binding/src/design_provider_binding tests/provider_binding/test_step31_hashing.py .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add deterministic provider binding hashes"
```

---

### Task 3: Native-constraint evaluator and Adapter registry

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/adapters.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_adapters.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Task 1 DTOs and domain error.
- Produces: `ProviderBindingAdapter` Protocol, `ProviderBindingAdapterRegistry`, `native_constraints_satisfied`, `validate_native_constraints`.
- Registry key is only `provider_server`; expected Adapter version is the selected candidate `input_adapter_version`.

- [ ] **Step 1: Add RED adapter tests and workflow step**

Add:

```yaml
      - name: Run Step31 adapter tests
        run: pytest -q tests/provider_binding/test_step31_adapters.py
```

Tests must include:

```python
def test_eq_and_in_native_constraints_are_generic(native_wall_binding):
    from design_provider_binding import (
        NativeConstraint,
        NativeConstraintOperator,
        native_constraints_satisfied,
    )

    assert native_constraints_satisfied(
        (NativeConstraint("native_kind", NativeConstraintOperator.EQ, ("Wall",)),),
        (native_wall_binding,),
    )
    assert native_constraints_satisfied(
        (NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Wall", "Door")),),
        (native_wall_binding,),
    )


def test_registry_rejects_conflicting_adapter(fake_adapter, alternate_fake_adapter):
    from design_provider_binding import ProviderBindingAdapterRegistry, ProviderBindingError

    registry = ProviderBindingAdapterRegistry()
    registry.register("provider.revit", fake_adapter)
    with pytest.raises(ProviderBindingError, match="conflicting") as exc:
        registry.register("provider.revit", alternate_fake_adapter)
    assert exc.value.code == "PROVIDER_ADAPTER_CONFLICT"
```

Also test:

- a constraint must hold for every Unit target;
- `validate_native_constraints` raises `PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED` when direct validation fails;
- empty constraint tuple passes;
- same Adapter object may be idempotently registered twice;
- missing provider server returns `PROVIDER_ADAPTER_UNAVAILABLE`;
- Adapter version mismatch returns `PROVIDER_ADAPTER_UNAVAILABLE`;
- registry lookup is independent of registration order.

- [ ] **Step 2: Extend `conftest.py` with deterministic fake Adapter support**

Define a test-only Adapter whose output is caller-controlled without importing Host packages:

```python
class FakeBindingAdapter:
    def __init__(self, *, adapter_version="1.0.0", material_factory=None, error=None):
        self.adapter_version = adapter_version
        self.material_factory = material_factory
        self.error = error
        self.calls = []

    def bind(self, execution_unit, host_runtime_ref, selected_candidate, native_target_bindings):
        self.calls.append((execution_unit, host_runtime_ref, selected_candidate, native_target_bindings))
        if self.error is not None:
            raise self.error
        if self.material_factory is not None:
            return self.material_factory(execution_unit, native_target_bindings)
        return ProviderBindingMaterial(
            native_targets=native_target_bindings,
            provider_arguments={
                "native_ids": [item.native_id for item in native_target_bindings],
                "operation": execution_unit.canonical_operation,
                "canonical_arguments": dict(execution_unit.arguments),
            },
            provider_preconditions=(),
            native_binding_metadata={"variant": "default"},
        )
```

The fixture provider input schema requires exactly the keys emitted above and permits `canonical_arguments` as an object. Keep `valid_until` constant across comparison fixtures unless expiry sensitivity is the subject of the test.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_adapters.py
```

Expected: missing `design_provider_binding.adapters` / adapter exports.

- [ ] **Step 4: Implement Protocol, registry, and generic native-constraint evaluation**

Protocol:

```python
class ProviderBindingAdapter(Protocol):
    adapter_version: str

    def bind(
        self,
        execution_unit: ExecutionUnit,
        host_runtime_ref: HostRuntimeRef,
        selected_candidate: ProviderExecutionCandidate,
        native_target_bindings: tuple[NativeTargetBindingEvidence, ...],
    ) -> ProviderBindingMaterial: ...
```

Registry behavior:

```python
class ProviderBindingAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderBindingAdapter] = {}

    def register(self, provider_server: str, adapter: ProviderBindingAdapter) -> None:
        key = provider_server.strip()
        if not key:
            raise ProviderBindingError("PROVIDER_BINDING_INPUT_INVALID", "provider_server is required")
        existing = self._adapters.get(key)
        if existing is None:
            self._adapters[key] = adapter
            return
        if existing is adapter:
            return
        raise ProviderBindingError("PROVIDER_ADAPTER_CONFLICT", f"conflicting adapter for {key}")

    def require(self, provider_server: str, input_adapter_version: str) -> ProviderBindingAdapter:
        adapter = self._adapters.get(provider_server)
        if adapter is None or str(adapter.adapter_version).strip() != input_adapter_version:
            raise ProviderBindingError("PROVIDER_ADAPTER_UNAVAILABLE", "required provider adapter/version unavailable")
        return adapter
```

Constraint evaluator switches only on the frozen generic operator enum and the generic `native_kind` field; it contains no provider/Host-specific constants.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py

git add platform/provider_binding/src/design_provider_binding tests/provider_binding .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add provider binding adapter boundary"
```

---

### Task 4: Snapshot integrity and deterministic candidate selection

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py` only for intentionally public diagnostic helpers; do NOT export `ProviderResolver` until Task 5.
- Create: `tests/provider_binding/test_step31_snapshot_and_selection.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Task 1 contracts, Task 2 hash helpers, Task 3 native-constraint evaluator.
- Produces internal deterministic helpers: `_validate_request_and_snapshot(request)`, `_native_bindings_by_semantic_id(slice_, snapshot)`, `_validate_candidates(slice_, snapshot)`, `_select_candidate(unit, unit_native_targets, candidates)`.
- No Adapter invocation or ProviderBinding construction in Task 4.

- [ ] **Step 1: Add RED snapshot/selection tests and workflow step**

Add:

```yaml
      - name: Run Step31 snapshot and selection tests
        run: pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Tests must prove the exact fail-closed codes:

```text
Slice id mismatch                       → PROVIDER_SLICE_MISMATCH
Slice hash mismatch                     → PROVIDER_SLICE_MISMATCH
HostRuntimeRef mismatch                 → PROVIDER_SLICE_MISMATCH
native binding host/document mismatch   → PROVIDER_SLICE_MISMATCH
HostBinding fingerprint mismatch        → PROVIDER_NATIVE_BINDING_CONFLICT
missing native target                   → PROVIDER_NATIVE_BINDING_UNRESOLVED
duplicate native target row             → PROVIDER_NATIVE_BINDING_CONFLICT
conflicting native target row           → PROVIDER_NATIVE_BINDING_CONFLICT
extraneous native target                → PROVIDER_NATIVE_BINDING_EXTRANEOUS
candidate fingerprint mismatch          → PROVIDER_CANDIDATE_INVALID
invalid provider input JSON Schema      → PROVIDER_CANDIDATE_INVALID
unrelated candidate canonical operation → PROVIDER_CANDIDATE_INVALID
snapshot hash mismatch                  → PROVIDER_SNAPSHOT_HASH_MISMATCH
admission_time == valid_until            → PROVIDER_SNAPSHOT_EXPIRED
admission_time > valid_until             → PROVIDER_SNAPSHOT_EXPIRED
```

Selection tests:

- canonical operation mismatch filters candidate;
- Unit operation version absent from `compatible_operation_versions` filters candidate;
- native constraint failure filters candidate;
- any of trust/compatibility/health/license/certification != `SATISFIED` filters candidate;
- `UNKNOWN` fails closed exactly like `UNSATISFIED` for eligibility;
- all filtered returns `PROVIDER_CANDIDATE_UNAVAILABLE`;
- lower `policy_priority` wins;
- equal priority then provider_server/tool/version lexical identity determines winner;
- candidate list order reversal does not change winner;
- same eligible ranking identity repeated with same fingerprint returns `PROVIDER_CANDIDATE_AMBIGUOUS`;
- same eligible ranking identity with different fingerprint returns `PROVIDER_CANDIDATE_AMBIGUOUS`;
- candidate fingerprint is never used to pick one of those ties.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Expected: `design_provider_binding.resolver` helpers are absent.

- [ ] **Step 3: Implement request/Slice/snapshot validation in deterministic order**

The validation pipeline before any candidate selection is:

```text
1. request DTO/type invariants are already enforced by contracts
2. snapshot execution_slice_id/hash/HostRuntimeRef == Slice
3. each native row host_type/document_ref == Slice HostRuntimeRef
4. recompute each HostBinding fingerprint
5. detect duplicate/conflicting native semantic ids before set comparison
6. exact closed-world target-set comparison
7. validate every candidate semantic body:
   - operation belongs to Slice
   - input schema passes jsonschema schema check
   - candidate fingerprint recomputes exactly
8. recompute snapshot hash
9. compare explicit admission_time against valid_until
```

Use `jsonschema.validators.validator_for(dict(candidate.provider_input_schema))` followed by `validator.check_schema(dict(...))`; convert `SchemaError` into `PROVIDER_CANDIDATE_INVALID`.

Do not call Adapter registry anywhere in this validation path.

- [ ] **Step 4: Implement candidate filtering and ranking**

Eligibility predicate for one candidate/unit:

```python
candidate.canonical_operation == unit.canonical_operation
and unit.canonical_operation_version in candidate.compatible_operation_versions
and native_constraints_satisfied(candidate.provider_native_constraints, unit_native_targets)
and candidate.trust_state is EligibilityState.SATISFIED
and candidate.compatibility_state is EligibilityState.SATISFIED
and candidate.health_state is EligibilityState.SATISFIED
and candidate.license_state is EligibilityState.SATISFIED
and candidate.certification_state is EligibilityState.SATISFIED
```

After filtering, fail `PROVIDER_CANDIDATE_UNAVAILABLE` on empty.

Sort eligible rows by:

```python
(candidate.policy_priority, candidate.provider_server, candidate.provider_tool, candidate.provider_version)
```

Before returning the first row, collect all eligible rows with the same 4-tuple as the first. If count != 1, raise `PROVIDER_CANDIDATE_AMBIGUOUS`. Do not inspect candidate fingerprint to break the tie.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py

git add platform/provider_binding/src/design_provider_binding tests/provider_binding .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add deterministic provider candidate selection"
```

---

### Task 5: Adapter materialization, integrity gates, and ProviderBinding construction

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_resolver.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Tasks 1–4 and injected `ProviderBindingAdapterRegistry`.
- Produces public `ProviderResolver(registry)` with `resolve(request: ProviderBindingRequest) -> ProviderBindingSet`.
- The resolver creates `ProviderBinding` values; BindingSet structural revalidation is finalized in Task 6.

- [ ] **Step 1: Add resolver RED tests and workflow step**

Add:

```yaml
      - name: Run Step31 resolver tests
        run: pytest -q tests/provider_binding/test_step31_resolver.py
```

Core happy-path test:

```python
def test_one_execution_unit_produces_exactly_one_provider_binding(valid_request, adapter_registry):
    from design_provider_binding import ProviderResolver

    result = ProviderResolver(adapter_registry).resolve(valid_request)
    slice_ = valid_request.execution_slice
    assert len(result.bindings) == len(slice_.execution_units)
    assert {binding.execution_unit_id for binding in result.bindings} == {
        unit.execution_unit_id for unit in slice_.execution_units
    }
```

Also test:

- binding copies exact Unit id/hash/canonical operation and exact Slice id/hash/host instance/document;
- selected provider identity/version/adapter version comes from candidate/registry, never Adapter return material;
- `binding_expires_at == snapshot.valid_until`;
- Adapter receives only the Unit's exact native binding rows, not all Slice rows;
- Adapter output target set missing/extra/substituted/duplicate returns `PROVIDER_NATIVE_TARGET_MISMATCH`;
- each Adapter native target must equal the exact frozen snapshot evidence row for that semantic id;
- provider preconditions may be empty;
- emitted provider precondition source fingerprint must match a real Unit precondition;
- duplicate provider precondition source refs return `PROVIDER_BINDING_ADAPTATION_FAILED`;
- nonexistent source precondition ref returns `PROVIDER_BINDING_ADAPTATION_FAILED`;
- provider arguments failing candidate schema return `PROVIDER_INPUT_SCHEMA_INVALID`;
- Adapter returning the wrong object type returns `PROVIDER_BINDING_ADAPTATION_FAILED`;
- Adapter exception returns `PROVIDER_BINDING_ADAPTATION_FAILED`;
- selected Adapter is invoked exactly once;
- a valid lower-ranked second candidate/Adapter is NOT called when the selected Adapter fails;
- missing/version-mismatched selected Adapter propagates `PROVIDER_ADAPTER_UNAVAILABLE` and does not try another candidate;
- binding id is exactly `PB-{binding_hash[:12]}` and `validate_provider_binding` passes.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_resolver.py
```

Expected: `ProviderResolver` is not exported/implemented.

- [ ] **Step 3: Implement `ProviderResolver.resolve()` pipeline**

Constructor:

```python
class ProviderResolver:
    def __init__(self, adapter_registry: ProviderBindingAdapterRegistry) -> None:
        if not isinstance(adapter_registry, ProviderBindingAdapterRegistry):
            raise TypeError("adapter_registry must be ProviderBindingAdapterRegistry")
        self._adapter_registry = adapter_registry
```

Resolve order:

```text
_validate_request_and_snapshot(request)
→ native_by_semantic_id
→ validate candidates
→ for each ExecutionUnit in sorted(unit.execution_unit_hash) order:
     unit_native_targets = exact rows for unit.targets
     selected = _select_candidate(...)
     adapter = registry.require(selected.provider_server, selected.input_adapter_version)
     material = adapter.bind(...)
     validate material type/targets/precondition refs/provider schema
     compute binding_hash
     construct ProviderBinding PB-<hash[:12]>
     validate_provider_binding(binding)
→ sort bindings by execution_unit_hash
→ compute binding_set_hash
→ construct ProviderBindingSet
→ return
```

Catch exceptions only around the Adapter `bind()` call:

```python
try:
    material = adapter.bind(...)
except Exception as exc:
    raise ProviderBindingError(
        "PROVIDER_BINDING_ADAPTATION_FAILED",
        "selected provider adapter failed",
    ) from exc
```

Do not catch `PROVIDER_ADAPTER_UNAVAILABLE` and then try another candidate.

- [ ] **Step 4: Implement Adapter target/precondition/schema integrity gates**

Target gate:

```text
len(material.native_targets) == len(unit.targets)
semantic ids are unique
set(material.native_targets.semantic_id) == set(unit.targets)
for each semantic id: material row == verified snapshot row
```

Any failure → `PROVIDER_NATIVE_TARGET_MISMATCH`.

Provider precondition source fingerprints are computed from `unit.preconditions` with Task 2 helper. `material.provider_preconditions` may use any subset, but every emitted source ref must be in that set and each source ref may appear at most once. Failure → `PROVIDER_BINDING_ADAPTATION_FAILED`.

Provider arguments schema validation:

```python
validator_cls = jsonschema.validators.validator_for(dict(selected.provider_input_schema))
validator = validator_cls(dict(selected.provider_input_schema))
try:
    validator.validate(dict(material.provider_arguments))
except jsonschema.ValidationError as exc:
    raise ProviderBindingError("PROVIDER_INPUT_SCHEMA_INVALID", "provider arguments do not satisfy provider input schema") from exc
```

Candidate schema structure was already checked in Task 4.

- [ ] **Step 5: Build immutable Binding and preliminary BindingSet using full hashes**

For each Binding, copy verification/rollback contracts from selected candidate, not Adapter material. `native_binding_metadata` comes from Adapter. `binding_expires_at` is snapshot `valid_until`.

Preliminary set creation:

```python
binding_set_hash = compute_binding_set_hash(
    execution_slice_hash=slice_.execution_slice_hash,
    binding_hashes=(binding.binding_hash for binding in bindings),
)
ProviderBindingSet(
    f"PBS-{binding_set_hash[:12]}",
    slice_.execution_slice_id,
    slice_.execution_slice_hash,
    snapshot.snapshot_id,
    snapshot.snapshot_hash,
    tuple(sorted(bindings, key=lambda value: value.execution_unit_hash)),
    binding_set_hash,
)
```

Do not place snapshot id/hash into the set hash.

- [ ] **Step 6: Export `ProviderResolver`, run GREEN, commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
pytest -q tests/provider_binding/test_step31_resolver.py

git add platform/provider_binding/src/design_provider_binding tests/provider_binding .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): resolve immutable provider bindings"
```

---

### Task 6: BindingSet structural validation, determinism, provenance-vs-authorization semantics

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/hashing.py`
- Modify: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_binding_set.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: complete resolver from Task 5.
- Produces: public `validate_provider_binding_set(binding_set, execution_slice)` structural validator in addition to the existing hash-only validator.
- Resolver calls the structural validator before returning its internally constructed set.

- [ ] **Step 1: Add RED BindingSet semantics tests and workflow step**

Add:

```yaml
      - name: Run Step31 binding-set tests
        run: pytest -q tests/provider_binding/test_step31_binding_set.py
```

Tests must prove:

1. **Exact Unit coverage**
   - missing binding → `PROVIDER_BINDING_SET_INVALID`;
   - duplicate binding for one Unit → `PROVIDER_BINDING_SET_INVALID`;
   - extraneous Unit id → `PROVIDER_BINDING_SET_INVALID`;
   - binding Slice id/hash mismatch → `PROVIDER_BINDING_SET_INVALID`.

2. **Full-hash set identity**

```python
def test_binding_set_hash_matches_full_binding_hashes_only(valid_request, adapter_registry):
    from design_provider_binding import ProviderResolver, compute_binding_set_hash

    result = ProviderResolver(adapter_registry).resolve(valid_request)
    expected = compute_binding_set_hash(
        execution_slice_hash=valid_request.execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in result.bindings),
    )
    assert result.binding_set_hash == expected
```

3. **Determinism**
   - reverse `snapshot.native_target_bindings` order → same selected bindings/set hash;
   - reverse `snapshot.provider_candidates` order → same selected bindings/set hash;
   - register Adapters in opposite order → same output;
   - two different admission times strictly before the same expiry → same binding semantics/hash.

4. **Unused candidate provenance**
   - mutate only an unused candidate's body/fingerprint while keeping winner/native rows/expiry identical;
   - recompute snapshot hash;
   - assert snapshot hash changes;
   - assert returned set `provider_execution_snapshot_hash` changes;
   - assert selected `binding_hash` values and `binding_set_hash` stay identical.

5. **Provider switch**
   - construct two valid snapshots whose `policy_priority` chooses different providers;
   - keep the same exact Step30 Slice and native targets;
   - assert `execution_slice_hash` and every Unit hash are identical;
   - assert selected Binding hashes and `binding_set_hash` differ.

6. **Expiry sensitivity**
   - changing only `valid_until` and recomputing snapshot hash changes Binding hashes/set hash because `binding_expires_at` is authorization material.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_binding_set.py
```

Expected: structural `validate_provider_binding_set` is missing and at least exact-coverage tampering is not yet rejected by a public validator.

- [ ] **Step 3: Implement exact structural BindingSet validator**

Signature:

```python
def validate_provider_binding_set(
    binding_set: ProviderBindingSet,
    execution_slice: ExecutionSlice,
) -> None:
```

Validation order:

```text
binding_set.execution_slice_id/hash == execution_slice
all ProviderBinding values pass validate_provider_binding
all bindings point to exact execution_slice_id/hash
binding execution_unit_ids are unique
set(binding.execution_unit_id) == set(slice.execution_units.execution_unit_id)
for each Unit id: binding.execution_unit_hash == Unit.execution_unit_hash
validate_provider_binding_set_hash(binding_set)
```

Structural failures use `PROVIDER_BINDING_SET_INVALID`. A corrupted individual Binding hash may retain the more specific `PROVIDER_BINDING_HASH_MISMATCH` from `validate_provider_binding`.

- [ ] **Step 4: Make resolver self-validate before return**

Immediately before return:

```python
validate_provider_binding_set(binding_set, slice_)
return binding_set
```

This is an invariant assertion through the same public validation path Step32/replay code can use; it does not add external I/O.

- [ ] **Step 5: Replace contract-only fake BindingSet fixture with resolver-produced fixture**

`valid_binding_set` in `conftest.py` now calls `ProviderResolver(valid_registry).resolve(valid_request)`. After this task, no final Step31 test should rely on arbitrary placeholder binding/set hashes.

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest -q tests/provider_binding

git add platform/provider_binding/src/design_provider_binding tests/provider_binding .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): validate deterministic binding sets"
```

---

### Task 7: Architecture guards, PR diff boundary, regressions, final exact-head verification

**Files:**
- Create: `tests/provider_binding/test_step31_architecture.py`
- Modify: `.github/workflows/step31-provider-binding.yml`
- Modify after all verification only: `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md`

**Interfaces:**
- Consumes: completed Step31 package.
- Produces: static architecture guarantees and the final merge-quality CI gate.
- Does not change Step31 runtime semantics.

- [ ] **Step 1: Write architecture-guard RED tests**

Parse only production Python files under `platform/provider_binding/src/design_provider_binding`; do not scan design docs/comments as forbidden-token evidence.

Test imports through AST `Import` / `ImportFrom` and reject modules/names matching:

```text
autocad_sidecar
revit
tekla
host_contracts
HostAdapter
CommandDispatcher
HostCommand
ApprovalRecord
ExecutionGrant
ActualDelta
send_command
```

Inspect AST identifier/attribute names and reject runtime ownership names:

```text
command_id
idempotency_key
retry
actual_delta
saga
```

Allow immutable field `rollback_contract`; do not reject the word `rollback` globally.

Reject provider-specific literal branching by asserting production AST contains no string constants from this frozen guard set:

```text
AUTOCAD
REVIT
TEKLA
```

The generic tests/fixtures may use `REVIT`; the guard applies only to production source.

Also assert public DTO surfaces have no Step32/33 fields:

```python
assert {"approval_id", "execution_grant", "command_id", "idempotency_key"}.isdisjoint(
    ProviderBinding.__dataclass_fields__
)
```

- [ ] **Step 2: Run architecture RED/GREEN cycle without changing runtime semantics**

First run after writing the tests:

```bash
pytest -q tests/provider_binding/test_step31_architecture.py
```

If production already satisfies the guard, RED is not required by manufacturing a violation. The TDD requirement for Task 7 is that any discovered violation must be demonstrated by the new test before the production cleanup that removes it.

Then run:

```bash
pytest -q tests/provider_binding/test_step31_architecture.py
```

Expected final: pass.

- [ ] **Step 3: Extend the Step31 workflow to the full final gate**

Insert PR diff boundary before tests:

```yaml
      - name: Verify Step31 PR diff boundary
        if: github.event_name == 'pull_request' && github.head_ref == 'feat/step31-provider-binding'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          changed="$(git diff --name-only "$BASE_SHA...$HEAD_SHA")"
          printf '%s\n' "$changed"
          bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step31-provider-binding\.yml|docs/superpowers/specs/2026-08-30-step31-provider-binding-design\.md|docs/superpowers/plans/2026-08-30-step31-provider-binding\.md|platform/provider_binding/.*|tests/provider_binding/.*|pyproject\.toml)$' || true)"
          if [ -n "$bad" ]; then
            echo "Step31 changed files outside approved boundary:"
            printf '%s\n' "$bad"
            exit 1
          fi
```

Keep the focused test steps from Tasks 1–6 and add:

```yaml
      - name: Run Step31 architecture guards
        run: pytest -q tests/provider_binding/test_step31_architecture.py
      - name: Run Step30 regressions
        run: pytest -q tests/execution_planning
      - name: Run Step29 regressions
        run: pytest -q tests/changeset
      - name: Run resolver/capability regressions
        run: pytest -q tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_step24_semantic_eligibility.py
      - name: Run Ruff on Step31 Python changes
        run: ruff check platform/provider_binding/src/design_provider_binding tests/provider_binding
      - name: Run full repository Python test suite
        run: pytest -q --import-mode=importlib
```

The final workflow test order is:

```text
PR diff boundary
contracts
hashing
adapters
snapshot + selection
resolver
binding set
architecture
Step30 regressions
Step29 regressions
resolver/capability regressions
Ruff
full repository pytest
```

- [ ] **Step 4: Run focused final verification on the implementation head**

```bash
pytest -q tests/provider_binding
ruff check platform/provider_binding/src/design_provider_binding tests/provider_binding
```

Expected: all Step31 focused tests and Ruff pass.

- [ ] **Step 5: Run upstream regressions on the same head**

```bash
pytest -q tests/execution_planning
pytest -q tests/changeset
pytest -q tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_step24_semantic_eligibility.py
```

Expected: all pass with no upstream contract changes.

- [ ] **Step 6: Run full repository pytest on the same head**

```bash
pytest -q --import-mode=importlib
```

Record the exact pass/skip/warning counts from the fresh run. Do not reuse Step30's historical `777 passed` count as Step31 evidence.

- [ ] **Step 7: Commit the final architecture/CI gate**

```bash
git add tests/provider_binding/test_step31_architecture.py .github/workflows/step31-provider-binding.yml
git commit -m "test(step31): enforce provider binding architecture"
```

- [ ] **Step 8: Open a draft PR only after the branch push gate is green**

Create a draft PR:

```text
Title: Step31 deterministic provider binding
Base: main
Head: feat/step31-provider-binding
```

PR description must include:

```text
- Step31 spec path
- final head SHA
- focused Step31 test counts
- Step30 and Step29 regression results
- resolver/capability regression result
- Ruff result
- full repository pytest count
- explicit note: no Host-specific Adapter implementation or HostCommand dispatch is added in Step31 core
```

Do not claim PR diff-boundary success until the PR-triggered Step31 workflow has actually completed that step successfully.

- [ ] **Step 9: Require PR-triggered exact-head verification**

For the PR head, require:

```text
Step31 provider-binding workflow = completed / success
Verify Step31 PR diff boundary    = success
Step30 existing PR workflow       = no regression if triggered by shared files
Step29 existing PR workflow       = no regression if triggered by shared files
```

If `main` advanced after branch creation, confirm GitHub mergeability and rerun exact merge-ref CI if the platform generates a new merge ref.

- [ ] **Step 10: Perform spec-to-implementation review before declaring completion**

Manually compare implementation against every design section, with special attention to:

```text
snapshot provenance excluded from binding/set semantic hashes
full 64-hex binding hashes used in set hash
candidate fingerprint not used as ranking tie-breaker
no exception-driven fallback
unused candidate may change snapshot hash without changing binding identity
binding expiry is hash material
optional native preconditions do not replace Step30 canonical preconditions
Adapter cannot provide canonical/provider identity fields
no Host-specific branches/imports
no Step32/33 runtime concepts
```

Any discovered mismatch must receive its own RED test before the implementation fix.

- [ ] **Step 11: Only after final implementation head and PR head are both green, change the spec status**

Change exactly:

```text
**Status:** Design approved; implementation not started
```

to:

```text
**Status:** Implemented; verification complete
```

Commit:

```bash
git add docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md
git commit -m "docs(step31): mark design implemented"
```

Because this changes head SHA, all prior final-head evidence is no longer final. Re-run Step31 push + PR CI and require both to succeed on the new exact head before reporting Step31 complete.

- [ ] **Step 12: Do not merge without explicit user instruction**

Leave the PR open/draft or ready according to the user's instruction. A successful implementation plan execution ends with verified code and PR evidence; merge is a separate explicit action.

---

## Final Acceptance Checklist

Before stating Step31 is complete, fresh evidence on the exact final head must prove all of the following:

```text
[ ] ProviderBindingRequest accepts exactly Slice + snapshot + explicit admission_time
[ ] one ExecutionUnit creates exactly one ProviderBinding
[ ] no Unit splitting or mixed-provider binding exists
[ ] snapshot Slice id/hash/HostRuntimeRef mismatch fails closed
[ ] HostBinding fingerprints are recomputed
[ ] native bindings are closed-world and duplicate rows fail closed
[ ] every candidate fingerprint and input schema is validated
[ ] snapshot hash is recomputed and expiry is checked without wall-clock reads
[ ] candidate eligibility covers version/native constraints/trust/compatibility/health/license/certification
[ ] ranking uses policy priority then stable provider identity only
[ ] eligible same-rank duplicate/conflicting candidate rows fail ambiguous
[ ] candidate fingerprint is not a ranking tie-breaker
[ ] Adapter registry is provider_server keyed and version exact
[ ] selected Adapter failure never falls back to another provider
[ ] Adapter output cannot add/remove/substitute/duplicate native targets
[ ] optional provider preconditions reference only real unique Step30 source fingerprints
[ ] provider arguments validate against provider input schema
[ ] binding_expires_at equals snapshot valid_until
[ ] binding_hash excludes snapshot provenance and includes all selected execution material
[ ] unused-candidate-only changes can leave binding/set identity stable
[ ] binding_set_hash uses full 64-hex binding hashes
[ ] provider switch changes Step31 hashes but not Step29/30 hashes
[ ] ProviderBindingSet structural validator proves exact Unit coverage
[ ] no Host-specific imports/branches exist in generic core
[ ] no ApprovalRecord/ExecutionGrant/HostCommand/dispatch/ActualDelta/Saga runtime behavior exists
[ ] Step31 focused tests pass
[ ] Ruff passes
[ ] Step30 regressions pass
[ ] Step29 regressions pass
[ ] resolver/capability regressions pass
[ ] full repository pytest passes
[ ] PR diff boundary passes on a real pull_request event
[ ] final design status is Implemented only after final exact-head verification
```
