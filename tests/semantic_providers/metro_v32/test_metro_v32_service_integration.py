import pytest

from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from metro_semantic_provider import METRO_V32_CATALOG, METRO_V32_PROVIDER
from semantic_service import (
    AuthorityMode,
    ProviderDependencyError,
    ProviderRef,
    SemanticClaim,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
    ValidationStatus,
)

DSP_REF = ProviderRef("dsp.core", "1.0")
IFC_REF = ProviderRef("buildingSMART.ifc43", "4.3.2.0")
METRO_REF = ProviderRef("dsp.metro.semantic", "3.2")


def _registry(*providers):
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry


def _service_with_ifc_metro():
    registry = _registry(IFC43_PROVIDER, METRO_V32_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin((IFC_REF, METRO_REF), registry)
    return SemanticService(registry, store), environment


def _ifc_strings(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if value.startswith("ifc:"):
            found.add(value)
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            found.update(_ifc_strings(key))
            found.update(_ifc_strings(item))
        return found
    if hasattr(value, "items"):
        for key, item in value.items():
            found.update(_ifc_strings(key))
            found.update(_ifc_strings(item))
        return found
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            found.update(_ifc_strings(item))
    return found


def _machine_ifc_references() -> set[str]:
    refs: set[str] = set()
    for term in METRO_V32_CATALOG.terms:
        refs.update(_ifc_strings(term.schema))
    for mapping in METRO_V32_CATALOG.mappings:
        if mapping.state.value != "ACTIVE":
            continue
        refs.add(mapping.target_term_id)
        for constraint in mapping.constraints:
            refs.add(constraint.term_id)
            refs.update(_ifc_strings(constraint.equals))
    for decision in METRO_V32_CATALOG.decisions:
        refs.update(_ifc_strings(decision.options))
        refs.update(_ifc_strings(decision.recommended_option))
        refs.update(_ifc_strings(decision.selected_option))
    for rule in METRO_V32_CATALOG.validation_rules:
        refs.update(_ifc_strings(rule.operands))
    return refs


def test_metro_only_environment_fails_exact_ifc_dependency():
    registry = _registry(METRO_V32_PROVIDER)
    store = SemanticEnvironmentStore()
    with pytest.raises(ProviderDependencyError, match="buildingSMART.ifc43@4.3.2.0"):
        store.pin((METRO_REF,), registry)


def test_ifc_and_metro_pin_with_distinct_namespace_authority():
    service, environment = _service_with_ifc_metro()
    ifc = service.resolve_term("ifc:IfcWall", environment.environment_id)
    metro = service.resolve_term("metro:RunningRail", environment.environment_id)
    assert ifc.provenance.provider_id == "buildingSMART.ifc43"
    assert metro.provenance.provider_id == "dsp.metro.semantic"

    authoritative = {
        authority.namespace: pinned.provider_id
        for pinned in environment.providers
        for authority in pinned.authority
        if authority.mode is AuthorityMode.AUTHORITATIVE
    }
    assert authoritative == {
        "ifc": "buildingSMART.ifc43",
        "metro": "dsp.metro.semantic",
    }


def test_dsp_ifc_and_metro_share_one_environment_with_three_authoritative_owners():
    registry = _registry(DSP_CORE_PROVIDER, IFC43_PROVIDER, METRO_V32_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin((DSP_REF, IFC_REF, METRO_REF), registry)
    authoritative = {
        authority.namespace: pinned.provider_id
        for pinned in environment.providers
        for authority in pinned.authority
        if authority.mode is AuthorityMode.AUTHORITATIVE
    }
    assert authoritative == {
        "dsp": "dsp.core",
        "ifc": "buildingSMART.ifc43",
        "metro": "dsp.metro.semantic",
    }


def test_every_machine_ifc_reference_resolves_through_ifc43_authority():
    service, environment = _service_with_ifc_metro()
    refs = _machine_ifc_references()
    assert refs
    for term_id in sorted(refs):
        resolved = service.resolve_term(term_id, environment.environment_id)
        assert resolved.term_id == term_id
        assert resolved.provenance.provider_id == "buildingSMART.ifc43"


def test_service_mapping_has_metro_provenance_and_legal_ifc_target():
    service, environment = _service_with_ifc_metro()
    results = service.find_mappings(
        SemanticClaim(subject="rail-1", canonical_term_id="metro:RunningRail"),
        environment.environment_id,
        "ifc",
    )
    assert [(item.mapping_id, item.target_term_id) for item in results] == [
        ("metro:Mapping.RunningRail.ToIfcRail", "ifc:IfcRail")
    ]
    assert results[0].provenance.provider_id == "dsp.metro.semantic"
    assert service.resolve_term(
        results[0].target_term_id,
        environment.environment_id,
    ).provenance.provider_id == "buildingSMART.ifc43"


def test_ifc_tunnel_is_not_vocabulary_but_metro_prohibition_still_runs():
    service, environment = _service_with_ifc_metro()
    findings = service.validate_claim(
        SemanticClaim(subject="x", canonical_term_id="ifc:IfcTunnel"),
        environment.environment_id,
    )
    assert any(
        item.provider_id == "dsp.metro.semantic"
        and item.rule_id == "metro:Rule.ProhibitIfcTunnelEntity"
        and item.status is ValidationStatus.FAIL
        for item in findings
    )
