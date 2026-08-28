"""Provider-local Metro semantic errors."""


class MetroSemanticProviderError(RuntimeError):
    pass


class MetroSourceError(MetroSemanticProviderError):
    pass


class MetroCatalogBuildError(MetroSemanticProviderError):
    pass


class MetroTermNotFoundError(MetroSemanticProviderError):
    pass


class MetroMappingError(MetroSemanticProviderError):
    pass


class MetroValidationError(MetroSemanticProviderError):
    pass
