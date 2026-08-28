"""Sanitized DSP-v0.6-aligned Semantic MCP tool errors."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.types import CallToolResult, TextContent
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


@dataclass(frozen=True)
class _ErrorContract:
    error_code: str
    category: str
    message: str


_ERROR_CONTRACTS: dict[type[SemanticServiceError], _ErrorContract] = {
    ManifestValidationError: _ErrorContract(
        "SEMANTIC_MANIFEST_INVALID",
        "SEMANTIC",
        "Semantic provider manifest is invalid.",
    ),
    ProviderRegistrationConflictError: _ErrorContract(
        "SEMANTIC_PROVIDER_REGISTRATION_CONFLICT",
        "CONSISTENCY",
        "Semantic provider registration conflicts with an existing immutable version.",
    ),
    ProviderNotFoundError: _ErrorContract(
        "SEMANTIC_PROVIDER_NOT_FOUND",
        "SEMANTIC",
        "Semantic provider was not found.",
    ),
    ProviderCapabilityError: _ErrorContract(
        "SEMANTIC_PROVIDER_CAPABILITY",
        "SEMANTIC",
        "Semantic provider capability requirements were not satisfied.",
    ),
    ProviderDependencyError: _ErrorContract(
        "SEMANTIC_PROVIDER_DEPENDENCY",
        "SEMANTIC",
        "Semantic provider dependency requirements were not satisfied.",
    ),
    NamespaceAuthorityError: _ErrorContract(
        "SEMANTIC_NAMESPACE_AUTHORITY",
        "SEMANTIC",
        "Semantic namespace authority requirements were not satisfied.",
    ),
    EnvironmentIntegrityError: _ErrorContract(
        "SEMANTIC_ENVIRONMENT_INTEGRITY",
        "CONSISTENCY",
        "Semantic environment integrity check failed.",
    ),
    EnvironmentNotFoundError: _ErrorContract(
        "SEMANTIC_ENVIRONMENT_NOT_FOUND",
        "SEMANTIC",
        "Semantic environment was not found.",
    ),
    TermResolutionError: _ErrorContract(
        "SEMANTIC_TERM_RESOLUTION",
        "SEMANTIC",
        "Semantic term resolution failed.",
    ),
}

_FALLBACK_SEMANTIC_ERROR = _ErrorContract(
    "SEMANTIC_SERVICE_ERROR",
    "SEMANTIC",
    "Semantic service request failed.",
)

_INTERNAL_ERROR = _ErrorContract(
    "SEMANTIC_INTERNAL_ERROR",
    "SEMANTIC",
    "Semantic service request failed.",
)


def _tool_error_result(contract: _ErrorContract) -> CallToolResult:
    payload = {
        "error": {
            "error_code": contract.error_code,
            "category": contract.category,
            "message": contract.message,
            "correlation_ids": [],
            "retryable": False,
            "details": [],
        }
    }
    return CallToolResult(
        content=[TextContent(type="text", text=contract.message)],
        structured_content=payload,
        is_error=True,
    )


def semantic_error_result(exc: SemanticServiceError) -> CallToolResult:
    """Map a known Core domain error to stable, sanitized remote semantics."""

    contract = _ERROR_CONTRACTS.get(type(exc), _FALLBACK_SEMANTIC_ERROR)
    return _tool_error_result(contract)


def internal_error_result() -> CallToolResult:
    """Return the generic sanitized result for an unexpected server failure."""

    return _tool_error_result(_INTERNAL_ERROR)
