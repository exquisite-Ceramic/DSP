"""Task 15：Cross-Host Product Vertical real-owner authorization matrix。"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest
from design_approval_scope import InMemoryApprovalScopeStore
from design_changeset import InMemoryChangeSetStore
from design_orchestrator.workflow_contracts import StableRef
from design_product_front_door import (
    ConfiguredPolicyApprovalAdmissionPortV2,
    ConfiguredProductApprovalPolicy,
    ConfiguredProductApprovalPolicyV2,
    PostgresConfiguredPolicyAdmissionStore,
    SessionBindingMemberV2,
    SessionBindingV2,
)
from design_product_runtime import (
    ProductTaskRequestV2,
    create_postgres_product_task_request_store,
)

from tests.materialization_planning._support import build_case

_PROJECT_ID = "project-cross-host-task15"
_SESSION_REF = "session-cross-host-task15"


def _dsn() -> str:
    """只在显式 PostgreSQL lane 中执行 real-owner authorization acceptance。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset(dsn: str) -> None:
    """每个 case 清理 ProductTask 与 policy durable owners。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS product_task CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS product_policy CASCADE")


def _binding(case) -> SessionBindingV2:
    """构造与真实 ChangeSet/topology 对齐的 exact two-Host accepted binding。"""

    slots = {slot.required_host_type: slot for slot in case.topology.slots}
    return SessionBindingV2.create(
        session_ref=_SESSION_REF,
        project_id=_PROJECT_ID,
        semantic_target_id="WALL-001",
        semantic_environment_id=case.changeset.semantic_environment_ref.environment_id,
        semantic_environment_hash=case.changeset.semantic_environment_ref.content_hash,
        topology_environment_id=case.topology.topology_environment_id,
        topology_revision=case.topology.topology_revision,
        topology_snapshot_hash=case.topology.topology_snapshot_hash,
        initiating_host_kind="REVIT",
        members=(
            SessionBindingMemberV2(
                host_kind="AUTOCAD",
                role="BOUND_REQUIRED",
                configured_reference_id="task15-autocad",
                configured_reference_hash="a" * 64,
                transport_locator="autocad://task15",
                host_instance_id="AUTOCAD-01",
                document_id=slots["autocad"].document_ref,
                native_target_id="ACAD-HANDLE-TASK15",
                host_binding_fingerprint="b" * 64,
            ),
            SessionBindingMemberV2(
                host_kind="REVIT",
                role="INITIATOR",
                configured_reference_id="task15-revit",
                configured_reference_hash="c" * 64,
                transport_locator="revit://task15",
                host_instance_id="REVIT-01",
                document_id=slots["revit"].document_ref,
                native_target_id="REVIT-UNIQUE-TASK15",
                host_binding_fingerprint="d" * 64,
            ),
        ),
    )


def _binding_payload(binding: SessionBindingV2) -> dict[str, object]:
    """生成 ProductTask owner 实际持久化的完整 SessionBindingV2 JSON body。"""

    return {
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


class _PolicySource:
    """显式返回一次 frozen configured policy；不做环境 fallback。"""

    def __init__(self, policy) -> None:
        self.policy = policy
        self.calls = 0

    def load(self):
        """返回 exact configured policy，并记录是否发生首次 issuance 读取。"""

        self.calls += 1
        return self.policy


class _Clock:
    """为 durable admission issuance 提供确定性 UTC 时间。"""

    def now(self) -> datetime:
        return datetime(2026, 10, 7, 6, 30, tzinfo=UTC)


def _policy(case, *, topology_hash: str | None = None):
    """构造只授权本测试 stable cross-Host capability 的 V2 policy。"""

    return ConfiguredProductApprovalPolicyV2.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
            "policy_id": "task15-cross-host-policy",
            "principal": "local:task15-operator",
            "project_ids": [_PROJECT_ID],
            "allowed_canonical_operations": ["set_wall_thickness.v1"],
            "reviewed_configuration_hash": "e" * 64,
            "semantic_target_ids": ["WALL-001"],
            "allowed_topology_snapshot_hashes": [
                topology_hash or case.topology.topology_snapshot_hash
            ],
            "required_host_roles": {
                "AUTOCAD": "BOUND_REQUIRED",
                "REVIT": "INITIATOR",
            },
            "admission_ttl_seconds": 900,
        }
    )


def _owners(dsn: str, *, policy):
    """组合真实 ProductTask/policy durable owners 与 production ChangeSet/Scope stores。"""

    case = build_case(project_id=_PROJECT_ID)
    binding = _binding(case)
    request = ProductTaskRequestV2.create(
        task_id=case.changeset.task_id,
        project_id=_PROJECT_ID,
        initiating_host_kind="REVIT",
        session_ref=_SESSION_REF,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    requests = create_postgres_product_task_request_store(dsn)
    accepted = requests.create_v2(
        request,
        session_binding_hash=binding.binding_hash,
        session_binding_payload=_binding_payload(binding),
    )

    changesets = InMemoryChangeSetStore()
    changesets.put(case.changeset)
    scopes = InMemoryApprovalScopeStore()
    scopes.put_boundary(case.boundary_v2)
    admissions = PostgresConfiguredPolicyAdmissionStore(dsn)
    source = _PolicySource(policy(case) if callable(policy) else policy)
    port = ConfiguredPolicyApprovalAdmissionPortV2(
        changeset_store=changesets,
        approval_scope_store=scopes,
        admission_store=admissions,
        accepted_input_reader=requests,
        policy_source=source,
        clock=_Clock(),
        id_factory=lambda: "ADM-TASK15-V2",
    )
    return case, accepted, requests, admissions, source, port


def test_v2_policy_issues_durable_admission_for_exact_accepted_host_set() -> None:
    """V2 stable policy + server-owned binding 才能签发 durable Gateway Admission。"""

    dsn = _dsn()
    _reset(dsn)
    case, accepted, requests, admissions, source, port = _owners(
        dsn,
        policy=lambda item: _policy(item),
    )
    try:
        admission = port.request_approval(
            StableRef(case.changeset.changeset_id, case.changeset.changeset_hash)
        )
        stored = admissions.get_v2(
            changeset_hash=case.changeset.changeset_hash,
            approved_scope_hash=case.boundary_v2.scope_hash,
        )

        assert accepted.request.task_id == case.changeset.task_id
        assert admission.changeset_hash == case.changeset.changeset_hash
        assert admission.approved_scope_hash == case.boundary_v2.scope_hash
        assert stored is not None
        assert stored.admission == admission
        assert stored.policy_version == "DSP_PRODUCT_APPROVAL_POLICY_V2"
        assert source.calls == 1
    finally:
        admissions.close()
        requests.close()


def test_v1_policy_cannot_authorize_v2_accepted_input() -> None:
    """V1 policy 即使 project/op 相同，也不能成为 cross-Host V2 authority。"""

    dsn = _dsn()
    _reset(dsn)
    case = build_case(project_id=_PROJECT_ID)
    v1 = ConfiguredProductApprovalPolicy.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
            "policy_id": "task15-v1-policy",
            "principal": "local:legacy",
            "project_ids": [_PROJECT_ID],
            "allowed_canonical_operations": ["set_wall_thickness.v1"],
            "admission_ttl_seconds": 900,
        }
    )
    _, _, requests, admissions, _, port = _owners(dsn, policy=v1)
    try:
        with pytest.raises(
            ValueError,
            match="FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID",
        ):
            port.request_approval(
                StableRef(
                    case.changeset.changeset_id,
                    case.changeset.changeset_hash,
                )
            )
        assert admissions.get_v2(
            changeset_hash=case.changeset.changeset_hash,
            approved_scope_hash=case.boundary_v2.scope_hash,
        ) is None
    finally:
        admissions.close()
        requests.close()


def test_v2_policy_denies_topology_mismatch_before_durable_admission() -> None:
    """accepted binding 与 policy topology 不一致时默认拒绝，不发布半条 admission。"""

    dsn = _dsn()
    _reset(dsn)
    case, _, requests, admissions, _, port = _owners(
        dsn,
        policy=lambda item: _policy(item, topology_hash="f" * 64),
    )
    try:
        with pytest.raises(
            ValueError,
            match="FRONT_DOOR_APPROVAL_POLICY_DENIED",
        ):
            port.request_approval(
                StableRef(
                    case.changeset.changeset_id,
                    case.changeset.changeset_hash,
                )
            )
        assert admissions.get(
            changeset_hash=case.changeset.changeset_hash,
            approved_scope_hash=case.boundary_v2.scope_hash,
        ) is None
    finally:
        admissions.close()
        requests.close()
