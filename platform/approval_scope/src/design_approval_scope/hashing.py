"""Deterministic semantic hashing for Step28 approval scope."""
from __future__ import annotations

import hashlib
import json
import re

from .contracts import (
    ApprovalScopeBoundary,
    ApprovalScopeDefinition,
    ApprovalScopeError,
    CanonicalEffectEvidence,
    CreationRule,
    DeletionRule,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _enum_value(value):
    return getattr(value, "value", value)


def _selector_payload(selector: EntitySelector) -> dict[str, object]:
    if selector.entities:
        return {"entities": list(selector.entities)}
    assert selector.predicate is not None
    return {
        "predicate": {
            "all_of": [
                {
                    "field": term.field.value,
                    "operator": term.operator.value,
                    "values": list(term.values),
                }
                for term in selector.predicate.all_of
            ]
        }
    }


def _existing_payload(rule: ExistingEntityRule) -> dict[str, object]:
    return {
        "selector": _selector_payload(rule.selector),
        "allowed_aspects": [aspect.value for aspect in rule.allowed_aspects],
    }


def _creation_payload(rule: CreationRule) -> dict[str, object]:
    return {
        "canonical_operation": rule.canonical_operation,
        "source_selector": _selector_payload(rule.source_selector),
        "entity_kinds": list(rule.entity_kinds),
        "max_count": rule.max_count,
        "required_derivation": rule.required_derivation,
    }


def _deletion_payload(rule: DeletionRule) -> dict[str, object]:
    return {"selector": _selector_payload(rule.selector)}


def _semantic_rule_maps(existing_rules, creation_rules, deletion_rules):
    existing = {rule.rule_id: _sha256_json(_existing_payload(rule)) for rule in existing_rules}
    creation = {rule.rule_id: _sha256_json(_creation_payload(rule)) for rule in creation_rules}
    deletion = {rule.rule_id: _sha256_json(_deletion_payload(rule)) for rule in deletion_rules}
    return existing, creation, deletion


def _slice_payload(
    rule: ExecutionSliceScopeRule,
    existing_map: dict[str, str],
    creation_map: dict[str, str],
    deletion_map: dict[str, str],
) -> dict[str, object]:
    return {
        "document_ref": rule.document_ref,
        "existing_rules": sorted({existing_map[rule_id] for rule_id in rule.existing_rule_ids}),
        "creation_rules": sorted({creation_map[rule_id] for rule_id in rule.creation_rule_ids}),
        "deletion_rules": sorted({deletion_map[rule_id] for rule_id in rule.deletion_rule_ids}),
    }


def _environment_payload(env) -> dict[str, object]:
    return {
        "environment_id": env.environment_id,
        "content_hash": env.content_hash,
    }


def _planning_payload(planning) -> dict[str, object]:
    return {
        "snapshot_id": planning.snapshot_id,
        "snapshot_hash": planning.snapshot_hash,
        "document_ref": planning.document_ref,
        "semantic_environment": _environment_payload(planning.semantic_environment),
    }


def _snapshot_set_payload(snapshot_set) -> dict[str, object]:
    return {
        "snapshot_set_id": snapshot_set.snapshot_set_id,
        "snapshot_set_hash": snapshot_set.snapshot_set_hash,
        "member_snapshot_ids": sorted(snapshot_set.member_snapshot_ids),
        "semantic_environment": _environment_payload(snapshot_set.semantic_environment),
    }


def _canonical_effect_payload(evidence: CanonicalEffectEvidence) -> dict[str, object]:
    return {
        "canonical_operation": evidence.canonical_operation,
        "canonical_operation_version": evidence.canonical_operation_version,
        "allowed_aspects": [aspect.value for aspect in evidence.allowed_aspects],
    }


def _intent_payload(intent) -> dict[str, object]:
    return {
        "direct_targets": sorted(intent.direct_targets),
        "allowed_canonical_effects": sorted(
            str(_enum_value(value)) for value in intent.allowed_canonical_effects
        ),
        "allowed_derived_rule_refs": sorted(intent.allowed_derived_rule_refs),
    }


def compute_scope_body_hash(
    *,
    impact_analysis_fingerprint: str,
    canonical_effect_evidence: CanonicalEffectEvidence,
    intent_boundary,
    planning_snapshot_ref,
    snapshot_set_ref,
    semantic_environment_ref,
    existing_entity_rules: tuple[ExistingEntityRule, ...],
    creation_rules: tuple[CreationRule, ...],
    deletion_rules: tuple[DeletionRule, ...],
    propagation_bundle_ids: tuple[str, ...],
    execution_slice_scope_rules: tuple[ExecutionSliceScopeRule, ...],
) -> str:
    existing_map, creation_map, deletion_map = _semantic_rule_maps(
        existing_entity_rules,
        creation_rules,
        deletion_rules,
    )
    slice_payloads = [
        _slice_payload(rule, existing_map, creation_map, deletion_map)
        for rule in execution_slice_scope_rules
    ]
    payload = {
        "impact_analysis_fingerprint": impact_analysis_fingerprint,
        "canonical_effect_evidence": _canonical_effect_payload(canonical_effect_evidence),
        "intent_boundary": _intent_payload(intent_boundary),
        "planning_snapshot_ref": _planning_payload(planning_snapshot_ref),
        "snapshot_set_ref": _snapshot_set_payload(snapshot_set_ref),
        "semantic_environment_ref": _environment_payload(semantic_environment_ref),
        "existing_entity_rules": sorted(set(existing_map.values())),
        "creation_rules": sorted(set(creation_map.values())),
        "deletion_rules": sorted(set(deletion_map.values())),
        "propagation_bundle_ids": sorted(set(propagation_bundle_ids)),
        "execution_slice_scope_rules": sorted(
            slice_payloads,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        ),
    }
    return _sha256_json(payload)


def bind_changeset(
    scope_definition: ApprovalScopeDefinition,
    changeset_hash: str,
    scope_id: str,
) -> ApprovalScopeBoundary:
    if re.fullmatch(r"[0-9a-f]{64}", changeset_hash) is None:
        raise ApprovalScopeError(
            "CHANGESET_HASH_INVALID",
            "changeset_hash must be a lowercase 64-hex SHA-256 digest",
        )
    scope_hash = _sha256_json(
        {
            "scope_body_hash": scope_definition.scope_body_hash,
            "changeset_hash": changeset_hash,
        }
    )
    return ApprovalScopeBoundary(
        scope_id=scope_id,
        scope_definition_id=scope_definition.scope_definition_id,
        impact_analysis_fingerprint=scope_definition.impact_analysis_fingerprint,
        canonical_effect_evidence=scope_definition.canonical_effect_evidence,
        intent_boundary=scope_definition.intent_boundary,
        planning_snapshot_ref=scope_definition.planning_snapshot_ref,
        snapshot_set_ref=scope_definition.snapshot_set_ref,
        semantic_environment_ref=scope_definition.semantic_environment_ref,
        changeset_hash=changeset_hash,
        scope_body_hash=scope_definition.scope_body_hash,
        existing_entity_rules=scope_definition.existing_entity_rules,
        creation_rules=scope_definition.creation_rules,
        deletion_rules=scope_definition.deletion_rules,
        propagation_bundle_ids=scope_definition.propagation_bundle_ids,
        execution_slice_scopes=scope_definition.execution_slice_scope_rules,
        scope_hash=scope_hash,
    )


def validate_approval_scope_boundary(boundary: ApprovalScopeBoundary) -> None:
    """Validate a final Step28 boundary. Integrity checks are added in Step32 Task 1."""
    if not isinstance(boundary, ApprovalScopeBoundary):
        raise TypeError("boundary must be ApprovalScopeBoundary")
