"""Fail-closed deterministic builder for the immutable Step29 ChangeSet."""

from __future__ import annotations

from collections.abc import Mapping

from design_approval_scope import ApprovalScopeDefinition, CanonicalAspect
from design_impact import ImpactAnalysis
from jsonschema import SchemaError, ValidationError, validate

from .contracts import (
    ApprovalScopeDefinitionRef,
    BoundOperationEvidence,
    CanonicalChangeOperation,
    CanonicalChangeSet,
    CanonicalOperationContractEvidence,
    ChangeDependency,
    ChangePrecondition,
    ChangeSetBuildRequest,
    ChangeSetError,
    DerivedOperationMaterialization,
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
    compute_proposed_change_hash,
    compute_scope_rule_fingerprint,
)


def _error(code: str, message: str) -> None:
    raise ChangeSetError(code, message)


def _aspect_values(values) -> tuple[str, ...]:
    result: set[str] = set()
    for value in values:
        raw = value.value if isinstance(value, CanonicalAspect) else str(value)
        try:
            result.add(CanonicalAspect(raw).value)
        except ValueError:
            _error("CHANGESET_INPUT_INVALID", f"unknown canonical aspect {raw!r}")
    return tuple(sorted(result))


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


def _resolve_contract_key(
    contracts: tuple[CanonicalOperationContractEvidence, ...],
    canonical_operation: str,
    canonical_operation_version: str,
) -> CanonicalOperationContractEvidence:
    contract = _contract_index(contracts).get((canonical_operation, canonical_operation_version))
    if contract is not None:
        return contract
    names = {item.canonical_operation for item in contracts}
    if canonical_operation not in names:
        _error(
            "CHANGESET_CANONICAL_OPERATION_UNKNOWN",
            f"no canonical contract evidence for {canonical_operation}",
        )
    _error(
        "CHANGESET_CANONICAL_OPERATION_VERSION_MISMATCH",
        f"no canonical contract evidence for {canonical_operation}@{canonical_operation_version}",
    )


def _resolve_root_contract(request: ChangeSetBuildRequest) -> CanonicalOperationContractEvidence:
    bound = request.bound_operation_evidence
    return _resolve_contract_key(
        request.canonical_operation_contracts,
        bound.canonical_operation,
        bound.canonical_operation_version,
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


def _validate_planning_state(impact: ImpactAnalysis, scope: ApprovalScopeDefinition) -> None:
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
    planning = impact.planning_snapshot_ref
    snapshot_set = impact.snapshot_set_ref
    environment = impact.semantic_environment_ref
    if planning.snapshot_id not in snapshot_set.member_snapshot_ids:
        _error("CHANGESET_SNAPSHOT_MISMATCH", "planning snapshot is not a SnapshotSet member")
    if planning.semantic_environment != environment or snapshot_set.semantic_environment != environment:
        _error(
            "CHANGESET_SEMANTIC_ENVIRONMENT_MISMATCH",
            "planning state does not share one semantic environment",
        )


def _validate_upstream_join(
    bound: BoundOperationEvidence,
    impact: ImpactAnalysis,
    scope: ApprovalScopeDefinition,
    contract: CanonicalOperationContractEvidence,
) -> tuple[str, ...]:
    _validate_planning_state(impact, scope)
    if bound.canonical_operation != impact.canonical_operation:
        _error("CHANGESET_IMPACT_MISMATCH", "bound operation does not match impact analysis")
    if bound.bound_operation_fingerprint != impact.bound_operation_fingerprint:
        _error(
            "CHANGESET_IMPACT_MISMATCH",
            "bound operation material is not the material analyzed by Step27",
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
        _error(
            "CHANGESET_ARGUMENTS_INVALID",
            f"canonical arguments do not satisfy contract: {exc.message}",
        )


def _cover_scope(
    *,
    targets: tuple[str, ...],
    expected_effects: tuple[CanonicalAspect, ...],
    scope: ApprovalScopeDefinition,
    requested_rule_ids: tuple[str, ...] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    known = {rule.rule_id: rule for rule in scope.existing_entity_rules}
    if requested_rule_ids is None:
        candidates = tuple(known.values())
    else:
        unknown = set(requested_rule_ids) - set(known)
        if unknown:
            _error(
                "CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED",
                f"scope rules are not present in Step28 definition: {sorted(unknown)}",
            )
        candidates = tuple(known[rule_id] for rule_id in requested_rule_ids)

    selected: dict[str, object] = {}
    required = {aspect.value for aspect in expected_effects}
    for target in targets:
        explicit = [
            rule
            for rule in candidates
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
            selected[rule.rule_id] = rule
        if not required.issubset(covered):
            _error(
                "CHANGESET_SCOPE_EFFECT_EXCEEDED",
                f"canonical effects exceed Step28 scope for {target}",
            )

    if requested_rule_ids is not None and set(requested_rule_ids) != set(selected):
        _error(
            "CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED",
            "derived operation scope_rule_ids include rules unrelated to its targets",
        )
    rule_ids = tuple(sorted(selected))
    fingerprints = tuple(
        sorted(compute_scope_rule_fingerprint(selected[rule_id]) for rule_id in rule_ids)
    )
    return rule_ids, fingerprints


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
        if isinstance(raw, (Mapping, str, bytes)):
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


def _canonical_validation_task(
    contract: CanonicalOperationContractEvidence,
    targets: tuple[str, ...],
) -> ValidationTask | None:
    if not contract.verification_contract:
        return None
    operation_ref = f"{contract.canonical_operation}@{contract.canonical_operation_version}"
    contract_ref = canonical_hash(contract.verification_contract)
    semantic = {
        "kind": ValidationTaskKind.CANONICAL_OPERATION.value,
        "subject_semantic_ids": list(targets),
        "canonical_operation_ref": operation_ref,
        "contract_ref": contract_ref,
    }
    task_hash = canonical_hash(semantic)
    return ValidationTask(
        validation_task_id=f"VT-{task_hash[:12]}",
        kind=ValidationTaskKind.CANONICAL_OPERATION,
        subject_semantic_ids=targets,
        canonical_operation_ref=operation_ref,
        contract_ref=contract_ref,
    )


def _validation_tasks(
    *,
    request: ChangeSetBuildRequest,
    root: CanonicalChangeOperation,
    derived: tuple[CanonicalChangeOperation, ...],
    impact: ImpactAnalysis,
) -> tuple[ValidationTask, ...]:
    tasks: list[ValidationTask] = []
    for operation in (root, *derived):
        contract = _resolve_contract_key(
            request.canonical_operation_contracts,
            operation.canonical_operation,
            operation.canonical_operation_version,
        )
        _verify_contract_fingerprint(contract)
        if contract.definition_fingerprint != operation.canonical_definition_fingerprint:
            _error(
                "CHANGESET_INPUT_INVALID",
                "materialized operation no longer matches its exact canonical contract evidence",
            )
        task = _canonical_validation_task(contract, operation.targets)
        if task is not None:
            tasks.append(task)

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
    ids = [task.validation_task_id for task in tasks]
    if len(set(ids)) != len(ids):
        _error("CHANGESET_INPUT_INVALID", "validation task semantic identity must be unique")
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


def _bundle_source_fingerprint(bundle, proposed_change_hash: str) -> str:
    return canonical_hash(
        {
            "bundle": {
                "rule_ref": bundle.rule_ref,
                "strength": bundle.strength.value,
                "propagation_owner": bundle.propagation_owner.value,
                "propagation_action": bundle.propagation_action.value,
                "source_entities": list(bundle.source_entities),
                "affected_entities": list(bundle.affected_entities),
                "deterministic": bundle.deterministic,
            },
            "proposed_change_hash": proposed_change_hash,
        }
    )


def _proposal_index(impact: ImpactAnalysis):
    bundles = {bundle.bundle_id: bundle for bundle in impact.propagation_bundles}
    proposal_by_key: dict[tuple[str, str], Mapping[str, object]] = {}
    global_hashes: set[str] = set()
    for bundle in impact.propagation_bundles:
        for proposal in bundle.proposed_changes:
            proposal_hash = compute_proposed_change_hash(proposal)
            key = (bundle.bundle_id, proposal_hash)
            if key in proposal_by_key or proposal_hash in global_hashes:
                _error(
                    "CHANGESET_DERIVED_PROPOSAL_DUPLICATE",
                    "Step27 proposed-change identity is ambiguous within one analysis",
                )
            proposal_by_key[key] = proposal
            global_hashes.add(proposal_hash)
    return bundles, proposal_by_key


def _materialize_derived(
    *,
    request: ChangeSetBuildRequest,
    root_operation: CanonicalChangeOperation,
    root_hash: str,
) -> tuple[
    tuple[CanonicalChangeOperation, ...],
    tuple[ChangeDependency, ...],
    tuple[str, ...],
]:
    impact = request.impact_analysis
    scope = request.approval_scope_definition
    bundles, proposals = _proposal_index(impact)
    admitted = set(scope.propagation_bundle_ids)
    missing_bundles = admitted - set(bundles)
    if missing_bundles:
        _error(
            "CHANGESET_SCOPE_MISMATCH",
            f"Step28 admits propagation bundles absent from Step27: {sorted(missing_bundles)}",
        )

    required = {
        key
        for key in proposals
        if key[0] in admitted and bundles[key[0]].deterministic
    }
    seen: set[tuple[str, str]] = set()
    built: list[tuple[str, CanonicalChangeOperation]] = []
    dependencies: list[tuple[str, ChangeDependency]] = []

    for materialization in request.derived_materializations:
        if not isinstance(materialization, DerivedOperationMaterialization):
            _error(
                "CHANGESET_DERIVED_OPERATION_INVALID",
                "derived materialization has an invalid contract type",
            )
        bundle = bundles.get(materialization.propagation_bundle_id)
        if bundle is None or bundle.bundle_id not in admitted:
            _error(
                "CHANGESET_DERIVED_BUNDLE_UNKNOWN",
                "derived materialization references an unknown or non-admitted bundle",
            )
        key = (bundle.bundle_id, materialization.proposed_change_hash)
        proposal = proposals.get(key)
        if proposal is None:
            _error(
                "CHANGESET_DERIVED_PROPOSAL_UNKNOWN",
                "derived materialization references an unknown Step27 proposal",
            )
        if key in seen:
            _error(
                "CHANGESET_DERIVED_PROPOSAL_DUPLICATE",
                "one Step27 proposal cannot be materialized twice",
            )
        seen.add(key)

        proposal_target = proposal.get("affected_semantic_id")
        if not isinstance(proposal_target, str) or not proposal_target.strip():
            _error(
                "CHANGESET_DERIVED_OPERATION_INVALID",
                "Step27 proposal lacks a canonical affected semantic id",
            )
        proposal_targets = (proposal_target.strip(),)
        if materialization.targets != proposal_targets:
            _error(
                "CHANGESET_TARGET_MISMATCH",
                "derived targets do not match the exact Step27 proposal",
            )
        if _targets(materialization.arguments) != materialization.targets:
            _error(
                "CHANGESET_TARGET_MISMATCH",
                "derived canonical arguments do not match declared targets",
            )

        contract = _resolve_contract_key(
            request.canonical_operation_contracts,
            materialization.canonical_operation,
            materialization.canonical_operation_version,
        )
        _verify_contract_fingerprint(contract)
        _validate_arguments(materialization.arguments, contract)
        expected_effects = tuple(contract.effects)
        scope_rule_ids, scope_rule_fingerprints = _cover_scope(
            targets=materialization.targets,
            expected_effects=expected_effects,
            scope=scope,
            requested_rule_ids=materialization.scope_rule_ids,
        )
        source = OperationSourceEvidence(
            source_kind=OperationSourceKind.DERIVED_PROPAGATION,
            source_fingerprint=_bundle_source_fingerprint(
                bundle,
                materialization.proposed_change_hash,
            ),
            propagation_bundle_id=bundle.bundle_id,
            proposed_change_hash=materialization.proposed_change_hash,
        )
        operation_hash = compute_operation_semantic_hash(
            origin=OperationOrigin.DERIVED,
            canonical_operation=contract.canonical_operation,
            canonical_operation_version=contract.canonical_operation_version,
            canonical_definition_fingerprint=contract.definition_fingerprint,
            targets=materialization.targets,
            arguments=materialization.arguments,
            expected_effects=expected_effects,
            scope_rule_fingerprints=scope_rule_fingerprints,
            source_evidence=source,
        )
        operation = CanonicalChangeOperation(
            operation_id=f"COP-{operation_hash[:12]}",
            origin=OperationOrigin.DERIVED,
            canonical_operation=contract.canonical_operation,
            canonical_operation_version=contract.canonical_operation_version,
            canonical_definition_fingerprint=contract.definition_fingerprint,
            targets=materialization.targets,
            arguments=materialization.arguments,
            expected_effects=expected_effects,
            scope_rule_ids=scope_rule_ids,
            source_evidence=source,
        )
        reason_ref = canonical_hash(
            {
                "root_operation_hash": root_hash,
                "derived_operation_hash": operation_hash,
                "propagation_bundle_id": bundle.bundle_id,
                "proposed_change_hash": materialization.proposed_change_hash,
            }
        )
        dependency = ChangeDependency(
            predecessor_operation_id=root_operation.operation_id,
            successor_operation_id=operation.operation_id,
            reason_ref=reason_ref,
        )
        built.append((operation_hash, operation))
        dependencies.append((operation_hash, dependency))

    missing = required - seen
    if missing:
        _error(
            "CHANGESET_DERIVED_MATERIALIZATION_MISSING",
            "every admitted deterministic Step27 proposal must be materialized exactly once",
        )
    extra = seen - required
    if extra:
        _error(
            "CHANGESET_DERIVED_BUNDLE_UNKNOWN",
            "derived materialization exceeds the admitted Step28 propagation scope",
        )

    built.sort(key=lambda pair: pair[0])
    dependencies.sort(key=lambda pair: pair[0])
    return (
        tuple(operation for _, operation in built),
        tuple(dependency for _, dependency in dependencies),
        tuple(operation_hash for operation_hash, _ in built),
    )


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
        contract = _resolve_root_contract(request)
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
        root_hash = compute_operation_semantic_hash(
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
            operation_id=f"COP-{root_hash[:12]}",
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

        derived, dependencies, derived_hashes = _materialize_derived(
            request=request,
            root_operation=root,
            root_hash=root_hash,
        )
        preconditions = _preconditions(bound)
        semantic_impacts = _semantic_impacts(impact)
        affected_entities = tuple(
            sorted(set(targets) | {item.affected_semantic_id for item in impact.predicted_impacts})
        )
        validation_tasks = _validation_tasks(
            request=request,
            root=root,
            derived=derived,
            impact=impact,
        )
        scope_ref = ApprovalScopeDefinitionRef(
            scope_definition_id=scope.scope_definition_id,
            scope_body_hash=scope.scope_body_hash,
        )
        dependency_payloads = [
            {
                "predecessor_operation_hash": root_hash,
                "successor_operation_hash": operation_hash,
                "reason_ref": dependency.reason_ref,
            }
            for operation_hash, dependency in zip(derived_hashes, dependencies, strict=True)
        ]
        semantic_body = {
            "task_id": request.task_id,
            "project_id": request.project_id,
            "planning_snapshot_ref": impact.planning_snapshot_ref,
            "snapshot_set_ref": impact.snapshot_set_ref,
            "semantic_environment_ref": impact.semantic_environment_ref,
            "impact_analysis_fingerprint": impact.analysis_fingerprint,
            "bound_operation_fingerprint": impact.bound_operation_fingerprint,
            "scope_body_hash": scope.scope_body_hash,
            "root_operation": root_hash,
            "derived_operations": list(derived_hashes),
            "change_dependencies": dependency_payloads,
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
            derived_operations=derived,
            change_dependencies=dependencies,
            preconditions=preconditions,
            affected_entities=affected_entities,
            semantic_impacts=semantic_impacts,
            validation_tasks=validation_tasks,
            changeset_hash=changeset_hash,
        )


__all__ = ["ChangeSetBuilder"]
