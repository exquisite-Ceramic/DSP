import pytest

from design_fact_contracts import NormalizedDesignFactBatch
from semantic_service import (
    AuthorityMode,
    ProviderRef,
    SemanticCapability,
    SemanticClaim,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
    SemanticServiceError,
)
from tests.semantic_service.helpers import VocabularyProvider, make_manifest


FACTS_V1 = "dsp.semantic.projection-facts.v1"
EMPTY_BATCH = NormalizedDesignFactBatch(())


class ProjectionProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        version: str = "1",
        claims: tuple[object, ...] = (),
        call_log: list[tuple[str, str]] | None = None,
        fail: bool = False,
        compatibility: tuple[str, ...] = (FACTS_V1,),
    ) -> None:
        self._manifest = make_manifest(
            provider_id=provider_id,
            version=version,
            namespace="ifc",
            authority=AuthorityMode.EXTENSION,
            capabilities=frozenset({SemanticCapability.PROJECTION}),
            compatibility=compatibility,
        )
        self.claims = claims
        self.calls = 0
        self.call_log = call_log if call_log is not None else []
        self.fail = fail

    @property
    def manifest(self):
        return self._manifest

    def project_facts(self, facts):
        self.calls += 1
        self.call_log.append((self.manifest.provider_id, self.manifest.version))
        assert facts is EMPTY_BATCH
        if self.fail:
            raise RuntimeError("fake projection failure")
        return self.claims


def claim(provider_id: str, *, subject: str, term: str) -> SemanticClaim:
    return SemanticClaim(
        subject=subject,
        predicate="classification",
        canonical_term_id=term,
        provider_id=provider_id,
        provider_version="1",
    )


def build_service(*providers):
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        tuple(ProviderRef(p.manifest.provider_id, p.manifest.version) for p in providers),
        registry,
    )
    return SemanticService(registry, store), environment


def test_project_facts_calls_only_selected_facts_v1_projection_providers():
    participating = ProjectionProvider(
        provider_id="a.projection",
        claims=(claim("a.projection", subject="s1", term="ifc:IfcWall"),),
    )
    marker_only = VocabularyProvider(
        provider_id="b.marker",
        version="1",
        namespace="ifc",
        authority=AuthorityMode.EXTENSION,
        claim_projection=True,
    )
    unselected = ProjectionProvider(provider_id="z.unselected")

    registry = SemanticProviderRegistry()
    for provider in (participating, marker_only, unselected):
        registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("a.projection", "1"),
            ProviderRef("b.marker", "1"),
        ),
        registry,
    )

    results = SemanticService(registry, store).project_facts(
        EMPTY_BATCH, environment.environment_id
    )

    assert [item.canonical_term_id for item in results] == ["ifc:IfcWall"]
    assert participating.calls == 1
    assert not hasattr(marker_only, "project_facts")
    assert unselected.calls == 0


def test_project_facts_uses_pinned_provider_order_and_preserves_provider_tuple_order():
    log: list[tuple[str, str]] = []
    provider_b = ProjectionProvider(
        provider_id="b.projection",
        claims=(
            claim("b.projection", subject="b2", term="ifc:IfcDoor"),
            claim("b.projection", subject="b1", term="ifc:IfcWall"),
        ),
        call_log=log,
    )
    provider_a = ProjectionProvider(
        provider_id="a.projection",
        claims=(
            claim("a.projection", subject="a2", term="ifc:IfcSlab"),
            claim("a.projection", subject="a1", term="ifc:IfcBeam"),
        ),
        call_log=log,
    )
    service, environment = build_service(provider_b, provider_a)

    results = service.project_facts(EMPTY_BATCH, environment.environment_id)

    assert log == [("a.projection", "1"), ("b.projection", "1")]
    assert [(item.provider_id, item.subject) for item in results] == [
        ("a.projection", "a2"),
        ("a.projection", "a1"),
        ("b.projection", "b2"),
        ("b.projection", "b1"),
    ]


def test_project_facts_without_facts_v1_participant_returns_empty_tuple():
    marker_only = VocabularyProvider(claim_projection=True)
    service, environment = build_service(marker_only)
    assert service.project_facts(EMPTY_BATCH, environment.environment_id) == ()


def test_projection_provider_exception_aborts_instead_of_returning_partial_results():
    good = ProjectionProvider(
        provider_id="a.projection",
        claims=(claim("a.projection", subject="s", term="ifc:IfcWall"),),
    )
    bad = ProjectionProvider(provider_id="b.projection", fail=True)
    service, environment = build_service(good, bad)

    with pytest.raises(SemanticServiceError, match=r"b\.projection@1.*RuntimeError"):
        service.project_facts(EMPTY_BATCH, environment.environment_id)
    assert good.calls == 1
    assert bad.calls == 1


@pytest.mark.parametrize(
    "claims",
    [
        [claim("a.projection", subject="s", term="ifc:IfcWall")],
        (object(),),
    ],
)
def test_projection_provider_output_shape_fails_closed(claims):
    provider = ProjectionProvider(provider_id="a.projection", claims=claims)
    service, environment = build_service(provider)
    with pytest.raises(SemanticServiceError):
        service.project_facts(EMPTY_BATCH, environment.environment_id)


@pytest.mark.parametrize(
    ("provider_id", "provider_version"),
    [
        (None, "1"),
        ("forged.projection", "1"),
        ("a.projection", None),
        ("a.projection", "9"),
    ],
)
def test_projection_claim_provider_identity_must_match_emitter(provider_id, provider_version):
    forged = SemanticClaim(
        subject="s",
        predicate="classification",
        canonical_term_id="ifc:IfcWall",
        provider_id=provider_id,
        provider_version=provider_version,
    )
    provider = ProjectionProvider(provider_id="a.projection", claims=(forged,))
    service, environment = build_service(provider)

    with pytest.raises(SemanticServiceError, match="provider identity mismatch"):
        service.project_facts(EMPTY_BATCH, environment.environment_id)
