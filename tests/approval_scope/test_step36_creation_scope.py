import hashlib
import json
from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopeError,
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalCreationContract,
    CanonicalEffectEvidence,
    CanonicalExistenceEffect,
    CreationRule,
    DeletionRule,
    EntitySelector,
    ExecutionSliceScopeRule,
)
from design_impact import (
    ImpactAnalysis,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


_UNSET = object()


def _creation_contract() -> CanonicalCreationContract:
    return CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def _requested_creation_rule(**overrides) -> CreationRule:
    values = {
        "rule_id": "REQUEST-1",
        "canonical_operation": "offset.v1",
        "source_selector": EntitySelector(entities=("WALL-001",)),
        "entity_kinds": ("ifc:IfcWall",),
        "max_count": 1,
        "required_derivation": "RULE-OFFSET-WALL",
    }
    values.update(overrides)
    return CreationRule(**values)


def _expected_creation_rule_id(rule: CreationRule) -> str:
    payload = {
        "canonical_operation": rule.canonical_operation,
        "source_selector": {"entities": list(rule.source_selector.entities)},
        "entity_kinds": list(rule.entity_kinds),
        "max_count": rule.max_count,
        "required_derivation": rule.required_derivation,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"CR-{hashlib.sha256(encoded).hexdigest()[:12]}"


def _offset_parts():
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "planning-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("SS-1", "set-hash", ("PS-1",), environment)
    impact = ImpactAnalysis(
        analysis_id="IA-OFFSET",
        canonical_operation="offset.v1",
        direct_targets=("WALL-001",),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        predicted_impacts=(),
        propagation_bundles=(),
        exceptions=(),
        analysis_fingerprint="impact-offset-fp",
    )
    evidence = CanonicalEffectEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        allowed_aspects=(),
        allowed_existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=_creation_contract(),
    )
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(),
        allowed_derived_rule_refs=(),
        allowed_existence_effects=("CREATE",),
    )
    return impact, evidence, intent


def _offset_request(
    *,
    rule: CreationRule | None = None,
    evidence: CanonicalEffectEvidence | None = None,
    intent: IntentBoundary | None = None,
    slices=_UNSET,
    delete: tuple[DeletionRule, ...] = (),
) -> ApprovalScopePlanRequest:
    impact, default_evidence, default_intent = _offset_parts()
    requested = rule or _requested_creation_rule()
    if slices is _UNSET:
        slices = (
            ExecutionSliceScopeRule(
                "SLICE-OFFSET",
                "DOC-1",
                creation_rule_ids=(_expected_creation_rule_id(requested),),
            ),
        )
    return ApprovalScopePlanRequest(
        canonical_effect_evidence=evidence or default_evidence,
        impact_analysis=impact,
        intent_boundary=intent or default_intent,
        direct_entity_effects=(),
        scope_effect_recipes=(),
        requested_creation_rules=(requested,),
        requested_deletion_rules=delete,
        execution_slice_scope_rules=tuple(slices),
    )


def _assert_code(code: str, request: ApprovalScopePlanRequest) -> None:
    with pytest.raises(ApprovalScopeError) as exc:
        ApprovalScopePlanner().plan(request)
    assert exc.value.code == code


def test_create_only_canonical_effect_evidence_allows_empty_aspects() -> None:
    evidence = CanonicalEffectEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        allowed_aspects=(),
        allowed_existence_effects=("CREATE", CanonicalExistenceEffect.CREATE),
        creation_contract=_creation_contract(),
    )

    assert evidence.allowed_aspects == ()
    assert evidence.allowed_existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert evidence.creation_contract == _creation_contract()


def test_canonical_effect_evidence_rejects_empty_authority() -> None:
    with pytest.raises(ValueError, match="effect authority"):
        CanonicalEffectEvidence(
            canonical_operation="offset.v1",
            canonical_operation_version="1.0.0",
            allowed_aspects=(),
        )


def test_planner_admits_exact_closed_creation_rule() -> None:
    request = _offset_request()
    requested = request.requested_creation_rules[0]
    expected_id = _expected_creation_rule_id(requested)

    result = ApprovalScopePlanner().plan(request)

    assert result.existing_entity_rules == ()
    assert result.deletion_rules == ()
    assert result.creation_rules == (
        CreationRule(
            rule_id=expected_id,
            canonical_operation="offset.v1",
            source_selector=EntitySelector(entities=("WALL-001",)),
            entity_kinds=("ifc:IfcWall",),
            max_count=1,
            required_derivation="RULE-OFFSET-WALL",
        ),
    )
    assert result.execution_slice_scope_rules[0].creation_rule_ids == (expected_id,)


@pytest.mark.parametrize(
    "rule",
    [
        _requested_creation_rule(canonical_operation="copy.v1"),
        _requested_creation_rule(
            source_selector=EntitySelector(entities=("WALL-001", "WALL-999"))
        ),
        _requested_creation_rule(entity_kinds=("ifc:IfcWall", "ifc:IfcDoor")),
        _requested_creation_rule(max_count=None),
        _requested_creation_rule(max_count=2),
        _requested_creation_rule(required_derivation="RULE-WRONG"),
    ],
)
def test_creation_rule_cannot_widen_or_change_canonical_authority(rule: CreationRule) -> None:
    _assert_code("SCOPE_RULE_INVALID", _offset_request(rule=rule))


def test_creation_requires_canonical_create_authority() -> None:
    evidence = CanonicalEffectEvidence(
        canonical_operation="offset.v1",
        canonical_operation_version="1.0.0",
        allowed_aspects=(CanonicalAspect.GEOMETRY,),
    )
    _assert_code("SCOPE_RULE_INVALID", _offset_request(evidence=evidence))


def test_creation_requires_intent_create_authority() -> None:
    _, _, intent = _offset_parts()
    intent = replace(intent, allowed_existence_effects=())
    _assert_code("SCOPE_RULE_INVALID", _offset_request(intent=intent))


def test_every_creation_rule_must_be_covered_by_slice_scope() -> None:
    _assert_code("SCOPE_SLICE_RULE_INVALID", _offset_request(slices=()))


def test_delete_remains_unsupported() -> None:
    deletion = DeletionRule("DELETE-1", EntitySelector(entities=("WALL-001",)))
    _assert_code(
        "SCOPE_EXISTENCE_EFFECT_UNSUPPORTED",
        _offset_request(delete=(deletion,)),
    )
