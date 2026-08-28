"""Adapters at Semantic Runtime contract boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from semantic_runtime.freshness import (
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    GeometryLevel,
    SemanticAspect,
    SemanticDepth,
)


def _parse_enum(
    item: Mapping[str, Any],
    key: str,
    enum_type,
    *,
    default: str | None,
):
    raw_value = item.get(key, default)
    if raw_value is None and default is not None:
        raw_value = default
    if raw_value is None:
        return None
    if isinstance(raw_value, enum_type):
        return raw_value
    name = str(raw_value).strip().upper()
    try:
        return enum_type[name]
    except KeyError as exc:
        raise ValueError(f"unknown {key}: {name!r}") from exc


def _max_optional(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def requirements_from_mappings(
    items: Iterable[Mapping[str, Any]],
) -> tuple[AspectRequirement, ...]:
    """Normalize D4/provider freshness metadata into D5 semantic requirements.

    The adapter is intentionally provider-neutral: it understands only the
    canonical freshness metadata shape and never imports an MCP/Host package.
    Unknown aspects, unsupported required states, and progressive-axis values
    fail closed instead of silently weakening the freshness barrier.
    """

    strongest: dict[SemanticAspect, AspectRequirement] = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ValueError(f"freshness requirement {index} must be an object")

        raw_aspect = str(item.get("aspect") or "").strip().upper()
        if not raw_aspect:
            raise ValueError(f"freshness requirement {index} requires aspect")
        try:
            aspect = SemanticAspect(raw_aspect)
        except ValueError as exc:
            raise ValueError(f"unknown semantic aspect: {raw_aspect!r}") from exc

        required_state = str(item.get("required_state") or "FRESH").strip().upper()
        if required_state != "FRESH":
            raise ValueError(
                f"unsupported required_state for {aspect.value}: {required_state!r}"
            )

        geometry_level = _parse_enum(
            item,
            "geometry_level",
            GeometryLevel,
            default="NONE",
        )
        minimum_coverage = _parse_enum(
            item,
            "minimum_coverage",
            CoverageState,
            default=None,
        )
        semantic_depth = _parse_enum(
            item,
            "semantic_depth",
            SemanticDepth,
            default=None,
        )
        minimum_assurance = _parse_enum(
            item,
            "minimum_assurance",
            AssuranceLevel,
            default="UNKNOWN",
        )
        if geometry_level is None or minimum_assurance is None:
            raise AssertionError("required progressive enum default was not applied")

        requirement = AspectRequirement(
            aspect,
            geometry_level=geometry_level,
            minimum_coverage=minimum_coverage,
            semantic_depth=semantic_depth,
            minimum_assurance=minimum_assurance,
        )
        current = strongest.get(aspect)
        if current is None:
            strongest[aspect] = requirement
            continue
        strongest[aspect] = AspectRequirement(
            aspect,
            geometry_level=max(current.geometry_level, requirement.geometry_level),
            minimum_coverage=_max_optional(
                current.minimum_coverage,
                requirement.minimum_coverage,
            ),
            semantic_depth=_max_optional(
                current.semantic_depth,
                requirement.semantic_depth,
            ),
            minimum_assurance=max(
                current.minimum_assurance,
                requirement.minimum_assurance,
            ),
        )

    return tuple(
        strongest[aspect]
        for aspect in sorted(strongest, key=lambda value: value.value)
    )
