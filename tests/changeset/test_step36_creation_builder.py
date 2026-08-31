from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalCreationContract,
    CanonicalEffectEvidence,
    CanonicalExistenceEffect,
    CreationRule,
    EntitySelector,
    ExecutionSliceScopeRule,
    creation_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalOperationContractEvidence,
    ChangeSetBuilder,
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
from design_orchestrator.canonical_operations import OFFSET_V1
from design_orchestrator.parameter_binder import (
    OFFSET_V1_BINDING_RECIPE,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _creation_contract() -> CanonicalCreationContract:
    return CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def _intent() -> IntentBoundary:
    return IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(),
        allowed_derived_rule_refs=(),
        allowed_existence_effects=("CREATE",),
    )


def _bound_offset():
    binder = ParameterBinder((OFFSET_V1,), (OFFSET_V1_BINDING_RECIPE,))
    return binder.bind(
        OperationProposal(
            canonical_operation="offset.v1",
            intent_arguments={
                "distance": {"value": 300.0, "unit": "mm"},
                "side_point": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
            },
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-STEP36",
            context_snapshot_hash="context-hash-step36",
            document_ref="DOC-A",
            semantic_environment_ref="ENV-A",
            selection=("WALL-001",),
        ),
    )


def _planning_state():
    environment = SemanticEnvironmentBinding("ENV-A", "env-hash")
    planning = PlanningSnapshotBinding("PS-STEP36", "planning-hash", "DOC-A", environment)
    snapshot_set = SnapshotSetBinding("SS-STEP36", "set-hash", ("PS-STEP36",), environment)
    return environment, planning, snapshot_set


def _impact(bound):
    environment, planning, snapshot_set = _planning_state()
    return ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=_intent(),
        )
    )


def _scope(impact):
    requested = CreationRule(
        rule_id="REQUEST-OFFSET",
        canonical_operation="offset.v1",
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )
    admitted_id = creation_rule_id(requested)
    return ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                canonical_operation="offset.v1",
                canonical_operation_version="1.0.0",
                allowed_aspects=(),
                allowed_existence_effects=(CanonicalExistenceEffect.CREATE,),
                creation_contract=_creation_contract(),
            ),
            impact_analysis=impact,
            intent_boundary=_intent(),
            requested_creation_rules=(requested,),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-OFFSET",
                    "DOC-A",
                    creation_rule_ids=(admitted_id,),
                ),
            ),
        )
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


def _bound_evidence(bound) -> BoundOperationEvidence:
    arguments = dict(bound.arguments)
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


def _contract() -> CanonicalOperationContractEvidence:
    creation_contract = _creation_contract()
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=OFFSET_V1.canonical_operation,
        canonical_operation_version=OFFSET_V1.version,
        argument_schema=OFFSET_V1.input_schema,
        effects=OFFSET_V1.effects,
        verification_contract=OFFSET_V1.verification_contract,
        existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=creation_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=OFFSET_V1.canonical_operation,
        canonical_operation_version=OFFSET_V1.version,
        argument_schema=OFFSET_V1.input_schema,
        effects=OFFSET_V1.effects,
        verification_contract=OFFSET_V1.verification_contract,
        definition_fingerprint=fingerprint,
        existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=creation_contract,
    )


def _request() -> ChangeSetBuildRequest:
    bound = _bound_offset()
    impact = _impact(bound)
    scope = _scope(impact)
    return ChangeSetBuildRequest(
        task_id="TASK-STEP36-OFFSET",
        bound_operation_evidence=_bound_evidence(bound),
        impact_analysis=impact,
        approval_scope_definition=scope,
        canonical_operation_contracts=(_contract(),),
    )


def test_offset_create_binds_exact_creation_rule_into_root_operation() -> None:
    request = _request()
    creation_rule = request.approval_scope_definition.creation_rules[0]

    changeset = ChangeSetBuilder().build(request)

    assert changeset.root_operation.canonical_operation == "offset.v1"
    assert changeset.root_operation.targets == ("WALL-001",)
    assert changeset.root_operation.expected_effects == ()
    assert changeset.root_operation.expected_existence_effects == (
        CanonicalExistenceEffect.CREATE,
    )
    assert changeset.root_operation.scope_rule_ids == (creation_rule.rule_id,)
    assert changeset.validation_tasks == ()


@pytest.mark.parametrize("reverse", [False, True])
def test_offset_create_rejects_equally_compatible_creation_rules(reverse: bool) -> None:
    request = _request()
    original = request.approval_scope_definition.creation_rules[0]
    duplicate = CreationRule(
        rule_id=f"{original.rule_id}-AMBIGUOUS",
        canonical_operation=original.canonical_operation,
        source_selector=original.source_selector,
        entity_kinds=original.entity_kinds,
        max_count=original.max_count,
        required_derivation=original.required_derivation,
    )
    rules = (duplicate, original) if reverse else (original, duplicate)
    ambiguous_scope = replace(request.approval_scope_definition, creation_rules=rules)
    ambiguous_request = replace(request, approval_scope_definition=ambiguous_scope)

    with pytest.raises(ChangeSetError) as exc_info:
        ChangeSetBuilder().build(ambiguous_request)

    assert exc_info.value.code == "CHANGESET_SCOPE_MEMBERSHIP_AMBIGUOUS"
