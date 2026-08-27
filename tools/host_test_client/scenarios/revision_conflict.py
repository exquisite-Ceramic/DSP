"""Scenario: write with a stale revision must fail with REVISION_CONFLICT."""

from __future__ import annotations

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
            command_id="scenario.revision_conflict",
            status="ERROR",
            error=ErrorShape(
                error_code="NO_SELECTION",
                category="EXECUTION",
                message="select at least one entity before running revision_conflict",
                retryable="NEVER",
            ),
        )

    payload = selection.payload or {}
    stale_revision = int(payload.get("revision") or 0) - 1
    result = await dispatcher.move(handles, 1.0, 0.0, revision=stale_revision)

    expected_code = "REVISION_CONFLICT"
    expected_conflict = (
        not result.ok
        and result.error is not None
        and result.error.error_code == expected_code
    )
    evidence = {"actual": result.to_dict(), "expectedCode": expected_code}

    if expected_conflict:
        return HostCommandResult(
            command_id="scenario.revision_conflict",
            status="OK",
            payload=evidence,
        )

    return HostCommandResult(
        command_id="scenario.revision_conflict",
        status="ERROR",
        payload=evidence,
        error=ErrorShape(
            error_code="EXPECTED_REVISION_CONFLICT_NOT_OBSERVED",
            category="CONSISTENCY",
            message="stale revision did not produce REVISION_CONFLICT",
            retryable="NEVER",
        ),
    )
