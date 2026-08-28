"""Pinned content-addressed Semantic Environments."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
import json

from semantic_service.errors import (
    EnvironmentIntegrityError,
    EnvironmentNotFoundError,
    NamespaceAuthorityError,
    ProviderDependencyError,
)
from semantic_service.manifest import (
    AuthorityMode,
    NamespaceAuthority,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticProviderManifest,
)
from semantic_service.registry import SemanticProviderRegistry


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PinnedProvider:
    provider_id: str
    provider_type: ProviderType
    version: str
    content_hash: str
    manifest_hash: str
    namespaces: tuple[str, ...]
    capabilities: frozenset[SemanticCapability]
    authority: tuple[NamespaceAuthority, ...]
    compatibility: tuple[str, ...]
    requires: tuple[ProviderRef, ...]

    @classmethod
    def from_manifest(cls, manifest: SemanticProviderManifest) -> "PinnedProvider":
        return cls(
            provider_id=manifest.provider_id,
            provider_type=manifest.provider_type,
            version=manifest.version,
            content_hash=manifest.content_hash,
            manifest_hash=manifest.manifest_hash,
            namespaces=manifest.namespaces,
            capabilities=manifest.capabilities,
            authority=manifest.authority,
            compatibility=manifest.compatibility,
            requires=manifest.requires,
        )

    def payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value,
            "version": self.version,
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "namespaces": list(self.namespaces),
            "capabilities": [
                item.value for item in sorted(self.capabilities, key=lambda item: item.value)
            ],
            "authority": [item.payload() for item in self.authority],
            "compatibility": list(self.compatibility),
            "requires": [item.payload() for item in self.requires],
        }


@dataclass(frozen=True, slots=True)
class SemanticEnvironment:
    providers: tuple[PinnedProvider, ...]
    environment_id: str
    content_hash: str

    @classmethod
    def create(cls, providers: Iterable[PinnedProvider]) -> "SemanticEnvironment":
        pinned = tuple(sorted(providers, key=lambda item: (item.provider_id, item.version)))
        digest = _hash_payload({"providers": [item.payload() for item in pinned]})
        return cls(
            providers=pinned,
            environment_id=f"sem-env:{digest}",
            content_hash=digest,
        )


class SemanticEnvironmentStore:
    """Pins exact provider versions and stores immutable semantic environments."""

    def __init__(self) -> None:
        self._by_id: dict[str, SemanticEnvironment] = {}
        self._by_hash: dict[str, SemanticEnvironment] = {}

    def pin(
        self,
        selections: Iterable[ProviderRef],
        registry: SemanticProviderRegistry,
    ) -> SemanticEnvironment:
        refs = tuple(sorted(set(selections)))
        selected = set(refs)
        manifests = tuple(
            registry.get_manifest(ref.provider_id, ref.version)
            for ref in refs
        )

        for manifest in manifests:
            for dependency in manifest.requires:
                if dependency not in selected:
                    raise ProviderDependencyError(
                        f"missing exact provider dependency: "
                        f"{dependency.provider_id}@{dependency.version}"
                    )

        authorities: dict[str, ProviderRef] = {}
        for manifest in manifests:
            current_ref = ProviderRef(manifest.provider_id, manifest.version)
            for item in manifest.authority:
                if item.mode is not AuthorityMode.AUTHORITATIVE:
                    continue
                existing = authorities.get(item.namespace)
                if existing is not None and existing != current_ref:
                    raise NamespaceAuthorityError(
                        f"multiple AUTHORITATIVE providers for namespace {item.namespace}: "
                        f"{existing.provider_id}@{existing.version}, "
                        f"{current_ref.provider_id}@{current_ref.version}"
                    )
                authorities[item.namespace] = current_ref

        environment = SemanticEnvironment.create(
            PinnedProvider.from_manifest(manifest) for manifest in manifests
        )
        existing_id = self._by_id.get(environment.environment_id)
        existing_hash = self._by_hash.get(environment.content_hash)
        for existing in (existing_id, existing_hash):
            if existing is not None and existing != environment:
                raise EnvironmentIntegrityError(
                    f"semantic environment key already bound: {environment.environment_id}"
                )
        if existing_id is not None:
            return existing_id
        if existing_hash is not None:
            return existing_hash

        self._by_id[environment.environment_id] = environment
        self._by_hash[environment.content_hash] = environment
        return environment

    def get(self, environment_id: str) -> SemanticEnvironment:
        key = environment_id.strip()
        try:
            return self._by_id[key]
        except KeyError as exc:
            raise EnvironmentNotFoundError(f"environment not found: {key}") from exc

    def get_by_hash(self, content_hash: str) -> SemanticEnvironment:
        key = content_hash.strip()
        try:
            return self._by_hash[key]
        except KeyError as exc:
            raise EnvironmentNotFoundError(f"environment hash not found: {key}") from exc
