import pytest

from autocad_sidecar.execution.idempotency import IdempotencyStore
from host_contracts.result import HostCommandResult


@pytest.mark.asyncio
async def test_recall_marks_cached_result_as_replayed_without_mutating_original():
    store = IdempotencyStore()
    first = HostCommandResult(
        command_id="cmd-1",
        status="OK",
        payload={"moved": 1},
        revision_after=4,
        replayed=False,
    )

    await store.complete("key-1", first)
    recalled = await store.recall("key-1")

    assert recalled is not first
    assert first.replayed is False
    assert recalled.replayed is True
    assert recalled.command_id == first.command_id
    assert recalled.payload == first.payload
    assert recalled.revision_after == first.revision_after
