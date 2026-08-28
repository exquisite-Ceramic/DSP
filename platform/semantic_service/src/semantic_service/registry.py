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
        existing = self._providers.get(key)
        if existing is not None:
            if existing.manifest == manifest:
                return existing.manifest
            raise ProviderRegistrationConflictError(
                f"immutable provider version conflict: {manifest.provider_id}@{manifest.version}"
            )

        self._providers[key] = provider
        return manifest

    def get(self, provider_id: str, version: str) -> SemanticProvider:
        key = (provider_id.strip(), version.strip())
        try:
            return self._providers[key]
        except KeyError as exc:
            raise ProviderNotFoundError(f"provider not found: {key[0]}@{key[1]}") from exc

    def get_manifest(self, provider_id: str, version: str) -> SemanticProviderManifest:
        return self.get(provider_id, version).manifest

    def versions(self, provider_id: str) -> tuple[str, ...]:
        normalized = provider_id.strip()
        return tuple(sorted(version for current, version in self._providers if current == normalized))

    def providers_with_capability(
        self,
        capability: SemanticCapability,
    ) -> tuple[SemanticProvider, ...]:
        return tuple(
            provider
            for _, provider in sorted(
                self._providers.items(),
                key=lambda item: item[0],
            )
            if capability in provider.manifest.capabilities
        )
