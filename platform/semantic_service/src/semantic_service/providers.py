"""Provider-neutral semantic DTOs and capability protocols."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from design_fact_contracts import NormalizedDesignFactBatch

from semantic_service.manifest import SemanticProviderManifest


FACT_PROJECTION_COMPATIBILITY = "dsp.semantic.projection-facts.v1"


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProviderProvenance:
    provider_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "version", _required_text(self.version, "version"))
        object.__setattr__(self, "content_hash", _required_text(self.content_hash, "content_hash"))


@dataclass(frozen=True, slots=True)
class ResolvedTerm:
    term_id: str
    kind: str | None
    provenance: ProviderProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "term_id", _required_text(self.term_id, "term_id"))
        object.__setattr__(self, "kind", _optional_text(self.kind))


@dataclass(frozen=True, slots=True)
class TermDescription:
    term_id: str
    text: str
    locale: str | None
    provenance: ProviderProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "term_id", _required_text(self.term_id, "term_id"))
        object.__setattr__(self, "text", _required_text(self.text, "text"))
        object.__setattr__(self, "locale", _optional_text(self.locale))


@dataclass(frozen=True, slots=True)
class TermSchema:
    term_id: str
    schema: Mapping[str, object]
    provenance: ProviderProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "term_id", _required_text(self.term_id, "term_id"))
        object.__setattr__(
            self,
            "schema",
            MappingProxyType(
                {key: _freeze_value(value) for key, value in self.schema.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticClaim:
    subject: str
    predicate: str | None = None
    canonical_term_id: str | None = None
    value: object = None
    unit: str | None = None
    assurance: str = "UNKNOWN"
    provenance: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    provider_id: str | None = None
    provider_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _required_text(self.subject, "subject"))
        object.__setattr__(self, "predicate", _optional_text(self.predicate))
        object.__setattr__(self, "canonical_term_id", _optional_text(self.canonical_term_id))
        object.__setattr__(self, "unit", _optional_text(self.unit))
        object.__setattr__(self, "assurance", _required_text(self.assurance, "assurance"))
        object.__setattr__(self, "provenance", tuple(self.provenance))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "provider_id", _optional_text(self.provider_id))
        object.__setattr__(self, "provider_version", _optional_text(self.provider_version))


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    mapping_id: str
    target_term_id: str
    provenance: ProviderProvenance
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping_id", _required_text(self.mapping_id, "mapping_id"))
        object.__setattr__(self, "target_term_id", _required_text(self.target_term_id, "target_term_id"))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def provider_id(self) -> str:
        return self.provenance.provider_id

    @property
    def provider_version(self) -> str:
        return self.provenance.version


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    rule_id: str
    status: ValidationStatus
    provenance: ProviderProvenance
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "rule_id"))
        if not isinstance(self.status, ValidationStatus):
            raise ValueError("status is invalid")
        object.__setattr__(self, "message", _optional_text(self.message))

    @property
    def provider_id(self) -> str:
        return self.provenance.provider_id

    @property
    def provider_version(self) -> str:
        return self.provenance.version


@runtime_checkable
class SemanticProvider(Protocol):
    @property
    def manifest(self) -> SemanticProviderManifest: ...


@runtime_checkable
class SemanticVocabularyProvider(SemanticProvider, Protocol):
    def resolve_term(self, term_id: str) -> ResolvedTerm: ...

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription: ...

    def get_term_schema(self, term_id: str) -> TermSchema: ...


@runtime_checkable
class SemanticMappingProvider(SemanticProvider, Protocol):
    def find_mappings(
        self,
        source_claim: SemanticClaim,
        target_namespace: str | None = None,
    ) -> tuple[MappingCandidate, ...]: ...


@runtime_checkable
class SemanticValidationProvider(SemanticProvider, Protocol):
    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]: ...


@runtime_checkable
class SemanticProjectionProvider(SemanticProvider, Protocol):
    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
    ) -> tuple[SemanticClaim, ...]: ...
