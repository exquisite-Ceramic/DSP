"""Immutable provider manifest values and machine-semantic hashing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import re

from semantic_service.errors import ManifestValidationError


_NAMESPACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class ProviderType(str, Enum):
    STANDARD = "STANDARD"
    CORE = "CORE"
    DOMAIN = "DOMAIN"
    ENTERPRISE = "ENTERPRISE"


class SemanticCapability(str, Enum):
    VOCABULARY = "VOCABULARY"
    MAPPING = "MAPPING"
    VALIDATION = "VALIDATION"
    PROJECTION = "PROJECTION"


class AuthorityMode(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    EXTENSION = "EXTENSION"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ManifestValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ManifestValidationError(f"{field_name} is required")
    return normalized


def _namespace_token(value: str) -> str:
    normalized = _required_text(value, "namespace")
    if _NAMESPACE_RE.fullmatch(normalized) is None:
        raise ManifestValidationError(f"invalid namespace: {value!r}")
    return normalized


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class ProviderRef:
    provider_id: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "version", _required_text(self.version, "version"))

    def payload(self) -> dict[str, str]:
        return {"provider_id": self.provider_id, "version": self.version}


@dataclass(frozen=True, slots=True)
class NamespaceAuthority:
    namespace: str
    mode: AuthorityMode

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _namespace_token(self.namespace))
        if not isinstance(self.mode, AuthorityMode):
            raise ManifestValidationError("authority mode is invalid")

    def payload(self) -> dict[str, str]:
        return {"namespace": self.namespace, "mode": self.mode.value}


@dataclass(frozen=True, slots=True)
class SemanticProviderManifest:
    provider_id: str
    provider_type: ProviderType
    version: str
    content_hash: str
    namespaces: tuple[str, ...]
    capabilities: frozenset[SemanticCapability]
    authority: tuple[NamespaceAuthority, ...]
    compatibility: tuple[str, ...]
    requires: tuple[ProviderRef, ...]
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        provider_id = _required_text(self.provider_id, "provider_id")
        version = _required_text(self.version, "version")
        content_hash = _required_text(self.content_hash, "content_hash")
        if not isinstance(self.provider_type, ProviderType):
            raise ManifestValidationError("provider_type is invalid")

        namespaces = tuple(sorted({_namespace_token(item) for item in self.namespaces}))
        if not namespaces:
            raise ManifestValidationError("namespaces is required")

        capabilities = frozenset(self.capabilities)
        if any(not isinstance(item, SemanticCapability) for item in capabilities):
            raise ManifestValidationError("capabilities contains an invalid value")

        authority_items = tuple(self.authority)
        seen_authority_namespaces: set[str] = set()
        for item in authority_items:
            if not isinstance(item, NamespaceAuthority):
                raise ManifestValidationError("authority contains an invalid value")
            if item.namespace in seen_authority_namespaces:
                raise ManifestValidationError(
                    f"duplicate namespace authority: {item.namespace}"
                )
            if item.namespace not in namespaces:
                raise ManifestValidationError(
                    f"authority namespace {item.namespace!r} is not declared in namespaces"
                )
            seen_authority_namespaces.add(item.namespace)
        authority = tuple(sorted(authority_items, key=lambda item: (item.namespace, item.mode.value)))

        compatibility = tuple(
            sorted({_required_text(item, "compatibility") for item in self.compatibility})
        )

        requires_items = tuple(self.requires)
        if any(not isinstance(item, ProviderRef) for item in requires_items):
            raise ManifestValidationError("requires contains an invalid value")
        requires = tuple(sorted(set(requires_items)))
        if ProviderRef(provider_id, version) in requires:
            raise ManifestValidationError(
                f"self-dependency is not allowed: {provider_id}@{version}"
            )

        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "namespaces", namespaces)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "compatibility", compatibility)
        object.__setattr__(self, "requires", requires)

        payload = {
            "provider_id": provider_id,
            "provider_type": self.provider_type.value,
            "version": version,
            "content_hash": content_hash,
            "namespaces": list(namespaces),
            "capabilities": [item.value for item in sorted(capabilities, key=lambda item: item.value)],
            "authority": [item.payload() for item in authority],
            "compatibility": list(compatibility),
            "requires": [item.payload() for item in requires],
        }
        object.__setattr__(self, "manifest_hash", _hash_payload(payload))
