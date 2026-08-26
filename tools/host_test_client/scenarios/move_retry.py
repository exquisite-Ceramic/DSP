"""Scenario: send the same idempotency key twice; expect identical results."""

from __future__ import annotations

import uuid

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(pipe_name: str) -> HostCommandResult:
    host = HostAdapter(pipe_name=pipe_name)
    try:
        dispatcher = CommandDispatcher(host=host)

        selection = await dispatcher.current_selection()
        if not selection.ok:
            return selection
        handles = [r["handle"] for r in selection.payload.get("entityRefs", [])]
        if not handles:
            return HostCommandResult(command_id="scenario.move_retry", ok=False, payload={})

        key = str(uuid.uuid4())
        first = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)
        second = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)

        if not first.ok or not second.ok:
            return HostCommandResult(
                command_id="scenario.move_retry",
                ok=False,
                payload={"first": first.to_dict(), "second": second.to_dict()},
            )

        assert second.replayed, "second call with the same key must be a replay"
        return HostCommandResult(
            command_id="scenario.move_retry",
            ok=True,
            payload={"first": first.to_dict(), "second": second.to_dict()},
        )
    finally:
        await host.close()
