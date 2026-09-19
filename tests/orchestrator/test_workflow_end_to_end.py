"""ADR-010 Task 9：端到端证明 HITL、异步等待、重启与 execution-owner 分离。

PostgreSQL 用例使用真实 LangGraph runtime、真实 OperationResolver、真实 ParameterBinder，
只把尚未接入本仓库的外部 authoritative owners 替换为可观察 fake。测试关注的是 owner 边界、
稳定引用和 crash/restart 行为，不在 fake 中复制任何 Saga、Gateway 或 Host dispatch 状态机。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import pytest
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
    HostDispatchRecoveryView,
)

ROOT = Path(__file__).resolve().parents[2]
_OWNER_SCHEMA = "orchestrator_checkpoint"
_DSN = os.getenv("DSP_TEST_POSTGRES_DSN")
_SLICE_HASH = "a" * 64

requires_postgres = pytest.mark.skipif(
    not _DSN,
    reason="DSP_TEST_POSTGRES_DSN is required",
)


@dataclass(frozen=True, slots=True)
class _Profile:
    """与 MOVE_V1 canonical contract 对齐的最小 provider capability。"""

    provider_server: str = "autocad.local"
    provider_tool: str = "cad.move"
    canonical_operation: str = "move.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PLACEMENT", "GEOMETRY")
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "handles": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["handles", "dx", "dy"],
        }
    )
    output_schema: dict[str, Any] | None = None


class _MemoryArtifactStore:
    """保存 workflow-local deterministic artifacts；checkpoint 只能保存其 StableRef。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        """以稳定编号保存 artifact，并返回由 service 计算的内容摘要引用。"""

        ref_id = f"task9-artifact-{len(self.values) + 1}"
        self.values[ref_id] = value
        return StableRef(ref_id=ref_id, content_hash=content_hash)

    def get(self, ref: StableRef) -> object:
        """只允许 DefaultWorkflowServices 在 deterministic adapter 内取回 artifact。"""

        return self.values[ref.ref_id]


class _ScenarioOwners:
    """Task 9 的外部 owner fake，只返回稳定 read model/ref 并记录跨边界调用。"""

    def __init__(
        self,
        *,
        operation_ready: bool = False,
        execution_status: str = "SUCCEEDED",
        recovery_state: HostDispatchRecoveryState | None = None,
    ) -> None:
        self.operation_ready = operation_ready
        self.execution_status = execution_status
        self.recovery_state = recovery_state
        self.begin_count = 0
        self.verify_count = 0
        self.execution_refreshes: list[str] = []
        self.dispatch_intent_ids: list[str] = []

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        """给真实 resolver 提供 snapshot-bound provider/context read model。"""

        return OperationResolutionInputs(
            profiles=(_Profile(),),
            context=ResolutionContext(
                host_provider_servers=frozenset({"autocad.local"}),
                semantic_context=SemanticEligibilityContext(
                    context_snapshot_id="CS-task9",
                    context_snapshot_hash="snapshot-task9",
                    document_ref="drawing-task9",
                    semantic_environment_ref="semantic-env@task9",
                    entities=(),
                ),
            ),
        )

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
    ) -> ParameterBindingInputs:
        """给真实 binder 提供用户 proposal 与同一 snapshot-bound binding context。"""

        return ParameterBindingInputs(
            proposal=OperationProposal(
                "move.v1",
                {"displacement": [300, 0, 0]},
            ),
            context=ParameterBindingContext(
                context_snapshot_id="CS-task9",
                context_snapshot_hash="snapshot-task9",
                document_ref="drawing-task9",
                semantic_environment_ref="semantic-env@task9",
                selection=("S-001", "S-002"),
            ),
        )

    def resolve_host_context(self, task_id: str) -> StableRef:
        """模拟 Host/context owner 返回稳定 ContextSnapshot 引用。"""

        return StableRef(f"snapshot-{task_id}", "1" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        """本场景上下文已经 fresh，因此原样返回稳定引用。"""

        return snapshot_ref

    def ensure_operation_freshness(
        self,
        operation_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        """首次进入时返回 reconstruction wait；owner 完成后重新查询才返回 fresh ref。"""

        if not self.operation_ready:
            return AsyncOperationRef(
                kind=AsyncOperationKind.RECONSTRUCTION_JOB,
                owner="semantic-runtime",
                operation_id="reconstruction-task9",
            )
        return operation_ref

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        """Impact owner 只向 workflow 暴露稳定引用。"""

        return StableRef("impact-task9", "2" * 64)

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        """ChangeSet owner 保留完整对象，只返回 canonical ref。"""

        return StableRef("changeset-task9", "3" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        """Preview owner 返回独立稳定引用。"""

        return StableRef("preview-task9", "4" * 64)

    def request_approval(self, changeset_ref: StableRef) -> StableRef:
        """Approval owner 返回 ApprovalRecord 引用而不是完整记录。"""

        return StableRef("approval-task9", "5" * 64)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        """Execution planning owner 返回计划引用。"""

        return StableRef("plan-task9", "6" * 64)

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        """Revision barrier 在 authoritative owner 内完成，本场景允许继续。"""

        return None

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        """Late ProviderBinding 仍由原 owner 完成。"""

        return StableRef("provider-binding-task9", "7" * 64)

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        """Gateway owner 返回 ExecutionGrant 引用。"""

        return StableRef("grant-task9", "8" * 64)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str:
        """记录唯一 execution start；测试据此检测 crash/restart 后的重复 dispatch。"""

        self.begin_count += 1
        return "saga-task9"

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        """组合 Saga truth 与独立 dispatch-recovery truth，供 workflow 每次恢复时重查。"""

        self.execution_refreshes.append(saga_id)
        recovery = None
        if self.recovery_state is not None:
            recovery = HostDispatchRecoveryView(
                dispatch_intent_id="dispatch-intent-task9",
                execution_slice_hash=_SLICE_HASH,
                state=self.recovery_state,
            )
            self.dispatch_intent_ids.append(recovery.dispatch_intent_id)
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=len(self.execution_refreshes),
                status=self.execution_status,
                active_slice_hash=_SLICE_HASH,
            ),
            active_dispatch_recovery=recovery,
        )

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        """Reconciliation owner 完成收口；workflow 不解释其内部 ActualDelta。"""

        self.verify_count += 1
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=max(1, len(self.execution_refreshes) + 1),
                status="SUCCEEDED",
                active_slice_hash=_SLICE_HASH,
            )
        )


def _service(
    owners: _ScenarioOwners,
    *,
    store: _MemoryArtifactStore | None = None,
) -> DefaultWorkflowServices:
    """用真实 resolver/binder 和 fake external owners 组装生产 DefaultWorkflowServices。"""

    return DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=store or _MemoryArtifactStore(),
        external_owners=owners,
    )


def _dsn() -> str:
    """返回真实 PostgreSQL DSN；带该 helper 的用例都受 requires_postgres 保护。"""

    assert _DSN is not None
    return _DSN


def _reset_owner_schema() -> None:
    """每个 PostgreSQL acceptance case 都从空 owner schema 开始。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {_OWNER_SCHEMA} CASCADE")


def _request(task_id: str) -> WorkflowStartRequest:
    """构造只含 workflow-local request data 与稳定 Host ref 的启动请求。"""

    return WorkflowStartRequest(
        task_id=task_id,
        request_data={"intent": "move selected elements by 300 mm"},
        initial_host_ref=StableRef("host-task9", "9" * 64),
        initial_context_ref=None,
    )


def _all_mapping_keys(value: object) -> set[str]:
    """递归收集 checkpoint payload 的 mapping keys，用于禁止 authoritative object payload。"""

    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_all_mapping_keys(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            keys.update(_all_mapping_keys(item))
    return keys


def _all_type_names(value: object) -> set[str]:
    """递归收集实际反序列化类型，确保 saver 没有藏入 authoritative domain object。"""

    names = {type(value).__name__}
    if isinstance(value, Mapping):
        for item in value.values():
            names.update(_all_type_names(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            names.update(_all_type_names(item))
    return names


def test_task9_ci_executes_end_to_end_postgres_gate() -> None:
    """Task 9 acceptance 必须进入 postgres:17 gate，不能只靠本地可跳过的测试存在。"""

    workflow = (
        ROOT / ".github" / "workflows" / "workflow-orchestrator.yml"
    ).read_text(encoding="utf-8")

    assert "postgres:17" in workflow
    assert "DSP_TEST_POSTGRES_DSN" in workflow
    assert "tests/orchestrator/test_workflow_end_to_end.py" in workflow


def test_recovery_runbook_freezes_owner_boundaries_and_operator_procedure() -> None:
    """恢复手册必须明确三个 truth owner 以及禁止手改 checkpoint 的操作边界。"""

    runbook_path = ROOT / "docs" / "runbooks" / "workflow-orchestrator-recovery.md"
    assert runbook_path.is_file()
    runbook = runbook_path.read_text(encoding="utf-8")

    required_terms = (
        "Workflow checkpoint",
        "Execution Saga",
        "Host dispatch recovery",
        "ExecutionOwnerView",
        "OUTCOME_UNKNOWN",
        "orchestrator_checkpoint",
        "AsyncOperationRef",
        "Temporal",
        "禁止手工修改",
    )
    for term in required_terms:
        assert term in runbook


@requires_postgres
def test_real_runtime_survives_hitl_async_restart_and_keeps_refs_only() -> None:
    """真实 runtime 跨 PostgreSQL 重启后继续同一 HITL/async workflow，并最终只持久化稳定引用。"""

    _reset_owner_schema()
    task_id = "task9-e2e-main"
    owners_a = _ScenarioOwners(operation_ready=False)
    saver_a = create_postgres_checkpointer(_dsn())
    runtime_a = LangGraphWorkflowRuntime(
        services=_service(owners_a),
        checkpointer=saver_a,
    )

    proposal_wait = runtime_a.start(_request(task_id))
    assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert proposal_wait.operation_ref is not None
    assert proposal_wait.pending_interaction is not None

    # proposal ACCEPT 必须与当前持久化 human pause 精确相关；不再使用旧的隐式 accepted payload。
    async_wait = runtime_a.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=proposal_wait.pending_interaction.pause_id,
        ),
    )
    assert async_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS
    assert async_wait.pending_interaction is None
    assert async_wait.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-task9",
    )
    saver_a.close()

    # 模拟进程重建：新的 runtime、checkpointer、service 和 artifact store 不复用旧进程对象。
    owners_b = _ScenarioOwners(operation_ready=True)
    saver_b = create_postgres_checkpointer(_dsn())
    try:
        runtime_b = LangGraphWorkflowRuntime(
            services=_service(owners_b),
            checkpointer=saver_b,
        )
        reopened = runtime_b.get_checkpoint(task_id)
        assert reopened == async_wait

        completed = runtime_b.resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={"operation_id": "reconstruction-task9"},
            ),
        )
        assert completed.phase is WorkflowPhase.COMPLETED
        assert completed.changeset_ref == StableRef("changeset-task9", "3" * 64)
        assert completed.approval_ref == StableRef("approval-task9", "5" * 64)
        assert completed.execution_plan_ref == StableRef("plan-task9", "6" * 64)
        assert completed.saga_id == "saga-task9"
        assert owners_b.begin_count == 1
        assert owners_b.verify_count == 1

        # 只通过 LangGraph saver 的支持 API 检查实际反序列化 checkpoint，不直读表内部格式。
        checkpoint_tuple = saver_b.get_tuple(
            {
                "configurable": {
                    "thread_id": task_id,
                    "checkpoint_ns": "",
                }
            }
        )
        assert checkpoint_tuple is not None
        payload = checkpoint_tuple.checkpoint
        forbidden_types = {
            "CanonicalChangeSet",
            "ApprovalRecord",
            "StoredExecutionSagaV2",
            "HostDispatchIntent",
            "ActualDelta",
            "SemanticProjection",
        }
        forbidden_keys = {
            "canonical_changeset",
            "approval_record",
            "stored_execution_saga_v2",
            "host_dispatch_intent",
            "actual_delta",
            "semantic_projection",
        }
        assert _all_type_names(payload).isdisjoint(forbidden_types)
        assert {key.lower() for key in _all_mapping_keys(payload)}.isdisjoint(
            forbidden_keys
        )
    finally:
        saver_b.close()


@requires_postgres
@pytest.mark.parametrize(
    ("status", "recovery_state", "expected_phase"),
    (
        ("SUCCEEDED", None, WorkflowPhase.COMPLETED),
        ("EXECUTING", None, WorkflowPhase.APPLY_WAIT),
        (
            "EXECUTING",
            HostDispatchRecoveryState.OUTCOME_UNKNOWN,
            WorkflowPhase.APPLY_WAIT,
        ),
    ),
)
def test_restart_with_existing_saga_refreshes_owner_without_second_execution(
    status: str,
    recovery_state: HostDispatchRecoveryState | None,
    expected_phase: WorkflowPhase,
) -> None:
    """Saga 已存在时，重启只能 refresh/reconcile/wait，绝不能凭 checkpoint 位置再次开始执行。"""

    _reset_owner_schema()
    task_id = f"task9-existing-saga-{status.lower()}-{recovery_state or 'none'}"
    owners = _ScenarioOwners(
        operation_ready=True,
        execution_status=status,
        recovery_state=recovery_state,
    )
    service = _service(owners)
    plan_ref = StableRef("plan-task9", "6" * 64)
    grant_ref = StableRef("grant-task9", "8" * 64)

    # 先让 execution owner 生成唯一 Saga identity，再模拟调用方尚未观察完成即发生进程边界。
    saga_id = owners.begin_execution(plan_ref, grant_ref)
    assert owners.begin_count == 1

    saver_a = create_postgres_checkpointer(_dsn())
    graph_a = build_workflow_graph(service).compile(checkpointer=saver_a)
    graph_a.update_state(
        {
            "configurable": {
                "thread_id": task_id,
                # LangGraph update_state 在人工 seed 根 checkpoint 时必须使用根 namespace；
                # 生产 runtime 会自行把稳定 workflow namespace 归一化到同一根 checkpoint。
                "checkpoint_ns": "",
            }
        },
        {
            "task_id": task_id,
            "phase": WorkflowPhase.APPLY_WAIT.value,
            "changeset_ref": {
                "ref_id": "changeset-task9",
                "content_hash": "3" * 64,
            },
            "approval_ref": {
                "ref_id": "approval-task9",
                "content_hash": "5" * 64,
            },
            "execution_plan_ref": {
                "ref_id": plan_ref.ref_id,
                "content_hash": plan_ref.content_hash,
            },
            "grant_ref": {
                "ref_id": grant_ref.ref_id,
                "content_hash": grant_ref.content_hash,
            },
            "saga_id": saga_id,
        },
        as_node="execution_grant",
    )
    saver_a.close()

    saver_b = create_postgres_checkpointer(_dsn())
    try:
        runtime_b = LangGraphWorkflowRuntime(
            services=service,
            checkpointer=saver_b,
        )
        resumed = runtime_b.resume(task_id)

        assert resumed.phase is expected_phase
        assert owners.begin_count == 1
        assert owners.execution_refreshes == [saga_id]

        if expected_phase is WorkflowPhase.APPLY_WAIT:
            assert resumed.async_operation_ref == AsyncOperationRef(
                kind=AsyncOperationKind.EXECUTION_JOB,
                owner="execution",
                operation_id=saga_id,
            )
        else:
            assert owners.verify_count == 1

        if recovery_state is HostDispatchRecoveryState.OUTCOME_UNKNOWN:
            # 重复唤醒只能重查同一 dispatch recovery identity，不能制造第二次 execution start。
            still_waiting = runtime_b.resume(
                task_id,
                WorkflowResumeCommand(
                    resume_kind="EXECUTION_OWNER_WAKE",
                    payload={"dispatch_intent_id": "dispatch-intent-task9"},
                ),
            )
            assert still_waiting.phase is WorkflowPhase.APPLY_WAIT
            assert owners.begin_count == 1
            assert owners.execution_refreshes == [saga_id, saga_id]
            assert owners.dispatch_intent_ids == [
                "dispatch-intent-task9",
                "dispatch-intent-task9",
            ]
    finally:
        saver_b.close()