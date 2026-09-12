from __future__ import annotations

from dataclasses import replace

from design_execution_planning import plan_materialized_execution
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshotV2,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash_v2,
)

from tests.execution_planning._support import build_phase_i_execution_inputs


def native_target(execution_slice, *, native_id: str, native_kind: str):
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


def candidate(execution_slice, *, provider_server: str, native_kind: str):
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


def snapshot(execution_slice, *, native_id: str, native_kind: str):
    target = native_target(
        execution_slice,
        native_id=native_id,
        native_kind=native_kind,
    )
    execution_candidate = candidate(
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
        provider_candidates=(execution_candidate,),
        candidate_binding_materials={execution_candidate.candidate_fingerprint: material},
        valid_until="2026-09-06T18:00:00Z",
        snapshot_hash="0" * 64,
    )
    return replace(
        provisional,
        snapshot_hash=compute_provider_snapshot_hash_v2(provisional),
    )


def build_phase_i_binding_inputs():
    _, materialization_plan, _, execution_request = build_phase_i_execution_inputs()
    execution_plan = plan_materialized_execution(execution_request)
    slices = {
        item.host_runtime_ref.host_type: item
        for item in execution_plan.execution_slices
    }
    snapshots = {
        "autocad": snapshot(
            slices["autocad"],
            native_id="ACAD-HANDLE-001",
            native_kind="AcDbPolyline",
        ),
        "revit": snapshot(
            slices["revit"],
            native_id="REVIT-UNIQUE-ID-001",
            native_kind="Wall",
        ),
    }
    return materialization_plan, slices, snapshots
