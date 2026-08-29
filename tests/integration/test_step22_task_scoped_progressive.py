from __future__ import annotations

import pytest

from autocad_sidecar.capability.profile import parse_design_capability
from autocad_sidecar.mcp_server import build_tool_definitions
from design_orchestrator.canonical_operations import MOVE_V1
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
)
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    DirtyMap,
    FreshnessResolver,
    FreshnessState,
    FreshnessUnsatisfiedError,
    GeometryLevel,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    build_operation_contract,
    requirements_from_mappings,
)


PROJECTION_REF = SemanticProjectionRef(
    "step22-projection",
    "step22-projection-hash",
    "step22-proof-v1",
    "step22-provider-set-hash",
    "step22-mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef(
    "step22-environment",
    "step22-environment-hash",
)


def _result(
    contract,
    revision: str,
    *guarantees: AspectGuarantee,
) -> ReconstructionResult:
    return ReconstructionResult(
        document_ref=contract.coverage.document_ref,
        host_revision=revision,
        coverage=contract.coverage,
        guarantees=tuple(guarantees),
        projection_ref=PROJECTION_REF,
        semantic_environment_ref=ENVIRONMENT_REF,
    )


def test_real_move_upgrades_only_placement() -> None:
    tools = {tool["name"]: tool for tool in build_tool_definitions()}
    profile = parse_design_capability(
        tools["cad.move"],
        provider_server="autocad.local",
    )
    resolution = OperationResolver((MOVE_V1,)).resolve(
        (profile,),
        ResolutionContext(
            host_provider_servers=frozenset({"autocad.local"}),
            semantic_context=SemanticEligibilityContext(
                context_snapshot_id="CS-step22-move",
                context_snapshot_hash="step22-context-snapshot-hash",
                document_ref="drawing-001",
                semantic_environment_ref=(
                    f"{ENVIRONMENT_REF.environment_id}@{ENVIRONMENT_REF.content_hash}"
                ),
                entities=(),
            ),
        ),
    )
    resolved = resolution.resolved_operations[0]
    requirements = requirements_from_mappings(
        resolved.operation_freshness_requirements
    )

    assert requirements == (AspectRequirement(SemanticAspect.PLACEMENT),)
    assert "GEOMETRY" in resolved.effects

    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation=resolved.canonical_operation,
        targets=("sem-line-001",),
        arguments={"displacement": [500, 0, 0]},
        requirements=requirements,
    )
    assert contract.coverage.root_entities == ("sem-line-001",)

    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-line-001",
        (
            SemanticAspect.PLACEMENT,
            SemanticAspect.GEOMETRY,
            SemanticAspect.CLASSIFICATION,
        ),
    )

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(SemanticAspect.PLACEMENT),
        ),
    )

    assert tuple(item.aspect for item in snapshot.aspect_guarantees) == (
        SemanticAspect.PLACEMENT,
    )
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.PLACEMENT
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY


def test_classification_only_task_does_not_upgrade_geometry_or_assurance() -> None:
    requirement = AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        geometry_level=GeometryLevel.NONE,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=AssuranceLevel.RULE_DERIVED,
    )
    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation="classify.v1",
        targets=("sem-wall-001",),
        arguments={},
        requirements=(requirement,),
    )
    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-wall-001",
        (SemanticAspect.CLASSIFICATION, SemanticAspect.GEOMETRY),
    )

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(
                SemanticAspect.CLASSIFICATION,
                coverage_state=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                assurance_level=AssuranceLevel.RULE_DERIVED,
            ),
        ),
    )

    assert len(snapshot.aspect_guarantees) == 1
    guarantee = snapshot.aspect_guarantees[0]
    assert guarantee.aspect is SemanticAspect.CLASSIFICATION
    assert guarantee.geometry_level is GeometryLevel.NONE
    assert guarantee.semantic_depth is SemanticDepth.CANONICAL
    assert guarantee.assurance_level is AssuranceLevel.RULE_DERIVED
    assert dirty.state(
        "drawing-001", "sem-wall-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-wall-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY


def test_exact_geometry_is_required_only_when_explicitly_requested() -> None:
    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation="geometry.inspect.v1",
        targets=("sem-line-001",),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.GEOMETRY,
                GeometryLevel.EXACT,
            ),
        ),
    )
    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-line-001",
        (SemanticAspect.GEOMETRY, SemanticAspect.CLASSIFICATION),
    )

    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"GEOMETRY\.geometry",
    ):
        FreshnessResolver(dirty).resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda current, revision: _result(
                current,
                revision,
                AspectGuarantee(
                    SemanticAspect.GEOMETRY,
                    GeometryLevel.BOUNDS,
                ),
            ),
        )

    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(
                SemanticAspect.GEOMETRY,
                GeometryLevel.EXACT,
            ),
        ),
    )

    assert snapshot.aspect_guarantees[0].geometry_level is GeometryLevel.EXACT
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY