from __future__ import annotations

import pytest

from semantic_runtime import IdentityBinding, IdentityConflictError, IdentityRegistry


def test_ifc_global_id_can_be_bound_on_demand_and_round_trips() -> None:
    registry = IdentityRegistry()
    original = registry.bind(IdentityBinding("sem-1", "doc-1", "A1"))

    assert original.ifc_global_id is None

    updated = registry.bind_ifc_global_id("sem-1", "ifc-1")

    assert updated.ifc_global_id == "ifc-1"
    assert registry.by_semantic("sem-1") == updated
    assert registry.by_native("doc-1", "A1") == updated
    assert registry.by_ifc_global_id("ifc-1") == updated
    assert registry.bind_ifc_global_id("sem-1", "ifc-1") == updated


def test_ifc_global_id_is_unique_across_semantic_bindings() -> None:
    registry = IdentityRegistry()
    first = registry.bind(IdentityBinding("sem-1", "doc-1", "A1", "ifc-1"))
    registry.bind(IdentityBinding("sem-2", "doc-1", "A2"))

    assert registry.by_ifc_global_id("ifc-1") == first

    with pytest.raises(IdentityConflictError):
        registry.bind_ifc_global_id("sem-2", "ifc-1")

    with pytest.raises(IdentityConflictError):
        registry.bind(IdentityBinding("sem-3", "doc-1", "A3", "ifc-1"))
