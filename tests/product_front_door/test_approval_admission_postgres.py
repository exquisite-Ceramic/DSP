"""Task 5：configured-policy ApprovalAdmission 的 PostgreSQL durable issuance 契约。"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import design_product_front_door as front_door
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
        self._value = datetime.fromisoformat(value)

    def now(self) -> datetime:
        """返回 timezone-aware UTC datetime。"""

        return self._value.astimezone(UTC)


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


# --- Cross-Host Product Vertical Task 7: durable V2 policy snapshot replay ---


def _v2_policy_api():
    """延迟加载 V2 policy/port，使 RED 精确落在 Task 7 public seam。"""

    from importlib import import_module

    module = import_module("design_product_front_door.approval_policy_v2")
    policy_type = getattr(module, "ConfiguredProductApprovalPolicyV2", None)
    port_type = getattr(module, "ConfiguredPolicyApprovalAdmissionPortV2", None)
    assert policy_type is not None
    assert port_type is not None
    return policy_type, port_type


def _v2_policy_for_case(changeset, boundary):
    """按当前 authoritative case 构造 exact V2 stable capability policy。"""

    policy_type, _ = _v2_policy_api()
    return policy_type.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
            "policy_id": "cross-host-wall-thickness-v2",
            "principal": "local:operator",
            "project_ids": [changeset.project_id],
            "allowed_canonical_operations": ["set_wall_thickness.v1"],
            "reviewed_configuration_hash": "a" * 64,
            "semantic_target_ids": [changeset.root_operation.targets[0]],
            "allowed_topology_snapshot_hashes": [boundary.topology_snapshot_hash],
            "required_host_roles": {
                "AUTOCAD": "BOUND_REQUIRED",
                "REVIT": "INITIATOR",
            },
            "admission_ttl_seconds": 900,
        }
    )


class _AcceptedInputReaderV2:
    """按 ChangeSet.task_id 返回 server-owned immutable binding authority。"""

    def __init__(self, accepted) -> None:
        self.accepted = accepted
        self.calls: list[str] = []

    def get_v2(self, task_id: str):
        """只支持 exact task，不做 latest/reverse lookup。"""

        self.calls.append(task_id)
        if task_id != self.accepted.request.task_id:
            return None
        return self.accepted


def _accepted_input_for_case(changeset, boundary):
    """构造与 authoritative ChangeSet/scope 对齐的 exact two-Host accepted input。"""

    from design_product_front_door import SessionBindingMemberV2, SessionBindingV2
    from design_product_runtime import ProductTaskRequestV2
    from design_product_runtime.accepted_input import AcceptedProductTaskInputV2

    semantic_target = changeset.root_operation.targets[0]
    binding = SessionBindingV2.create(
        session_ref=f"session-{changeset.task_id}",
        project_id=changeset.project_id,
        semantic_target_id=semantic_target,
        semantic_environment_id=changeset.semantic_environment_ref.environment_id,
        # SessionBindingV2 要求规范 64-hex environment hash；本测试只验证
        # policy/topology/Host-role authority，不把 build_case 的 legacy ref 编码当作 V2 hash。
        semantic_environment_hash="f" * 64,
        topology_environment_id="TOPOLOGY-V2",
        topology_revision=7,
        topology_snapshot_hash=boundary.topology_snapshot_hash,
        initiating_host_kind="REVIT",
        members=(
            SessionBindingMemberV2(
                host_kind="AUTOCAD",
                role="BOUND_REQUIRED",
                configured_reference_id="primary-autocad",
                configured_reference_hash="b" * 64,
                transport_locator="autocad-pipe",
                host_instance_id="autocad-runtime",
                document_id=r"C:\DSP\fixture.dwg",
                native_target_id="autocad-wall",
                host_binding_fingerprint="c" * 64,
            ),
            SessionBindingMemberV2(
                host_kind="REVIT",
                role="INITIATOR",
                configured_reference_id="primary-revit",
                configured_reference_hash="d" * 64,
                transport_locator="revit-pipe",
                host_instance_id="revit-runtime",
                document_id=r"C:\DSP\fixture.rvt",
                native_target_id="revit-wall",
                host_binding_fingerprint="e" * 64,
            ),
        ),
    )
    request = ProductTaskRequestV2.create(
        task_id=changeset.task_id,
        project_id=changeset.project_id,
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    payload = {
        "session_ref": binding.session_ref,
        "project_id": binding.project_id,
        "semantic_target_id": binding.semantic_target_id,
        "semantic_environment_id": binding.semantic_environment_id,
        "semantic_environment_hash": binding.semantic_environment_hash,
        "topology_environment_id": binding.topology_environment_id,
        "topology_revision": binding.topology_revision,
        "topology_snapshot_hash": binding.topology_snapshot_hash,
        "initiating_host_kind": binding.initiating_host_kind,
        "members": [
            {
                "host_kind": member.host_kind,
                "role": member.role,
                "configured_reference_id": member.configured_reference_id,
                "configured_reference_hash": member.configured_reference_hash,
                "transport_locator": member.transport_locator,
                "host_instance_id": member.host_instance_id,
                "document_id": member.document_id,
                "native_target_id": member.native_target_id,
                "host_binding_fingerprint": member.host_binding_fingerprint,
            }
            for member in binding.members
        ],
        "binding_hash": binding.binding_hash,
    }
    return AcceptedProductTaskInputV2(
        request,
        binding.binding_hash,
        payload,
    )


def test_v1_policy_cannot_authorize_v2_cross_host_task() -> None:
    """V2 port 必须显式拒绝既有 V1 policy，不能把单 Host policy 隐式升级。"""

    admission_store_type, _ = _public_types()
    _, v2_port_type = _v2_policy_api()
    dsn = _postgres_dsn()
    _reset_policy_schema(dsn)
    changeset, _, changeset_store, scope_store = _authoritative_case()
    boundary = scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
    accepted_reader = _AcceptedInputReaderV2(
        _accepted_input_for_case(changeset, boundary)
    )
    store = admission_store_type(dsn)
    try:
        port = v2_port_type(
            changeset_store=changeset_store,
            approval_scope_store=scope_store,
            admission_store=store,
            accepted_input_reader=accepted_reader,
            policy_source=_StaticPolicySource(_policy()),
            clock=_Clock("2026-10-07T00:00:00Z"),
            id_factory=lambda: "ADM-V2-MUST-DENY",
        )
        with pytest.raises(ValueError, match="FRONT_DOOR_APPROVAL_POLICY"):
            port.request_approval(
                StableRef(changeset.changeset_id, changeset.changeset_hash)
            )
    finally:
        store.close()


def test_v2_admission_replay_uses_durable_policy_snapshot_not_current_config() -> None:
    """replay 必须验证签发时持久化 policy body，而不是重新加载当前配置。"""

    admission_store_type, _ = _public_types()
    _, v2_port_type = _v2_policy_api()
    dsn = _postgres_dsn()
    _reset_policy_schema(dsn)
    changeset, boundary, changeset_store, scope_store = _authoritative_case()
    accepted = _accepted_input_for_case(changeset, boundary)
    accepted_reader = _AcceptedInputReaderV2(accepted)
    policy = _v2_policy_for_case(changeset, boundary)
    changeset_ref = StableRef(changeset.changeset_id, changeset.changeset_hash)

    first_store = admission_store_type(dsn)
    try:
        first_port = v2_port_type(
            changeset_store=changeset_store,
            approval_scope_store=scope_store,
            admission_store=first_store,
            accepted_input_reader=accepted_reader,
            policy_source=_StaticPolicySource(policy),
            clock=_Clock("2026-10-07T00:00:00Z"),
            id_factory=lambda: "ADM-CROSS-HOST-V2",
        )
        first = first_port.request_approval(changeset_ref)
        stored = first_store.get_v2(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        )
        assert stored is not None
        assert stored.admission == first
        assert stored.policy_version == "DSP_PRODUCT_APPROVAL_POLICY_V2"
        assert stored.policy_snapshot_payload["version"] == "DSP_PRODUCT_APPROVAL_POLICY_V2"
        assert canonical_hash(stored.policy_snapshot_payload) == first.policy_snapshot_hash
    finally:
        first_store.close()

    reopened = admission_store_type(dsn)
    try:
        replay = v2_port_type(
            changeset_store=changeset_store,
            approval_scope_store=scope_store,
            admission_store=reopened,
            accepted_input_reader=accepted_reader,
            policy_source=_ForbiddenPolicySource(),
            clock=_Clock("2030-01-01T00:00:00Z"),
            id_factory=lambda: "ADM-MUST-NOT-WIN",
        ).request_approval(changeset_ref)
        assert replay == first
    finally:
        reopened.close()
