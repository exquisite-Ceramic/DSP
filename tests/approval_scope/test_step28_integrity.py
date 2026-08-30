from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

import design_approval_scope as approval_scope
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
)
from design_impact import (
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _definition() -> ApprovalScopeDefinition:
    env = SemanticEnvironmentBinding("ENV-32", "env-hash-32")
    planning = PlanningSnapshotBinding("PS-32", "planning-hash-32", "DOC-32", env)
    snapshot_set = SnapshotSetBinding("SS-32", "set-hash-32", ("PS-32",), env)
    evidence = CanonicalEffectEvidence(
        "move.v1",
        "1.0.0",
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    intent = IntentBoundary(
        ("WALL-032",),
        ("PLACEMENT", "GEOMETRY"),
        ("RULE-32",),
    )
    rule = ExistingEntityRule(
        "ER-32",
        EntitySelector(entities=("WALL-032",)),
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    slice_rule = ExecutionSliceScopeRule("SSR-32", "DOC-32", (rule.rule_id,), (), ())
    body_hash = compute_scope_body_hash(
        impact_analysis_fingerprint="impact-fingerprint-32",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=env,
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
        semantic_environment_ref=env,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-32",),
        execution_slice_scope_rules=(slice_rule,),
        scope_body_hash=body_hash,
    )


def _boundary():
    return bind_changeset(_definition(), "a" * 64, "SCOPE-32")


def _validator():
    return approval_scope.validate_approval_scope_boundary


def test_final_boundary_retains_every_scope_body_commitment():
    definition = _definition()
    boundary = bind_changeset(definition, "a" * 64, "SCOPE-32")

    assert boundary.scope_definition_id == definition.scope_definition_id
    assert boundary.impact_analysis_fingerprint == definition.impact_analysis_fingerprint
    assert boundary.canonical_effect_evidence == definition.canonical_effect_evidence
    assert boundary.intent_boundary == definition.intent_boundary
    assert boundary.planning_snapshot_ref == definition.planning_snapshot_ref
    assert boundary.snapshot_set_ref == definition.snapshot_set_ref
    assert boundary.semantic_environment_ref == definition.semantic_environment_ref


def test_valid_boundary_passes_public_integrity_validator():
    _validator()(_boundary())


@pytest.mark.parametrize(
    "mutator",
    (
        lambda boundary: replace(
            boundary,
            intent_boundary=IntentBoundary(("OTHER",), ("PLACEMENT",), ()),
        ),
        lambda boundary: replace(
            boundary,
            planning_snapshot_ref=replace(
                boundary.planning_snapshot_ref,
                snapshot_hash="tampered-planning-hash",
            ),
        ),
        lambda boundary: replace(
            boundary,
            snapshot_set_ref=replace(
                boundary.snapshot_set_ref,
                snapshot_set_hash="tampered-set-hash",
            ),
        ),
        lambda boundary: replace(
            boundary,
            semantic_environment_ref=SemanticEnvironmentBinding(
                "ENV-32",
                "tampered-env-hash",
            ),
        ),
        lambda boundary: replace(
            boundary,
            existing_entity_rules=(
                replace(
                    boundary.existing_entity_rules[0],
                    allowed_aspects=(CanonicalAspect.PLACEMENT,),
                ),
            ),
        ),
        lambda boundary: replace(boundary, changeset_hash="b" * 64),
        lambda boundary: replace(boundary, scope_hash="c" * 64),
    ),
)
def test_committed_boundary_tamper_fails_closed(mutator):
    with pytest.raises(ApprovalScopeError) as exc:
        _validator()(mutator(_boundary()))
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"


def test_scope_hash_formula_remains_body_plus_changeset_only():
    boundary = _boundary()
    expected = _sha256_json(
        {
            "scope_body_hash": boundary.scope_body_hash,
            "changeset_hash": boundary.changeset_hash,
        }
    )
    assert boundary.scope_hash == expected
