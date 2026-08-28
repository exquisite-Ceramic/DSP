"""VOCABULARY-only DSP Core Semantic Provider."""

from __future__ import annotations

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

from .catalog import DSP_CORE_CATALOG, SemanticTermCatalog


class DspCoreSemanticProvider:
    """Authoritative provider for the pinned DSP Core `dsp:*` vocabulary."""

    def __init__(self, catalog: SemanticTermCatalog = DSP_CORE_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="dsp.core",
            provider_type=ProviderType.CORE,
            version="1.0",
            content_hash=catalog.content_hash,
            namespaces=("dsp",),
            capabilities=frozenset({SemanticCapability.VOCABULARY}),
            authority=(NamespaceAuthority("dsp", AuthorityMode.AUTHORITATIVE),),
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
        definition = self._catalog.get(term_id)
        return ResolvedTerm(definition.term_id, definition.kind, self._provenance)

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        definition = self._catalog.get(term_id)
        return TermDescription(
            definition.term_id,
            definition.description,
            None,
            self._provenance,
        )

    def get_term_schema(self, term_id: str) -> TermSchema:
        definition = self._catalog.get(term_id)
        return TermSchema(
            definition.term_id,
            definition.machine_payload(),
            self._provenance,
        )


DSP_CORE_PROVIDER = DspCoreSemanticProvider()
