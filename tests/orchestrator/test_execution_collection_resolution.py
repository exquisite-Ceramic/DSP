"""Cross-Host Product Vertical Task 9：execution collection 只读解析契约。"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_execution_planning import plan_materialized_execution
from design_gateway_authorization import ExecutionGrantV2
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import resolve_provider_bindings_v2

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.orchestrator.test_canonical_owner_ports import _ArtifactStore
from tests.provider_binding._support import build_phase_i_binding_inputs


def _modules():
    """延迟取得 Task 9 artifacts/resolver，使 RED 精确指向缺失 capability。"""

    artifacts = import_module("design_orchestrator.execution_collection_artifacts")
    resolution = import_module("design_orchestrator.execution_collection_resolution")
    return artifacts, resolution


def _plan_and_bindings():
    """生成两个 required Slice 及其真实 ProviderBindingSetV2。"""

    _, _, _, request = build_phase_i_execution_inputs()
    plan = plan_materialized_execution(request)
    _, _, snapshots = build_phase_i_binding_inputs()
    bindings = tuple(
        resolve_provider_bindings_v2(
            execution_slice,
            snapshots[execution_slice.host_runtime_ref.host_type],
        )
        for execution_slice in plan.execution_slices
    )
    return plan, bindings


class _BindingStore:
    """只提供 read-only get；任何未声明动作都视为 resolver 越权。"""

    def __init__(self, bindings) -> None:
        self._items = {item.binding_set_id: item for item in bindings}
        self.calls: list[str] = []

    def get(self, binding_set_id: str):
        """读取 original ProviderBinding owner object。"""

        self.calls.append(binding_set_id)
        return self._items[binding_set_id]

    def __getattr__(self, name: str):
        raise AssertionError(f"resolver touched non-read binding owner method: {name}")


class _GatewayStore:
    """只提供 get_grant_v2；admission/revocation/readiness 不属于 collection resolver。"""

    def __init__(self, grants) -> None:
        self._items = {item.grant_hash: item for item in grants}
        self.calls: list[str] = []

    def get_grant_v2(self, grant_hash: str):
        """按完整 content hash 读取 original Gateway grant。"""

        self.calls.append(grant_hash)
        return self._items.get(grant_hash)

    def __getattr__(self, name: str):
        raise AssertionError(f"resolver touched non-read Gateway method: {name}")


def _grants(plan, bindings):
    """构造 owner-valid shape 的两条 immutable grant read model。"""

    return tuple(
        ExecutionGrantV2(
            grant_id=f"GRANT-TASK9-{index}",
            approval_id="APP-TASK9",
            approval_hash="a" * 64,
            changeset_hash=plan.changeset_hash,
            approved_scope_hash=plan.approval_scope_ref.scope_hash,
            materialization_plan_hash=plan.materialization_plan_hash,
            materialization_id=execution_slice.materialization_id,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            allowed_operations=("set_wall_thickness.v1",),
            issued_at="2026-10-07T01:00:00Z",
            expires_at="2026-10-08T01:00:00Z",
            grant_hash=f"{index + 9:x}" * 64,
        )
        for index, (execution_slice, binding_set) in enumerate(
            zip(plan.execution_slices, bindings, strict=True)
        )
    )


def _manifests(plan, bindings, grants):
    """构造两个 collection manifests，并持久化到 workflow artifact store。"""

    artifacts, _ = _modules()
    store = _ArtifactStore()

    binding_manifest = artifacts.ProviderBindingCollectionManifest.create(
        plan,
        tuple(
            artifacts.ProviderBindingCollectionMember(
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
                bindings,
                strict=True,
            )
        ),
    )
    binding_ref = store.put(
        kind="provider_binding_collection_manifest",
        value=binding_manifest,
        content_hash=workflow_artifact_content_hash(binding_manifest),
    )

    grant_manifest = artifacts.ExecutionGrantCollectionManifest.create(
        plan,
        tuple(
            artifacts.ExecutionGrantCollectionMember(
                execution_slice_id=execution_slice.execution_slice_id,
                execution_slice_hash=execution_slice.execution_slice_hash,
                materialization_id=execution_slice.materialization_id,
                owner_ref=StableRef(grant.grant_id, grant.grant_hash),
            )
            for execution_slice, grant in zip(
                plan.execution_slices,
                grants,
                strict=True,
            )
        ),
    )
    grant_ref = store.put(
        kind="execution_grant_collection_manifest",
        value=grant_manifest,
        content_hash=workflow_artifact_content_hash(grant_manifest),
    )
    return store, binding_manifest, binding_ref, grant_manifest, grant_ref


def test_manifest_resolution_does_not_admit_check_readiness_or_execute() -> None:
    """common resolver 只读 manifest 与原 owner objects，不允许任何执行副作用。"""

    _, resolution = _modules()
    plan, bindings = _plan_and_bindings()
    grants = _grants(plan, bindings)
    store, _, binding_ref, _, grant_ref = _manifests(plan, bindings, grants)
    binding_store = _BindingStore(bindings)
    gateway_store = _GatewayStore(grants)

    resolved_bindings = resolution.resolve_provider_binding_collection(
        binding_ref,
        plan,
        store,
        binding_store,
    )
    resolved_grants = resolution.resolve_execution_grant_collection(
        grant_ref,
        plan,
        store,
        gateway_store,
    )

    assert resolved_bindings == bindings
    assert resolved_grants == grants
    assert binding_store.calls == [item.binding_set_id for item in bindings]
    assert gateway_store.calls == [item.grant_hash for item in grants]


@pytest.mark.parametrize("kind", ["binding", "grant"])
def test_partial_or_corrupt_manifest_fails_before_any_owner_mutation(kind: str) -> None:
    """manifest coverage 被破坏时必须在读取任何原 owner 对象前 fail closed。"""

    _, resolution = _modules()
    plan, bindings = _plan_and_bindings()
    grants = _grants(plan, bindings)
    store, binding_manifest, binding_ref, grant_manifest, grant_ref = _manifests(
        plan,
        bindings,
        grants,
    )
    binding_store = _BindingStore(bindings)
    gateway_store = _GatewayStore(grants)

    if kind == "binding":
        object.__setattr__(binding_manifest, "members", binding_manifest.members[:1])
        with pytest.raises(ValueError, match="EXECUTION_COLLECTION_INVALID"):
            resolution.resolve_provider_binding_collection(
                binding_ref,
                plan,
                store,
                binding_store,
            )
    else:
        object.__setattr__(grant_manifest, "members", grant_manifest.members[:1])
        with pytest.raises(ValueError, match="EXECUTION_COLLECTION_INVALID"):
            resolution.resolve_execution_grant_collection(
                grant_ref,
                plan,
                store,
                gateway_store,
            )

    assert binding_store.calls == []
    assert gateway_store.calls == []
