# Step 31 Provider Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic immutable Step31 late binding from an exact Step30 `ExecutionSlice` plus exact slice-scoped provider/native evidence into exactly one `ProviderBinding` per `ExecutionUnit` and one authorization-relevant `ProviderBindingSet` / `binding_set_hash` per Slice, without changing canonical semantics or performing Host execution.

**Architecture:** Step31 is a separate `design_provider_binding` package. It consumes immutable Step30 execution contracts plus a caller-assembled `ProviderExecutionSnapshot`, validates closed-world native identity and provider-candidate evidence, deterministically selects one provider candidate per Unit, invokes an injected provider-specific `ProviderBindingAdapter`, validates returned native material, and computes canonical SHA-256 binding identities. Step31 never live-queries Host/provider services, never falls back after Adapter failure, never emits `ExecutionGrant`/`HostCommand`, and never branches on Host-specific types.

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
- Snapshot native bindings are closed-world for the union of Slice Unit targets: missing/conflicting/extraneous rows fail closed.
- `host_instance_id` belongs to Step30 `HostRuntimeRef`; persistent native evidence carries semantic id + host type + document + native id + native kind + fingerprint.
- Provider-native constraints are v1 declarative `native_kind EQ/IN` predicates only; generic Step31 compares opaque strings and contains no Host ontology.
- Candidate eligibility uses canonical operation/version, native constraints, trust, compatibility, health, license, and certification evidence; policy preference is already projected into deterministic integer `policy_priority`.
- Candidate winner ordering is `(policy_priority, provider_server, provider_tool, provider_version)` ascending.
- Same ranking identity among eligible candidates is ambiguous whether fingerprints are equal or different; candidate fingerprint is never a winner tie-breaker.
- After a winner is selected, Adapter failure MUST NOT fall back to the next candidate.
- Adapter registry is keyed by `provider_server`; generic Step31 contains no Host-specific branch or dynamic Host-package import.
- Adapter output may contain native targets, provider arguments, optional provider-native enforcement projections, and opaque execution-semantic metadata only.
- Optional provider-native preconditions may reference only real unique Step30 precondition fingerprints; complete translation of all Step30 planning preconditions is NOT required.
- Provider arguments MUST validate against selected candidate `provider_input_schema`.
- `binding_expires_at = snapshot.valid_until` in v1.
- `binding_hash` excludes construction id and snapshot id/hash; it binds exact selected provider/native execution material and expiry.
- `binding_set_hash = SHA256({execution_slice_hash, sorted(full 64-hex binding_hashes)})`; construction IDs never enter semantic hash bodies.
- Snapshot id/hash are provenance only and do not enter `binding_hash` or `binding_set_hash`.
- Changing an unused candidate may change snapshot hash but MUST NOT change binding/set hash when winner/native material/contracts/expiry are unchanged.
- Provider switch MUST leave Step29/30 ChangeSet/Unit/Slice hashes unchanged and change ProviderBinding/binding-set hashes.
- `admission_time` is explicit UTC input used only for expiry admission; resolver code MUST NOT read wall-clock time.
- Step31 MUST NOT create/read `ApprovalRecord`, `ExecutionGrant`, `HostCommand`, dispatch/retry/idempotency state, ActualDelta, verification result, rollback execution, or Saga state.
- Production Step31 code changes only under `platform/provider_binding/`; root `pyproject.toml` only adds the Step31 pytest path. Tests live under `tests/provider_binding/` and CI in `.github/workflows/step31-provider-binding.yml`.

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

- `platform/provider_binding/pyproject.toml`
- `platform/provider_binding/src/design_provider_binding/contracts.py`
- `platform/provider_binding/src/design_provider_binding/hashing.py`
- `platform/provider_binding/src/design_provider_binding/adapters.py`
- `platform/provider_binding/src/design_provider_binding/resolver.py`
- `platform/provider_binding/src/design_provider_binding/__init__.py`
- `pyproject.toml`

### Tests

- `tests/provider_binding/conftest.py`
- `tests/provider_binding/test_step31_contracts.py`
- `tests/provider_binding/test_step31_hashing.py`
- `tests/provider_binding/test_step31_adapters.py`
- `tests/provider_binding/test_step31_snapshot_and_selection.py`
- `tests/provider_binding/test_step31_resolver.py`
- `tests/provider_binding/test_step31_binding_set.py`
- `tests/provider_binding/test_step31_architecture.py`

### CI / docs

- `.github/workflows/step31-provider-binding.yml`
- `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md`
- `docs/superpowers/plans/2026-08-30-step31-provider-binding.md`

---

### Task 1: Package shell, immutable contracts, and Step30 boundary fixtures

**Files:**
- Create: `platform/provider_binding/pyproject.toml`
- Create: `platform/provider_binding/src/design_provider_binding/contracts.py`
- Create: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/provider_binding/conftest.py`
- Create: `tests/provider_binding/test_step31_contracts.py`
- Create: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Step30 `ExecutionSlice`, `ExecutionUnit`, `HostRuntimeRef`; Step29 `ChangePrecondition` values already embedded in Units.
- Produces: `ProviderBindingError`, `EligibilityState`, `NativeConstraintOperator`, `NativeConstraint`, `NativeTargetBindingEvidence`, `ProviderExecutionCandidate`, `ProviderExecutionSnapshot`, `ProviderPreconditionBinding`, `ProviderBindingMaterial`, `ProviderBinding`, `ProviderBindingSet`, `ProviderBindingRequest`.
- Does not export Resolver, Adapter registry, or hash helpers yet.

- [ ] **Step 1: Create the RED workflow and failing contract tests before the package exists**

Create `.github/workflows/step31-provider-binding.yml` with:

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

Contract tests:

```python
from dataclasses import FrozenInstanceError, fields

import pytest


def test_provider_binding_request_has_no_provider_choice_or_grant_fields():
    from design_provider_binding import ProviderBindingRequest

    names = {field.name for field in fields(ProviderBindingRequest)}
    assert names == {"execution_slice", "provider_execution_snapshot", "admission_time"}
    assert {"provider_server", "provider_tool", "approval_id", "execution_grant"}.isdisjoint(names)


def test_native_constraint_normalizes_in_values():
    from design_provider_binding import NativeConstraint, NativeConstraintOperator

    constraint = NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Wall", "Wall", "Door"))
    assert constraint.values == ("Door", "Wall")


def test_native_binding_evidence_is_frozen(digest):
    from design_provider_binding import NativeTargetBindingEvidence

    value = NativeTargetBindingEvidence("WALL-001", "REVIT", "DOC-1", "42", "Wall", digest("host-binding"))
    with pytest.raises(FrozenInstanceError):
        value.native_id = "43"
```

Also test:

- only `native_kind` is accepted as `NativeConstraint.field`;
- `EQ` requires exactly one value and `IN` at least one;
- digest fields accept only lowercase 64-hex;
- `policy_priority` is integer `>= 0` and rejects booleans;
- candidate state fields normalize to `EligibilityState`;
- mapping fields are defensively copied and expose a read-only outer mapping;
- tuple fields reject wrong member types;
- UTC timestamps accept `Z` and `+00:00`, normalize to `Z`, and reject naive/non-UTC offsets;
- `ProviderBindingRequest.admission_time` uses the same normalization;
- `ProviderBindingMaterial.provider_preconditions` may be empty;
- `ProviderBindingSet.bindings` requires at least one `ProviderBinding`.

- [ ] **Step 2: Add real Step30 DTO/hash fixtures**

In `tests/provider_binding/conftest.py`:

```python
from __future__ import annotations

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


@pytest.fixture
def digest_fn():
    return digest


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
            f"EU-{unit_hash[:12]}", f"COP-{source_hash[:12]}", source_hash,
            "move.v1", "1.0.0", definition_hash, (target,), arguments,
            preconditions, (CanonicalAspect.PLACEMENT,), unit_hash,
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
        f"XS-{slice_hash[:12]}", "CS-31", changeset_hash,
        host_ref, scope_ref, units, slice_hash,
    )


@pytest.fixture
def execution_slice():
    return build_execution_slice()
```

The Contract tests do not require a BindingSet fixture. A resolver-produced `valid_binding_set` fixture is introduced only after the resolver exists in Task 6.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

Expected: import failure specifically because `design_provider_binding` does not exist.

- [ ] **Step 4: Implement package shell and exact frozen contracts**

`platform/provider_binding/pyproject.toml`:

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

Add to root pytest `pythonpath`:

```toml
"platform/provider_binding/src",
```

Define exact DTO fields from the spec. Use these enums/error:

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

Dataclasses:

```text
NativeConstraint(field, operator, values)
NativeTargetBindingEvidence(semantic_id, host_type, document_ref, native_id, native_kind, host_binding_fingerprint)
ProviderExecutionCandidate(provider_server, provider_tool, provider_version, canonical_operation, compatible_operation_versions, input_adapter_version, provider_native_constraints, provider_input_schema, verification_contract, rollback_contract, trust_state, compatibility_state, health_state, license_state, certification_state, policy_priority, candidate_fingerprint)
ProviderExecutionSnapshot(snapshot_id, execution_slice_id, execution_slice_hash, host_runtime_ref, native_target_bindings, provider_candidates, valid_until, snapshot_hash)
ProviderPreconditionBinding(source_precondition_fingerprint, provider_precondition)
ProviderBindingMaterial(native_targets, provider_arguments, provider_preconditions, native_binding_metadata)
ProviderBinding(binding_id, execution_unit_id, execution_unit_hash, execution_slice_id, execution_slice_hash, canonical_operation, provider_server, provider_tool, provider_version, selected_candidate_fingerprint, host_instance_id, document_ref, input_adapter_version, native_targets, provider_arguments, provider_preconditions, native_binding_metadata, verification_contract, rollback_contract, binding_expires_at, binding_hash)
ProviderBindingSet(binding_set_id, execution_slice_id, execution_slice_hash, provider_execution_snapshot_id, provider_execution_snapshot_hash, bindings, binding_set_hash)
ProviderBindingRequest(execution_slice, provider_execution_snapshot, admission_time)
```

Use `deepcopy(dict(value))` + `MappingProxyType` for mapping fields, matching Step29/30. Normalize UTC timestamps with:

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

- [ ] **Step 5: Export only contracts and run GREEN**

Update workflow install step to include `-e platform/provider_binding` after execution planning. Then run:

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

Expected: pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add platform/provider_binding tests/provider_binding/conftest.py tests/provider_binding/test_step31_contracts.py pyproject.toml .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add immutable provider binding contracts"
```

---

### Task 2: Deterministic semantic hashing

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/hashing.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_hashing.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Consumes: Task 1 DTOs and public Step29 `design_changeset.canonical_hash`.
- Produces: `compute_host_binding_fingerprint`, `compute_candidate_fingerprint`, `compute_provider_snapshot_hash`, `compute_precondition_fingerprint`, `compute_binding_hash`, `compute_binding_set_hash`, `validate_provider_binding`, `validate_provider_binding_set_hash`.

- [ ] **Step 1: Write RED hashing tests and add workflow step**

```yaml
      - name: Run Step31 hashing tests
        run: pytest -q tests/provider_binding/test_step31_hashing.py
```

Required tests:

- HostBinding fingerprint binds semantic id/host/document/native id/native kind exactly;
- candidate fingerprint changes when any frozen candidate semantic field changes;
- candidate collection/constraint ordering normalizes deterministically;
- snapshot hash is invariant to candidate/native-row ordering but preserves duplicate-row multiplicity;
- snapshot id is excluded from snapshot hash;
- precondition fingerprint binds kind/subject/evidence;
- binding hash is invariant to native-target/provider-precondition ordering;
- binding hash changes for provider server/tool/version/candidate fingerprint/adapter version/host instance/document/native identity/provider args/provider preconditions/native metadata/verification/rollback/expiry;
- binding hash API has no snapshot id/hash inputs;
- binding-set hash is order invariant and changes when any full binding hash changes;
- `validate_provider_binding` returns `PROVIDER_BINDING_HASH_MISMATCH` for hash or `PB-` id mismatch;
- `validate_provider_binding_set_hash` returns `PROVIDER_BINDING_SET_INVALID` for set hash/id mismatch.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_hashing.py
```

Expected: hash helpers are missing.

- [ ] **Step 3: Implement canonical payloads with Step29 `canonical_hash`**

Do not copy a JSON encoder.

Host binding:

```python
canonical_hash({
    "semantic_id": value.semantic_id,
    "host_type": value.host_type,
    "document_ref": value.document_ref,
    "native_id": value.native_id,
    "native_kind": value.native_kind,
})
```

Candidate fingerprint includes every §9 field. Constraints normalize as:

```python
{"field": c.field, "operator": c.operator.value, "values": list(c.values)}
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
    "native_target_bindings": sorted(full_native_rows, key=native_key),
    "provider_candidate_fingerprints": sorted(c.candidate_fingerprint for c in snapshot.provider_candidates),
    "valid_until": snapshot.valid_until,
}
```

Use lists, not sets, so duplicate evidence remains detectable.

Precondition fingerprint:

```python
canonical_hash({
    "kind": precondition.kind.value,
    "subject_ref": precondition.subject_ref,
    "evidence_ref": precondition.evidence_ref,
})
```

Binding hash uses the exact §16.3 body; provider preconditions sort by `(source_precondition_fingerprint, canonical_hash(provider_precondition))`, native targets sort by full persistent identity.

Binding-set hash:

```python
canonical_hash({
    "execution_slice_hash": execution_slice_hash,
    "binding_hashes": sorted(binding_hashes),
})
```

Do not deduplicate binding hashes inside this helper.

- [ ] **Step 4: Implement supplied-hash validators**

```python
def validate_provider_binding(binding: ProviderBinding) -> None:
    expected = compute_binding_hash(...)
    if binding.binding_hash != expected or binding.binding_id != f"PB-{expected[:12]}":
        raise ProviderBindingError("PROVIDER_BINDING_HASH_MISMATCH", "provider binding hash/id mismatch")


def validate_provider_binding_set_hash(binding_set: ProviderBindingSet) -> None:
    expected = compute_binding_set_hash(
        execution_slice_hash=binding_set.execution_slice_hash,
        binding_hashes=(b.binding_hash for b in binding_set.bindings),
    )
    if binding_set.binding_set_hash != expected or binding_set.binding_set_id != f"PBS-{expected[:12]}":
        raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "provider binding set hash/id mismatch")
```

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
git add platform/provider_binding/src/design_provider_binding tests/provider_binding/test_step31_hashing.py .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): add deterministic provider binding hashes"
```

---

### Task 3: Native constraints and Adapter registry

**Files:**
- Create: `platform/provider_binding/src/design_provider_binding/adapters.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_adapters.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Produces: `ProviderBindingAdapter` Protocol, `ProviderBindingAdapterRegistry`, `native_constraints_satisfied`, `validate_native_constraints`.

- [ ] **Step 1: Write RED tests and add workflow step**

```yaml
      - name: Run Step31 adapter tests
        run: pytest -q tests/provider_binding/test_step31_adapters.py
```

Tests cover:

- `EQ` and `IN` over opaque `native_kind`;
- every Unit native target must satisfy every constraint;
- empty constraints pass;
- direct failed validation raises `PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED`;
- idempotent registration of the same Adapter object succeeds;
- different Adapter on same provider server raises `PROVIDER_ADAPTER_CONFLICT`;
- missing provider server raises `PROVIDER_ADAPTER_UNAVAILABLE`;
- Adapter version mismatch raises `PROVIDER_ADAPTER_UNAVAILABLE`;
- registration order does not affect lookup.

- [ ] **Step 2: Add deterministic fake Adapter fixture**

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

Candidate fixture schema requires exactly `native_ids`, `operation`, `canonical_arguments`; `additionalProperties` is false.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_adapters.py
```

Expected: adapters module/exports missing.

- [ ] **Step 4: Implement Protocol and registry**

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

Registry:

```python
class ProviderBindingAdapterRegistry:
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

Constraint evaluator switches only on `NativeConstraintOperator`; no Host-specific literals.

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
- Create: `tests/provider_binding/test_step31_snapshot_and_selection.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Produces internal helpers `_validate_request_and_snapshot`, `_native_bindings_by_semantic_id`, `_validate_candidates`, `_select_candidate`.
- Does not invoke Adapters or export `ProviderResolver` yet.

- [ ] **Step 1: Write RED snapshot/selection tests and add workflow step**

```yaml
      - name: Run Step31 snapshot and selection tests
        run: pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Required exact failures:

```text
Slice id/hash/runtime mismatch            → PROVIDER_SLICE_MISMATCH
native row host/document mismatch         → PROVIDER_SLICE_MISMATCH
HostBinding fingerprint mismatch          → PROVIDER_NATIVE_BINDING_CONFLICT
missing native target                     → PROVIDER_NATIVE_BINDING_UNRESOLVED
duplicate/conflicting native row          → PROVIDER_NATIVE_BINDING_CONFLICT
extraneous native target                  → PROVIDER_NATIVE_BINDING_EXTRANEOUS
candidate fingerprint/schema invalid      → PROVIDER_CANDIDATE_INVALID
candidate operation unrelated to Slice    → PROVIDER_CANDIDATE_INVALID
snapshot hash mismatch                    → PROVIDER_SNAPSHOT_HASH_MISMATCH
admission_time >= valid_until              → PROVIDER_SNAPSHOT_EXPIRED
```

Selection tests prove canonical op/version/native constraints and all five eligibility states filter candidates; all filtered gives `PROVIDER_CANDIDATE_UNAVAILABLE`; lower priority wins; identity tuple breaks non-ambiguous ties; candidate order does not matter; same eligible ranking identity repeated gives `PROVIDER_CANDIDATE_AMBIGUOUS` whether fingerprints match or differ.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Expected: resolver helpers missing.

- [ ] **Step 3: Implement snapshot validation in this exact order**

```text
1. snapshot Slice id/hash/HostRuntimeRef == Slice
2. each native row host_type/document_ref == Slice runtime route
3. recompute every HostBinding fingerprint
4. detect duplicate semantic ids
5. exact required-target coverage
6. every candidate operation belongs to a Unit in the Slice
7. validate candidate input JSON Schema
8. recompute every candidate fingerprint
9. recompute snapshot hash
10. admission_time < valid_until
```

Use `jsonschema.validators.validator_for(dict(schema)).check_schema(dict(schema))`; convert `SchemaError` to `PROVIDER_CANDIDATE_INVALID`.

- [ ] **Step 4: Implement candidate filter/rank**

Eligibility:

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

Ranking key:

```python
(candidate.policy_priority, candidate.provider_server, candidate.provider_tool, candidate.provider_version)
```

If all filtered, raise `PROVIDER_CANDIDATE_UNAVAILABLE`. If more than one eligible row shares the winning key, raise `PROVIDER_CANDIDATE_AMBIGUOUS`. Do not inspect fingerprint to break the tie.

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

### Task 5: Adapter materialization and ProviderBinding construction

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_resolver.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Produces public `ProviderResolver(adapter_registry)` and `resolve(request: ProviderBindingRequest) -> ProviderBindingSet`.

- [ ] **Step 1: Write RED resolver tests and add workflow step**

```yaml
      - name: Run Step31 resolver tests
        run: pytest -q tests/provider_binding/test_step31_resolver.py
```

Required tests:

- each Unit produces exactly one Binding;
- Binding copies exact Unit id/hash/canonical operation and Slice id/hash/host instance/document;
- selected provider identity/version/adapter version comes from selected candidate/registry, not Adapter return material;
- `binding_expires_at == snapshot.valid_until`;
- Adapter receives only the Unit's native rows;
- Adapter native targets missing/extra/substituted/duplicate → `PROVIDER_NATIVE_TARGET_MISMATCH`;
- returned native target row must equal verified snapshot evidence;
- provider preconditions may be empty;
- emitted precondition source ref must match a real Unit precondition and be unique;
- duplicate/unknown precondition source ref → `PROVIDER_BINDING_ADAPTATION_FAILED`;
- provider arguments failing selected schema → `PROVIDER_INPUT_SCHEMA_INVALID`;
- Adapter wrong return type/exception → `PROVIDER_BINDING_ADAPTATION_FAILED`;
- selected Adapter is invoked exactly once;
- lower-ranked alternative is never invoked after selected Adapter failure;
- missing/version-mismatched selected Adapter → `PROVIDER_ADAPTER_UNAVAILABLE`, no fallback;
- Binding id is `PB-{binding_hash[:12]}` and `validate_provider_binding` passes.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_resolver.py
```

Expected: `ProviderResolver` absent.

- [ ] **Step 3: Implement resolver pipeline**

```text
_validate_request_and_snapshot(request)
→ native_by_semantic_id
→ validate candidates
→ for each Unit sorted by execution_unit_hash:
     exact native rows for Unit.targets
     selected = _select_candidate(...)
     adapter = registry.require(selected.provider_server, selected.input_adapter_version)
     call adapter exactly once
     validate material type
     validate exact native targets
     validate optional source-precondition refs
     validate provider arguments against provider_input_schema
     compute binding_hash
     construct ProviderBinding PB-<hash[:12]>
     validate_provider_binding(binding)
→ sort bindings by execution_unit_hash
→ compute binding_set_hash from full hashes
→ construct ProviderBindingSet
```

Catch only Adapter-call exceptions:

```python
try:
    material = adapter.bind(...)
except Exception as exc:
    raise ProviderBindingError("PROVIDER_BINDING_ADAPTATION_FAILED", "selected provider adapter failed") from exc
```

Do not catch Adapter unavailability and choose a second candidate.

- [ ] **Step 4: Implement output integrity gates**

Native targets must satisfy:

```text
len(material.native_targets) == len(unit.targets)
semantic ids unique
set(material.native_targets.semantic_id) == set(unit.targets)
each returned row == verified snapshot row for that semantic id
```

Precondition refs are compared to `{compute_precondition_fingerprint(p) for p in unit.preconditions}`; any unknown or duplicate emitted source ref gives `PROVIDER_BINDING_ADAPTATION_FAILED`.

Validate arguments with:

```python
validator_cls = jsonschema.validators.validator_for(dict(selected.provider_input_schema))
validator = validator_cls(dict(selected.provider_input_schema))
try:
    validator.validate(dict(material.provider_arguments))
except jsonschema.ValidationError as exc:
    raise ProviderBindingError("PROVIDER_INPUT_SCHEMA_INVALID", "provider arguments do not satisfy provider input schema") from exc
```

- [ ] **Step 5: Build Binding and preliminary BindingSet**

Provider verification/rollback contracts come from selected candidate; `native_binding_metadata` comes from Adapter; expiry comes from snapshot. Set hash uses only Slice hash + full Binding hashes. Snapshot id/hash are copied as provenance fields only.

- [ ] **Step 6: Export Resolver, run GREEN, commit**

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

### Task 6: BindingSet structural validation and authorization/provenance determinism

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/hashing.py`
- Modify: `platform/provider_binding/src/design_provider_binding/resolver.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_step31_binding_set.py`
- Modify: `tests/provider_binding/conftest.py`
- Modify: `.github/workflows/step31-provider-binding.yml`

**Interfaces:**
- Produces public `validate_provider_binding_set(binding_set, execution_slice)`.

- [ ] **Step 1: Write RED BindingSet tests and add workflow step**

```yaml
      - name: Run Step31 binding-set tests
        run: pytest -q tests/provider_binding/test_step31_binding_set.py
```

Required tests:

- missing/duplicate/extraneous Unit Binding → `PROVIDER_BINDING_SET_INVALID`;
- Binding Slice id/hash mismatch → `PROVIDER_BINDING_SET_INVALID`;
- Binding Unit hash differs from exact Slice Unit → `PROVIDER_BINDING_SET_INVALID`;
- set hash equals computation over full 64-hex Binding hashes;
- reversing snapshot native rows/candidates or Adapter registration order leaves output identity unchanged;
- two different admission times before same expiry produce identical bindings/set;
- changing only an unused candidate body/fingerprint and recomputing snapshot hash changes snapshot provenance but leaves selected Binding hashes/set hash unchanged;
- changing only policy priorities so a different provider wins leaves exact Step30 Slice/Unit hashes unchanged but changes Step31 hashes;
- changing only `valid_until` changes Binding/set hash.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_binding_set.py
```

Expected: structural validator missing.

- [ ] **Step 3: Implement structural validator**

```python
def validate_provider_binding_set(binding_set: ProviderBindingSet, execution_slice: ExecutionSlice) -> None:
    if (
        binding_set.execution_slice_id != execution_slice.execution_slice_id
        or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
    ):
        raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "binding set slice mismatch")

    for binding in binding_set.bindings:
        validate_provider_binding(binding)
        if binding.execution_slice_id != execution_slice.execution_slice_id or binding.execution_slice_hash != execution_slice.execution_slice_hash:
            raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "binding references wrong slice")

    units = {unit.execution_unit_id: unit for unit in execution_slice.execution_units}
    bindings = {binding.execution_unit_id: binding for binding in binding_set.bindings}
    if len(bindings) != len(binding_set.bindings) or set(bindings) != set(units):
        raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "binding set unit coverage mismatch")
    if any(bindings[unit_id].execution_unit_hash != units[unit_id].execution_unit_hash for unit_id in units):
        raise ProviderBindingError("PROVIDER_BINDING_SET_INVALID", "binding set unit hash mismatch")

    validate_provider_binding_set_hash(binding_set)
```

A corrupted individual Binding hash may retain `PROVIDER_BINDING_HASH_MISMATCH`; structural set mismatches use `PROVIDER_BINDING_SET_INVALID`.

- [ ] **Step 4: Make resolver self-validate and add real BindingSet fixture**

Before returning:

```python
validate_provider_binding_set(binding_set, slice_)
return binding_set
```

Now add in `conftest.py`:

```python
@pytest.fixture
def valid_binding_set(valid_request, adapter_registry):
    return ProviderResolver(adapter_registry).resolve(valid_request)
```

Every final BindingSet fixture is resolver-produced.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding
git add platform/provider_binding/src/design_provider_binding tests/provider_binding .github/workflows/step31-provider-binding.yml
git commit -m "feat(step31): validate deterministic binding sets"
```

---

### Task 7: Architecture guards, regression gates, and final exact-head verification

**Files:**
- Create: `tests/provider_binding/test_step31_architecture.py`
- Modify: `.github/workflows/step31-provider-binding.yml`
- Modify only after all final gates pass: `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md`

**Interfaces:**
- Adds no runtime semantics; freezes architectural boundaries and merge-quality evidence.

- [ ] **Step 1: Add architecture tests**

Parse production Python only under `platform/provider_binding/src/design_provider_binding`. Reject import/identifier references to:

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
command_id
idempotency_key
```

Reject production string literals `AUTOCAD`, `REVIT`, `TEKLA` so generic resolver code cannot encode Host-specific branches. Do not scan tests, fixtures, docs, or comments. Allow immutable `rollback_contract`; do not reject the generic word `rollback`.

Also assert `ProviderBinding` / `ProviderBindingRequest` fields contain no approval/grant/HostCommand envelope fields.

- [ ] **Step 2: Run architecture tests**

```bash
pytest -q tests/provider_binding/test_step31_architecture.py
```

If a real violation is found, preserve the failing test, make the smallest production cleanup, and rerun. Do not manufacture a violation if the architecture already passes.

- [ ] **Step 3: Extend workflow with PR boundary and all final gates**

Add before focused tests:

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

Final workflow order:

```text
PR diff boundary
contracts
hashing
adapters
snapshot + selection
resolver
binding set
architecture
Step30 regressions: pytest -q tests/execution_planning
Step29 regressions: pytest -q tests/changeset
resolver/capability regressions: pytest -q tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_step24_semantic_eligibility.py
Ruff: ruff check platform/provider_binding/src/design_provider_binding tests/provider_binding
full repository: pytest -q --import-mode=importlib
```

- [ ] **Step 4: Commit architecture/CI gate**

```bash
git add tests/provider_binding/test_step31_architecture.py .github/workflows/step31-provider-binding.yml
git commit -m "test(step31): enforce provider binding architecture"
```

- [ ] **Step 5: Run fresh exact-head verification**

```bash
pytest -q tests/provider_binding
ruff check platform/provider_binding/src/design_provider_binding tests/provider_binding
pytest -q tests/execution_planning
pytest -q tests/changeset
pytest -q tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_step24_semantic_eligibility.py
pytest -q --import-mode=importlib
```

Record fresh counts. Historical Step30 counts are not Step31 evidence.

- [ ] **Step 6: Open a draft PR only after branch push CI is green**

```text
Title: Step31 deterministic provider binding
Base: main
Head: feat/step31-provider-binding
```

PR description records spec path, exact head SHA, focused test counts, upstream regression counts, Ruff, full-repo pytest, and explicitly states that Step31 core adds no Host-specific Adapter implementation or HostCommand dispatch.

- [ ] **Step 7: Require real PR-triggered exact-head evidence**

Require Step31 workflow `completed / success` and `Verify Step31 PR diff boundary = success`. If `main` moved, check mergeability and new merge-ref CI rather than reusing old evidence.

- [ ] **Step 8: Perform spec-to-implementation review before completion claim**

Review these failure-prone invariants explicitly:

```text
snapshot provenance excluded from binding/set semantic hashes
full 64-hex binding hashes used in set hash
candidate fingerprint not used as ranking tie-breaker
no exception-driven fallback
unused candidate can change snapshot hash without changing binding identity
binding expiry is hash material
optional native preconditions do not replace Step30 canonical preconditions
Adapter cannot provide canonical/provider identity fields
no Host-specific branches/imports
no Step32/33 runtime concepts
```

Any mismatch gets its own RED test before a fix.

- [ ] **Step 9: Change design status only after final code + PR CI are green**

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

Because head changes, rerun final push + PR CI on the new exact head before reporting completion.

- [ ] **Step 10: Do not merge without explicit user instruction**

Leave the PR unmerged until the user explicitly asks for merge.

---

## Final Acceptance Checklist

```text
[ ] ProviderBindingRequest contains only Slice + snapshot + explicit admission_time
[ ] one ExecutionUnit creates exactly one ProviderBinding
[ ] no Unit splitting or mixed-provider binding exists
[ ] snapshot Slice id/hash/HostRuntimeRef mismatch fails closed
[ ] HostBinding fingerprints are recomputed
[ ] native bindings are closed-world and duplicate rows fail closed
[ ] every candidate fingerprint and input schema is validated
[ ] snapshot hash is recomputed and expiry checked without wall-clock reads
[ ] candidate eligibility covers version/native constraints/trust/compatibility/health/license/certification
[ ] ranking uses policy priority then stable provider identity only
[ ] same-rank eligible duplicate/conflicting candidate rows fail ambiguous
[ ] candidate fingerprint is not a ranking tie-breaker
[ ] Adapter registry is provider_server keyed and adapter version exact
[ ] selected Adapter failure never falls back to another provider
[ ] Adapter output cannot add/remove/substitute/duplicate native targets
[ ] optional provider preconditions reference only real unique Step30 source fingerprints
[ ] provider arguments validate against provider input schema
[ ] binding_expires_at equals snapshot valid_until
[ ] binding_hash excludes snapshot provenance and includes all selected execution material
[ ] unused-candidate-only change can leave binding/set identity stable
[ ] binding_set_hash uses full 64-hex binding hashes
[ ] provider switch changes Step31 hashes but not Step29/30 hashes
[ ] ProviderBindingSet structural validator proves exact Unit coverage
[ ] generic core has no Host-specific imports/branches
[ ] Step31 has no ApprovalRecord/ExecutionGrant/HostCommand/dispatch/ActualDelta/Saga runtime behavior
[ ] Step31 focused tests pass
[ ] Ruff passes
[ ] Step30 regressions pass
[ ] Step29 regressions pass
[ ] resolver/capability regressions pass
[ ] full repository pytest passes
[ ] PR diff boundary passes on a real pull_request event
[ ] design status is Implemented only after final exact-head verification
```
