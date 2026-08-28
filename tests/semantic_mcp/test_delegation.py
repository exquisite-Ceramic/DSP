import json

import pytest
from mcp import Client
from mcp.types import TextContent
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
from semantic_mcp.server import build_mcp_server

from tests.semantic_mcp.helpers import FakeSemanticService


PROVENANCE = ProviderProvenance(
    "buildingSMART.ifc43",
    "4.3.2.0",
    "ifc-content",
)

CLAIM_INPUT = {
    "subject": "S-WALL-001",
    "predicate": "dsp:WallThickness",
    "canonical_term_id": "ifc:IfcWall",
    "value": 300,
    "unit": "mm",
    "assurance": "RULE_DERIVED",
    "provenance": ["host:A31"],
    "evidence": ["layer:A-WALL"],
    "provider_id": "acme.semantic",
    "provider_version": "1",
}

CORE_CLAIM = SemanticClaim(
    subject="S-WALL-001",
    predicate="dsp:WallThickness",
    canonical_term_id="ifc:IfcWall",
    value=300,
    unit="mm",
    assurance="RULE_DERIVED",
    provenance=("host:A31",),
    evidence=("layer:A-WALL",),
    provider_id="acme.semantic",
    provider_version="1",
)


def _assert_success(result, payload):
    assert result.is_error is False
    assert result.structured_content == payload
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _provider_payload(manifest: SemanticProviderManifest):
    return {
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


def _manifest():
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


@pytest.mark.asyncio
async def test_vocabulary_tools_delegate_once_with_exact_arguments_and_payloads():
    service = FakeSemanticService()
    service.resolve_result = ResolvedTerm("ifc:IfcWall", "ENTITY", PROVENANCE)
    service.describe_result = TermDescription("ifc:IfcWall", "Wall", "en", PROVENANCE)
    service.schema_result = TermSchema(
        "ifc:IfcWall",
        {"allowed": frozenset({"B", "A"}), "type": "object"},
        PROVENANCE,
    )

    async with Client(build_mcp_server(service)) as client:
        resolved = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:abc"},
        )
        described = await client.call_tool(
            "semantic.describe_term",
            {
                "term_id": "ifc:IfcWall",
                "environment_id": "sem-env:abc",
                "locale": "en",
            },
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:abc"},
        )

    assert service.resolve_calls == [("ifc:IfcWall", "sem-env:abc")]
    assert service.describe_calls == [("ifc:IfcWall", "sem-env:abc", "en")]
    assert service.schema_calls == [("ifc:IfcWall", "sem-env:abc")]

    provenance = {
        "provider_id": "buildingSMART.ifc43",
        "version": "4.3.2.0",
        "content_hash": "ifc-content",
    }
    _assert_success(
        resolved,
        {"term_id": "ifc:IfcWall", "kind": "ENTITY", "provenance": provenance},
    )
    _assert_success(
        described,
        {
            "term_id": "ifc:IfcWall",
            "text": "Wall",
            "locale": "en",
            "provenance": provenance,
        },
    )
    _assert_success(
        schema,
        {
            "term_id": "ifc:IfcWall",
            "schema": {"allowed": ["A", "B"], "type": "object"},
            "provenance": provenance,
        },
    )


@pytest.mark.asyncio
async def test_validation_and_mapping_delegate_without_voting_winner_or_resorting():
    service = FakeSemanticService()
    service.validation_result = (
        ValidationFinding("rule-b", ValidationStatus.FAIL, PROVENANCE, "failed"),
        ValidationFinding("rule-a", ValidationStatus.PASS, PROVENANCE),
    )
    service.mapping_result = (
        MappingCandidate("map-b", "ifc:IfcWall", PROVENANCE, ("e2",)),
        MappingCandidate("map-a", "ifc:IfcDoor", PROVENANCE, ("e1",)),
    )

    async with Client(build_mcp_server(service)) as client:
        validation = await client.call_tool(
            "semantic.validate_claim",
            {"environment_id": "sem-env:abc", "claim": CLAIM_INPUT},
        )
        mappings = await client.call_tool(
            "semantic.find_mappings",
            {
                "environment_id": "sem-env:abc",
                "source_claim": CLAIM_INPUT,
                "target_namespace": "ifc",
            },
        )

    assert service.validate_calls == [(CORE_CLAIM, "sem-env:abc")]
    assert service.mapping_calls == [(CORE_CLAIM, "sem-env:abc", "ifc")]

    provenance = {
        "provider_id": "buildingSMART.ifc43",
        "version": "4.3.2.0",
        "content_hash": "ifc-content",
    }
    _assert_success(
        validation,
        {
            "findings": [
                {
                    "rule_id": "rule-b",
                    "status": "FAIL",
                    "message": "failed",
                    "provenance": provenance,
                },
                {
                    "rule_id": "rule-a",
                    "status": "PASS",
                    "message": None,
                    "provenance": provenance,
                },
            ]
        },
    )
    _assert_success(
        mappings,
        {
            "mappings": [
                {
                    "mapping_id": "map-b",
                    "target_term_id": "ifc:IfcWall",
                    "evidence": ["e2"],
                    "provenance": provenance,
                },
                {
                    "mapping_id": "map-a",
                    "target_term_id": "ifc:IfcDoor",
                    "evidence": ["e1"],
                    "provenance": provenance,
                },
            ]
        },
    )


@pytest.mark.asyncio
async def test_manifest_and_environment_delegate_exactly_and_emit_machine_payloads():
    service = FakeSemanticService()
    manifest = _manifest()
    environment = SemanticEnvironment.create((PinnedProvider.from_manifest(manifest),))
    service.manifest_result = manifest
    service.environment_result = environment

    async with Client(build_mcp_server(service)) as client:
        manifest_result = await client.call_tool(
            "semantic.get_provider_manifest",
            {"provider_id": "buildingSMART.ifc43", "version": "4.3.2.0"},
        )
        environment_result = await client.call_tool(
            "semantic.get_environment",
            {"environment_id": environment.environment_id},
        )

    assert service.manifest_calls == [("buildingSMART.ifc43", "4.3.2.0")]
    assert service.environment_calls == [environment.environment_id]

    provider = _provider_payload(manifest)
    _assert_success(manifest_result, provider)
    _assert_success(
        environment_result,
        {
            "environment_id": environment.environment_id,
            "content_hash": environment.content_hash,
            "providers": [provider],
        },
    )
