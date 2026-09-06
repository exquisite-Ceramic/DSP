from __future__ import annotations

from dataclasses import replace

import pytest

from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    bind_changeset_v2,
    bind_topology_snapshot_v2,
    direct_existing_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalOperationContractEvidence,
    ChangeSetBuildRequest,
    ChangeSetBuilder,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
    validate_changeset_integrity_v2,
)
from design_convergence import (
    ConvergenceComparisonMode,
    ConvergenceProfileBuildRequest,
    ConvergenceProfileError,
    build_convergence_profile,
)
from design_impact import (
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from design_orchestrator.parameter_binder import (
    SET_WALL_THICKNESS_V1_BINDING_RECIPE,
    BoundOperationProposal,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _bound_evidence(bound: BoundOperationProposal) -> BoundOperationEvidence:
    planning_requirements = {
        "operation_freshness_requirements": (
            bound.planning_requirements.operation_freshness_requirements
        ),
        "coverage_requirements": bound.planning_requirements.coverage_requirements,
        "assurance_requirements": bound.planning_requirements.assurance_requirements,
    }
    binding_evidence = {
        slot: {
            "binding_class": evidence.binding_class.value,
            "source": evidence.source,
            "source_ref": evidence.source_ref,
        }
        for slot, evidence in bound.binding_evidence.items()
    }
    arguments = dict(bound.arguments)
    material_fingerprint = compute_bound_operation_fingerprint(
        bound.operation.canonical_operation,
        bound.operation.version,
        arguments,
    )
    evidence_fingerprint = compute_bound_operation_evidence_fingerprint(
        canonical_operation=bound.operation.canonical_operation,
        canonical_operation_version=bound.operation.version,
        arguments=arguments,
        context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
        context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
        document_ref=bound.context_snapshot_ref.document_ref,
        semantic_environment_id=bound.semantic_environment_ref,
        planning_requirements=planning_requirements,
        binding_evidence=binding_evidence,
    )
    return BoundOperationEvidence(
        canonical_operation=bound.operation.canonical_operation,
        canonical_operation_version=bound.operation.version,
        arguments=arguments,
        context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
        context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
        document_ref=bound.context_snapshot_ref.document_ref,
        semantic_environment_id=bound.semantic_environment_ref,
        planning_requirements=planning_requirements,
        binding_evidence=binding_evidence,
        bound_operation_fingerprint=material_fingerprint,
        bound_operation_evidence_fingerprint=evidence_fingerprint,
    )


def _contract_from_definition() -> CanonicalOperationContractEvidence:
    definition = SET_WALL_THICKNESS_V1
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=definition.canonical_operation,
        canonical_operation_version=definition.version,
        argument_schema=definition.input_schema,
        effects=definition.effects,
        verification_contract=definition.verification_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=definition.canonical_operation,
        canonical_operation_version=definition.version,
        argument_schema=definition.input_schema,
        effects=definition.effects,
        verification_contract=definition.verification_contract,
        definition_fingerprint=fingerprint,
    )


def _transaction():
    binder = ParameterBinder(
        (SET_WALL_THICKNESS_V1,),
        (SET_WALL_THICKNESS_V1_BINDING_RECIPE,),
    )
    bound = binder.bind(
        OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300.0, "unit": "mm"}},
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-CONVERGENCE",
            context_snapshot_hash="context-hash-convergence",
            document_ref="DOC-CONVERGENCE",
            semantic_environment_ref="ENV-CONVERGENCE",
            selection=("WALL-001",),
            context_values={},
        ),
    )
    environment = SemanticEnvironmentBinding("ENV-CONVERGENCE", "env-hash-convergence")
    planning = PlanningSnapshotBinding(
        "PS-CONVERGENCE",
        "ps-hash-convergence",
        "DOC-CONVERGENCE",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-CONVERGENCE",
        "pss-hash-convergence",
        (planning.snapshot_id,),
        environment,
    )
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(CanonicalAspect.PROPERTIES.value,),
    )
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=intent,
        )
    )
    rule_id = direct_existing_rule_id("WALL-001")
    scope_v1 = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                SET_WALL_THICKNESS_V1.canonical_operation,
                SET_WALL_THICKNESS_V1.version,
                (CanonicalAspect.PROPERTIES,),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=(
                DirectEntityEffect("WALL-001", (CanonicalAspect.PROPERTIES,)),
            ),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-CONVERGENCE",
                    "DOC-CONVERGENCE",
                    existing_rule_ids=(rule_id,),
                ),
            ),
        )
    )
    scope_v2 = bind_topology_snapshot_v2(scope_v1, "a" * 64)
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-CONVERGENCE",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope_v2,
            canonical_operation_contracts=(_contract_from_definition(),),
        )
    )
    boundary_v2 = bind_changeset_v2(
        scope_v2,
        changeset.changeset_hash,
        "SCOPE-CONVERGENCE",
    )
    validate_changeset_integrity_v2(changeset, boundary_v2)
    return changeset, boundary_v2


def _build(definition=SET_WALL_THICKNESS_V1):
    changeset, boundary_v2 = _transaction()
    return build_convergence_profile(
        ConvergenceProfileBuildRequest(
            canonical_changeset=changeset,
            approval_scope_boundary=boundary_v2,
            canonical_operation_definition=definition,
        )
    )


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ConvergenceProfileError) as exc:
        operation()
    assert exc.value.code == code


def test_exact_wall_contract_builds_one_mm_profile_rule() -> None:
    changeset, boundary_v2 = _transaction()
    definition = SET_WALL_THICKNESS_V1

    assert changeset.root_operation.arguments["thickness"]["unit"] == "mm"
    assert (
        definition.input_schema["properties"]["thickness"]["properties"]["unit"]["const"]
        == "mm"
    )
    assert "tolerance" not in definition.verification_contract

    profile = build_convergence_profile(
        ConvergenceProfileBuildRequest(changeset, boundary_v2, definition)
    )
    assert profile.profile_version == "1.0.0"
    assert len(profile.field_rules) == 1
    rule = profile.field_rules[0]
    assert rule.subjects_from_argument == "targets"
    assert rule.path == "properties.dsp:WallThickness"
    assert rule.expected_argument == "thickness"
    assert rule.measurement_unit == "mm"
    assert rule.comparison_mode is ConvergenceComparisonMode.EXACT_CANONICAL_VALUE
    assert len(profile.profile_hash) == 64


def test_operation_identity_or_version_mismatch_fails_closed() -> None:
    _assert_code(
        "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
        lambda: _build(replace(SET_WALL_THICKNESS_V1, canonical_operation="other.v1")),
    )
    _assert_code(
        "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
        lambda: _build(replace(SET_WALL_THICKNESS_V1, version="2.0.0")),
    )


def test_canonical_unit_mismatch_requires_no_implicit_conversion() -> None:
    changed_schema = {
        **SET_WALL_THICKNESS_V1.input_schema,
        "properties": {
            **SET_WALL_THICKNESS_V1.input_schema["properties"],
            "thickness": {
                **SET_WALL_THICKNESS_V1.input_schema["properties"]["thickness"],
                "properties": {
                    **SET_WALL_THICKNESS_V1.input_schema["properties"]["thickness"]["properties"],
                    "unit": {"const": "cm"},
                },
            },
        },
    }
    _assert_code(
        "CONVERGENCE_PROFILE_OPERATION_CONTRACT_MISMATCH",
        lambda: _build(replace(SET_WALL_THICKNESS_V1, input_schema=changed_schema)),
    )


def test_unsupported_verification_contract_and_operator_fail_closed() -> None:
    _assert_code(
        "CONVERGENCE_PROFILE_UNSUPPORTED",
        lambda: _build(
            replace(
                SET_WALL_THICKNESS_V1,
                verification_contract={"type": "HOST_READ_BACK"},
            )
        ),
    )
    changed_contract = {
        **SET_WALL_THICKNESS_V1.verification_contract,
        "assertions": [
            {
                **SET_WALL_THICKNESS_V1.verification_contract["assertions"][0],
                "operator": "APPROX_EQUALS_ARGUMENT",
            }
        ],
    }
    _assert_code(
        "CONVERGENCE_PROFILE_UNSUPPORTED",
        lambda: _build(replace(SET_WALL_THICKNESS_V1, verification_contract=changed_contract)),
    )


def test_tolerance_is_not_an_admissible_canonical_profile_feature() -> None:
    changed_contract = {
        **SET_WALL_THICKNESS_V1.verification_contract,
        "tolerance": {"value": 0.1, "unit": "mm"},
    }
    _assert_code(
        "CONVERGENCE_PROFILE_UNSUPPORTED",
        lambda: _build(replace(SET_WALL_THICKNESS_V1, verification_contract=changed_contract)),
    )
