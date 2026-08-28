"""Provider-neutral semantic identity and persistent host/external bindings."""

from __future__ import annotations

from dataclasses import dataclass


class IdentityConflictError(ValueError):
    """Raised when a unique host or external identity key would be rebound."""


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class SemanticIdentity:
    semantic_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_id", _required(self.semantic_id, "semantic_id"))


@dataclass(frozen=True, slots=True)
class HostBinding:
    semantic_id: str
    host_type: str
    document_id: str
    native_id: str
    native_kind: str

    def __post_init__(self) -> None:
        for field_name in (
            "semantic_id",
            "host_type",
            "document_id",
            "native_id",
            "native_kind",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    semantic_id: str
    scheme: str
    value: str

    def __post_init__(self) -> None:
        for field_name in ("semantic_id", "scheme", "value"):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )


class IdentityRegistry:
    """In-memory identity registry with 1:N bindings and fail-closed unique indexes."""

    def __init__(self) -> None:
        self._identities: dict[str, SemanticIdentity] = {}
        self._host_bindings: dict[str, list[HostBinding]] = {}
        self._external_identities: dict[str, list[ExternalIdentity]] = {}
        self._by_host: dict[tuple[str, str, str], HostBinding] = {}
        self._by_external: dict[tuple[str, str], ExternalIdentity] = {}

    def ensure_identity(self, semantic_id: str) -> SemanticIdentity:
        identity = SemanticIdentity(semantic_id)
        existing = self._identities.get(identity.semantic_id)
        if existing is not None:
            return existing
        self._identities[identity.semantic_id] = identity
        self._host_bindings[identity.semantic_id] = []
        self._external_identities[identity.semantic_id] = []
        return identity

    def bind_host(self, binding: HostBinding) -> HostBinding:
        if binding.semantic_id not in self._identities:
            raise KeyError(f"unknown semantic identity: {binding.semantic_id!r}")
        key = (binding.host_type, binding.document_id, binding.native_id)
        existing = self._by_host.get(key)
        if existing is not None:
            if existing == binding:
                return existing
            raise IdentityConflictError(f"host identity {key!r} is already bound")
        self._by_host[key] = binding
        self._host_bindings[binding.semantic_id].append(binding)
        return binding

    def bind_external(self, identity: ExternalIdentity) -> ExternalIdentity:
        if identity.semantic_id not in self._identities:
            raise KeyError(f"unknown semantic identity: {identity.semantic_id!r}")
        key = (identity.scheme, identity.value)
        existing = self._by_external.get(key)
        if existing is not None:
            if existing == identity:
                return existing
            raise IdentityConflictError(f"external identity {key!r} is already bound")
        self._by_external[key] = identity
        self._external_identities[identity.semantic_id].append(identity)
        return identity

    def by_semantic(self, semantic_id: str) -> SemanticIdentity | None:
        return self._identities.get(semantic_id.strip())

    def host_bindings(self, semantic_id: str) -> tuple[HostBinding, ...]:
        return tuple(self._host_bindings.get(semantic_id.strip(), ()))

    def external_identities(self, semantic_id: str) -> tuple[ExternalIdentity, ...]:
        return tuple(self._external_identities.get(semantic_id.strip(), ()))

    def by_host(
        self,
        host_type: str,
        document_id: str,
        native_id: str,
    ) -> HostBinding | None:
        return self._by_host.get(
            (host_type.strip(), document_id.strip(), native_id.strip())
        )

    def by_external(self, scheme: str, value: str) -> ExternalIdentity | None:
        return self._by_external.get((scheme.strip(), value.strip()))
