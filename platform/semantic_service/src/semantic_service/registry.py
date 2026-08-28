"""Immutable Semantic Provider registration and lookup."""

from __future__ import annotations

from semantic_service.errors import (
    ProviderCapabilityError,
    ProviderNotFoundError,
    ProviderRegistrationConflictError,
)
from semantic_service.manifest import SemanticCapability, SemanticProviderManifest
from semantic_service.providers import (
    SemanticMappingProvider,
    SemanticProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
)


class SemanticProviderRegistry:
    """Registers exact immutable provider versions and validates claimed capabilities."""

    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], SemanticProvider] = {}
        self._manifests: dict[tuple[str, str], SemanticProviderManifest] = {}

    def register(self, provider: SemanticProvider) -> SemanticProviderManifest:
        if not isinstance(provider, SemanticProvider):
            raise ProviderCapabilityError("provider does not expose a SemanticProvider manifest")

        manifest = provider.manifest
        checks = {
            SemanticCapability.VOCABULARY: SemanticVocabularyProvider,
            SemanticCapability.MAPPING: SemanticMappingProvider,
            SemanticCapability.VALIDATION: SemanticValidationProvider,
        }
        for capability, protocol in checks.items():
            if capability in manifest.capabilities and not isinstance(provider, protocol):
                raise ProviderCapabilityError(
                    f"provider {manifest.provider_id}@{manifest.version} claims "
                    f"{capability.value} without implementing its protocol"
                )

        key = (manifest.provider_id, manifest.version)
        existing_manifest = self._manifests.get(key)
        if existing_manifest is not None:
            if existing_manifest == manifest:
                return existing_manifest
            raise ProviderRegistrationConflictError(
                f"immutable provider version conflict: {manifest.provider_id}@{manifest.version}"
            )

        self._providers[key] = provider
        self._manifests[key] = manifest
        return manifest

    def get(self, provider_id: str, version: str) -> SemanticProvider:
        key = (provider_id.strip(), version.strip())
        try:
            provider = self._providers[key]
            frozen_manifest = self._manifests[key]
        except KeyError as exc:
            raise ProviderNotFoundError(f"provider not found: {key[0]}@{key[1]}") from exc
        if provider.manifest != frozen_manifest:
            raise ProviderRegistrationConflictError(
                f"registered provider manifest drift: {key[0]}@{key[1]}"
            )
        return provider

    def get_manifest(self, provider_id: str, version: str) -> SemanticProviderManifest:
        key = (provider_id.strip(), version.strip())
        try:
            return self._manifests[key]
        except KeyError as exc:
            raise ProviderNotFoundError(f"provider not found: {key[0]}@{key[1]}") from exc

    def versions(self, provider_id: str) -> tuple[str, ...]:
        normalized = provider_id.strip()
        return tuple(sorted(version for current, version in self._manifests if current == normalized))

    def providers_with_capability(
        self,
        capability: SemanticCapability,
    ) -> tuple[SemanticProvider, ...]:
        providers: list[SemanticProvider] = []
        for key, manifest in sorted(self._manifests.items(), key=lambda item: item[0]):
            if capability not in manifest.capabilities:
                continue
            providers.append(self.get(*key))
        return tuple(providers)
