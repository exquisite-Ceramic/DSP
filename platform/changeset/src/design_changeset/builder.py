"""Fail-closed deterministic builder for the immutable Step29 ChangeSet."""

from __future__ import annotations

from collections.abc import Mapping

from jsonschema import SchemaError, ValidationError, validate

from design_approval_scope import ApprovalScopeDefinition, CanonicalAspect
from design_impact import ImpactAnalysis

from .contracts import (
    ApprovalScopeDefinitionRef,
    BoundOperationEvidence,
    CanonicalChangeOperation,
    CanonicalChangeSet,
    CanonicalOperationContractEvidence,
    ChangePrecondition,
    ChangeSetBuildRequest,
    ChangeSetError,
    OperationOrigin,
    OperationSourceEvidence,
    OperationSourceKind,
    PreconditionKind,
    SemanticImpactEvidence,
    ValidationTask,
    ValidationTaskKind,
)
from .hashing import (
    canonical_hash,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_changeset_hash,
    compute_contract_definition_fingerprint,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)


def _error(code: str, message: str) -> None:
    raise ChangeSetError(code, message)


def _aspect_values(values) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value.value if isinstance(value, CanonicalAspect) else CanonicalAspect(str(value)).value
                for value in values
            }
        )
    )


def _targets(arguments: Mapping[str, object]) -> tuple[str, ...]:
    raw = arguments.get("targets")
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, (tuple, list)):
        _error("CHANGESET_TARGET_MISMATCH", "canonical arguments require a target sequence")
    targets: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            _error("CHANGESET_TARGET_MISMATCH", "canonical targets must be non-empty semantic ids")
        targets.append(item.strip())
    normalized = tuple(sorted(set(targets)))
    if not normalized:
        _error("CHANGESET_TARGET_MISMATCH", "canonical arguments require at least one target")
    return normalized


def _contract_index(
    contracts: tuple[CanonicalOperationContractEvidence, ...],
) -> dict[tuple[str, str], CanonicalOperationContractEvidence]:
    return {
        (contract.canonical_operation, contract.canonical_operation_version): contract
        for contract in contracts
    }


def _resolve_contract(
    request: ChangeSetBuildRequest,
) -> CanonicalOperationContractEvidence:
    bound = request.bound_operation_evidence
    contracts = _contract_index(request.canonical_operation_contracts)
    key = (bound.canonical_operation, bound.canonical_operation_version)
    contract = contracts.get(key)
    if contract is not None:
        return contract
    names = {item.canonical_operation for item in request.canonical_operation_contracts}
    if bound.canonical_operation not in names:
        _error(
            "CHANGESET_CANONICAL_OPERATION_UNKNOWN",
            f"no canonical contract evidence for {bound.canonical_operation}",
        )
    _error(
        "CHANGESET_CANONICAL_OPERATION_VERSION_MISMATCH",
        f"no canonical contract evidence for {bound.canonical_operation}@{bound.canonical_operation_version}",
    )


def _verify_contract_fingerprint(contract: CanonicalOperationContractEvidence) -> None:
    expected = compute_contract_definition_fingerprint(
        canonical_operation=contract.canonical_operation,
        canonical_operation_version=contract.canonical_operation_version,
        argument_schema=contract.argument_schema,
        effects=contract.effects,
        verification_contract=contract.verification_contract,
    )
    if expected != contract.definition_fingerprint:
        _error(
            "CHANGESET_INPUT_INVALID",
            "canonical operation contract evidence fingerprint does not match its semantic body",
        )


def _verify_bound_evidence(bound: BoundOperationEvidence) -> None:
    material = compute_bound_operation_fingerprint(
        bound.canonical_operation,
        bound.canonical_operation_version,
        bound.arguments,
    )
    if material != bound.bound_operation_fingerprint:
        _error(
            "CHANGESET_INPUT_INVALID",
            "bound operation fingerprint does not match the supplied operation material",
        )
    evidence = compute_bound_operation_evidence_fingerprint(
        canonical_operation=bound.canonical_operation,
        canonical_operation_version=bound.canonical_operation_version,
        arguments=bound.arguments,
        context_snapshot_id=bound.context_snapshot_id,
        context_snapshot_hash=bound.context_snapshot_hash,
        document_ref=bound.document_ref,
        semantic_environment_id=bound.semantic_environment_id,
        planning_requirements=bound.planning_requirements,
        binding_evidence=bound.binding_evidence,
    )
    if evidence != bound.bound_operation_evidence_fingerprint:
        _error(
            "CHANGESET_INPUT_INVALID",
            "bound operation evidence fingerprint does not match the supplied D6 projection",
        )


def _validate_upstream_join(
    bound: BoundOperationEvidence,
    impact: ImpactAnalysis,
    scope: ApprovalScopeDefinition,
    contract: CanonicalOperationContractEvidence,
) -> tuple[str, ...]:
    if bound.canonical_operation != impact.canonical_operation:
        _error("CHANGESET_IMPACT_MISMATCH", "bound operation does not match impact analysis")
    if bound.bound_operation_fingerprint != impact.bound_operation_fingerprint:
        _error(
            "CHANGESET_IMPACT_MISMATCH",
            "bound operation material is not the material analyzed by Step27",
        )
    if impact.analysis_fingerprint != scope.impact_analysis_fingerprint:
        _error("CHANGESET_SCOPE_MISMATCH", "approval scope does not bind this impact analysis")
    if (
        impact.planning_snapshot_ref != scope.planning_snapshot_ref
        or impact.snapshot_set_ref != scope.snapshot_set_ref
    ):
        _error("CHANGESET_SNAPSHOT_MISMATCH", "impact and approval scope planning state differ")
    if impact.semantic_environment_ref != scope.semantic_environment_ref:
        _error(
            "CHANGESET_SEMANTIC_ENVIRONMENT_MISMATCH",
            "impact and approval scope semantic environments differ",
        )
    if bound.semantic_environment_id != impact.semantic_environment_ref.environment_id:
        _error(
            "CHANGESET_SEMANTIC_ENVIRONMENT_MISMATCH",
            "D6 evidence and impact analysis semantic environments differ",
        )
    if bound.document_ref != impact.planning_snapshot_ref.document_ref:
        _error("CHANGESET_SNAPSHOT_MISMATCH", "D6 document does not match planning snapshot")

    direct_targets = _targets(bound.arguments)
    if direct_targets != tuple(sorted(impact.direct_targets)):
        _error("CHANGESET_TARGET_MISMATCH", "bound targets do not match Step27 direct targets")

    scope_evidence = scope.canonical_effect_evidence
    if scope_evidence.canonical_operation != bound.canonical_operation:
        _error("CHANGESET_SCOPE_MISMATCH", "scope canonical operation does not match root operation")
    if scope_evidence.canonical_operation_version != bound.canonical_operation_version:
        _error(
            "CHANGESET_SCOPE_MISMATCH",
            "scope canonical operation version does not match root operation",
        )
    if (
        contract.canonical_operation != bound.canonical_operation
        or contract.canonical_operation_version != bound.canonical_operation_version
    ):
        _error(
            "CHANGESET_CANONICAL_OPERATION_VERSION_MISMATCH",
            "canonical operation contract does not match root operation identity",
        )
    if _aspect_values(contract.effects) != _aspect_values(scope_evidence.allowed_aspects):
        _error(
            "CHANGESET_SCOPE_MISMATCH",
            "scope canonical effect evidence differs from the exact Step23 contract",
        )
    return direct_targets


def _validate_arguments(
    arguments: Mapping[str, object],
    contract: CanonicalOperationContractEvidence,
) -> None:
    try:
        validate(instance=dict(arguments), schema=dict(contract.argument_schema))
    except (ValidationError, SchemaError) as exc:
        _error("CHANGESET_ARGUMENTS_INVALID", f"canonical arguments do not satisfy contract: {exc.message}")


def _cover_scope(
    *,
    targets: tuple[str, ...],
    expected_effects: tuple[CanonicalAspect, ...],
    scope: ApprovalScopeDefinition,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected_rule_ids: set[str] = set()
    selected_rule_fingerprints: set[str] = set()
    required = {aspect.value for aspect in expected_effects}

    for target in targets:
        explicit = [
            rule
            for rule in scope.existing_entity_rules
            if rule.selector.entities and target in rule.selector.entities
        ]
        if not explicit:
            _error(
                "CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED",
                f"no explicit Step28 entity rule proves mutation authority for {target}",
            )
        covered: set[str] = set()
        for rule in explicit:
            covered.update(aspect.value for aspect in rule.allowed_aspects)
            selected_rule_ids.add(rule.rule_id)
            selected_rule_fingerprints.add(compute_scope_rule_fingerprint(rule))
        if not required.issubset(covered):
            _error(
                "CHANGESET_SCOPE_EFFECT_EXCEEDED",
                f"canonical effects exceed Step28 scope for {target}",
            )

    return tuple(sorted(selected_rule_ids)), tuple(sorted(selected_rule_fingerprints))


def _preconditions(bound: BoundOperationEvidence) -> tuple[ChangePrecondition, ...]:
    mapping = (
        ("operation_freshness_requirements", PreconditionKind.OPERATION_FRESHNESS),
        ("coverage_requirements", PreconditionKind.COVERAGE),
        ("assurance_requirements", PreconditionKind.ASSURANCE),
    )
    result: list[ChangePrecondition] = []
    subject = f"{bound.canonical_operation}@{bound.canonical_operation_version}"
    for key, kind in mapping:
        raw = bound.planning_requirements.get(key, ())
        if isinstance(raw, Mapping) or isinstance(raw, (str, bytes)):
            _error("CHANGESET_INPUT_INVALID", f"{key} must be a sequence of mappings")
        try:
            values = tuple(raw)
        except TypeError:
            _error("CHANGESET_INPUT_INVALID", f"{key} must be a sequence of mappings")
        for requirement in values:
            if not isinstance(requirement, Mapping):
                _error("CHANGESET_INPUT_INVALID", f"{key} entries must be mappings")
            result.append(
                ChangePrecondition(
                    kind=kind,
                    subject_ref=subject,
                    evidence_ref=canonical_hash(requirement),
                )
            )
    return tuple(sorted(result, key=lambda item: (item.kind.value, item.evidence_ref)))


def _semantic_impacts(impact: ImpactAnalysis) -> tuple[SemanticImpactEvidence, ...]:
    result = [
        SemanticImpactEvidence(
            source_semantic_id=item.source_semantic_id,
            affected_semantic_id=item.affected_semantic_id,
            dependency_ref=item.dependency_ref,
            propagation_owner=item.propagation_owner.value,
            propagation_action=item.propagation_action.value,
            requires_verification=item.requires_verification,
        )
        for item in impact.predicted_impacts
    ]
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.source_semantic_id,
                item.affected_semantic_id,
                item.dependency_ref,
            ),
        )
    )


def _validation_tasks(
    *,
    contract: CanonicalOperationContractEvidence,
    targets: tuple[str, ...],
    impact: ImpactAnalysis,
) -> tuple[ValidationTask, ...]:
    tasks: list[ValidationTask] = []
    operation_ref = f"{contract.canonical_operation}@{contract.canonical_operation_version}"
    if contract.verification_contract:
        contract_ref = canonical_hash(contract.verification_contract)
        semantic = {
            "kind": ValidationTaskKind.CANONICAL_OPERATION.value,
            "subject_semantic_ids": list(targets),
            "canonical_operation_ref": operation_ref,
            "contract_ref": contract_ref,
        }
        task_hash = canonical_hash(semantic)
        tasks.append(
            ValidationTask(
                validation_task_id=f"VT-{task_hash[:12]}",
                kind=ValidationTaskKind.CANONICAL_OPERATION,
                subject_semantic_ids=targets,
                canonical_operation_ref=operation_ref,
                contract_ref=contract_ref,
            )
        )
    for item in impact.predicted_impacts:
        if not item.requires_verification:
            continue
        contract_ref = canonical_hash(
            {
                "dependency_ref": item.dependency_ref,
                "propagation_owner": item.propagation_owner.value,
                "propagation_action": item.propagation_action.value,
                "requires_verification": True,
            }
        )
        semantic = {
            "kind": ValidationTaskKind.DEPENDENCY_VERIFICATION.value,
            "subject_semantic_ids": [item.affected_semantic_id],
            "dependency_ref": item.dependency_ref,
            "contract_ref": contract_ref,
        }
        task_hash = canonical_hash(semantic)
        tasks.append(
            ValidationTask(
                validation_task_id=f"VT-{task_hash[:12]}",
                kind=ValidationTaskKind.DEPENDENCY_VERIFICATION,
                subject_semantic_ids=(item.affected_semantic_id,),
                dependency_ref=item.dependency_ref,
                contract_ref=contract_ref,
            )
        )
    return tuple(sorted(tasks, key=lambda item: item.validation_task_id))


def _validation_semantic_payload(tasks: tuple[ValidationTask, ...]) -> list[dict[str, object]]:
    return [
        {
            "kind": task.kind.value,
            "subject_semantic_ids": list(task.subject_semantic_ids),
            "canonical_operation_ref": task.canonical_operation_ref,
            "dependency_ref": task.dependency_ref,
            "contract_ref": task.contract_ref,
        }
        for task in tasks
    ]


class ChangeSetBuilder:
    """Materialize one exact provider-neutral canonical transaction."""

    def build(self, request: ChangeSetBuildRequest) -> CanonicalChangeSet:
        if not isinstance(request, ChangeSetBuildRequest):
            _error("CHANGESET_INPUT_INVALID", "request must be ChangeSetBuildRequest")
        if not isinstance(request.impact_analysis, ImpactAnalysis):
            _error("CHANGESET_INPUT_INVALID", "impact_analysis must be public ImpactAnalysis")
        if not isinstance(request.approval_scope_definition, ApprovalScopeDefinition):
            _error(
                "CHANGESET_INPUT_INVALID",
                "approval_scope_definition must be ApprovalScopeDefinition",
            )

        bound = request.bound_operation_evidence
        impact = request.impact_analysis
        scope = request.approval_scope_definition
        _verify_bound_evidence(bound)
        contract = _resolve_contract(request)
        _verify_contract_fingerprint(contract)
        targets = _validate_upstream_join(bound, impact, scope, contract)
        _validate_arguments(bound.arguments, contract)

        expected_effects = tuple(contract.effects)
        scope_rule_ids, scope_rule_fingerprints = _cover_scope(
            targets=targets,
            expected_effects=expected_effects,
            scope=scope,
        )
        source = OperationSourceEvidence(
            source_kind=OperationSourceKind.ROOT_BOUND_OPERATION,
            source_fingerprint=bound.bound_operation_evidence_fingerprint,
        )
        operation_hash = compute_operation_semantic_hash(
            origin=OperationOrigin.ROOT,
            canonical_operation=bound.canonical_operation,
            canonical_operation_version=bound.canonical_operation_version,
            canonical_definition_fingerprint=contract.definition_fingerprint,
            targets=targets,
            arguments=bound.arguments,
            expected_effects=expected_effects,
            scope_rule_fingerprints=scope_rule_fingerprints,
            source_evidence=source,
        )
        root = CanonicalChangeOperation(
            operation_id=f"COP-{operation_hash[:12]}",
            origin=OperationOrigin.ROOT,
            canonical_operation=bound.canonical_operation,
            canonical_operation_version=bound.canonical_operation_version,
            canonical_definition_fingerprint=contract.definition_fingerprint,
            targets=targets,
            arguments=bound.arguments,
            expected_effects=expected_effects,
            scope_rule_ids=scope_rule_ids,
            source_evidence=source,
        )

        # Task 5 opens derived materialization. Until then, fail closed if callers
        # attempt to supply derived mutation material.
        if request.derived_materializations:
            _error(
                "CHANGESET_DERIVED_OPERATION_INVALID",
                "derived operation materialization is not enabled by this builder stage",
            )
        if scope.propagation_bundle_ids:
            _error(
                "CHANGESET_DERIVED_MATERIALIZATION_MISSING",
                "admitted deterministic propagation has not been materialized",
            )

        preconditions = _preconditions(bound)
        semantic_impacts = _semantic_impacts(impact)
        affected_entities = tuple(
            sorted(
                set(targets)
                | {item.affected_semantic_id for item in impact.predicted_impacts}
            )
        )
        validation_tasks = _validation_tasks(contract=contract, targets=targets, impact=impact)
        scope_ref = ApprovalScopeDefinitionRef(
            scope_definition_id=scope.scope_definition_id,
            scope_body_hash=scope.scope_body_hash,
        )

        semantic_body = {
            "task_id": request.task_id,
            "project_id": request.project_id,
            "planning_snapshot_ref": impact.planning_snapshot_ref,
            "snapshot_set_ref": impact.snapshot_set_ref,
            "semantic_environment_ref": impact.semantic_environment_ref,
            "impact_analysis_fingerprint": impact.analysis_fingerprint,
            "bound_operation_fingerprint": impact.bound_operation_fingerprint,
            "scope_body_hash": scope.scope_body_hash,
            "root_operation": operation_hash,
            "derived_operations": [],
            "change_dependencies": [],
            "preconditions": preconditions,
            "affected_entities": list(affected_entities),
            "semantic_impacts": semantic_impacts,
            "validation_tasks": _validation_semantic_payload(validation_tasks),
        }
        changeset_hash = compute_changeset_hash(semantic_body)
        return CanonicalChangeSet(
            changeset_id=f"CS-{changeset_hash[:12]}",
            task_id=request.task_id,
            project_id=request.project_id,
            planning_snapshot_ref=impact.planning_snapshot_ref,
            snapshot_set_ref=impact.snapshot_set_ref,
            semantic_environment_ref=impact.semantic_environment_ref,
            impact_analysis_fingerprint=impact.analysis_fingerprint,
            bound_operation_fingerprint=impact.bound_operation_fingerprint,
            approval_scope_definition_ref=scope_ref,
            root_operation=root,
            derived_operations=(),
            change_dependencies=(),
            preconditions=preconditions,
            affected_entities=affected_entities,
            semantic_impacts=semantic_impacts,
            validation_tasks=validation_tasks,
            changeset_hash=changeset_hash,
        )


__all__ = ["ChangeSetBuilder"]
