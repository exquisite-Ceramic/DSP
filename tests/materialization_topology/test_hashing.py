from dataclasses import replace

import pytest
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyError,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
    validate_materialization_topology_snapshot,
)


def _slot(
    slot_id: str,
    host_type: str,
    document_ref: str,
    semantic_target_ref: str = "WALL-001",
) -> MaterializationSlot:
    return MaterializationSlot(
        materialization_slot_id=slot_id,
        semantic_target_ref=semantic_target_ref,
        required_host_type=host_type,
        document_ref=document_ref,
        requirement=MaterializationRequirement.REQUIRED,
    )


def _snapshot(
    *,
    environment: str = "TOPO-ENV-1",
    revision: int = 1,
    slots: tuple[MaterializationSlot, ...] | None = None,
) -> MaterializationTopologySnapshot:
    if slots is None:
        slots = (
            _slot("MS-AUTOCAD", "autocad", "DOC-AUTOCAD"),
            _slot("MS-REVIT", "revit", "DOC-REVIT"),
        )
    draft = MaterializationTopologySnapshot(
        topology_environment_id=environment,
        topology_revision=revision,
        slots=slots,
        topology_snapshot_hash="0" * 64,
    )
    return replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))


def test_slot_order_is_hash_insensitive():
    snapshot = _snapshot()
    reversed_snapshot = _snapshot(slots=tuple(reversed(snapshot.slots)))
    assert snapshot.topology_snapshot_hash == reversed_snapshot.topology_snapshot_hash


@pytest.mark.parametrize(
    "changed",
    (
        _slot("MS-AUTOCAD-ALT", "autocad", "DOC-AUTOCAD"),
        _slot("MS-AUTOCAD", "revit", "DOC-AUTOCAD"),
        _slot("MS-AUTOCAD", "autocad", "DOC-OTHER"),
        _slot("MS-AUTOCAD", "autocad", "DOC-AUTOCAD", "WALL-002"),
    ),
)
def test_material_slot_semantics_change_snapshot_hash(changed: MaterializationSlot):
    baseline = _snapshot(slots=(_slot("MS-AUTOCAD", "autocad", "DOC-AUTOCAD"),))
    candidate = _snapshot(slots=(changed,))
    assert baseline.topology_snapshot_hash != candidate.topology_snapshot_hash


def test_environment_and_revision_participate_in_hash():
    baseline = _snapshot()
    assert baseline.topology_snapshot_hash != _snapshot(environment="TOPO-ENV-2").topology_snapshot_hash
    assert baseline.topology_snapshot_hash != _snapshot(revision=2).topology_snapshot_hash


def test_integrity_validator_rejects_stale_hash():
    snapshot = _snapshot()
    validate_materialization_topology_snapshot(snapshot)

    with pytest.raises(MaterializationTopologyError) as exc:
        validate_materialization_topology_snapshot(
            replace(snapshot, topology_snapshot_hash="f" * 64)
        )
    assert exc.value.code == "MATERIALIZATION_TOPOLOGY_INTEGRITY_INVALID"
