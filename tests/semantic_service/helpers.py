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
    SemanticProvider,
    SemanticProviderManifest,
    SemanticProviderRegistry,
    SemanticEnvironment,
    SemanticEnvironmentStore,
    SemanticService,
    TermDescription,
    TermSchema,
    ValidationFinding,
    ValidationStatus,
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
        compatibility: tuple[str, ...] = ("semantic-service.v1",),
        requires: tuple[ProviderRef, ...] = (),
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
            compatibility=compatibility,
            requires=requires,
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
        compatibility: tuple[str, ...] = ("semantic-service.v1",),
        requires: tuple[ProviderRef, ...] = (),
        call_log: list[tuple[str, str]] | None = None,
        fail: bool = False,
    ) -> None:
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace=namespace,
            authority=authority,
            capabilities=frozenset({SemanticCapability.MAPPING}),
            content_hash=content_hash,
            compatibility=compatibility,
            requires=requires,
        )
        self.mappings = tuple(mappings)
        self.calls = 0
        self.call_log = call_log if call_log is not None else []
        self.fail = fail

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def find_mappings(
        self,
        source_claim: SemanticClaim,
        target_namespace: str | None = None,
    ) -> tuple[MappingCandidate, ...]:
        self.calls += 1
        self.call_log.append((self.manifest.provider_id, self.manifest.version))
        if self.fail:
            raise RuntimeError("fake mapping failure")
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
        compatibility: tuple[str, ...] = ("semantic-service.v1",),
        requires: tuple[ProviderRef, ...] = (),
        call_log: list[tuple[str, str]] | None = None,
        fail: bool = False,
    ) -> None:
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace=namespace,
            authority=authority,
            capabilities=frozenset({SemanticCapability.VALIDATION}),
            content_hash=content_hash,
            compatibility=compatibility,
            requires=requires,
        )
        self.findings = tuple(findings)
        self.calls = 0
        self.call_log = call_log if call_log is not None else []
        self.fail = fail

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]:
        self.calls += 1
        self.call_log.append((self.manifest.provider_id, self.manifest.version))
        if self.fail:
            raise RuntimeError("fake validation failure")
        return self.findings


def register_all(*providers: SemanticProvider) -> SemanticProviderRegistry:
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry


def all_refs(registry: SemanticProviderRegistry) -> tuple[ProviderRef, ...]:
    refs: list[ProviderRef] = []
    for provider_id in (
        "acme.design.standard",
        "buildingSMART.ifc43",
        "dsp.metro.semantic",
        "shadow.ifc",
    ):
        for version in registry.versions(provider_id):
            refs.append(ProviderRef(provider_id, version))
    return tuple(sorted(refs))


def registry_with_ifc() -> SemanticProviderRegistry:
    return register_all(VocabularyProvider())


def registry_with_ifc_and_enterprise() -> SemanticProviderRegistry:
    return register_all(
        VocabularyProvider(),
        MappingProvider(
            provider_id="acme.design.standard",
            version="2026.08",
            namespace="acme",
            authority=AuthorityMode.AUTHORITATIVE,
        ),
    )


def registry_with_metro_requiring_ifc() -> SemanticProviderRegistry:
    return register_all(
        VocabularyProvider(),
        MappingProvider(
            provider_id="dsp.metro.semantic",
            version="3.2",
            namespace="metro",
            authority=AuthorityMode.AUTHORITATIVE,
            requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        ),
    )


def registry_with_two_ifc_authorities() -> SemanticProviderRegistry:
    return register_all(
        VocabularyProvider(),
        VocabularyProvider(
            provider_id="shadow.ifc",
            version="1",
            namespace="ifc",
            authority=AuthorityMode.AUTHORITATIVE,
        ),
    )


def registry_with_ifc_authority_and_metro_extension() -> SemanticProviderRegistry:
    return register_all(
        VocabularyProvider(),
        MappingProvider(
            provider_id="dsp.metro.semantic",
            version="3.2",
            namespace="ifc",
            authority=AuthorityMode.EXTENSION,
        ),
    )


def service_with_ifc_authority_and_extension() -> tuple[
    SemanticService, VocabularyProvider, VocabularyProvider, SemanticEnvironment
]:
    authoritative = VocabularyProvider()
    extension = VocabularyProvider(
        provider_id="dsp.metro.semantic",
        version="3.2",
        namespace="ifc",
        authority=AuthorityMode.EXTENSION,
    )
    registry = register_all(authoritative, extension)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
            ProviderRef("dsp.metro.semantic", "3.2"),
        ),
        registry,
    )
    return SemanticService(registry, store), authoritative, extension, environment


def service_with_ifc_extension_only() -> tuple[SemanticService, SemanticEnvironment]:
    extension = VocabularyProvider(
        provider_id="dsp.metro.semantic",
        version="3.2",
        namespace="ifc",
        authority=AuthorityMode.EXTENSION,
    )
    registry = register_all(extension)
    store = SemanticEnvironmentStore()
    environment = store.pin((ProviderRef("dsp.metro.semantic", "3.2"),), registry)
    return SemanticService(registry, store), environment


def mapping_service_fixture() -> tuple[
    SemanticService, SemanticEnvironment, MappingProvider, MappingProvider, MappingProvider
]:
    call_log: list[tuple[str, str]] = []
    selected_a = MappingProvider(provider_id="a.mapping", call_log=call_log)
    selected_b = MappingProvider(provider_id="b.mapping", call_log=call_log)
    unselected = MappingProvider(provider_id="z.unselected", call_log=call_log)
    selected_a.mappings = (
        MappingCandidate("map-b", "ifc:IfcWall", _provenance(selected_a.manifest)),
    )
    selected_b.mappings = (
        MappingCandidate("map-a", "ifc:IfcWall", _provenance(selected_b.manifest)),
    )
    registry = register_all(selected_b, unselected, selected_a)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (ProviderRef("b.mapping", "1"), ProviderRef("a.mapping", "1")),
        registry,
    )
    return SemanticService(registry, store), environment, selected_a, selected_b, unselected


def validation_service_with_fail_and_pass() -> tuple[SemanticService, SemanticEnvironment]:
    fail_provider = ValidationProvider(provider_id="a.standard.validation", namespace="ifc")
    pass_provider = ValidationProvider(provider_id="b.domain.validation", namespace="metro")
    fail_provider.findings = (
        ValidationFinding(
            "rule-standard",
            ValidationStatus.FAIL,
            _provenance(fail_provider.manifest),
        ),
    )
    pass_provider.findings = (
        ValidationFinding(
            "rule-domain",
            ValidationStatus.PASS,
            _provenance(pass_provider.manifest),
        ),
    )
    registry = register_all(pass_provider, fail_provider)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("b.domain.validation", "1"),
            ProviderRef("a.standard.validation", "1"),
        ),
        registry,
    )
    return SemanticService(registry, store), environment
