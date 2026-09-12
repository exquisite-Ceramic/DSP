from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    ApprovalScopeDefinition,
    ApprovalScopeDefinitionV2,
    ApprovalScopeError,
    CanonicalAspect,
    CanonicalEffectEvidence,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    bind_changeset,
    bind_changeset_v2,
    bind_topology_snapshot_v2,
    compute_scope_body_hash,
    validate_approval_scope_boundary,
    validate_approval_scope_boundary_v2,
    validate_approval_scope_definition_v2,
)
from design_impact import (
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def _definition() -> ApprovalScopeDefinition:
    env = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "planning-hash", "DOC-1", env)
    snapshot_set = SnapshotSetBinding("SS-1", "set-hash", ("PS-1", "PS-2"), env)
    evidence = CanonicalEffectEvidence(
        "move.v1",
        "1.0.0",
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    intent = IntentBoundary(
        ("WALL-001",),
        ("PLACEMENT", "GEOMETRY"),
        ("RULE-A",),
    )
    rule = ExistingEntityRule(
        "R-1",
        EntitySelector(entities=("WALL-001",)),
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    slice_rule = ExecutionSliceScopeRule("S-1", "DOC-1", ("R-1",), (), ())
    body_hash = compute_scope_body_hash(
        impact_analysis_fingerprint="impact-fp",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=env,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-1",),
        execution_slice_scope_rules=(slice_rule,),
    )
    return ApprovalScopeDefinition(
        scope_definition_id=f"ASD-{body_hash[:12]}",
        impact_analysis_fingerprint="impact-fp",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=env,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-1",),
        execution_slice_scope_rules=(slice_rule,),
        scope_body_hash=body_hash,
    )


def test_v2_definition_rekeys_content_addressed_identity_when_topology_changes():
    v1 = _definition()
    first = bind_topology_snapshot_v2(v1, topology_snapshot_hash="a" * 64)
    second = bind_topology_snapshot_v2(v1, topology_snapshot_hash="b" * 64)

    assert isinstance(first, ApprovalScopeDefinitionV2)
    assert first.scope_body_hash != v1.scope_body_hash
    assert first.scope_body_hash != second.scope_body_hash
    assert first.scope_definition_id == f"ASD-{first.scope_body_hash[:12]}"
    assert second.scope_definition_id == f"ASD-{second.scope_body_hash[:12]}"
    assert first.scope_definition_id != v1.scope_definition_id
    assert first.topology_snapshot_hash == "a" * 64
    validate_approval_scope_definition_v2(first)
    validate_approval_scope_definition_v2(second)


def test_v2_definition_rejects_malformed_topology_hash():
    for bad in ("TBD", "A" * 64, "abc"):
        with pytest.raises(ValueError):
            bind_topology_snapshot_v2(_definition(), topology_snapshot_hash=bad)


def test_v2_definition_validator_rejects_reused_or_tampered_identity():
    v1 = _definition()
    v2 = bind_topology_snapshot_v2(v1, topology_snapshot_hash="a" * 64)

    with pytest.raises(ApprovalScopeError) as exc:
        validate_approval_scope_definition_v2(
            replace(v2, scope_definition_id=v1.scope_definition_id)
        )
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"


def test_v2_boundary_binds_changeset_to_v2_body_and_topology():
    definition = bind_topology_snapshot_v2(
        _definition(),
        topology_snapshot_hash="a" * 64,
    )
    first = bind_changeset_v2(definition, "0" * 64, "SCOPE-A")
    second = bind_changeset_v2(definition, "1" * 64, "SCOPE-B")

    assert isinstance(first, ApprovalScopeBoundaryV2)
    assert first.scope_definition_id == definition.scope_definition_id
    assert first.scope_body_hash == definition.scope_body_hash
    assert first.topology_snapshot_hash == definition.topology_snapshot_hash
    assert first.scope_hash != second.scope_hash
    validate_approval_scope_boundary_v2(first)
    validate_approval_scope_boundary_v2(second)


def test_v2_boundary_validator_rejects_topology_substitution():
    definition = bind_topology_snapshot_v2(
        _definition(),
        topology_snapshot_hash="a" * 64,
    )
    boundary = bind_changeset_v2(definition, "0" * 64, "SCOPE-A")

    with pytest.raises(ApprovalScopeError) as exc:
        validate_approval_scope_boundary_v2(
            replace(boundary, topology_snapshot_hash="b" * 64)
        )
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"


def test_v1_and_v2_boundary_validators_remain_type_separated():
    v1_definition = _definition()
    v1_boundary = bind_changeset(v1_definition, "0" * 64, "SCOPE-V1")
    v2_definition = bind_topology_snapshot_v2(
        v1_definition,
        topology_snapshot_hash="a" * 64,
    )
    v2_boundary = bind_changeset_v2(v2_definition, "0" * 64, "SCOPE-V2")

    validate_approval_scope_boundary(v1_boundary)
    validate_approval_scope_boundary_v2(v2_boundary)

    with pytest.raises(TypeError):
        validate_approval_scope_boundary(v2_boundary)
    with pytest.raises(TypeError):
        validate_approval_scope_boundary_v2(v1_boundary)
