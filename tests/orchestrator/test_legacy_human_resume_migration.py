"""Task 7 Step 6：legacy human pause 迁移到 v2 durable pause 的 RED/GREEN 契约。"""

from __future__ import annotations

from importlib import import_module

import pytest

from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_stable_ref,
    _encode_stable_ref,
)
from design_orchestrator.workflow_artifacts import WorkflowArtifactUnavailableError
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    OperationArtifactResolution,
    WorkflowStateError,
)

# Step36 的轻量 orchestrator lane 不安装 LangGraph。本文件只验证 runtime-private migration，
# 因此必须在动态加载 runtime/graph 类型前做模块级 skip；完整 repository lane 仍会真实执行。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for legacy human resume migration tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
_checkpoint_lookup_config = _runtime_module._checkpoint_lookup_config
_runtime_config = _runtime_module._runtime_config
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver
_graph_module = import_module("langgraph.graph")
END = _graph_module.END
START = _graph_module.START
StateGraph = _graph_module.StateGraph
interrupt = import_module("langgraph.types").interrupt


class _MigrationServices:
    """记录 legacy artifact recovery 与 binder 输入，证明 migration 发生在命令消费之前。"""

    def __init__(self) -> None:
        self.artifact_calls: list[tuple[StableRef, StableRef, bool]] = []
        self.bind_calls: list[StableRef] = []
        self.migrated_ref = StableRef("migrated-operation", "c" * 64)

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """模拟 legacy hash 已验证并写入 durable artifact store 的成功恢复。"""

        self.artifact_calls.append(
            (operation_ref, context_snapshot_ref, allow_legacy_rehydrate)
        )
        return OperationArtifactResolution(ref=self.migrated_ref, source="rehydrated")

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        """记录 binder 真正消费的是 migration 后的 durable ref。"""

        self.bind_calls.append(operation_ref)
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="legacy-migration-binding",
        )

    # 下列方法只用于满足当前 graph 的 WorkflowServices 结构；本组测试在 async wait 前停止。
    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(f"snapshot-{task_id}", "1" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        return self.migrated_ref

    def ensure_operation_freshness(self, operation_ref: StableRef) -> StableRef:
        return operation_ref

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        return StableRef("impact", "2" * 64)

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        return StableRef("changeset", "3" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("preview", "4" * 64)

    def request_approval(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("approval", "5" * 64)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        return StableRef("plan", "6" * 64)

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        return None

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("binding", "7" * 64)

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("grant", "8" * 64)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str:
        return "saga-legacy-migration"

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=0,
                status="READY",
                active_slice_hash=None,
            )
        )

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=1,
                status="SUCCEEDED",
                active_slice_hash=None,
            )
        )


class _UnavailableMigrationServices(_MigrationServices):
    """模拟 legacy artifact 无法安全 rehydrate，并保留底层 owner/storage cause。"""

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        self.artifact_calls.append(
            (operation_ref, context_snapshot_ref, allow_legacy_rehydrate)
        )
        cause = LookupError("legacy operation artifact source is unavailable")
        try:
            raise cause
        except LookupError as exc:
            raise WorkflowArtifactUnavailableError(
                "legacy operation artifact cannot be reconstructed"
            ) from exc


def _build_legacy_operation_proposal_graph(checkpointer):
    """复制 pre-v2 的真实 await_operation_proposal 节点名和 interrupt payload。"""

    builder = StateGraph(WorkflowGraphState)

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        """旧节点只有 operation_ref，没有 checkpoint version/pending identity。"""

        operation_ref = _decode_stable_ref(state["operation_ref"], "operation_ref")
        assert operation_ref is not None
        interrupt(
            {
                "kind": "OPERATION_PROPOSAL",
                "operation_ref": _encode_stable_ref(operation_ref),
            }
        )
        return {"phase": WorkflowPhase.PARAMETER_BINDING.value}

    builder.add_node("await_operation_proposal", await_operation_proposal)
    builder.add_edge(START, "await_operation_proposal")
    builder.add_edge("await_operation_proposal", END)
    return builder.compile(checkpointer=checkpointer)


def _seed_legacy_human_pause(
    *,
    task_id: str,
    saver: InMemorySaver,
) -> tuple[StableRef, StableRef]:
    """写入一个真实 unversioned human interrupt，并返回其 snapshot/operation refs。"""

    context_snapshot_ref = StableRef("legacy-snapshot", "a" * 64)
    operation_ref = StableRef("legacy-operation", "b" * 64)
    legacy_graph = _build_legacy_operation_proposal_graph(saver)
    legacy_graph.invoke(
        {
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "context_snapshot_ref": _encode_stable_ref(context_snapshot_ref),
            "operation_ref": _encode_stable_ref(operation_ref),
        },
        _runtime_config(task_id),
    )
    return context_snapshot_ref, operation_ref


def test_stale_legacy_human_command_is_rejected_before_artifact_recovery() -> None:
    """pause_id 不匹配必须先报 STALE，不能读取或重建任何 artifact。"""

    task_id = "task-legacy-migration-stale"
    saver = InMemorySaver()
    _seed_legacy_human_pause(task_id=task_id, saver=saver)
    services = _MigrationServices()
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={},
                pause_id="legacy-op-proposal:stale",
            ),
        )

    assert captured.value.code == "WORKFLOW_RESUME_STALE"
    assert services.artifact_calls == []
    assert services.bind_calls == []


def test_exact_legacy_human_resume_migrates_to_v2_before_consuming_command() -> None:
    """精确 legacy ACCEPT 必须先持久化同 identity 的 v2 pause，再由 graph 消费命令。"""

    task_id = "task-legacy-migration-success"
    saver = InMemorySaver()
    context_snapshot_ref, operation_ref = _seed_legacy_human_pause(
        task_id=task_id,
        saver=saver,
    )
    services = _MigrationServices()
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)
    legacy_checkpoint = runtime.get_checkpoint(task_id)
    assert legacy_checkpoint is not None
    assert legacy_checkpoint.pending_interaction is not None
    synthetic_pause_id = legacy_checkpoint.pending_interaction.pause_id

    checkpoint = runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=synthetic_pause_id,
        ),
    )

    assert services.artifact_calls == [
        (operation_ref, context_snapshot_ref, True),
    ]
    assert services.bind_calls == [services.migrated_ref]
    assert checkpoint.operation_ref == services.migrated_ref
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="legacy-migration-binding",
    )

    # 最终 state 已从 legacy contract 升级为 v2；若 migration 生成了新的随机 pause_id，原命令
    # 无法通过 await_operation_proposal 的 defense-in-depth 校验，因此成功继续同时证明 identity 保持。
    migrated_snapshot = runtime._load_snapshot(task_id)
    assert migrated_snapshot is not None
    assert migrated_snapshot.values["checkpoint_contract_version"] == 2
    assert migrated_snapshot.values["operation_ref"] == _encode_stable_ref(
        services.migrated_ref
    )


def test_legacy_artifact_failure_preserves_original_pause_and_checkpoint() -> None:
    """artifact recovery 失败必须发生在 update_state 前，旧 pause 与 unversioned state 原样保留。"""

    task_id = "task-legacy-migration-unavailable"
    saver = InMemorySaver()
    context_snapshot_ref, operation_ref = _seed_legacy_human_pause(
        task_id=task_id,
        saver=saver,
    )
    services = _UnavailableMigrationServices()
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)
    before_checkpoint = runtime.get_checkpoint(task_id)
    assert before_checkpoint is not None
    assert before_checkpoint.pending_interaction is not None
    before_snapshot = runtime._load_snapshot(task_id)
    assert before_snapshot is not None
    before_values = dict(before_snapshot.values)
    before_interrupts = tuple(item.value for item in before_snapshot.interrupts)

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={},
                pause_id=before_checkpoint.pending_interaction.pause_id,
            ),
        )

    assert captured.value.code == "WORKFLOW_ARTIFACT_UNAVAILABLE"
    assert isinstance(captured.value.__cause__, WorkflowArtifactUnavailableError)
    assert isinstance(captured.value.__cause__.__cause__, LookupError)
    assert services.artifact_calls == [
        (operation_ref, context_snapshot_ref, True),
    ]
    assert services.bind_calls == []

    after_checkpoint = runtime.get_checkpoint(task_id)
    after_snapshot = runtime._load_snapshot(task_id)
    assert after_snapshot is not None
    assert after_checkpoint == before_checkpoint
    assert dict(after_snapshot.values) == before_values
    assert tuple(item.value for item in after_snapshot.interrupts) == before_interrupts
    assert after_snapshot.values.get("checkpoint_contract_version") is None
