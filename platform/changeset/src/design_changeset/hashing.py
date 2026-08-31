"""Deterministic semantic hashing for the Step29 canonical ChangeSet."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Any

from design_approval_scope import CreationRule, DeletionRule, ExistingEntityRule


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_jsonable(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    return deepcopy(value)


def canonical_json(payload: object) -> str:
    """Encode semantic content with stable ordering.

    ``ensure_ascii=True`` intentionally matches Step27's already-frozen hashing
    convention so the shared bound-operation fingerprint is byte-for-byte
    verifiable without changing Step27's existing analysis fingerprint.
    """

    return json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_hash(payload: object) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_bound_operation_fingerprint(
    canonical_operation: str,
    canonical_operation_version: str,
    arguments: Mapping[str, Any],
) -> str:
    return canonical_hash(
        {
            "canonical_operation": canonical_operation,
            "canonical_operation_version": canonical_operation_version,
            "arguments": arguments,
        }
    )


def compute_bound_operation_evidence_fingerprint(
    *,
    canonical_operation: str,
    canonical_operation_version: str,
    arguments: Mapping[str, Any],
    context_snapshot_id: str,
    context_snapshot_hash: str,
    document_ref: str,
    semantic_environment_id: str,
    planning_requirements: Mapping[str, Any],
    binding_evidence: Mapping[str, Any],
) -> str:
    return canonical_hash(
        {
            "canonical_operation": canonical_operation,
            "canonical_operation_version": canonical_operation_version,
            "arguments": arguments,
            "context_snapshot": {
                "context_snapshot_id": context_snapshot_id,
                "context_snapshot_hash": context_snapshot_hash,
                "document_ref": document_ref,
            },
            "semantic_environment_id": semantic_environment_id,
            "planning_requirements": planning_requirements,
            "binding_evidence": binding_evidence,
        }
    )


def compute_contract_definition_fingerprint(
    *,
    canonical_operation: str,
    canonical_operation_version: str,
    argument_schema: Mapping[str, Any],
    effects,
    verification_contract: Mapping[str, Any],
    existence_effects=(),
    creation_contract=None,
) -> str:
    normalized_effects = sorted(
        item.value if isinstance(item, Enum) else str(item) for item in effects
    )
    payload: dict[str, object] = {
        "canonical_operation": canonical_operation,
        "canonical_operation_version": canonical_operation_version,
        "argument_schema": argument_schema,
        "effects": normalized_effects,
        "verification_contract": verification_contract,
    }
    normalized_existence = sorted(
        item.value if isinstance(item, Enum) else str(item) for item in existence_effects
    )
    if normalized_existence:
        payload["existence_effects"] = normalized_existence
    if creation_contract is not None:
        payload["creation_contract"] = creation_contract
    return canonical_hash(payload)


def compute_proposed_change_hash(change: Mapping[str, object]) -> str:
    if not isinstance(change, Mapping):
        raise TypeError("proposed change must be a mapping")
    return canonical_hash(change)


def _selector_payload(selector: object) -> object:
    predicate = getattr(selector, "predicate", None)
    if predicate is None:
        return {"entities": list(selector.entities)}
    return {
        "predicate": [
            {
                "field": term.field,
                "operator": term.operator,
                "values": list(term.values),
            }
            for term in predicate.all_of
        ]
    }


def compute_scope_rule_fingerprint(rule: object) -> str:
    if isinstance(rule, ExistingEntityRule):
        return canonical_hash(
            {
                "selector": _selector_payload(rule.selector),
                "allowed_aspects": sorted(
                    item.value if isinstance(item, Enum) else str(item)
                    for item in rule.allowed_aspects
                ),
            }
        )
    if isinstance(rule, CreationRule):
        return canonical_hash(
            {
                "rule_kind": "CREATION",
                "canonical_operation": rule.canonical_operation,
                "source_selector": _selector_payload(rule.source_selector),
                "entity_kinds": list(rule.entity_kinds),
                "max_count": rule.max_count,
                "required_derivation": rule.required_derivation,
            }
        )
    if isinstance(rule, DeletionRule):
        return canonical_hash(
            {
                "rule_kind": "DELETION",
                "selector": _selector_payload(rule.selector),
            }
        )
    raise TypeError("scope rule must be ExistingEntityRule, CreationRule, or DeletionRule")


def compute_operation_semantic_hash(
    *,
    origin: object,
    canonical_operation: str,
    canonical_operation_version: str,
    canonical_definition_fingerprint: str,
    targets,
    arguments: Mapping[str, Any],
    expected_effects,
    scope_rule_fingerprints,
    source_evidence: object,
    expected_existence_effects=(),
) -> str:
    payload: dict[str, object] = {
        "origin": origin,
        "canonical_operation": canonical_operation,
        "canonical_operation_version": canonical_operation_version,
        "canonical_definition_fingerprint": canonical_definition_fingerprint,
        "targets": sorted(set(targets)),
        "arguments": arguments,
        "expected_effects": sorted(
            item.value if isinstance(item, Enum) else str(item)
            for item in expected_effects
        ),
        "scope_rule_fingerprints": sorted(set(scope_rule_fingerprints)),
        "source_evidence": source_evidence,
    }
    normalized_existence = sorted(
        item.value if isinstance(item, Enum) else str(item)
        for item in expected_existence_effects
    )
    if normalized_existence:
        payload["expected_existence_effects"] = normalized_existence
    return canonical_hash(payload)


def compute_changeset_hash(semantic_body: Mapping[str, Any]) -> str:
    """Hash an already-normalized semantic ChangeSet body.

    Construction ids are excluded by the builder when assembling this body;
    accepting only the semantic body keeps those ids out of this API entirely.
    """

    if not isinstance(semantic_body, Mapping):
        raise TypeError("semantic_body must be a mapping")
    return canonical_hash(semantic_body)


__all__ = [
    "canonical_hash",
    "canonical_json",
    "compute_bound_operation_evidence_fingerprint",
    "compute_bound_operation_fingerprint",
    "compute_changeset_hash",
    "compute_contract_definition_fingerprint",
    "compute_operation_semantic_hash",
    "compute_proposed_change_hash",
    "compute_scope_rule_fingerprint",
]
