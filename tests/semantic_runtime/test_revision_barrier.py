from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    DirtyMap,
    FreshnessResolver,
    HostRevisionObservationPort,
    ReconstructionResult,
    RevisionBarrier,
    RevisionChangedError,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotSet,
    SnapshotSetError,
    build_context_contract,
    build_operation_contract,
)

PROJECTION_REF = SemanticProjectionRef(
    "projection-revision-barrier",
    "projection-hash-revision-barrier",
    "semantic-model-v1",
    "provider-set-hash",
    "mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef(
    "environment-revision-barrier",
    "environment-hash-revision-barrier",
)


@dataclass
class _RevisionObservations(HostRevisionObservationPort):
    """只返回 Host 当前 revision，并记录调用；不承担任何 pass/fail 语义。"""

    revisions: dict[str, str]
    observed_documents: list[str] = field(default_factory=list)

    def current_revision(self, document_ref: str) -> str:
        self.observed_documents.append(document_ref)
        return self.revisions[document_ref]


def _planning_snapshot(*, document_ref: str, revision: str, target: str):
    """通过现有 FreshnessResolver 构造真实 PlanningSnapshot，避免手造领域对象。"""
    resolver = FreshnessResolver(DirtyMap())
    contract = build_operation_contract(
        project_id="project-revision-barrier",
        document_ref=document_ref,
        canonical_operation="move.v1",
        targets=(target,),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    return resolver.resolve(
        contract,
        expected_host_revision=revision,
        reconstruct=lambda current_contract, expected_revision: ReconstructionResult(
            document_ref=current_contract.coverage.document_ref,
            host_revision=expected_revision,
            coverage=current_contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
            projection_ref=PROJECTION_REF,
            semantic_environment_ref=ENVIRONMENT_REF,
        ),
    )


def _context_snapshot(*, document_ref: str, revision: str):
    """通过现有 context freshness contract 构造真实 ContextSnapshot。"""
    resolver = FreshnessResolver(DirtyMap())
    contract = build_context_contract(
        document_ref,
        ("sem-context",),
        project_id="project-revision-barrier",
    )
    return resolver.resolve(
        contract,
        expected_host_revision=revision,
        reconstruct=lambda current_contract, expected_revision: ReconstructionResult(
            document_ref=current_contract.coverage.document_ref,
            host_revision=expected_revision,
            coverage=current_contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.IDENTITY),),
            projection_ref=PROJECTION_REF,
            semantic_environment_ref=ENVIRONMENT_REF,
        ),
    )


def test_revision_barrier_accepts_unchanged_host_revision() -> None:
    snapshot_set = SnapshotSet.create(
        (_planning_snapshot(document_ref="doc-a", revision="42", target="sem-a"),)
    )
    observations = _RevisionObservations({"doc-a": "42"})

    RevisionBarrier(observations).check(snapshot_set)

    assert observations.observed_documents == ["doc-a"]


def test_revision_barrier_rejects_changed_host_revision() -> None:
    snapshot_set = SnapshotSet.create(
        (_planning_snapshot(document_ref="doc-a", revision="42", target="sem-a"),)
    )
    observations = _RevisionObservations({"doc-a": "43"})

    with pytest.raises(RevisionChangedError, match="42.*43"):
        RevisionBarrier(observations).check(snapshot_set)


def test_revision_barrier_fails_closed_for_missing_or_empty_observation() -> None:
    snapshot_set = SnapshotSet.create(
        (_planning_snapshot(document_ref="doc-a", revision="42", target="sem-a"),)
    )

    with pytest.raises(RevisionChangedError, match="doc-a"):
        RevisionBarrier(_RevisionObservations({})).check(snapshot_set)

    with pytest.raises(RevisionChangedError, match="doc-a"):
        RevisionBarrier(_RevisionObservations({"doc-a": "   "})).check(snapshot_set)


def test_revision_barrier_checks_every_planning_snapshot() -> None:
    snapshot_set = SnapshotSet.create(
        (
            _planning_snapshot(document_ref="doc-b", revision="8", target="sem-b"),
            _planning_snapshot(document_ref="doc-a", revision="7", target="sem-a"),
        )
    )
    observations = _RevisionObservations({"doc-a": "7", "doc-b": "8"})

    RevisionBarrier(observations).check(snapshot_set)

    assert observations.observed_documents == ["doc-a", "doc-b"]


def test_snapshot_set_owner_rejects_context_snapshot_before_barrier() -> None:
    context_snapshot = _context_snapshot(document_ref="doc-context", revision="11")

    with pytest.raises(SnapshotSetError, match="PlanningSnapshots only"):
        SnapshotSet.create((context_snapshot,))
