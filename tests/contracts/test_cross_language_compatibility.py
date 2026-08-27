"""Dynamic Python <-> C# wire compatibility tests.

Unlike the shared golden-vector tests, these cases consume JSON emitted by the
other language at test time.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INTEROP_PROJECT = ROOT / "tests" / "contracts" / "dotnet_interop" / "ContractInterop.csproj"


def _run_csharp(mode: str, *, stdin: str | None = None) -> dict:
    assert INTEROP_PROJECT.exists(), f"missing C# interop helper: {INTEROP_PROJECT}"

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK is required for cross-language contract compatibility tests")

    completed = subprocess.run(
        [
            dotnet,
            "run",
            "--project",
            str(INTEROP_PROJECT),
            "--configuration",
            "Release",
            "--verbosity",
            "quiet",
            "--",
            mode,
        ],
        cwd=ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"C# interop helper failed ({mode})\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, f"C# interop helper produced no JSON ({mode})"
    return json.loads(lines[-1])


@pytest.mark.conformance
def test_python_wire_json_is_consumed_by_csharp():
    from host_contracts.command import HostCommand
    from host_contracts.entity_ref import HostEntityRef
    from host_contracts.envelope import RequestEnvelope

    command = HostCommand(
        command_id="cmd-py-001",
        document_id="drawing-001",
        mode="EXECUTE",
        operation="move.v1",
        target_native_refs=[HostEntityRef(document_id="drawing-001", native_id="2AF")],
        arguments={"displacement": {"x": 500, "y": 0, "z": 0}},
        idempotency_key="interop-py-cs-001",
        deadline_at="2026-08-27T01:00:00Z",
    )
    envelope = RequestEnvelope(
        request_id="req-py-001",
        task_id="task-interop-001",
        project_id="project-001",
        idempotency_key="interop-py-cs-001",
        payload=command.to_dict(),
    )

    summary = _run_csharp("consume-request", stdin=json.dumps(envelope.to_dict()))

    assert summary == {
        "request_id": "req-py-001",
        "task_id": "task-interop-001",
        "command_id": "cmd-py-001",
        "document_id": "drawing-001",
        "mode": "EXECUTE",
        "operation": "move.v1",
        "native_id": "2AF",
        "displacement_x": 500,
        "idempotency_key": "interop-py-cs-001",
    }


@pytest.mark.conformance
def test_csharp_wire_json_is_consumed_by_python():
    from host_contracts.command import HostCommand
    from host_contracts.envelope import RequestEnvelope

    raw = _run_csharp("emit-request")
    envelope = RequestEnvelope.from_dict(raw)
    command = HostCommand.from_dict(envelope.payload)

    assert envelope.request_id == "req-cs-001"
    assert envelope.task_id == "task-interop-002"
    assert envelope.project_id == "project-001"
    assert command.command_id == "cmd-cs-001"
    assert command.document_id == "drawing-001"
    assert command.mode == "EXECUTE"
    assert command.operation == "move.v1"
    assert len(command.target_native_refs) == 1
    assert command.target_native_refs[0].native_id == "2AF"
    assert command.arguments == {"displacement": {"x": 500, "y": 0, "z": 0}}
    assert command.idempotency_key == "interop-cs-py-001"
