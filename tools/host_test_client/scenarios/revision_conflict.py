"""Scenario: write with a stale revision must fail with revision_conflict."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(host: HostAdapter) -> HostCommandResult:
    dispatcher = CommandDispatcher(host=host)

    selection = await dispatcher.current_selection()
    if not selection.ok:
        return selection
    handles = [r["handle"] for r in selection.payload.get("entityRefs", [])]
    if not handles:
        return HostCommandResult(command_id="scenario.revision_conflict", ok=False, payload={})

    stale_revision = (selection.payload.get("revision") or 0) - 1  # intentionally stale
    result = await dispatcher.move(handles, 1.0, 0.0, revision=stale_revision)

    expected_conflict = not result.ok and result.error is not None and result.error.code == "revision_conflict"
    return HostCommandResult(
        command_id="scenario.revision_conflict",
        ok=expected_conflict,
        payload={"actual": result.to_dict(), "expectedCode": "revision_conflict"},
    )
