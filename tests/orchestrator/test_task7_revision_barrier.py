"""Task 7 Step 3：真实 RevisionBarrier 必须先于 provider binding 执行。"""

from __future__ import annotations

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
from semantic_runtime import RevisionBarrier, RevisionChangedError

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


def _planned_case():
    """组装 Task 7 Step 1/2 已有真实 owners，并让同一 revision observation 驱动 barrier。"""

    revision = _MutableHostRevisionObservation("42")
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
        }
    )

    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
    admission_port.admission = _approval_admission(changeset, boundary)
    approval_ref = adapter.request_approval(changeset_ref)
    assert isinstance(approval_ref, StableRef)
    execution_plan_ref = adapter.plan_execution(changeset_ref, approval_ref)
    return adapter, revision, execution_plan_ref


def test_task7_revision_barrier_rejects_changed_host_revision_before_binding() -> None:
    """Host revision 变化必须由真实 RevisionBarrier 拒绝，不能推进到 provider binding。"""

    adapter, revision, execution_plan_ref = _planned_case()
    revision.revision = "43"

    with pytest.raises(RevisionChangedError):
        adapter.check_revision_barrier(execution_plan_ref)


def test_task7_revision_barrier_same_revision_reaches_provider_binding_boundary() -> None:
    """Host revision 未变化时 barrier 应通过，并把 fail-closed 边界推进到 bind_providers。"""

    adapter, _, execution_plan_ref = _planned_case()

    adapter.check_revision_barrier(execution_plan_ref)
    with pytest.raises(CanonicalOwnerPortNotWiredError) as exc_info:
        adapter.bind_providers(execution_plan_ref)
    assert exc_info.value.method_name == "bind_providers"
