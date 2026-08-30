from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace

import pytest
from design_approval_scope import (
    ApprovalScopeDefinition,
    ApprovalScopeError,
    CanonicalAspect,
    CanonicalEffectEvidence,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    bind_changeset,
    compute_scope_body_hash,
    validate_approval_scope_boundary,
)
from design_impact import (
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def _definition() -> ApprovalScopeDefinition:
    environment = SemanticEnvironmentBinding("ENV-32", "environment-hash")
    planning = PlanningSnapshotBinding(
        "PS-32",
        "planning-hash",
        "DOC-32",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "SS-32",
        "snapshot-set-hash",
        ("PS-32",),
        environment,
    )
    evidence = CanonicalEffectEvidence(
        "move.v1",
        "1.0.0",
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    intent = IntentBoundary(
        ("WALL-032",),
        ("GEOMETRY", "PLACEMENT"),
        ("RULE-32",),
    )
    rule = ExistingEntityRule(
        "ER-32",
        EntitySelector(entities=("WALL-032",)),
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    slice_rule = ExecutionSliceScopeRule(
        "SSR-32",
        "DOC-32",
        (rule.rule_id,),
        (),
        (),
    )
    body_hash = compute_scope_body_hash(
        impact_analysis_fingerprint="impact-fingerprint-32",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-32",),
        execution_slice_scope_rules=(slice_rule,),
    )
    return ApprovalScopeDefinition(
        scope_definition_id="ASD-32",
        impact_analysis_fingerprint="impact-fingerprint-32",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-32",),
        execution_slice_scope_rules=(slice_rule,),
        scope_body_hash=body_hash,
    )


def _boundary():
    return bind_changeset(_definition(), "a" * 64, "SCOPE-32")


def _assert_integrity_failure(boundary) -> None:
    with pytest.raises(ApprovalScopeError) as exc:
        validate_approval_scope_boundary(boundary)
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"


def test_scope_definition_retains_intent_boundary_witness():
    names = {field.name for field in fields(ApprovalScopeDefinition)}
    assert "intent_boundary" in names


def test_final_boundary_retains_scope_commitment_witness():
    from design_approval_scope import ApprovalScopeBoundary

    names = {field.name for field in fields(ApprovalScopeBoundary)}
    assert {
        "scope_definition_id",
        "impact_analysis_fingerprint",
        "canonical_effect_evidence",
        "intent_boundary",
        "planning_snapshot_ref",
        "snapshot_set_ref",
        "semantic_environment_ref",
    }.issubset(names)


def test_valid_boundary_passes_integrity_validation():
    validate_approval_scope_boundary(_boundary())


def test_intent_tamper_fails_closed():
    boundary = _boundary()
    tampered = replace(
        boundary,
        intent_boundary=IntentBoundary(("OTHER",), ("PLACEMENT",), ()),
    )
    _assert_integrity_failure(tampered)


def test_planning_snapshot_tamper_fails_closed():
    boundary = _boundary()
    tampered = replace(
        boundary,
        planning_snapshot_ref=replace(
            boundary.planning_snapshot_ref,
            snapshot_hash="tampered-planning-hash",
        ),
    )
    _assert_integrity_failure(tampered)


def test_snapshot_set_tamper_fails_closed():
    boundary = _boundary()
    tampered = replace(
        boundary,
        snapshot_set_ref=replace(
            boundary.snapshot_set_ref,
            snapshot_set_hash="tampered-snapshot-set-hash",
        ),
    )
    _assert_integrity_failure(tampered)


def test_semantic_environment_tamper_fails_closed():
    boundary = _boundary()
    tampered = replace(
        boundary,
        semantic_environment_ref=SemanticEnvironmentBinding(
            "ENV-32",
            "tampered-environment-hash",
        ),
    )
    _assert_integrity_failure(tampered)


def test_rule_body_tamper_fails_closed():
    boundary = _boundary()
    rule = boundary.existing_entity_rules[0]
    tampered = replace(
        boundary,
        existing_entity_rules=(
            replace(rule, allowed_aspects=(CanonicalAspect.PLACEMENT,)),
        ),
    )
    _assert_integrity_failure(tampered)


def test_changeset_hash_tamper_fails_closed():
    _assert_integrity_failure(replace(_boundary(), changeset_hash="b" * 64))


def test_scope_hash_tamper_fails_closed():
    _assert_integrity_failure(replace(_boundary(), scope_hash="c" * 64))


def test_scope_hash_formula_is_unchanged():
    boundary = _boundary()
    encoded = json.dumps(
        {
            "scope_body_hash": boundary.scope_body_hash,
            "changeset_hash": boundary.changeset_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert boundary.scope_hash == hashlib.sha256(encoded).hexdigest()
