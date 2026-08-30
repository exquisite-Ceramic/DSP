# Step 31 Provider Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic immutable Step31 late binding from an exact Step30 `ExecutionSlice` plus exact slice-scoped provider/native evidence into exactly one `ProviderBinding` per `ExecutionUnit` and one authorization-relevant `ProviderBindingSet` / `binding_set_hash` per Slice, without changing canonical semantics or performing Host execution.

**Architecture:** Step31 is a separate `design_provider_binding` package. It consumes immutable Step30 execution contracts plus a caller-assembled `ProviderExecutionSnapshot`, validates closed-world native identity and provider-candidate evidence, deterministically selects one provider candidate per Unit, invokes an injected `ProviderBindingAdapter`, validates returned native material, and computes canonical SHA-256 binding identities. Step31 never live-queries Host/provider services, never falls back after Adapter failure, never emits `ExecutionGrant`/`HostCommand`, and never branches on Host-specific types.

**Tech Stack:** Python 3.11, frozen dataclasses, `MappingProxyType`, `typing.Protocol`, Step29 `canonical_hash`, `jsonschema>=4.20`, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-step31-provider-binding-design.md`

## Global Constraints

- Base: `main@69dbe0886c7a2fe497ed58bf3b82676007a667dd`; branch: `feat/step31-provider-binding`.
- Distribution: `design-provider-binding`; source package: `design_provider_binding`.
- Step31 consumes Step30 `ExecutionSlice`, `ExecutionUnit`, and `HostRuntimeRef` as immutable upstream truth.
- v1 invariant: `1 ExecutionUnit = exactly 1 ProviderBinding`.
- v1 invariant: `1 ExecutionSlice = exactly 1 ProviderExecutionSnapshot + exactly 1 ProviderBindingSet`.
- Step31 MUST NOT split, merge, rewrite, reorder, or reinterpret canonical Units or approved scope.
- Step31 MUST NOT live-query D3, HostBinding storage, Host sidecars, MCP sessions, health/license/certification services, policy engines, or Host APIs during resolution.
- Snapshot native bindings are closed-world for the union of Slice Unit targets; missing/conflicting/extraneous rows fail closed.
- `host_instance_id` belongs to Step30 `HostRuntimeRef`; persistent native evidence contains semantic id + host type + document + native id + native kind + fingerprint.
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
- Provider switch MUST leave Step29/30 ChangeSet/Unit/Slice hashes unchanged and change Step31 Binding/set hashes.
- `admission_time` is explicit UTC input used only for expiry admission; resolver code MUST NOT read wall-clock time.
- Step31 MUST NOT create/read `ApprovalRecord`, `ExecutionGrant`, `HostCommand`, dispatch/retry/idempotency state, ActualDelta, verification result, rollback execution, or Saga state.
- Production Step31 code changes only under `platform/provider_binding/`; root `pyproject.toml` only adds the Step31 pytest path. Tests live under `tests/provider_binding/`; CI lives in `.github/workflows/step31-provider-binding.yml`.

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

Create `.github/workflows/step31-provider-binding.yml`:

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

Write `tests/provider_binding/test_step31_contracts.py` with concrete shape/immutability tests:

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

    constraint = NativeConstraint(
        "native_kind",
        NativeConstraintOperator.IN,
        ("Wall", "Wall", "Door"),
    )
    assert constraint.values == ("Door", "Wall")


def test_native_binding_evidence_is_frozen(digest_fn):
    from design_provider_binding import NativeTargetBindingEvidence

    value = NativeTargetBindingEvidence(
        "WALL-001",
        "REVIT",
        "DOC-1",
        "42",
        "Wall",
        digest_fn("host-binding"),
    )
    with pytest.raises(FrozenInstanceError):
        value.native_id = "43"
```

Add tests for:
- only `native_kind` accepted as `NativeConstraint.field`;
- `EQ` exactly one value; `IN` at least one normalized unique value;
- digest fields only lowercase 64-hex;
- `policy_priority` integer `>= 0` and booleans rejected;
- candidate state fields normalize to `EligibilityState`;
- mappings are defensively copied with read-only outer mapping;
- tuple members are type checked;
- UTC timestamps accept `Z` and `+00:00`, normalize to `Z`, reject naive/non-UTC offsets;
- `ProviderBindingRequest.admission_time` uses same UTC normalization;
- `ProviderBindingMaterial.provider_preconditions` may be empty;
- `ProviderBindingSet.bindings` requires at least one real `ProviderBinding` object.

- [ ] **Step 2: Add real Step30 DTO/hash fixtures**

Create `tests/provider_binding/conftest.py`:

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
        ChangePrecondition(
            PreconditionKind.OPERATION_FRESHNESS,
            "move.v1",
            digest("freshness"),
        ),
        ChangePrecondition(
            PreconditionKind.COVERAGE,
            "move.v1",
            digest("coverage"),
        ),
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

    units = (
        unit("operation-wall", "WALL-001"),
        unit("operation-annotation", "ANNOTATION-002"),
    )
    host_ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    scope_ref = ApprovedExecutionScopeRef(
        "SCOPE-31",
        digest("scope"),
        "SLICE-SCOPE-31",
    )
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

Do not create a fake BindingSet fixture in Task 1. The first reusable `valid_binding_set` fixture is added in Task 6 and is produced by the real resolver.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

Expected: import failure specifically because `design_provider_binding` does not exist. Step30 fixture imports must succeed first.

- [ ] **Step 4: Implement package shell and exact frozen contracts**

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

Add to root `pyproject.toml` pytest `pythonpath` after execution planning:

```toml
"platform/provider_binding/src",
```

Create the following enums/error in `contracts.py`:

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

Create exact frozen DTO field order:

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

Use `deepcopy(dict(value))` + `MappingProxyType` for mapping fields, matching Step29/30. Normalize timestamps with:

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

`NativeConstraint.__post_init__` must reject fields other than `native_kind`; `EQ` has exactly one value; `IN` has at least one sorted unique value.

- [ ] **Step 5: Export only contracts and run GREEN**

Update the workflow install step: rename it `Install Step31 verification stack` and add:

```bash
-e platform/provider_binding \
```

after `-e platform/execution_planning`.

Run:

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
```

Expected: all contract tests pass.

- [ ] **Step 6: Commit Task 1**

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
- Consumes: Task 1 DTOs and public Step29 `design_changeset.canonical_hash`.
- Produces: `compute_host_binding_fingerprint`, `compute_candidate_fingerprint`, `compute_provider_snapshot_hash`, `compute_precondition_fingerprint`, `compute_binding_hash`, `compute_binding_set_hash`, `validate_provider_binding`, `validate_provider_binding_set_hash`.

- [ ] **Step 1: Write hashing RED tests and add workflow step**

Add:

```yaml
      - name: Run Step31 hashing tests
        run: pytest -q tests/provider_binding/test_step31_hashing.py
```

Tests must prove:
- HostBinding fingerprint binds semantic id/host/document/native id/native kind exactly;
- candidate fingerprint changes when any frozen candidate semantic field changes;
- compatible-version and constraint ordering normalize deterministically;
- snapshot hash is invariant to candidate/native-row ordering but preserves duplicate-row multiplicity;
- snapshot id is excluded from snapshot hash;
- precondition fingerprint binds kind/subject/evidence exactly;
- binding hash is invariant to native-target/provider-precondition ordering;
- binding hash changes when provider server/tool/version/candidate fingerprint/adapter version/host instance/document/native identity/provider args/provider preconditions/native metadata/verification/rollback/expiry changes;
- binding hash function has no snapshot id/hash parameters;
- binding-set hash is order invariant and changes when any full Binding hash changes;
- supplied Binding hash/id mismatch gives `PROVIDER_BINDING_HASH_MISMATCH`;
- supplied BindingSet hash/id mismatch gives `PROVIDER_BINDING_SET_INVALID`.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_hashing.py
```

Expected: the hash module/public helpers do not exist.

- [ ] **Step 3: Implement canonical hash helpers using Step29 `canonical_hash`**

Do not copy a JSON encoder. Import:

```python
from collections.abc import Iterable, Mapping
from typing import Any

from design_changeset import ChangePrecondition, canonical_hash
```

HostBinding fingerprint:

```python
def compute_host_binding_fingerprint(value: NativeTargetBindingEvidence) -> str:
    return canonical_hash(
        {
            "semantic_id": value.semantic_id,
            "host_type": value.host_type,
            "document_ref": value.document_ref,
            "native_id": value.native_id,
            "native_kind": value.native_kind,
        }
    )
```

Candidate fingerprint payload contains every candidate semantic field from the spec. Normalize each native constraint as:

```python
{
    "field": constraint.field,
    "operator": constraint.operator.value,
    "values": list(constraint.values),
}
```

Snapshot hash uses full normalized native rows and full normalized candidate rows including their candidate fingerprints:

```python
canonical_hash(
    {
        "execution_slice_hash": snapshot.execution_slice_hash,
        "host_runtime_ref": {
            "host_type": snapshot.host_runtime_ref.host_type,
            "host_instance_id": snapshot.host_runtime_ref.host_instance_id,
            "document_ref": snapshot.host_runtime_ref.document_ref,
        },
        "native_target_bindings": sorted(native_payloads, key=native_sort_key),
        "provider_candidates": sorted(candidate_payloads, key=candidate_sort_key),
        "valid_until": snapshot.valid_until,
    }
)
```

Use lists rather than sets so duplicate evidence remains observable.

Precondition fingerprint:

```python
def compute_precondition_fingerprint(precondition: ChangePrecondition) -> str:
    return canonical_hash(
        {
            "kind": precondition.kind.value,
            "subject_ref": precondition.subject_ref,
            "evidence_ref": precondition.evidence_ref,
        }
    )
```

Define the Binding hash helper with the exact explicit signature:

```python
def compute_binding_hash(
    *,
    execution_unit_hash: str,
    execution_slice_hash: str,
    canonical_operation: str,
    provider_server: str,
    provider_tool: str,
    provider_version: str,
    selected_candidate_fingerprint: str,
    host_instance_id: str,
    document_ref: str,
    input_adapter_version: str,
    native_targets: Iterable[NativeTargetBindingEvidence],
    provider_arguments: Mapping[str, Any],
    provider_preconditions: Iterable[ProviderPreconditionBinding],
    native_binding_metadata: Mapping[str, Any],
    verification_contract: Mapping[str, Any],
    rollback_contract: Mapping[str, Any],
    binding_expires_at: str,
) -> str:
    return canonical_hash(
        {
            "execution_unit_hash": execution_unit_hash,
            "execution_slice_hash": execution_slice_hash,
            "canonical_operation": canonical_operation,
            "provider_server": provider_server,
            "provider_tool": provider_tool,
            "provider_version": provider_version,
            "selected_candidate_fingerprint": selected_candidate_fingerprint,
            "host_instance_id": host_instance_id,
            "document_ref": document_ref,
            "input_adapter_version": input_adapter_version,
            "native_targets": sorted(
                (_native_target_payload(item) for item in native_targets),
                key=_native_target_sort_key,
            ),
            "provider_arguments": provider_arguments,
            "provider_preconditions": sorted(
                (_provider_precondition_payload(item) for item in provider_preconditions),
                key=lambda item: (
                    item["source_precondition_fingerprint"],
                    canonical_hash(item["provider_precondition"]),
                ),
            ),
            "native_binding_metadata": native_binding_metadata,
            "verification_contract": verification_contract,
            "rollback_contract": rollback_contract,
            "binding_expires_at": binding_expires_at,
        }
    )
```

Binding-set hash:

```python
def compute_binding_set_hash(
    *,
    execution_slice_hash: str,
    binding_hashes: Iterable[str],
) -> str:
    return canonical_hash(
        {
            "execution_slice_hash": execution_slice_hash,
            "binding_hashes": sorted(binding_hashes),
        }
    )
```

Do not deduplicate Binding hashes in this helper.

- [ ] **Step 4: Implement supplied-hash validators with explicit hash arguments**

```python
def validate_provider_binding(binding: ProviderBinding) -> None:
    expected = compute_binding_hash(
        execution_unit_hash=binding.execution_unit_hash,
        execution_slice_hash=binding.execution_slice_hash,
        canonical_operation=binding.canonical_operation,
        provider_server=binding.provider_server,
        provider_tool=binding.provider_tool,
        provider_version=binding.provider_version,
        selected_candidate_fingerprint=binding.selected_candidate_fingerprint,
        host_instance_id=binding.host_instance_id,
        document_ref=binding.document_ref,
        input_adapter_version=binding.input_adapter_version,
        native_targets=binding.native_targets,
        provider_arguments=binding.provider_arguments,
        provider_preconditions=binding.provider_preconditions,
        native_binding_metadata=binding.native_binding_metadata,
        verification_contract=binding.verification_contract,
        rollback_contract=binding.rollback_contract,
        binding_expires_at=binding.binding_expires_at,
    )
    if binding.binding_hash != expected or binding.binding_id != f"PB-{expected[:12]}":
        raise ProviderBindingError(
            "PROVIDER_BINDING_HASH_MISMATCH",
            "provider binding hash/id mismatch",
        )


def validate_provider_binding_set_hash(binding_set: ProviderBindingSet) -> None:
    expected = compute_binding_set_hash(
        execution_slice_hash=binding_set.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in binding_set.bindings),
    )
    if (
        binding_set.binding_set_hash != expected
        or binding_set.binding_set_id != f"PBS-{expected[:12]}"
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_SET_INVALID",
            "provider binding set hash/id mismatch",
        )
```

- [ ] **Step 5: Export helpers, run GREEN, commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py

git add \
  platform/provider_binding/src/design_provider_binding \
  tests/provider_binding/test_step31_hashing.py \
  .github/workflows/step31-provider-binding.yml
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

- [ ] **Step 1: Write Adapter RED tests and add workflow step**

Add:

```yaml
      - name: Run Step31 adapter tests
        run: pytest -q tests/provider_binding/test_step31_adapters.py
```

Tests cover:
- `EQ` and `IN` over opaque `native_kind`;
- every Unit native target must satisfy every constraint;
- empty constraint tuple passes;
- direct failed validation raises `PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED`;
- registering the same Adapter object twice is idempotent;
- different Adapter on same provider server raises `PROVIDER_ADAPTER_CONFLICT`;
- missing provider server raises `PROVIDER_ADAPTER_UNAVAILABLE`;
- Adapter version mismatch raises `PROVIDER_ADAPTER_UNAVAILABLE`;
- registration order does not affect lookup.

- [ ] **Step 2: Add deterministic fake Adapter support in `conftest.py`**

```python
class FakeBindingAdapter:
    def __init__(
        self,
        *,
        adapter_version="1.0.0",
        material_factory=None,
        error=None,
    ):
        self.adapter_version = adapter_version
        self.material_factory = material_factory
        self.error = error
        self.calls = []

    def bind(
        self,
        execution_unit,
        host_runtime_ref,
        selected_candidate,
        native_target_bindings,
    ):
        self.calls.append(
            (
                execution_unit,
                host_runtime_ref,
                selected_candidate,
                native_target_bindings,
            )
        )
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

The default candidate fixture schema must require exactly `native_ids`, `operation`, and `canonical_arguments`, with `additionalProperties: false`.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_adapters.py
```

Expected: Adapter module/public exports are absent.

- [ ] **Step 4: Implement Protocol, registry, and generic native-constraint evaluator**

```python
class ProviderBindingAdapter(Protocol):
    adapter_version: str

    def bind(
        self,
        execution_unit: ExecutionUnit,
        host_runtime_ref: HostRuntimeRef,
        selected_candidate: ProviderExecutionCandidate,
        native_target_bindings: tuple[NativeTargetBindingEvidence, ...],
    ) -> ProviderBindingMaterial:
        raise NotImplementedError
```

Registry core:

```python
class ProviderBindingAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderBindingAdapter] = {}

    def register(self, provider_server: str, adapter: ProviderBindingAdapter) -> None:
        key = provider_server.strip()
        if not key:
            raise ProviderBindingError(
                "PROVIDER_BINDING_INPUT_INVALID",
                "provider_server is required",
            )
        existing = self._adapters.get(key)
        if existing is None:
            self._adapters[key] = adapter
            return
        if existing is adapter:
            return
        raise ProviderBindingError(
            "PROVIDER_ADAPTER_CONFLICT",
            f"conflicting adapter for {key}",
        )

    def require(
        self,
        provider_server: str,
        input_adapter_version: str,
    ) -> ProviderBindingAdapter:
        adapter = self._adapters.get(provider_server)
        if (
            adapter is None
            or str(adapter.adapter_version).strip() != input_adapter_version
        ):
            raise ProviderBindingError(
                "PROVIDER_ADAPTER_UNAVAILABLE",
                "required provider adapter/version unavailable",
            )
        return adapter
```

The constraint evaluator may switch only on `NativeConstraintOperator` and the already-validated generic field `native_kind`; no provider/Host-specific literals.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py

git add \
  platform/provider_binding/src/design_provider_binding \
  tests/provider_binding \
  .github/workflows/step31-provider-binding.yml
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

- [ ] **Step 1: Add snapshot/selection RED tests and workflow step**

Add:

```yaml
      - name: Run Step31 snapshot and selection tests
        run: pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Extend `conftest.py` after Task 2 helpers exist with deterministic factories:

```python
def make_native_binding(semantic_id, *, native_id, native_kind="Wall"):
    provisional = NativeTargetBindingEvidence(
        semantic_id,
        "REVIT",
        "DOC-1",
        native_id,
        native_kind,
        digest("temporary-host-binding"),
    )
    return replace(
        provisional,
        host_binding_fingerprint=compute_host_binding_fingerprint(provisional),
    )


def make_candidate(
    *,
    provider_server="provider.revit.a",
    provider_tool="move",
    provider_version="1.0.0",
    priority=10,
    native_kinds=("Wall",),
    state=EligibilityState.SATISFIED,
):
    provisional = ProviderExecutionCandidate(
        provider_server,
        provider_tool,
        provider_version,
        "move.v1",
        ("1.0.0",),
        "1.0.0",
        (NativeConstraint("native_kind", NativeConstraintOperator.IN, native_kinds),),
        DEFAULT_PROVIDER_INPUT_SCHEMA,
        {"read_back": "required"},
        {"mode": "compensating_changeset"},
        state,
        state,
        state,
        state,
        state,
        priority,
        digest("temporary-candidate"),
    )
    return replace(
        provisional,
        candidate_fingerprint=compute_candidate_fingerprint(provisional),
    )
```

Build snapshot/request factories the same way: create a valid DTO with a temporary 64-hex digest, then replace it with `compute_provider_snapshot_hash(snapshot)`. This makes every “valid” fixture use the same public hashing rules the resolver verifies.

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

Selection tests prove:
- canonical operation mismatch filters candidate;
- incompatible Unit operation version filters candidate;
- native constraint failure filters candidate;
- any of trust/compatibility/health/license/certification not `SATISFIED` filters candidate;
- `UNKNOWN` fails eligibility just like `UNSATISFIED`;
- all filtered → `PROVIDER_CANDIDATE_UNAVAILABLE`;
- lower `policy_priority` wins;
- equal priority uses provider server/tool/version lexical identity;
- candidate list order does not alter winner;
- repeated winning ranking identity → `PROVIDER_CANDIDATE_AMBIGUOUS` whether fingerprints match or differ.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
```

Expected: resolver helpers are absent.

- [ ] **Step 3: Implement snapshot validation in this exact order**

```text
1. snapshot execution_slice_id/hash/HostRuntimeRef == Slice
2. each native row host_type/document_ref == Slice HostRuntimeRef
3. recompute every HostBinding fingerprint
4. detect duplicate native semantic ids before set comparison
5. exact closed-world required-target coverage
6. every candidate canonical operation belongs to at least one Unit in Slice
7. validate candidate input JSON Schema
8. recompute every candidate fingerprint
9. recompute snapshot hash
10. require admission_time < valid_until
```

Candidate schema validation:

```python
validator_cls = jsonschema.validators.validator_for(
    dict(candidate.provider_input_schema)
)
try:
    validator_cls.check_schema(dict(candidate.provider_input_schema))
except jsonschema.SchemaError as exc:
    raise ProviderBindingError(
        "PROVIDER_CANDIDATE_INVALID",
        "provider input schema is invalid",
    ) from exc
```

Do not call Adapter registry on this validation path.

- [ ] **Step 4: Implement candidate filter/rank exactly**

Eligibility:

```python
def _candidate_is_eligible(candidate, unit, unit_native_targets):
    return (
        candidate.canonical_operation == unit.canonical_operation
        and unit.canonical_operation_version
        in candidate.compatible_operation_versions
        and native_constraints_satisfied(
            candidate.provider_native_constraints,
            unit_native_targets,
        )
        and candidate.trust_state is EligibilityState.SATISFIED
        and candidate.compatibility_state is EligibilityState.SATISFIED
        and candidate.health_state is EligibilityState.SATISFIED
        and candidate.license_state is EligibilityState.SATISFIED
        and candidate.certification_state is EligibilityState.SATISFIED
    )
```

Ranking key:

```python
def _candidate_rank(candidate):
    return (
        candidate.policy_priority,
        candidate.provider_server,
        candidate.provider_tool,
        candidate.provider_version,
    )
```

If no eligible candidate, raise `PROVIDER_CANDIDATE_UNAVAILABLE`. Sort by `_candidate_rank`; if more than one eligible row has the winning 4-tuple, raise `PROVIDER_CANDIDATE_AMBIGUOUS`. Never inspect candidate fingerprint to resolve the tie.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py

git add \
  platform/provider_binding/src/design_provider_binding \
  tests/provider_binding \
  .github/workflows/step31-provider-binding.yml
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
- Consumes Tasks 1–4 plus injected `ProviderBindingAdapterRegistry`.
- Produces public `ProviderResolver(adapter_registry)` and `resolve(request: ProviderBindingRequest) -> ProviderBindingSet`.

- [ ] **Step 1: Add resolver RED tests and workflow step**

Add:

```yaml
      - name: Run Step31 resolver tests
        run: pytest -q tests/provider_binding/test_step31_resolver.py
```

Required tests:
- each Unit produces exactly one Binding;
- Binding copies exact Unit id/hash/canonical operation and Slice id/hash/host instance/document;
- selected provider identity/version/adapter version comes from candidate/registry, never Adapter-return material;
- `binding_expires_at == snapshot.valid_until`;
- Adapter receives only the current Unit's exact native rows;
- Adapter native targets missing/extra/substituted/duplicate → `PROVIDER_NATIVE_TARGET_MISMATCH`;
- each Adapter native target row must equal frozen verified snapshot evidence;
- provider preconditions may be empty;
- emitted precondition source fingerprint must reference a real Unit precondition and be unique;
- duplicate/unknown precondition source ref → `PROVIDER_BINDING_ADAPTATION_FAILED`;
- provider arguments failing selected schema → `PROVIDER_INPUT_SCHEMA_INVALID`;
- Adapter wrong return type/exception → `PROVIDER_BINDING_ADAPTATION_FAILED`;
- selected Adapter is invoked exactly once;
- a valid lower-ranked Adapter is not called after selected Adapter failure;
- missing/version-mismatched selected Adapter → `PROVIDER_ADAPTER_UNAVAILABLE`, no fallback;
- Binding id equals `PB-{binding_hash[:12]}` and `validate_provider_binding` succeeds.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_resolver.py
```

Expected: `ProviderResolver` is absent.

- [ ] **Step 3: Implement resolver construction and deterministic pipeline**

```python
class ProviderResolver:
    def __init__(self, adapter_registry: ProviderBindingAdapterRegistry) -> None:
        if not isinstance(adapter_registry, ProviderBindingAdapterRegistry):
            raise TypeError(
                "adapter_registry must be ProviderBindingAdapterRegistry"
            )
        self._adapter_registry = adapter_registry
```

Resolve order:

```text
_validate_request_and_snapshot(request)
→ native_by_semantic_id
→ validated candidates
→ iterate Units sorted by execution_unit_hash
   → exact native rows for this Unit.targets
   → deterministic selected candidate
   → registry.require(provider_server, input_adapter_version)
   → call selected Adapter exactly once
   → validate material type
   → exact target identity gate
   → optional source-precondition reference gate
   → provider input-schema gate
   → compute full binding_hash
   → construct PB-<hash-prefix>
   → validate_provider_binding(binding)
→ sort Bindings by execution_unit_hash
→ compute binding_set_hash from full Binding hashes
→ construct ProviderBindingSet with snapshot provenance fields
```

Catch only exceptions thrown by the Adapter's `bind()`:

```python
try:
    material = adapter.bind(
        unit,
        slice_.host_runtime_ref,
        selected,
        unit_native_targets,
    )
except Exception as exc:
    raise ProviderBindingError(
        "PROVIDER_BINDING_ADAPTATION_FAILED",
        "selected provider adapter failed",
    ) from exc
```

Do not catch `PROVIDER_ADAPTER_UNAVAILABLE` and select another candidate.

- [ ] **Step 4: Implement exact Adapter output integrity gates**

Native target gate:

```python
returned = tuple(material.native_targets)
returned_ids = tuple(item.semantic_id for item in returned)
if (
    len(returned) != len(unit.targets)
    or len(set(returned_ids)) != len(returned_ids)
    or set(returned_ids) != set(unit.targets)
    or any(item != native_by_semantic_id[item.semantic_id] for item in returned)
):
    raise ProviderBindingError(
        "PROVIDER_NATIVE_TARGET_MISMATCH",
        "adapter native targets do not match frozen native evidence",
    )
```

Optional precondition gate:

```python
source_fingerprints = {
    compute_precondition_fingerprint(item)
    for item in unit.preconditions
}
seen = set()
for item in material.provider_preconditions:
    if (
        item.source_precondition_fingerprint not in source_fingerprints
        or item.source_precondition_fingerprint in seen
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_ADAPTATION_FAILED",
            "provider precondition source reference is invalid",
        )
    seen.add(item.source_precondition_fingerprint)
```

Provider argument schema gate:

```python
validator_cls = jsonschema.validators.validator_for(
    dict(selected.provider_input_schema)
)
validator = validator_cls(dict(selected.provider_input_schema))
try:
    validator.validate(dict(material.provider_arguments))
except jsonschema.ValidationError as exc:
    raise ProviderBindingError(
        "PROVIDER_INPUT_SCHEMA_INVALID",
        "provider arguments do not satisfy provider input schema",
    ) from exc
```

- [ ] **Step 5: Compute Binding hash with all explicit selected execution material**

The resolver call must use the same exact argument list frozen in Task 2:

```python
binding_hash = compute_binding_hash(
    execution_unit_hash=unit.execution_unit_hash,
    execution_slice_hash=slice_.execution_slice_hash,
    canonical_operation=unit.canonical_operation,
    provider_server=selected.provider_server,
    provider_tool=selected.provider_tool,
    provider_version=selected.provider_version,
    selected_candidate_fingerprint=selected.candidate_fingerprint,
    host_instance_id=slice_.host_runtime_ref.host_instance_id,
    document_ref=slice_.host_runtime_ref.document_ref,
    input_adapter_version=selected.input_adapter_version,
    native_targets=material.native_targets,
    provider_arguments=material.provider_arguments,
    provider_preconditions=material.provider_preconditions,
    native_binding_metadata=material.native_binding_metadata,
    verification_contract=selected.verification_contract,
    rollback_contract=selected.rollback_contract,
    binding_expires_at=snapshot.valid_until,
)
```

Construct `ProviderBinding` with `binding_id=f"PB-{binding_hash[:12]}"`. Verification/rollback contracts come from selected candidate; native metadata comes from Adapter; expiry comes from snapshot. Snapshot id/hash do not enter Binding hash.

Construct preliminary set:

```python
binding_set_hash = compute_binding_set_hash(
    execution_slice_hash=slice_.execution_slice_hash,
    binding_hashes=(item.binding_hash for item in bindings),
)
binding_set = ProviderBindingSet(
    f"PBS-{binding_set_hash[:12]}",
    slice_.execution_slice_id,
    slice_.execution_slice_hash,
    snapshot.snapshot_id,
    snapshot.snapshot_hash,
    tuple(sorted(bindings, key=lambda item: item.execution_unit_hash)),
    binding_set_hash,
)
```

- [ ] **Step 6: Export Resolver, run GREEN, commit**

```bash
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
pytest -q tests/provider_binding/test_step31_resolver.py

git add \
  platform/provider_binding/src/design_provider_binding \
  tests/provider_binding \
  .github/workflows/step31-provider-binding.yml
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
- Resolver self-validates its result through this public path before return.

- [ ] **Step 1: Add BindingSet RED tests and workflow step**

Add:

```yaml
      - name: Run Step31 binding-set tests
        run: pytest -q tests/provider_binding/test_step31_binding_set.py
```

Required tests:
- missing/duplicate/extraneous Unit Binding → `PROVIDER_BINDING_SET_INVALID`;
- Binding Slice id/hash mismatch → `PROVIDER_BINDING_SET_INVALID`;
- Binding Unit hash differs from exact Slice Unit → `PROVIDER_BINDING_SET_INVALID`;
- set hash equals computation over full 64-hex Binding hashes;
- reversing snapshot native rows/candidates leaves output identity unchanged;
- registering Adapters in opposite order leaves output identity unchanged;
- two admission times strictly before same expiry produce identical Binding semantics/hash;
- changing only an unused candidate body/fingerprint and recomputing snapshot hash changes snapshot provenance but not selected Binding hashes/set hash;
- changing only policy priority so another provider wins leaves exact Step30 Slice/Unit hashes unchanged but changes Step31 Binding/set hashes;
- changing only `valid_until` changes Binding/set hashes because expiry is authorization material.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/provider_binding/test_step31_binding_set.py
```

Expected: structural validator does not exist.

- [ ] **Step 3: Implement exact structural validator**

```python
def validate_provider_binding_set(
    binding_set: ProviderBindingSet,
    execution_slice: ExecutionSlice,
) -> None:
    if (
        binding_set.execution_slice_id != execution_slice.execution_slice_id
        or binding_set.execution_slice_hash != execution_slice.execution_slice_hash
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_SET_INVALID",
            "binding set slice mismatch",
        )

    for binding in binding_set.bindings:
        validate_provider_binding(binding)
        if (
            binding.execution_slice_id != execution_slice.execution_slice_id
            or binding.execution_slice_hash != execution_slice.execution_slice_hash
        ):
            raise ProviderBindingError(
                "PROVIDER_BINDING_SET_INVALID",
                "binding references wrong slice",
            )

    units = {
        unit.execution_unit_id: unit
        for unit in execution_slice.execution_units
    }
    bindings = {
        binding.execution_unit_id: binding
        for binding in binding_set.bindings
    }
    if (
        len(bindings) != len(binding_set.bindings)
        or set(bindings) != set(units)
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_SET_INVALID",
            "binding set unit coverage mismatch",
        )

    if any(
        bindings[unit_id].execution_unit_hash
        != units[unit_id].execution_unit_hash
        for unit_id in units
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_SET_INVALID",
            "binding set unit hash mismatch",
        )

    validate_provider_binding_set_hash(binding_set)
```

A corrupted individual Binding hash may retain `PROVIDER_BINDING_HASH_MISMATCH`; structural set mismatches use `PROVIDER_BINDING_SET_INVALID`.

- [ ] **Step 4: Make Resolver self-validate and introduce only real BindingSet fixture**

Before resolver return:

```python
validate_provider_binding_set(binding_set, slice_)
return binding_set
```

Add in `conftest.py`:

```python
@pytest.fixture
def valid_binding_set(valid_request, adapter_registry):
    return ProviderResolver(adapter_registry).resolve(valid_request)
```

No final Step31 test uses arbitrary precomputed Binding/set hashes.

- [ ] **Step 5: Run GREEN and commit**

```bash
pytest -q tests/provider_binding

git add \
  platform/provider_binding/src/design_provider_binding \
  tests/provider_binding \
  .github/workflows/step31-provider-binding.yml
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

- [ ] **Step 1: Add architecture guards**

Parse production Python only under `platform/provider_binding/src/design_provider_binding`. Through AST imports/names/attributes reject:

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

Reject production string constants exactly equal to:

```text
AUTOCAD
REVIT
TEKLA
```

Do not scan tests, fixtures, docs, or comments. Allow immutable `rollback_contract`; do not reject the generic word `rollback`.

Also assert `ProviderBinding` and `ProviderBindingRequest` field sets contain no approval/grant/HostCommand envelope fields.

- [ ] **Step 2: Run architecture tests**

```bash
pytest -q tests/provider_binding/test_step31_architecture.py
```

If a real violation is found, preserve that failing test and make the smallest production cleanup. Do not manufacture a production violation merely to force RED for this static-guard task.

- [ ] **Step 3: Extend workflow with PR boundary and final gates**

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

Final workflow sequence must be:

```text
Verify Step31 PR diff boundary
pytest -q tests/provider_binding/test_step31_contracts.py
pytest -q tests/provider_binding/test_step31_hashing.py
pytest -q tests/provider_binding/test_step31_adapters.py
pytest -q tests/provider_binding/test_step31_snapshot_and_selection.py
pytest -q tests/provider_binding/test_step31_resolver.py
pytest -q tests/provider_binding/test_step31_binding_set.py
pytest -q tests/provider_binding/test_step31_architecture.py
pytest -q tests/execution_planning
pytest -q tests/changeset
pytest -q tests/orchestrator/test_operation_resolver.py tests/orchestrator/test_step24_semantic_eligibility.py
ruff check platform/provider_binding/src/design_provider_binding tests/provider_binding
pytest -q --import-mode=importlib
```

- [ ] **Step 4: Commit architecture/CI gate**

```bash
git add \
  tests/provider_binding/test_step31_architecture.py \
  .github/workflows/step31-provider-binding.yml
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

Record fresh counts from this head. Historical Step30 counts are not Step31 evidence.

- [ ] **Step 6: Open a draft PR only after branch push CI is green**

Create:

```text
Title: Step31 deterministic provider binding
Base: main
Head: feat/step31-provider-binding
Draft: true
```

PR description records the spec path, exact head SHA, Step31 focused counts, Step30/29 regressions, resolver/capability regression result, Ruff, full-repo pytest, and explicitly states that Step31 core adds no Host-specific Adapter implementation or HostCommand dispatch.

- [ ] **Step 7: Require real PR-triggered exact-head evidence**

Require:

```text
Step31 provider-binding workflow = completed / success
Verify Step31 PR diff boundary    = success
```

If `main` moved after branch creation, check mergeability and the new merge-ref CI rather than reusing old evidence.

- [ ] **Step 8: Perform spec-to-implementation review before completion claim**

Manually inspect these high-risk invariants:

```text
snapshot provenance excluded from Binding/set semantic hashes
full 64-hex Binding hashes used in set hash
candidate fingerprint never used as ranking tie-breaker
no exception-driven fallback
unused candidate may change snapshot hash without changing Binding identity
binding expiry is hash material
optional native preconditions do not replace Step30 canonical preconditions
Adapter cannot provide canonical/provider identity fields
no Host-specific branches/imports
no Step32/33 runtime concepts
```

Any mismatch receives its own RED test before the production fix.

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

Because head changes, all prior “final” evidence is stale. Re-run Step31 push + PR CI on the new exact head before reporting completion.

- [ ] **Step 10: Do not merge without explicit user instruction**

Leave the PR unmerged until the user explicitly asks for merge.

---

## Final Acceptance Checklist

```text
[ ] ProviderBindingRequest contains exactly Slice + snapshot + admission_time
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
[ ] unused-candidate-only changes can leave Binding/set identity stable
[ ] binding_set_hash uses full 64-hex Binding hashes
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
