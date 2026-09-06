from dataclasses import replace

import pytest
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyError,
    MaterializationTopologyRegistry,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
)


def _snapshot(
    *,
    environment: str = "TOPO-ENV-1",
    revision: int = 1,
    document_ref: str = "DOC-AUTOCAD",
) -> MaterializationTopologySnapshot:
    slot = MaterializationSlot(
        materialization_slot_id="MS-AUTOCAD",
        semantic_target_ref="WALL-001",
        required_host_type="autocad",
        document_ref=document_ref,
        requirement=MaterializationRequirement.REQUIRED,
    )
    draft = MaterializationTopologySnapshot(
        topology_environment_id=environment,
        topology_revision=revision,
        slots=(slot,),
        topology_snapshot_hash="0" * 64,
    )
    return replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))


def test_identical_registration_is_idempotent():
    registry = MaterializationTopologyRegistry()
    snapshot = _snapshot()
    registry.register(snapshot)
    registry.register(snapshot)
    assert registry.get("TOPO-ENV-1", 1) == snapshot


def test_conflicting_same_environment_revision_fails_closed():
    registry = MaterializationTopologyRegistry()
    registry.register(_snapshot())

    with pytest.raises(MaterializationTopologyError) as exc:
        registry.register(_snapshot(document_ref="DOC-OTHER"))
    assert exc.value.code == "MATERIALIZATION_TOPOLOGY_MISMATCH"


def test_different_revision_is_a_distinct_immutable_snapshot():
    registry = MaterializationTopologyRegistry()
    first = _snapshot(revision=1)
    second = _snapshot(revision=2)
    registry.register(first)
    registry.register(second)
    assert registry.get("TOPO-ENV-1", 1) == first
    assert registry.get("TOPO-ENV-1", 2) == second


def test_missing_snapshot_raises_explicit_not_found_error():
    registry = MaterializationTopologyRegistry()
    with pytest.raises(MaterializationTopologyError) as exc:
        registry.get("TOPO-ENV-404", 9)
    assert exc.value.code == "MATERIALIZATION_TOPOLOGY_NOT_FOUND"
