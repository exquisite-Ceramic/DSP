"""Immutable DSP Core semantic term catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .hashing import canonical_hash


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=repr)
    return value


@dataclass(frozen=True, slots=True)
class SemanticTermDefinition:
    term_id: str
    version: str
    kind: str
    domain: str
    range: str
    unit: str | None
    allowed_values: tuple[str, ...]
    constraints: Mapping[str, object]
    label: str
    description: str

    def __post_init__(self) -> None:
        for field_name in (
            "term_id",
            "version",
            "kind",
            "domain",
            "range",
            "label",
            "description",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
        if not self.term_id.startswith("dsp:"):
            raise ValueError("DSP Core term_id must use dsp: namespace")
        if self.unit is not None and (not isinstance(self.unit, str) or not self.unit.strip()):
            raise ValueError("unit must be null or non-empty")
        object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        object.__setattr__(self, "constraints", _freeze(self.constraints))

    def machine_payload(self) -> dict[str, object]:
        return {
            "term_id": self.term_id,
            "version": self.version,
            "kind": self.kind,
            "domain": self.domain,
            "range": self.range,
            "unit": self.unit,
            "allowed_values": list(self.allowed_values),
            "constraints": _plain(self.constraints),
        }


class SemanticTermCatalog:
    def __init__(self, definitions: tuple[SemanticTermDefinition, ...]):
        ordered = tuple(sorted(definitions, key=lambda item: item.term_id))
        term_ids = tuple(item.term_id for item in ordered)
        if len(term_ids) != len(set(term_ids)):
            raise ValueError("duplicate term_id")
        self._definitions = ordered
        self._by_id = MappingProxyType({item.term_id: item for item in ordered})
        self._content_hash = canonical_hash(
            {"terms": [item.machine_payload() for item in ordered]}
        )

    @property
    def definitions(self) -> tuple[SemanticTermDefinition, ...]:
        return self._definitions

    @property
    def content_hash(self) -> str:
        return self._content_hash

    def get(self, term_id: str) -> SemanticTermDefinition:
        return self._by_id[term_id]


DSP_CORE_TERMS = (
    SemanticTermDefinition(
        "dsp:SemanticIdentity",
        "1.0",
        "TYPE",
        "DSP_COLLABORATION",
        "SEMANTIC_IDENTITY",
        None,
        (),
        {"host_bindings": "0..N", "external_identities": "0..N"},
        "Semantic Identity",
        "Stable DSP semantic identity shared across Host bindings.",
    ),
    SemanticTermDefinition(
        "dsp:HostBinding",
        "1.0",
        "TYPE",
        "SEMANTIC_IDENTITY",
        "HOST_NATIVE_IDENTITY_BINDING",
        None,
        (),
        {"required": ("host_type", "document_id", "native_id")},
        "Host Binding",
        "Binding from a DSP semantic identity to one Host-native entity identity.",
    ),
    SemanticTermDefinition(
        "dsp:ExternalIdentity",
        "1.0",
        "TYPE",
        "SEMANTIC_IDENTITY",
        "EXTERNAL_IDENTITY_BINDING",
        None,
        (),
        {"required": ("scheme", "value")},
        "External Identity",
        "Scheme/value identity supplied by an external semantic or data system.",
    ),
    SemanticTermDefinition(
        "dsp:WallThickness",
        "1.0",
        "PROPERTY",
        "WALL_LIKE_DESIGN_ELEMENT",
        "NUMBER",
        "mm",
        (),
        {"minimum_exclusive": 0},
        "Wall Thickness",
        "Canonical wall-like element thickness expressed in millimetres.",
    ),
    SemanticTermDefinition(
        "dsp:Freshness",
        "1.0",
        "STATE",
        "SEMANTIC_ASPECT",
        "ENUM",
        None,
        ("FRESH", "STALE", "DIRTY", "UNKNOWN", "RECONSTRUCTING"),
        {},
        "Freshness",
        "State describing whether a semantic aspect is current relative to Host revision evidence.",
    ),
    SemanticTermDefinition(
        "dsp:Assurance",
        "1.0",
        "STATE",
        "SEMANTIC_CLAIM",
        "ORDERED_ENUM",
        None,
        ("UNKNOWN", "HEURISTIC", "RULE_DERIVED", "STANDARD_MAPPED", "NATIVE_ASSERTED"),
        {},
        "Assurance",
        "Ordered confidence class describing how strongly a semantic claim is supported.",
    ),
    SemanticTermDefinition(
        "dsp:Snapshot",
        "1.0",
        "TYPE",
        "COLLABORATION_STATE",
        "IMMUTABLE_SEMANTIC_SNAPSHOT",
        None,
        (),
        {
            "snapshot_kind": ("CONTEXT", "PLANNING"),
            "planning_requires": (
                "semantic_projection_ref",
                "semantic_environment_ref",
            ),
        },
        "Semantic Snapshot",
        "Immutable DSP semantic snapshot bound to reconstruction and semantic-environment evidence.",
    ),
    SemanticTermDefinition(
        "dsp:ChangeSet",
        "1.0",
        "TYPE",
        "MODEL_OPERATION",
        "IMMUTABLE_CANONICAL_LOGICAL_TRANSACTION",
        None,
        (),
        {
            "approval_binds": (
                "changeset_hash",
                "approved_scope_hash",
                "semantic_environment_ref",
            ),
            "provider_native_payload_forbidden": True,
        },
        "ChangeSet",
        "Immutable canonical logical transaction used as the unit of planning and approval.",
    ),
)

DSP_CORE_CATALOG = SemanticTermCatalog(DSP_CORE_TERMS)
