"""In-memory provider registry cache for discovered design capabilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from autocad_sidecar.capability.profile import DesignCapabilityProfile, parse_design_capability


class RegistryCache:
    """Small deterministic cache used before the D4 Operation Resolver exists."""

    def __init__(self) -> None:
        self._by_provider: dict[str, tuple[DesignCapabilityProfile, ...]] = {}

    def replace_provider_tools(
        self,
        provider_server: str,
        tools: Iterable[Mapping[str, Any]],
    ) -> tuple[DesignCapabilityProfile, ...]:
        profiles = tuple(
            parse_design_capability(tool, provider_server=provider_server) for tool in tools
        )
        self._by_provider[provider_server] = profiles
        return profiles

    def providers_for(self, canonical_operation: str) -> tuple[DesignCapabilityProfile, ...]:
        matches = [
            profile
            for profiles in self._by_provider.values()
            for profile in profiles
            if profile.canonical_operation == canonical_operation
        ]
        return tuple(sorted(matches, key=lambda item: (item.provider_server, item.provider_tool)))

    def all_profiles(self) -> tuple[DesignCapabilityProfile, ...]:
        profiles = [profile for items in self._by_provider.values() for profile in items]
        return tuple(
            sorted(
                profiles,
                key=lambda item: (
                    item.canonical_operation,
                    item.provider_server,
                    item.provider_tool,
                ),
            )
        )
