"""Task 6 sidecar focused tests 的最小 V2 execution fixture。

该 helper 只使用 production public contracts 构造一个单 Revit wall materialization。
它不依赖仓库根 ``tests.*``，因此 sidecar focused invocation 与全仓回归拥有相同语义。
"""

from __future__ import annotations

from dataclasses import replace

from design_approval_scope import CanonicalAspect
from design_execution_planning import (
    ApprovedExecutionScopeRef,
    ExecutionSliceV2,
    ExecutionUnitV2,
    HostRuntimeRef,
)
from design_gateway_authorization import AdmittedExecutionAuthorityV2
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
    resolve_provider_bindings_v2,
)


def _execution_slice() -> ExecutionSliceV2:
    """构造一个只含单 wall / 单 unit 的 Revit ExecutionSliceV2。"""

    materialization_plan_hash = "a" * 64
    changeset_hash = "e" * 64
    unit = ExecutionUnitV2(
        execution_unit_id="EU-REVIT-WALL-001",
        materialization_id="MAT-REVIT-WALL-001",
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id="MS-REVIT-WALL-001",
        required_host_type="revit",
        source_operation_id="COP-REVIT-WALL-001",
        source_operation_hash="b" * 64,
        canonical_operation="set_wall_thickness.v1",
        canonical_operation_version="1.0.0",
        canonical_definition_fingerprint="c" * 64,
        targets=("WALL-001",),
        arguments={"thickness": {"value": 300.0, "unit": "mm"}},
        preconditions=(),
        expected_effects=(CanonicalAspect.PROPERTIES,),
        scope_rule_ids=("RULE-WALL-001",),
        execution_unit_hash="d" * 64,
    )
    return ExecutionSliceV2(
        execution_slice_id="ES-REVIT-WALL-001",
        changeset_id="CHANGESET-REVIT-WALL-001",
        changeset_hash=changeset_hash,
        materialization_id=unit.materialization_id,
        materialization_plan_hash=materialization_plan_hash,
        materialization_slot_id=unit.materialization_slot_id,
        host_runtime_ref=HostRuntimeRef(
            host_type="revit",
            host_instance_id="REVIT-01",
            document_ref="DOC-REVIT",
        ),
        approved_scope_ref=ApprovedExecutionScopeRef(
            scope_id="SCOPE-REVIT-WALL-001",
            scope_hash="f" * 64,
            execution_slice_scope_rule_id="SLICE-SCOPE-REVIT-WALL-001",
        ),
        execution_units=(unit,),
        execution_slice_hash="1" * 64,
    )


def _native_target(execution_slice: ExecutionSliceV2) -> NativeTargetBindingEvidence:
    """为 approved semantic wall 构造 exact persistent Revit identity evidence。"""

    provisional = NativeTargetBindingEvidence(
        semantic_id=execution_slice.execution_units[0].targets[0],
        host_type="revit",
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id="REVIT-UNIQUE-ID-001",
        native_kind="Wall",
        host_binding_fingerprint="0" * 64,
    )
    return replace(
        provisional,
        host_binding_fingerprint=compute_host_binding_fingerprint(provisional),
    )


def _candidate(
    execution_slice: ExecutionSliceV2,
    *,
    provider_tool: str,
) -> ProviderExecutionCandidate:
    """构造一个满足 Step31 V2 schema/eligibility 的 Revit wall provider candidate。"""

    unit = execution_slice.execution_units[0]
    provisional = ProviderExecutionCandidate(
        provider_server="provider.revit.wall",
        provider_tool=provider_tool,
        provider_version="1.0.0",
        canonical_operation=unit.canonical_operation,
        compatible_operation_versions=(unit.canonical_operation_version,),
        input_adapter_version="1.0.0",
        provider_native_constraints=(
            NativeConstraint(
                "native_kind",
                NativeConstraintOperator.EQ,
                ("Wall",),
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


def revit_execution_inputs(
    *,
    expected_revision: int | None = 31,
    provider_tool: str = "revit.set_wall_thickness",
):
    """返回 exact Slice、真实 Step31 V2 binding set 与匹配的 admitted V2 authority。"""

    execution_slice = _execution_slice()
    target = _native_target(execution_slice)
    candidate = _candidate(execution_slice, provider_tool=provider_tool)
    metadata = {"identity_source": "persistent_host_binding"}
    if expected_revision is not None:
        metadata["expected_revision"] = expected_revision
    material = ProviderBindingMaterial(
        native_targets=(target,),
        provider_arguments={
            "native_ids": [target.native_id],
            "canonical_arguments": dict(execution_slice.execution_units[0].arguments),
        },
        provider_preconditions=(),
        native_binding_metadata=metadata,
    )
    snapshot_draft = ProviderExecutionSnapshotV2(
        snapshot_id="PESV2-REVIT-WALL-001",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        native_target_bindings=(target,),
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        valid_until="2027-01-01T00:00:00Z",
        snapshot_hash="0" * 64,
    )
    snapshot = replace(
        snapshot_draft,
        snapshot_hash=compute_provider_snapshot_hash_v2(snapshot_draft),
    )
    binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)
    authority = AdmittedExecutionAuthorityV2(
        approval_hash="2" * 64,
        grant_hash="3" * 64,
        changeset_hash=execution_slice.changeset_hash,
        approved_scope_hash=execution_slice.approved_scope_ref.scope_hash,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        materialization_id=execution_slice.materialization_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_set_hash=binding_set.binding_set_hash,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        admitted_at="2026-09-25T00:00:00Z",
    )
    return execution_slice, binding_set, authority


__all__ = ["revit_execution_inputs"]
