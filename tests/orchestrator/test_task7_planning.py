"""Task 7 planning TDD：真实 Gateway approval → materialization → ExecutionPlanV2。"""

from __future__ import annotations

from dataclasses import replace

from design_execution_planning import (
    HostRuntimeRef,
    InMemoryExecutionPlanV2Store,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
)
from design_gateway_authorization import (
    ApprovalAdmission,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_materialization_planning import (
    InMemoryMaterializationPlanStore,
    MaterializationPlanner,
)
from design_orchestrator.workflow_contracts import StableRef

from tests.orchestrator.test_canonical_owner_ports import (
    _task6_real_impact_case,
    _Task7ApprovalAdmission,
    _Task7Clock,
)


class _Task7MaterializationRouting:
    """只提供运行时路由事实，不实现 Execution Planning 领域规则。"""

    def routing_evidence(self, materialization_plan, topology_snapshot):
        """按 owner 已冻结的 materialization id 绑定测试运行时文档。"""

        slot_by_id = {
            slot.materialization_slot_id: slot
            for slot in topology_snapshot.slots
        }
        routes = tuple(
            MaterializationRuntimeRoute(
                materialization_id=intent.materialization_id,
                host_runtime_ref=HostRuntimeRef(
                    host_type=intent.required_host_type,
                    host_instance_id=f"{intent.required_host_type.upper()}-TASK7",
                    document_ref=slot_by_id[intent.materialization_slot_id].document_ref,
                ),
            )
            for intent in materialization_plan.intents
        )
        return MaterializationRoutingEvidence(
            routing_snapshot_id="MRS-TASK7",
            routes=routes,
            routing_snapshot_hash=compute_materialization_routing_hash(routes),
        )


def _approval_admission(changeset, boundary) -> ApprovalAdmission:
    """构造 human/policy admission 输入；approval truth 仍必须由 Gateway V2 生成。"""

    draft = ApprovalAdmission(
        admission_id="ADM-TASK7-PLANNING",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:task7-planner",
        policy_snapshot_hash="8" * 64,
        policy_allowed_operations=(changeset.root_operation.canonical_operation,),
        approved_at="2026-09-06T09:00:00Z",
        expires_at="2026-09-06T17:00:00Z",
        admission_fingerprint="0" * 64,
    )
    return replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )


def test_task7_plan_execution_uses_real_materialization_and_execution_owners() -> None:
    """plan_execution 必须发布 owner-store 可解析且 lineage 精确的 ExecutionPlanV2。"""

    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(gateway_store)
    admission_port = _Task7ApprovalAdmission()
    materialization_store = InMemoryMaterializationPlanStore()
    execution_store = InMemoryExecutionPlanV2Store()

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
            "materialization_planner": MaterializationPlanner(),
            "materialization_plan_store": materialization_store,
            "execution_plan_store": execution_store,
            "gateway_authorization": gateway,
            "gateway_authorization_store": gateway_store,
            "coordination_clock": _Task7Clock(),
            "approval_admission": admission_port,
            "materialization_routing": _Task7MaterializationRouting(),
        }
    )

    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
    admission_port.admission = _approval_admission(changeset, boundary)
    approval_ref = adapter.request_approval(changeset_ref)
    assert isinstance(approval_ref, StableRef)

    execution_plan_ref = adapter.plan_execution(changeset_ref, approval_ref)

    execution_plan = execution_store.get(execution_plan_ref.ref_id)
    materialization_plan = materialization_store.get(
        execution_plan.materialization_plan_hash
    )
    assert execution_plan_ref == StableRef(
        execution_plan.execution_plan_id,
        execution_plan.execution_plan_hash,
    )
    assert execution_plan.changeset_id == changeset.changeset_id
    assert execution_plan.changeset_hash == changeset.changeset_hash
    assert materialization_plan.changeset_hash == changeset.changeset_hash
    assert materialization_plan.approved_scope_hash == boundary.scope_hash
    assert execution_plan.topology_snapshot_hash == materialization_plan.topology_snapshot_hash
