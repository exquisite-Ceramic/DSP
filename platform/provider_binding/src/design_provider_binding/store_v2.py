"""Step31 V2 owner-local immutable provider-binding-set reference store."""

from __future__ import annotations

from .contracts import ProviderBindingError
from .v2 import ProviderBindingSetV2


def _validate_reference(binding_set: ProviderBindingSetV2) -> None:
    """Validate the owner-issued content-addressed id/hash relation only.

    Full ``validate_provider_binding_set_v2`` requires the authoritative
    ExecutionSliceV2. Cross-owner lineage validation therefore remains in the
    composition layer instead of coupling this owner-local store to Step30.
    """
    if not isinstance(binding_set, ProviderBindingSetV2):
        raise TypeError("binding_set must be ProviderBindingSetV2")
    if binding_set.binding_set_id != f"PBSV2-{binding_set.binding_set_hash[:12]}":
        raise ProviderBindingError(
            "PROVIDER_BINDING_INTEGRITY_INVALID",
            "ProviderBindingSetV2 id does not match its owner hash",
        )


class InMemoryProviderBindingSetV2Store:
    """Reference in-memory lookup for immutable Step31 V2 binding sets."""

    def __init__(self) -> None:
        self._items: dict[str, ProviderBindingSetV2] = {}

    def put(self, binding_set: ProviderBindingSetV2) -> None:
        """Store one V2 binding set; exact replay is idempotent."""
        existing = self._items.get(binding_set.binding_set_id)
        if existing is not None and existing != binding_set:
            raise ProviderBindingError(
                "PROVIDER_BINDING_SET_REFERENCE_CONFLICT",
                f"provider binding-set reference conflicts: {binding_set.binding_set_id}",
            )
        _validate_reference(binding_set)
        if existing is None:
            self._items[binding_set.binding_set_id] = binding_set

    def get(self, binding_set_id: str) -> ProviderBindingSetV2:
        """Resolve one owner artifact and re-check its local id/hash relation."""
        try:
            binding_set = self._items[binding_set_id]
        except KeyError as exc:
            raise ProviderBindingError(
                "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND",
                f"provider binding-set reference is unresolved: {binding_set_id}",
            ) from exc
        _validate_reference(binding_set)
        return binding_set


__all__ = ["InMemoryProviderBindingSetV2Store"]
