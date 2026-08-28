from __future__ import annotations

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    CoverageMismatchError,
    DirtyMap,
    FreshnessResolver,
    FreshnessState,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    build_operation_contract,
)

PROJECTION_REF = SemanticProjectionRef(
    "projection-1",
    "projection-hash",
    "semantic-model-v1",
    "provider-set-hash",
    "mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef("environment-1", "environment-hash")


def _result(current, revision, *, guarantees):
    return ReconstructionResult(
        document_ref=current.coverage.document_ref,
        host_revision=revision,
        coverage=current.coverage,
        guarantees=guarantees,
        projection_ref=PROJECTION_REF,
        semantic_environment_ref=ENVIRONMENT_REF,
    )


def test_freshness_contract_and_snapshot_bind_project_id() -> None:
    first = build_operation_contract(
        project_id="project-001",
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    second_project = build_operation_contract(
        project_id="project-002",
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )

    snapshot = FreshnessResolver(DirtyMap()).resolve(
        first,
        expected_host_revision="42",
        reconstruct=lambda contract, revision: _result(
            contract,
            revision,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
        ),
    )

    assert first.project_id == "project-001"
    assert snapshot.project_id == "project-001"
    assert snapshot.projection_ref == PROJECTION_REF
    assert snapshot.semantic_environment_ref == ENVIRONMENT_REF
    assert first.hash != second_project.hash


def test_snapshot_aspect_guarantee_is_bound_to_contract_coverage() -> None:
    contract = build_operation_contract(
        project_id="project-001",
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )

    snapshot = FreshnessResolver(DirtyMap()).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
        ),
    )

    assert snapshot.aspect_guarantees[0].coverage_ref == f"{contract.contract_id}#coverage"


def test_mismatched_guarantee_scope_is_rejected_before_dirty_map_is_fresh() -> None:
    dirty = DirtyMap()
    dirty.mark_dirty("doc-1", "sem-1", (SemanticAspect.PLACEMENT,))
    resolver = FreshnessResolver(dirty)
    contract = build_operation_contract(
        project_id="project-001",
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )

    with pytest.raises(CoverageMismatchError, match="guarantee scope"):
        resolver.resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda current, revision: _result(
                current,
                revision,
                guarantees=(
                    AspectGuarantee(
                        SemanticAspect.PLACEMENT,
                        coverage_ref="FC-other#coverage",
                    ),
                ),
            ),
        )

    assert dirty.state("doc-1", "sem-1", SemanticAspect.PLACEMENT) is FreshnessState.DIRTY
