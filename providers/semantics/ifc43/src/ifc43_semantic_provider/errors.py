class Ifc43ProviderError(ValueError):
    """Base error for deterministic IFC4.3 provider failures."""


class Ifc43SourceVersionError(Ifc43ProviderError):
    """The implementation source is not exactly IFC4X3_ADD2 / 4.3.2.0."""


class Ifc43CatalogBuildError(Ifc43ProviderError):
    """The pinned source could not be normalized deterministically."""


class Ifc43TermNotFoundError(Ifc43ProviderError, KeyError):
    """An exact canonical IFC term is not present."""


class Ifc43ValidationError(Ifc43ProviderError):
    """Claim validator execution/configuration failed."""
