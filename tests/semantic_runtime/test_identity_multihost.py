from __future__ import annotations

import pytest

from semantic_runtime import (
    ExternalIdentity,
    HostBinding,
    IdentityConflictError,
    IdentityRegistry,
    SemanticIdentity,
)


def test_one_semantic_identity_can_bind_autocad_and_revit() -> None:
    registry = IdentityRegistry()
    identity = registry.ensure_identity("S-WALL-001")
    cad = registry.bind_host(
        HostBinding("S-WALL-001", "autocad", "dwg-1", "A31", "LWPOLYLINE")
    )
    revit = registry.bind_host(
        HostBinding("S-WALL-001", "revit", "rvt-1", "38912", "Wall")
    )

    assert identity == SemanticIdentity("S-WALL-001")
    assert registry.by_semantic("S-WALL-001") == identity
    assert registry.host_bindings("S-WALL-001") == (cad, revit)
    assert registry.by_host("autocad", "dwg-1", "A31") == cad
    assert registry.by_host("revit", "rvt-1", "38912") == revit


def test_ifc_global_id_is_generic_external_identity() -> None:
    registry = IdentityRegistry()
    registry.ensure_identity("S-WALL-001")
    external = registry.bind_external(
        ExternalIdentity("S-WALL-001", "ifc.global_id", "2Ksd")
    )

    assert registry.external_identities("S-WALL-001") == (external,)
    assert registry.by_external("ifc.global_id", "2Ksd") == external


def test_host_key_cannot_be_rebound_to_another_semantic_identity() -> None:
    registry = IdentityRegistry()
    registry.ensure_identity("S-1")
    registry.ensure_identity("S-2")
    registry.bind_host(HostBinding("S-1", "autocad", "doc-1", "A1", "LINE"))

    with pytest.raises(IdentityConflictError):
        registry.bind_host(HostBinding("S-2", "autocad", "doc-1", "A1", "LINE"))


def test_external_key_cannot_be_rebound_to_another_semantic_identity() -> None:
    registry = IdentityRegistry()
    registry.ensure_identity("S-1")
    registry.ensure_identity("S-2")
    registry.bind_external(ExternalIdentity("S-1", "ifc.global_id", "2Ksd"))

    with pytest.raises(IdentityConflictError):
        registry.bind_external(ExternalIdentity("S-2", "ifc.global_id", "2Ksd"))
