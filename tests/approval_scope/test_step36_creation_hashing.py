import hashlib
import json

import design_approval_scope as approval_scope
from design_approval_scope import (
    CanonicalAspect,
    CanonicalCreationContract,
    CanonicalEffectEvidence,
    CreationRule,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    compute_scope_body_hash,
)
from design_impact import (
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def _sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bindings():
    env = SemanticEnvironmentBinding("ENV-H", "env-hash")
    planning = PlanningSnapshotBinding("PS-H", "planning-hash", "DOC-H", env)
    snapshot_set = SnapshotSetBinding("SS-H", "set-hash", ("PS-H",), env)
    return env, planning, snapshot_set


def _legacy_material_hash() -> tuple[str, str]:
    env, planning, snapshot_set = _bindings()
    evidence = CanonicalEffectEvidence(
        "move.v1",
        "1.0.0",
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    intent = IntentBoundary(
        ("WALL-001",),
        ("GEOMETRY", "PLACEMENT"),
        ("RULE-A",),
    )
    rule = ExistingEntityRule(
        "ER-LEGACY",
        EntitySelector(entities=("WALL-001",)),
        (CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    slice_rule = ExecutionSliceScopeRule(
        "SLICE-LEGACY",
        "DOC-H",
        existing_rule_ids=(rule.rule_id,),
    )
    actual = compute_scope_body_hash(
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

    rule_hash = _sha(
        {
            "selector": {"entities": ["WALL-001"]},
            "allowed_aspects": ["GEOMETRY", "PLACEMENT"],
        }
    )
    expected = _sha(
        {
            "impact_analysis_fingerprint": "impact-fp",
            "canonical_effect_evidence": {
                "canonical_operation": "move.v1",
                "canonical_operation_version": "1.0.0",
                "allowed_aspects": ["GEOMETRY", "PLACEMENT"],
            },
            "intent_boundary": {
                "direct_targets": ["WALL-001"],
                "allowed_canonical_effects": ["GEOMETRY", "PLACEMENT"],
                "allowed_derived_rule_refs": ["RULE-A"],
            },
            "planning_snapshot_ref": {
                "snapshot_id": "PS-H",
                "snapshot_hash": "planning-hash",
                "document_ref": "DOC-H",
                "semantic_environment": {
                    "environment_id": "ENV-H",
                    "content_hash": "env-hash",
                },
            },
            "snapshot_set_ref": {
                "snapshot_set_id": "SS-H",
                "snapshot_set_hash": "set-hash",
                "member_snapshot_ids": ["PS-H"],
                "semantic_environment": {
                    "environment_id": "ENV-H",
                    "content_hash": "env-hash",
                },
            },
            "semantic_environment_ref": {
                "environment_id": "ENV-H",
                "content_hash": "env-hash",
            },
            "existing_entity_rules": [rule_hash],
            "creation_rules": [],
            "deletion_rules": [],
            "propagation_bundle_ids": ["PB-1"],
            "execution_slice_scope_rules": [
                {
                    "document_ref": "DOC-H",
                    "existing_rules": [rule_hash],
                    "creation_rules": [],
                    "deletion_rules": [],
                }
            ],
        }
    )
    return actual, expected


def _creation_rule(*, rule_id="REQUEST", max_count=1, derivation="RULE-OFFSET-WALL"):
    return CreationRule(
        rule_id=rule_id,
        canonical_operation="offset.v1",
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=max_count,
        required_derivation=derivation,
    )


def _creation_hash(rule: CreationRule, *, existence: bool = True) -> str:
    env, planning, snapshot_set = _bindings()
    contract = CanonicalCreationContract(
        ("ifc:IfcWall",),
        1,
        "RULE-OFFSET-WALL",
    )
    evidence = (
        CanonicalEffectEvidence(
            "offset.v1",
            "1.0.0",
            (),
            ("CREATE",),
            contract,
        )
        if existence
        else CanonicalEffectEvidence(
            "offset.v1",
            "1.0.0",
            (CanonicalAspect.GEOMETRY,),
        )
    )
    intent = IntentBoundary(
        ("WALL-001",),
        () if existence else ("GEOMETRY",),
        (),
        ("CREATE",) if existence else (),
    )
    slice_rule = ExecutionSliceScopeRule(
        "SLICE-CREATE",
        "DOC-H",
        creation_rule_ids=(rule.rule_id,),
    )
    return compute_scope_body_hash(
        impact_analysis_fingerprint="impact-create-fp",
        canonical_effect_evidence=evidence,
        intent_boundary=intent,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=env,
        existing_entity_rules=(),
        creation_rules=(rule,),
        deletion_rules=(),
        propagation_bundle_ids=(),
        execution_slice_scope_rules=(slice_rule,),
    )


def test_empty_existence_fields_preserve_exact_pre_step36_hash_material() -> None:
    actual, expected = _legacy_material_hash()
    assert actual == expected


def test_nonempty_existence_authority_changes_scope_hash_material() -> None:
    rule = _creation_rule()
    assert _creation_hash(rule, existence=True) != _creation_hash(rule, existence=False)


def test_creation_rule_id_is_deterministic_and_excludes_request_rule_id() -> None:
    helper = getattr(approval_scope, "creation_rule_id", None)
    assert callable(helper)

    first = _creation_rule(rule_id="REQUEST-A")
    second = _creation_rule(rule_id="REQUEST-B")
    expected_payload = {
        "canonical_operation": "offset.v1",
        "source_selector": {"entities": ["WALL-001"]},
        "entity_kinds": ["ifc:IfcWall"],
        "max_count": 1,
        "required_derivation": "RULE-OFFSET-WALL",
    }
    expected = f"CR-{_sha(expected_payload)[:12]}"

    assert helper(first) == expected
    assert helper(second) == expected


def test_creation_scope_hash_is_sensitive_to_count_and_derivation() -> None:
    base = _creation_hash(_creation_rule())
    assert base != _creation_hash(_creation_rule(max_count=2))
    assert base != _creation_hash(_creation_rule(derivation="RULE-OTHER"))
