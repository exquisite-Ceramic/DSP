"""Task 16A：受控 V2 产品提交后，读取真实持久化 proposal 供人工审核。

本模块属于现场测试支持层，而非新 ProductTask owner。
它只转发 production V2 controller/MCP 并读取 checkpoint/artifact owner；
明确不发起 human ACCEPT、resume、Grant 或任何 Host EXECUTE。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_front_door.agent import AgentClarificationRequired
from design_product_front_door.sqlite_state import FrozenSubmissionV2
from design_product_runtime import (
    ProductProposalStateV2,
    ProductTaskQueryState,
    ProductTaskQueryViewV2,
    ProductTaskV2Status,
)


def _fail(code: str, detail: str) -> None:
    """使用稳定错误码停止测试，绝不把失败的 V2 关联解释成可审批 proposal。"""

    raise ValueError(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class ReviewedV2Proposal:
    """只读审核视图：引用现有 owner truth，不承载新的业务授权。"""

    frozen: FrozenSubmissionV2
    view: ProductTaskQueryViewV2
    pause_id: str
    subject: CrossHostOperationProposalSubjectV2


def _require_v2_query(view: object, frozen: FrozenSubmissionV2) -> None:
    """核对 MCP GET/submit 的 V2 版本、request 身份与等待状态。"""

    if not isinstance(view, ProductTaskQueryViewV2):
        _fail("LIVE_V2_REQUEST_LINEAGE_INVALID", "MCP must return V2 query view")
    request = frozen.request
    if view.task_id != request.task_id or view.request_hash != request.request_hash:
        _fail("LIVE_V2_REQUEST_LINEAGE_INVALID", "MCP returned another request")
    if (
        view.state is not ProductTaskQueryState.WORKFLOW
        or view.status is not ProductTaskV2Status.WAITING
        or view.proposal_state is not ProductProposalStateV2.AWAITING
        or view.saga_id is not None
        or view.materializations
    ):
        _fail("LIVE_V2_QUERY_NOT_PENDING", "V2 query is not awaiting human proposal")


def _validate_subject(
    *,
    subject: object,
    frozen: FrozenSubmissionV2,
    pending,
) -> CrossHostOperationProposalSubjectV2:
    """将 immutable subject 精确关联冻结的请求、拓扑、语义环境和双端 READ。"""

    if not isinstance(subject, CrossHostOperationProposalSubjectV2):
        _fail("LIVE_V2_SUBJECT_LINEAGE_INVALID", "wrong artifact type")
    request = frozen.request
    binding = frozen.session_binding
    if (
        subject.request_hash != request.request_hash
        or subject.session_binding_hash != binding.binding_hash
        or subject.topology_snapshot_hash != binding.topology_snapshot_hash
        or subject.semantic_target_id != binding.semantic_target_id
        or subject.semantic_environment_id != binding.semantic_environment_id
        or subject.semantic_environment_hash != binding.semantic_environment_hash
        or subject.canonical_operation != "set_wall_thickness.v1"
    ):
        _fail("LIVE_V2_SUBJECT_LINEAGE_INVALID", "proposal authority identity differs")
    arguments = subject.canonical_arguments_body()
    frozen_thickness = request.intent_arguments.get("thickness")
    if (
        not isinstance(frozen_thickness, Mapping)
        or arguments != {
            "targets": [binding.semantic_target_id],
            "thickness": {
                "unit": frozen_thickness.get("unit"),
                "value": frozen_thickness.get("value"),
            },
        }
    ):
        _fail("LIVE_V2_SUBJECT_LINEAGE_INVALID", "model intent differs from proposal")
    by_host = {obs.host_kind: obs for obs in subject.observations}
    if set(by_host) != {"AUTOCAD", "REVIT"}:
        _fail("LIVE_V2_SUBJECT_LINEAGE_INVALID", "required two-host observation missing")
    for member in binding.members:
        observation = by_host[member.host_kind]
        if (
            observation.host_instance_id != member.host_instance_id
            or observation.document_id != member.document_id
            or observation.native_target_id != member.native_target_id
            or observation.semantic_target_id != binding.semantic_target_id
            or observation.normalized_thickness_mm != 200.0
        ):
            _fail(
                "LIVE_V2_SUBJECT_LINEAGE_INVALID",
                "Host observation does not equal reviewed 200 mm baseline",
            )
    reference_hash = pending.subject_ref.content_hash
    if (
        reference_hash is None
        or workflow_artifact_content_hash(subject) != reference_hash
    ):
        _fail(
            "LIVE_V2_SUBJECT_INTEGRITY_INVALID",
            "proposal artifact content hash differs from exact checkpoint ref",
        )
    return subject


async def prepare_and_read_v2_proposal(
    *,
    submission_controller: object,
    mcp_client: object,
    checkpoint_reader: object,
    artifact_reader: object,
    client_submission_ref: str,
    utterance: str,
) -> ReviewedV2Proposal:
    """经生产 V2 freeze/MCP submit 后读取 authoritative pause，不执行任何 resume。

    Controller 负责真实模型与双 Host context read，MCP 客户端负责提交和
    exact-task GET；checkpoint 和 subject 必须由现有 owner 按确定引用读取。
    """

    prepare = getattr(submission_controller, "prepare_cross_host_submission", None)
    submit = getattr(mcp_client, "submit", None)
    get = getattr(mcp_client, "get", None)
    get_checkpoint = getattr(checkpoint_reader, "get_checkpoint", None)
    read_artifact = getattr(artifact_reader, "get", None)
    if not all(callable(fn) for fn in (prepare, submit, get, get_checkpoint, read_artifact)):
        _fail("LIVE_V2_WIRING_INVALID", "production V2 seams are missing")

    frozen = prepare(
        client_submission_ref=client_submission_ref,
        utterance=utterance,
    )
    if isinstance(frozen, AgentClarificationRequired):
        _fail("LIVE_V2_MODEL_CLARIFICATION_REQUIRED", "model has not frozen V2 request")
    if not isinstance(frozen, FrozenSubmissionV2):
        _fail("LIVE_V2_WIRING_INVALID", "V2 controller did not freeze request")
    if (
        frozen.client_submission_ref != client_submission_ref
        or frozen.utterance != utterance
        or frozen.request.session_ref != frozen.session_binding.session_ref
        or frozen.request.session_binding_hash != frozen.session_binding.binding_hash
    ):
        _fail("LIVE_V2_REQUEST_LINEAGE_INVALID", "client frozen winner differs")

    # MCP 的 V2 工具路径不会携带完整 binding body；服务端独立查 session/accepted owner。
    first_view = await submit(frozen.request)
    _require_v2_query(first_view, frozen)
    queried_view = await get(frozen.request.task_id)
    _require_v2_query(queried_view, frozen)
    if queried_view != first_view:
        _fail("LIVE_V2_QUERY_NOT_PENDING", "durable GET changed after submit")

    checkpoint = get_checkpoint(frozen.request.task_id)
    if (
        not isinstance(checkpoint, WorkflowCheckpointView)
        or checkpoint.task_id != frozen.request.task_id
        or checkpoint.phase is not WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        or checkpoint.pending_interaction is None
        or checkpoint.pending_interaction.kind is not PendingInteractionKind.OPERATION_PROPOSAL
    ):
        _fail("LIVE_V2_CHECKPOINT_INVALID", "exact durable pending checkpoint missing")
    pending = checkpoint.pending_interaction
    if set(pending.allowed_resume_kinds) != {
        "OPERATION_PROPOSAL_ACCEPTED",
        "OPERATION_PROPOSAL_REJECTED",
    }:
        _fail("LIVE_V2_CHECKPOINT_INVALID", "pending resume kinds differ")

    # 只按 checkpoint 的 exact StableRef 读取 subject，禁止按 task/latest 反查 artifact。
    subject = _validate_subject(
        subject=read_artifact(pending.subject_ref),
        frozen=frozen,
        pending=pending,
    )
    return ReviewedV2Proposal(
        frozen=frozen,
        view=queried_view,
        pause_id=pending.pause_id,
        subject=subject,
    )


__all__ = ["ReviewedV2Proposal", "prepare_and_read_v2_proposal"]
