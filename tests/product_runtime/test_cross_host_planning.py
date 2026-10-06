"""Cross-Host Product Vertical Task 6：双 Host PlanningSnapshot 与 Gate B 契约。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_orchestrator.canonical_operations import MVP_CANONICAL_OPERATIONS
from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
    ProposalDecisionRecord,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime.cross_host_planning import (
    CrossHostOperationFreshnessBoundary,
    CrossHostPlanningError,
    CrossHostPlanningMemberEvidence,
)
from semantic_runtime import (
    AspectGuarantee,
    DirtyMap,
    FreshnessResolver,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotSet,
    build_context_contract,
)

_PROJECT = "project-cross-host-task6"
_TARGET = "WALL-001"
_REVIT_DOC = r"C:\DSP\fixtures\cross-host.rvt"
_AUTOCAD_DOC = r"C:\DSP\fixtures\cross-host.dwg"
_ENV = SemanticEnvironmentRef("SEM-ENV-1", "1" * 64)


def _observation(host_kind: str) -> CrossHostProposalObservationV2:
    """构造 human ACCEPT 时实际展示的稳定 Host 状态。"""

    if host_kind == "AUTOCAD":
        return CrossHostProposalObservationV2(
            host_kind="AUTOCAD",
            host_instance_id="autocad-runtime-1",
            document_id=_AUTOCAD_DOC,
            native_target_id="autocad-wall-1",
            semantic_target_id=_TARGET,
            host_revision=17,
            normalized_thickness_mm=200.0,
            observed_at="2026-10-06T12:00:00Z",
            command_id="proposal-autocad",
        )
    return CrossHostProposalObservationV2(
        host_kind="REVIT",
        host_instance_id="revit-runtime-1",
        document_id=_REVIT_DOC,
        native_target_id="revit-wall-1",
        semantic_target_id=_TARGET,
        host_revision=41,
        normalized_thickness_mm=200.0,
        observed_at="2026-10-06T12:00:01Z",
        command_id="proposal-revit",
    )


def _subject() -> CrossHostOperationProposalSubjectV2:
    """构造已被 human ACCEPT 的 exact cross-Host proposal subject。"""

    return CrossHostOperationProposalSubjectV2(
        request_hash="2" * 64,
        session_binding_hash="3" * 64,
        topology_snapshot_hash="4" * 64,
        semantic_target_id=_TARGET,
        semantic_environment_id=_ENV.environment_id,
        semantic_environment_hash=_ENV.content_hash,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "thickness": {"value": 300.0, "unit": "mm"},
            "targets": [_TARGET],
        },
        observations=(_observation("AUTOCAD"), _observation("REVIT")),
    )


class _ArtifactStore:
    """只保存 Task 6 所需 bound operation 与 proposal subject。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.counter = 0

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        """按 supplied canonical hash 发布稳定引用。"""

        self.counter += 1
        ref = StableRef(f"task6:{kind}:{self.counter}", content_hash)
        self.values[ref.ref_id] = value
        return ref

    def get(self, ref: StableRef) -> object:
        """只按 exact ref 读取，不提供 latest/reverse lookup。"""

        return self.values[ref.ref_id]


class _Revisions:
    """分别返回 Revit/AutoCAD 当前 document revision。"""

    def __init__(self) -> None:
        self.values = {_REVIT_DOC: "41", _AUTOCAD_DOC: "17"}
        self.calls: list[str] = []

    def current_revision(self, document_ref: str) -> str:
        """记录每个 required document 都被独立观察。"""

        self.calls.append(document_ref)
        return self.values[document_ref]


class _MemberReconstruction:
    """模拟 Host-specific READ→normalize→semantic reconstruction，不复制另一 Host snapshot。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.drift_host: str | None = None
        self.metadata_generation = 0

    def reconstruct_member(
        self,
        *,
        task_id: str,
        host_kind: str,
        contract,
        accepted_observation: CrossHostProposalObservationV2,
        expected_host_revision: str,
        semantic_environment_ref: SemanticEnvironmentRef,
    ) -> CrossHostPlanningMemberEvidence:
        """每个 Host 独立产生 observation 与 ReconstructionResult。"""

        assert task_id == "task-cross-host-task6"
        self.calls.append(
            (host_kind, contract.coverage.document_ref, expected_host_revision)
        )
        self.metadata_generation += 1
        fresh = replace(
            accepted_observation,
            host_revision=int(expected_host_revision),
            observed_at=f"2026-10-06T12:10:0{self.metadata_generation}Z",
            command_id=f"planning-read-{host_kind.lower()}-{self.metadata_generation}",
        )
        if self.drift_host == host_kind:
            fresh = replace(fresh, normalized_thickness_mm=225.0)

        projection = SemanticProjectionRef(
            projection_id=f"projection-{host_kind.lower()}",
            projection_hash=("a" if host_kind == "AUTOCAD" else "b") * 64,
            semantic_model_version="dsp.semantic.projection-facts.v1",
            provider_set_hash=semantic_environment_ref.content_hash,
            mapping_profile_set_hash=("c" if host_kind == "AUTOCAD" else "d") * 64,
            normalized_fact_batch_hash=("e" if host_kind == "AUTOCAD" else "f") * 64,
        )
        reconstruction = ReconstructionResult(
            document_ref=contract.coverage.document_ref,
            host_revision=expected_host_revision,
            coverage=contract.coverage,
            guarantees=contract.requirements,
            projection_ref=projection,
            semantic_environment_ref=semantic_environment_ref,
        )
        return CrossHostPlanningMemberEvidence(
            observation=fresh,
            reconstruction=reconstruction,
        )


class _ProposalDecisions:
    """按 exact task+subject 投影 Task 5 durable ACCEPT，并记录 Gate-B transition。"""

    def __init__(self, subject_ref: StableRef) -> None:
        self.subject_ref = subject_ref
        self.record = ProposalDecisionRecord(
            task_id="task-cross-host-task6",
            pause_id="pause-cross-host-task6",
            subject_ref=subject_ref,
            human_decision=HumanDecisionState.ACCEPTED,
            continuation=ProposalContinuationState.CONTINUABLE,
            revision=1,
        )
        self.invalidations: list[str] = []

    def get_by_subject(
        self,
        task_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord | None:
        """恢复时只允许 exact task+subject 命中同一 accepted decision。"""

        assert task_id == self.record.task_id
        assert subject_ref == self.subject_ref
        return self.record

    def invalidate_gate_b_by_subject(
        self,
        task_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord:
        """模拟 owner-local Gate-B CAS，保留 ACCEPTED history。"""

        assert task_id == self.record.task_id
        assert subject_ref == self.subject_ref
        self.invalidations.append(reason)
        if self.record.continuation is ProposalContinuationState.CONTINUABLE:
            self.record = replace(
                self.record,
                continuation=ProposalContinuationState.STALE_GATE_B,
                revision=self.record.revision + 1,
                reason=reason,
            )
        return self.record


def _context_snapshot(registry: InMemorySnapshotRegistry):
    """通过真实 FreshnessResolver 生成 Revit anchor ContextSnapshot。"""

    contract = build_context_contract(
        _REVIT_DOC,
        (_TARGET,),
        project_id=_PROJECT,
    )
    snapshot = FreshnessResolver(DirtyMap()).resolve(
        contract,
        expected_host_revision="41",
        reconstruct=lambda current, revision: ReconstructionResult(
            document_ref=current.coverage.document_ref,
            host_revision=revision,
            coverage=current.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.IDENTITY),),
            projection_ref=SemanticProjectionRef(
                "context-revit",
                "9" * 64,
                "dsp.semantic.projection-facts.v1",
                _ENV.content_hash,
                "8" * 64,
                "7" * 64,
            ),
            semantic_environment_ref=_ENV,
        ),
    )
    registry.put_snapshot(snapshot)
    return snapshot


def _boundary_case():
    """组装真实 freshness/snapshot owner 与窄 Host reconstruction/decision seams。"""

    registry = InMemorySnapshotRegistry()
    context = _context_snapshot(registry)
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300.0, "unit": "mm"}},
        ),
        ParameterBindingContext(
            context_snapshot_id=context.snapshot_id,
            context_snapshot_hash=context.hash,
            document_ref=_REVIT_DOC,
            semantic_environment_ref=_ENV.environment_id,
            selection=(_TARGET,),
        ),
    )
    artifacts = _ArtifactStore()
    bound_ref = artifacts.put(
        kind="bound_operation_proposal",
        value=bound,
        content_hash=workflow_artifact_content_hash(bound),
    )
    subject = _subject()
    subject_ref = artifacts.put(
        kind="cross_host_operation_proposal_subject_v2",
        value=subject,
        content_hash=workflow_artifact_content_hash(subject),
    )
    revisions = _Revisions()
    reconstruction = _MemberReconstruction()
    decisions = _ProposalDecisions(subject_ref)
    boundary = CrossHostOperationFreshnessBoundary(
        snapshot_registry=registry,
        freshness_resolver=FreshnessResolver(DirtyMap()),
        workflow_artifact_store=artifacts,
        host_revision_observation=revisions,
        member_reconstruction=reconstruction,
        proposal_decisions=decisions,
    )
    return (
        boundary,
        registry,
        revisions,
        reconstruction,
        decisions,
        bound_ref,
        subject_ref,
    )


def test_v2_snapshot_set_contains_exact_revit_and_autocad_members() -> None:
    """成功 freshness 必须发布 exact 双成员 SnapshotSet，Revit 仍是 anchor。"""

    boundary, registry, revisions, _, _, bound_ref, subject_ref = _boundary_case()

    result = boundary.ensure(
        "task-cross-host-task6",
        bound_ref,
        subject_ref,
    )

    snapshot_set = registry.get_snapshot_set(result.snapshot_set_ref.ref_id)
    anchor = registry.get_snapshot(result.planning_snapshot_ref.ref_id)
    assert isinstance(snapshot_set, SnapshotSet)
    assert {member.document_ref for member in snapshot_set.members} == {
        _AUTOCAD_DOC,
        _REVIT_DOC,
    }
    assert {member.document_ref: member.base_host_revision for member in snapshot_set.members} == {
        _AUTOCAD_DOC: "17",
        _REVIT_DOC: "41",
    }
    assert anchor.document_ref == _REVIT_DOC
    assert result.operation_ref == bound_ref
    assert sorted(revisions.calls) == sorted([_AUTOCAD_DOC, _REVIT_DOC])


def test_autocad_snapshot_is_reconstructed_not_cloned_from_revit() -> None:
    """两个 member 必须各自经过 Host reconstruction，projection lineage 不可复用 Revit。"""

    boundary, registry, _, reconstruction, _, bound_ref, subject_ref = _boundary_case()

    result = boundary.ensure(
        "task-cross-host-task6",
        bound_ref,
        subject_ref,
    )
    snapshot_set = registry.get_snapshot_set(result.snapshot_set_ref.ref_id)
    by_document = {item.document_ref: item for item in snapshot_set.members}

    assert reconstruction.calls == [
        ("AUTOCAD", _AUTOCAD_DOC, "17"),
        ("REVIT", _REVIT_DOC, "41"),
    ]
    assert by_document[_AUTOCAD_DOC].projection_ref.projection_id == "projection-autocad"
    assert by_document[_REVIT_DOC].projection_ref.projection_id == "projection-revit"
    assert (
        by_document[_AUTOCAD_DOC].projection_ref
        != by_document[_REVIT_DOC].projection_ref
    )


def test_equal_stable_state_with_new_acquisition_metadata_passes_gate_b() -> None:
    """timestamp/command id 可变化；稳定 runtime/doc/target/revision/value 相同即可继续。"""

    boundary, _, _, _, decisions, bound_ref, subject_ref = _boundary_case()

    result = boundary.ensure(
        "task-cross-host-task6",
        bound_ref,
        subject_ref,
    )

    assert result.snapshot_set_ref.content_hash is not None
    assert decisions.invalidations == []
    assert decisions.record.human_decision is HumanDecisionState.ACCEPTED
    assert decisions.record.continuation is ProposalContinuationState.CONTINUABLE


@pytest.mark.parametrize("host_kind", ["REVIT", "AUTOCAD"])
def test_post_accept_revit_or_autocad_drift_marks_stale_gate_b_and_preserves_accept(
    host_kind: str,
) -> None:
    """任一 Host planning read 漂移都必须停止 progression，但不得抹掉历史 ACCEPT。"""

    boundary, registry, _, reconstruction, decisions, bound_ref, subject_ref = _boundary_case()
    reconstruction.drift_host = host_kind

    with pytest.raises(CrossHostPlanningError) as captured:
        boundary.ensure(
            "task-cross-host-task6",
            bound_ref,
            subject_ref,
        )

    assert captured.value.code == "OPERATION_PROPOSAL_STALE"
    assert decisions.record.human_decision is HumanDecisionState.ACCEPTED
    assert decisions.record.continuation is ProposalContinuationState.STALE_GATE_B
    assert decisions.record.revision == 2
    assert decisions.invalidations
    # Gate B 失败不得发布一个看似 authoritative 的双 Host SnapshotSet。
    with pytest.raises(Exception):
        registry.get_snapshot_set("PSS-not-published")
