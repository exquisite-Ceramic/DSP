from __future__ import annotations

from dataclasses import replace

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    Coverage,
    CoverageMismatchError,
    DirtyMap,
    FreshnessResolver,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotSet,
    SnapshotSetError,
    build_operation_contract,
)


def _projection(projection_hash: str = "projection-hash") -> SemanticProjectionRef:
    return SemanticProjectionRef(
        "projection-1",
        projection_hash,
        "semantic-model-v1",
        "provider-set-hash",
        "mapping-profile-set-hash",
    )


def _environment(content_hash: str = "environment-hash") -> SemanticEnvironmentRef:
    return SemanticEnvironmentRef("environment-1", content_hash)


def _planning_snapshot(
    document_ref: str,
    *,
    projection_ref: SemanticProjectionRef | None = None,
    environment_ref: SemanticEnvironmentRef | None = None,
):
    contract = build_operation_contract(
        project_id="project-001",
        document_ref=document_ref,
        canonical_operation="move.v1",
        targets=(f"sem-{document_ref}",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    return FreshnessResolver(DirtyMap()).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: ReconstructionResult(
            document_ref=current.coverage.document_ref,
            host_revision=revision,
            coverage=current.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
            projection_ref=projection_ref or _projection(),
            semantic_environment_ref=environment_ref or _environment(),
        ),
    )


def test_snapshot_hash_changes_when_projection_or_environment_hash_changes() -> None:
    baseline = _planning_snapshot("doc-1")
    projection_changed = _planning_snapshot(
        "doc-1",
        projection_ref=_projection("projection-hash-2"),
    )
    environment_changed = _planning_snapshot(
        "doc-1",
        environment_ref=_environment("environment-hash-2"),
    )

    assert len({baseline.hash, projection_changed.hash, environment_changed.hash}) == 3


def test_semantic_snapshot_create_rejects_coverage_mismatch_directly() -> None:
    contract = build_operation_contract(
        project_id="project-001",
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    expanded = Coverage("doc-1", ("sem-1", "sem-2"), 0)
    result = ReconstructionResult(
        document_ref="doc-1",
        host_revision="42",
        coverage=expanded,
        guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
        projection_ref=_projection(),
        semantic_environment_ref=_environment(),
    )

    with pytest.raises(CoverageMismatchError, match="coverage"):
        SemanticSnapshot.create(contract, result)


def test_snapshot_set_requires_one_pinned_environment() -> None:
    first = _planning_snapshot("doc-a", environment_ref=_environment("hash-a"))
    second = _planning_snapshot("doc-b", environment_ref=_environment("hash-b"))

    with pytest.raises(SnapshotSetError, match="SemanticEnvironment"):
        SnapshotSet.create((first, second))


def test_snapshot_set_hash_binds_projection_ref_even_with_same_member_hash() -> None:
    snapshot = _planning_snapshot("doc-a")
    changed_projection = replace(
        snapshot,
        projection_ref=_projection("projection-hash-2"),
    )

    assert snapshot.hash == changed_projection.hash
    assert SnapshotSet.create((snapshot,)).hash != SnapshotSet.create((changed_projection,)).hash
