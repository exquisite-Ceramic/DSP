"""Environment-scoped Semantic Service routing."""

from __future__ import annotations

from semantic_service.environment import (
    PinnedProvider,
    SemanticEnvironment,
    SemanticEnvironmentStore,
)
from semantic_service.errors import (
    NamespaceAuthorityError,
    ProviderCapabilityError,
    TermResolutionError,
)
from semantic_service.manifest import AuthorityMode, SemanticCapability, SemanticProviderManifest
from semantic_service.providers import (
    ResolvedTerm,
    SemanticVocabularyProvider,
    TermDescription,
    TermSchema,
)
from semantic_service.registry import SemanticProviderRegistry


class SemanticService:
    """Composes one provider registry and one pinned environment store."""

    def __init__(
        self,
        registry: SemanticProviderRegistry,
        environments: SemanticEnvironmentStore,
    ) -> None:
        self._registry = registry
        self._environments = environments

    @staticmethod
    def _term_namespace(term_id: str) -> str:
        normalized = term_id.strip()
        if ":" not in normalized:
            raise TermResolutionError("term_id must use namespace:local form")
        namespace, local = normalized.split(":", 1)
        if not namespace or not local:
            raise TermResolutionError("term_id must use namespace:local form")
        return namespace

    def _vocabulary_provider(
        self,
        term_id: str,
        environment_id: str,
    ) -> tuple[SemanticVocabularyProvider, PinnedProvider]:
        namespace = self._term_namespace(term_id)
        environment = self._environments.get(environment_id)
        owners = tuple(
            pinned
            for pinned in environment.providers
            if any(
                authority.namespace == namespace
                and authority.mode is AuthorityMode.AUTHORITATIVE
                for authority in pinned.authority
            )
        )
        if len(owners) != 1:
            raise NamespaceAuthorityError(
                f"namespace {namespace} requires exactly one AUTHORITATIVE provider; "
                f"found {len(owners)}"
            )
        pinned = owners[0]
        if SemanticCapability.VOCABULARY not in pinned.capabilities:
            raise ProviderCapabilityError(
                f"provider {pinned.provider_id}@{pinned.version} lacks VOCABULARY capability"
            )
        provider = self._registry.get(pinned.provider_id, pinned.version)
        if not isinstance(provider, SemanticVocabularyProvider):
            raise ProviderCapabilityError(
                f"provider {pinned.provider_id}@{pinned.version} does not implement VOCABULARY"
            )
        return provider, pinned

    @staticmethod
    def _raise_term_error(operation: str, pinned: PinnedProvider, exc: Exception) -> None:
        raise TermResolutionError(
            f"{operation} failed via {pinned.provider_id}@{pinned.version}: "
            f"{type(exc).__name__}"
        ) from exc

    def resolve_term(self, term_id: str, environment_id: str) -> ResolvedTerm:
        provider, pinned = self._vocabulary_provider(term_id, environment_id)
        try:
            return provider.resolve_term(term_id)
        except Exception as exc:
            self._raise_term_error("resolve_term", pinned, exc)

    def describe_term(
        self,
        term_id: str,
        environment_id: str,
        locale: str | None = None,
    ) -> TermDescription:
        provider, pinned = self._vocabulary_provider(term_id, environment_id)
        try:
            return provider.describe_term(term_id, locale)
        except Exception as exc:
            self._raise_term_error("describe_term", pinned, exc)

    def get_term_schema(self, term_id: str, environment_id: str) -> TermSchema:
        provider, pinned = self._vocabulary_provider(term_id, environment_id)
        try:
            return provider.get_term_schema(term_id)
        except Exception as exc:
            self._raise_term_error("get_term_schema", pinned, exc)

    def get_provider_manifest(self, provider_id: str, version: str) -> SemanticProviderManifest:
        return self._registry.get_manifest(provider_id, version)

    def get_environment(self, environment_id: str) -> SemanticEnvironment:
        return self._environments.get(environment_id)
