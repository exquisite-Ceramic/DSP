from __future__ import annotations

from collections.abc import Callable

import pytest
from design_orchestrator import WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_runtime import ProductFlowStatus

_SEMANTIC_WALL_ID = "WALL-001"


def _submit_and_accept(case):
    """通过真实 ProductFlow 接受 exact proposal，并把结果留给各 verification 场景断言。"""

    proposal = case.flow.submit(case.request)
    assert proposal.status is ProductFlowStatus.WAITING
    assert proposal.checkpoint.pending_interaction is not None
    return case.flow.resume(
        case.task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=proposal.checkpoint.pending_interaction.pause_id,
        ),
    )


def _inject_wider_effect(case, effect: dict[str, object]) -> None:
    """只扩展 fake Host 的成功 verification evidence，让真实 ActualDelta adapter/scope owner 判定。"""

    execute = case.host._execute_wall_thickness

    def execute_with_wider_effect(command):
        result = execute(command)
        if result.get("status") != "OK":
            return result
        patched = dict(result)
        verification = dict(patched["verification"])
        verification["normalized_wider_effects"] = [effect]
        patched["verification"] = verification
        return patched

    case.host._execute_wall_thickness = execute_with_wider_effect


def _inject_post_commit_snapshot_transform(
    case,
    transform: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    """只改 mutation 之后的独立 snapshot READ；pre-execute freshness READ 保持原始真实 fixture。"""

    request = case.host.request

    def request_with_post_commit_transform(command):
        result = request(command)
        if (
            command.operation == "read_wall_thickness_snapshot"
            and case.host.execute_count == 1
        ):
            return transform(dict(result))
        return result

    case.host.request = request_with_post_commit_transform


def _assert_committed_once_without_success(case) -> None:
    """所有 post-commit failure 都必须保持 exactly-one Host mutation，且不能投影产品成功。"""

    assert case.host.execute_count == 1
    assert case.host.command_operations().count("set_wall_thickness") == 1


def test_actual_delta_extra_entity_is_rejected_by_real_scope_comparator(
    revit_wall_thickness_product_case,
) -> None:
    """场景 11/19：Host 报告额外实体变化时，真实 ScopeComparator 阻止 Step33/product success。"""

    case = revit_wall_thickness_product_case("task-product-extra-entity")
    _inject_wider_effect(
        case,
        {
            "semantic_id": "WALL-UNAPPROVED",
            "canonical_kind": "ifc:IfcWall",
            "changed_aspects": ["PROPERTIES"],
        },
    )

    result = _submit_and_accept(case)

    _assert_committed_once_without_success(case)
    assert result.status is not ProductFlowStatus.SUCCEEDED
    assert result.saga_id is not None
    saga = case.saga_store.get_saga(result.saga_id)
    assert saga is not None
    slice_state = saga.slice_states[0]
    assert slice_state.actual_delta_hash is not None
    assert slice_state.scope_comparison_hash is not None
    assert slice_state.verification_hash is None


def test_actual_delta_extra_aspect_is_rejected_by_real_scope_comparator(
    revit_wall_thickness_product_case,
) -> None:
    """场景 12/19：同一 approved Wall 出现未授权 GEOMETRY aspect 时产品不得成功。"""

    case = revit_wall_thickness_product_case("task-product-extra-aspect")
    _inject_wider_effect(
        case,
        {
            "semantic_id": _SEMANTIC_WALL_ID,
            "canonical_kind": "ifc:IfcWall",
            "changed_aspects": ["GEOMETRY"],
        },
    )

    result = _submit_and_accept(case)

    _assert_committed_once_without_success(case)
    assert result.status is not ProductFlowStatus.SUCCEEDED
    assert result.saga_id is not None
    saga = case.saga_store.get_saga(result.saga_id)
    assert saga is not None
    slice_state = saga.slice_states[0]
    assert slice_state.actual_delta_hash is not None
    assert slice_state.scope_comparison_hash is not None
    assert slice_state.verification_hash is None


def test_mutation_claims_300_but_independent_read_other_value_fails_semantic_verification(
    revit_wall_thickness_product_case,
) -> None:
    """场景 13/19：mutation response 的 300 不能替代 independent READ；275 必须由 SemanticVerifier 判失败。"""

    case = revit_wall_thickness_product_case("task-product-independent-wrong-value")

    def wrong_value(result: dict[str, object]) -> dict[str, object]:
        payload = dict(result["payload"])
        payload["wall_thickness_mm"] = 275.0
        result["payload"] = payload
        return result

    _inject_post_commit_snapshot_transform(case, wrong_value)

    result = _submit_and_accept(case)

    _assert_committed_once_without_success(case)
    assert case.host.current_thickness_mm == 300.0
    assert result.status is not ProductFlowStatus.SUCCEEDED
    assert result.saga_id is not None
    saga = case.saga_store.get_saga(result.saga_id)
    assert saga is not None
    slice_state = saga.slice_states[0]
    assert slice_state.actual_delta_hash is not None
    assert slice_state.scope_comparison_hash is not None
    assert slice_state.verification_hash is not None


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("document_id", "DOC-WRONG", "REVIT_SNAPSHOT_DOCUMENT_MISMATCH"),
        ("host_instance_id", "REVIT-WRONG", "REVIT_SNAPSHOT_HOST_MISMATCH"),
        ("wall_unique_id", "REVIT-WALL-WRONG", "REVIT_SNAPSHOT_TARGET_MISMATCH"),
    ),
)
def test_independent_read_wrong_identity_fails_closed_without_second_execute(
    revit_wall_thickness_product_case,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    """场景 14/19：独立 READ 的 host/document/entity 任一不匹配都必须拒绝 evidence。"""

    case = revit_wall_thickness_product_case(f"task-product-wrong-{field}")

    def wrong_identity(result: dict[str, object]) -> dict[str, object]:
        payload = dict(result["payload"])
        payload[field] = value
        result["payload"] = payload
        return result

    _inject_post_commit_snapshot_transform(case, wrong_identity)

    with pytest.raises(WorkflowStateError) as captured:
        _submit_and_accept(case)

    assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
    cause = captured.value.__cause__
    assert isinstance(cause, ValueError)
    assert str(cause).startswith(f"{expected_code}:")
    _assert_committed_once_without_success(case)
    checkpoint = case.flow.get(case.task_id)
    assert checkpoint is not None
    assert checkpoint.status is not ProductFlowStatus.SUCCEEDED


def test_independent_read_newer_revision_is_not_accepted_as_commit_evidence(
    revit_wall_thickness_product_case,
) -> None:
    """场景 15/19：即使值仍为 300，revision 44 也不能证明 revision 43 的 committed state。"""

    case = revit_wall_thickness_product_case("task-product-newer-read-revision")

    def newer_revision(result: dict[str, object]) -> dict[str, object]:
        case.host.current_revision += 1
        result["revision_after"] = case.host.current_revision
        payload = dict(result["payload"])
        payload["revision_before"] = case.host.current_revision
        payload["revision_after"] = case.host.current_revision
        result["payload"] = payload
        return result

    _inject_post_commit_snapshot_transform(case, newer_revision)

    with pytest.raises(WorkflowStateError) as captured:
        _submit_and_accept(case)

    assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
    cause = captured.value.__cause__
    assert isinstance(cause, ValueError)
    assert str(cause).startswith("REVIT_SNAPSHOT_REVISION_MISMATCH:")
    _assert_committed_once_without_success(case)
    checkpoint = case.flow.get(case.task_id)
    assert checkpoint is not None
    assert checkpoint.status is not ProductFlowStatus.SUCCEEDED


def test_revision_change_during_independent_read_stays_recoverable_without_redispatch(
    revit_wall_thickness_product_case,
) -> None:
    """场景 16/19：READ window 内 revision 漂移属于 evidence unavailable，保持 RECONCILING recovery。"""

    case = revit_wall_thickness_product_case("task-product-read-window-revision-change")

    def changed_during_read(result: dict[str, object]) -> dict[str, object]:
        case.host.current_revision += 1
        return {
            "status": "ERROR",
            "revision_after": case.host.current_revision,
            "error": {"code": "REVIT_SNAPSHOT_REVISION_CHANGED"},
        }

    _inject_post_commit_snapshot_transform(case, changed_during_read)

    result = _submit_and_accept(case)

    _assert_committed_once_without_success(case)
    assert result.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert result.saga_id is not None
    saga = case.saga_store.get_saga(result.saga_id)
    assert saga is not None
    slice_state = saga.slice_states[0]
    assert slice_state.actual_delta_hash is not None
    assert slice_state.scope_comparison_hash is not None
    assert slice_state.verification_hash is None

    # 为获取“更干净” evidence 不得再次 mutation；重复产品读取也只投影 owner truth。
    reread = case.flow.get(case.task_id)
    assert reread is not None
    assert reread.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert case.host.execute_count == 1
