from __future__ import annotations

from dataclasses import replace

import design_changeset
import pytest
from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    direct_existing_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalOperationContractEvidence,
    ChangeSetBuildRequest,
    ChangeSetError,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
)
from design_impact import (
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _bound_move(*, displacement=(100.0, 0.0, 0.0)):
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP29",
        context_snapshot_hash="context-hash-step29",
        document_ref="DOC-1",
        semantic_environment_ref="ENV-1",
        selection=("WALL-001",),
        context_values={},
    )
    return binder.bind(
        OperationProposal("move.v1", {"displacement": list(displacement)}),
        context,
    )


def _impact(bound=None):
    bound = bound or _bound_move()
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    request = ImpactAnalysisRequest(
        bound_operation=bound,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        intent_boundary=IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
        ),
    )
    return ImpactAnalyzer().analyze(request)


def _scope(impact, *, direct_aspects=(CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY)):
    rule_id = direct_existing_rule_id("WALL-001")
    return ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                "move.v1",
                "1.0.0",
                (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
            ),
            impact_analysis=impact,
            intent_boundary=IntentBoundary(
                direct_targets=("WALL-001",),
                allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
            ),
            direct_entity_effects=(DirectEntityEffect("WALL-001", direct_aspects),),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule("SLICE-SCOPE-1", "DOC-1", (rule_id,)),
            ),
        )
    )


def _contract() -> CanonicalOperationContractEvidence:
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
        definition_fingerprint=fingerprint,
    )


def _plain_planning_requirements(bound) -> dict[str, object]:
    requirements = bound.planning_requirements
    return {
        "operation_freshness_requirements": requirements.operation_freshness_requirements,
        "coverage_requirements": requirements.coverage_requirements,
        "assurance_requirements": requirements.assurance_requirements,
    }


def _plain_binding_evidence(bound) -> dict[str, object]:
    return {
        slot: {
            "binding_class": evidence.binding_class.value,
            "source": evidence.source,
            "source_ref": evidence.source_ref,
        }
        for slot, evidence in bound.binding_evidence.items()
    }


def _bound_evidence(bound=None, *, arguments=None) -> BoundOperationEvidence:
    bound = bound or _bound_move()
    arguments = dict(bound.arguments) if arguments is None else arguments
    planning_requirements = _plain_planning_requirements(bound)
    binding_evidence = _plain_binding_evidence(bound)
    material_fp = compute_bound_operation_fingerprint(
        bound.operation.canonical_operation,
        bound.operation.version,
        arguments,
    )
    evidence_fp = compute_bound_operation_evidence_fingerprint(
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
        bound_operation_fingerprint=material_fp,
        bound_operation_evidence_fingerprint=evidence_fp,
    )


def _request(*, bound_evidence=None, impact=None, scope=None) -> ChangeSetBuildRequest:
    impact = impact or _impact()
    return ChangeSetBuildRequest(
        task_id="TASK-29",
        bound_operation_evidence=bound_evidence or _bound_evidence(),
        impact_analysis=impact,
        approval_scope_definition=scope or _scope(impact),
        canonical_operation_contracts=(_contract(),),
    )


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ChangeSetError) as exc:
        operation()
    assert exc.value.code == code


def test_root_operation_is_materialized_from_exact_canonical_contract() -> None:
    result = design_changeset.ChangeSetBuilder().build(_request())

    assert result.root_operation.canonical_operation == "move.v1"
    assert result.root_operation.canonical_operation_version == "1.0.0"
    assert result.root_operation.targets == ("WALL-001",)
    assert result.root_operation.expected_effects == (
        CanonicalAspect.GEOMETRY,
        CanonicalAspect.PLACEMENT,
    )
    assert result.root_operation.operation_id.startswith("COP-")


def test_material_argument_swap_cannot_reuse_old_impact_analysis() -> None:
    old_impact = _impact()
    changed = _bound_evidence(
        arguments={"targets": ["WALL-001"], "displacement": [101.0, 0.0, 0.0]}
    )
    _assert_code(
        "CHANGESET_IMPACT_MISMATCH",
        lambda: design_changeset.ChangeSetBuilder().build(
            _request(bound_evidence=changed, impact=old_impact)
        ),
    )


def test_canonical_arguments_are_validated_against_exact_step23_schema() -> None:
    impact = _impact()
    invalid = _bound_evidence(
        arguments={"targets": ["WALL-001"], "displacement": [100.0, 0.0]}
    )
    impact = replace(impact, bound_operation_fingerprint=invalid.bound_operation_fingerprint)
    _assert_code(
        "CHANGESET_ARGUMENTS_INVALID",
        lambda: design_changeset.ChangeSetBuilder().build(
            _request(bound_evidence=invalid, impact=impact, scope=_scope(impact))
        ),
    )


def test_bound_targets_must_equal_step27_direct_targets() -> None:
    impact = _impact()
    changed = _bound_evidence(
        arguments={"targets": ["WALL-002"], "displacement": [100.0, 0.0, 0.0]}
    )
    impact = replace(impact, bound_operation_fingerprint=changed.bound_operation_fingerprint)
    _assert_code(
        "CHANGESET_TARGET_MISMATCH",
        lambda: design_changeset.ChangeSetBuilder().build(
            _request(bound_evidence=changed, impact=impact, scope=_scope(impact))
        ),
    )


def test_root_effects_must_be_fully_covered_by_explicit_scope_rules() -> None:
    impact = _impact()
    narrowed = _scope(impact, direct_aspects=(CanonicalAspect.PLACEMENT,))
    _assert_code(
        "CHANGESET_SCOPE_EFFECT_EXCEEDED",
        lambda: design_changeset.ChangeSetBuilder().build(_request(impact=impact, scope=narrowed)),
    )
