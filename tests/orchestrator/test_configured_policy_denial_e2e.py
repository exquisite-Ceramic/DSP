"""Task 5：真实 workflow 在 configured-policy deny 路径上的 fail-closed acceptance。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from design_orchestrator.workflow_contracts import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
import design_product_front_door as front_door

from tests.orchestrator.test_real_owner_workflow_end_to_end import (
    _build_real_owner_case,
    _close_case,
    _dsn,
    _request,
    requires_postgres,
)


@dataclass(frozen=True, slots=True)
class _AdmissionClock:
    """为 configured-policy admission 提供稳定 UTC issuance 时间。"""

    def now(self) -> datetime:
        """返回 timezone-aware UTC datetime。"""

        return datetime.fromisoformat("2026-09-24T10:00:00+00:00")


class _MissingPolicySource:
    """模拟本地 policy material 缺失；缺失必须默认拒绝新 issuance。"""

    def load(self):
        """以稳定配置错误表示 policy 文件/配置不可用。"""

        raise ValueError(
            "FRONT_DOOR_APPROVAL_POLICY_CONFIG_INVALID: configured policy is missing"
        )


class _StaticPolicySource:
    """为 negative E2E 提供一个确定性的规范 policy snapshot。"""

    def __init__(self, policy) -> None:
        self._policy = policy

    def load(self):
        """返回 exact configured policy。"""

        return self._policy


def _policy_source(kind: str):
    """按场景构造 missing / project-denied / operation-denied policy source。"""

    if kind == "missing":
        return _MissingPolicySource()
    if kind == "project-denied":
        return _StaticPolicySource(
            front_door.ConfiguredProductApprovalPolicy.from_mapping(
                {
                    "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                    "policy_id": "wrong-project-policy",
                    "principal": "local:operator",
                    "project_ids": ["some-other-project"],
                    "allowed_canonical_operations": ["set_wall_thickness.v1"],
                    "admission_ttl_seconds": 900,
                }
            )
        )
    if kind == "operation-denied":
        return _StaticPolicySource(
            front_door.ConfiguredProductApprovalPolicy.from_mapping(
                {
                    "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                    "policy_id": "wrong-operation-policy",
                    "principal": "local:operator",
                    "project_ids": ["project-task9"],
                    "allowed_canonical_operations": ["some_other_operation.v1"],
                    "admission_ttl_seconds": 900,
                }
            )
        )
    raise AssertionError(f"unsupported policy test case: {kind}")


def _install_configured_policy_admission(case, *, kind: str):
    """测试内把真实 policy port 接到 case 已创建的同一组 ChangeSet/Scope owner stores。

    Task 6 负责 production reference composition 的显式 factory seam；这里仅为 Task 5
    negative acceptance 替换既有 test boundary，不把私有 reach-through 变成生产构造规则。
    """

    admission_store = front_door.PostgresConfiguredPolicyAdmissionStore(_dsn())
    admission_port = front_door.ConfiguredPolicyApprovalAdmissionPort(
        changeset_store=case.changeset_store,
        approval_scope_store=case.scope_store,
        admission_store=admission_store,
        policy_source=_policy_source(kind),
        clock=_AdmissionClock(),
        id_factory=lambda: f"ADM-DENY-{kind}",
    )
    # 这是测试夹具替换；production composition 不允许依赖该私有字段。
    adapter = case.runtime._services._external_owners
    adapter._approval_admission = admission_port
    return admission_store


@requires_postgres
@pytest.mark.parametrize(
    ("kind", "expected_policy_code"),
    [
        ("missing", "FRONT_DOOR_APPROVAL_POLICY_CONFIG_INVALID"),
        ("project-denied", "FRONT_DOOR_APPROVAL_POLICY_DENIED"),
        ("operation-denied", "FRONT_DOOR_APPROVAL_POLICY_DENIED"),
    ],
)
def test_operation_proposal_acceptance_cannot_bypass_configured_policy_denial(
    kind: str,
    expected_policy_code: str,
) -> None:
    """HITL 接受只允许解释继续；policy deny 前后都不能产生 approval/planning/grant/Host mutation。"""

    case = _build_real_owner_case(f"task5-policy-deny-{kind}")
    admission_store = _install_configured_policy_admission(case, kind=kind)
    try:
        proposal_wait = case.runtime.start(_request(case.task_id))
        assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal_wait.pending_interaction is not None

        freshness_wait = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                pause_id=proposal_wait.pending_interaction.pause_id,
            ),
        )
        assert freshness_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS
        assert freshness_wait.async_operation_ref is not None

        case.semantic_boundary.operation_ready = True
        with pytest.raises(WorkflowStateError) as exc_info:
            case.runtime.resume(
                case.task_id,
                WorkflowResumeCommand(
                    resume_kind="ASYNC_OPERATION_COMPLETED",
                    payload={"operation_id": "task9-reconstruction"},
                ),
            )

        assert exc_info.value.code == "WORKFLOW_SERVICE_FAILURE"
        assert exc_info.value.__cause__ is not None
        assert expected_policy_code in str(exc_info.value.__cause__)

        checkpoint = case.runtime.get_checkpoint(case.task_id)
        assert checkpoint is not None
        assert checkpoint.changeset_ref is not None
        assert checkpoint.approval_ref is None
        assert checkpoint.execution_plan_ref is None
        assert checkpoint.saga_id is None
        assert len(case.host_port.calls) == 0

        changeset = case.changeset_store.get(checkpoint.changeset_ref.ref_id)
        boundary = case.scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")
        assert admission_store.get(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        ) is None
    finally:
        admission_store.close()
        _close_case(case)
