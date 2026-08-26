"""HostEntityRef tests (spec §12.2)."""

from host_contracts.entity_ref import HostEntityRef


def test_round_trips_all_fields():
    ref = HostEntityRef(document_id="drawing-001", native_id="2AF", native_type="LINE")
    restored = HostEntityRef.from_dict(ref.to_dict())
    assert restored == ref


def test_native_type_is_optional():
    ref = HostEntityRef(document_id="drawing-001", native_id="2AF")
    d = ref.to_dict()
    assert "native_type" not in d
    assert HostEntityRef.from_dict(d) == ref


def test_missing_fields_are_invalid():
    assert HostEntityRef(document_id="", native_id="2AF").validate() != []
    assert HostEntityRef(document_id="drawing-001", native_id="").validate() != []
    assert HostEntityRef(document_id="drawing-001", native_id="2AF").validate() == []


def test_unknown_field_is_ignored():
    ref = HostEntityRef.from_dict(
        {"document_id": "drawing-001", "native_id": "2AF", "object_id": "0x1a2b"}
    )
    assert ref.document_id == "drawing-001"
    assert ref.native_id == "2AF"
    assert "object_id" not in ref.to_dict()
