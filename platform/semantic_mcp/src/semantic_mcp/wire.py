"""Stable JSON wire contract for the DSP Semantic MCP adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
import json
import math
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from semantic_service import (
    MappingCandidate,
    ProviderProvenance,
    ResolvedTerm,
    SemanticClaim,
    SemanticEnvironment,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
    ValidationFinding,
)
from semantic_service.environment import PinnedProvider


WireValue: TypeAlias = JsonValue


class SemanticClaimInput(BaseModel):
    """Strict MCP-boundary input DTO for a semantic claim."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    subject: str
    predicate: str | None = None
    canonical_term_id: str | None = None
    value: JsonValue = None
    unit: str | None = None
    assurance: str = "UNKNOWN"
    provenance: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    provider_id: str | None = None
    provider_version: str | None = None


def _canonical_json(value: WireValue) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def to_json_value(value: object) -> WireValue:
    """Convert supported Core values to deterministic JSON-safe values."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, Mapping):
        result: dict[str, WireValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = to_json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        encoded = [to_json_value(item) for item in value]
        return sorted(encoded, key=_canonical_json)
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def decode_semantic_claim(payload: SemanticClaimInput) -> SemanticClaim:
    """Convert the strict MCP input DTO into the Core immutable claim."""

    return SemanticClaim(
        subject=payload.subject,
        predicate=payload.predicate,
        canonical_term_id=payload.canonical_term_id,
        value=payload.value,
        unit=payload.unit,
        assurance=payload.assurance,
        provenance=tuple(payload.provenance),
        evidence=tuple(payload.evidence),
        provider_id=payload.provider_id,
        provider_version=payload.provider_version,
    )


def _encode_provenance(value: ProviderProvenance) -> dict[str, WireValue]:
    return {
        "provider_id": value.provider_id,
        "version": value.version,
        "content_hash": value.content_hash,
    }


def encode_resolved_term(value: ResolvedTerm) -> dict[str, WireValue]:
    return {
        "term_id": value.term_id,
        "kind": value.kind,
        "provenance": _encode_provenance(value.provenance),
    }


def encode_term_description(value: TermDescription) -> dict[str, WireValue]:
    return {
        "term_id": value.term_id,
        "text": value.text,
        "locale": value.locale,
        "provenance": _encode_provenance(value.provenance),
    }


def encode_term_schema(value: TermSchema) -> dict[str, WireValue]:
    return {
        "term_id": value.term_id,
        "schema": to_json_value(value.schema),
        "provenance": _encode_provenance(value.provenance),
    }


def encode_validation_findings(
    values: Sequence[ValidationFinding],
) -> dict[str, WireValue]:
    return {
        "findings": [
            {
                "rule_id": item.rule_id,
                "status": item.status.value,
                "message": item.message,
                "provenance": _encode_provenance(item.provenance),
            }
            for item in values
        ]
    }


def encode_mapping_candidates(
    values: Sequence[MappingCandidate],
) -> dict[str, WireValue]:
    return {
        "mappings": [
            {
                "mapping_id": item.mapping_id,
                "target_term_id": item.target_term_id,
                "evidence": list(item.evidence),
                "provenance": _encode_provenance(item.provenance),
            }
            for item in values
        ]
    }


def _encode_provider_record(
    value: SemanticProviderManifest | PinnedProvider,
) -> dict[str, WireValue]:
    return {
        "provider_id": value.provider_id,
        "provider_type": value.provider_type.value,
        "version": value.version,
        "content_hash": value.content_hash,
        "manifest_hash": value.manifest_hash,
        "namespaces": list(value.namespaces),
        "capabilities": [
            item.value for item in sorted(value.capabilities, key=lambda item: item.value)
        ],
        "authority": [
            {"namespace": item.namespace, "mode": item.mode.value}
            for item in value.authority
        ],
        "compatibility": list(value.compatibility),
        "requires": [
            {"provider_id": item.provider_id, "version": item.version}
            for item in value.requires
        ],
    }


def encode_manifest(value: SemanticProviderManifest) -> dict[str, WireValue]:
    return _encode_provider_record(value)


def encode_environment(value: SemanticEnvironment) -> dict[str, WireValue]:
    return {
        "environment_id": value.environment_id,
        "content_hash": value.content_hash,
        "providers": [_encode_provider_record(item) for item in value.providers],
    }
