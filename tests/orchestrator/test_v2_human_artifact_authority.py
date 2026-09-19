"""Task 7 Step 7：v2 human resume 必须先验证 durable operation artifact authority。"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    _encode_async_ref,
    _encode_stable_ref,
    encode_pending_interaction,
)
from design_orchestrator.workflow_artifacts import WorkflowArtifactUnavailableError
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from design_orchestrator.workflow_services import (
    OperationArtifactResolution,
    WorkflowStateError,
)

# Step36 的轻量 orchestrator lane 不安装 LangGraph；本文件只验证 runtime-private resume
# authority，因此先做模块级 optional-dependency gate。完整 Repository regression 会真实执行。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for v2 human artifact authority tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
_checkpoint_lookup_config = _runtime_module._checkpoint_lookup_config
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver


class _ArtifactAuthorityServices:
    """只记录 Step 7 允许触达的 artifact authority 与 binder 边界。"""

    def __init__(
        self,
        *,
        resolution: OperationArtifactResolution | None = None,
        failure: bool = False,
    ) -> None:
        self.resolution = resolution
        self.failure = failure
        self.artifact_calls: list[tuple[StableRef, StableRef, bool]] = []
        self.bound_operation_refs: list[StableRef] = []
        self.async_ref = AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="v2-artifact-authority-binding",
        )

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """返回指定 authority 结果，或保留 storage cause 模拟 artifact 不可用。"""

        self.artifact_calls.append(
            (operation_ref, context_snapshot_ref, allow_legacy_rehydrate)
        )
        if self.failure:
            try:
                raise LookupError("durable operation artifact row is unavailable")
            except LookupError as exc:
                raise WorkflowArtifactUnavailableError(
                    "durable operation artifact is unavailable"
                ) from exc
        if self.resolution is None:
            raise AssertionError("artifact authority test requires a configured resolution")
        return self.resolution

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        """记录 graph 真正消费 command 后使用的 operation ref，并再次进入 async wait。"""

        self.bound_operation_refs.append(operation_ref)
        return self.async_ref

    def __getattr__(self, name: str):
        """任何超出 Step 7 边界的 service 调用都说明 graph 意外越界。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


def _seed_v2_human_pause(
    *,
    task_id: str,
    services: _ArtifactAuthorityServices,
) -> tuple[object, StableRef, StableRef, PendingInteractionView]:
    """用当前 graph 建立真实 v2 await_operation_proposal interrupt。"""

    saver = InMemorySaver()
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)
    context_ref = StableRef("v2-context", "a" * 64)
    operation_ref = StableRef("v2-operation", "b" * 64)
    pending = PendingInteractionView(
        pause_id="pause-v2-artifact-authority",
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=operation_ref,
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )
    migrated_config = runtime._graph.update_state(
        _checkpoint_lookup_config(task_id),
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "context_snapshot_ref": _encode_stable_ref(context_ref),
            "operation_ref": _encode_stable_ref(operation_ref),
            "pending_interaction": encode_pending_interaction(pending),
            "async_operation_ref": None,
        },
        as_node="prepare_operation_proposal_pause",
    )
    runtime._graph.invoke(None, migrated_config)
    return runtime, context_ref, operation_ref, pending


def _seed_v2_async_wait(
    *,
    task_id: str,
    services: _ArtifactAuthorityServices,
) -> tuple[object, StableRef, AsyncOperationRef]:
    """直接从 parameter_binding 输出建立真实 v2 async interrupt，证明它不是 human artifact gate。"""

    saver = InMemorySaver()
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=saver)
    operation_ref = StableRef("v2-async-operation", "d" * 64)
    async_ref = AsyncOperationRef(
        kind=AsyncOperationKind.INTERACTION_SESSION,
        owner="interaction",
        operation_id="v2-async-wait",
    )
    async_config = runtime._graph.update_state(
        _checkpoint_lookup_config(task_id),
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": task_id,
            "phase": WorkflowPhase.PARAMETER_BINDING.value,
            "context_snapshot_ref": _encode_stable_ref(
                StableRef("v2-async-context", "c" * 64)
            ),
            "operation_ref": _encode_stable_ref(operation_ref),
            "pending_interaction": None,
            "async_operation_ref": _encode_async_ref(async_ref),
            "resume_node": "parameter_binding",
        },
        as_node="parameter_binding",
    )
    runtime._graph.invoke(None, async_config)
    return runtime, operation_ref, async_ref


def _accept(pause_id: str) -> WorkflowResumeCommand:
    """构造与 v2 Operation Proposal pause 精确相关的 ACCEPT command。"""

    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        payload={},
        pause_id=pause_id,
    )


def _snapshot_identity(runtime, task_id: str) -> tuple[dict[str, object], tuple[object, ...]]:
    """提取 side-effect 前后的持久化 values/interrupt payload，用于证明失败不移动 checkpoint。"""

    snapshot = runtime._load_snapshot(task_id)
    assert snapshot is not None
    return (
        dict(snapshot.values),
        tuple(item.value for item in snapshot.interrupts),
    )


def test_v2_human_resume_requires_exact_durable_artifact_before_graph_invocation() -> None:
    """v2 ACCEPT 必须先 durable exact-hit，随后 binder 才能消费同一个 subject ref。"""

    task_id = "task-v2-artifact-authority-success"
    operation_ref = StableRef("v2-operation", "b" * 64)
    services = _ArtifactAuthorityServices(
        resolution=OperationArtifactResolution(operation_ref, "durable")
    )
    runtime, context_ref, seeded_operation_ref, pending = _seed_v2_human_pause(
        task_id=task_id,
        services=services,
    )
    assert seeded_operation_ref == operation_ref

    checkpoint = runtime.resume(task_id, _accept(pending.pause_id))

    assert services.artifact_calls == [(operation_ref, context_ref, False)]
    assert services.bound_operation_refs == [operation_ref]
    assert checkpoint.pending_interaction is None
    assert checkpoint.async_operation_ref == services.async_ref


def test_v2_human_artifact_unavailable_preserves_pause_and_original_cause() -> None:
    """durable artifact 缺失/损坏必须稳定报错，且在任何 graph/binder mutation 前失败。"""

    task_id = "task-v2-artifact-authority-unavailable"
    services = _ArtifactAuthorityServices(failure=True)
    runtime, context_ref, operation_ref, pending = _seed_v2_human_pause(
        task_id=task_id,
        services=services,
    )
    before_checkpoint = runtime.get_checkpoint(task_id)
    before_identity = _snapshot_identity(runtime, task_id)

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(task_id, _accept(pending.pause_id))

    assert captured.value.code == "WORKFLOW_ARTIFACT_UNAVAILABLE"
    assert isinstance(captured.value.__cause__, WorkflowArtifactUnavailableError)
    assert isinstance(captured.value.__cause__.__cause__, LookupError)
    assert services.artifact_calls == [(operation_ref, context_ref, False)]
    assert services.bound_operation_refs == []
    assert runtime.get_checkpoint(task_id) == before_checkpoint
    assert _snapshot_identity(runtime, task_id) == before_identity


@pytest.mark.parametrize(
    ("resolution", "case_name"),
    [
        (
            OperationArtifactResolution(
                StableRef("v2-operation", "b" * 64),
                "rehydrated",
            ),
            "rehydrated-source",
        ),
        (
            OperationArtifactResolution(
                StableRef("different-operation", "e" * 64),
                "durable",
            ),
            "different-ref",
        ),
    ],
)
def test_v2_human_artifact_authority_mismatch_fails_closed_without_consuming_command(
    resolution: OperationArtifactResolution,
    case_name: str,
) -> None:
    """v2 只能接受 exact durable identity；legacy rehydrate 或 ref 漂移都不能继续。"""

    task_id = f"task-v2-artifact-authority-{case_name}"
    services = _ArtifactAuthorityServices(resolution=resolution)
    runtime, context_ref, operation_ref, pending = _seed_v2_human_pause(
        task_id=task_id,
        services=services,
    )
    before_checkpoint = runtime.get_checkpoint(task_id)
    before_identity = _snapshot_identity(runtime, task_id)

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(task_id, _accept(pending.pause_id))

    assert captured.value.code == "WORKFLOW_ARTIFACT_UNAVAILABLE"
    assert services.artifact_calls == [(operation_ref, context_ref, False)]
    assert services.bound_operation_refs == []
    assert runtime.get_checkpoint(task_id) == before_checkpoint
    assert _snapshot_identity(runtime, task_id) == before_identity


def test_v2_async_resume_never_invokes_operation_artifact_recovery() -> None:
    """真实 async interrupt 仍沿用外部 owner 恢复语义，不能误走 human artifact authority gate。"""

    task_id = "task-v2-async-no-artifact-recovery"
    services = _ArtifactAuthorityServices(
        resolution=OperationArtifactResolution(
            StableRef("unused-operation", "f" * 64),
            "durable",
        )
    )
    runtime, operation_ref, async_ref = _seed_v2_async_wait(
        task_id=task_id,
        services=services,
    )

    checkpoint = runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={"operation_id": async_ref.operation_id},
        ),
    )

    assert services.artifact_calls == []
    assert services.bound_operation_refs == [operation_ref]
    assert checkpoint.async_operation_ref == services.async_ref
