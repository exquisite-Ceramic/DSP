"""Design Capability Profile parsing for MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

META_PREFIX = "com.company.design/"
OPERATION_KEY = f"{META_PREFIX}operation"
CATEGORY_KEY = f"{META_PREFIX}category"
ENTITIES_KEY = f"{META_PREFIX}entities"
EXECUTION_FRESHNESS_KEY = f"{META_PREFIX}execution_freshness"
EFFECTS_KEY = f"{META_PREFIX}effects"
RISK_KEY = f"{META_PREFIX}risk"
PREVIEW_KEY = f"{META_PREFIX}preview"
ROLLBACK_KEY = f"{META_PREFIX}rollback"
IDEMPOTENT_KEY = f"{META_PREFIX}idempotent"
VERIFICATION_KEY = f"{META_PREFIX}verification"

VALID_CATEGORIES = frozenset({"MODEL_OPERATION", "INTERACTION", "VIEW", "CONTEXT"})


@dataclass(frozen=True, slots=True)
class DesignCapabilityProfile:
    """Normalized provider-level capability metadata discovered from MCP tools/list."""

    provider_server: str
    provider_tool: str
    canonical_operation: str
    category: str
    entity_constraints: tuple[str, ...]
    execution_freshness: tuple[dict[str, Any], ...]
    effects: tuple[Any, ...]
    risk: str | None
    preview_supported: bool
    rollback_supported: bool
    idempotent: bool
    verification_contract: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    description: str | None


def _sequence(value: Any, *, field: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    return tuple(value)


def parse_design_capability(
    tool: Mapping[str, Any],
    *,
    provider_server: str,
) -> DesignCapabilityProfile:
    """Parse one MCP Tool object into the platform's provider-level profile.

    Provider identity remains separate from canonical operation identity. The
    parser intentionally treats provider `_meta` as claims; trust/policy
    certification happens later in the registry/resolver pipeline.
    """

    provider_server = provider_server.strip()
    if not provider_server:
        raise ValueError("provider_server is required")

    provider_tool = str(tool.get("name") or "").strip()
    if not provider_tool:
        raise ValueError("MCP tool name is required")

    raw_meta = tool.get("_meta") or {}
    if not isinstance(raw_meta, Mapping):
        raise ValueError("MCP tool _meta must be an object")

    canonical_operation = str(raw_meta.get(OPERATION_KEY) or "").strip()
    if not canonical_operation:
        raise ValueError("canonical operation metadata is required")

    category = str(raw_meta.get(CATEGORY_KEY) or "").strip()
    if category not in VALID_CATEGORIES:
        raise ValueError(f"invalid design capability category: {category!r}")

    entity_constraints = tuple(
        str(item) for item in _sequence(raw_meta.get(ENTITIES_KEY), field=ENTITIES_KEY)
    )

    freshness_items = _sequence(
        raw_meta.get(EXECUTION_FRESHNESS_KEY), field=EXECUTION_FRESHNESS_KEY
    )
    execution_freshness: list[dict[str, Any]] = []
    for item in freshness_items:
        if not isinstance(item, Mapping):
            raise ValueError(f"{EXECUTION_FRESHNESS_KEY} entries must be objects")
        execution_freshness.append(dict(item))

    effects = _sequence(raw_meta.get(EFFECTS_KEY), field=EFFECTS_KEY)

    raw_verification = raw_meta.get(VERIFICATION_KEY) or {}
    if not isinstance(raw_verification, Mapping):
        raise ValueError(f"{VERIFICATION_KEY} must be an object")

    raw_input_schema = tool.get("inputSchema") or {}
    if not isinstance(raw_input_schema, Mapping):
        raise ValueError("inputSchema must be an object")

    raw_output_schema = tool.get("outputSchema")
    if raw_output_schema is not None and not isinstance(raw_output_schema, Mapping):
        raise ValueError("outputSchema must be an object when present")

    description = tool.get("description")
    if description is not None and not isinstance(description, str):
        description = str(description)

    risk = raw_meta.get(RISK_KEY)
    if risk is not None:
        risk = str(risk)

    return DesignCapabilityProfile(
        provider_server=provider_server,
        provider_tool=provider_tool,
        canonical_operation=canonical_operation,
        category=category,
        entity_constraints=entity_constraints,
        execution_freshness=tuple(execution_freshness),
        effects=effects,
        risk=risk,
        preview_supported=bool(raw_meta.get(PREVIEW_KEY, False)),
        rollback_supported=bool(raw_meta.get(ROLLBACK_KEY, False)),
        idempotent=bool(raw_meta.get(IDEMPOTENT_KEY, False)),
        verification_contract=dict(raw_verification),
        input_schema=dict(raw_input_schema),
        output_schema=dict(raw_output_schema) if raw_output_schema is not None else None,
        description=description,
    )
