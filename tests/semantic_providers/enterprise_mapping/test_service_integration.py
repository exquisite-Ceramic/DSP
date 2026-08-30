import pytest

from design_fact_contracts import (
    DesignFactHostRef,
    FactKind,
    NativeSubjectRef,
    NormalizedDesignFact,
    NormalizedDesignFactBatch,
    ValueType,
)
from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from enterprise_mapping_provider import ENTERPRISE_MAPPING_CATALOG, ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from semantic_service import (
    AuthorityMode,
    ProviderDependencyError,
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)


DSP_CORE_REF = ProviderRef("dsp.core", "1.0")
IFC_REF = ProviderRef("buildingSMART.ifc43", "4.3.2.0")
ENTERPRISE_REF = ProviderRef("dsp.enterprise.mapping", "1.0.0")


def wall_batch():
    document_id = "station.dwg"
    fact = NormalizedDesignFact(
        fact_id="fact-a31",
        producer="test.producer",
        host_ref=DesignFactHostRef("autocad", "session-1", document_id),
        source_revision=1,
        subject_native_ref=NativeSubjectRef(document_id, "A31", "LWPOLYLINE"),
        fact_kind=FactKind.CLASSIFICATION,
        predicate="layer",
        value="A-WALL",
        value_type=ValueType.STRING,
        source_scheme="autocad.layer",
        source_code="A-WALL",
        provenance=("autocad://session-1/station.dwg/A31@1",),
    )
    return NormalizedDesignFactBatch((fact,))


def build_registry():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    registry.register(IFC43_PROVIDER)
    registry.register(ENTERPRISE_MAPPING_PROVIDER)
    return registry


def test_enterprise_provider_cannot_be_pinned_without_exact_ifc_dependency():
    registry = build_registry()
    with pytest.raises(ProviderDependencyError, match=r"buildingSMART\.ifc43@4\.3\.2\.0"):
        SemanticEnvironmentStore().pin((ENTERPRISE_REF,), registry)


def test_enterprise_provider_cannot_be_pinned_without_exact_dsp_core_dependency():
    registry = build_registry()
    with pytest.raises(ProviderDependencyError, match=r"dsp\.core@1\.0"):
        SemanticEnvironmentStore().pin((ENTERPRISE_REF, IFC_REF), registry)


def test_authoritative_vocabularies_remain_owned_while_enterprise_projects_claims():
    registry = build_registry()
    store = SemanticEnvironmentStore()
    environment = store.pin((DSP_CORE_REF, ENTERPRISE_REF, IFC_REF), registry)
    service = SemanticService(registry, store)

    pinned = {item.provider_id: item for item in environment.providers}
    assert pinned["buildingSMART.ifc43"].authority[0].mode is AuthorityMode.AUTHORITATIVE
    assert pinned["dsp.core"].authority[0].mode is AuthorityMode.AUTHORITATIVE
    assert all(
        authority.mode is AuthorityMode.EXTENSION
        for authority in pinned["dsp.enterprise.mapping"].authority
    )

    claims = service.project_facts(wall_batch(), environment.environment_id)
    assert len(claims) == 1
    assert claims[0].canonical_term_id == "ifc:IfcWall"
    assert claims[0].provider_id == "dsp.enterprise.mapping"

    resolved = service.resolve_term("ifc:IfcWall", environment.environment_id)
    assert resolved.term_id == "ifc:IfcWall"
    assert resolved.provenance.provider_id == "buildingSMART.ifc43"
    assert resolved.provenance.version == "4.3.2.0"


def test_every_packaged_enterprise_target_resolves_in_required_authoritative_baseline():
    registry = build_registry()
    store = SemanticEnvironmentStore()
    environment = store.pin((DSP_CORE_REF, IFC_REF, ENTERPRISE_REF), registry)
    service = SemanticService(registry, store)

    expected_owner = {
        "dsp": "dsp.core",
        "ifc": "buildingSMART.ifc43",
    }
    for target in sorted({rule.target_term_id for rule in ENTERPRISE_MAPPING_CATALOG.rules}):
        resolved = service.resolve_term(target, environment.environment_id)
        assert resolved.term_id == target
        namespace = target.split(":", 1)[0]
        assert resolved.provenance.provider_id == expected_owner[namespace]
