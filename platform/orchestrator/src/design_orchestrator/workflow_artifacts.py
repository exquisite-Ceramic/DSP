"""Workflow Orchestrator 所拥有 deterministic artifacts 的显式持久化 codec。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Any

from design_orchestrator.canonical_operations import (
    CanonicalExistenceEffect,
    SlotBindingClass,
)
from design_orchestrator.operation_resolver import ResolutionResult, ResolvedOperation
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    PlanningRequirements,
    SlotBindingEvidence,
)

WORKFLOW_ARTIFACT_CODEC_VERSION = 1

PERSISTED_CAPABILITY_PROFILE_FIELDS = (
    "provider_server",
    "provider_tool",
    "canonical_operation",
    "category",
    "entity_constraints",
    "execution_freshness",
    "effects",
    "existence_effects",
    "risk",
    "preview_supported",
    "rollback_supported",
    "idempotent",
    "verification_contract",
    "input_schema",
    "output_schema",
    "description",
)


class WorkflowArtifactError(ValueError):
    """Workflow-local artifact 边界的基础错误。"""


class WorkflowArtifactCodecError(WorkflowArtifactError):
    """Artifact kind、版本、类型或 payload 不满足显式 codec 契约。"""


class WorkflowArtifactUnavailableError(WorkflowArtifactError):
    """Artifact 缺失、损坏或无法通过完整性校验。"""


@dataclass(frozen=True, slots=True)
class PersistedCapabilityProfile:
    """跨进程恢复所需的 provider capability 稳定结构投影。"""

    provider_server: str
    provider_tool: str
    canonical_operation: str
    category: str
    entity_constraints: tuple[str, ...]
    execution_freshness: tuple[dict[str, Any], ...]
    effects: tuple[Any, ...]
    existence_effects: tuple[Any, ...]
    risk: str | None
    preview_supported: bool
    rollback_supported: bool
    idempotent: bool
    verification_contract: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    description: str | None


_RESOLVED_OPERATION_KEYS = frozenset(
    {
        "operation_id",
        "canonical_operation",
        "input_schema",
        "canonical_entity_constraints",
        "context_freshness_requirements",
        "operation_freshness_requirements",
        "effects",
        "existence_effects",
        "policy_decision",
        "risk",
        "task_score",
        "preview_supported",
        "rollback_supported",
        "verification_contract",
        "candidate_provider_ids",
    }
)
_PROFILE_KEYS = frozenset(PERSISTED_CAPABILITY_PROFILE_FIELDS)
_RESOLUTION_KEYS = frozenset({"resolved_operations", "provider_candidates"})
_BOUND_KEYS = frozenset(
    {
        "operation",
        "arguments",
        "binding_evidence",
        "context_snapshot_ref",
        "planning_requirements",
        "semantic_environment_ref",
    }
)
_OPERATION_REF_KEYS = frozenset({"canonical_operation", "version"})
_BINDING_EVIDENCE_KEYS = frozenset(
    {"slot", "binding_class", "source", "source_ref"}
)
_CONTEXT_REF_KEYS = frozenset(
    {"context_snapshot_id", "context_snapshot_hash", "document_ref"}
)
_PLANNING_REQUIREMENT_KEYS = frozenset(
    {
        "operation_freshness_requirements",
        "coverage_requirements",
        "assurance_requirements",
    }
)


def _codec_error(
    message: str,
    exc: Exception | None = None,
) -> WorkflowArtifactCodecError:
    error = WorkflowArtifactCodecError(message)
    if exc is not None:
        error.__cause__ = exc
    return error


def _expect_mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowArtifactCodecError(f"{context} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise WorkflowArtifactCodecError(f"{context} requires string keys")
    return value


def _expect_exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    context: str,
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise WorkflowArtifactCodecError(
            f"{context} keys mismatch: missing={missing}, extra={extra}"
        )


def _expect_sequence(value: object, *, context: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkflowArtifactCodecError(f"{context} must be an array")
    return value


def _required_text(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowArtifactCodecError(f"{context} must be a non-empty string")
    return value


def _optional_text(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowArtifactCodecError(f"{context} must be a string or null")
    return value


def _expect_bool(value: object, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowArtifactCodecError(f"{context} must be a boolean")
    return value


def _expect_number(value: object, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowArtifactCodecError(f"{context} must be a number")
    return float(value)


def _json_value(value: object, *, context: str) -> object:
    """只把显式 artifact 字段递归转换成确定性的 JSON-compatible 值。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value, context=context)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise WorkflowArtifactCodecError(f"{context} requires string mapping keys")
        return {
            key: _json_value(value[key], context=f"{context}.{key}")
            for key in sorted(value)
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item, context=f"{context}[]") for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_json_value(item, context=f"{context}[]") for item in value]
        try:
            return sorted(
                items,
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            )
        except (TypeError, ValueError) as exc:
            raise _codec_error(f"{context} contains a non-JSON value", exc)
    raise WorkflowArtifactCodecError(
        f"{context} contains unsupported value type {type(value).__name__}"
    )


def _json_object(value: object, *, context: str) -> dict[str, Any]:
    mapping = _expect_mapping(value, context=context)
    normalized = _json_value(mapping, context=context)
    assert isinstance(normalized, dict)
    return normalized


def _json_array(value: object, *, context: str) -> tuple[Any, ...]:
    items = _expect_sequence(value, context=context)
    return tuple(_json_value(item, context=f"{context}[]") for item in items)


def _mapping_sequence(value: object, *, context: str) -> tuple[dict[str, Any], ...]:
    items = _expect_sequence(value, context=context)
    return tuple(_json_object(item, context=f"{context}[]") for item in items)


def _text_sequence(value: object, *, context: str) -> tuple[str, ...]:
    items = _expect_sequence(value, context=context)
    return tuple(_required_text(item, context=f"{context}[]") for item in items)


def _profile_field(profile: object, name: str) -> object:
    if hasattr(profile, name):
        return getattr(profile, name)
    defaults: dict[str, object] = {
        "existence_effects": (),
        "idempotent": False,
        "description": None,
    }
    if name in defaults:
        return defaults[name]
    raise WorkflowArtifactCodecError(
        f"capability profile is missing required field {name!r}"
    )


def _encode_profile(profile: object) -> dict[str, object]:
    return {
        name: _json_value(
            _profile_field(profile, name),
            context=f"provider_candidate.{name}",
        )
        for name in PERSISTED_CAPABILITY_PROFILE_FIELDS
    }


def _decode_profile(payload: object) -> PersistedCapabilityProfile:
    value = _expect_mapping(payload, context="provider_candidate")
    _expect_exact_keys(value, _PROFILE_KEYS, context="provider_candidate")
    output_schema_raw = value["output_schema"]
    output_schema = (
        None
        if output_schema_raw is None
        else _json_object(output_schema_raw, context="provider_candidate.output_schema")
    )
    return PersistedCapabilityProfile(
        provider_server=_required_text(
            value["provider_server"], context="provider_candidate.provider_server"
        ),
        provider_tool=_required_text(
            value["provider_tool"], context="provider_candidate.provider_tool"
        ),
        canonical_operation=_required_text(
            value["canonical_operation"],
            context="provider_candidate.canonical_operation",
        ),
        category=_required_text(value["category"], context="provider_candidate.category"),
        entity_constraints=_text_sequence(
            value["entity_constraints"],
            context="provider_candidate.entity_constraints",
        ),
        execution_freshness=_mapping_sequence(
            value["execution_freshness"],
            context="provider_candidate.execution_freshness",
        ),
        effects=_json_array(value["effects"], context="provider_candidate.effects"),
        existence_effects=_json_array(
            value["existence_effects"],
            context="provider_candidate.existence_effects",
        ),
        risk=_optional_text(value["risk"], context="provider_candidate.risk"),
        preview_supported=_expect_bool(
            value["preview_supported"],
            context="provider_candidate.preview_supported",
        ),
        rollback_supported=_expect_bool(
            value["rollback_supported"],
            context="provider_candidate.rollback_supported",
        ),
        idempotent=_expect_bool(
            value["idempotent"], context="provider_candidate.idempotent"
        ),
        verification_contract=_json_object(
            value["verification_contract"],
            context="provider_candidate.verification_contract",
        ),
        input_schema=_json_object(
            value["input_schema"], context="provider_candidate.input_schema"
        ),
        output_schema=output_schema,
        description=_optional_text(
            value["description"], context="provider_candidate.description"
        ),
    )


def _encode_resolved_operation(operation: ResolvedOperation) -> dict[str, object]:
    return {
        "operation_id": operation.operation_id,
        "canonical_operation": operation.canonical_operation,
        "input_schema": _json_value(
            operation.input_schema, context="resolved_operation.input_schema"
        ),
        "canonical_entity_constraints": list(operation.canonical_entity_constraints),
        "context_freshness_requirements": _json_value(
            operation.context_freshness_requirements,
            context="resolved_operation.context_freshness_requirements",
        ),
        "operation_freshness_requirements": _json_value(
            operation.operation_freshness_requirements,
            context="resolved_operation.operation_freshness_requirements",
        ),
        "effects": _json_value(operation.effects, context="resolved_operation.effects"),
        "existence_effects": [item.value for item in operation.existence_effects],
        "policy_decision": operation.policy_decision,
        "risk": operation.risk,
        "task_score": operation.task_score,
        "preview_supported": operation.preview_supported,
        "rollback_supported": operation.rollback_supported,
        "verification_contract": _json_value(
            operation.verification_contract,
            context="resolved_operation.verification_contract",
        ),
        "candidate_provider_ids": list(operation.candidate_provider_ids),
    }


def _decode_resolved_operation(payload: object) -> ResolvedOperation:
    value = _expect_mapping(payload, context="resolved_operation")
    _expect_exact_keys(value, _RESOLVED_OPERATION_KEYS, context="resolved_operation")
    existence_effects: list[CanonicalExistenceEffect] = []
    for item in _expect_sequence(
        value["existence_effects"],
        context="resolved_operation.existence_effects",
    ):
        if not isinstance(item, str):
            raise WorkflowArtifactCodecError(
                "resolved_operation.existence_effects entries must be strings"
            )
        try:
            existence_effects.append(CanonicalExistenceEffect(item))
        except ValueError as exc:
            raise _codec_error(f"invalid CanonicalExistenceEffect {item!r}", exc)
    return ResolvedOperation(
        operation_id=_required_text(
            value["operation_id"], context="resolved_operation.operation_id"
        ),
        canonical_operation=_required_text(
            value["canonical_operation"],
            context="resolved_operation.canonical_operation",
        ),
        input_schema=_json_object(
            value["input_schema"], context="resolved_operation.input_schema"
        ),
        canonical_entity_constraints=_text_sequence(
            value["canonical_entity_constraints"],
            context="resolved_operation.canonical_entity_constraints",
        ),
        context_freshness_requirements=_mapping_sequence(
            value["context_freshness_requirements"],
            context="resolved_operation.context_freshness_requirements",
        ),
        operation_freshness_requirements=_mapping_sequence(
            value["operation_freshness_requirements"],
            context="resolved_operation.operation_freshness_requirements",
        ),
        effects=_json_array(value["effects"], context="resolved_operation.effects"),
        existence_effects=tuple(existence_effects),
        policy_decision=_required_text(
            value["policy_decision"], context="resolved_operation.policy_decision"
        ),
        risk=_optional_text(value["risk"], context="resolved_operation.risk"),
        task_score=_expect_number(
            value["task_score"], context="resolved_operation.task_score"
        ),
        preview_supported=_expect_bool(
            value["preview_supported"],
            context="resolved_operation.preview_supported",
        ),
        rollback_supported=_expect_bool(
            value["rollback_supported"],
            context="resolved_operation.rollback_supported",
        ),
        verification_contract=_json_object(
            value["verification_contract"],
            context="resolved_operation.verification_contract",
        ),
        candidate_provider_ids=_text_sequence(
            value["candidate_provider_ids"],
            context="resolved_operation.candidate_provider_ids",
        ),
    )


def _encode_resolution(value: ResolutionResult) -> dict[str, object]:
    return {
        "resolved_operations": [
            _encode_resolved_operation(item) for item in value.resolved_operations
        ],
        "provider_candidates": {
            candidate_id: _encode_profile(value.provider_candidates[candidate_id])
            for candidate_id in sorted(value.provider_candidates)
        },
    }


def _decode_resolution(payload: Mapping[str, object]) -> ResolutionResult:
    _expect_exact_keys(payload, _RESOLUTION_KEYS, context="operation_resolution")
    operations = tuple(
        _decode_resolved_operation(item)
        for item in _expect_sequence(
            payload["resolved_operations"],
            context="operation_resolution.resolved_operations",
        )
    )
    candidates_raw = _expect_mapping(
        payload["provider_candidates"],
        context="operation_resolution.provider_candidates",
    )
    candidates = {
        candidate_id: _decode_profile(candidates_raw[candidate_id])
        for candidate_id in sorted(candidates_raw)
    }
    return ResolutionResult(
        resolved_operations=operations,
        provider_candidates=candidates,
    )


def _encode_bound(value: BoundOperationProposal) -> dict[str, object]:
    return {
        "operation": {
            "canonical_operation": value.operation.canonical_operation,
            "version": value.operation.version,
        },
        "arguments": _json_value(value.arguments, context="bound.arguments"),
        "binding_evidence": {
            slot: {
                "slot": evidence.slot,
                "binding_class": evidence.binding_class.value,
                "source": evidence.source,
                "source_ref": evidence.source_ref,
            }
            for slot, evidence in sorted(value.binding_evidence.items())
        },
        "context_snapshot_ref": {
            "context_snapshot_id": value.context_snapshot_ref.context_snapshot_id,
            "context_snapshot_hash": value.context_snapshot_ref.context_snapshot_hash,
            "document_ref": value.context_snapshot_ref.document_ref,
        },
        "planning_requirements": {
            "operation_freshness_requirements": _json_value(
                value.planning_requirements.operation_freshness_requirements,
                context="bound.planning_requirements.operation_freshness_requirements",
            ),
            "coverage_requirements": _json_value(
                value.planning_requirements.coverage_requirements,
                context="bound.planning_requirements.coverage_requirements",
            ),
            "assurance_requirements": _json_value(
                value.planning_requirements.assurance_requirements,
                context="bound.planning_requirements.assurance_requirements",
            ),
        },
        "semantic_environment_ref": value.semantic_environment_ref,
    }


def _decode_bound(payload: Mapping[str, object]) -> BoundOperationProposal:
    _expect_exact_keys(payload, _BOUND_KEYS, context="bound_operation_proposal")

    operation_raw = _expect_mapping(payload["operation"], context="bound.operation")
    _expect_exact_keys(operation_raw, _OPERATION_REF_KEYS, context="bound.operation")
    operation = CanonicalOperationRef(
        canonical_operation=_required_text(
            operation_raw["canonical_operation"],
            context="bound.operation.canonical_operation",
        ),
        version=_required_text(
            operation_raw["version"], context="bound.operation.version"
        ),
    )

    arguments = _json_object(payload["arguments"], context="bound.arguments")

    evidence_raw = _expect_mapping(
        payload["binding_evidence"], context="bound.binding_evidence"
    )
    evidence: dict[str, SlotBindingEvidence] = {}
    for key in sorted(evidence_raw):
        item = _expect_mapping(
            evidence_raw[key], context=f"bound.binding_evidence.{key}"
        )
        _expect_exact_keys(
            item,
            _BINDING_EVIDENCE_KEYS,
            context=f"bound.binding_evidence.{key}",
        )
        binding_class_raw = item["binding_class"]
        if not isinstance(binding_class_raw, str):
            raise WorkflowArtifactCodecError(
                f"bound.binding_evidence.{key}.binding_class must be a string"
            )
        try:
            binding_class = SlotBindingClass(binding_class_raw)
        except ValueError as exc:
            raise _codec_error(f"invalid SlotBindingClass {binding_class_raw!r}", exc)
        evidence[key] = SlotBindingEvidence(
            slot=_required_text(
                item["slot"], context=f"bound.binding_evidence.{key}.slot"
            ),
            binding_class=binding_class,
            source=_required_text(
                item["source"], context=f"bound.binding_evidence.{key}.source"
            ),
            source_ref=_optional_text(
                item["source_ref"],
                context=f"bound.binding_evidence.{key}.source_ref",
            ),
        )

    context_raw = _expect_mapping(
        payload["context_snapshot_ref"], context="bound.context_snapshot_ref"
    )
    _expect_exact_keys(
        context_raw, _CONTEXT_REF_KEYS, context="bound.context_snapshot_ref"
    )
    context_ref = ContextSnapshotRef(
        context_snapshot_id=_required_text(
            context_raw["context_snapshot_id"],
            context="bound.context_snapshot_ref.context_snapshot_id",
        ),
        context_snapshot_hash=_required_text(
            context_raw["context_snapshot_hash"],
            context="bound.context_snapshot_ref.context_snapshot_hash",
        ),
        document_ref=_required_text(
            context_raw["document_ref"],
            context="bound.context_snapshot_ref.document_ref",
        ),
    )

    planning_raw = _expect_mapping(
        payload["planning_requirements"], context="bound.planning_requirements"
    )
    _expect_exact_keys(
        planning_raw,
        _PLANNING_REQUIREMENT_KEYS,
        context="bound.planning_requirements",
    )
    planning_requirements = PlanningRequirements(
        operation_freshness_requirements=_mapping_sequence(
            planning_raw["operation_freshness_requirements"],
            context="bound.planning_requirements.operation_freshness_requirements",
        ),
        coverage_requirements=_mapping_sequence(
            planning_raw["coverage_requirements"],
            context="bound.planning_requirements.coverage_requirements",
        ),
        assurance_requirements=_mapping_sequence(
            planning_raw["assurance_requirements"],
            context="bound.planning_requirements.assurance_requirements",
        ),
    )

    return BoundOperationProposal(
        operation=operation,
        arguments=arguments,
        binding_evidence=evidence,
        context_snapshot_ref=context_ref,
        planning_requirements=planning_requirements,
        semantic_environment_ref=_required_text(
            payload["semantic_environment_ref"],
            context="bound.semantic_environment_ref",
        ),
    )


def encode_workflow_artifact(*, kind: str, value: object) -> dict[str, object]:
    """把支持的 workflow-local artifact 编码为显式 versioned JSON payload。"""

    try:
        if kind == "operation_resolution":
            if not isinstance(value, ResolutionResult):
                raise WorkflowArtifactCodecError(
                    "operation_resolution requires ResolutionResult"
                )
            return _encode_resolution(value)
        if kind == "bound_operation_proposal":
            if not isinstance(value, BoundOperationProposal):
                raise WorkflowArtifactCodecError(
                    "bound_operation_proposal requires BoundOperationProposal"
                )
            return _encode_bound(value)
        raise WorkflowArtifactCodecError(
            f"unsupported workflow artifact kind: {kind!r}"
        )
    except WorkflowArtifactCodecError:
        raise
    except (TypeError, ValueError) as exc:
        raise _codec_error(f"failed to encode workflow artifact kind {kind!r}", exc)


def decode_workflow_artifact(
    *,
    kind: str,
    codec_version: int,
    payload: Mapping[str, object],
) -> object:
    """按 kind/version 严格重建 workflow-local deterministic artifact。"""

    if (
        type(codec_version) is not int
        or codec_version != WORKFLOW_ARTIFACT_CODEC_VERSION
    ):
        raise WorkflowArtifactCodecError(
            f"unsupported workflow artifact codec version: {codec_version!r}"
        )
    mapping = _expect_mapping(payload, context=f"{kind}.payload")
    try:
        if kind == "operation_resolution":
            return _decode_resolution(mapping)
        if kind == "bound_operation_proposal":
            return _decode_bound(mapping)
        raise WorkflowArtifactCodecError(
            f"unsupported workflow artifact kind: {kind!r}"
        )
    except WorkflowArtifactCodecError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise _codec_error(f"failed to decode workflow artifact kind {kind!r}", exc)


def _artifact_kind(value: object) -> str:
    if isinstance(value, ResolutionResult):
        return "operation_resolution"
    if isinstance(value, BoundOperationProposal):
        return "bound_operation_proposal"
    raise WorkflowArtifactCodecError(
        f"unsupported workflow artifact value type: {type(value).__name__}"
    )


def workflow_artifact_content_hash(value: object) -> str:
    """仅对显式 codec payload 计算 lowercase SHA-256。"""

    payload = encode_workflow_artifact(kind=_artifact_kind(value), value=value)
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _codec_error("workflow artifact payload is not canonical JSON", exc)
    return sha256(encoded).hexdigest()


def _normalize_for_legacy_hash(value: object) -> object:
    """保持迁移前 generic artifact hash 的递归规范化行为，不供新 producer 使用。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _normalize_for_legacy_hash(value.value)
    if isinstance(value, Mapping):
        normalized_items: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("workflow artifact mappings require string keys")
            normalized_items[key] = _normalize_for_legacy_hash(item)
        return {key: normalized_items[key] for key in sorted(normalized_items)}
    if isinstance(value, (tuple, list)):
        return [_normalize_for_legacy_hash(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize_for_legacy_hash(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _normalize_for_legacy_hash(getattr(value, field.name))
            for field in fields(value)
        }

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        return _normalize_for_legacy_hash(dumped)

    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        public_attributes = {
            str(key): item
            for key, item in attributes.items()
            if not str(key).startswith("_")
        }
        if public_attributes:
            return _normalize_for_legacy_hash(public_attributes)

    raise TypeError(
        "workflow-local artifact contains a value without deterministic serialization"
    )


def legacy_workflow_artifact_content_hash(value: object) -> str:
    """计算迁移前 workflow artifact ref 使用的 lowercase SHA-256。"""

    normalized = _normalize_for_legacy_hash(value)
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


__all__ = [
    "PERSISTED_CAPABILITY_PROFILE_FIELDS",
    "WORKFLOW_ARTIFACT_CODEC_VERSION",
    "PersistedCapabilityProfile",
    "WorkflowArtifactCodecError",
    "WorkflowArtifactError",
    "WorkflowArtifactUnavailableError",
    "decode_workflow_artifact",
    "encode_workflow_artifact",
    "legacy_workflow_artifact_content_hash",
    "workflow_artifact_content_hash",
]
