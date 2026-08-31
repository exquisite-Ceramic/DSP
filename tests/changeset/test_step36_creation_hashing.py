from __future__ import annotations

from design_approval_scope import (
    CanonicalAspect,
    CreationRule,
    DeletionRule,
    EntitySelector,
    ExistingEntityRule,
)
from design_changeset import canonical_hash, compute_scope_rule_fingerprint


def test_existing_rule_fingerprint_preserves_pre_step36_payload() -> None:
    rule = ExistingEntityRule(
        rule_id="ER-LEGACY",
        selector=EntitySelector(entities=("WALL-001",)),
        allowed_aspects=(CanonicalAspect.GEOMETRY, CanonicalAspect.PLACEMENT),
    )
    legacy_payload = {
        "selector": {"entities": ["WALL-001"]},
        "allowed_aspects": ["GEOMETRY", "PLACEMENT"],
    }

    assert compute_scope_rule_fingerprint(rule) == canonical_hash(legacy_payload)


def test_creation_rule_fingerprint_uses_typed_semantic_payload() -> None:
    rule = CreationRule(
        rule_id="CR-CONSTRUCTION-ID-IGNORED",
        canonical_operation="offset.v1",
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )
    expected_payload = {
        "rule_kind": "CREATION",
        "canonical_operation": "offset.v1",
        "source_selector": {"entities": ["WALL-001"]},
        "entity_kinds": ["ifc:IfcWall"],
        "max_count": 1,
        "required_derivation": "RULE-OFFSET-WALL",
    }

    assert compute_scope_rule_fingerprint(rule) == canonical_hash(expected_payload)


def test_creation_rule_fingerprint_excludes_construction_rule_id() -> None:
    first = CreationRule(
        rule_id="CR-FIRST",
        canonical_operation="offset.v1",
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )
    second = CreationRule(
        rule_id="CR-SECOND",
        canonical_operation="offset.v1",
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )

    assert compute_scope_rule_fingerprint(first) == compute_scope_rule_fingerprint(second)


def test_deletion_rule_fingerprint_has_typed_collision_safe_payload() -> None:
    rule = DeletionRule(
        rule_id="DR-CONSTRUCTION-ID-IGNORED",
        selector=EntitySelector(entities=("WALL-001",)),
    )
    expected_payload = {
        "rule_kind": "DELETION",
        "selector": {"entities": ["WALL-001"]},
    }

    assert compute_scope_rule_fingerprint(rule) == canonical_hash(expected_payload)
