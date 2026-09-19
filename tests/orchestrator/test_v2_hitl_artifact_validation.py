"""Task 7 Step 7：v2 human resume 的 durable artifact preflight 契约。

这些测试冻结三个边界：

1. v2 human command 在进入 LangGraph 前，必须以 ``allow_legacy_rehydrate=False`` 验证
   当前 pending subject 对应的 durable Operation Resolution artifact；
2. artifact unavailable 时必须稳定归一为 ``WORKFLOW_ARTIFACT_UNAVAILABLE``，保留原始 cause，
   并且 checkpoint 与 binder side effect 都保持不变；
3. external-owner async wait 的 poll 与显式 legacy async command 都不能因为存在 LangGraph
   interrupt 就误触 operation-artifact recovery。
"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_orchestrator.workflow_artifacts import WorkflowArtifactUnavailableError
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_services import (
    OperationArtifactResolution,
    WorkflowStateError,
)

# Step36 的轻量 orchestrator lane 不安装 LangGraph。本文件验证 runtime-private resume，
# 因此必须先做模块级 optional-dependency gate；完整 Repository regression 仍会真实执行。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for v2 HITL artifact validation tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver


class _V2ArtifactServices:
    """把 workflow 推到 human pause，并记录 artifact preflight 与 binder 的严格顺序。"""

    def __init__(self) -> None:
        self.context_ref = StableRef("context-v2", "a" * 64)
        self.operation_ref = StableRef("operation-v2", "b" * 64)
        self.calls: list[str] = []
        self.artifact_calls: list[tuple[StableRef, StableRef, bool]] = []
        self.bind_count = 0
        self.artifact_failure: Exception | None = None
        self.artifact_resolution = OperationArtifactResolution(
            ref=self.operation_ref,
            source="durable",
        )

    def resolve_host_context(self, task_id: str) -> StableRef:
        """返回固定 context ref，使 v2 pending 与 artifact preflight 输入可精确断言。"""

        return self.context_ref

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        """保持 context 不变，让测试只观察 human resume 边界。"""

        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        """返回固定 operation ref，并由当前 v2 graph 建立真实 correlated human pause。"""

        return self.operation_ref

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """记录 durable preflight；按场景返回命中结果或模拟底层 artifact 不可用。"""

        self.calls.append("ensure_operation_artifact")
        self.artifact_calls.append(
            (operation_ref, context_snapshot_ref, allow_legacy_rehydrate)
        )
        if self.artifact_failure is not None:
            raise self.artifact_failure
        return self.artifact_resolution

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        """记录 graph continuation；若 preflight 正确，它必须严格发生在 artifact 校验之后。"""

        self.calls.append("bind_parameters")
        self.bind_count += 1
        assert operation_ref == self.operation_ref
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-v2-artifact-validation",
        )

    def __getattr__(self, name: str):
        """任何超出 human/async 边界的 service 调用都说明测试意外前进。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


def _runtime(services: _V2ArtifactServices) -> LangGraphWorkflowRuntime:
    """创建独立 InMemorySaver runtime，确保每条测试拥有自己的 durable graph state。"""

    return LangGraphWorkflowRuntime(
        services=services,
        checkpointer=InMemorySaver(),
    )


def _request(task_id: str) -> WorkflowStartRequest:
    """构造最小 v2 start request。"""

    return WorkflowStartRequest(
        task_id=task_id,
        request_data={"intent": "validate durable operation artifact"},
        initial_host_ref=StableRef("host-v2", "c" * 64),
    )


def _accepted(pause_id: str) -> WorkflowResumeCommand:
    """构造与当前 v2 Operation Proposal pause 精确相关的 ACCEPT command。"""

    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        payload={},
        pause_id=pause_id,
    )


def test_v2_human_resume_validates_durable_artifact_before_graph_continuation() -> None:
    """v2 ACCEPT 必须先 durable-only preflight，再允许 binder/async continuation。"""

    task_id = "task-v2-artifact-success"
    services = _V2ArtifactServices()
    runtime = _runtime(services)
    paused = runtime.start(_request(task_id))
    assert paused.pending_interaction is not None
    services.calls.clear()

    checkpoint = runtime.resume(
        task_id,
        _accepted(paused.pending_interaction.pause_id),
    )

    assert services.artifact_calls == [
        (services.operation_ref, services.context_ref, False),
    ]
    assert services.calls[:2] == ["ensure_operation_artifact", "bind_parameters"]
    assert services.bind_count == 1
    assert checkpoint.pending_interaction is None
    assert checkpoint.operation_ref == services.operation_ref
    assert checkpoint.async_operation_ref == AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="interaction-v2-artifact-validation",
    )


def test_v2_artifact_unavailable_fails_before_graph_and_preserves_checkpoint() -> None:
    """Durable artifact 缺失必须保留 v2 human pause，并保留底层不可用 cause。"""

    task_id = "task-v2-artifact-unavailable"
    services = _V2ArtifactServices()
    runtime = _runtime(services)
    paused = runtime.start(_request(task_id))
    assert paused.pending_interaction is not None
    snapshot_before = runtime._load_snapshot(task_id)
    assert snapshot_before is not None
    values_before = dict(snapshot_before.values)
    interrupts_before = tuple(item.value for item in snapshot_before.interrupts)

    cause = LookupError("durable operation artifact is missing")
    try:
        raise cause
    except LookupError as exc:
        services.artifact_failure = WorkflowArtifactUnavailableError(
            "operation artifact is unavailable"
        )
        services.artifact_failure.__cause__ = exc

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(
            task_id,
            _accepted(paused.pending_interaction.pause_id),
        )

    assert captured.value.code == "WORKFLOW_ARTIFACT_UNAVAILABLE"
    assert isinstance(captured.value.__cause__, WorkflowArtifactUnavailableError)
    assert isinstance(captured.value.__cause__.__cause__, LookupError)
    assert services.artifact_calls == [
        (services.operation_ref, services.context_ref, False),
    ]
    assert services.bind_count == 0

    snapshot_after = runtime._load_snapshot(task_id)
    assert snapshot_after is not None
    assert dict(snapshot_after.values) == values_before
    assert tuple(item.value for item in snapshot_after.interrupts) == interrupts_before
    assert runtime.get_checkpoint(task_id) == paused


@pytest.mark.parametrize(
    "resume_command",
    [
        None,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={"operation_id": "interaction-v2-artifact-validation"},
            pause_id=None,
        ),
    ],
)
def test_async_wait_never_revalidates_operation_artifact(
    resume_command: WorkflowResumeCommand | None,
) -> None:
    """Async poll/command 都只唤醒 external owner wait，不能重新执行 human artifact preflight。"""

    task_id = "task-v2-async-no-artifact"
    services = _V2ArtifactServices()
    runtime = _runtime(services)
    paused = runtime.start(_request(task_id))
    assert paused.pending_interaction is not None

    # 先正常消费 v2 human pause，建立一个真实 parameter_binding external-owner interrupt。
    # Step 7 GREEN 后这一步会执行一次 human artifact preflight；后续 async 断言从这里重新计数。
    runtime.resume(task_id, _accepted(paused.pending_interaction.pause_id))
    services.artifact_calls.clear()
    services.calls.clear()

    checkpoint = runtime.resume(task_id, resume_command)

    assert services.artifact_calls == []
    assert "ensure_operation_artifact" not in services.calls
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref is not None
