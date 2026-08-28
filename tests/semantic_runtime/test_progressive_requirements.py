from __future__ import annotations

import pytest

from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    GeometryLevel,
    SemanticAspect,
    SemanticDepth,
    build_operation_contract,
    requirements_from_mappings,
)


def test_classification_is_first_class_aspect() -> None:
    assert SemanticAspect.CLASSIFICATION.value == "CLASSIFICATION"


def test_requirement_keeps_progressive_axes_separate() -> None:
    requirement = AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=AssuranceLevel.RULE_DERIVED,
    )

    assert requirement.geometry_level is GeometryLevel.NONE
    assert requirement.minimum_coverage is CoverageState.RESOLVED
    assert requirement.semantic_depth is SemanticDepth.CANONICAL
    assert requirement.minimum_assurance is AssuranceLevel.RULE_DERIVED


def test_guarantee_keeps_actual_progressive_evidence_separate() -> None:
    guarantee = AspectGuarantee(
        SemanticAspect.CLASSIFICATION,
        coverage_state=CoverageState.PARTIAL,
        semantic_depth=SemanticDepth.NORMALIZED,
        assurance_level=AssuranceLevel.HEURISTIC,
    )

    assert guarantee.geometry_level is GeometryLevel.NONE
    assert guarantee.coverage_state is CoverageState.PARTIAL
    assert guarantee.semantic_depth is SemanticDepth.NORMALIZED
    assert guarantee.assurance_level is AssuranceLevel.HEURISTIC


def test_mapping_adapter_parses_progressive_axes_and_classification() -> None:
    requirements = requirements_from_mappings(
        (
            {
                "aspect": "classification",
                "minimum_coverage": "RESOLVED",
                "semantic_depth": "CANONICAL",
                "minimum_assurance": "STANDARD_MAPPED",
            },
        )
    )

    assert requirements == (
        AspectRequirement(
            SemanticAspect.CLASSIFICATION,
            minimum_coverage=CoverageState.RESOLVED,
            semantic_depth=SemanticDepth.CANONICAL,
            minimum_assurance=AssuranceLevel.STANDARD_MAPPED,
        ),
    )


def test_mapping_adapter_merges_duplicate_aspect_axes_independently() -> None:
    requirements = requirements_from_mappings(
        (
            {
                "aspect": "classification",
                "minimum_coverage": "PARTIAL",
                "minimum_assurance": "STANDARD_MAPPED",
            },
            {
                "aspect": "classification",
                "minimum_coverage": "RESOLVED",
                "semantic_depth": "CANONICAL",
            },
        )
    )

    assert requirements == (
        AspectRequirement(
            SemanticAspect.CLASSIFICATION,
            minimum_coverage=CoverageState.RESOLVED,
            semantic_depth=SemanticDepth.CANONICAL,
            minimum_assurance=AssuranceLevel.STANDARD_MAPPED,
        ),
    )


def test_mapping_adapter_fails_closed_on_unknown_progressive_enum() -> None:
    with pytest.raises(ValueError, match="unknown minimum_assurance"):
        requirements_from_mappings(
            ({"aspect": "classification", "minimum_assurance": "MAGICAL"},)
        )


def test_contract_hash_binds_progressive_requirement_axes() -> None:
    weak = build_operation_contract(
        project_id="project-1",
        document_ref="doc-1",
        canonical_operation="classify.v1",
        targets=("sem-1",),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.CLASSIFICATION,
                minimum_assurance=AssuranceLevel.RULE_DERIVED,
            ),
        ),
    )
    strong = build_operation_contract(
        project_id="project-1",
        document_ref="doc-1",
        canonical_operation="classify.v1",
        targets=("sem-1",),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.CLASSIFICATION,
                minimum_assurance=AssuranceLevel.STANDARD_MAPPED,
            ),
        ),
    )

    assert weak.hash != strong.hash


def test_geometry_axis_remains_independent_from_other_axes() -> None:
    requirement = AspectRequirement(
        SemanticAspect.GEOMETRY,
        GeometryLevel.EXACT,
        minimum_coverage=CoverageState.PARTIAL,
        semantic_depth=SemanticDepth.NORMALIZED,
        minimum_assurance=AssuranceLevel.HEURISTIC,
    )

    assert requirement.geometry_level is GeometryLevel.EXACT
    assert requirement.minimum_coverage is CoverageState.PARTIAL
    assert requirement.semantic_depth is SemanticDepth.NORMALIZED
    assert requirement.minimum_assurance is AssuranceLevel.HEURISTIC
