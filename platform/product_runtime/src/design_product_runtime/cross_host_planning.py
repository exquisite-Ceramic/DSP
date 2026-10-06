"""Cross-Host Product Vertical 的双 Host operation freshness 与 Gate B。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.parameter_binder import BoundOperationProposal
from design_orchestrator.proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
    ProposalDecisionRecord,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationRef,
    OperationFreshnessResult,
    StableRef,
)
from semantic_runtime import (
    FreshnessContract,
    ReconstructionResult,
    SemanticEnvironmentRef,
    SnapshotSet,
    build_operation_contract,
    requirements_from_mappings,
)


class CrossHostPlanningError(RuntimeError):
    """Cross-Host planning continuity 无法安全继续时暴露稳定错误码。"""

    def __init__(self, code: str, detail: str) -> None:
        self.code = _required_text(code, "code")
        self.detail = _required_text(detail, "detail")
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True, slots=True)
class CrossHostPlanningMemberEvidence:
    """一次独立 Host planning READ/normalize/reconstruction 的瞬时结果。"""

    observation: CrossHostProposalObservationV2
    reconstruction: ReconstructionResult

    def __post_init__(self) -> None:
        if not isinstance(self.observation, CrossHostProposalObservationV2):
            raise TypeError("observation must be CrossHostProposalObservationV2")
        if not isinstance(self.reconstruction, ReconstructionResult):
            raise TypeError("reconstruction must be ReconstructionResult")


class CrossHostPlanningMemberReconstructionPort(Protocol):
    """每个 REQUIRED Host 独立获取 planning observation 与 semantic reconstruction。"""

    def reconstruct_member(
        self,
        *,
        task_id: str,
        host_kind: str,
        contract: FreshnessContract,
        accepted_observation: CrossHostProposalObservationV2,
        expected_host_revision: str,
        semantic_environment_ref: SemanticEnvironmentRef,
    ) -> CrossHostPlanningMemberEvidence | AsyncOperationRef: ...


class ProposalDecisionContinuationPort(Protocol):
    """按 exact task+subject 恢复 Task 5 decision，并执行 Gate-B continuation transition。"""

    def get_by_subject(
        self,
        task_id: str,
        subject_ref: StableRef,
    ) -> ProposalDecisionRecord | None: ...

    def invalidate_gate_b_by_subject(
        self,
        task_id: str,
        subject_ref: StableRef,
        reason: str,
    ) -> ProposalDecisionRecord: ...


def _required_text(value: object, field_name: str) -> str:
    """把 boundary locator 规范化为非空文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _normalize_json(value: object) -> object:
    """把 tuple/mapping 归一成 JSON 形状，用于比较 human subject 与 bound operation。"""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json(value[key])
            for key in sorted(value)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalize_json(item) for item in value]
    raise TypeError(f"unsupported planning JSON value: {type(value).__name__}")


class CrossHostOperationFreshnessBoundary:
    """把 accepted proposal 连续性与两个独立 PlanningSnapshot 组合成一个 owner result。"""

    def __init__(
        self,
        *,
        snapshot_registry: object,
        freshness_resolver: object,
        workflow_artifact_store: object,
        host_revision_observation: object,
        member_reconstruction: CrossHostPlanningMemberReconstructionPort,
        proposal_decisions: ProposalDecisionContinuationPort,
    ) -> None:
        """显式注入既有 authoritative owners；本 boundary 不保存可恢复私有 lineage。"""

        for value, method_name, field_name in (
            (snapshot_registry, "get_snapshot", "snapshot_registry"),
            (snapshot_registry, "put_snapshot", "snapshot_registry"),
            (snapshot_registry, "put_snapshot_set", "snapshot_registry"),
            (freshness_resolver, "resolve", "freshness_resolver"),
            (workflow_artifact_store, "get", "workflow_artifact_store"),
            (
                host_revision_observation,
                "current_revision",
                "host_revision_observation",
            ),
            (
                member_reconstruction,
                "reconstruct_member",
                "member_reconstruction",
            ),
            (proposal_decisions, "get_by_subject", "proposal_decisions"),
            (
                proposal_decisions,
                "invalidate_gate_b_by_subject",
                "proposal_decisions",
            ),
        ):
            if value is None or not callable(getattr(value, method_name, None)):
                raise TypeError(f"{field_name} must provide {method_name}")

        self._snapshot_registry = snapshot_registry
        self._freshness_resolver = freshness_resolver
        self._workflow_artifact_store = workflow_artifact_store
        self._host_revision_observation = host_revision_observation
        self._member_reconstruction = member_reconstruction
        self._proposal_decisions = proposal_decisions

    def ensure(
        self,
        task_id: str,
        operation_ref: StableRef,
        proposal_subject_ref: StableRef,
    ) -> OperationFreshnessResult | AsyncOperationRef:
        """独立重建两端状态，先过 Gate B，再原子发布双成员 SnapshotSet lineage。"""

        normalized_task_id = _required_text(task_id, "task_id")
        if not isinstance(operation_ref, StableRef):
            raise TypeError("operation_ref must be StableRef")
        if not isinstance(proposal_subject_ref, StableRef):
            raise TypeError("proposal_subject_ref must be StableRef")

        bound = self._workflow_artifact_store.get(operation_ref)
        if not isinstance(bound, BoundOperationProposal):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "operation_ref does not resolve to BoundOperationProposal",
            )
        subject = self._workflow_artifact_store.get(proposal_subject_ref)
        if not isinstance(subject, CrossHostOperationProposalSubjectV2):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "proposal_subject_ref does not resolve to V2 proposal subject",
            )

        decision = self._proposal_decisions.get_by_subject(
            normalized_task_id,
            proposal_subject_ref,
        )
        if (
            decision is None
            or decision.human_decision is not HumanDecisionState.ACCEPTED
            or decision.continuation is not ProposalContinuationState.CONTINUABLE
        ):
            raise CrossHostPlanningError(
                "OPERATION_PROPOSAL_STALE",
                "proposal decision is not ACCEPTED and CONTINUABLE",
            )

        context = self._snapshot_registry.get_snapshot(
            bound.context_snapshot_ref.context_snapshot_id
        )
        if context.hash != bound.context_snapshot_ref.context_snapshot_hash:
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "bound ContextSnapshot hash does not match Semantic Runtime truth",
            )

        environment = SemanticEnvironmentRef(
            subject.semantic_environment_id,
            subject.semantic_environment_hash,
        )
        if (
            context.semantic_environment_ref != environment
            or bound.semantic_environment_ref != environment.environment_id
        ):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "proposal SemanticEnvironment does not match bound operation context",
            )
        if subject.canonical_operation != bound.operation.canonical_operation:
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "proposal canonical operation does not match bound operation",
            )
        if _normalize_json(subject.canonical_arguments_body()) != _normalize_json(
            bound.arguments
        ):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "proposal canonical arguments do not match bound operation",
            )

        targets = self._bound_targets(bound)
        if targets != (subject.semantic_target_id,):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "proposal semantic target does not match bound operation targets",
            )
        requirement_mappings = (
            *bound.planning_requirements.operation_freshness_requirements,
            *bound.planning_requirements.coverage_requirements,
            *bound.planning_requirements.assurance_requirements,
        )
        requirements = requirements_from_mappings(requirement_mappings)

        reconstructed: list[
            tuple[
                str,
                FreshnessContract,
                str,
                CrossHostPlanningMemberEvidence,
            ]
        ] = []
        for accepted_observation in subject.observations:
            contract = build_operation_contract(
                project_id=context.project_id,
                document_ref=accepted_observation.document_id,
                canonical_operation=bound.operation.canonical_operation,
                targets=targets,
                arguments=dict(bound.arguments),
                requirements=requirements,
            )
            expected_revision = _required_text(
                self._host_revision_observation.current_revision(
                    accepted_observation.document_id
                ),
                "expected_host_revision",
            )
            evidence = self._member_reconstruction.reconstruct_member(
                task_id=normalized_task_id,
                host_kind=accepted_observation.host_kind,
                contract=contract,
                accepted_observation=accepted_observation,
                expected_host_revision=expected_revision,
                semantic_environment_ref=environment,
            )
            if isinstance(evidence, AsyncOperationRef):
                return evidence
            if not isinstance(evidence, CrossHostPlanningMemberEvidence):
                raise TypeError(
                    "member_reconstruction must return CrossHostPlanningMemberEvidence "
                    "or AsyncOperationRef"
                )
            if evidence.reconstruction.semantic_environment_ref != environment:
                raise CrossHostPlanningError(
                    "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                    "reconstructed member uses a different SemanticEnvironment",
                )
            if (
                evidence.observation.stable_state_body()
                != accepted_observation.stable_state_body()
            ):
                stale = self._proposal_decisions.invalidate_gate_b_by_subject(
                    normalized_task_id,
                    proposal_subject_ref,
                    f"{accepted_observation.host_kind}_PLANNING_CONTINUITY_DRIFT",
                )
                if stale.human_decision is not HumanDecisionState.ACCEPTED:
                    raise CrossHostPlanningError(
                        "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                        "Gate B transition erased historical ACCEPT",
                    )
                raise CrossHostPlanningError(
                    "OPERATION_PROPOSAL_STALE",
                    "planning state no longer matches the accepted proposal",
                )
            reconstructed.append(
                (
                    accepted_observation.host_kind,
                    contract,
                    expected_revision,
                    evidence,
                )
            )

        snapshots: list[tuple[str, object]] = []
        for host_kind, contract, expected_revision, evidence in reconstructed:
            snapshot = self._freshness_resolver.resolve(
                contract,
                expected_host_revision=expected_revision,
                reconstruct=lambda _contract, _revision, value=evidence: value.reconstruction,
            )
            if snapshot.semantic_environment_ref != environment:
                raise CrossHostPlanningError(
                    "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                    "PlanningSnapshot environment drifted from accepted proposal",
                )
            snapshots.append((host_kind, snapshot))

        if {host_kind for host_kind, _ in snapshots} != {"AUTOCAD", "REVIT"}:
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "planning requires exact AUTOCAD and REVIT members",
            )
        snapshot_set = SnapshotSet.create(snapshot for _, snapshot in snapshots)
        for _, snapshot in snapshots:
            self._snapshot_registry.put_snapshot(snapshot)
        self._snapshot_registry.put_snapshot_set(snapshot_set)

        revit = next(
            snapshot
            for host_kind, snapshot in snapshots
            if host_kind == "REVIT"
        )
        return OperationFreshnessResult(
            operation_ref=operation_ref,
            planning_snapshot_ref=StableRef(revit.snapshot_id, revit.hash),
            snapshot_set_ref=StableRef(
                snapshot_set.snapshot_set_id,
                snapshot_set.hash,
            ),
        )

    @staticmethod
    def _bound_targets(bound: BoundOperationProposal) -> tuple[str, ...]:
        """读取 binder 冻结的 canonical targets，不从 proposal reverse-resolve identity。"""

        raw_targets = bound.arguments.get("targets")
        if not isinstance(raw_targets, (tuple, list)):
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "bound operation requires canonical targets",
            )
        targets = tuple(
            str(item).strip()
            for item in raw_targets
            if str(item).strip()
        )
        if not targets:
            raise CrossHostPlanningError(
                "CROSS_HOST_PLANNING_LINEAGE_INVALID",
                "bound operation requires at least one canonical target",
            )
        return targets


__all__ = [
    "CrossHostOperationFreshnessBoundary",
    "CrossHostPlanningError",
    "CrossHostPlanningMemberEvidence",
    "CrossHostPlanningMemberReconstructionPort",
    "ProposalDecisionContinuationPort",
]
