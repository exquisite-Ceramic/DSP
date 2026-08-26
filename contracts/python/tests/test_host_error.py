"""ErrorShape tests (spec §19.2)."""

import json

from host_contracts.error import ErrorShape


def _roundtrip(obj):
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


def test_round_trips_all_fields():
    error = ErrorShape(
        error_code="REVISION_CONFLICT",
        category="CONSISTENCY",
        message="Document has changed since the planning snapshot",
        correlation_ids=["task-001", "cmd-002"],
        retryable="AFTER_RECONSTRUCT",
        details=[{"expected_revision": 100, "actual_revision": 101}],
    )
    restored = _roundtrip(error)
    assert restored == error
    assert restored.validate() == []


def test_error_code_is_stable_while_message_may_change():
    a = ErrorShape(error_code="REVISION_CONFLICT", message="old wording")
    b = ErrorShape(error_code="REVISION_CONFLICT", message="new wording")
    assert a.error_code == b.error_code == "REVISION_CONFLICT"
    assert a.message != b.message


def test_category_and_retryable_serialize_as_strings():
    error = ErrorShape(
        error_code="X", category="CONSISTENCY", retryable="IMMEDIATE"
    )
    raw = json.dumps(error.to_dict())
    assert '"category": "CONSISTENCY"' in raw
    assert '"retryable": "IMMEDIATE"' in raw


def test_invalid_category_and_retryable_rejected():
    assert ErrorShape(error_code="X", category="NONSENSE").validate() != []
    assert ErrorShape(error_code="X", retryable="MAYBE").validate() != []


def test_missing_error_code_is_invalid():
    assert ErrorShape(error_code="").validate() != []


def test_unknown_field_is_ignored():
    error = ErrorShape.from_dict(
        {"error_code": "X", "message": "m", "native_stack": "not part of contract"}
    )
    assert "native_stack" not in error.to_dict()
