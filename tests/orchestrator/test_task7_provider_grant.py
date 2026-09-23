"""Task 7 Step 4：真实 Provider Binding V2 与 Gateway V2 grant/admission TDD。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import InMemoryExecutionPlanV2Store
from design_gateway_authorization import (
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
)
from design_materialization_planning import (
    InMemoryMaterializationPlanStore,
    MaterializationPlanner,
)
from design_orchestrator.canonical_owner_ports import CanonicalOwnerPortNotWiredError
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import (
    EligibilityState,
    InMemoryProviderBindingSetV2Store,
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
)
from semantic_runtime import RevisionBarrier

from tests.orchestrator.test_canonical_owner_ports import (
    _MutableHostRevisionObservation,
    _task6_real_impact_case,
    _Task7ApprovalAdmission,
    _Task7Clock,
)
from tests.orchestrator.test_task7_planning import (
    _approval_admission,
    _Task7MaterializationRouting,
)


class _ProviderExecutionSnapshotBoundary:
    """只提供 Host/provider runtime evidence，不执行候选选择或 provider binding 规则。"""

    def __init__(self, *, mismatched_slice: bool = False) -> None:
        self.mismatched_slice = mismatched_slice
        self.calls: list[object] = []

    def __call__(self, execution_slice):
        """为 exact Slice 构造 public ProviderExecutionSnapshotV2 环境事实。"""

        self.calls.append(execution_slice)
        unit = execution_slice.execution_units[0]
        provisional_target = NativeTargetBindingEvidence(
            semantic_id=unit.targets[0],
            host_type=execution_slice.host_runtime_ref.host_type,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            native_id="REVIT-UNIQUE-ID-TASK7",
            native_kind="Wall",
            host_binding_fingerprint="0" * 64,
        )
        target = replace(
            provisional_target,
            host_binding_fingerprint=compute_host_binding_fingerprint(provisional_target),
        )

        provisional_candidate = ProviderExecutionCandidate(
            provider_server="provider.revit.wall",
            provider_tool="set_wall_thickness",
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
                    "native_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
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
        candidate = replace(
            provisional_candidate,
            candidate_fingerprint=compute_candidate_fingerprint(provisional_candidate),
        )
        material = ProviderBindingMaterial(
            native_targets=(target,),
            provider_arguments={
                "native_ids": [target.native_id],
                "canonical_arguments": dict(unit.arguments),
            },
            provider_preconditions=(),
            native_binding_metadata={"identity_source": "task7-runtime-boundary"},
        )
        execution_slice_hash = (
            "f" * 64
            if self.mismatched_slice
            else execution_slice.execution_slice_hash
        )
        provisional_snapshot = ProviderExecutionSnapshotV2(
            snapshot_id="PESV2-TASK7",
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice_hash,
            host_runtime_ref=execution_slice.host_runtime_ref,
            native_target_bindings=(target,),
            provider_candidates=(candidate,),
            candidate_binding_materials={candidate.candidate_fingerprint: material},
            valid_until="2026-09-06T17:00:00Z",
            snapshot_hash="0" * 64,
        )
        return replace(
            provisional_snapshot,
            snapshot_hash=compute_provider_snapshot_hash_v2(provisional_snapshot),
        )


class _CountingGatewayV2:
    """只记录 Gateway V2 调用，并把全部授权语义委托给真实 service。"""

    def __init__(self, store: InMemoryGatewayAuthorizationStoreV2) -> None:
        self._delegate = GatewayAuthorizationServiceV2(store)
        self.issue_requests: list[object] = []
        self.admit_calls: list[tuple[str, str]] = []
        self.admitted_authorities: list[object] = []

    def consume_approval(self, request):
        """Approval truth 仍由真实 Gateway V2 创建。"""

        return self._delegate.consume_approval(request)

    def issue_execution_grant(self, request):
        """记录 request 后交给真实 Gateway V2 校验并签发。"""

        self.issue_requests.append(request)
        return self._delegate.issue_execution_grant(request)

    def admit_execution_grant(self, grant_hash: str, admitted_at: str):
        """记录 admission 后交给真实 Gateway V2 原子 admission。"""

        self.admit_calls.append((grant_hash, admitted_at))
        authority = self._delegate.admit_execution_grant(grant_hash, admitted_at)
        self.admitted_authorities.append(authority)
        return authority


def _provider_grant_case(*, mismatched_slice: bool = False):
    """组装 Task 7 Step 1–3 的真实 owners，并保留 provider/grant owner stores。"""

    revision = _MutableHostRevisionObservation("42")
    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = _CountingGatewayV2(gateway_store)
    admission_port = _Task7ApprovalAdmission()
    materialization_store = InMemoryMaterializationPlanStore()
    execution_store = InMemoryExecutionPlanV2Store()
    provider_store = InMemoryProviderBindingSetV2Store()
    provider_snapshot = _ProviderExecutionSnapshotBoundary(
        mismatched_slice=mismatched_slice
    )

    (
        adapter,
        bound_ref,
        impact_ref,
        _,
        _,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case(
        overrides={
            "host_revision_observation": revision,
            "revision_barrier": RevisionBarrier(revision),
            "materialization_planner": MaterializationPlanner(),
            "materialization_plan_store": materialization_store,
            "execution_plan_store": execution_store,
            "gateway_authorization": gateway,
            "gateway_authorization_store": gateway_store,
            "coordination_clock": _Task7Clock(),
            "approval_admission": admission_port,
            "materialization_routing": _Task7MaterializationRouting(),
            "provider_binding_store": provider_store,
            "provider_execution_snapshot": provider_snapshot,
        }
    )

    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
    admission_port.admission = _approval_admission(changeset, boundary)
    approval_ref = adapter.request_approval(changeset_ref)
    assert isinstance(approval_ref, StableRef)
    execution_plan_ref = adapter.plan_execution(changeset_ref, approval_ref)
    adapter.check_revision_barrier(execution_plan_ref)
    return (
        adapter,
        execution_plan_ref,
        approval_ref,
        execution_store,
        materialization_store,
        provider_store,
        gateway_store,
        gateway,
        provider_snapshot,
        changeset,
        boundary,
    )


def test_task7_provider_binding_and_grant_use_real_v2_owners() -> None:
    """Provider Binding V2 → Gateway V2 issue/admit 必须保留 exact materialization lineage。"""

    (
        adapter,
        execution_plan_ref,
        approval_ref,
        execution_store,
        materialization_store,
        provider_store,
        gateway_store,
        gateway,
        provider_snapshot,
        changeset,
        boundary,
    ) = _provider_grant_case()

    provider_binding_ref = adapter.bind_providers(execution_plan_ref)
    binding_set = provider_store.get(provider_binding_ref.ref_id)
    execution_plan = execution_store.get(execution_plan_ref.ref_id)
    execution_slice = execution_plan.execution_slices[0]
    materialization_plan = materialization_store.get(
        execution_plan.materialization_plan_hash
    )

    assert provider_binding_ref == StableRef(
        binding_set.binding_set_id,
        binding_set.binding_set_hash,
    )
    assert provider_snapshot.calls == [execution_slice]
    assert binding_set.execution_slice_hash == execution_slice.execution_slice_hash
    assert binding_set.materialization_plan_hash == materialization_plan.materialization_plan_hash

    grant_ref = adapter.issue_execution_grant(
        execution_plan_ref,
        approval_ref,
        provider_binding_ref,
    )
    assert grant_ref.content_hash is not None
    grant = gateway_store.get_grant_v2(grant_ref.content_hash)
    assert grant is not None
    assert grant_ref == StableRef(grant.grant_id, grant.grant_hash)
    assert grant.changeset_hash == changeset.changeset_hash
    assert grant.approved_scope_hash == boundary.scope_hash
    assert grant.materialization_plan_hash == materialization_plan.materialization_plan_hash
    assert grant.materialization_id == execution_slice.materialization_id
    assert grant.execution_slice_hash == execution_slice.execution_slice_hash
    assert grant.binding_set_hash == binding_set.binding_set_hash
    assert len(gateway.issue_requests) == 1
    assert gateway.admit_calls == [(grant.grant_hash, "2026-09-06T10:00:00Z")]
    assert len(gateway.admitted_authorities) == 1
    authority = gateway.admitted_authorities[0]
    assert authority.grant_hash == grant.grant_hash
    assert authority.changeset_hash == changeset.changeset_hash
    assert authority.approved_scope_hash == boundary.scope_hash
    assert authority.materialization_plan_hash == materialization_plan.materialization_plan_hash
    assert authority.execution_slice_hash == execution_slice.execution_slice_hash
    assert authority.binding_set_hash == binding_set.binding_set_hash


def test_task7_provider_mismatch_stops_before_grant_or_execution() -> None:
    """Provider snapshot 与 exact Slice 不匹配时必须由真实 Binding V2 拒绝且不签发 grant。"""

    (
        adapter,
        execution_plan_ref,
        _,
        _,
        _,
        _,
        _,
        gateway,
        provider_snapshot,
        _,
        _,
    ) = _provider_grant_case(mismatched_slice=True)

    with pytest.raises(ProviderBindingError) as exc_info:
        adapter.bind_providers(execution_plan_ref)
    assert exc_info.value.code == "MATERIALIZATION_BINDING_MISMATCH"
    assert len(provider_snapshot.calls) == 1
    assert gateway.issue_requests == []
    assert gateway.admit_calls == []
