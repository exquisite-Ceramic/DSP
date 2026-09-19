"""Task 7 Step 8：legacy human migration 的安全 resume observability 契约。"""

from __future__ import annotations

from importlib import import_module

import pytest
from design_orchestrator.langgraph_state import (
    WorkflowGraphState,
    _decode_stable_ref,
    _encode_stable_ref,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
)
from design_orchestrator.workflow_services import OperationArtifactResolution

# Step36 的轻量 lane 不安装 LangGraph；完整 Repository regression 会执行本测试。
pytest.importorskip(
    "langgraph",
    reason="langgraph is required for legacy HITL resume observability tests",
)
_runtime_module = import_module("design_orchestrator.langgraph_runtime")
LangGraphWorkflowRuntime = _runtime_module.LangGraphWorkflowRuntime
_runtime_config = _runtime_module._runtime_config
InMemorySaver = import_module("langgraph.checkpoint.memory").InMemorySaver
_graph_module = import_module("langgraph.graph")
END = _graph_module.END
START = _graph_module.START
StateGraph = _graph_module.StateGraph
interrupt = import_module("langgraph.types").interrupt

_LOGGER_NAME = "design_orchestrator.langgraph_runtime"
_LOG_MESSAGE = "workflow resume"


class _LegacyObservabilityServices:
    """只允许 legacy artifact rehydrate 与后续 parameter binding。"""

    def __init__(self) -> None:
        self.durable_ref = StableRef("legacy-observable-durable", "c" * 64)
        self.async_ref = AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="legacy-observable-interaction",
        )

    def ensure_operation_artifact(
        self,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
        *,
        allow_legacy_rehydrate: bool,
    ) -> OperationArtifactResolution:
        """legacy migration 必须明确允许 rehydrate，并返回新的 durable identity。"""

        assert operation_ref == StableRef("legacy-observable-operation", "b" * 64)
        assert context_snapshot_ref == StableRef("legacy-observable-context", "a" * 64)
        assert allow_legacy_rehydrate is True
        return OperationArtifactResolution(ref=self.durable_ref, source="rehydrated")

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        """证明 command 消费发生在 migration 建立 v2 human interrupt 之后。"""

        assert operation_ref == self.durable_ref
        return self.async_ref

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected workflow service call: {name}")


def _build_legacy_graph(checkpointer: InMemorySaver):
    """复制 pre-v2 Operation Proposal await 节点，真实写入旧 interrupt。"""

    builder = StateGraph(WorkflowGraphState)

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
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


def test_legacy_human_accept_logs_rehydrated_artifact_without_domain_body(caplog) -> None:
    """legacy 成功迁移只记录 rehydrated identity，不记录 command/domain body。"""

    task_id = "task-observe-legacy-rehydrated"
    context_ref = StableRef("legacy-observable-context", "a" * 64)
    operation_ref = StableRef("legacy-observable-operation", "b" * 64)
    services = _LegacyObservabilityServices()
    saver = InMemorySaver()
    legacy_graph = _build_legacy_graph(saver)
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
    before = runtime.get_checkpoint(task_id)
    assert before is not None and before.pending_interaction is not None
    pause_id = before.pending_interaction.pause_id
    caplog.set_level("INFO", logger=_LOGGER_NAME)
    caplog.clear()

    runtime.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            payload={},
            pause_id=pause_id,
        ),
    )

    records = [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.getMessage() == _LOG_MESSAGE
    ]
    assert len(records) == 1
    record = records[0]
    assert record.task_id == task_id
    assert record.pause_id == pause_id
    assert record.pending_kind == "OPERATION_PROPOSAL"
    assert record.resume_kind == "OPERATION_PROPOSAL_ACCEPTED"
    assert record.resume_mode == "human"
    assert record.artifact_ref == services.durable_ref.ref_id
    assert record.artifact_content_hash == services.durable_ref.content_hash
    assert record.artifact_source == "rehydrated"
    assert record.checkpoint_contract_version == 2
    assert record.result == "accepted"
    rendered = repr(record.__dict__)
    assert "payload" not in rendered
    assert "request_data" not in rendered
