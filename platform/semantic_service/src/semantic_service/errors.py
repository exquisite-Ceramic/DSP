"""Typed fail-closed errors for Semantic Service Core."""


class SemanticServiceError(ValueError):
    """Base error for deterministic Semantic Service failures."""


class ManifestValidationError(SemanticServiceError):
    """Provider manifest data is invalid."""


class ProviderRegistrationConflictError(SemanticServiceError):
    """An immutable provider version was registered with conflicting metadata."""


class ProviderNotFoundError(SemanticServiceError):
    """An exact provider version was not registered."""


class ProviderCapabilityError(SemanticServiceError):
    """A provider does not implement a capability it declares."""


class ProviderDependencyError(SemanticServiceError):
    """A pinned provider dependency is missing or incompatible."""


class NamespaceAuthorityError(SemanticServiceError):
    """Namespace authority is missing or conflicting."""


class EnvironmentIntegrityError(SemanticServiceError):
    """A semantic environment violates immutable storage invariants."""


class EnvironmentNotFoundError(SemanticServiceError):
    """A semantic environment could not be found."""


class TermResolutionError(SemanticServiceError):
    """A vocabulary provider failed to resolve a term deterministically."""
