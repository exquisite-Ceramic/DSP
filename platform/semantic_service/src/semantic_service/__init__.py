"""Semantic Service Core public surface."""

from semantic_service.errors import (
    EnvironmentIntegrityError,
    EnvironmentNotFoundError,
    ManifestValidationError,
    NamespaceAuthorityError,
    ProviderCapabilityError,
    ProviderDependencyError,
    ProviderNotFoundError,
    ProviderRegistrationConflictError,
    SemanticServiceError,
    TermResolutionError,
)
from semantic_service.manifest import (
    AuthorityMode,
    NamespaceAuthority,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticProviderManifest,
)

__all__ = [
    "AuthorityMode",
    "EnvironmentIntegrityError",
    "EnvironmentNotFoundError",
    "ManifestValidationError",
    "NamespaceAuthority",
    "NamespaceAuthorityError",
    "ProviderCapabilityError",
    "ProviderDependencyError",
    "ProviderNotFoundError",
    "ProviderRef",
    "ProviderRegistrationConflictError",
    "ProviderType",
    "SemanticCapability",
    "SemanticProviderManifest",
    "SemanticServiceError",
    "TermResolutionError",
]
