"""Deterministic semantic hashing for Step28 approval scope."""
from __future__ import annotations

import hashlib
import json
import re

from .contracts import (
    ApprovalScopeBoundary,
    ApprovalScopeBoundaryV2,
    ApprovalScopeDefinition,
    ApprovalScopeDefinitionV2,
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


def creation_rule_id(rule: CreationRule) -> str:
    """Return the stable semantic id for one admitted creation rule."""
    if not isinstance(rule, CreationRule):
        raise TypeError("rule must be CreationRule")
    return f"CR-{_sha256_json(_creation_payload(rule))[:12]}"


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
    payload: dict[str, object] = {
        "canonical_operation": evidence.canonical_operation,
        "canonical_operation_version": evidence.canonical_operation_version,
        "allowed_aspects": [aspect.value for aspect in evidence.allowed_aspects],
    }
    existence_effects = tuple(getattr(evidence, "allowed_existence_effects", ()))
    if existence_effects:
        payload["allowed_existence_effects"] = sorted(
            str(_enum_value(value)) for value in existence_effects
        )
        contract = getattr(evidence, "creation_contract", None)
        if contract is not None:
            payload["creation_contract"] = {
                "entity_kinds": list(contract.entity_kinds),
                "max_count": contract.max_count,
                "required_derivation": contract.required_derivation,
            }
    return payload


def _intent_payload(intent) -> dict[str, object]:
    payload: dict[str, object] = {
        "direct_targets": sorted(intent.direct_targets),
        "allowed_canonical_effects": sorted(
            str(_enum_value(value)) for value in intent.allowed_canonical_effects
        ),
        "allowed_derived_rule_refs": sorted(intent.allowed_derived_rule_refs),
    }
    existence_effects = tuple(getattr(intent, "allowed_existence_effects", ()))
    if existence_effects:
        payload["allowed_existence_effects"] = sorted(
            str(_enum_value(value)) for value in existence_effects
        )
    return payload


def _scope_body_payload(
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
) -> dict[str, object]:
    existing_map, creation_map, deletion_map = _semantic_rule_maps(
        existing_entity_rules,
        creation_rules,
        deletion_rules,
    )
    slice_payloads = [
        _slice_payload(rule, existing_map, creation_map, deletion_map)
        for rule in execution_slice_scope_rules
    ]
    return {
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
    return _sha256_json(
        _scope_body_payload(
            impact_analysis_fingerprint=impact_analysis_fingerprint,
            canonical_effect_evidence=canonical_effect_evidence,
            intent_boundary=intent_boundary,
            planning_snapshot_ref=planning_snapshot_ref,
            snapshot_set_ref=snapshot_set_ref,
            semantic_environment_ref=semantic_environment_ref,
            existing_entity_rules=existing_entity_rules,
            creation_rules=creation_rules,
            deletion_rules=deletion_rules,
            propagation_bundle_ids=propagation_bundle_ids,
            execution_slice_scope_rules=execution_slice_scope_rules,
        )
    )


def _require_digest(value: str, *, field_name: str, code: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ApprovalScopeError(
            code,
            f"{field_name} must be a lowercase 64-hex SHA-256 digest",
        )
    return value


def _compute_scope_body_hash_v2_from_fields(
    *,
    impact_analysis_fingerprint: str,
    canonical_effect_evidence: CanonicalEffectEvidence,
    intent_boundary,
    planning_snapshot_ref,
    snapshot_set_ref,
    semantic_environment_ref,
    topology_snapshot_hash: str,
    existing_entity_rules: tuple[ExistingEntityRule, ...],
    creation_rules: tuple[CreationRule, ...],
    deletion_rules: tuple[DeletionRule, ...],
    propagation_bundle_ids: tuple[str, ...],
    execution_slice_scope_rules: tuple[ExecutionSliceScopeRule, ...],
) -> str:
    topology_hash = _require_digest(
        topology_snapshot_hash,
        field_name="topology_snapshot_hash",
        code="TOPOLOGY_SNAPSHOT_HASH_INVALID",
    )
    return _sha256_json(
        {
            "version": "APPROVAL_SCOPE_V2",
            "scope_body": _scope_body_payload(
                impact_analysis_fingerprint=impact_analysis_fingerprint,
                canonical_effect_evidence=canonical_effect_evidence,
                intent_boundary=intent_boundary,
                planning_snapshot_ref=planning_snapshot_ref,
                snapshot_set_ref=snapshot_set_ref,
                semantic_environment_ref=semantic_environment_ref,
                existing_entity_rules=existing_entity_rules,
                creation_rules=creation_rules,
                deletion_rules=deletion_rules,
                propagation_bundle_ids=propagation_bundle_ids,
                execution_slice_scope_rules=execution_slice_scope_rules,
            ),
            "topology_snapshot_hash": topology_hash,
        }
    )


def compute_scope_body_hash_v2(
    definition: ApprovalScopeDefinition,
    topology_snapshot_hash: str,
) -> str:
    """从完整 V1 语义体与拓扑快照生成 Step28 V2 内容哈希。"""
    if not isinstance(definition, ApprovalScopeDefinition):
        raise TypeError("definition must be ApprovalScopeDefinition")
    return _compute_scope_body_hash_v2_from_fields(
        impact_analysis_fingerprint=definition.impact_analysis_fingerprint,
        canonical_effect_evidence=definition.canonical_effect_evidence,
        intent_boundary=definition.intent_boundary,
        planning_snapshot_ref=definition.planning_snapshot_ref,
        snapshot_set_ref=definition.snapshot_set_ref,
        semantic_environment_ref=definition.semantic_environment_ref,
        topology_snapshot_hash=topology_snapshot_hash,
        existing_entity_rules=definition.existing_entity_rules,
        creation_rules=definition.creation_rules,
        deletion_rules=definition.deletion_rules,
        propagation_bundle_ids=definition.propagation_bundle_ids,
        execution_slice_scope_rules=definition.execution_slice_scope_rules,
    )


def bind_topology_snapshot_v2(
    definition: ApprovalScopeDefinition,
    topology_snapshot_hash: str,
) -> ApprovalScopeDefinitionV2:
    """把不可变拓扑快照绑定进新的 Step28 V2 定义身份。"""
    body_hash = compute_scope_body_hash_v2(definition, topology_snapshot_hash)
    return ApprovalScopeDefinitionV2(
        scope_definition_id=f"ASD-{body_hash[:12]}",
        impact_analysis_fingerprint=definition.impact_analysis_fingerprint,
        canonical_effect_evidence=definition.canonical_effect_evidence,
        intent_boundary=definition.intent_boundary,
        planning_snapshot_ref=definition.planning_snapshot_ref,
        snapshot_set_ref=definition.snapshot_set_ref,
        semantic_environment_ref=definition.semantic_environment_ref,
        topology_snapshot_hash=topology_snapshot_hash,
        existing_entity_rules=definition.existing_entity_rules,
        creation_rules=definition.creation_rules,
        deletion_rules=definition.deletion_rules,
        propagation_bundle_ids=definition.propagation_bundle_ids,
        execution_slice_scope_rules=definition.execution_slice_scope_rules,
        scope_body_hash=body_hash,
    )


def validate_approval_scope_definition_v2(value: ApprovalScopeDefinitionV2) -> None:
    """重算并验证 Step28 V2 定义的内容寻址身份。"""
    if not isinstance(value, ApprovalScopeDefinitionV2):
        raise TypeError("value must be ApprovalScopeDefinitionV2")
    expected_body = _compute_scope_body_hash_v2_from_fields(
        impact_analysis_fingerprint=value.impact_analysis_fingerprint,
        canonical_effect_evidence=value.canonical_effect_evidence,
        intent_boundary=value.intent_boundary,
        planning_snapshot_ref=value.planning_snapshot_ref,
        snapshot_set_ref=value.snapshot_set_ref,
        semantic_environment_ref=value.semantic_environment_ref,
        topology_snapshot_hash=value.topology_snapshot_hash,
        existing_entity_rules=value.existing_entity_rules,
        creation_rules=value.creation_rules,
        deletion_rules=value.deletion_rules,
        propagation_bundle_ids=value.propagation_bundle_ids,
        execution_slice_scope_rules=value.execution_slice_scope_rules,
    )
    expected_id = f"ASD-{expected_body[:12]}"
    if value.scope_body_hash != expected_body or value.scope_definition_id != expected_id:
        raise ApprovalScopeError(
            "SCOPE_INTEGRITY_INVALID",
            "approval scope definition v2 integrity mismatch",
        )


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


def _compute_scope_hash_v2(scope_body_hash: str, changeset_hash: str) -> str:
    return _sha256_json(
        {
            "version": "APPROVAL_SCOPE_BOUNDARY_V2",
            "scope_body_hash": scope_body_hash,
            "changeset_hash": changeset_hash,
        }
    )


def bind_changeset_v2(
    definition: ApprovalScopeDefinitionV2,
    changeset_hash: str,
    scope_id: str,
) -> ApprovalScopeBoundaryV2:
    """把 ChangeSet 精确绑定到一个已验证的 Step28 V2 定义。"""
    validate_approval_scope_definition_v2(definition)
    normalized_changeset_hash = _require_digest(
        changeset_hash,
        field_name="changeset_hash",
        code="CHANGESET_HASH_INVALID",
    )
    scope_hash = _compute_scope_hash_v2(
        definition.scope_body_hash,
        normalized_changeset_hash,
    )
    return ApprovalScopeBoundaryV2(
        scope_id=scope_id,
        scope_definition_id=definition.scope_definition_id,
        impact_analysis_fingerprint=definition.impact_analysis_fingerprint,
        canonical_effect_evidence=definition.canonical_effect_evidence,
        intent_boundary=definition.intent_boundary,
        planning_snapshot_ref=definition.planning_snapshot_ref,
        snapshot_set_ref=definition.snapshot_set_ref,
        semantic_environment_ref=definition.semantic_environment_ref,
        topology_snapshot_hash=definition.topology_snapshot_hash,
        changeset_hash=normalized_changeset_hash,
        scope_body_hash=definition.scope_body_hash,
        existing_entity_rules=definition.existing_entity_rules,
        creation_rules=definition.creation_rules,
        deletion_rules=definition.deletion_rules,
        propagation_bundle_ids=definition.propagation_bundle_ids,
        execution_slice_scopes=definition.execution_slice_scope_rules,
        scope_hash=scope_hash,
    )


def validate_approval_scope_boundary(boundary: ApprovalScopeBoundary) -> None:
    """Recompute and validate the exact final Step28 commitment chain."""
    if not isinstance(boundary, ApprovalScopeBoundary):
        raise TypeError("boundary must be ApprovalScopeBoundary")

    expected_body = compute_scope_body_hash(
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        existing_entity_rules=boundary.existing_entity_rules,
        creation_rules=boundary.creation_rules,
        deletion_rules=boundary.deletion_rules,
        propagation_bundle_ids=boundary.propagation_bundle_ids,
        execution_slice_scope_rules=boundary.execution_slice_scopes,
    )
    expected_scope = _sha256_json(
        {
            "scope_body_hash": expected_body,
            "changeset_hash": boundary.changeset_hash,
        }
    )
    if expected_body != boundary.scope_body_hash or expected_scope != boundary.scope_hash:
        raise ApprovalScopeError(
            "SCOPE_INTEGRITY_INVALID",
            "approval scope integrity mismatch",
        )


def validate_approval_scope_boundary_v2(boundary: ApprovalScopeBoundaryV2) -> None:
    """重算并验证最终 Step28 V2 拓扑与 ChangeSet 承诺链。"""
    if not isinstance(boundary, ApprovalScopeBoundaryV2):
        raise TypeError("boundary must be ApprovalScopeBoundaryV2")

    expected_body = _compute_scope_body_hash_v2_from_fields(
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        topology_snapshot_hash=boundary.topology_snapshot_hash,
        existing_entity_rules=boundary.existing_entity_rules,
        creation_rules=boundary.creation_rules,
        deletion_rules=boundary.deletion_rules,
        propagation_bundle_ids=boundary.propagation_bundle_ids,
        execution_slice_scope_rules=boundary.execution_slice_scopes,
    )
    expected_scope = _compute_scope_hash_v2(expected_body, boundary.changeset_hash)
    expected_id = f"ASD-{expected_body[:12]}"
    if (
        expected_body != boundary.scope_body_hash
        or expected_scope != boundary.scope_hash
        or expected_id != boundary.scope_definition_id
    ):
        raise ApprovalScopeError(
            "SCOPE_INTEGRITY_INVALID",
            "approval scope boundary v2 integrity mismatch",
        )
