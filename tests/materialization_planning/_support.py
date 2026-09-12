from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    bind_changeset,
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
from design_convergence import ConvergenceProfileBuildRequest, build_convergence_profile
from design_impact import (
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
)
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
    SET_WALL_THICKNESS_V1_BINDING_RECIPE,
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


def _contract() -> CanonicalOperationContractEvidence:
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


def slot(
    slot_id: str,
    target: str,
    host_type: str,
    document_ref: str,
) -> MaterializationSlot:
    return MaterializationSlot(
        materialization_slot_id=slot_id,
        semantic_target_ref=target,
        required_host_type=host_type,
        document_ref=document_ref,
        requirement=MaterializationRequirement.REQUIRED,
    )


def topology(slots: tuple[MaterializationSlot, ...]) -> MaterializationTopologySnapshot:
    draft = MaterializationTopologySnapshot(
        topology_environment_id="TOPO-ENV-PHASE-I",
        topology_revision=1,
        slots=slots,
        topology_snapshot_hash="0" * 64,
    )
    return replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))


def build_case(
    *,
    targets: tuple[str, ...] = ("WALL-001",),
    topology_slots: tuple[MaterializationSlot, ...] | None = None,
):
    if topology_slots is None:
        topology_slots = (
            slot("MS-AUTOCAD", "WALL-001", "autocad", "DOC-AUTOCAD"),
            slot("MS-REVIT", "WALL-001", "revit", "DOC-REVIT"),
        )
    topology_snapshot = topology(topology_slots)

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
            context_snapshot_id="CS-MATERIALIZATION",
            context_snapshot_hash="context-hash-materialization",
            document_ref="DOC-CANONICAL",
            semantic_environment_ref="ENV-MATERIALIZATION",
            selection=targets,
            context_values={},
        ),
    )
    environment = SemanticEnvironmentBinding(
        "ENV-MATERIALIZATION",
        "env-hash-materialization",
    )
    planning = PlanningSnapshotBinding(
        "PS-MATERIALIZATION",
        "ps-hash-materialization",
        "DOC-CANONICAL",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-MATERIALIZATION",
        "pss-hash-materialization",
        (planning.snapshot_id,),
        environment,
    )
    intent = IntentBoundary(
        direct_targets=targets,
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
    rule_ids = tuple(direct_existing_rule_id(target) for target in targets)
    document_refs = tuple(sorted({item.document_ref for item in topology_slots}))
    scope_v1 = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                SET_WALL_THICKNESS_V1.canonical_operation,
                SET_WALL_THICKNESS_V1.version,
                (CanonicalAspect.PROPERTIES,),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=tuple(
                DirectEntityEffect(target, (CanonicalAspect.PROPERTIES,))
                for target in targets
            ),
            execution_slice_scope_rules=tuple(
                ExecutionSliceScopeRule(
                    f"SLICE-SCOPE-{index}",
                    document_ref,
                    existing_rule_ids=rule_ids,
                )
                for index, document_ref in enumerate(document_refs, start=1)
            ),
        )
    )
    scope_v2 = bind_topology_snapshot_v2(
        scope_v1,
        topology_snapshot.topology_snapshot_hash,
    )
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-MATERIALIZATION",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope_v2,
            canonical_operation_contracts=(_contract(),),
        )
    )
    boundary_v2 = bind_changeset_v2(
        scope_v2,
        changeset.changeset_hash,
        "SCOPE-MATERIALIZATION",
    )
    validate_changeset_integrity_v2(changeset, boundary_v2)
    profile = build_convergence_profile(
        ConvergenceProfileBuildRequest(
            canonical_changeset=changeset,
            approval_scope_boundary=boundary_v2,
            canonical_operation_definition=SET_WALL_THICKNESS_V1,
        )
    )
    boundary_v1 = bind_changeset(
        scope_v1,
        changeset.changeset_hash,
        "SCOPE-MATERIALIZATION-V1",
    )
    return SimpleNamespace(
        changeset=changeset,
        boundary_v2=boundary_v2,
        boundary_v1=boundary_v1,
        scope_v1=scope_v1,
        topology=topology_snapshot,
        profile=profile,
    )
