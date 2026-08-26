"""HostDelta tests (spec §12.3 / §26.8)."""

import json

from host_contracts.delta import HostDelta
from host_contracts.entity_ref import HostEntityRef


def _roundtrip(obj):
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


def test_round_trips_structure():
    delta = HostDelta(
        revision_before=100,
        revision_after=101,
        modified=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
    )
    restored = _roundtrip(delta)
    assert restored == delta
    assert restored.validate() == []


def test_revision_after_must_be_ge_revision_before():
    assert HostDelta(revision_before=100, revision_after=101).validate() == []
    assert HostDelta(revision_before=100, revision_after=100).validate() == []
    assert HostDelta(revision_before=101, revision_after=100).validate() != []


def test_same_entity_not_in_added_and_erased():
    ref = HostEntityRef(document_id="drawing-001", native_id="2AF")
    conflict = HostDelta(revision_before=100, revision_after=101, added=[ref], erased=[ref])
    assert conflict.validate() != []

    ok = HostDelta(
        revision_before=100,
        revision_after=101,
        added=[HostEntityRef(document_id="drawing-001", native_id="3B1")],
        erased=[ref],
    )
    assert ok.validate() == []


def test_unknown_field_is_ignored():
    delta = HostDelta.from_dict(
        {"revision_before": 100, "revision_after": 101, "future_kind": "x"}
    )
    assert "future_kind" not in delta.to_dict()
