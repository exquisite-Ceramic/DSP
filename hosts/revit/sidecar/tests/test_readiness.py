from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_coordination import (
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
from revit_sidecar.readiness import RevitWallThicknessReadinessPort

from tests.execution_coordination.test_phase_i_readiness_barrier import (
    _phase_i_readiness_inputs,
)


class FakeTransport:
    def __init__(self, *, payload_changes=None, error_code: str | None = None) -> None:
        self.payload_changes = dict(payload_changes or {})
        self.error_code = error_code
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        if self.error_code is not None:
            return {
                "command_id": command.command_id,
                "status": "ERROR",
                "error": {"code": self.error_code},
                "revision_after": 31,
                "replayed": False,
            }
        payload = {
            "document_id": command.document_id,
            "wall_unique_id": command.target_native_refs[0].native_id,
            "wall_type_unique_id": "REVIT-WALLTYPE-001",
            "current_width": {"value": 200.0, "unit": "mm"},
            "requested_width": {"value": 300.0, "unit": "mm"},
            "isolation_ready": True,
            "plan_ready": True,
        }
        payload.update(self.payload_changes)
        return {
            "command_id": command.command_id,
            "status": "OK",
            "payload": payload,
            "revision_after": 31,
            "replayed": False,
        }


def _revit_inputs():
    ctx = _phase_i_readiness_inputs()
    index = next(
        index
        for index, execution_slice in enumerate(ctx.execution_plan.execution_slices)
        if execution_slice.host_runtime_ref.host_type == "revit"
    )
    return (
        ctx.execution_plan.execution_slices[index],
        ctx.binding_sets[index],
        ctx.authorities[index],
    )


def test_revit_readiness_builds_one_exact_read_command_and_returns_ready_receipt() -> None:
    execution_slice, binding_set, authority = _revit_inputs()
    transport = FakeTransport()
    receipt = RevitWallThicknessReadinessPort(transport).check(
        execution_slice,
        authority,
        binding_set,
    )

    assert len(transport.commands) == 1
    command = transport.commands[0]
    target = binding_set.bindings[0].native_targets[0]
    assert command.mode == "READ"
    assert command.operation == "check_wall_thickness_readiness"
    assert command.document_id == execution_slice.host_runtime_ref.document_ref
    assert command.idempotency_key is None
    assert command.preconditions == []
    assert len(command.target_native_refs) == 1
    assert command.target_native_refs[0].native_id == target.native_id
    assert command.target_native_refs[0].native_type == "Wall"
    assert command.arguments == {"thickness": {"value": 300.0, "unit": "mm"}}

    assert receipt.status is ReadinessStatus.READY
    assert receipt.failure_code is None
    assert receipt.observed_revision == 31
    assert receipt.materialization_id == execution_slice.materialization_id
    assert receipt.materialization_plan_hash == execution_slice.materialization_plan_hash
    assert receipt.execution_slice_hash == execution_slice.execution_slice_hash
    assert receipt.binding_set_hash == binding_set.binding_set_hash
    assert receipt.grant_hash == authority.grant_hash
    assert receipt.host_runtime_ref == execution_slice.host_runtime_ref
    assert receipt.receipt_hash == compute_readiness_receipt_hash(receipt)


@pytest.mark.parametrize(
    ("payload_changes", "expected_code"),
    (
        ({"document_id": "DOC-OTHER"}, "REVIT_READINESS_DOCUMENT_MISMATCH"),
        ({"wall_unique_id": "REVIT-OTHER"}, "REVIT_READINESS_TARGET_MISMATCH"),
        (
            {"current_width": {"value": 200.0, "unit": "cm"}},
            "REVIT_READINESS_WIDTH_UNIT_MISMATCH",
        ),
        (
            {"current_width": {"value": 0.0, "unit": "mm"}},
            "REVIT_READINESS_WIDTH_INVALID",
        ),
        ({"isolation_ready": False}, "REVIT_READINESS_ISOLATION_UNPROVEN"),
        ({"plan_ready": False}, "REVIT_READINESS_PLAN_UNPROVEN"),
    ),
)
def test_revit_readiness_rejects_mismatched_native_evidence(
    payload_changes,
    expected_code,
) -> None:
    execution_slice, binding_set, authority = _revit_inputs()
    receipt = RevitWallThicknessReadinessPort(
        FakeTransport(payload_changes=payload_changes)
    ).check(execution_slice, authority, binding_set)
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == expected_code
    assert receipt.observed_revision == 31


def test_native_readiness_error_becomes_not_ready_with_real_revision() -> None:
    execution_slice, binding_set, authority = _revit_inputs()
    receipt = RevitWallThicknessReadinessPort(
        FakeTransport(error_code="WALL_ASSOCIATIVITY_UNPROVEN")
    ).check(execution_slice, authority, binding_set)
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == "WALL_ASSOCIATIVITY_UNPROVEN"
    assert receipt.observed_revision == 31


def test_missing_revision_fails_without_fabricating_readiness_receipt() -> None:
    execution_slice, binding_set, authority = _revit_inputs()

    class MissingRevisionTransport(FakeTransport):
        def request(self, command):
            response = super().request(command)
            response.pop("revision_after")
            return response

    with pytest.raises(ReadinessError) as exc:
        RevitWallThicknessReadinessPort(MissingRevisionTransport()).check(
            execution_slice,
            authority,
            binding_set,
        )
    assert exc.value.code == "READINESS_FAILED"


def test_authority_substitution_fails_before_named_pipe_request() -> None:
    execution_slice, binding_set, authority = _revit_inputs()
    transport = FakeTransport()
    substituted = replace(authority, host_instance_id="REVIT-OTHER")
    with pytest.raises(ReadinessError) as exc:
        RevitWallThicknessReadinessPort(transport).check(
            execution_slice,
            substituted,
            binding_set,
        )
    assert exc.value.code == "READINESS_LINEAGE_MISMATCH"
    assert transport.commands == []
