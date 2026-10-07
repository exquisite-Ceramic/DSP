"""Cross-Host Product Vertical Task 8：ProviderBinding collection manifest 契约。"""

from __future__ import annotations

import os
from dataclasses import replace
from importlib import import_module

import pytest
from design_execution_planning import (
    InMemoryExecutionPlanV2Store,
    plan_materialized_execution,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import StableRef
from design_provider_binding import InMemoryProviderBindingSetV2Store

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.orchestrator.test_canonical_owner_ports import _ArtifactStore, _task6_adapter
from tests.provider_binding._support import build_phase_i_binding_inputs


def _api():
    """延迟加载 Task 8 新 manifest，使 test-only commit 形成明确 TDD RED。"""

    module = import_module(
        "design_orchestrator.execution_collection_artifacts"
    )
    member_type = getattr(module, "ProviderBindingCollectionMember", None)
    manifest_type = getattr(module, "ProviderBindingCollectionManifest", None)
    assert member_type is not None, "ProviderBindingCollectionMember 尚未实现"
    assert manifest_type is not None, "ProviderBindingCollectionManifest 尚未实现"
    return member_type, manifest_type


def _execution_plan():
    """用仓库 Phase I 两 materialization fixture 生成真实 Step30 V2 plan。"""

    _, _, _, request = build_phase_i_execution_inputs()
    plan = plan_materialized_execution(request)
    assert len(plan.execution_slices) == 2
    return plan


def _members(plan):
    """按 execution-plan 顺序构造只含 original-owner refs 的 manifest members。"""

    member_type, _ = _api()
    return tuple(
        member_type(
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            materialization_id=execution_slice.materialization_id,
            owner_ref=StableRef(
                f"PBSV2-{index}",
                f"{index + 1:x}" * 64,
            ),
        )
        for index, execution_slice in enumerate(plan.execution_slices)
    )


def test_binding_manifest_covers_exact_required_slice_set_in_plan_order() -> None:
    """manifest membership 必须与 ExecutionPlanV2 两个 REQUIRED Slice 一一对应且保序。"""

    _, manifest_type = _api()
    plan = _execution_plan()
    members = _members(plan)

    manifest = manifest_type.create(plan, members)

    assert manifest.execution_plan_id == plan.execution_plan_id
    assert manifest.execution_plan_hash == plan.execution_plan_hash
    assert manifest.materialization_plan_hash == plan.materialization_plan_hash
    assert tuple(
        (item.ref_id, item.content_hash)
        for item in manifest.required_slice_refs
    ) == tuple(
        (item.execution_slice_id, item.execution_slice_hash)
        for item in plan.execution_slices
    )
    assert manifest.members == members
    assert tuple(item.execution_slice_id for item in manifest.members) == tuple(
        item.execution_slice_id for item in plan.execution_slices
    )
    assert all(hasattr(item, "owner_ref") for item in manifest.members)
    assert not hasattr(manifest, "provider_eligibility")
    assert not hasattr(manifest, "grant")
    assert not hasattr(manifest, "authority")


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "extra", "wrong_slice_hash", "wrong_plan"],
)
def test_binding_manifest_rejects_missing_duplicate_extra_or_wrong_plan_lineage(
    mutation: str,
) -> None:
    """coverage 或 plan lineage 任何偏差都必须在 manifest 构造边界 fail closed。"""

    member_type, manifest_type = _api()
    plan = _execution_plan()
    members = list(_members(plan))

    if mutation == "missing":
        members.pop()
    elif mutation == "duplicate":
        members[1] = members[0]
    elif mutation == "extra":
        members.append(
            member_type(
                execution_slice_id="XSLICE-EXTRA",
                execution_slice_hash="e" * 64,
                materialization_id="MAT-EXTRA",
                owner_ref=StableRef("PBSV2-extra", "f" * 64),
            )
        )
    elif mutation == "wrong_slice_hash":
        members[0] = replace(
            members[0],
            execution_slice_hash="9" * 64,
        )
    elif mutation == "wrong_plan":
        plan = replace(
            plan,
            materialization_plan_hash="8" * 64,
        )

    with pytest.raises(ValueError, match="PROVIDER_BINDING_COLLECTION_INVALID"):
        manifest_type.create(plan, tuple(members))


def test_binding_manifest_rejects_owner_ref_without_content_hash() -> None:
    """manifest 只能保存 original owner 的完整 StableRef，不能只存短 id。"""

    member_type, manifest_type = _api()
    plan = _execution_plan()
    members = list(_members(plan))
    members[0] = replace(
        members[0],
        owner_ref=StableRef("PBSV2-without-hash"),
    )

    with pytest.raises(ValueError, match="PROVIDER_BINDING_COLLECTION_INVALID"):
        manifest_type.create(plan, tuple(members))


def test_bind_providers_for_two_slices_stores_original_owner_sets_then_manifest() -> None:
    """canonical adapter 必须逐 Slice 调真实 Step31 owner，再只持久化 refs manifest。"""

    member_type, manifest_type = _api()
    del member_type
    _, _, snapshots = build_phase_i_binding_inputs()
    _, _, _, request = build_phase_i_execution_inputs()
    plan = plan_materialized_execution(request)

    plan_store = InMemoryExecutionPlanV2Store()
    plan_store.put(plan)
    binding_store = InMemoryProviderBindingSetV2Store()
    artifact_store = _ArtifactStore()
    calls: list[str] = []

    def _snapshot_provider(execution_slice):
        """按 exact Host type 返回该 Slice 自己的 ProviderExecutionSnapshotV2。"""

        host_type = execution_slice.host_runtime_ref.host_type
        calls.append(host_type)
        return snapshots[host_type]

    adapter, *_ = _task6_adapter(
        artifact_store=artifact_store,
        overrides={
            "execution_plan_store": plan_store,
            "provider_binding_store": binding_store,
            "provider_execution_snapshot": _snapshot_provider,
        },
    )
    manifest_ref = adapter.bind_providers(
        StableRef(plan.execution_plan_id, plan.execution_plan_hash)
    )
    manifest = artifact_store.get(manifest_ref)

    assert isinstance(manifest, manifest_type)
    assert tuple(calls) == tuple(
        item.host_runtime_ref.host_type for item in plan.execution_slices
    )
    assert manifest.execution_plan_id == plan.execution_plan_id
    assert tuple(item.execution_slice_id for item in manifest.members) == tuple(
        item.execution_slice_id for item in plan.execution_slices
    )
    for item in manifest.members:
        stored = binding_store.get(item.owner_ref.ref_id)
        assert stored.binding_set_hash == item.owner_ref.content_hash
        assert stored.execution_slice_id == item.execution_slice_id
        assert stored.execution_slice_hash == item.execution_slice_hash
        assert stored.materialization_id == item.materialization_id


def test_binding_manifest_survives_postgres_artifact_restart() -> None:
    """manifest body 必须由 Workflow Orchestrator artifact owner 跨进程恢复。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")

    postgres = import_module("design_orchestrator.artifact_postgres")
    _, manifest_type = _api()
    plan = _execution_plan()
    manifest = manifest_type.create(plan, _members(plan))

    store_a = postgres.create_postgres_artifact_store(dsn)
    try:
        ref = store_a.put(
            kind="provider_binding_collection_manifest",
            value=manifest,
            content_hash=workflow_artifact_content_hash(manifest),
        )
    finally:
        store_a.close()

    store_b = postgres.create_postgres_artifact_store(dsn)
    try:
        restored = store_b.get(ref)
    finally:
        store_b.close()

    assert restored == manifest
    assert workflow_artifact_content_hash(restored) == ref.content_hash
