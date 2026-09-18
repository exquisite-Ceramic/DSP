from __future__ import annotations

import json

from design_execution_reconciliation import InMemoryExecutionSagaStoreV2
from design_execution_reconciliation.saga_persistence_v2 import (
    decode_stored_saga_v2,
    encode_stored_saga_v2,
)

from tests.execution_reconciliation.test_saga_v2_store import _v2_definition


def test_stored_saga_v2_round_trips_through_versioned_json_payload() -> None:
    ctx, definition = _v2_definition()
    store = InMemoryExecutionSagaStoreV2()
    stored = store.create_saga(definition)
    execution_slice = ctx.execution_plan.execution_slices[0]

    stored = store.reserve_slice_admission(
        definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-09-17T00:00:00Z",
    )
    stored = store.confirm_slice_admitted(
        definition.saga_id,
        ctx.authorities[0],
        expected_revision=stored.saga_revision,
    )

    payload = encode_stored_saga_v2(stored)
    wire_payload = json.loads(json.dumps(payload, sort_keys=True))

    assert payload["schema_version"] == 1
    assert "__dict__" not in payload
    assert "pickle" not in repr(payload).lower()
    assert decode_stored_saga_v2(wire_payload) == stored
