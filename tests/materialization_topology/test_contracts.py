from dataclasses import fields

import pytest
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologySnapshot,
)


def _slot(
    *,
    slot_id: str = "MS-AUTOCAD-WALL-001",
    semantic_target_ref: str = "WALL-001",
    required_host_type: str = "autocad",
    document_ref: str = "DOC-AUTOCAD",
) -> MaterializationSlot:
    return MaterializationSlot(
        materialization_slot_id=slot_id,
        semantic_target_ref=semantic_target_ref,
        required_host_type=required_host_type,
        document_ref=document_ref,
        requirement=MaterializationRequirement.REQUIRED,
    )


def test_requirement_is_closed_to_required_only():
    assert tuple(item.value for item in MaterializationRequirement) == ("REQUIRED",)
    with pytest.raises(ValueError):
        MaterializationRequirement("OPTIONAL")


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("materialization_slot_id", " "),
        ("semantic_target_ref", ""),
        ("required_host_type", " "),
        ("document_ref", ""),
    ),
)
def test_slot_rejects_blank_identity_fields(field_name: str, bad_value: str):
    kwargs = {
        "materialization_slot_id": "MS-AUTOCAD-WALL-001",
        "semantic_target_ref": "WALL-001",
        "required_host_type": "autocad",
        "document_ref": "DOC-AUTOCAD",
        "requirement": MaterializationRequirement.REQUIRED,
    }
    kwargs[field_name] = bad_value
    with pytest.raises(ValueError):
        MaterializationSlot(**kwargs)


def test_slot_requires_lowercase_host_type_token():
    with pytest.raises(ValueError):
        _slot(required_host_type="AutoCAD")


@pytest.mark.parametrize("revision", (-1, True, 1.5))
def test_snapshot_rejects_invalid_revision(revision):
    with pytest.raises(ValueError):
        MaterializationTopologySnapshot(
            topology_environment_id="TOPO-ENV-1",
            topology_revision=revision,
            slots=(_slot(),),
            topology_snapshot_hash="0" * 64,
        )


def test_snapshot_rejects_duplicate_semantic_host_document_slot():
    first = _slot(slot_id="MS-A")
    duplicate = _slot(slot_id="MS-B")
    with pytest.raises(ValueError):
        MaterializationTopologySnapshot(
            topology_environment_id="TOPO-ENV-1",
            topology_revision=1,
            slots=(first, duplicate),
            topology_snapshot_hash="0" * 64,
        )


def test_snapshot_contract_excludes_runtime_host_identity_and_availability():
    names = {field.name for field in fields(MaterializationTopologySnapshot)}
    assert names == {
        "topology_environment_id",
        "topology_revision",
        "slots",
        "topology_snapshot_hash",
    }
    assert "host_instance_id" not in names
    assert "availability" not in names
