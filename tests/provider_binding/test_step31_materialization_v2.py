from __future__ import annotations

from dataclasses import replace

import pytest
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshotV2,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash_v2,
    resolve_provider_bindings_v2,
    validate_provider_binding_set_v2,
)

from tests.execution_planning.test_step30_materialization_v2 import _phase_i_inputs


def _native_target(execution_slice, *, native_id: str, native_kind: str):
    provisional = NativeTargetBindingEvidence(
        semantic_id=execution_slice.execution_units[0].targets[0],
        host_type=execution_slice.host_runtime_ref.host_type,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id=native_id,
        native_kind=native_kind,
        host_binding_fingerprint="0" * 64,
    )
    return replace(
        provisional,
        host_binding_fingerprint=compute_host_binding_fingerprint(provisional),
    )


def _candidate(execution_slice, *, provider_server: str, native_kind: str):
    unit = execution_slice.execution_units[0]
    provisional = ProviderExecutionCandidate(
        provider_server=provider_server,
        provider_tool="set_wall_thickness",
        provider_version="1.0.0",
        canonical_operation=unit.canonical_operation,
        compatible_operation_versions=(unit.canonical_operation_version,),
        input_adapter_version="1.0.0",
        provider_native_constraints=(
            NativeConstraint(
                "native_kind",
                NativeConstraintOperator.EQ,
                (native_kind,),
            ),
        ),
        provider_input_schema={
            "type": "object",
            "properties": {
                "native_ids": {"type": "array", "items": {"type": "string"}},
                "canonical_arguments": {"type": "object"},
            },
            "required": ["native_ids", "canonical_arguments"],
            "additionalProperties": False,
        },
        verification_contract={"read_back": "required"},
        rollback_contract={"mode": "compensating_changeset"},
        trust_state=EligibilityState.SATISFIED,
        compatibility_state=EligibilityState.SATISFIED,
        health_state=EligibilityState.SATISFIED,
        license_state=EligibilityState.SATISFIED,
        certification_state=EligibilityState.SATISFIED,
        policy_priority=10,
        candidate_fingerprint="0" * 64,
    )
    return replace(
        provisional,
        candidate_fingerprint=compute_candidate_fingerprint(provisional),
    )


def _snapshot(execution_slice, *, native_id: str, native_kind: str):
    target = _native_target(
        execution_slice,
        native_id=native_id,
        native_kind=native_kind,
    )
    candidate = _candidate(
        execution_slice,
        provider_server=f"provider.{execution_slice.host_runtime_ref.host_type}.wall",
        native_kind=native_kind,
    )
    material = ProviderBindingMaterial(
        native_targets=(target,),
        provider_arguments={
            "native_ids": [target.native_id],
            "canonical_arguments": dict(execution_slice.execution_units[0].arguments),
        },
        provider_preconditions=(),
        native_binding_metadata={"identity_source": "persistent_host_binding"},
    )
    provisional = ProviderExecutionSnapshotV2(
        snapshot_id=f"PESV2-{execution_slice.host_runtime_ref.host_type}",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        native_target_bindings=(target,),
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        valid_until="2026-09-06T18:00:00Z",
        snapshot_hash="0" * 64,
    )
    return replace(
        provisional,
        snapshot_hash=compute_provider_snapshot_hash_v2(provisional),
    )


def _phase_i_binding_inputs():
    _, materialization_plan, _, execution_request = _phase_i_inputs()
    execution_plan = __import__(
        "design_execution_planning",
        fromlist=["plan_materialized_execution"],
    ).plan_materialized_execution(execution_request)
    slices = {
        item.host_runtime_ref.host_type: item
        for item in execution_plan.execution_slices
    }
    snapshots = {
        "autocad": _snapshot(
            slices["autocad"],
            native_id="ACAD-HANDLE-001",
            native_kind="AcDbPolyline",
        ),
        "revit": _snapshot(
            slices["revit"],
            native_id="REVIT-UNIQUE-ID-001",
            native_kind="Wall",
        ),
    }
    return materialization_plan, slices, snapshots


def test_v2_binding_preserves_exact_materialization_slice_and_host_lineage() -> None:
    _, slices, snapshots = _phase_i_binding_inputs()

    for host_type in ("autocad", "revit"):
        execution_slice = slices[host_type]
        snapshot = snapshots[host_type]
        binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)

        assert snapshot.materialization_id == execution_slice.materialization_id
        assert snapshot.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert snapshot.execution_slice_hash == execution_slice.execution_slice_hash
        assert snapshot.host_runtime_ref == execution_slice.host_runtime_ref
        assert binding_set.materialization_id == execution_slice.materialization_id
        assert binding_set.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert binding_set.execution_slice_hash == execution_slice.execution_slice_hash
        assert len(binding_set.bindings) == 1
        binding = binding_set.bindings[0]
        assert binding.materialization_id == execution_slice.materialization_id
        assert binding.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert binding.execution_slice_hash == execution_slice.execution_slice_hash
        assert binding.host_runtime_ref == execution_slice.host_runtime_ref
        assert binding.native_targets == snapshot.native_target_bindings
        validate_provider_binding_set_v2(binding_set, execution_slice)


def test_native_identity_change_changes_snapshot_binding_and_set_hashes() -> None:
    _, slices, _ = _phase_i_binding_inputs()
    execution_slice = slices["revit"]
    first_snapshot = _snapshot(
        execution_slice,
        native_id="REVIT-UNIQUE-ID-001",
        native_kind="Wall",
    )
    second_snapshot = _snapshot(
        execution_slice,
        native_id="REVIT-UNIQUE-ID-002",
        native_kind="Wall",
    )

    first = resolve_provider_bindings_v2(execution_slice, first_snapshot)
    second = resolve_provider_bindings_v2(execution_slice, second_snapshot)

    assert first_snapshot.snapshot_hash != second_snapshot.snapshot_hash
    assert first.bindings[0].binding_hash != second.bindings[0].binding_hash
    assert first.binding_set_hash != second.binding_set_hash


def test_changed_revit_unique_id_under_old_host_binding_fingerprint_fails_closed() -> None:
    _, slices, snapshots = _phase_i_binding_inputs()
    execution_slice = slices["revit"]
    snapshot = snapshots["revit"]
    original = snapshot.native_target_bindings[0]
    tampered_target = replace(original, native_id="REVIT-UNIQUE-ID-CHANGED")
    tampered = replace(snapshot, native_target_bindings=(tampered_target,))

    with pytest.raises(ProviderBindingError) as exc:
        resolve_provider_bindings_v2(execution_slice, tampered)
    assert exc.value.code == "IDENTITY_BINDING_CONFLICT"


def test_snapshot_materialization_or_host_substitution_fails_closed() -> None:
    _, slices, snapshots = _phase_i_binding_inputs()
    execution_slice = slices["autocad"]
    snapshot = snapshots["autocad"]

    with pytest.raises(ProviderBindingError) as exc:
        resolve_provider_bindings_v2(
            execution_slice,
            replace(snapshot, materialization_id="MAT-SUBSTITUTED"),
        )
    assert exc.value.code == "MATERIALIZATION_BINDING_MISMATCH"
