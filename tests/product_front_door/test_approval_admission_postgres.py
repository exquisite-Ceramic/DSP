"""Task 5：configured-policy ApprovalAdmission 的 PostgreSQL durable issuance 契约。"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psycopg
import pytest
from design_approval_scope import (
    InMemoryApprovalScopeStore,
    bind_changeset_v2,
    bind_topology_snapshot_v2,
)
from design_changeset import InMemoryChangeSetStore, validate_changeset_integrity_v2
from design_gateway_authorization import ApprovalAdmission, compute_admission_fingerprint
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


class _BarrierPolicySource:
    """把两个首次 issuance 都停在 policy-load 阶段，制造真实跨连接竞争窗口。"""

    def __init__(self, policy, barrier: threading.Barrier) -> None:
        self._policy = policy
        self._barrier = barrier

    def load(self):
        """确认双方都已完成 durable existing lookup 后，再同时继续构造 admission。"""

        self._barrier.wait(timeout=10)
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


def _reset_policy_schema(dsn: str) -> None:
    """为每个并发场景清空 issuance owner schema，避免跨测试 durable winner 污染。"""

    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS product_policy CASCADE")


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


def _policy(*, principal: str = "local:operator"):
    """构造只允许本 reference vertical 的最小 configured policy。"""

    return front_door.ConfiguredProductApprovalPolicy.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
            "policy_id": "local-wall-thickness-v1",
            "principal": principal,
            "project_ids": ["project-id"],
            "allowed_canonical_operations": ["set_wall_thickness.v1"],
            "admission_ttl_seconds": 900,
        }
    )


def _port(
    port_type,
    *,
    changeset_store,
    scope_store,
    admission_store,
    policy_source,
    admission_id: str,
):
    """用统一 clock 组装并发 issuance port，使 admission id 成为唯一非 authority 差异。"""

    return port_type(
        changeset_store=changeset_store,
        approval_scope_store=scope_store,
        admission_store=admission_store,
        policy_source=policy_source,
        clock=_Clock("2026-09-29T10:00:00Z"),
        id_factory=lambda: admission_id,
    )


def test_configured_policy_admission_public_surface_exists() -> None:
    """Task 5 Step 2 需要 durable store 与真实 admission port 两个明确公共 seam。"""

    _public_types()


def test_first_issuance_persists_and_fresh_store_replays_exact_admission() -> None:
    """首次 issuance 持久化；重建 store 后即使 policy/clock/id 已变也必须返回原 winner。"""

    admission_store_type, port_type = _public_types()
    dsn = _postgres_dsn()
    _reset_policy_schema(dsn)

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


def test_concurrent_same_policy_authority_converges_on_one_durable_winner() -> None:
    """两个独立 PostgreSQL 连接并发首次签发同 authority 时只能产生一个 durable Admission。"""

    admission_store_type, port_type = _public_types()
    dsn = _postgres_dsn()
    _reset_policy_schema(dsn)
    changeset, boundary, changeset_store, scope_store = _authoritative_case()
    changeset_ref = StableRef(changeset.changeset_id, changeset.changeset_hash)
    barrier = threading.Barrier(2)
    stores = (admission_store_type(dsn), admission_store_type(dsn))
    ports = (
        _port(
            port_type,
            changeset_store=changeset_store,
            scope_store=scope_store,
            admission_store=stores[0],
            policy_source=_BarrierPolicySource(_policy(), barrier),
            admission_id="ADM-RACE-A",
        ),
        _port(
            port_type,
            changeset_store=changeset_store,
            scope_store=scope_store,
            admission_store=stores[1],
            policy_source=_BarrierPolicySource(_policy(), barrier),
            admission_id="ADM-RACE-B",
        ),
    )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda port: port.request_approval(changeset_ref), ports))

        assert results[0] == results[1]
        assert results[0].admission_id in {"ADM-RACE-A", "ADM-RACE-B"}
        assert results[0].admission_fingerprint == compute_admission_fingerprint(results[0])
        assert stores[0].get(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        ) == results[0]
    finally:
        for store in stores:
            store.close()


def test_concurrent_different_policy_authority_allows_one_winner_and_one_conflict() -> None:
    """同一 final lineage 并发首次读取不同 policy body 时，一方胜出，另一方必须 conflict。"""

    admission_store_type, port_type = _public_types()
    dsn = _postgres_dsn()
    _reset_policy_schema(dsn)
    changeset, _, changeset_store, scope_store = _authoritative_case()
    changeset_ref = StableRef(changeset.changeset_id, changeset.changeset_hash)
    barrier = threading.Barrier(2)
    stores = (admission_store_type(dsn), admission_store_type(dsn))
    ports = (
        _port(
            port_type,
            changeset_store=changeset_store,
            scope_store=scope_store,
            admission_store=stores[0],
            policy_source=_BarrierPolicySource(_policy(principal="local:operator-a"), barrier),
            admission_id="ADM-CONFLICT-A",
        ),
        _port(
            port_type,
            changeset_store=changeset_store,
            scope_store=scope_store,
            admission_store=stores[1],
            policy_source=_BarrierPolicySource(_policy(principal="local:operator-b"), barrier),
            admission_id="ADM-CONFLICT-B",
        ),
    )

    def compete(port):
        """把 winner/loser 都转成可断言结果，避免线程异常丢失稳定错误码。"""

        try:
            return port.request_approval(changeset_ref)
        except ValueError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(compete, ports))

        winners = tuple(item for item in outcomes if isinstance(item, ApprovalAdmission))
        conflicts = tuple(item for item in outcomes if isinstance(item, ValueError))
        assert len(winners) == 1
        assert len(conflicts) == 1
        assert "FRONT_DOOR_APPROVAL_ADMISSION_CONFLICT" in str(conflicts[0])
    finally:
        for store in stores:
            store.close()
