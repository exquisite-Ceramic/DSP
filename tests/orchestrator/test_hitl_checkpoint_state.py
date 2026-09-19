"""HITL v2 checkpoint state 的版本化与 pending-human 序列化 RED 测试。"""

from __future__ import annotations

import pytest
from design_orchestrator import langgraph_state
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowPhase,
)


def _pending() -> PendingInteractionView:
    """构造最小、完整且可持久化的 human pause 公共视图。"""

    return PendingInteractionView(
        pause_id="pause-1",
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=StableRef("operation-1", "a" * 64),
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )


def test_pending_interaction_codec_round_trips_exact_public_contract() -> None:
    """Runtime-private codec 只能持久化冻结的四个 pending interaction 字段。"""

    encoded = langgraph_state.encode_pending_interaction(_pending())

    assert encoded == {
        "pause_id": "pause-1",
        "kind": "OPERATION_PROPOSAL",
        "subject_ref": {
            "ref_id": "operation-1",
            "content_hash": "a" * 64,
        },
        "allowed_resume_kinds": [
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ],
    }
    assert langgraph_state.decode_pending_interaction(encoded) == _pending()


def test_pending_interaction_decoder_rejects_extra_keys() -> None:
    """Persisted human pause 不得携带未冻结的隐藏字段。"""

    encoded = {
        "pause_id": "pause-1",
        "kind": "OPERATION_PROPOSAL",
        "subject_ref": {
            "ref_id": "operation-1",
            "content_hash": "a" * 64,
        },
        "allowed_resume_kinds": ["OPERATION_PROPOSAL_ACCEPTED"],
        "authoritative_object": {"forbidden": True},
    }

    with pytest.raises(ValueError, match="unsupported keys"):
        langgraph_state.decode_pending_interaction(encoded)


def test_v2_operation_proposal_wait_requires_pending_interaction() -> None:
    """v2 human wait 若丢失 pending identity 必须 fail closed，不能降级成 legacy。"""

    state = {
        "checkpoint_contract_version": 2,
        "task_id": "task-1",
        "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
        "operation_ref": {
            "ref_id": "operation-1",
            "content_hash": "a" * 64,
        },
    }

    with pytest.raises(ValueError, match="pending_interaction"):
        langgraph_state.graph_state_to_checkpoint_view(state)


def test_unknown_checkpoint_contract_version_is_rejected() -> None:
    """只有 unversioned legacy 与冻结的 v2 可以被 runtime 投影。"""

    state = {
        "checkpoint_contract_version": 99,
        "task_id": "task-1",
        "phase": WorkflowPhase.RESOLVE_OPERATIONS.value,
    }

    with pytest.raises(ValueError, match="checkpoint_contract_version"):
        langgraph_state.graph_state_to_checkpoint_view(state)
