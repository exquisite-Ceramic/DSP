"""Task 7 Step 8：HITL resume 的结构化、非敏感 observability 契约。"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
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
from design_orchestrator.workflow_services import OperationArtifactResolution, WorkflowStateError

# Step36 的轻量 orchestrator lane 不安装 LangGraph。本文件只验证 runtime-private resume 日志，
# 因此必须先做模块级 optional-dependency gate；完整 Repository regression 会真实执行。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for HITL resume observability tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
_checkpoint_lookup_config = _runtime_module._checkpoint_lookup_config
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver

_LOGGER_NAME = "design_orchestrator.langgraph_runtime"
_LOG_MESSAGE = "workflow resume"


class _ObservabilityServices:
    """只暴露 human artifact preflight 与 parameter binding，便于检查安全日志字段。"""

    def __init__(self) -> None:
        self.operation_ref = StableRef("observable-operation", "b" * 64)
        self.context_ref = StableRef("observable-context", "a" * 64)
        self.async_ref = AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="observable-interaction",
        )
        self.artifact_resolution = OperationArtifactResolution(
            ref=self.operation_ref,
            source="durable",
        )
        self.artifact_failure: Exception | None = None

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """返回配置好的 authority 结果；失败场景保留底层 cause。"""

        assert operation_ref == self.operation_ref
        assert context_snapshot_ref == self.context_ref
        assert allow_legacy_rehydrate is False
        if self.artifact_failure is not None:
            raise self.artifact_failure
        return self.artifact_resolution

    def bind_parameters(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> AsyncOperationRef:
        """Human ACCEPT 后携带 exact ContextSnapshot ref 进入真实 external-owner async wait。"""

        assert operation_ref == self.operation_ref
        assert context_snapshot_ref == self.context_ref
        return self.async_ref

    def __getattr__(self, name: str):
        """任何超出本组测试边界的 owner 调用都说明 graph 意外前进。"""

        raise AssertionError(f"unexpected workflow service call: {name}")


def _runtime_and_pause(
    task_id: str,
    services: _ObservabilityServices,
) -> tuple[LangGraphWorkflowRuntime, PendingInteractionView]:
    """用当前 graph 建立真实 v2 Operation Proposal interrupt。"""

    runtime = LangGraphWorkflowRuntime(
        services=services,
        checkpointer=InMemorySaver(),
    )
    pending = PendingInteractionView(
        pause_id=f"pause-{task_id}",
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=services.operation_ref,
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )
    config = runtime._graph.update_state(
        _checkpoint_lookup_config(task_id),
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": task_id,
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "context_snapshot_ref": _encode_stable_ref(services.context_ref),
            "operation_ref": _encode_stable_ref(services.operation_ref),
            "pending_interaction": encode_pending_interaction(pending),
            "async_operation_ref": None,
        },
        as_node="prepare_operation_proposal_pause",
    )
    runtime._graph.invoke(None, config)
    return runtime, pending


def _resume_records(caplog) -> list[object]:
    """只返回 Task 7 runtime 的单次 resume 结构化事件。"""

    return [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.getMessage() == _LOG_MESSAGE
    ]


def _assert_no_sensitive_body(record: object, *secrets: str) -> None:
    """日志正文与结构化属性都不得包含 command/domain body。"""

    rendered = repr(record.__dict__)
    message = record.getMessage()
    for secret in secrets:
        assert secret not in rendered
        assert secret not in message


def test_human_accept_logs_correlated_durable_fields_without_payload(caplog) -> None:
    """成功 human ACCEPT 必须记录 correlation/artifact 标量，但绝不记录 payload body。"""

    task_id = "task-observe-human"
    services = _ObservabilityServices()
    runtime, pending = _runtime_and_pause(task_id, services)
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()

    runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=pending.pause_id,
        ),
    )

    records = _resume_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.task_id == task_id
    assert record.pause_id == pending.pause_id
    assert record.pending_kind == "OPERATION_PROPOSAL"
    assert record.resume_kind == "OPERATION_PROPOSAL_ACCEPTED"
    assert record.resume_mode == "human"
    assert record.artifact_ref == services.operation_ref.ref_id
    assert record.artifact_content_hash == services.operation_ref.content_hash
    assert record.artifact_source == "durable"
    assert record.checkpoint_contract_version == 2
    assert record.result == "accepted"
    _assert_no_sensitive_body(record, "payload", "request_data")


@pytest.mark.parametrize(
    ("command", "expected_result"),
    [
        (
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={},
                pause_id="pause-stale-attempt",
            ),
            "stale",
        ),
        (
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={},
                pause_id="pause-task-observe-validation",
            ),
            "mismatch",
        ),
        (
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={"forbidden": "SECRET-HUMAN-BODY"},
                pause_id="pause-task-observe-validation",
            ),
            "invalid",
        ),
    ],
)
def test_human_validation_rejection_logs_stable_result_without_artifact_body(
    caplog,
    command: WorkflowResumeCommand,
    expected_result: str,
) -> None:
    """stale/mismatch/invalid 必须在 artifact preflight 前产生安全的 human 结果日志。"""

    task_id = "task-observe-validation"
    services = _ObservabilityServices()
    runtime, pending = _runtime_and_pause(task_id, services)
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()

    with pytest.raises(WorkflowStateError):
        runtime.resume(task_id, command)

    records = _resume_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.task_id == task_id
    assert record.pause_id == pending.pause_id
    assert record.pending_kind == "OPERATION_PROPOSAL"
    assert record.resume_kind == command.resume_kind
    assert record.resume_mode == "human"
    assert record.checkpoint_contract_version == 2
    assert record.result == expected_result
    assert not hasattr(record, "artifact_source")
    _assert_no_sensitive_body(record, "SECRET-HUMAN-BODY", repr(dict(command.payload)))


def test_artifact_unavailable_logs_safe_identity_and_preserves_original_cause(caplog) -> None:
    """artifact unavailable 只记录 pending identity/hash，不输出底层异常正文或 domain body。"""

    task_id = "task-observe-unavailable"
    services = _ObservabilityServices()
    runtime, pending = _runtime_and_pause(task_id, services)
    try:
        raise LookupError("SECRET-STORAGE-DIAGNOSTIC")
    except LookupError as exc:
        unavailable = WorkflowArtifactUnavailableError("artifact unavailable")
        unavailable.__cause__ = exc
        services.artifact_failure = unavailable
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()

    with pytest.raises(WorkflowStateError) as captured:
        runtime.resume(
            task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={},
                pause_id=pending.pause_id,
            ),
        )

    assert captured.value.code == "WORKFLOW_ARTIFACT_UNAVAILABLE"
    records = _resume_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.resume_mode == "human"
    assert record.result == "unavailable"
    assert record.artifact_ref == services.operation_ref.ref_id
    assert record.artifact_content_hash == services.operation_ref.content_hash
    assert not hasattr(record, "artifact_source")
    _assert_no_sensitive_body(record, "SECRET-STORAGE-DIAGNOSTIC")


def test_async_command_logs_continued_without_human_fields_or_payload(caplog) -> None:
    """external-owner async command 只记录恢复模式/结果，不泄漏 payload 且没有 human 字段。"""

    task_id = "task-observe-async"
    services = _ObservabilityServices()
    runtime, pending = _runtime_and_pause(task_id, services)
    runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=pending.pause_id,
        ),
    )
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()
    secret = "SECRET-ASYNC-DOMAIN-BODY"

    runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={
                "operation_id": services.async_ref.operation_id,
                "domain_body": secret,
            },
        ),
    )

    records = _resume_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.task_id == task_id
    assert record.resume_kind == "ASYNC_OPERATION_COMPLETED"
    assert record.resume_mode == "async"
    assert record.checkpoint_contract_version == 2
    assert record.result == "continued"
    assert not hasattr(record, "pause_id")
    assert not hasattr(record, "pending_kind")
    assert not hasattr(record, "artifact_ref")
    assert not hasattr(record, "artifact_content_hash")
    assert not hasattr(record, "artifact_source")
    _assert_no_sensitive_body(record, secret, "domain_body")


def test_async_poll_logs_continued_without_human_fields(caplog) -> None:
    """poll 也是独立 resume_mode；它不携带 resume kind、pause 或 artifact identity。"""

    task_id = "task-observe-poll"
    services = _ObservabilityServices()
    runtime, pending = _runtime_and_pause(task_id, services)
    runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=pending.pause_id,
        ),
    )
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()

    runtime.resume(task_id, None)

    records = _resume_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.task_id == task_id
    assert record.resume_kind is None
    assert record.resume_mode == "poll"
    assert record.checkpoint_contract_version == 2
    assert record.result == "continued"
    assert not hasattr(record, "pause_id")
    assert not hasattr(record, "pending_kind")
    assert not hasattr(record, "artifact_ref")
