"""Deterministic fake Semantic Providers used only by tests."""

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


def _provider_type(provider_id: str) -> ProviderType:
    if provider_id.startswith("buildingSMART."):
        return ProviderType.STANDARD
    if provider_id.startswith("dsp.metro."):
        return ProviderType.DOMAIN
    if provider_id.startswith("acme."):
        return ProviderType.ENTERPRISE
    return ProviderType.CORE


def make_manifest(
    *,
    provider_id: str,
    version: str,
    namespace: str,
    authority: AuthorityMode,
    capabilities: frozenset[SemanticCapability],
    content_hash: str | None = None,
    compatibility: tuple[str, ...] = ("semantic-service.v1",),
    requires: tuple[ProviderRef, ...] = (),
) -> SemanticProviderManifest:
    return SemanticProviderManifest(
        provider_id=provider_id,
        provider_type=_provider_type(provider_id),
        version=version,
        content_hash=content_hash or f"{provider_id}@{version}",
        namespaces=(namespace,),
        capabilities=capabilities,
        authority=(NamespaceAuthority(namespace, authority),),
        compatibility=compatibility,
        requires=requires,
    )


def _provenance(manifest: SemanticProviderManifest) -> ProviderProvenance:
    return ProviderProvenance(manifest.provider_id, manifest.version, manifest.content_hash)


class VocabularyProvider:
    def __init__(
        self,
        *,
        provider_id: str = "buildingSMART.ifc43",
        version: str = "4.3.2.0",
        namespace: str = "ifc",
        authority: AuthorityMode = AuthorityMode.AUTHORITATIVE,
        content_hash: str | None = None,
        extra_capabilities: set[SemanticCapability] | frozenset[SemanticCapability] = frozenset(),
        claim_projection: bool = False,
        fail_resolve: bool = False,
    ) -> None:
        capabilities = {SemanticCapability.VOCABULARY, *extra_capabilities}
        if claim_projection:
            capabilities.add(SemanticCapability.PROJECTION)
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace=namespace,
            authority=authority,
            capabilities=frozenset(capabilities),
            content_hash=content_hash,
        )
        self.fail_resolve = fail_resolve
        self.resolve_calls: list[str] = []
        self.describe_calls: list[tuple[str, str | None]] = []
        self.schema_calls: list[str] = []

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        self.resolve_calls.append(term_id)
        if self.fail_resolve:
            raise RuntimeError("fake vocabulary failure")
        return ResolvedTerm(term_id, "TERM", _provenance(self.manifest))

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        self.describe_calls.append((term_id, locale))
        return TermDescription(term_id, f"Description for {term_id}", locale, _provenance(self.manifest))

    def get_term_schema(self, term_id: str) -> TermSchema:
        self.schema_calls.append(term_id)
        return TermSchema(term_id, {"type": "object"}, _provenance(self.manifest))


class MappingProvider:
    def __init__(
        self,
        *,
        provider_id: str = "acme.mapping",
        version: str = "1",
        namespace: str = "acme",
        authority: AuthorityMode = AuthorityMode.EXTENSION,
        mappings: tuple[MappingCandidate, ...] = (),
        content_hash: str | None = None,
    ) -> None:
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace=namespace,
            authority=authority,
            capabilities=frozenset({SemanticCapability.MAPPING}),
            content_hash=content_hash,
        )
        self.mappings = tuple(mappings)
        self.calls: list[tuple[SemanticClaim, str | None]] = []

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def find_mappings(
        self,
        source_claim: SemanticClaim,
        target_namespace: str | None = None,
    ) -> tuple[MappingCandidate, ...]:
        self.calls.append((source_claim, target_namespace))
        return self.mappings


class ValidationProvider:
    def __init__(
        self,
        *,
        provider_id: str = "acme.validation",
        version: str = "1",
        namespace: str = "acme",
        authority: AuthorityMode = AuthorityMode.EXTENSION,
        findings: tuple[ValidationFinding, ...] = (),
        content_hash: str | None = None,
    ) -> None:
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace=namespace,
            authority=authority,
            capabilities=frozenset({SemanticCapability.VALIDATION}),
            content_hash=content_hash,
        )
        self.findings = tuple(findings)
        self.calls: list[SemanticClaim] = []

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]:
        self.calls.append(claim)
        return self.findings
