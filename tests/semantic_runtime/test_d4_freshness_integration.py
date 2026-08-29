from __future__ import annotations

from autocad_sidecar.capability.profile import parse_design_capability
from autocad_sidecar.mcp_server import build_tool_definitions
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from semantic_runtime import (
    AspectRequirement,
    GeometryLevel,
    SemanticAspect,
    build_operation_contract,
    requirements_from_mappings,
)


def test_requirements_from_mappings_normalizes_d4_and_profile_shapes() -> None:
    requirements = requirements_from_mappings(
        (
            {"aspect": "placement", "required_state": "FRESH"},
            {"aspect": "geometry", "geometry_level": "EXACT"},
        )
    )

    assert requirements == (
        AspectRequirement(SemanticAspect.GEOMETRY, GeometryLevel.EXACT),
        AspectRequirement(SemanticAspect.PLACEMENT),
    )


def test_real_d3_move_freshness_flows_through_d4_into_d5_contract() -> None:
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
                context_snapshot_id="CS-d4-d5-test",
                context_snapshot_hash="snapshot-hash-d4-d5-test",
                document_ref="drawing-001",
                semantic_environment_ref="semantic-env@d4-d5-test",
                entities=(),
            ),
        ),
    )
    resolved = resolution.resolved_operations[0]

    requirements = requirements_from_mappings(resolved.operation_freshness_requirements)
    contract = build_operation_contract(
        project_id="project-001",
        document_ref="drawing-001",
        canonical_operation=resolved.canonical_operation,
        targets=("sem-line-001",),
        arguments={"displacement": [500, 0, 0]},
        requirements=requirements,
    )

    assert requirements == (AspectRequirement(SemanticAspect.PLACEMENT),)
    assert contract.requirements == requirements
    assert contract.operation_fingerprint


def test_step25_bound_move_flows_into_phase_b_operation_freshness_contract() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [500, 0, 0]}),
        ParameterBindingContext(
            context_snapshot_id="CS-step25",
            context_snapshot_hash="snapshot-hash-step25",
            document_ref="drawing-001",
            semantic_environment_ref="semantic-env@step25",
            selection=("sem-line-001",),
        ),
    )

    requirements = requirements_from_mappings(
        bound.planning_requirements.operation_freshness_requirements
    )
    contract = build_operation_contract(
        project_id="project-001",
        document_ref=bound.context_snapshot_ref.document_ref,
        canonical_operation=bound.operation.canonical_operation,
        targets=bound.arguments["targets"],
        arguments={"displacement": bound.arguments["displacement"]},
        requirements=requirements,
    )

    assert requirements == (AspectRequirement(SemanticAspect.PLACEMENT),)
    assert contract.requirements == requirements
    assert contract.coverage.root_entities == ("sem-line-001",)
    assert contract.operation_fingerprint
