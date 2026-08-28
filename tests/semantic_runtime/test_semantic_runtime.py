from __future__ import annotations

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    ChangeJournal,
    ContractType,
    Coverage,
    CoverageMismatchError,
    DirtyMap,
    FreshnessResolver,
    FreshnessState,
    FreshnessUnsatisfiedError,
    GeometryLevel,
    HostDeltaRecord,
    ReconstructionResult,
    RevisionChangedError,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotKind,
    SnapshotSet,
    SnapshotSetError,
    build_context_contract,
    build_operation_contract,
)

PROJECT_ID = "project-001"
PROJECTION_REF = SemanticProjectionRef(
    "projection-1",
    "projection-hash",
    "semantic-model-v1",
    "provider-set-hash",
    "mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef("environment-1", "environment-hash")


def test_change_journal_and_dirty_map_track_entity_aspects_only() -> None:
    journal = ChangeJournal()
    dirty = DirtyMap()
    entry = journal.append(
        actor="HUMAN",
        delta=HostDeltaRecord(
            document_id="doc-1",
            host_revision="42",
            semantic_id="sem-1",
            change_type="MODIFIED",
            affected_aspects=(SemanticAspect.PLACEMENT, SemanticAspect.GEOMETRY),
        ),
    )

    dirty.apply(entry)

    assert entry.sequence == 1
    assert dirty.state("doc-1", "sem-1", SemanticAspect.PLACEMENT) is FreshnessState.DIRTY
    assert dirty.state("doc-1", "sem-1", SemanticAspect.GEOMETRY) is FreshnessState.DIRTY
    assert dirty.state("doc-1", "sem-1", SemanticAspect.PROPERTIES) is FreshnessState.UNKNOWN
    assert dirty.state("doc-1", "sem-2", SemanticAspect.GEOMETRY) is FreshnessState.UNKNOWN


def test_dirty_map_can_mark_only_requested_scope_fresh() -> None:
    dirty = DirtyMap()
    dirty.mark_dirty("doc-1", "sem-1", (SemanticAspect.PLACEMENT, SemanticAspect.GEOMETRY))

    dirty.mark_fresh("doc-1", ("sem-1",), (SemanticAspect.PLACEMENT,))

    assert dirty.state("doc-1", "sem-1", SemanticAspect.PLACEMENT) is FreshnessState.FRESH
    assert dirty.state("doc-1", "sem-1", SemanticAspect.GEOMETRY) is FreshnessState.DIRTY


def test_context_contract_includes_identity_and_caps_geometry_at_bounds() -> None:
    contract = build_context_contract(
        document_ref="doc-1",
        root_entities=("sem-2", "sem-1", "sem-1"),
        extra_requirements=(
            AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.BOUNDS),
            AspectRequirement(SemanticAspect.PROPERTIES),
        ),
        project_id=PROJECT_ID,
    )

    assert contract.contract_type is ContractType.CONTEXT
    assert contract.coverage == Coverage("doc-1", ("sem-1", "sem-2"), 0)
    assert AspectRequirement(SemanticAspect.IDENTITY) in contract.requirements
    assert AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.BOUNDS) in contract.requirements
    assert contract.operation_fingerprint is None


def test_context_contract_rejects_geometry_above_bounds() -> None:
    with pytest.raises(ValueError, match="Context Freshness"):
        build_context_contract(
            document_ref="doc-1",
            root_entities=("sem-1",),
            extra_requirements=(
                AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.EXACT),
            ),
            project_id=PROJECT_ID,
        )


def test_operation_contract_binds_operation_targets_arguments_and_requirements() -> None:
    requirements = (
        AspectRequirement(SemanticAspect.PLACEMENT),
        AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.EXACT),
    )
    first = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=requirements,
    )
    target_changed = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-2",),
        arguments={"displacement": [500, 0, 0]},
        requirements=requirements,
    )
    argument_changed = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [1000, 0, 0]},
        requirements=requirements,
    )

    assert first.contract_type is ContractType.OPERATION
    assert first.hash != target_changed.hash
    assert first.hash != argument_changed.hash
    assert first.operation_fingerprint is not None


def _result_for(
    contract,
    *,
    revision: str = "42",
    coverage: Coverage | None = None,
    guarantees=None,
    projection_ref: SemanticProjectionRef = PROJECTION_REF,
    environment_ref: SemanticEnvironmentRef = ENVIRONMENT_REF,
):
    return ReconstructionResult(
        document_ref=contract.coverage.document_ref,
        host_revision=revision,
        coverage=coverage or contract.coverage,
        guarantees=tuple(guarantees or contract.requirements),
        projection_ref=projection_ref,
        semantic_environment_ref=environment_ref,
    )


def test_freshness_resolver_emits_context_and_planning_snapshots() -> None:
    dirty = DirtyMap()
    resolver = FreshnessResolver(dirty)
    context_contract = build_context_contract(
        "doc-1", ("sem-1",), project_id=PROJECT_ID
    )
    operation_contract = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )

    context_snapshot = resolver.resolve(
        context_contract,
        expected_host_revision="42",
        reconstruct=lambda contract, revision: _result_for(contract, revision=revision),
    )
    planning_snapshot = resolver.resolve(
        operation_contract,
        expected_host_revision="42",
        reconstruct=lambda contract, revision: _result_for(contract, revision=revision),
    )

    assert context_snapshot.kind is SnapshotKind.CONTEXT
    assert planning_snapshot.kind is SnapshotKind.PLANNING
    assert context_snapshot.freshness_contract_hash == context_contract.hash
    assert planning_snapshot.freshness_contract_hash == operation_contract.hash
    assert planning_snapshot.coverage == operation_contract.coverage
    assert planning_snapshot.projection_ref == PROJECTION_REF
    assert planning_snapshot.semantic_environment_ref == ENVIRONMENT_REF


def test_snapshot_hash_binds_contract_revision_coverage_and_guarantees() -> None:
    resolver = FreshnessResolver(DirtyMap())
    contract = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )

    first = resolver.resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda c, r: _result_for(c, revision=r),
    )
    second = resolver.resolve(
        contract,
        expected_host_revision="43",
        reconstruct=lambda c, r: _result_for(c, revision=r),
    )

    assert first.hash != second.hash
    assert first.base_host_revision == "42"
    assert second.base_host_revision == "43"


def test_freshness_resolver_rejects_revision_change_during_reconstruction() -> None:
    resolver = FreshnessResolver(DirtyMap())
    contract = build_context_contract(
        "doc-1", ("sem-1",), project_id=PROJECT_ID
    )

    with pytest.raises(RevisionChangedError):
        resolver.resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda c, _r: _result_for(c, revision="43"),
        )


def test_freshness_resolver_rejects_silent_coverage_expansion() -> None:
    resolver = FreshnessResolver(DirtyMap())
    contract = build_context_contract(
        "doc-1", ("sem-1",), project_id=PROJECT_ID
    )
    expanded = Coverage("doc-1", ("sem-1", "sem-2"), 0)

    with pytest.raises(CoverageMismatchError):
        resolver.resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda c, r: _result_for(c, revision=r, coverage=expanded),
        )


def test_freshness_resolver_rejects_missing_or_weaker_guarantees() -> None:
    dirty = DirtyMap()
    dirty.mark_dirty(
        "doc-1",
        "sem-1",
        (SemanticAspect.GEOMETRY, SemanticAspect.PLACEMENT),
    )
    resolver = FreshnessResolver(dirty)
    contract = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(
            AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.EXACT),
            AspectRequirement(SemanticAspect.PLACEMENT),
        ),
    )

    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"GEOMETRY\.geometry, PLACEMENT\.freshness",
    ):
        resolver.resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda c, r: _result_for(
                c,
                revision=r,
                guarantees=(AspectGuarantee(SemanticAspect.GEOMETRY, GeometryLevel.BOUNDS),),
            ),
        )

    assert dirty.state("doc-1", "sem-1", SemanticAspect.GEOMETRY) is FreshnessState.DIRTY
    assert dirty.state("doc-1", "sem-1", SemanticAspect.PLACEMENT) is FreshnessState.DIRTY


def test_successful_barrier_marks_only_contract_guarantees_fresh() -> None:
    dirty = DirtyMap()
    dirty.mark_dirty(
        "doc-1",
        "sem-1",
        (SemanticAspect.PLACEMENT, SemanticAspect.GEOMETRY, SemanticAspect.PROPERTIES),
    )
    resolver = FreshnessResolver(dirty)
    contract = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(
            AspectRequirement(SemanticAspect.PLACEMENT),
            AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.EXACT),
        ),
    )

    resolver.resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda c, r: _result_for(c, revision=r),
    )

    assert dirty.state("doc-1", "sem-1", SemanticAspect.PLACEMENT) is FreshnessState.FRESH
    assert dirty.state("doc-1", "sem-1", SemanticAspect.GEOMETRY) is FreshnessState.FRESH
    assert dirty.state("doc-1", "sem-1", SemanticAspect.PROPERTIES) is FreshnessState.DIRTY


def test_snapshot_set_accepts_only_planning_snapshots_and_hashes_members() -> None:
    resolver = FreshnessResolver(DirtyMap())
    operation_contract = build_operation_contract(
        project_id=PROJECT_ID,
        document_ref="doc-1",
        canonical_operation="move.v1",
        targets=("sem-1",),
        arguments={"displacement": [500, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    planning = resolver.resolve(
        operation_contract,
        expected_host_revision="42",
        reconstruct=lambda c, r: _result_for(c, revision=r),
    )
    snapshot_set = SnapshotSet.create((planning,))

    assert snapshot_set.member_snapshot_ids == (planning.snapshot_id,)
    assert snapshot_set.semantic_environment_ref == ENVIRONMENT_REF
    assert snapshot_set.hash

    context_contract = build_context_contract(
        "doc-1", ("sem-1",), project_id=PROJECT_ID
    )
    context = resolver.resolve(
        context_contract,
        expected_host_revision="42",
        reconstruct=lambda c, r: _result_for(c, revision=r),
    )
    with pytest.raises(SnapshotSetError):
        SnapshotSet.create((context,))
