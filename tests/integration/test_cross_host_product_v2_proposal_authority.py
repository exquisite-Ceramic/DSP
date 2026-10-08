"""Task 16A：V2 模型冻结→MCP submit→exact proposal 的只读关联契约。

所有替身只模拟外部 I/O；主体 DTO、哈希与 checkpoint contract 均来自生产代码。
本测试绝不触发真正的 AutoCAD / Revit mutation 或自动人工批准。
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_front_door.sqlite_state import FrozenSubmissionV2
from design_product_runtime import (
    ProductProposalStateV2,
    ProductTaskQueryState,
    ProductTaskQueryViewV2,
    ProductTaskRequestV2,
    ProductTaskV2Status,
)

from tests.product_front_door.test_cross_host_gate_a import _binding


def _case():
    """构造与现有 V2 SessionBinding 契约一致的一组只读 owner 快照。"""

    binding = _binding()
    request = ProductTaskRequestV2.create(
        task_id="task-task16a-proposal",
        project_id=binding.project_id,
        initiating_host_kind=binding.initiating_host_kind,
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    frozen = FrozenSubmissionV2(
        client_submission_ref="submission-task16a",
        utterance="把两端墙厚同步改到300毫米",
        proposal_hash="9" * 64,
        reviewed_configuration_hash="8" * 64,
        session_binding=binding,
        request=request,
        delivery_state="PENDING",
    )
    subject = CrossHostOperationProposalSubjectV2(
        request_hash=request.request_hash,
        session_binding_hash=binding.binding_hash,
        topology_snapshot_hash=binding.topology_snapshot_hash,
        semantic_target_id=binding.semantic_target_id,
        semantic_environment_id=binding.semantic_environment_id,
        semantic_environment_hash=binding.semantic_environment_hash,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "targets": [binding.semantic_target_id],
            "thickness": {"value": 300.0, "unit": "mm"},
        },
        observations=tuple(
            CrossHostProposalObservationV2(
                host_kind=member.host_kind,
                host_instance_id=member.host_instance_id,
                document_id=member.document_id,
                native_target_id=member.native_target_id,
                semantic_target_id=binding.semantic_target_id,
                host_revision=0,
                normalized_thickness_mm=200.0,
                observed_at="2026-10-08T10:00:00Z",
                command_id=f"live-read-{member.host_kind.lower()}",
            )
            for member in binding.members
        ),
    )
    reference = StableRef(
        ref_id="proposal-task16a",
        content_hash=workflow_artifact_content_hash(subject),
    )
    checkpoint = WorkflowCheckpointView(
        task_id=request.task_id,
        phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
        pending_interaction=PendingInteractionView(
            pause_id="pause-task16a",
            kind=PendingInteractionKind.OPERATION_PROPOSAL,
            subject_ref=reference,
            allowed_resume_kinds=(
                "OPERATION_PROPOSAL_ACCEPTED",
                "OPERATION_PROPOSAL_REJECTED",
            ),
        ),
    )
    view = ProductTaskQueryViewV2(
        version="V2",
        task_id=request.task_id,
        request_hash=request.request_hash,
        state=ProductTaskQueryState.WORKFLOW,
        status=ProductTaskV2Status.WAITING,
        proposal_state=ProductProposalStateV2.AWAITING,
        saga_id=None,
        convergence_result_hash=None,
        materializations=(),
    )
    return frozen, view, checkpoint, subject


class _Controller:
    """只记录准备阶段由生产 V2 controller 应执行的调用，不调用真实模型。"""

    def __init__(self, frozen) -> None:
        self.frozen = frozen
        self.calls = []

    def prepare_cross_host_submission(self, *, client_submission_ref, utterance):
        """返回受测案例预先建立的真正 FrozenSubmissionV2。"""

        self.calls.append((client_submission_ref, utterance))
        return self.frozen


class _Mcp:
    """只记录 MCP submit/get；若代码尝试自动 resume 则立即抛错。"""

    def __init__(self, view) -> None:
        self.view = view
        self.calls = []

    async def submit(self, request):
        """记录冻结 request 是否以原样穿透 transport。"""

        self.calls.append(("submit", request))
        return self.view

    async def get(self, task_id):
        """按 exact task 查询已提交状态，不提供 latest fallback。"""

        self.calls.append(("get", task_id))
        return self.view

    async def resume_operation_proposal(self, **kwargs):
        """受控模型/MCP proposal gate 不得自行执行人工决定。"""

        raise AssertionError(f"AUTO_RESUME_FORBIDDEN: {kwargs}")


class _CheckpointReader:
    """模拟已有 PostgreSQL checkpoint 的按 task 精确读取。"""

    def __init__(self, checkpoint) -> None:
        self.checkpoint = checkpoint
        self.lookups = []

    def get_checkpoint(self, task_id):
        """保存一次 exact task lookup 的证据。"""

        self.lookups.append(task_id)
        return self.checkpoint


class _ArtifactReader:
    """模拟现有 Workflow Artifact Store 的 exact ref 读取。"""

    def __init__(self, subject) -> None:
        self.subject = subject
        self.lookups = []

    def get(self, ref):
        """记录使用了 checkpoint subject_ref 而不是按 task 猜测 latest artifact。"""

        self.lookups.append(ref)
        return self.subject


@pytest.mark.asyncio
async def test_v2_proposal_uses_real_dto_and_durable_exact_pause_without_resume():
    """成功只允许返回人工审核所需 immutable subject，不产生任何 grant/mutation。"""

    from tests.integration.cross_host_product_v2_proposal_authority import (
        prepare_and_read_v2_proposal,
    )

    frozen, view, checkpoint, subject = _case()
    controller = _Controller(frozen)
    mcp = _Mcp(view)
    checkpoints = _CheckpointReader(checkpoint)
    artifacts = _ArtifactReader(subject)

    result = await prepare_and_read_v2_proposal(
        submission_controller=controller,
        mcp_client=mcp,
        checkpoint_reader=checkpoints,
        artifact_reader=artifacts,
        client_submission_ref=frozen.client_submission_ref,
        utterance=frozen.utterance,
    )
    assert result.frozen == frozen
    assert result.view == view
    assert result.pause_id == "pause-task16a"
    assert result.subject == subject
    assert controller.calls == [(frozen.client_submission_ref, frozen.utterance)]
    assert mcp.calls == [("submit", frozen.request), ("get", frozen.request.task_id)]
    assert checkpoints.lookups == [frozen.request.task_id]
    assert artifacts.lookups == [checkpoint.pending_interaction.subject_ref]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("wrong_view_hash", "LIVE_V2_REQUEST_LINEAGE_INVALID"),
        ("wrong_checkpoint_task", "LIVE_V2_CHECKPOINT_INVALID"),
        ("not_pending", "LIVE_V2_CHECKPOINT_INVALID"),
        ("wrong_subject_binding", "LIVE_V2_SUBJECT_LINEAGE_INVALID"),
        ("wrong_subject_value", "LIVE_V2_SUBJECT_LINEAGE_INVALID"),
        ("stale_query", "LIVE_V2_QUERY_NOT_PENDING"),
        ("wrong_subject_hash", "LIVE_V2_SUBJECT_INTEGRITY_INVALID"),
    ],
)
async def test_v2_proposal_refuses_wrong_authority_before_any_human_resume(
    damage, expected
):
    """任何旧版本、漂移或伪造 evidence 必须立即失败，绝不可触发 resume。"""

    from tests.integration.cross_host_product_v2_proposal_authority import (
        prepare_and_read_v2_proposal,
    )

    frozen, view, checkpoint, subject = _case()
    if damage == "wrong_view_hash":
        view = replace(view, request_hash="f" * 64)
    elif damage == "wrong_checkpoint_task":
        checkpoint = replace(checkpoint, task_id="other-task")
    elif damage == "not_pending":
        checkpoint = replace(
            checkpoint,
            phase=WorkflowPhase.PARAMETER_BINDING,
            pending_interaction=None,
        )
    elif damage == "wrong_subject_binding":
        subject = replace(subject, session_binding_hash="f" * 64)
    elif damage == "wrong_subject_value":
        subject = replace(
            subject,
            observations=(
                replace(subject.observations[0], normalized_thickness_mm=201.0),
                subject.observations[1],
            ),
        )
    elif damage == "stale_query":
        view = replace(view, status=ProductTaskV2Status.STALE)
    elif damage == "wrong_subject_hash":
        checkpoint = replace(
            checkpoint,
            pending_interaction=replace(
                checkpoint.pending_interaction,
                subject_ref=StableRef(ref_id="proposal-task16a", content_hash="e" * 64),
            ),
        )

    with pytest.raises(ValueError, match=expected):
        await prepare_and_read_v2_proposal(
            submission_controller=_Controller(frozen),
            mcp_client=_Mcp(view),
            checkpoint_reader=_CheckpointReader(checkpoint),
            artifact_reader=_ArtifactReader(subject),
            client_submission_ref=frozen.client_submission_ref,
            utterance=frozen.utterance,
        )


class _ResumeMcp(_Mcp):
    """用真实 V2 Query DTO 模拟一次显式恢复，防止测试碰真实 Host。"""

    def __init__(self, before, after):
        """保留 resume 前后的 owner 投影及所有发送操作。"""

        super().__init__(before)
        self.after = after
        self.resumed = False

    async def get(self, task_id):
        """resume 前返回 pending，resume 后返回同一 task 最新 durable query。"""

        self.calls.append(("get", task_id))
        return self.after if self.resumed else self.view

    async def resume_operation_proposal(self, **kwargs):
        """只模拟 transport 返回值，不生成任何实际 Host mutation。"""

        self.calls.append(("resume", kwargs))
        self.resumed = True
        return self.after


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision_kind", "status", "proposal_state"),
    [
        (
            "OPERATION_PROPOSAL_ACCEPTED",
            ProductTaskV2Status.WAITING,
            ProductProposalStateV2.ACCEPTED,
        ),
        (
            "OPERATION_PROPOSAL_REJECTED",
            ProductTaskV2Status.CANCELLED,
            ProductProposalStateV2.REJECTED,
        ),
    ],
)
async def test_v2_manual_resume_requires_exact_explicit_review_and_rechecks_owner(
    decision_kind, status, proposal_state
):
    """仅显式决定且二次 authoritative READ 全一致才可调用一次 MCP resume。"""

    from tests.integration.cross_host_product_v2_proposal_authority import (
        ReviewedV2Proposal,
    )
    from tests.integration.cross_host_product_v2_manual_resume import (
        ExplicitHumanDecisionV2,
        resume_reviewed_v2_proposal,
    )

    frozen, view, checkpoint, subject = _case()
    after = replace(view, status=status, proposal_state=proposal_state)
    mcp = _ResumeMcp(view, after)
    checkpoints = _CheckpointReader(checkpoint)
    artifacts = _ArtifactReader(subject)
    reviewed = ReviewedV2Proposal(
        frozen=frozen,
        view=view,
        pause_id=checkpoint.pending_interaction.pause_id,
        subject=subject,
    )
    directive = ExplicitHumanDecisionV2(
        task_id=frozen.request.task_id,
        request_hash=frozen.request.request_hash,
        session_binding_hash=frozen.session_binding.binding_hash,
        pause_id=reviewed.pause_id,
        subject_content_hash=checkpoint.pending_interaction.subject_ref.content_hash,
        resume_kind=decision_kind,
    )

    result = await resume_reviewed_v2_proposal(
        reviewed=reviewed,
        human_decision=directive,
        mcp_client=mcp,
        checkpoint_reader=checkpoints,
        artifact_reader=artifacts,
    )

    assert result is after
    assert checkpoints.lookups == [frozen.request.task_id]
    assert artifacts.lookups == [checkpoint.pending_interaction.subject_ref]
    assert mcp.calls == [
        ("get", frozen.request.task_id),
        (
            "resume",
            {
                "task_id": frozen.request.task_id,
                "pause_id": reviewed.pause_id,
                "resume_kind": decision_kind,
            },
        ),
        ("get", frozen.request.task_id),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("decision_wrong_task", "LIVE_HUMAN_DECISION_LINEAGE_INVALID"),
        ("decision_wrong_request", "LIVE_HUMAN_DECISION_LINEAGE_INVALID"),
        ("decision_wrong_binding", "LIVE_HUMAN_DECISION_LINEAGE_INVALID"),
        ("decision_wrong_pause", "LIVE_HUMAN_DECISION_LINEAGE_INVALID"),
        ("decision_wrong_subject", "LIVE_HUMAN_DECISION_LINEAGE_INVALID"),
        ("changed_pause", "LIVE_HUMAN_DECISION_STALE"),
        ("changed_subject", "LIVE_HUMAN_DECISION_STALE"),
        ("changed_query", "LIVE_HUMAN_DECISION_STALE"),
        ("changed_artifact", "LIVE_V2_SUBJECT_INTEGRITY_INVALID"),
        ("unexpected_decision_kind", "LIVE_HUMAN_DECISION_INVALID"),
    ],
)
async def test_v2_manual_resume_fails_closed_without_any_mutation_on_stale_review(
    damage, code
):
    """明确人工决定仍不足以越过 stale authority，失败不得调用 resume。"""

    from tests.integration.cross_host_product_v2_proposal_authority import (
        ReviewedV2Proposal,
    )
    from tests.integration.cross_host_product_v2_manual_resume import (
        ExplicitHumanDecisionV2,
        resume_reviewed_v2_proposal,
    )

    frozen, view, checkpoint, subject = _case()
    pending = checkpoint.pending_interaction
    directive_fields = {
        "task_id": frozen.request.task_id,
        "request_hash": frozen.request.request_hash,
        "session_binding_hash": frozen.session_binding.binding_hash,
        "pause_id": pending.pause_id,
        "subject_content_hash": pending.subject_ref.content_hash,
        "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
    }
    if damage.startswith("decision_wrong_"):
        field_name = {
            "decision_wrong_task": "task_id",
            "decision_wrong_request": "request_hash",
            "decision_wrong_binding": "session_binding_hash",
            "decision_wrong_pause": "pause_id",
            "decision_wrong_subject": "subject_content_hash",
        }[damage]
        directive_fields[field_name] = "f" * 64 if "hash" in field_name or field_name == "subject_content_hash" else "other-id"
    if damage == "unexpected_decision_kind":
        directive_fields["resume_kind"] = "AUTO_APPROVE"
    if damage == "changed_pause":
        checkpoint = replace(
            checkpoint,
            pending_interaction=replace(pending, pause_id="another-pause"),
        )
    if damage == "changed_subject":
        checkpoint = replace(
            checkpoint,
            pending_interaction=replace(
                pending,
                subject_ref=StableRef("another-subject", pending.subject_ref.content_hash),
            ),
        )
    if damage == "changed_query":
        view_current = replace(view, status=ProductTaskV2Status.STALE)
    else:
        view_current = view
    if damage == "changed_artifact":
        subject_current = replace(
            subject,
            observations=(
                replace(subject.observations[0], normalized_thickness_mm=201.0),
                subject.observations[1],
            ),
        )
    else:
        subject_current = subject

    mcp = _ResumeMcp(view_current, view_current)
    reviewed = ReviewedV2Proposal(
        frozen=frozen,
        view=view,
        pause_id=pending.pause_id,
        subject=subject,
    )
    with pytest.raises(ValueError, match=code):
        await resume_reviewed_v2_proposal(
            reviewed=reviewed,
            human_decision=ExplicitHumanDecisionV2(**directive_fields),
            mcp_client=mcp,
            checkpoint_reader=_CheckpointReader(checkpoint),
            artifact_reader=_ArtifactReader(subject_current),
        )
    assert all(method != "resume" for method, _ in mcp.calls)


@pytest.mark.asyncio
async def test_v2_manual_resume_missing_human_decision_fails_before_mcp_get():
    """人工决定缺失时即使已审核 proposal 也绝不能自动推进。"""

    from tests.integration.cross_host_product_v2_proposal_authority import (
        ReviewedV2Proposal,
    )
    from tests.integration.cross_host_product_v2_manual_resume import (
        resume_reviewed_v2_proposal,
    )

    frozen, view, checkpoint, subject = _case()
    mcp = _ResumeMcp(view, view)
    reviewed = ReviewedV2Proposal(
        frozen=frozen,
        view=view,
        pause_id=checkpoint.pending_interaction.pause_id,
        subject=subject,
    )
    with pytest.raises(ValueError, match="LIVE_HUMAN_DECISION_REQUIRED"):
        await resume_reviewed_v2_proposal(
            reviewed=reviewed,
            human_decision=None,
            mcp_client=mcp,
            checkpoint_reader=_CheckpointReader(checkpoint),
            artifact_reader=_ArtifactReader(subject),
        )
    assert mcp.calls == []
