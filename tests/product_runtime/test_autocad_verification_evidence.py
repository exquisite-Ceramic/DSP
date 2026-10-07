"""Task 12 RED：AutoCAD 独立 READ 驱动的 semantic verification evidence。"""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module

import pytest
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_execution_reconciliation import VerificationStatus
from design_impact import SemanticEnvironmentBinding

from tests.execution_coordination._support import phase_i_readiness_inputs
from tests.execution_reconciliation._support import service, signed_delta
from tests.product_runtime.test_revit_semantics import _real_semantic_service


def _api():
    sidecar = import_module("autocad_sidecar.execution.wall_thickness_read")
    runtime = import_module("design_product_runtime.autocad_evidence")
    read_type = getattr(sidecar, "AutoCadWallThicknessFactReadPort", None)
    evidence_type = getattr(
        runtime,
        "AutoCadWallThicknessVerificationEvidencePort",
        None,
    )
    assert read_type is not None, "AutoCadWallThicknessFactReadPort 尚未实现"
    assert evidence_type is not None, (
        "AutoCadWallThicknessVerificationEvidencePort 尚未实现"
    )
    return read_type, evidence_type


class _Dispatcher:
    """独立 READ fake；mutation response 不在此对象上存在。"""

    def __init__(
        self,
        *,
        host_instance_id: str,
        document_id: str,
        native_id: str,
        revision: int = 11,
        width_mm: float = 300.0,
    ) -> None:
        self.calls = []
        self.batch = DesignFactAdapter().normalize_snapshot(
            {
                "hostInstanceId": host_instance_id,
                "documentId": document_id,
                "revision": revision,
                "entities": [
                    {
                        "nativeId": native_id,
                        "nativeKind": "LWPOLYLINE",
                        "layer": "A-WALL",
                        "properties": {
                            "constantWidth": {
                                "value": width_mm,
                                "unit": "mm",
                            }
                        },
                    }
                ],
            }
        )

    async def extract_design_facts(self, handles):
        self.calls.append(tuple(handles))
        return self.batch


def _case(*, revision: int = 11, width_mm: float = 300.0):
    read_type, evidence_type = _api()
    semantic_service, semantic_environment = _real_semantic_service()
    ctx = phase_i_readiness_inputs(
        semantic_environment=SemanticEnvironmentBinding(
            semantic_environment.environment_id,
            semantic_environment.content_hash,
        ),
        project_id="project-1",
    )
    index = next(
        i
        for i, item in enumerate(ctx.execution_plan.execution_slices)
        if item.host_runtime_ref.host_type == "autocad"
    )
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    binding_set = ctx.binding_sets[index]
    actual_delta = signed_delta(ctx, index)
    native_target = binding_set.bindings[0].native_targets[0]
    dispatcher = _Dispatcher(
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_id=execution_slice.host_runtime_ref.document_ref,
        native_id=native_target.native_id,
        revision=revision,
        width_mm=width_mm,
    )
    read_port = read_type(dispatcher)
    evidence = evidence_type(
        fact_reader=read_port,
        semantic_service=semantic_service,
        semantic_environment=semantic_environment,
    )
    return (
        ctx,
        index,
        execution_slice,
        authority,
        binding_set,
        actual_delta,
        evidence,
        dispatcher,
    )


def _bundle(case):
    ctx, _, execution_slice, authority, binding_set, actual_delta, evidence, _ = case
    return evidence.build_bundle(
        execution_slice=execution_slice,
        authority=authority,
        binding_set=binding_set,
        actual_delta=actual_delta,
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
    )


def test_autocad_independent_read_requires_exact_committed_revision() -> None:
    """post-commit READ 必须精确命中 ActualDelta.revision_after，不能接受 newer state。"""

    case = _case(revision=12)
    with pytest.raises(ValueError, match="AUTOCAD_WALL_READ_REVISION_MISMATCH"):
        _bundle(case)


def test_autocad_verification_uses_semantic_facts_not_execute_response_width() -> None:
    """verification value 只能来自独立 normalized facts；execute response width 不参与接口。"""

    case = _case(revision=11, width_mm=300.0)
    bundle = _bundle(case)
    ctx, _, execution_slice, authority, _, actual_delta, _, dispatcher = case

    assert dispatcher.calls == [
        (binding_set.bindings[0].native_targets[0].native_id,)
    ]
    assert bundle.base_host_revision == str(actual_delta.revision_after)
    assert bundle.subject_evidence[0].properties["dsp:WallThickness"] == {
        "value": 300.0,
        "unit": "mm",
    }

    stored = service().create_saga(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    tasks = {item.validation_task_id: item for item in ctx.case.changeset.validation_tasks}
    result = service().verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=actual_delta,
        validation_tasks=tuple(tasks[item] for item in assignment.validation_task_ids),
        verification_evidence_bundle=bundle,
        verified_at="2026-10-07T03:10:00Z",
    )
    assert result.status is VerificationStatus.PASSED


def test_autocad_wrong_independent_fact_value_is_semantic_failure_not_success() -> None:
    """exact identity/revision 但宽度错误时证据仍有效，最终应由 verifier 判 FAILED。"""

    case = _case(revision=11, width_mm=275.0)
    bundle = _bundle(case)
    assert bundle.subject_evidence[0].properties["dsp:WallThickness"]["value"] == 275.0
