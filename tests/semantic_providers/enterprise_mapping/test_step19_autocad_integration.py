from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from semantic_service import ProviderRef, SemanticEnvironmentStore, SemanticProviderRegistry, SemanticService


def test_step19_autocad_a_wall_fact_projects_to_ifc_wall_without_d5():
    snapshot = {
        "hostInstanceId": "autocad-session-1",
        "documentId": "C:/models/station.dwg",
        "revision": 42,
        "entities": [
            {
                "nativeId": "A31",
                "nativeKind": "LWPOLYLINE",
                "layer": "A-WALL",
            }
        ],
    }
    facts = DesignFactAdapter().normalize_snapshot(snapshot)

    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    registry.register(ENTERPRISE_MAPPING_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
            ProviderRef("dsp.enterprise.mapping", "1.0.0"),
        ),
        registry,
    )

    claims = SemanticService(registry, store).project_facts(facts, environment.environment_id)

    assert len(claims) == 1
    claim = claims[0]
    assert claim.subject.endswith("/A31")
    assert claim.predicate == "classification"
    assert claim.canonical_term_id == "ifc:IfcWall"
    assert claim.assurance == "RULE_DERIVED"
    assert claim.provider_id == "dsp.enterprise.mapping"
    assert claim.evidence[0].startswith("design-fact:")
