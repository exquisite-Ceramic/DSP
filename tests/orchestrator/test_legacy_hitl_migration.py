"""Task 7 Step 6：精确 legacy human pause 的迁移与恢复顺序契约。

这些测试只覆盖 legacy Operation Proposal checkpoint 的迁移，不提前冻结 Step 7 的 v2
artifact-unavailable 错误归一化。核心不变量是：先校验 correlated command，再恢复 artifact；
恢复成功后必须以同一个 synthetic pause_id 写成 v2 并重新建立真实 human interrupt，最后才
允许消费原 command。任何恢复失败都不能破坏旧 checkpoint。
"""

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
    OperationArtifactResolution,
    WorkflowStateError,
)

# Step36 的轻量 lane 不安装 LangGraph。本文件验证 runtime-private migration，因此先做模块级
# optional-dependency gate；完整 Repository regression 安装 LangGraph 后会执行全部断言。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for legacy HITL migration tests",
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
    """只记录 Step 6 允许触达的 artifact recovery 与 binder 边界。"""

    def __init__(
        self,
        *,
        resolution: OperationArtifactResolution,
        failure: Exception | None = None,
    ) -> None:
        self.resolution = resolution
        self.failure = failure
        self.artifact_calls: list[tuple[StableRef, StableRef, bool]] = []
        self.bound_operation_refs: list[StableRef] = []

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """记录 legacy recovery 参数，并按测试场景返回 durable ref 或模拟不可用。"""

        self.artifact_calls.append(
            (operation_ref, context_snapshot_ref, allow_legacy_rehydrate)
        )
        if self.failure is not None:
            raise self.failure
        return self.resolution

    def bind_parameters(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> AsyncOperationRef:
        """证明迁移后 binder 同时收到新 durable operation ref 与 saver 恢复的 exact context ref。"""

        assert self.artifact_calls
        assert context_snapshot_ref == self.artifact_calls[-1][1]
        self.bound_operation_refs.append(operation_ref)
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-after-legacy-migration",
        )

    def __getattr__(self, name: str):
        """任何超出 Step 6 边界的 service 调用都说明 graph 意外前进。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


def _build_legacy_operation_proposal_graph(checkpointer: InMemorySaver):
    """复制 pre-v2 历史 await node，真实产生未版本化 Operation Proposal interrupt。"""

    builder = StateGraph(WorkflowGraphState)

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        """旧节点只持有 operation_ref，不存在 checkpoint version 与 pending identity。"""

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


def _seed_legacy_human(
    services: _MigrationServices,
    *,
    task_id: str,
) -> tuple[
    object,
    StableRef,
    StableRef,
]:
    """用真实旧 graph 写 checkpoint，再让当前 runtime 打开同一个 saver。"""

    saver = InMemorySaver()
    legacy_graph = _build_legacy_operation_proposal_graph(saver)
    context_ref = StableRef("legacy-context", "a" * 64)
    operation_ref = StableRef("legacy-operation", "b" * 64)
    legacy_graph.invoke(
        {
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "context_snapshot_ref": _encode_stable_ref(context_ref),
            "operation_ref": _encode_stable_ref(operation_ref),
        },
        _runtime_config(task_id),
    )
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)
    return runtime, context_ref, operation_ref


def _accepted(pause_id: str) -> WorkflowResumeCommand:
    """构造与当前 synthetic human pause 精确相关的 ACCEPT command。"""

    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        payload={},
        pause_id=pause_id,
    )


def test_legacy_human_resume_validates_command_before_artifact_recovery() -> None:
    """Stale pause_id 必须在 artifact recovery 前失败，旧 checkpoint 不能被迁移。"""

    task_id = "task-legacy-stale-before-recovery"
    durable_ref = StableRef("durable-operation", "c" * 64)
    services = _MigrationServices(
        resolution=OperationArtifactResolution(durable_ref, "rehydrated")
    )
    runtime, _, _ = _seed_legacy_human(services, task_id=task_id)
    before = runtime.get_checkpoint(task_id)
    assert before is not None and before.pending_interaction is not None

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
    snapshot = runtime._load_snapshot(task_id)
    assert snapshot is not None
    assert snapshot.values.get("checkpoint_contract_version") is None
    assert snapshot.values.get("pending_interaction") is None
    assert runtime.get_checkpoint(task_id) == before


def test_legacy_human_resume_migrates_same_pause_then_consumes_command() -> None:
    """成功恢复必须先建立同 identity 的 v2 interrupt，再把 command 交给当前 graph。"""

    task_id = "task-legacy-migrate-success"
    durable_ref = StableRef("durable-operation", "c" * 64)
    services = _MigrationServices(
        resolution=OperationArtifactResolution(durable_ref, "rehydrated")
    )
    runtime, context_ref, legacy_ref = _seed_legacy_human(services, task_id=task_id)
    legacy_checkpoint = runtime.get_checkpoint(task_id)
    assert legacy_checkpoint is not None
    assert legacy_checkpoint.pending_interaction is not None
    pause_id = legacy_checkpoint.pending_interaction.pause_id

    checkpoint = runtime.resume(task_id, _accepted(pause_id))

    assert services.artifact_calls == [(legacy_ref, context_ref, True)]
    assert services.bound_operation_refs == [durable_ref]
    assert checkpoint.phase is WorkflowPhase.PARAMETER_BINDING
    assert checkpoint.operation_ref == durable_ref
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-after-legacy-migration",
    )

    # 最终 command 已消费 pending，因此通过 history 证明 migration 中间态真实存在且没有换 ID。
    history = list(runtime._graph.get_state_history(_checkpoint_lookup_config(task_id)))
    migrated = []
    for snapshot in history:
        pending = snapshot.values.get("pending_interaction")
        if (
            snapshot.values.get("checkpoint_contract_version") == 2
            and isinstance(pending, dict)
            and pending.get("pause_id") == pause_id
        ):
            migrated.append(snapshot)

    assert migrated
    expected_interrupt = {
        "pause_id": pause_id,
        "kind": "OPERATION_PROPOSAL",
        "subject_ref": _encode_stable_ref(durable_ref),
    }
    assert any(
        len(snapshot.interrupts) == 1
        and snapshot.interrupts[0].value == expected_interrupt
        for snapshot in migrated
    )


def test_legacy_artifact_recovery_failure_preserves_original_pause() -> None:
    """Artifact recovery 失败必须发生在 update_state 前，旧 unversioned pause 保持可重试。"""

    task_id = "task-legacy-recovery-failure"
    durable_ref = StableRef("unused-durable-operation", "c" * 64)
    failure = WorkflowArtifactUnavailableError("legacy resolution cannot be recovered")
    services = _MigrationServices(
        resolution=OperationArtifactResolution(durable_ref, "rehydrated"),
        failure=failure,
    )
    runtime, context_ref, legacy_ref = _seed_legacy_human(services, task_id=task_id)
    before = runtime.get_checkpoint(task_id)
    assert before is not None and before.pending_interaction is not None
    pause_id = before.pending_interaction.pause_id
    snapshot_before = runtime._load_snapshot(task_id)
    assert snapshot_before is not None
    values_before = dict(snapshot_before.values)

    # Step 6 只冻结 side-effect ordering；异常的稳定公共错误码由 Step 7 单独冻结。
    with pytest.raises(Exception):
        runtime.resume(task_id, _accepted(pause_id))

    assert services.artifact_calls == [(legacy_ref, context_ref, True)]
    snapshot_after = runtime._load_snapshot(task_id)
    assert snapshot_after is not None
    assert dict(snapshot_after.values) == values_before
    assert snapshot_after.values.get("checkpoint_contract_version") is None
    assert snapshot_after.values.get("pending_interaction") is None
    assert runtime.get_checkpoint(task_id) == before
