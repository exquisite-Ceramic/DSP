from __future__ import annotations

from dataclasses import replace
from inspect import signature

import pytest
from design_changeset import ChangePrecondition, PreconditionKind, canonical_hash
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingError,
    ProviderBindingSet,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
    ProviderPreconditionBinding,
    compute_binding_hash,
    compute_binding_set_hash,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_precondition_fingerprint,
    compute_provider_snapshot_hash,
    validate_provider_binding,
    validate_provider_binding_set_hash,
)


def _candidate(digest_fn, **overrides) -> ProviderExecutionCandidate:
    values = {
        "provider_server": "provider.revit",
        "provider_tool": "element.move",
        "provider_version": "1.2.3",
        "canonical_operation": "move.v1",
        "compatible_operation_versions": ("1.1.0", "1.0.0"),
        "input_adapter_version": "1.0.0",
        "provider_native_constraints": (
            NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Wall", "Annotation")),
            NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Annotation", "Wall")),
        ),
        "provider_input_schema": {"type": "object", "required": ["distance"]},
        "verification_contract": {"kind": "readback"},
        "rollback_contract": {"kind": "inverse"},
        "trust_state": EligibilityState.SATISFIED,
        "compatibility_state": EligibilityState.SATISFIED,
        "health_state": EligibilityState.SATISFIED,
        "license_state": EligibilityState.SATISFIED,
        "certification_state": EligibilityState.SATISFIED,
        "policy_priority": 10,
        "candidate_fingerprint": digest_fn("candidate-supplied"),
    }
    values.update(overrides)
    return ProviderExecutionCandidate(**values)


def _native_rows(execution_slice, digest_fn):
    targets = tuple(target for unit in execution_slice.execution_units for target in unit.targets)
    return tuple(
        NativeTargetBindingEvidence(
            target,
            execution_slice.host_runtime_ref.host_type,
            execution_slice.host_runtime_ref.document_ref,
            f"NATIVE-{index}",
            "Wall" if index == 1 else "Annotation",
            digest_fn(f"host-binding-{target}"),
        )
        for index, target in enumerate(targets, start=1)
    )


def _binding_kwargs(execution_slice, digest_fn):
    unit = execution_slice.execution_units[0]
    native = _native_rows(execution_slice, digest_fn)[0]
    precondition = ProviderPreconditionBinding(
        compute_precondition_fingerprint(unit.preconditions[0]),
        {"revision": "R-31"},
    )
    return {
        "execution_unit_hash": unit.execution_unit_hash,
        "execution_slice_hash": execution_slice.execution_slice_hash,
        "canonical_operation": unit.canonical_operation,
        "provider_server": "provider.revit",
        "provider_tool": "element.move",
        "provider_version": "1.2.3",
        "selected_candidate_fingerprint": digest_fn("candidate-winner"),
        "host_instance_id": execution_slice.host_runtime_ref.host_instance_id,
        "document_ref": execution_slice.host_runtime_ref.document_ref,
        "input_adapter_version": "1.0.0",
        "native_targets": (native,),
        "provider_arguments": {"distance": 100.0},
        "provider_preconditions": (precondition,),
        "native_binding_metadata": {"variant": "default"},
        "verification_contract": {"kind": "readback"},
        "rollback_contract": {"kind": "inverse"},
        "binding_expires_at": "2026-08-30T10:30:00Z",
    }


def _binding(execution_slice, digest_fn, **overrides):
    kwargs = _binding_kwargs(execution_slice, digest_fn)
    kwargs.update(overrides)
    binding_hash = compute_binding_hash(**kwargs)
    unit = execution_slice.execution_units[0]
    return ProviderBinding(
        f"PB-{binding_hash[:12]}",
        unit.execution_unit_id,
        kwargs["execution_unit_hash"],
        execution_slice.execution_slice_id,
        kwargs["execution_slice_hash"],
        kwargs["canonical_operation"],
        kwargs["provider_server"],
        kwargs["provider_tool"],
        kwargs["provider_version"],
        kwargs["selected_candidate_fingerprint"],
        kwargs["host_instance_id"],
        kwargs["document_ref"],
        kwargs["input_adapter_version"],
        kwargs["native_targets"],
        kwargs["provider_arguments"],
        kwargs["provider_preconditions"],
        kwargs["native_binding_metadata"],
        kwargs["verification_contract"],
        kwargs["rollback_contract"],
        kwargs["binding_expires_at"],
        binding_hash,
    )


def test_host_binding_fingerprint_binds_exact_native_identity(digest_fn):
    row = NativeTargetBindingEvidence(
        "WALL-001", "REVIT", "DOC-1", "42", "Wall", digest_fn("supplied")
    )
    expected = canonical_hash(
        {
            "semantic_id": "WALL-001",
            "host_type": "REVIT",
            "document_ref": "DOC-1",
            "native_id": "42",
            "native_kind": "Wall",
        }
    )
    assert compute_host_binding_fingerprint(row) == expected
    assert compute_host_binding_fingerprint(replace(row, native_id="43")) != expected


def test_candidate_fingerprint_is_deterministic_and_sensitive(digest_fn):
    candidate = _candidate(digest_fn)
    forward = compute_candidate_fingerprint(candidate)
    reordered = replace(
        candidate,
        compatible_operation_versions=tuple(reversed(candidate.compatible_operation_versions)),
        provider_native_constraints=tuple(reversed(candidate.provider_native_constraints)),
    )
    assert compute_candidate_fingerprint(reordered) == forward

    changes = (
        {"provider_server": "provider.alt"},
        {"provider_tool": "element.translate"},
        {"provider_version": "1.2.4"},
        {"canonical_operation": "rotate.v1"},
        {"compatible_operation_versions": ("1.0.1",)},
        {"input_adapter_version": "1.0.1"},
        {"provider_native_constraints": (NativeConstraint("native_kind", "EQ", ("Wall",)),)},
        {"provider_input_schema": {"type": "array"}},
        {"verification_contract": {"kind": "strong-readback"}},
        {"rollback_contract": {"kind": "none"}},
        {"trust_state": EligibilityState.UNSATISFIED},
        {"compatibility_state": EligibilityState.UNSATISFIED},
        {"health_state": EligibilityState.UNSATISFIED},
        {"license_state": EligibilityState.UNSATISFIED},
        {"certification_state": EligibilityState.UNSATISFIED},
        {"policy_priority": 11},
    )
    for update in changes:
        assert compute_candidate_fingerprint(replace(candidate, **update)) != forward


def test_snapshot_hash_is_order_invariant_preserves_duplicates_and_excludes_id(
    execution_slice, digest_fn
):
    rows = _native_rows(execution_slice, digest_fn)
    candidates = (
        _candidate(digest_fn),
        _candidate(digest_fn, provider_server="provider.second", candidate_fingerprint=digest_fn("second")),
    )
    snapshot = ProviderExecutionSnapshot(
        "PES-A",
        execution_slice.execution_slice_id,
        execution_slice.execution_slice_hash,
        execution_slice.host_runtime_ref,
        rows,
        candidates,
        "2026-08-30T10:30:00Z",
        digest_fn("supplied-snapshot"),
    )
    baseline = compute_provider_snapshot_hash(snapshot)
    reordered = replace(
        snapshot,
        snapshot_id="PES-B",
        native_target_bindings=tuple(reversed(rows)),
        provider_candidates=tuple(reversed(candidates)),
    )
    assert compute_provider_snapshot_hash(reordered) == baseline

    duplicated = replace(snapshot, native_target_bindings=(*rows, rows[0]))
    assert compute_provider_snapshot_hash(duplicated) != baseline


def test_precondition_fingerprint_binds_exact_body(digest_fn):
    value = ChangePrecondition(PreconditionKind.COVERAGE, "move.v1", digest_fn("coverage"))
    expected = canonical_hash(
        {
            "kind": "COVERAGE",
            "subject_ref": "move.v1",
            "evidence_ref": digest_fn("coverage"),
        }
    )
    assert compute_precondition_fingerprint(value) == expected
    assert compute_precondition_fingerprint(
        ChangePrecondition(PreconditionKind.ASSURANCE, "move.v1", digest_fn("coverage"))
    ) != expected


def test_binding_hash_is_order_invariant_and_has_no_snapshot_parameters(execution_slice, digest_fn):
    kwargs = _binding_kwargs(execution_slice, digest_fn)
    first = compute_binding_hash(**kwargs)
    second_native = replace(
        kwargs["native_targets"][0],
        semantic_id="ANNOTATION-002",
        native_id="NATIVE-2",
        native_kind="Annotation",
        host_binding_fingerprint=digest_fn("host-binding-annotation"),
    )
    second_precondition = ProviderPreconditionBinding(
        compute_precondition_fingerprint(execution_slice.execution_units[0].preconditions[1]),
        {"coverage": "checked"},
    )
    multiple = {
        **kwargs,
        "native_targets": (kwargs["native_targets"][0], second_native),
        "provider_preconditions": (kwargs["provider_preconditions"][0], second_precondition),
    }
    forward = compute_binding_hash(**multiple)
    reversed_hash = compute_binding_hash(
        **{
            **multiple,
            "native_targets": tuple(reversed(multiple["native_targets"])),
            "provider_preconditions": tuple(reversed(multiple["provider_preconditions"])),
        }
    )
    assert forward == reversed_hash
    assert first != forward
    assert "provider_execution_snapshot_id" not in signature(compute_binding_hash).parameters
    assert "provider_execution_snapshot_hash" not in signature(compute_binding_hash).parameters


def test_binding_hash_changes_for_every_authorization_relevant_dimension(execution_slice, digest_fn):
    kwargs = _binding_kwargs(execution_slice, digest_fn)
    baseline = compute_binding_hash(**kwargs)
    native = kwargs["native_targets"][0]
    precondition = kwargs["provider_preconditions"][0]
    changes = (
        {"provider_server": "provider.alt"},
        {"provider_tool": "element.translate"},
        {"provider_version": "1.2.4"},
        {"selected_candidate_fingerprint": digest_fn("other-candidate")},
        {"input_adapter_version": "1.0.1"},
        {"host_instance_id": "RVT-02"},
        {"document_ref": "DOC-2"},
        {"native_targets": (replace(native, native_id="NATIVE-99"),)},
        {"provider_arguments": {"distance": 101.0}},
        {"provider_preconditions": (replace(precondition, provider_precondition={"revision": "R-32"}),)},
        {"native_binding_metadata": {"variant": "alternate"}},
        {"verification_contract": {"kind": "strong-readback"}},
        {"rollback_contract": {"kind": "none"}},
        {"binding_expires_at": "2026-08-30T10:31:00Z"},
    )
    for update in changes:
        assert compute_binding_hash(**{**kwargs, **update}) != baseline


def test_binding_set_hash_uses_full_hashes_and_is_order_invariant(digest_fn):
    first = digest_fn("binding-one")
    second = digest_fn("binding-two")
    slice_hash = digest_fn("slice")
    baseline = compute_binding_set_hash(
        execution_slice_hash=slice_hash,
        binding_hashes=(first, second),
    )
    assert baseline == compute_binding_set_hash(
        execution_slice_hash=slice_hash,
        binding_hashes=(second, first),
    )
    assert baseline != compute_binding_set_hash(
        execution_slice_hash=slice_hash,
        binding_hashes=(first, digest_fn("binding-three")),
    )
    expected = canonical_hash(
        {"execution_slice_hash": slice_hash, "binding_hashes": sorted((first, second))}
    )
    assert baseline == expected
    with pytest.raises(ValueError):
        compute_binding_set_hash(
            execution_slice_hash=slice_hash,
            binding_hashes=(f"PB-{first[:12]}", second),
        )


def test_binding_validator_rejects_supplied_hash_or_id_mismatch(execution_slice, digest_fn):
    binding = _binding(execution_slice, digest_fn)
    validate_provider_binding(binding)
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding(replace(binding, binding_hash=digest_fn("wrong-binding")))
    assert exc.value.code == "PROVIDER_BINDING_HASH_MISMATCH"
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding(replace(binding, binding_id="PB-deadbeef0000"))
    assert exc.value.code == "PROVIDER_BINDING_HASH_MISMATCH"


def test_binding_set_validator_rejects_supplied_hash_or_id_mismatch(execution_slice, digest_fn):
    binding = _binding(execution_slice, digest_fn)
    set_hash = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash,),
    )
    value = ProviderBindingSet(
        f"PBS-{set_hash[:12]}",
        execution_slice.execution_slice_id,
        execution_slice.execution_slice_hash,
        "PES-31",
        digest_fn("snapshot-provenance"),
        (binding,),
        set_hash,
    )
    validate_provider_binding_set_hash(value)
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set_hash(replace(value, binding_set_hash=digest_fn("wrong-set")))
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"
    with pytest.raises(ProviderBindingError) as exc:
        validate_provider_binding_set_hash(replace(value, binding_set_id="PBS-deadbeef0000"))
    assert exc.value.code == "PROVIDER_BINDING_SET_INVALID"
