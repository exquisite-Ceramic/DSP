from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    ProviderProvenance,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
)

from .catalog import IFC43_CATALOG, Ifc43Catalog


class Ifc43SemanticProvider:
    def __init__(self, catalog: Ifc43Catalog = IFC43_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="buildingSMART.ifc43",
            provider_type=ProviderType.STANDARD,
            version="4.3.2.0",
            content_hash=catalog.content_hash,
            namespaces=("ifc",),
            capabilities=frozenset(
                {
                    SemanticCapability.VOCABULARY,
                    SemanticCapability.VALIDATION,
                    SemanticCapability.PROJECTION,
                }
            ),
            authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
            compatibility=(),
            requires=(),
        )
        self._provenance = ProviderProvenance(
            self._manifest.provider_id,
            self._manifest.version,
            self._manifest.content_hash,
        )

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        record = self._catalog.get(term_id)
        return ResolvedTerm(record.term_id, record.kind, self._provenance)

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        record = self._catalog.get(term_id)
        return TermDescription(record.term_id, record.description, None, self._provenance)

    def get_term_schema(self, term_id: str) -> TermSchema:
        record = self._catalog.get(term_id)
        return TermSchema(record.term_id, self._catalog.schema_for(term_id), self._provenance)


IFC43_PROVIDER = Ifc43SemanticProvider()
