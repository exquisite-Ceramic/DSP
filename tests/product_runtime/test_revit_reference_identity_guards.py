from __future__ import annotations

from datetime import datetime, timezone

import pytest
from design_orchestrator import WorkflowPhase
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_front_door import (
    ConfiguredPolicyApprovalAdmissionPort,
    ConfiguredProductApprovalPolicy,
    PostgresConfiguredPolicyAdmissionStore,
)
from design_product_runtime import (
    ProductTaskRequest,
    build_revit_wall_thickness_reference_composition,
)

from tests.product_runtime.conftest import StatefulRevitTransport
from tests.product_runtime.test_revit_reference_composition import (
    _accept,
    _real_config,
    _request,
)


class _MutableContextIdentityTransport(StatefulRevitTransport):
    """只允许测试改变 fresh context evidence；其余 Revit Host 行为保持既有 production fixture。"""

    def __init__(self) -> None:
        super().__init__()
        self.context_document_id = "DOC-TASK9"
        self.context_host_instance_id = "REVIT-TASK9"
        self.context_selected_unique_id = "REVIT-UNIQUE-ID-TASK9"

    def request(self, command):
        response = super().request(command)
        if command.operation != "context.current_selection":
            return response
        payload = dict(response["payload"])
        payload["document_id"] = self.context_document_id
        payload["host_instance_id"] = self.context_host_instance_id
        payload["selected_elements"] = [
            {
                "unique_id": self.context_selected_unique_id,
                "native_kind": "Wall",
            }
        ]
        return {**response, "payload": payload}


class _StaticPolicySource:
    """Step 5 继续使用真实 configured-policy admission，只固定测试 policy。"""

    def __init__(self, policy: ConfiguredProductApprovalPolicy) -> None:
        self._policy = policy

    def load(self) -> ConfiguredProductApprovalPolicy:
        return self._policy


class _PolicyClock:
    """为真实 configured-policy issuance 提供 timezone-aware UTC 时间。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UniqueConfiguredPolicyAdmissionFactory:
    """每个 identity-guard case 使用独立 admission id，避免 durable issuance 互相干扰。"""

    def __init__(self, dsn: str, *, admission_id: str) -> None:
        self._dsn = dsn
        self._admission_id = admission_id
        self._stores: list[PostgresConfiguredPolicyAdmissionStore] = []

    def build(self, *, changeset_store, approval_scope_store):
        admission_store = PostgresConfiguredPolicyAdmissionStore(self._dsn)
        self._stores.append(admission_store)
        policy = ConfiguredProductApprovalPolicy.from_mapping(
            {
                "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                "policy_id": "task6-reference-identity-policy",
                "principal": "user:task6-reference",
                "project_ids": ["project-task9"],
                "allowed_canonical_operations": ["set_wall_thickness.v1"],
                "admission_ttl_seconds": 3600,
            }
        )
        return ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=admission_store,
            policy_source=_StaticPolicySource(policy),
            clock=_PolicyClock(),
            id_factory=lambda: self._admission_id,
        )

    def close(self) -> None:
        """关闭本 case 创建的 durable admission store。"""

        for store in reversed(self._stores):
            store.close()


def _wrong_session_request(task_id: str) -> ProductTaskRequest:
    """构造与 production composition frozen session 不一致的 immutable request。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-task9",
        host_kind="REVIT",
        session_ref="revit-session-other",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def test_request_session_mismatch_fails_closed_before_host_mutation(
    product_task_postgres_dsn: str,
) -> None:
    """request session 与 frozen composition session 不一致时不得进入任何 Host mutation。"""

    host = _MutableContextIdentityTransport()
    approval_factory = _UniqueConfiguredPolicyAdmissionFactory(
        product_task_postgres_dsn,
        admission_id="ADM-TASK6-IDENTITY-SESSION",
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        with pytest.raises((ValueError, WorkflowStateError), match="session|SESSION"):
            composition.flow.submit(
                _wrong_session_request("task6-reference-identity-session")
            )

        assert host.execute_count == 0
        assert "set_wall_thickness" not in host.command_operations()
    finally:
        composition.close()
        approval_factory.close()


def test_runtime_drift_after_proposal_fails_closed_before_host_mutation(
    product_task_postgres_dsn: str,
) -> None:
    """proposal pause 后 Revit runtime identity 漂移，resume 必须 fresh-read 并拒绝。"""

    host = _MutableContextIdentityTransport()
    approval_factory = _UniqueConfiguredPolicyAdmissionFactory(
        product_task_postgres_dsn,
        admission_id="ADM-TASK6-IDENTITY-RUNTIME",
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        proposal = composition.flow.submit(_request("task6-reference-identity-runtime"))
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        host.context_host_instance_id = "REVIT-TASK6-DRIFTED"

        with pytest.raises((ValueError, WorkflowStateError), match="HOST|host|runtime"):
            composition.flow.resume(proposal.task_id, _accept(proposal))

        assert host.execute_count == 0
        assert "set_wall_thickness" not in host.command_operations()
    finally:
        composition.close()
        approval_factory.close()


def test_document_drift_after_proposal_fails_closed_before_host_mutation(
    product_task_postgres_dsn: str,
) -> None:
    """proposal pause 后 active document 漂移，resume 必须在 Gateway/Host mutation 前拒绝。"""

    host = _MutableContextIdentityTransport()
    approval_factory = _UniqueConfiguredPolicyAdmissionFactory(
        product_task_postgres_dsn,
        admission_id="ADM-TASK6-IDENTITY-DOCUMENT",
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        proposal = composition.flow.submit(_request("task6-reference-identity-document"))
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        host.context_document_id = "DOC-TASK6-DRIFTED"

        with pytest.raises((ValueError, WorkflowStateError), match="DOCUMENT|document"):
            composition.flow.resume(proposal.task_id, _accept(proposal))

        assert host.execute_count == 0
        assert "set_wall_thickness" not in host.command_operations()
    finally:
        composition.close()
        approval_factory.close()


def test_selected_target_drift_after_proposal_fails_closed_before_host_mutation(
    product_task_postgres_dsn: str,
) -> None:
    """proposal pause 后当前选择漂移到另一 Wall，也不得继续执行 frozen target mutation。"""

    host = _MutableContextIdentityTransport()
    approval_factory = _UniqueConfiguredPolicyAdmissionFactory(
        product_task_postgres_dsn,
        admission_id="ADM-TASK6-IDENTITY-TARGET",
    )
    composition = build_revit_wall_thickness_reference_composition(
        config=_real_config(product_task_postgres_dsn),
        transport=host,
        approval_admission_factory=approval_factory,
    )
    try:
        proposal = composition.flow.submit(_request("task6-reference-identity-target"))
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        host.context_selected_unique_id = "REVIT-UNIQUE-ID-OTHER-WALL"

        with pytest.raises((ValueError, WorkflowStateError), match="identity|target|selection|context"):
            composition.flow.resume(proposal.task_id, _accept(proposal))

        assert host.execute_count == 0
        assert "set_wall_thickness" not in host.command_operations()
    finally:
        composition.close()
        approval_factory.close()
