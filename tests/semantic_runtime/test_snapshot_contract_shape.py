from __future__ import annotations

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    Coverage,
    DirtyMap,
    FreshnessResolver,
    FreshnessState,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotKind,
    SnapshotSet,
    SnapshotSetError,
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


def test_coverage_binds_neighborhood_depth_and_relations() -> None:
    coverage = Coverage(
        "doc-1",
        ("sem-1",),
        2,
        ("HOSTED_BY", "CONNECTED_TO", "HOSTED_BY"),
    )

    assert coverage.neighborhood_relations == ("CONNECTED_TO", "HOSTED_BY")
    assert coverage.payload()["neighborhood"] == {
        "depth": 2,
        "relations": ["CONNECTED_TO", "HOSTED_BY"],
    }


def test_aspect_guarantee_explicitly_guarantees_fresh_state() -> None:
    guarantee = AspectGuarantee(SemanticAspect.PLACEMENT)

    assert guarantee.required_state is FreshnessState.FRESH


def _planning_snapshot(*, revision: str, target: str, document_ref: str = "doc-1"):
    resolver = FreshnessResolver(DirtyMap())
    contract = build_operation_contract(
        project_id="project-001",
        document_ref=document_ref,
        canonical_operation="move.v1",
        targets=(target,),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    return resolver.resolve(
        contract,
        expected_host_revision=revision,
        reconstruct=lambda c, r: ReconstructionResult(
            document_ref=c.coverage.document_ref,
            host_revision=r,
            coverage=c.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
            projection_ref=PROJECTION_REF,
            semantic_environment_ref=ENVIRONMENT_REF,
        ),
    )


def test_snapshot_set_is_explicitly_planning_and_one_snapshot_per_document() -> None:
    first = _planning_snapshot(revision="42", target="sem-1")
    snapshot_set = SnapshotSet.create((first,))

    assert snapshot_set.kind is SnapshotKind.PLANNING
    assert snapshot_set.semantic_environment_ref == ENVIRONMENT_REF

    second_same_document = _planning_snapshot(revision="43", target="sem-2")
    with pytest.raises(SnapshotSetError, match="document"):
        SnapshotSet.create((first, second_same_document))
