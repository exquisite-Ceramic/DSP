"""Task 5：configured-policy ApprovalAdmission 的 PostgreSQL durable issuance 契约。"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
import pytest
from design_approval_scope import (
    InMemoryApprovalScopeStore,
    bind_changeset_v2,
    bind_topology_snapshot_v2,
)
from design_changeset import InMemoryChangeSetStore, validate_changeset_integrity_v2
from design_gateway_authorization import compute_admission_fingerprint
from design_orchestrator.workflow_contracts import StableRef
import design_product_front_door as front_door

from tests.materialization_planning._support import build_case


class _StaticPolicySource:
    """返回同一份已经规范化 policy authority，便于隔离 issuance 行为。"""

    def __init__(self, policy) -> None:
        self._policy = policy
        self.calls = 0

    def load(self):
        """返回 configured policy，并记录真正的新 issuance 是否读取了 policy。"""

        self.calls += 1
        return self._policy


class _ForbiddenPolicySource:
    """durable replay 若再次读取 policy，测试必须立即失败。"""

    def load(self):
        """已签发 admission 的 replay 不允许依赖当前 policy 文件仍然存在。"""

        raise AssertionError("durable admission replay must not reload configured policy")


class _Clock:
    """提供可预测的 UTC issuance 时间。"""

    def __init__(self, value: str) -> None:
        self._value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    def now(self) -> datetime:
        """返回 timezone-aware UTC datetime。"""

        return self._value.astimezone(timezone.utc)


def _public_types():
    """延迟取得 Task 5 新类型，使缺失实现形成明确 TDD RED。"""

    admission_store_type = getattr(front_door, "PostgresConfiguredPolicyAdmissionStore", None)
    port_type = getattr(front_door, "ConfiguredPolicyApprovalAdmissionPort", None)
    assert admission_store_type is not None, "PostgresConfiguredPolicyAdmissionStore 尚未实现"
    assert port_type is not None, "ConfiguredPolicyApprovalAdmissionPort 尚未实现"
    return admission_store_type, port_type


def _postgres_dsn() -> str:
    """只在显式 PostgreSQL lane 执行真实 durable issuance acceptance。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _authoritative_case():
    """用仓库真实 builders 生成合法 wall-thickness ChangeSet + final BoundaryV2。"""

    case = build_case(project_id="project-id")
    scope_v2 = bind_topology_snapshot_v2(
        case.scope_v1,
        case.topology.topology_snapshot_hash,
    )
    boundary = bind_changeset_v2(
        scope_v2,
        case.changeset.changeset_hash,
        f"SCOPE-{case.changeset.changeset_id}",
    )
    validate_changeset_integrity_v2(case.changeset, boundary)

    changeset_store = InMemoryChangeSetStore()
    scope_store = InMemoryApprovalScopeStore()
    changeset_store.put(case.changeset)
    scope_store.put_definition(scope_v2)
    scope_store.put_boundary(boundary)
    return case.changeset, boundary, changeset_store, scope_store


def _policy():
    """构造只允许本 reference vertical 的最小 configured policy。"""

    return front_door.ConfiguredProductApprovalPolicy.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
            "policy_id": "local-wall-thickness-v1",
            "principal": "local:operator",
            "project_ids": ["project-id"],
            "allowed_canonical_operations": ["set_wall_thickness.v1"],
            "admission_ttl_seconds": 900,
        }
    )


def test_configured_policy_admission_public_surface_exists() -> None:
    """Task 5 Step 2 需要 durable store 与真实 admission port 两个明确公共 seam。"""

    _public_types()


def test_first_issuance_persists_and_fresh_store_replays_exact_admission() -> None:
    """首次 issuance 持久化；重建 store 后即使 policy/clock/id 已变也必须返回原 winner。"""

    admission_store_type, port_type = _public_types()
    dsn = _postgres_dsn()
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS product_policy CASCADE")

    changeset, boundary, changeset_store, scope_store = _authoritative_case()
    policy = _policy()
    policy_source = _StaticPolicySource(policy)
    changeset_ref = StableRef(changeset.changeset_id, changeset.changeset_hash)

    first_store = admission_store_type(dsn)
    try:
        first_port = port_type(
            changeset_store=changeset_store,
            approval_scope_store=scope_store,
            admission_store=first_store,
            policy_source=policy_source,
            clock=_Clock("2026-09-29T10:00:00Z"),
            id_factory=lambda: "ADM-CONFIGURED-001",
        )
        first = first_port.request_approval(changeset_ref)

        assert first.admission_id == "ADM-CONFIGURED-001"
        assert first.changeset_hash == changeset.changeset_hash
        assert first.approved_scope_hash == boundary.scope_hash
        assert first.semantic_environment_ref == changeset.semantic_environment_ref
        assert first.approver == "local:operator"
        assert first.policy_snapshot_hash == policy.policy_snapshot_hash
        assert first.policy_allowed_operations == ("set_wall_thickness.v1",)
        assert first.approved_at == "2026-09-29T10:00:00Z"
        assert first.expires_at == "2026-09-29T10:15:00Z"
        assert first.admission_fingerprint == compute_admission_fingerprint(first)
        assert policy_source.calls == 1
    finally:
        first_store.close()

    reopened_store = admission_store_type(dsn)
    try:
        replay_port = port_type(
            changeset_store=changeset_store,
            approval_scope_store=scope_store,
            admission_store=reopened_store,
            policy_source=_ForbiddenPolicySource(),
            clock=_Clock("2030-01-01T00:00:00Z"),
            id_factory=lambda: "ADM-MUST-NOT-WIN",
        )
        replayed = replay_port.request_approval(changeset_ref)

        assert replayed == first
        assert reopened_store.get(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        ) == first
    finally:
        reopened_store.close()
