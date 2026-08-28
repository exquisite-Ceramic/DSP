import importlib
import math
from types import MappingProxyType

import pytest
from pydantic import ValidationError
from semantic_service import (
    AuthorityMode,
    MappingCandidate,
    NamespaceAuthority,
    ProviderProvenance,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticClaim,
    SemanticEnvironment,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
    ValidationFinding,
    ValidationStatus,
)
from semantic_service.environment import PinnedProvider


def _wire():
    try:
        return importlib.import_module("semantic_mcp.wire")
    except ModuleNotFoundError:
        pytest.fail("semantic_mcp.wire is not implemented")


def _provenance() -> ProviderProvenance:
    return ProviderProvenance("buildingSMART.ifc43", "4.3.2.0", "ifc-content")


def _manifest() -> SemanticProviderManifest:
    return SemanticProviderManifest(
        provider_id="buildingSMART.ifc43",
        provider_type=ProviderType.STANDARD,
        version="4.3.2.0",
        content_hash="ifc-content",
        namespaces=("ifc",),
        capabilities=frozenset({SemanticCapability.VALIDATION, SemanticCapability.VOCABULARY}),
        authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
        compatibility=("semantic-service.v1",),
        requires=(),
    )


def test_json_codec_recurses_and_canonicalizes_unordered_values():
    wire = _wire()
    value = MappingProxyType({
        "kinds": frozenset({"wall", "door"}),
        "values": (1, True, None),
    })
    assert wire.to_json_value(value) == {
        "kinds": ["door", "wall"],
        "values": [1, True, None],
    }


def test_json_codec_rejects_runtime_object():
    wire = _wire()
    with pytest.raises(TypeError, match="not JSON-safe"):
        wire.to_json_value(object())


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_json_codec_rejects_non_finite_number(value):
    wire = _wire()
    with pytest.raises(TypeError, match="finite"):
        wire.to_json_value(value)


def test_claim_input_builds_core_claim_without_coercion():
    wire = _wire()
    model = wire.SemanticClaimInput.model_validate({
        "subject": "S-WALL-001",
        "predicate": "dsp:WallThickness",
        "canonical_term_id": "ifc:IfcWall",
        "value": {"amount": 300, "tags": ["design"]},
        "unit": "mm",
        "assurance": "RULE_DERIVED",
        "provenance": ["host:A31"],
        "evidence": ["layer:A-WALL"],
        "provider_id": "acme.semantic",
        "provider_version": "1",
    })
    claim = wire.decode_semantic_claim(model)
    assert claim == SemanticClaim(
        subject="S-WALL-001",
        predicate="dsp:WallThickness",
        canonical_term_id="ifc:IfcWall",
        value={"amount": 300, "tags": ["design"]},
        unit="mm",
        assurance="RULE_DERIVED",
        provenance=("host:A31",),
        evidence=("layer:A-WALL",),
        provider_id="acme.semantic",
        provider_version="1",
    )


def test_claim_input_rejects_unknown_field():
    wire = _wire()
    with pytest.raises(ValidationError):
        wire.SemanticClaimInput.model_validate({"subject": "S-1", "unknown": 1})


def test_claim_input_rejects_missing_subject():
    wire = _wire()
    with pytest.raises(ValidationError):
        wire.SemanticClaimInput.model_validate({"assurance": "UNKNOWN"})


def test_claim_input_rejects_string_coercion():
    wire = _wire()
    with pytest.raises(ValidationError):
        wire.SemanticClaimInput.model_validate({"subject": 123})
    with pytest.raises(ValidationError):
        wire.SemanticClaimInput.model_validate({"subject": "S-1", "provenance": [123]})


def test_claim_input_rejects_non_json_value():
    wire = _wire()
    with pytest.raises(ValidationError):
        wire.SemanticClaimInput.model_validate({"subject": "S-1", "value": object()})


def test_explicit_term_encoders_have_exact_shape():
    wire = _wire()
    provenance = _provenance()
    assert wire.encode_resolved_term(ResolvedTerm("ifc:IfcWall", "ENTITY", provenance)) == {
        "term_id": "ifc:IfcWall",
        "kind": "ENTITY",
        "provenance": {
            "provider_id": "buildingSMART.ifc43",
            "version": "4.3.2.0",
            "content_hash": "ifc-content",
        },
    }
    assert wire.encode_term_description(
        TermDescription("ifc:IfcWall", "Wall", "en", provenance)
    ) == {
        "term_id": "ifc:IfcWall",
        "text": "Wall",
        "locale": "en",
        "provenance": {
            "provider_id": "buildingSMART.ifc43",
            "version": "4.3.2.0",
            "content_hash": "ifc-content",
        },
    }
    schema = TermSchema(
        "ifc:IfcWall",
        {"allowed": frozenset({"B", "A"}), "type": "object"},
        provenance,
    )
    assert wire.encode_term_schema(schema) == {
        "term_id": "ifc:IfcWall",
        "schema": {"allowed": ["A", "B"], "type": "object"},
        "provenance": {
            "provider_id": "buildingSMART.ifc43",
            "version": "4.3.2.0",
            "content_hash": "ifc-content",
        },
    }


def test_validation_and_mapping_encoders_preserve_input_order():
    wire = _wire()
    provenance = _provenance()
    findings = (
        ValidationFinding("rule-b", ValidationStatus.FAIL, provenance, "failed"),
        ValidationFinding("rule-a", ValidationStatus.PASS, provenance),
    )
    assert wire.encode_validation_findings(findings) == {
        "findings": [
            {
                "rule_id": "rule-b",
                "status": "FAIL",
                "message": "failed",
                "provenance": {
                    "provider_id": "buildingSMART.ifc43",
                    "version": "4.3.2.0",
                    "content_hash": "ifc-content",
                },
            },
            {
                "rule_id": "rule-a",
                "status": "PASS",
                "message": None,
                "provenance": {
                    "provider_id": "buildingSMART.ifc43",
                    "version": "4.3.2.0",
                    "content_hash": "ifc-content",
                },
            },
        ]
    }
    mappings = (
        MappingCandidate("map-b", "ifc:IfcWall", provenance, ("e2",)),
        MappingCandidate("map-a", "ifc:IfcDoor", provenance, ("e1",)),
    )
    assert wire.encode_mapping_candidates(mappings) == {
        "mappings": [
            {
                "mapping_id": "map-b",
                "target_term_id": "ifc:IfcWall",
                "evidence": ["e2"],
                "provenance": {
                    "provider_id": "buildingSMART.ifc43",
                    "version": "4.3.2.0",
                    "content_hash": "ifc-content",
                },
            },
            {
                "mapping_id": "map-a",
                "target_term_id": "ifc:IfcDoor",
                "evidence": ["e1"],
                "provenance": {
                    "provider_id": "buildingSMART.ifc43",
                    "version": "4.3.2.0",
                    "content_hash": "ifc-content",
                },
            },
        ]
    }


def test_manifest_and_environment_encoders_match_machine_payload():
    wire = _wire()
    manifest = _manifest()
    expected_provider = {
        "provider_id": "buildingSMART.ifc43",
        "provider_type": "STANDARD",
        "version": "4.3.2.0",
        "content_hash": "ifc-content",
        "manifest_hash": manifest.manifest_hash,
        "namespaces": ["ifc"],
        "capabilities": ["VALIDATION", "VOCABULARY"],
        "authority": [{"namespace": "ifc", "mode": "AUTHORITATIVE"}],
        "compatibility": ["semantic-service.v1"],
        "requires": [],
    }
    assert wire.encode_manifest(manifest) == expected_provider

    environment = SemanticEnvironment.create((PinnedProvider.from_manifest(manifest),))
    assert wire.encode_environment(environment) == {
        "environment_id": environment.environment_id,
        "content_hash": environment.content_hash,
        "providers": [expected_provider],
    }
