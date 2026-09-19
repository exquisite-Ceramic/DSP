"""ADR-010 LangGraph runtime adapter 的 RED/GREEN 契约测试。

这些测试只观察 framework-neutral 的 WorkflowOrchestratorPort 行为。LangGraph 的 config、
Command、StateSnapshot 等类型都必须留在 adapter 内部，不能成为调用方需要理解的契约。
"""

from __future__ import annotations

from design_orchestrator.langgraph_runtime import (
    LangGraphWorkflowRuntime,
    _runtime_config,
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


def test_start_uses_task_id_as_langgraph_thread_and_returns_neutral_checkpoint() -> None:
    """Start 必须以 task_id 隔离 checkpoint，并停在第一个 proposal HITL interrupt。"""

    saver = _TrackingSaver()
    runtime = LangGraphWorkflowRuntime(services=_RuntimeServices(), checkpointer=saver)

    checkpoint = runtime.start(_request())

    assert isinstance(checkpoint, WorkflowCheckpointView)
    assert checkpoint.task_id == "task-runtime-1"
    assert checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert checkpoint.operation_ref == StableRef("operation-1", "b" * 64)
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
    """只有显式 HITL command 才能恢复 proposal interrupt，随后 owner 异步事实仍以 ref 表达。"""

    runtime = LangGraphWorkflowRuntime(
        services=_RuntimeServices(),
        checkpointer=InMemorySaver(),
    )
    runtime.start(_request())

    checkpoint = runtime.resume(
        "task-runtime-1",
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={"accepted": True},
        ),
    )

    assert isinstance(checkpoint, WorkflowCheckpointView)
    assert checkpoint.phase is WorkflowPhase.PARAMETER_BINDING
    assert checkpoint.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-1",
    )
    assert "langgraph" not in type(checkpoint).__module__.lower()


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
