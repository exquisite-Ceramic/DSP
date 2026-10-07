"""Cross-Host Product Vertical Task 9：ExecutionGrant collection manifest 契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace

from design_approval_scope import InMemoryApprovalScopeStore
from design_execution_planning import (
    InMemoryExecutionPlanV2Store,
    plan_materialized_execution,
)
from design_gateway_authorization import ExecutionGrantV2
from design_materialization_planning import InMemoryMaterializationPlanStore
from design_materialization_topology import MaterializationTopologyRegistry
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import (
    InMemoryProviderBindingSetV2Store,
    resolve_provider_bindings_v2,
)

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.orchestrator.test_canonical_owner_ports import _ArtifactStore, _task6_adapter
from tests.provider_binding._support import build_phase_i_binding_inputs


def _api():
    """延迟取得 Task 9 grant manifest 类型，使 test-only commit 形成明确 RED。"""

    module = import_module("design_orchestrator.execution_collection_artifacts")
    member_type = getattr(module, "ExecutionGrantCollectionMember", None)
    manifest_type = getattr(module, "ExecutionGrantCollectionManifest", None)
    assert member_type is not None, "ExecutionGrantCollectionMember 尚未实现"
    assert manifest_type is not None, "ExecutionGrantCollectionManifest 尚未实现"
    return member_type, manifest_type


def _plan_case():
    """返回真实 Phase I 双 materialization plan 与其 owner inputs。"""

    case, materialization_plan, _, request = build_phase_i_execution_inputs()
    plan = plan_materialized_execution(request)
    assert len(plan.execution_slices) == 2
    return case, materialization_plan, plan


def _binding_sets(plan):
    """为 plan 每个 Slice 生成真实 Step31 ProviderBindingSetV2。"""

    _, _, snapshots = build_phase_i_binding_inputs()
    values = []
    for execution_slice in plan.execution_slices:
        host_type = execution_slice.host_runtime_ref.host_type
        values.append(
            resolve_provider_bindings_v2(
                execution_slice,
                snapshots[host_type],
            )
        )
    return tuple(values)


def _grant_members(plan, binding_sets):
    """按 plan 顺序构造只保存原 Gateway grant refs 的 manifest members。"""

    member_type, _ = _api()
    return tuple(
        member_type(
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            materialization_id=execution_slice.materialization_id,
            owner_ref=StableRef(
                f"XGV2-{index}",
                f"{index + 7:x}" * 64,
            ),
        )
        for index, execution_slice in enumerate(plan.execution_slices)
    )


def test_grant_manifest_exactly_matches_binding_manifest_and_required_slices() -> None:
    """Grant manifest 与 binding manifest 必须覆盖同一 ordered REQUIRED Slice set。"""

    module = import_module("design_orchestrator.execution_collection_artifacts")
    _, grant_manifest_type = _api()
    _, _, plan = _plan_case()
    binding_sets = _binding_sets(plan)

    binding_manifest = module.ProviderBindingCollectionManifest.create(
        plan,
        tuple(
            module.ProviderBindingCollectionMember(
                execution_slice_id=execution_slice.execution_slice_id,
                execution_slice_hash=execution_slice.execution_slice_hash,
                materialization_id=execution_slice.materialization_id,
                owner_ref=StableRef(
                    binding_set.binding_set_id,
                    binding_set.binding_set_hash,
                ),
            )
            for execution_slice, binding_set in zip(
                plan.execution_slices,
                binding_sets,
                strict=True,
            )
        ),
    )
    grant_manifest = grant_manifest_type.create(
        plan,
        _grant_members(plan, binding_sets),
    )

    assert grant_manifest.execution_plan_id == binding_manifest.execution_plan_id
    assert grant_manifest.execution_plan_hash == binding_manifest.execution_plan_hash
    assert (
        grant_manifest.materialization_plan_hash
        == binding_manifest.materialization_plan_hash
    )
    assert grant_manifest.required_slice_refs == binding_manifest.required_slice_refs
    assert tuple(item.execution_slice_id for item in grant_manifest.members) == tuple(
        item.execution_slice_id for item in plan.execution_slices
    )
    assert not hasattr(grant_manifest, "admitted")
    assert not hasattr(grant_manifest, "authority")
    assert not hasattr(grant_manifest, "readiness")


@dataclass
class _Approval:
    """canonical adapter 测试所需最小 Gateway approval owner body。"""

    approval_id: str
    approval_hash: str


@dataclass
class _StoredApproval:
    """匹配 Gateway store get_approval() 的 read shape。"""

    record: _Approval


class _ApprovalStore:
    """只允许读取一个 exact approval；不拥有 grant issuance。"""

    def __init__(self, approval: _Approval) -> None:
        self._approval = approval

    def get_approval(self, approval_id: str):
        """按 exact approval id 返回 durable record。"""

        if approval_id != self._approval.approval_id:
            return None
        return _StoredApproval(self._approval)


class _Gateway:
    """记录两个 Slice 的真实 ExecutionGrantRequestV2，并返回确定性 grant。"""

    def __init__(self) -> None:
        self.requests = []
        self.admissions: list[tuple[str, str]] = []

    def issue_execution_grant(self, request):
        """验证请求携带 exact Slice/binding 后生成 original Gateway grant。"""

        self.requests.append(request)
        index = len(self.requests)
        grant_hash = f"{index + 7:x}" * 64
        return ExecutionGrantV2(
            grant_id=f"XGV2-{index - 1}",
            approval_id=request.approval_id,
            approval_hash="a" * 64,
            changeset_hash=request.execution_plan.changeset_hash,
            approved_scope_hash=request.approval_scope_boundary.scope_hash,
            materialization_plan_hash=request.materialization_plan.materialization_plan_hash,
            materialization_id=request.execution_slice.materialization_id,
            execution_slice_id=request.execution_slice.execution_slice_id,
            execution_slice_hash=request.execution_slice.execution_slice_hash,
            binding_set_hash=request.provider_binding_set.binding_set_hash,
            host_instance_id=request.execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=("set_wall_thickness.v1",),
            issued_at=request.issued_at,
            expires_at="2026-10-08T00:00:00Z",
            grant_hash=grant_hash,
        )

    def admit_execution_grant(self, grant_hash: str, admitted_at: str):
        """记录 admission 调用；返回值只证明 exact grant hash 未漂移。"""

        self.admissions.append((grant_hash, admitted_at))
        return SimpleNamespace(grant_hash=grant_hash)


class _Clock:
    """为两个 grant 使用同一 deterministic UTC issuance time。"""

    def now(self) -> datetime:
        """返回 timezone-aware UTC 时间。"""

        return datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


def test_issue_execution_grant_for_two_slices_persists_only_grant_refs_manifest() -> None:
    """adapter 必须逐 Slice issue/admit，再只保存 original Gateway grant refs。"""

    module = import_module("design_orchestrator.execution_collection_artifacts")
    _, grant_manifest_type = _api()
    case, materialization_plan, plan = _plan_case()
    binding_sets = _binding_sets(plan)

    plan_store = InMemoryExecutionPlanV2Store()
    plan_store.put(plan)
    binding_store = InMemoryProviderBindingSetV2Store()
    for binding_set in binding_sets:
        binding_store.put(binding_set)

    artifact_store = _ArtifactStore()
    binding_manifest = module.ProviderBindingCollectionManifest.create(
        plan,
        tuple(
            module.ProviderBindingCollectionMember(
                execution_slice_id=execution_slice.execution_slice_id,
                execution_slice_hash=execution_slice.execution_slice_hash,
                materialization_id=execution_slice.materialization_id,
                owner_ref=StableRef(
                    binding_set.binding_set_id,
                    binding_set.binding_set_hash,
                ),
            )
            for execution_slice, binding_set in zip(
                plan.execution_slices,
                binding_sets,
                strict=True,
            )
        ),
    )
    binding_manifest_ref = artifact_store.put(
        kind="provider_binding_collection_manifest",
        value=binding_manifest,
        content_hash=workflow_artifact_content_hash(binding_manifest),
    )

    materialization_store = InMemoryMaterializationPlanStore()
    materialization_store.put(materialization_plan)
    topology_registry = MaterializationTopologyRegistry()
    topology_registry.register(case.topology)
    scope_store = InMemoryApprovalScopeStore()
    scope_store.put_boundary(case.boundary_v2)

    approval = _Approval("APP-TASK9", "a" * 64)
    gateway = _Gateway()
    adapter, *_ = _task6_adapter(
        artifact_store=artifact_store,
        overrides={
            "execution_plan_store": plan_store,
            "provider_binding_store": binding_store,
            "materialization_plan_store": materialization_store,
            "topology_registry": topology_registry,
            "topology_environment_id": case.topology.topology_environment_id,
            "topology_revision": case.topology.topology_revision,
            "approval_scope_store": scope_store,
            "gateway_authorization_store": _ApprovalStore(approval),
            "gateway_authorization": gateway,
            "coordination_clock": _Clock(),
        },
    )

    grant_manifest_ref = adapter.issue_execution_grant(
        StableRef(plan.execution_plan_id, plan.execution_plan_hash),
        StableRef(approval.approval_id, approval.approval_hash),
        binding_manifest_ref,
    )
    grant_manifest = artifact_store.get(grant_manifest_ref)

    assert isinstance(grant_manifest, grant_manifest_type)
    assert grant_manifest.required_slice_refs == binding_manifest.required_slice_refs
    assert len(gateway.requests) == 2
    assert len(gateway.admissions) == 2
    for request, execution_slice, binding_set in zip(
        gateway.requests,
        plan.execution_slices,
        binding_sets,
        strict=True,
    ):
        assert request.execution_plan == plan
        assert request.execution_slice == execution_slice
        assert request.provider_binding_set == binding_set
        assert request.materialization_plan == materialization_plan
        assert request.topology_snapshot == case.topology
        assert request.approval_scope_boundary == case.boundary_v2


def test_grant_manifest_content_hash_is_deterministic() -> None:
    """相同 plan/Slice/grant refs 必须得到同一个 workflow artifact hash。"""

    _, manifest_type = _api()
    _, _, plan = _plan_case()
    binding_sets = _binding_sets(plan)
    first = manifest_type.create(plan, _grant_members(plan, binding_sets))
    second = manifest_type.create(plan, _grant_members(plan, binding_sets))

    assert first == second
    assert workflow_artifact_content_hash(first) == workflow_artifact_content_hash(second)
