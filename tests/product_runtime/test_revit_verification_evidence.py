"""Task 7：Revit 独立 post-commit READ 必须生成 Step33 的真实语义证据。"""

from __future__ import annotations

import pytest
from design_execution_coordination import VerificationEvidenceUnavailable
from design_execution_reconciliation import VerificationStatus
from design_impact import SemanticEnvironmentBinding
from design_product_runtime import RevitWallThicknessVerificationEvidencePort
from revit_sidecar import RevitWallThicknessSnapshotReadPort
from revit_sidecar.design_fact_adapter import DesignFactAdapter

from tests.execution_coordination._support import phase_i_readiness_inputs
from tests.execution_reconciliation._support import service, signed_delta
from tests.product_runtime.test_revit_semantics import _real_semantic_service


class _SnapshotTransport:
    (
        "只 fake Revit 外部 transport；snapshot adapter、事实归一化与 "
        "SemanticService 均使用 production。"
    )

    def __init__(
        self,
        *,
        thickness_mm: float = 300.0,
        document_id: str | None = None,
        host_instance_id: str | None = None,
        wall_unique_id: str | None = None,
        revision_offset: int = 0,
        fail_transport: bool = False,
    ) -> None:
        self.thickness_mm = thickness_mm
        self.document_id = document_id
        self.host_instance_id = host_instance_id
        self.wall_unique_id = wall_unique_id
        self.revision_offset = revision_offset
        self.fail_transport = fail_transport
        self.commands = []

    def request(self, command):
        """按收到的 exact READ command 返回可控 Host evidence。"""
        self.commands.append(command)
        if self.fail_transport:
            raise ConnectionError("fixture transport unavailable")
        requested_target = command.target_native_refs[0]
        expected_revision = 11 + self.revision_offset
        return {
            "status": "OK",
            "revision_after": expected_revision,
            "payload": {
                "document_id": self.document_id or command.document_id,
                "host_instance_id": self.host_instance_id or "REVIT-01",
                "wall_unique_id": self.wall_unique_id or requested_target.native_id,
                "wall_type_unique_id": "REVIT-WALL-TYPE-001",
                "native_kind": "Wall",
                "builtin_category": "OST_Walls",
                "wall_thickness_mm": self.thickness_mm,
                "location_signature": "LOC-POST-COMMIT-001",
                "relationship_signature": "REL-POST-COMMIT-001",
                "revision_before": expected_revision,
                "revision_after": expected_revision,
            },
        }


def _case(*, transport: _SnapshotTransport | None = None):
    """从真实 Phase I owners 选出 Revit Slice，并组合 production semantic collaborators。"""
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
        if item.host_runtime_ref.host_type == "revit"
    )
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    binding_set = ctx.binding_sets[index]
    actual_delta = signed_delta(ctx, index)
    transport = transport or _SnapshotTransport(
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id
    )
    evidence_port = RevitWallThicknessVerificationEvidencePort(
        snapshot_reader=RevitWallThicknessSnapshotReadPort(transport),
        design_fact_adapter=DesignFactAdapter(),
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
        evidence_port,
        transport,
    )


def _build_bundle(case_tuple):
    """通过新的 V2 evidence seam 调用 product evidence port。"""
    ctx, _, execution_slice, authority, binding_set, actual_delta, evidence_port, _ = case_tuple
    return evidence_port.build_bundle(
        execution_slice=execution_slice,
        authority=authority,
        binding_set=binding_set,
        actual_delta=actual_delta,
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
    )


def _assigned_tasks(ctx, execution_slice):
    """读取 Saga builder 冻结的 validation-task assignment，避免测试自造 Step33 规则。"""
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
    return tuple(tasks[task_id] for task_id in assignment.validation_task_ids)


def _verify(case_tuple, bundle):
    """把 product bundle 交给真实 SemanticVerifier 路径，而不是在 product 层自判 PASS。"""
    ctx, _, execution_slice, authority, _, actual_delta, _, _ = case_tuple
    return service().verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=actual_delta,
        validation_tasks=_assigned_tasks(ctx, execution_slice),
        verification_evidence_bundle=bundle,
        verified_at="2026-09-25T16:00:00Z",
    )


def test_independent_read_builds_exact_revision_step33_bundle() -> None:
    (
        "独立 READ 必须使用 admitted native target 与 committed revision，"
        "并生成可 PASS 的 Step33 bundle。"
    )
    case_tuple = _case()
    bundle = _build_bundle(case_tuple)
    ctx, _, execution_slice, _, _, actual_delta, _, transport = case_tuple

    assert len(transport.commands) == 1
    command = transport.commands[0]
    assert command.mode == "READ"
    assert command.operation == "read_wall_thickness_snapshot"
    assert command.document_id == execution_slice.host_runtime_ref.document_ref
    assert command.target_native_refs[0].native_id == "REVIT-UNIQUE-ID-001"
    assert bundle.changeset_hash == ctx.case.changeset.changeset_hash
    assert bundle.execution_slice_hash == execution_slice.execution_slice_hash
    assert bundle.actual_delta_hash == actual_delta.actual_delta_hash
    assert bundle.base_host_revision == str(actual_delta.revision_after)
    assert bundle.post_execution_snapshot_ref.base_host_revision == str(actual_delta.revision_after)
    assert bundle.subject_evidence[0].properties["dsp:WallThickness"] == {
        "value": 300.0,
        "unit": "mm",
    }
    assert _verify(case_tuple, bundle).status is VerificationStatus.PASSED


def test_exact_revision_wrong_value_uses_semantic_failure_not_recovery() -> None:
    """READ identity/revision 正确但值错误时，证据仍有效，最终由真实 SemanticVerifier 判失败。"""
    base = phase_i_readiness_inputs()
    revit_slice = next(
        item
        for item in base.execution_plan.execution_slices
        if item.host_runtime_ref.host_type == "revit"
    )
    case_tuple = _case(
        transport=_SnapshotTransport(
            thickness_mm=275.0,
            host_instance_id=revit_slice.host_runtime_ref.host_instance_id,
        )
    )
    bundle = _build_bundle(case_tuple)

    assert bundle.subject_evidence[0].properties["dsp:WallThickness"]["value"] == 275.0
    assert _verify(case_tuple, bundle).status is VerificationStatus.FAILED


@pytest.mark.parametrize(
    ("transport", "error_code"),
    (
        (
            _SnapshotTransport(document_id="DOC-WRONG", host_instance_id="REVIT-01"),
            "REVIT_SNAPSHOT_DOCUMENT_MISMATCH",
        ),
        (_SnapshotTransport(host_instance_id="REVIT-WRONG"), "REVIT_SNAPSHOT_HOST_MISMATCH"),
        (
            _SnapshotTransport(host_instance_id="REVIT-01", wall_unique_id="WALL-WRONG"),
            "REVIT_SNAPSHOT_TARGET_MISMATCH",
        ),
        (
            _SnapshotTransport(host_instance_id="REVIT-01", revision_offset=1),
            "REVIT_SNAPSHOT_REVISION_MISMATCH",
        ),
    ),
)
def test_correlated_identity_or_revision_mismatch_fails_closed(transport, error_code: str) -> None:
    """错误 identity 或更新后的 revision 都不是“暂不可得”，必须直接 fail closed。"""
    case_tuple = _case(transport=transport)

    with pytest.raises(ValueError, match=error_code):
        _build_bundle(case_tuple)


def test_transport_unavailable_is_explicit_recovery_signal() -> None:
    """只有真正无法取得独立 READ 时，才转换成 known-commit recovery signal。"""
    case_tuple = _case(transport=_SnapshotTransport(fail_transport=True))

    with pytest.raises(VerificationEvidenceUnavailable) as exc_info:
        _build_bundle(case_tuple)

    assert exc_info.value.code == "REVIT_VERIFICATION_EVIDENCE_UNAVAILABLE"
