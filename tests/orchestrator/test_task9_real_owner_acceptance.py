"""Task 9 B/C/D/F：补齐真实 owner workflow acceptance。

本模块复用 ``test_real_owner_workflow_end_to_end`` 已冻结的 reference composition，
只增加行为断言；不新增 owner fake、Saga/dispatch/recovery 状态机或私有 selector。
"""

from __future__ import annotations

import pytest
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
)

from tests.orchestrator import test_real_owner_workflow_end_to_end as real_owner


def _checkpoint_values(case) -> dict[str, object]:
    """只通过 LangGraph saver 公共 API 读取 root checkpoint 的 JSON-compatible state。"""

    checkpoint_tuple = case.checkpointer.get_tuple(
        {
            "configurable": {
                "thread_id": case.task_id,
                "checkpoint_ns": "",
            }
        }
    )
    assert checkpoint_tuple is not None
    checkpoint = checkpoint_tuple.checkpoint
    assert isinstance(checkpoint, dict)
    values = checkpoint.get("channel_values")
    assert isinstance(values, dict)
    return values


def _stable_ref_from_state(value: object) -> StableRef:
    """把 saver 中允许持久化的 StableRef mapping 恢复为 framework-neutral ref。"""

    assert isinstance(value, dict)
    ref_id = value.get("ref_id")
    content_hash = value.get("content_hash")
    assert isinstance(ref_id, str) and ref_id
    assert isinstance(content_hash, str) and content_hash
    return StableRef(ref_id, content_hash)


def _all_mapping_keys(value: object) -> set[str]:
    """递归收集 checkpoint mapping keys，用于拒绝 authoritative owner body。"""

    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_all_mapping_keys(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            keys.update(_all_mapping_keys(item))
    return keys


def _all_type_names(value: object) -> set[str]:
    """递归收集反序列化类型名，确保 checkpoint 只保留 navigation/value primitives。"""

    names = {type(value).__name__}
    if isinstance(value, dict):
        for item in value.values():
            names.update(_all_type_names(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            names.update(_all_type_names(item))
    return names


@real_owner.requires_postgres
def test_real_owner_hitl_requires_exact_pause_and_rejects_consumed_resume() -> None:
    """B：exact pause_id 只能消费一次；旧 human command 不得穿透到真实 owner/Host。"""

    case = real_owner._build_real_owner_case("task9-real-owner-hitl-b")
    try:
        proposal_wait = case.runtime.start(real_owner._request(case.task_id))
        assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal_wait.pending_interaction is not None
        pause_id = proposal_wait.pending_interaction.pause_id

        accept = WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=pause_id,
        )
        freshness_wait = case.runtime.resume(case.task_id, accept)
        assert freshness_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS
        assert freshness_wait.async_operation_ref == AsyncOperationRef(
            kind=AsyncOperationKind.RECONSTRUCTION_JOB,
            owner="semantic-runtime",
            operation_id="task9-reconstruction",
        )

        # 同一个 pause 已被消费；重放必须在任何 Host mutation 前稳定拒绝。
        with pytest.raises(RuntimeError, match="WORKFLOW_RESUME_STALE"):
            case.runtime.resume(case.task_id, accept)
        assert case.runtime.get_checkpoint(case.task_id) == freshness_wait
        assert case.host_port.calls == []

        case.semantic_boundary.operation_ready = True
        completed = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={"operation_id": "task9-reconstruction"},
            ),
        )
        assert completed.phase is WorkflowPhase.COMPLETED
        assert len(case.host_port.calls) == 1
    finally:
        real_owner._close_case(case)


@real_owner.requires_postgres
def test_real_owner_async_resume_persists_and_consumes_exact_freshness_tuple() -> None:
    """C：async re-entry 后 saver 中的新 PS/PSS tuple 必须与真实 Impact owner 输入一致。"""

    case = real_owner._build_real_owner_case("task9-real-owner-async-c")
    try:
        proposal_wait = case.runtime.start(real_owner._request(case.task_id))
        assert proposal_wait.pending_interaction is not None
        freshness_wait = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                pause_id=proposal_wait.pending_interaction.pause_id,
            ),
        )
        assert freshness_wait.phase is WorkflowPhase.ENSURE_OPERATION_FRESHNESS

        waiting_values = _checkpoint_values(case)
        assert waiting_values.get("planning_snapshot_ref") is None
        assert waiting_values.get("snapshot_set_ref") is None

        case.semantic_boundary.operation_ready = True
        completed = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={"operation_id": "task9-reconstruction"},
            ),
        )
        assert completed.phase is WorkflowPhase.COMPLETED

        values = _checkpoint_values(case)
        operation_ref = _stable_ref_from_state(values["operation_ref"])
        planning_ref = _stable_ref_from_state(values["planning_snapshot_ref"])
        snapshot_set_ref = _stable_ref_from_state(values["snapshot_set_ref"])
        impact_ref = _stable_ref_from_state(values["impact_ref"])

        assert completed.operation_ref == operation_ref
        analysis = case.impact_store.get(impact_ref.ref_id)
        assert impact_ref.content_hash == analysis.analysis_fingerprint
        assert analysis.planning_snapshot_ref.snapshot_id == planning_ref.ref_id
        assert analysis.planning_snapshot_ref.snapshot_hash == planning_ref.content_hash
        assert analysis.snapshot_set_ref.snapshot_set_id == snapshot_set_ref.ref_id
        assert analysis.snapshot_set_ref.snapshot_set_hash == snapshot_set_ref.content_hash
        assert case.semantic_boundary.reconstruction_calls == [
            ("CONTEXT_FRESHNESS", "42"),
            ("OPERATION_FRESHNESS", "42"),
            ("OPERATION_FRESHNESS", "42"),
        ]
        assert len(case.host_port.calls) == 1
    finally:
        real_owner._close_case(case)


@real_owner.requires_postgres
def test_real_owner_resume_fails_closed_when_context_snapshot_owner_truth_is_missing(
) -> None:
    """D：checkpoint 只保存 ContextSnapshot ref。

    owner body 丢失后 fresh runtime 必须 fail closed。
    """

    task_id = "task9-real-owner-missing-d"
    case_a = real_owner._build_real_owner_case(task_id)
    try:
        proposal_wait = case_a.runtime.start(real_owner._request(task_id))
        assert proposal_wait.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert proposal_wait.pending_interaction is not None
        assert proposal_wait.context_snapshot_ref is not None
    finally:
        # 丢弃 runtime A 的 in-memory Semantic Runtime registry；PostgreSQL checkpoint/artifact
        # 仍完整保留，fresh runtime 只能看到 ref，不能从 checkpoint 重建 SemanticSnapshot body。
        real_owner._close_case(case_a)

    case_b = real_owner._build_real_owner_case(task_id)
    try:
        reopened = case_b.runtime.get_checkpoint(task_id)
        assert reopened == proposal_wait

        with pytest.raises(RuntimeError, match="WORKFLOW_SERVICE_FAILURE") as exc_info:
            case_b.runtime.resume(
                task_id,
                WorkflowResumeCommand(
                    resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                    pause_id=proposal_wait.pending_interaction.pause_id,
                ),
            )
        assert getattr(exc_info.value.__cause__, "code", None) == (
            "SNAPSHOT_REFERENCE_NOT_FOUND"
        )
        assert case_b.host_port.calls == []
        assert case_b.saga_store.get_saga("SAGA-TASK9") is None
    finally:
        real_owner._close_case(case_b)


@real_owner.requires_postgres
def test_real_owner_checkpoint_contains_refs_and_navigation_only() -> None:
    """F：真实 owner terminal checkpoint 不得序列化任何 authoritative domain body。"""

    case = real_owner._build_real_owner_case("task9-real-owner-refs-only-f")
    try:
        proposal_wait = case.runtime.start(real_owner._request(case.task_id))
        assert proposal_wait.pending_interaction is not None
        case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                pause_id=proposal_wait.pending_interaction.pause_id,
            ),
        )
        case.semantic_boundary.operation_ready = True
        completed = case.runtime.resume(
            case.task_id,
            WorkflowResumeCommand(
                resume_kind="ASYNC_OPERATION_COMPLETED",
                payload={"operation_id": "task9-reconstruction"},
            ),
        )
        assert completed.phase is WorkflowPhase.COMPLETED

        checkpoint_tuple = case.checkpointer.get_tuple(
            {
                "configurable": {
                    "thread_id": case.task_id,
                    "checkpoint_ns": "",
                }
            }
        )
        assert checkpoint_tuple is not None
        payload = checkpoint_tuple.checkpoint

        forbidden_types = {
            "SemanticSnapshot",
            "SnapshotSet",
            "ImpactAnalysis",
            "ApprovalScopeDefinitionV2",
            "ApprovalScopeBoundaryV2",
            "CanonicalChangeSet",
            "ApprovalRecord",
            "ExecutionGrantV2",
            "ExecutionPlanV2",
            "ProviderBindingSetV2",
            "StoredExecutionSagaV2",
            "HostDispatchIntent",
            "ActualDelta",
        }
        forbidden_body_keys = {
            "freshness_contract_id",
            "base_host_revision",
            "aspect_guarantees",
            "member_snapshot_ids",
            "analysis_id",
            "analysis_fingerprint",
            "scope_definition_id",
            "scope_hash",
            "changeset_id",
            "approval_id",
            "grant_id",
            "execution_plan_id",
            "binding_set_id",
            "saga_revision",
            "ordered_slice_hashes",
            "dispatch_intent_id",
            "actual_delta_id",
        }
        assert _all_type_names(payload).isdisjoint(forbidden_types)
        assert _all_mapping_keys(payload).isdisjoint(forbidden_body_keys)

        values = _checkpoint_values(case)
        for field_name in (
            "context_snapshot_ref",
            "operation_ref",
            "planning_snapshot_ref",
            "snapshot_set_ref",
            "impact_ref",
            "changeset_ref",
            "approval_ref",
            "execution_plan_ref",
            "provider_binding_ref",
            "grant_ref",
        ):
            assert isinstance(values.get(field_name), dict)
        assert values.get("saga_id") == completed.saga_id
    finally:
        real_owner._close_case(case)
