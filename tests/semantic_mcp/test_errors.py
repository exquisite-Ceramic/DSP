import importlib

import pytest
from mcp import Client
from mcp.types import TextContent
from semantic_service import (
    EnvironmentIntegrityError,
    EnvironmentNotFoundError,
    ManifestValidationError,
    NamespaceAuthorityError,
    ProviderCapabilityError,
    ProviderDependencyError,
    ProviderNotFoundError,
    ProviderRegistrationConflictError,
    SemanticServiceError,
    TermResolutionError,
)
from semantic_mcp.server import build_mcp_server

from tests.semantic_mcp.helpers import FakeSemanticService


def _errors():
    try:
        return importlib.import_module("semantic_mcp.errors")
    except ModuleNotFoundError:
        pytest.fail("semantic_mcp.errors is not implemented")


CASES = (
    (
        ManifestValidationError,
        "SEMANTIC_MANIFEST_INVALID",
        "SEMANTIC",
        "Semantic provider manifest is invalid.",
    ),
    (
        ProviderRegistrationConflictError,
        "SEMANTIC_PROVIDER_REGISTRATION_CONFLICT",
        "CONSISTENCY",
        "Semantic provider registration conflicts with an existing immutable version.",
    ),
    (
        ProviderNotFoundError,
        "SEMANTIC_PROVIDER_NOT_FOUND",
        "SEMANTIC",
        "Semantic provider was not found.",
    ),
    (
        ProviderCapabilityError,
        "SEMANTIC_PROVIDER_CAPABILITY",
        "SEMANTIC",
        "Semantic provider capability requirements were not satisfied.",
    ),
    (
        ProviderDependencyError,
        "SEMANTIC_PROVIDER_DEPENDENCY",
        "SEMANTIC",
        "Semantic provider dependency requirements were not satisfied.",
    ),
    (
        NamespaceAuthorityError,
        "SEMANTIC_NAMESPACE_AUTHORITY",
        "SEMANTIC",
        "Semantic namespace authority requirements were not satisfied.",
    ),
    (
        EnvironmentIntegrityError,
        "SEMANTIC_ENVIRONMENT_INTEGRITY",
        "CONSISTENCY",
        "Semantic environment integrity check failed.",
    ),
    (
        EnvironmentNotFoundError,
        "SEMANTIC_ENVIRONMENT_NOT_FOUND",
        "SEMANTIC",
        "Semantic environment was not found.",
    ),
    (
        TermResolutionError,
        "SEMANTIC_TERM_RESOLUTION",
        "SEMANTIC",
        "Semantic term resolution failed.",
    ),
    (
        SemanticServiceError,
        "SEMANTIC_SERVICE_ERROR",
        "SEMANTIC",
        "Semantic service request failed.",
    ),
)


@pytest.mark.parametrize("error_type,error_code,category,message", CASES)
def test_semantic_error_result_uses_stable_dsp_error_shape(
    error_type, error_code, category, message
):
    errors = _errors()
    result = errors.semantic_error_result(error_type("private implementation detail"))

    assert result.is_error is True
    assert result.structured_content == {
        "error": {
            "error_code": error_code,
            "category": category,
            "message": message,
            "correlation_ids": [],
            "retryable": False,
            "details": [],
        }
    }
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == message


def test_semantic_error_result_never_forwards_raw_exception_text():
    errors = _errors()
    result = errors.semantic_error_result(
        ProviderNotFoundError("secret=/srv/acme/token=abc123 https://internal.example")
    )
    rendered = str(result.model_dump(by_alias=True))
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered
    assert "internal.example" not in rendered


def test_internal_error_result_is_sanitized_and_main_spec_aligned():
    errors = _errors()
    result = errors.internal_error_result()

    assert result.is_error is True
    assert result.structured_content == {
        "error": {
            "error_code": "SEMANTIC_INTERNAL_ERROR",
            "category": "SEMANTIC",
            "message": "Semantic service request failed.",
            "correlation_ids": [],
            "retryable": False,
            "details": [],
        }
    }
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Semantic service request failed."


@pytest.mark.asyncio
async def test_tool_maps_core_domain_error_to_structured_dsp_error_shape():
    service = FakeSemanticService()
    service.resolve_error = EnvironmentNotFoundError(
        "secret=/srv/acme/environment-token=abc123"
    )

    async with Client(build_mcp_server(service)) as client:
        result = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:missing"},
        )

    assert service.resolve_calls == [("ifc:IfcWall", "sem-env:missing")]
    assert result.is_error is True
    assert result.structured_content == {
        "error": {
            "error_code": "SEMANTIC_ENVIRONMENT_NOT_FOUND",
            "category": "SEMANTIC",
            "message": "Semantic environment was not found.",
            "correlation_ids": [],
            "retryable": False,
            "details": [],
        }
    }
    rendered = str(result.model_dump(by_alias=True))
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered


@pytest.mark.asyncio
async def test_tool_sanitizes_unexpected_failure_to_internal_error_shape():
    service = FakeSemanticService()
    service.resolve_error = RuntimeError(
        "secret-path=/srv/acme/token=abc123 https://internal.example"
    )

    async with Client(build_mcp_server(service)) as client:
        result = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:abc"},
        )

    assert service.resolve_calls == [("ifc:IfcWall", "sem-env:abc")]
    assert result.is_error is True
    assert result.structured_content == {
        "error": {
            "error_code": "SEMANTIC_INTERNAL_ERROR",
            "category": "SEMANTIC",
            "message": "Semantic service request failed.",
            "correlation_ids": [],
            "retryable": False,
            "details": [],
        }
    }
    rendered = str(result.model_dump(by_alias=True))
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered
    assert "internal.example" not in rendered
