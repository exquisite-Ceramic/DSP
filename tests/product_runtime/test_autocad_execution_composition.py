"""Task 12 RED：AutoCAD product execution 与 provider revision authority。"""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module

import pytest
from design_execution_coordination import (
    HostCommitted,
    HostDispatchContext,
    HostFailed,
    HostFailurePhase,
)
from design_provider_binding import (
    compute_provider_snapshot_hash_v2,
    resolve_provider_bindings_v2,
)

from tests.execution_coordination._support import phase_i_readiness_inputs
from tests.provider_binding._support import snapshot


def _api():
    module = import_module("design_product_runtime.autocad_execution")
    execution_type = getattr(module, "AutoCadWallThicknessExecutionPort", None)
    boundary_type = getattr(
        module,
        "AutoCadWallThicknessProviderExecutionSnapshotBoundary",
        None,
    )
    assert execution_type is not None, "AutoCadWallThicknessExecutionPort 尚未实现"
    assert boundary_type is not None, (
        "AutoCadWallThicknessProviderExecutionSnapshotBoundary 尚未实现"
    )
    return execution_type, boundary_type


def _lineage(*, expected_revision: int = 11):
    """构造 exact AutoCAD Slice，并让 expected revision 真正进入 Step31 binding hash。"""

    ctx = phase_i_readiness_inputs()
    index = next(
        i
        for i, item in enumerate(ctx.execution_plan.execution_slices)
        if item.host_runtime_ref.host_type == "autocad"
    )
    execution_slice = ctx.execution_plan.execution_slices[index]
    base = snapshot(
        execution_slice,
        native_id="A31",
        native_kind="LWPOLYLINE",
    )
    materials = {}
    for fingerprint, material in base.candidate_binding_materials.items():
        materials[fingerprint] = replace(
            material,
            native_binding_metadata={
                **dict(material.native_binding_metadata),
                "expected_revision": expected_revision,
            },
        )
    provisional = replace(
        base,
        candidate_binding_materials=materials,
        snapshot_hash="0" * 64,
    )
    provider_snapshot = replace(
        provisional,
        snapshot_hash=compute_provider_snapshot_hash_v2(provisional),
    )
    binding_set = resolve_provider_bindings_v2(execution_slice, provider_snapshot)
    authority = replace(
        ctx.authorities[index],
        binding_set_hash=binding_set.binding_set_hash,
    )
    dispatch = HostDispatchContext(
        dispatch_intent_id="DISPATCH-AUTOCAD-1",
        idempotency_key="IDEMPOTENCY-AUTOCAD-1",
        saga_id="SAGA-AUTOCAD-1",
        execution_slice_hash=execution_slice.execution_slice_hash,
    )
    return ctx, execution_slice, authority, binding_set, dispatch


class _MutationPort:
    """Host wrapper fake；Product Runtime 只能根据公开 HostCommandResult 分类。"""

    def __init__(self, result=None, failure: Exception | None = None) -> None:
        self.result = result
        self.failure = failure
        self.calls = []

    def execute(
        self,
        *,
        native_id,
        thickness_mm,
        idempotency_key,
        expected_revision,
    ):
        self.calls.append(
            (native_id, thickness_mm, idempotency_key, expected_revision)
        )
        if self.failure is not None:
            raise self.failure
        return self.result


def _ok_result(*, extra_target: bool = False):
    from host_contracts import HostCommandResult

    widths = {"A31": 300.0}
    before = {"A31": 200.0}
    if extra_target:
        widths["A32"] = 300.0
        before["A32"] = 200.0
    return HostCommandResult(
        command_id="CMD-AUTOCAD-1",
        status="OK",
        payload={
            "updated": len(widths),
            "beforeWidths": before,
            "widths": widths,
            "unit": "mm",
        },
        revision_after=12,
    )


def test_autocad_commit_builds_actual_delta_only_for_exact_changed_target_effect() -> None:
    """只有 exact native target 的 property 修改能发布 HostCommitted/ActualDelta。"""

    execution_type, _ = _api()
    _, execution_slice, authority, binding_set, dispatch = _lineage()
    mutation = _MutationPort(_ok_result())
    port = execution_type(mutation, clock=lambda: "2026-10-07T03:00:00Z")

    outcome = port.execute(
        execution_slice,
        authority,
        binding_set,
        dispatch,
    )

    assert isinstance(outcome, HostCommitted)
    delta = outcome.actual_delta
    assert delta.revision_before == 11
    assert delta.revision_after == 12
    assert delta.document_ref == execution_slice.host_runtime_ref.document_ref
    assert len(delta.changes) == 1
    assert delta.changes[0].semantic_id == execution_slice.execution_units[0].targets[0]
    assert tuple(item.value for item in delta.changes[0].changed_aspects) == (
        "PROPERTIES",
    )
    assert mutation.calls == [
        ("A31", 300.0, dispatch.idempotency_key, 11)
    ]

    bad = execution_type(
        _MutationPort(_ok_result(extra_target=True)),
        clock=lambda: "2026-10-07T03:00:00Z",
    )
    bad_outcome = bad.execute(execution_slice, authority, binding_set, dispatch)
    assert isinstance(bad_outcome, HostFailed)
    assert bad_outcome.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN
    assert bad_outcome.failure_ref == "AUTOCAD_COMMIT_EVIDENCE_MISMATCH"


def test_autocad_revision_conflict_is_before_commit_and_has_no_actual_delta() -> None:
    """Host 明确 revision conflict 时，结果必须是 BEFORE_COMMIT，不能伪造 ActualDelta。"""

    from host_contracts import ErrorShape, HostCommandResult

    execution_type, _ = _api()
    _, execution_slice, authority, binding_set, dispatch = _lineage()
    result = HostCommandResult(
        command_id="CMD-AUTOCAD-REVISION",
        status="ERROR",
        error=ErrorShape(
            error_code="REVISION_CONFLICT",
            category="CONSISTENCY",
            message="expected revision 11, observed 12",
            retryable="AFTER_RECONSTRUCT",
        ),
    )
    outcome = execution_type(
        _MutationPort(result),
        clock=lambda: "2026-10-07T03:00:00Z",
    ).execute(execution_slice, authority, binding_set, dispatch)

    assert isinstance(outcome, HostFailed)
    assert outcome.phase is HostFailurePhase.BEFORE_COMMIT
    assert outcome.failure_ref == "REVISION_CONFLICT"
    assert not hasattr(outcome, "actual_delta")


def test_autocad_lost_response_is_outcome_unknown_not_safe_retry() -> None:
    """EXECUTE 调用后 response 丢失无法证明未提交，必须进入 outcome-unknown recovery。"""

    execution_type, _ = _api()
    _, execution_slice, authority, binding_set, dispatch = _lineage()
    mutation = _MutationPort(failure=ConnectionError("response lost"))
    outcome = execution_type(
        mutation,
        clock=lambda: "2026-10-07T03:00:00Z",
    ).execute(execution_slice, authority, binding_set, dispatch)

    assert isinstance(outcome, HostFailed)
    assert outcome.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN
    assert outcome.failure_ref == "AUTOCAD_COMMIT_STATE_UNKNOWN"
    assert len(mutation.calls) == 1


def test_provider_snapshot_freezes_exact_planning_revision_into_binding_hash() -> None:
    """AutoCAD provider snapshot boundary 必须把自己的 planning revision 写入 hash-bound metadata。"""

    _, boundary_type = _api()
    _, execution_slice, _, _, _ = _lineage(expected_revision=11)

    class _ChangeSetStore:
        def __init__(self, changeset):
            self.changeset = changeset
        def get(self, changeset_id):
            assert changeset_id == self.changeset.changeset_id
            return self.changeset

    class _Registry:
        def __init__(self, changeset):
            self.changeset = changeset
        def get_snapshot_set(self, snapshot_set_id):
            ref = self.changeset.snapshot_set_ref
            return type("S", (), {
                "snapshot_set_id": ref.snapshot_set_id,
                "hash": ref.snapshot_set_hash,
                "member_snapshot_ids": tuple(ref.member_snapshot_ids),
                "semantic_environment_ref": ref.semantic_environment,
            })()
        def get_snapshot(self, snapshot_id):
            member_ids = tuple(self.changeset.snapshot_set_ref.member_snapshot_ids)
            document_ref = (
                execution_slice.host_runtime_ref.document_ref
                if snapshot_id == member_ids[0]
                else "DOC-NON-AUTOCAD"
            )
            return type("P", (), {
                "snapshot_id": snapshot_id,
                "hash": f"HASH-{snapshot_id}",
                "kind": import_module("semantic_runtime").SnapshotKind.PLANNING,
                "document_ref": document_ref,
                "base_host_revision": "11",
                "semantic_environment_ref": self.changeset.semantic_environment_ref,
            })()

    ctx = phase_i_readiness_inputs()
    boundary = boundary_type(
        changeset_store=_ChangeSetStore(ctx.case.changeset),
        snapshot_registry=_Registry(ctx.case.changeset),
        provider_snapshot_factory=lambda item: snapshot(
            item,
            native_id="A31",
            native_kind="LWPOLYLINE",
        ),
    )
    bound = boundary(execution_slice)
    material = next(iter(bound.candidate_binding_materials.values()))
    assert material.native_binding_metadata["expected_revision"] == 11
