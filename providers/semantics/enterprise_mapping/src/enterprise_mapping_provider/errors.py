class EnterpriseSemanticProviderError(Exception):
    """Base error for enterprise semantic provider failures."""


class EnterpriseSourceError(EnterpriseSemanticProviderError):
    """Raised when packaged machine source is missing or malformed."""


class EnterpriseCatalogBuildError(EnterpriseSemanticProviderError):
    """Raised when machine mapping rules cannot form a deterministic catalog."""


class EnterpriseProjectionError(EnterpriseSemanticProviderError):
    """Raised when one fact cannot be projected deterministically."""
