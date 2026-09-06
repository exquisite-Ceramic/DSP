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


def fixtures(
    rule_id="R-1",
    slice_id="S-1",
    aspect_order=(CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
):
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
        rule_id,
        EntitySelector(entities=("WALL-001",)),
        aspect_order,
    )
    slice_rule = ExecutionSliceScopeRule(slice_id, "DOC-1", (rule_id,), (), ())
    return env, planning, snapshot_set, evidence, intent, rule, slice_rule


def body_hash(
    rule_id="R-1",
    slice_id="S-1",
    aspect_order=(CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    fingerprint="impact-fp",
):
    env, planning, snapshot_set, evidence, intent, rule, slice_rule = fixtures(
        rule_id,
        slice_id,
        aspect_order,
    )
    return compute_scope_body_hash(
        impact_analysis_fingerprint=fingerprint,
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=env,
        existing_entity_rules=(rule,),
        creation_rules=(),
        deletion_rules=(),
        propagation_bundle_ids=("PB-2", "PB-1"),
        execution_slice_scope_rules=(slice_rule,),
    )


def test_scope_hash_is_order_independent_and_opaque_ids_do_not_matter():
    left = body_hash(
        "R-A",
        "S-A",
        (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
    )
    right = body_hash(
        "R-Z",
        "S-Z",
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    assert left == right


def test_material_scope_change_changes_body_hash():
    assert body_hash() != body_hash(aspect_order=(CanonicalAspect.PLACEMENT,))
    assert body_hash() != body_hash(fingerprint="other-impact")


def test_v1_scope_body_hash_remains_byte_for_byte_stable():
    assert body_hash() == "ec160f2bcdc0bc8cc8df763ad15adba44af2bcaf90ab50c99dc80d8974835281"


def definition():
    env, planning, snapshot_set, evidence, intent, rule, slice_rule = fixtures()
    return ApprovalScopeDefinition(
        "DEF-1",
        "impact-fp",
        evidence,
        intent,
        planning,
        snapshot_set,
        env,
        (rule,),
        (),
        (),
        ("PB-2", "PB-1"),
        (slice_rule,),
        body_hash(),
    )


def test_bind_requires_lowercase_sha256_changeset_hash():
    for bad in ("TBD", "A" * 64, "abc"):
        with pytest.raises(ApprovalScopeError) as exc:
            bind_changeset(definition(), bad, "SCOPE-1")
        assert exc.value.code == "CHANGESET_HASH_INVALID"


def test_different_changeset_hash_changes_scope_hash_and_preserves_body():
    frozen = definition()
    first = bind_changeset(frozen, "0" * 64, "SCOPE-A")
    second = bind_changeset(frozen, "1" * 64, "SCOPE-B")
    assert first.scope_hash != second.scope_hash
    assert first.existing_entity_rules == frozen.existing_entity_rules
    assert first.execution_slice_scopes == frozen.execution_slice_scope_rules


def test_v2_topology_binding_rekeys_content_addressed_definition():
    frozen = definition()
    first = bind_topology_snapshot_v2(frozen, topology_snapshot_hash="a" * 64)
    second = bind_topology_snapshot_v2(frozen, topology_snapshot_hash="b" * 64)

    assert first.scope_body_hash != frozen.scope_body_hash
    assert first.scope_body_hash != second.scope_body_hash
    assert first.scope_definition_id == f"ASD-{first.scope_body_hash[:12]}"
    assert second.scope_definition_id == f"ASD-{second.scope_body_hash[:12]}"
    assert first.scope_definition_id != frozen.scope_definition_id
    validate_approval_scope_definition_v2(first)
    validate_approval_scope_definition_v2(second)


def test_v2_topology_binding_requires_lowercase_sha256_hash():
    for bad in ("TBD", "A" * 64, "abc"):
        with pytest.raises(ValueError):
            bind_topology_snapshot_v2(definition(), topology_snapshot_hash=bad)


def test_v2_boundary_is_integrity_checked_and_type_separated_from_v1():
    frozen = definition()
    v1_boundary = bind_changeset(frozen, "0" * 64, "SCOPE-V1")
    v2_definition = bind_topology_snapshot_v2(
        frozen,
        topology_snapshot_hash="a" * 64,
    )
    v2_boundary = bind_changeset_v2(v2_definition, "0" * 64, "SCOPE-V2")

    validate_approval_scope_boundary(v1_boundary)
    validate_approval_scope_boundary_v2(v2_boundary)

    with pytest.raises(TypeError):
        validate_approval_scope_boundary(v2_boundary)
    with pytest.raises(TypeError):
        validate_approval_scope_boundary_v2(v1_boundary)
