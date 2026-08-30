from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from types import MappingProxyType

import pytest
from design_execution_planning import HostRuntimeRef
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingMaterial,
    ProviderBindingRequest,
    ProviderBindingSet,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
)


def _candidate(digest_fn, **overrides):
    values = {
        "provider_server": "provider.revit",
        "provider_tool": "element.move",
        "provider_version": "1.2.3",
        "canonical_operation": "move.v1",
        "compatible_operation_versions": ("1.0.0",),
        "input_adapter_version": "1.0.0",
        "provider_native_constraints": (
            NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Wall", "Annotation")),
        ),
        "provider_input_schema": {"type": "object"},
        "verification_contract": {"kind": "readback"},
        "rollback_contract": {"kind": "inverse"},
        "trust_state": EligibilityState.SATISFIED,
        "compatibility_state": EligibilityState.SATISFIED,
        "health_state": EligibilityState.SATISFIED,
        "license_state": EligibilityState.SATISFIED,
        "certification_state": EligibilityState.SATISFIED,
        "policy_priority": 10,
        "candidate_fingerprint": digest_fn("candidate"),
    }
    values.update(overrides)
    return ProviderExecutionCandidate(**values)


def _snapshot(execution_slice, digest_fn, **overrides):
    bindings = tuple(
        NativeTargetBindingEvidence(
            target,
            execution_slice.host_runtime_ref.host_type,
            execution_slice.host_runtime_ref.document_ref,
            f"NATIVE-{index}",
            "Wall" if index == 1 else "Annotation",
            digest_fn(f"host-binding-{target}"),
        )
        for index, target in enumerate(
            (target for unit in execution_slice.execution_units for target in unit.targets),
            start=1,
        )
    )
    values = {
        "snapshot_id": "PES-31",
        "execution_slice_id": execution_slice.execution_slice_id,
        "execution_slice_hash": execution_slice.execution_slice_hash,
        "host_runtime_ref": execution_slice.host_runtime_ref,
        "native_target_bindings": bindings,
        "provider_candidates": (_candidate(digest_fn),),
        "valid_until": "2026-08-30T10:30:00Z",
        "snapshot_hash": digest_fn("snapshot"),
    }
    values.update(overrides)
    return ProviderExecutionSnapshot(**values)


def test_provider_binding_request_has_no_provider_choice_or_grant_fields(
    execution_slice, digest_fn
):
    names = {field.name for field in fields(ProviderBindingRequest)}
    assert names == {"execution_slice", "provider_execution_snapshot", "admission_time"}
    assert {"provider_server", "provider_tool", "approval_id", "execution_grant"}.isdisjoint(names)
    request = ProviderBindingRequest(
        execution_slice,
        _snapshot(execution_slice, digest_fn),
        "2026-08-30T10:00:00+00:00",
    )
    assert request.admission_time == "2026-08-30T10:00:00Z"


def test_provider_binding_has_no_host_command_or_approval_fields():
    names = {field.name for field in fields(ProviderBinding)}
    assert {"command_id", "idempotency_key", "approval_id", "execution_grant"}.isdisjoint(names)


def test_native_constraint_normalizes_in_values():
    constraint = NativeConstraint(
        "native_kind",
        NativeConstraintOperator.IN,
        ("Wall", "Wall", "Door"),
    )
    assert constraint.values == ("Door", "Wall")


def test_native_constraint_rejects_unsupported_field_and_invalid_cardinality():
    with pytest.raises(ValueError):
        NativeConstraint("layer", NativeConstraintOperator.EQ, ("A",))
    with pytest.raises(ValueError):
        NativeConstraint("native_kind", NativeConstraintOperator.EQ, ("Wall", "Door"))
    with pytest.raises(ValueError):
        NativeConstraint("native_kind", NativeConstraintOperator.IN, ())


def test_native_binding_evidence_is_frozen(digest_fn):
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


def test_digest_fields_require_lowercase_sha256():
    with pytest.raises(ValueError):
        NativeTargetBindingEvidence("WALL-001", "REVIT", "DOC-1", "42", "Wall", "A" * 64)


def test_candidate_normalizes_states_priority_and_mappings(digest_fn):
    schema = {"type": "object", "properties": {"distance": {"type": "number"}}}
    candidate = _candidate(
        digest_fn,
        provider_input_schema=schema,
        trust_state="SATISFIED",
    )
    schema["type"] = "array"
    assert candidate.trust_state is EligibilityState.SATISFIED
    assert candidate.policy_priority == 10
    assert candidate.provider_input_schema["type"] == "object"
    assert isinstance(candidate.provider_input_schema, MappingProxyType)
    with pytest.raises(TypeError):
        candidate.provider_input_schema["type"] = "array"
    with pytest.raises(TypeError):
        _candidate(digest_fn, policy_priority=True)
    with pytest.raises(ValueError):
        _candidate(digest_fn, policy_priority=-1)


def test_candidate_rejects_invalid_tuple_members(digest_fn):
    with pytest.raises(TypeError):
        _candidate(digest_fn, provider_native_constraints=("not-a-constraint",))


def test_snapshot_normalizes_utc_and_rejects_non_utc(execution_slice, digest_fn):
    snapshot = _snapshot(
        execution_slice,
        digest_fn,
        valid_until="2026-08-30T10:30:00+00:00",
    )
    assert snapshot.valid_until == "2026-08-30T10:30:00Z"
    with pytest.raises(ValueError):
        _snapshot(execution_slice, digest_fn, valid_until="2026-08-30T10:30:00")
    with pytest.raises(ValueError):
        _snapshot(execution_slice, digest_fn, valid_until="2026-08-30T18:30:00+08:00")


def test_binding_material_allows_empty_provider_preconditions(digest_fn):
    target = NativeTargetBindingEvidence(
        "WALL-001",
        "REVIT",
        "DOC-1",
        "42",
        "Wall",
        digest_fn("binding-material-target"),
    )
    material = ProviderBindingMaterial((target,), {"distance": 1.0}, (), {"mode": "native"})
    assert material.provider_preconditions == ()
    assert isinstance(material.provider_arguments, MappingProxyType)
    assert isinstance(material.native_binding_metadata, MappingProxyType)


def test_binding_set_requires_real_binding_member(digest_fn):
    with pytest.raises((TypeError, ValueError)):
        ProviderBindingSet(
            "PBS-123",
            "XS-123",
            digest_fn("slice"),
            "PES-31",
            digest_fn("snapshot"),
            (),
            digest_fn("binding-set"),
        )


def test_request_rejects_wrong_upstream_types(execution_slice, digest_fn):
    snapshot = _snapshot(execution_slice, digest_fn)
    with pytest.raises(TypeError):
        ProviderBindingRequest("not-a-slice", snapshot, "2026-08-30T10:00:00Z")
    with pytest.raises(TypeError):
        ProviderBindingRequest(execution_slice, "not-a-snapshot", "2026-08-30T10:00:00Z")
    with pytest.raises(ValueError):
        ProviderBindingRequest(execution_slice, snapshot, "2026-08-30T18:00:00+08:00")


def test_snapshot_requires_host_runtime_ref(execution_slice, digest_fn):
    with pytest.raises(TypeError):
        _snapshot(execution_slice, digest_fn, host_runtime_ref="not-a-ref")
    assert isinstance(_snapshot(execution_slice, digest_fn).host_runtime_ref, HostRuntimeRef)
