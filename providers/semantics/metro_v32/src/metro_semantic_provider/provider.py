"""Metro V3.2 Semantic Provider."""

from __future__ import annotations

from semantic_service import (
    AuthorityMode,
    MappingCandidate,
    NamespaceAuthority,
    ProviderProvenance,
    ProviderRef,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticClaim,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
    ValidationFinding,
)

from .catalog import MetroCatalog, build_catalog
from .errors import MetroCatalogBuildError
from .golden import METRO_V32_GOLDEN_CONTENT_HASH
from .mapping import find_mappings_for_claim
from .source import load_raw_machine_source
from .validation import validate_claim_against_metro


METRO_V32_CATALOG = build_catalog(load_raw_machine_source())
if METRO_V32_CATALOG.content_hash != METRO_V32_GOLDEN_CONTENT_HASH:
    raise MetroCatalogBuildError(
        "Metro V3.2 semantic content hash differs from the reviewed golden hash"
    )


class MetroV32SemanticProvider:
    def __init__(self, catalog: MetroCatalog = METRO_V32_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="dsp.metro.semantic",
            provider_type=ProviderType.DOMAIN,
            version="3.2",
            content_hash=catalog.content_hash,
            namespaces=("metro", "ifc"),
            capabilities=frozenset(
                {
                    SemanticCapability.VOCABULARY,
                    SemanticCapability.MAPPING,
                    SemanticCapability.VALIDATION,
                    SemanticCapability.PROJECTION,
                }
            ),
            authority=(
                NamespaceAuthority("metro", AuthorityMode.AUTHORITATIVE),
                NamespaceAuthority("ifc", AuthorityMode.EXTENSION),
            ),
            compatibility=(),
            requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        )
        self._provenance = ProviderProvenance(
            provider_id=self._manifest.provider_id,
            version=self._manifest.version,
            content_hash=self._manifest.content_hash,
        )

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        record = self._catalog.get(term_id)
        return ResolvedTerm(record.term_id, record.kind, self._provenance)

    def describe_term(
        self,
        term_id: str,
        locale: str | None = None,
    ) -> TermDescription:
        record = self._catalog.get(term_id)
        text = record.description or record.term_id
        return TermDescription(record.term_id, text, None, self._provenance)

    def get_term_schema(self, term_id: str) -> TermSchema:
        record = self._catalog.get(term_id)
        return TermSchema(
            record.term_id,
            self._catalog.schema_for(term_id),
            self._provenance,
        )

    def find_mappings(
        self,
        source_claim: SemanticClaim,
        target_namespace: str | None = None,
    ) -> tuple[MappingCandidate, ...]:
        return find_mappings_for_claim(
            self._catalog,
            source_claim,
            self._provenance,
            target_namespace,
        )

    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]:
        return validate_claim_against_metro(self._catalog, claim, self._provenance)


METRO_V32_PROVIDER = MetroV32SemanticProvider()
