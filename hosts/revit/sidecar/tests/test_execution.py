"""Task 6 RED：admitted Revit wall-thickness Slice 必须经真实 Host adapter/result adapter 执行。"""

from __future__ import annotations

from dataclasses import replace

import pytest
import revit_sidecar
from design_execution_coordination import HostCommitted, HostDispatchContext
from design_provider_binding import (
    compute_candidate_fingerprint,
    compute_provider_snapshot_hash_v2,
    resolve_provider_bindings_v2,
)

from tests.execution_coordination.test_phase_i_readiness_barrier import (
    _phase_i_readiness_inputs,
)
from tests.provider_binding._support import snapshot as provider_snapshot


class _Transport:
    """只 fake named-pipe I/O；command construction 与 result normalization 使用 production。"""

    def __init__(self) -> None:
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        expected_revision = command.preconditions[0]["revision"]
        return {
            "command_id": command.command_id,
            "status": "OK",
            "revision_after": expected_revision + 1,
            "payload": {
                "wall_unique_id": command.target_native_refs[0].native_id,
                "wall_type_unique_id": "REVIT-WALLTYPE-001",
                "editable_layer_index": 1,
                "width_before_internal": 0.5,
                "width_after_internal": 0.984251968503937,
                "width_after_mm": 300.0,
                "requested_width_mm": 300.0,
                "transaction_attempt_count": 1,
            },
            "verification": {
                "identity_invariant_proven": True,
                "location_invariant_proven": True,
                "relationship_invariant_proven": True,
                "document_change_observed": True,
                "revision_before": expected_revision,
                "revision_after": expected_revision + 1,
                "location_signature_before": "Line|0|0|0|10|0|0",
                "location_signature_after": "Line|0|0|0|10|0|0",
                "relationship_signature_before": "isolated",
                "relationship_signature_after": "isolated",
            },
            "replayed": False,
        }


def _revit_inputs(
    *,
    expected_revision: int | None = 31,
    provider_tool: str = "revit.set_wall_thickness",
):
    """基于真实 V2 resolver 生成 exact binding，再对 authority 绑定新 binding hash。"""

    ctx = _phase_i_readiness_inputs()
    index = next(
        index
        for index, execution_slice in enumerate(ctx.execution_plan.execution_slices)
        if execution_slice.host_runtime_ref.host_type == "revit"
    )
    execution_slice = ctx.execution_plan.execution_slices[index]
    base = provider_snapshot(
        execution_slice,
        native_id="REVIT-UNIQUE-ID-001",
        native_kind="Wall",
    )
    old_candidate = base.provider_candidates[0]
    candidate_draft = replace(
        old_candidate,
        provider_tool=provider_tool,
        candidate_fingerprint="0" * 64,
    )
    candidate = replace(
        candidate_draft,
        candidate_fingerprint=compute_candidate_fingerprint(candidate_draft),
    )
    old_material = next(iter(base.candidate_binding_materials.values()))
    metadata = dict(old_material.native_binding_metadata)
    if expected_revision is not None:
        metadata["expected_revision"] = expected_revision
    material = replace(old_material, native_binding_metadata=metadata)
    snapshot_draft = replace(
        base,
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        snapshot_hash="0" * 64,
    )
    snapshot = replace(
        snapshot_draft,
        snapshot_hash=compute_provider_snapshot_hash_v2(snapshot_draft),
    )
    binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)
    authority = replace(
        ctx.authorities[index],
        binding_set_hash=binding_set.binding_set_hash,
    )
    return execution_slice, authority, binding_set


def _port(transport):
    port_type = getattr(revit_sidecar, "RevitWallThicknessExecutionPort", None)
    assert port_type is not None, "RevitWallThicknessExecutionPort is not implemented"
    return port_type(transport)


def _dispatch(execution_slice) -> HostDispatchContext:
    return HostDispatchContext(
        dispatch_intent_id="DISPATCH-REVIT-001",
        idempotency_key="IDEMPOTENCY-REVIT-001",
        saga_id="SAGA-REVIT-001",
        execution_slice_hash=execution_slice.execution_slice_hash,
    )


def test_execution_uses_exact_provider_host_contract_revision_and_idempotency() -> None:
    """canonical/provider/Host 三层命名、mm 单位和 durable dispatch identity 必须同时成立。"""

    execution_slice, authority, binding_set = _revit_inputs(expected_revision=31)
    transport = _Transport()

    result = _port(transport).execute(
        execution_slice,
        authority,
        binding_set,
        _dispatch(execution_slice),
    )

    assert isinstance(result, HostCommitted)
    assert len(transport.commands) == 1
    command = transport.commands[0]
    binding = binding_set.bindings[0]
    target = binding.native_targets[0]
    assert execution_slice.execution_units[0].canonical_operation == "set_wall_thickness.v1"
    assert binding.provider_tool == "revit.set_wall_thickness"
    assert command.mode == "EXECUTE"
    assert command.operation == "set_wall_thickness"
    assert command.document_id == execution_slice.host_runtime_ref.document_ref
    assert command.target_native_refs[0].native_id == target.native_id
    assert command.arguments == {"thickness": {"value": 300.0, "unit": "mm"}}
    assert command.preconditions == [{"revision": 31}]
    assert command.idempotency_key == "IDEMPOTENCY-REVIT-001"
    assert result.actual_delta.revision_before == 31
    assert result.actual_delta.revision_after == 32
    assert result.actual_delta.binding_set_hash == binding_set.binding_set_hash
    assert result.actual_delta.execution_slice_hash == execution_slice.execution_slice_hash


@pytest.mark.parametrize(
    ("expected_revision", "provider_tool"),
    (
        (None, "revit.set_wall_thickness"),
        (31, "set_wall_thickness"),
    ),
)
def test_execution_rejects_unfrozen_revision_or_wrong_provider_tool_before_transport(
    expected_revision,
    provider_tool,
) -> None:
    """execution-time fallback revision 或错误 provider namespace 都不得到达 Host。"""

    execution_slice, authority, binding_set = _revit_inputs(
        expected_revision=expected_revision,
        provider_tool=provider_tool,
    )
    transport = _Transport()

    with pytest.raises(ValueError):
        _port(transport).execute(
            execution_slice,
            authority,
            binding_set,
            _dispatch(execution_slice),
        )

    assert transport.commands == []


def test_execution_rejects_dispatch_context_for_other_slice_before_transport() -> None:
    """Host write 必须消费 coordinator 持久化的同一 slice dispatch identity。"""

    execution_slice, authority, binding_set = _revit_inputs(expected_revision=31)
    transport = _Transport()
    dispatch = replace(_dispatch(execution_slice), execution_slice_hash="f" * 64)

    with pytest.raises(ValueError):
        _port(transport).execute(execution_slice, authority, binding_set, dispatch)

    assert transport.commands == []
