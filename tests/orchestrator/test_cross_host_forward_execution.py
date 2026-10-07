"""Cross-Host Product Vertical Task 10：双 Slice forward-execution 契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from design_approval_scope import InMemoryApprovalScopeStore
from design_changeset import InMemoryChangeSetStore
from design_execution_planning import (
    InMemoryExecutionPlanV2Store,
    plan_materialized_execution,
)
from design_gateway_authorization import (
    AdmittedExecutionAuthorityV2,
    ExecutionGrantV2,
)
from design_materialization_planning import InMemoryMaterializationPlanStore
from design_orchestrator.execution_collection_artifacts import (
    ExecutionGrantCollectionManifest,
    ExecutionGrantCollectionMember,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import (
    ProviderBindingSetV2,
    resolve_provider_bindings_v2,
)

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.orchestrator.test_canonical_owner_ports import _ArtifactStore, _task6_adapter
from tests.provider_binding._support import build_phase_i_binding_inputs


class _BindingStore:
    """记录按完整 hash 解析 BindingSetV2 的顺序。"""

    def __init__(self, bindings, events) -> None:
        self._by_hash = {item.binding_set_hash: item for item in bindings}
        self.events = events

    def get_by_hash(self, binding_set_hash: str) -> ProviderBindingSetV2:
        """按完整 owner hash 读取；未知 hash fail closed。"""

        self.events.append(("binding.get", binding_set_hash))
        return self._by_hash[binding_set_hash]


class _GatewayStore:
    """只读 grant owner；缺失第二个 grant 用于证明 complete-before-execute。"""

    def __init__(self, grants, events, *, omit_last: bool = False) -> None:
        values = grants[:-1] if omit_last else grants
        self._by_hash = {item.grant_hash: item for item in values}
        self.events = events

    def get_grant_v2(self, grant_hash: str):
        """按完整 grant hash 读取，不做 admission。"""

        self.events.append(("grant.get", grant_hash))
        return self._by_hash.get(grant_hash)


class _GatewayAuthority:
    """把已签发 grant 投影为 admitted authority，并记录调用顺序。"""

    def __init__(self, grants, events) -> None:
        self._by_hash = {item.grant_hash: item for item in grants}
        self.events = events
        self.admissions: list[str] = []

    def admit_execution_grant(self, grant_hash: str, admitted_at: str):
        """模拟 Gateway 当前适用性校验；不触碰 Host。"""

        grant = self._by_hash[grant_hash]
        self.events.append(("grant.admit", grant_hash))
        self.admissions.append(grant_hash)
        return AdmittedExecutionAuthorityV2(
            approval_hash=grant.approval_hash,
            grant_hash=grant.grant_hash,
            changeset_hash=grant.changeset_hash,
            approved_scope_hash=grant.approved_scope_hash,
            materialization_plan_hash=grant.materialization_plan_hash,
            materialization_id=grant.materialization_id,
            execution_slice_hash=grant.execution_slice_hash,
            binding_set_hash=grant.binding_set_hash,
            host_instance_id=grant.host_instance_id,
            admitted_at=admitted_at,
        )


class _Coordinator:
    """记录唯一 forward execute 调用；manifest 对象不得进入该边界。"""

    def __init__(self, events) -> None:
        self.events = events
        self.calls = []

    def execute(
        self,
        changeset,
        boundary,
        materialization_plan,
        execution_plan,
        binding_sets,
        authorities,
        convergence_profile,
    ):
        """记录 concrete owner tuples，并返回已存在的 durable Saga identity。"""

        self.events.append(("coordinator.execute", execution_plan.execution_plan_hash))
        self.calls.append(
            (
                changeset,
                boundary,
                materialization_plan,
                execution_plan,
                tuple(binding_sets),
                tuple(authorities),
                convergence_profile,
            )
        )
        return SimpleNamespace(status="SUCCEEDED", saga_id="SAGA-TASK10")


class _SagaStore:
    """只证明 coordinator 返回的 saga_id 可由 durable owner 解析。"""

    def get_saga(self, saga_id: str):
        """返回非空 durable sentinel。"""

        if saga_id == "SAGA-TASK10":
            return SimpleNamespace(saga_id=saga_id)
        return None


class _Clock:
    """为 Gateway current-applicability check 提供确定 UTC 时间。"""

    def now(self) -> datetime:
        """返回固定 timezone-aware UTC。"""

        return datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


def _case(*, omit_last_grant: bool = False):
    """构造真实 Step28/29/30/31 lineage 与 Task 9 Grant manifest。"""

    case, materialization_plan, _, request = build_phase_i_execution_inputs()
    execution_plan = plan_materialized_execution(request)
    _, _, snapshots = build_phase_i_binding_inputs()
    binding_sets = tuple(
        resolve_provider_bindings_v2(
            execution_slice,
            snapshots[execution_slice.host_runtime_ref.host_type],
        )
        for execution_slice in execution_plan.execution_slices
    )
    grants = tuple(
        ExecutionGrantV2(
            grant_id=f"GRANT-TASK10-{index}",
            approval_id="APP-TASK10",
            approval_hash="b" * 64,
            changeset_hash=execution_plan.changeset_hash,
            approved_scope_hash=execution_plan.approval_scope_ref.scope_hash,
            materialization_plan_hash=execution_plan.materialization_plan_hash,
            materialization_id=execution_slice.materialization_id,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=("set_wall_thickness.v1",),
            issued_at="2026-10-07T01:00:00Z",
            expires_at="2026-10-08T01:00:00Z",
            grant_hash=("9" if index == 0 else "a") * 64,
        )
        for index, (execution_slice, binding_set) in enumerate(
            zip(execution_plan.execution_slices, binding_sets, strict=True)
        )
    )

    artifact_store = _ArtifactStore()
    grant_manifest = ExecutionGrantCollectionManifest.create(
        execution_plan,
        tuple(
            ExecutionGrantCollectionMember(
                execution_slice_id=execution_slice.execution_slice_id,
                execution_slice_hash=execution_slice.execution_slice_hash,
                materialization_id=execution_slice.materialization_id,
                owner_ref=StableRef(grant.grant_id, grant.grant_hash),
            )
            for execution_slice, grant in zip(
                execution_plan.execution_slices,
                grants,
                strict=True,
            )
        ),
    )
    grant_ref = artifact_store.put(
        kind="execution_grant_collection_manifest",
        value=grant_manifest,
        content_hash=workflow_artifact_content_hash(grant_manifest),
    )

    plan_store = InMemoryExecutionPlanV2Store()
    plan_store.put(execution_plan)
    changeset_store = InMemoryChangeSetStore()
    changeset_store.put(case.changeset)
    scope_store = InMemoryApprovalScopeStore()
    scope_store.put_boundary(case.boundary_v2)
    materialization_store = InMemoryMaterializationPlanStore()
    materialization_store.put(materialization_plan)

    events = []
    binding_store = _BindingStore(binding_sets, events)
    gateway_store = _GatewayStore(
        grants,
        events,
        omit_last=omit_last_grant,
    )
    gateway = _GatewayAuthority(grants, events)
    coordinator = _Coordinator(events)

    adapter, *_ = _task6_adapter(
        artifact_store=artifact_store,
        overrides={
            "execution_plan_store": plan_store,
            "provider_binding_store": binding_store,
            "gateway_authorization_store": gateway_store,
            "gateway_authorization": gateway,
            "changeset_store": changeset_store,
            "approval_scope_store": scope_store,
            "materialization_plan_store": materialization_store,
            "execution_coordinator": coordinator,
            "saga_store": _SagaStore(),
            "coordination_clock": _Clock(),
        },
    )
    return SimpleNamespace(
        adapter=adapter,
        plan=execution_plan,
        bindings=binding_sets,
        grants=grants,
        grant_ref=grant_ref,
        gateway=gateway,
        coordinator=coordinator,
        events=events,
    )


def test_forward_execution_resolves_all_bindings_and_grants_before_first_host_execute() -> None:
    """双 Slice concrete owner objects 完整后才允许进入 coordinator。"""

    ctx = _case()
    saga_id = ctx.adapter.begin_execution(
        StableRef(ctx.plan.execution_plan_id, ctx.plan.execution_plan_hash),
        ctx.grant_ref,
    )

    assert saga_id == "SAGA-TASK10"
    assert len(ctx.coordinator.calls) == 1
    _, _, _, plan, bindings, authorities, _ = ctx.coordinator.calls[0]
    assert plan == ctx.plan
    assert bindings == ctx.bindings
    assert tuple(item.grant_hash for item in authorities) == tuple(
        item.grant_hash for item in ctx.grants
    )

    event_names = [item[0] for item in ctx.events]
    assert event_names[:2] == ["grant.get", "grant.get"]
    assert event_names[2:4] == ["binding.get", "binding.get"]
    assert event_names[4:6] == ["grant.admit", "grant.admit"]
    assert event_names[6] == "coordinator.execute"


def test_missing_second_grant_causes_zero_host_mutations() -> None:
    """第二个 required Grant 缺失必须在 coordinator/Host mutation 前 fail closed。"""

    ctx = _case(omit_last_grant=True)

    with pytest.raises(ValueError, match="EXECUTION_COLLECTION_INVALID"):
        ctx.adapter.begin_execution(
            StableRef(ctx.plan.execution_plan_id, ctx.plan.execution_plan_hash),
            ctx.grant_ref,
        )

    assert ctx.coordinator.calls == []
    assert ctx.gateway.admissions == []
    assert all(event[0] != "coordinator.execute" for event in ctx.events)
