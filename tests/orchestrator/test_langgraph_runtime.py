"""ADR-010 LangGraph runtime adapter 的 RED/GREEN 契约测试。

这些测试只观察 framework-neutral 的 WorkflowOrchestratorPort 行为。LangGraph 的 config、
Command、StateSnapshot 等类型都必须留在 adapter 内部，不能成为调用方需要理解的契约。
"""

from __future__ import annotations

from design_orchestrator.hitl_resume import synthetic_legacy_operation_proposal_pause
from design_orchestrator.langgraph_runtime import (
    LangGraphWorkflowRuntime,
    _checkpoint_lookup_config,
    _runtime_config,
)
from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_async_ref,
    _decode_stable_ref,
    _encode_async_ref,
    _encode_stable_ref,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    WorkflowStateError,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class _TrackingSaver(InMemorySaver):
    """记录 LangGraph 写 checkpoint 时实际收到的 runtime-private config。"""

    def __init__(self) -> None:
        super().__init__()
        self.put_configs: list[dict[str, object]] = []

    def put(self, *args, **kwargs):
        """透传 InMemorySaver.put，同时保存第一参数 config 供隔离测试检查。"""

        config = args[0] if args else kwargs["config"]
        self.put_configs.append(config)
        return super().put(*args, **kwargs)


class _RuntimeServices:
    """把 workflow 推进到 proposal interrupt，再在参数绑定处制造 owner 异步等待。"""

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(f"snapshot-{task_id}", "a" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        return StableRef("operation-1", "b" * 64)

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-1",
        )

    def ensure_operation_freshness(self, operation_ref: StableRef) -> StableRef:
        return operation_ref

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        return StableRef("impact-1", "c" * 64)

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        return StableRef("changeset-1", "d" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("preview-1", "e" * 64)

    def request_approval(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("approval-1", "f" * 64)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        return StableRef("plan-1", "1" * 64)

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        return None

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("binding-1", "2" * 64)

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("grant-1", "3" * 64)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str:
        return "saga-1"

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


class _FailingServices(_RuntimeServices):
    """用于证明 service 异常会被稳定错误码归一化，而不是泄漏 framework 异常。"""

    def resolve_host_context(self, task_id: str) -> StableRef:
        raise LookupError(f"owner lookup failed for {task_id}")


def _request(task_id: str = "task-runtime-1") -> WorkflowStartRequest:
    """构造最小 framework-neutral workflow start request。"""

    return WorkflowStartRequest(
        task_id=task_id,
        request_data={"intent": "thicken wall"},
        initial_host_ref=StableRef("host-1", "4" * 64),
        initial_context_ref=None,
    )


def _build_legacy_operation_proposal_graph(checkpointer):
    """按历史 production shape 构造未版本化 Operation Proposal interrupt graph。

    该 fixture 精确复制 pre-Task-6 的旧节点名和 interrupt payload；它故意不经过当前
    ``prepare_operation_proposal_pause``，从而证明 migration 读取的是真实旧 checkpoint，
    而不是由新 topology 人工 seed 出来的近似状态。
    """

    builder = StateGraph(WorkflowGraphState)

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        """复制旧 await node：只有 operation_ref，没有 version/pending identity。"""

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


def _build_legacy_async_operation_graph(checkpointer):
    """按历史 production shape 构造未版本化 external-owner async interrupt graph。"""

    builder = StateGraph(WorkflowGraphState)

    def await_async_operation(state: WorkflowGraphState) -> dict[str, object]:
        """复制旧 async node；恢复值只表示允许重新查询 owner。"""

        ref = _decode_async_ref(state["async_operation_ref"], "async_operation_ref")
        assert ref is not None
        interrupt(
            {
                "kind": "ASYNC_OPERATION",
                "operation_ref": _encode_async_ref(ref),
            }
        )
        return {"async_operation_ref": None}

    builder.add_node("await_async_operation", await_async_operation)
    builder.add_edge(START, "await_async_operation")
    builder.add_edge("await_async_operation", END)
    return builder.compile(checkpointer=checkpointer)


def test_start_uses_task_id_as_langgraph_thread_and_returns_neutral_checkpoint() -> None:
    """Start 必须以 task_id 隔离 checkpoint，并停在第一个 proposal HITL interrupt。"""

    saver = _TrackingSaver()
    runtime = LangGraphWorkflowRuntime(services=_RuntimeServices(), checkpointer=saver)

    checkpoint = runtime.start(_request())

    assert isinstance(checkpoint, WorkflowCheckpointView)
    assert checkpoint.task_id == "task-runtime-1"
    assert checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert checkpoint.operation_ref == StableRef("operation-1", "b" * 64)
    assert checkpoint.pending_interaction is not None
    assert checkpoint.pending_interaction.subject_ref == checkpoint.operation_ref
    assert runtime.get_checkpoint("task-runtime-1") == checkpoint
    assert runtime.get_checkpoint("another-task") is None

    # 新 workflow 从第一次 graph invocation 起就必须是 v2，不能等到 human resume 时再补版本。
    snapshot = runtime._load_snapshot("task-runtime-1")
    assert snapshot is not None
    assert snapshot.values["checkpoint_contract_version"] == 2

    # ADR-010 的应用级 invoke config 保持固定 namespace；它不会暴露到公共 port。
    assert _runtime_config("task-runtime-1") == {
        "configurable": {
            "thread_id": "task-runtime-1",
            "checkpoint_ns": "dsp.workflow.v0_6",
        }
    }

    configurable_rows = [
        config["configurable"]
        for config in saver.put_configs
        if isinstance(config, dict) and isinstance(config.get("configurable"), dict)
    ]
    assert configurable_rows
    assert all(row["thread_id"] == "task-runtime-1" for row in configurable_rows)
    # LangGraph root graph 会把非空 checkpoint_ns 归一化为空；非空 namespace 留给 subgraph。
    assert all(row["checkpoint_ns"] == "" for row in configurable_rows)


def test_explicit_hitl_resume_uses_private_command_and_reaches_async_owner_wait() -> None:
    """显式 HITL command 必须携带当前 pause_id；恢复后 owner 异步事实仍只以 ref 表达。"""

    runtime = LangGraphWorkflowRuntime(
        services=_RuntimeServices(),
        checkpointer=InMemorySaver(),
    )
    start_checkpoint = runtime.start(_request())
    assert start_checkpoint.pending_interaction is not None

    checkpoint = runtime.resume(
        "task-runtime-1",
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=start_checkpoint.pending_interaction.pause_id,
        ),
    )

    assert isinstance(checkpoint, WorkflowCheckpointView)
    assert checkpoint.phase is WorkflowPhase.PARAMETER_BINDING
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-1",
    )
    assert "langgraph" not in type(checkpoint).__module__.lower()


def test_real_legacy_operation_proposal_interrupt_projects_synthetic_pause() -> None:
    """新 runtime 必须从真实旧 interrupt 合成 deterministic human pause，而不是猜 phase。"""

    task_id = "task-legacy-human"
    saver = InMemorySaver()
    legacy_graph = _build_legacy_operation_proposal_graph(saver)
    operation_ref = StableRef("legacy-operation", "b" * 64)
    legacy_graph.invoke(
        {
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "context_snapshot_ref": _encode_stable_ref(
                StableRef("legacy-snapshot", "a" * 64)
            ),
            "operation_ref": _encode_stable_ref(operation_ref),
        },
        _runtime_config(task_id),
    )

    # 旧 root checkpoint 实际写在 checkpoint_ns=""；应用级 namespace 仅用于 invoke config。
    # 这里显式使用 runtime 自己的 root lookup helper，确保 fixture 验证的是同一持久化坐标。
    legacy_snapshot = legacy_graph.get_state(_checkpoint_lookup_config(task_id))
    assert legacy_snapshot.values.get("checkpoint_contract_version") is None
    assert legacy_snapshot.values.get("pending_interaction") is None
    assert len(legacy_snapshot.interrupts) == 1
    assert legacy_snapshot.interrupts[0].value == {
        "kind": "OPERATION_PROPOSAL",
        "operation_ref": _encode_stable_ref(operation_ref),
    }

    runtime = LangGraphWorkflowRuntime(services=_RuntimeServices(), checkpointer=saver)
    checkpoint = runtime.get_checkpoint(task_id)

    assert checkpoint is not None
    assert checkpoint.pending_interaction == synthetic_legacy_operation_proposal_pause(
        task_id=task_id,
        operation_ref=operation_ref,
    )
    assert checkpoint.async_operation_ref is None


def test_real_legacy_async_interrupt_remains_external_owner_wait() -> None:
    """旧 async interrupt 仍是 owner wait，不能因为存在 interrupt 就被误判成人工 HITL pause。"""

    task_id = "task-legacy-async"
    saver = InMemorySaver()
    legacy_graph = _build_legacy_async_operation_graph(saver)
    async_ref = AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-legacy",
    )
    legacy_graph.invoke(
        {
            "task_id": task_id,
            "phase": WorkflowPhase.ENSURE_CONTEXT_FRESHNESS.value,
            "async_operation_ref": _encode_async_ref(async_ref),
            "resume_node": "ensure_context_freshness",
        },
        _runtime_config(task_id),
    )

    # 与 human fixture 一样，直接按 root checkpoint 坐标读取旧 graph 的真实 interrupt。
    legacy_snapshot = legacy_graph.get_state(_checkpoint_lookup_config(task_id))
    assert legacy_snapshot.values.get("checkpoint_contract_version") is None
    assert len(legacy_snapshot.interrupts) == 1
    assert legacy_snapshot.interrupts[0].value == {
        "kind": "ASYNC_OPERATION",
        "operation_ref": _encode_async_ref(async_ref),
    }

    runtime = LangGraphWorkflowRuntime(services=_RuntimeServices(), checkpointer=saver)
    checkpoint = runtime.get_checkpoint(task_id)

    assert checkpoint is not None
    assert checkpoint.phase is WorkflowPhase.ENSURE_CONTEXT_FRESHNESS
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref == async_ref


def test_resume_missing_task_uses_stable_workflow_error_code() -> None:
    """不存在的 task 不能把 LangGraph checkpoint 异常直接暴露给调用方。"""

    runtime = LangGraphWorkflowRuntime(
        services=_RuntimeServices(),
        checkpointer=InMemorySaver(),
    )

    try:
        runtime.resume("missing-task")
    except WorkflowStateError as exc:
        assert exc.code == "WORKFLOW_NOT_FOUND"
        assert "langgraph" not in str(exc).lower()
    else:
        raise AssertionError("missing task resume must fail closed")


def test_service_failure_is_normalized_and_keeps_original_cause() -> None:
    """Owner/service 故障必须映射为稳定错误码，同时保留原始 cause 供诊断。"""

    runtime = LangGraphWorkflowRuntime(
        services=_FailingServices(),
        checkpointer=InMemorySaver(),
    )

    try:
        runtime.start(_request("task-failure"))
    except WorkflowStateError as exc:
        assert exc.code == "WORKFLOW_SERVICE_FAILURE"
        assert isinstance(exc.__cause__, LookupError)
        assert "langgraph" not in str(exc).lower()
    else:
        raise AssertionError("service failure must be normalized")
