"""Scenario: send the same idempotency key twice; expect a host replay."""

from __future__ import annotations

import uuid

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.error import ErrorShape
from host_contracts.result import HostCommandResult


def _selected_native_ids(selection: HostCommandResult) -> list[str]:
    payload = selection.payload or {}
    return [
        str(ref["native_id"])
        for ref in payload.get("entityRefs", [])
        if ref.get("native_id")
    ]


async def run(host: HostAdapter) -> HostCommandResult:
    dispatcher = CommandDispatcher(host=host)

    selection = await dispatcher.current_selection()
    if not selection.ok:
        return selection

    handles = _selected_native_ids(selection)
    if not handles:
        return HostCommandResult(
            command_id="scenario.move_retry",
            status="ERROR",
            error=ErrorShape(
                error_code="NO_SELECTION",
                category="EXECUTION",
                message="select at least one entity before running move_retry",
                retryable="NEVER",
            ),
        )

    key = str(uuid.uuid4())
    first = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)
    second = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)
    evidence = {"first": first.to_dict(), "second": second.to_dict()}

    if not first.ok or not second.ok:
        return HostCommandResult(
            command_id="scenario.move_retry",
            status="ERROR",
            payload=evidence,
            error=first.error
            or second.error
            or ErrorShape(
                error_code="MOVE_RETRY_FAILED",
                category="EXECUTION",
                message="one of the idempotency probe moves failed",
                retryable="NEVER",
            ),
        )

    if not second.replayed:
        return HostCommandResult(
            command_id="scenario.move_retry",
            status="ERROR",
            payload=evidence,
            error=ErrorShape(
                error_code="IDEMPOTENCY_REPLAY_MISSING",
                category="CONSISTENCY",
                message="second call with the same idempotency key was not reported as a replay",
                retryable="NEVER",
            ),
        )

    return HostCommandResult(
        command_id="scenario.move_retry",
        status="OK",
        payload=evidence,
    )
