"""Adapters at Semantic Runtime contract boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from semantic_runtime.freshness import AspectRequirement, GeometryLevel, SemanticAspect


def requirements_from_mappings(
    items: Iterable[Mapping[str, Any]],
) -> tuple[AspectRequirement, ...]:
    """Normalize D4/provider freshness metadata into D5 semantic requirements.

    The adapter is intentionally provider-neutral: it understands only the
    canonical freshness metadata shape and never imports an MCP/Host package.
    Unknown aspects, unsupported required states, and geometry levels fail
    closed instead of silently weakening the freshness barrier.
    """

    strongest: dict[SemanticAspect, GeometryLevel] = {}
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

        raw_level = item.get("geometry_level", "NONE")
        if isinstance(raw_level, GeometryLevel):
            geometry_level = raw_level
        else:
            level_name = str(raw_level or "NONE").strip().upper()
            try:
                geometry_level = GeometryLevel[level_name]
            except KeyError as exc:
                raise ValueError(f"unknown geometry_level: {level_name!r}") from exc

        requirement = AspectRequirement(aspect, geometry_level)
        strongest[aspect] = max(
            strongest.get(aspect, GeometryLevel.NONE),
            requirement.geometry_level,
        )

    return tuple(
        AspectRequirement(aspect, strongest[aspect])
        for aspect in sorted(strongest, key=lambda value: value.value)
    )
