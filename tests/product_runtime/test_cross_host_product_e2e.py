"""Task 15：Cross-Host Product Vertical real-owner E2E acceptance。"""

from __future__ import annotations

from design_product_runtime.revit_semantics import RevitWallThicknessSemanticBoundary
from semantic_runtime import HostBinding, IdentityRegistry

from tests.execution_coordination._materialized_support import materialized_fixture
from tests.product_runtime.test_product_task_query_v2 import _accepted


class _V2AcceptedReader:
    """只暴露 server-owned V2 accepted input；禁止测试回退到 V1 request。"""

    def __init__(self) -> None:
        self.accepted = _accepted(materialized_fixture().ctx)

    def get_v2(self, task_id: str):
        """按 exact task 返回 V2 accepted input。"""

        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get(self, task_id: str):
        """V2 semantic path 若尝试 V1 request reader，立即暴露 authority 回退。"""

        raise AssertionError(f"V2 semantic path must not use V1 request reader: {task_id}")


class _ContextReader:
    """外部 Host transport double；只返回当前 Revit selection evidence。"""

    def __init__(self, native_target_id: str) -> None:
        """冻结本测试从 accepted binding 取得的 exact Revit native target。"""

        self._native_target_id = native_target_id

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ):
        """返回 production semantic boundary 所需的 Revit context observation。"""

        from revit_sidecar import RevitContextObservation, RevitSelectedElement

        assert command_id
        return RevitContextObservation(
            document_id=document_id,
            document_title="Cross-Host Task 15",
            host_instance_id=host_instance_id,
            revision=41,
            selected_elements=(
                RevitSelectedElement(
                    unique_id=self._native_target_id,
                    native_kind="Wall",
                ),
            ),
        )


def test_v2_accepted_input_enters_real_revit_semantic_boundary_without_v1_rewrite() -> None:
    """V2 request hash/session/project 必须原样参与 Revit context identity。"""

    accepted_reader = _V2AcceptedReader()
    request = accepted_reader.accepted.request
    binding = accepted_reader.accepted.session_binding_payload
    revit = next(
        item for item in binding["members"] if item["host_kind"] == "REVIT"
    )
    identities = IdentityRegistry()
    identities.ensure_identity(binding["semantic_target_id"])
    identities.bind_host(
        HostBinding(
            semantic_id=binding["semantic_target_id"],
            host_type="revit",
            document_id=revit["document_id"],
            native_id=revit["native_target_id"],
            native_kind="Wall",
        )
    )
    boundary = RevitWallThicknessSemanticBoundary(
        request_store=accepted_reader,
        context_reader=_ContextReader(revit["native_target_id"]),
        identity_registry=identities,
        session_ref=request.session_ref,
        document_id=revit["document_id"],
        host_instance_id=revit["host_instance_id"],
    )

    context_ref = boundary.resolve_host_context(request.task_id)
    inputs = boundary.load_context_inputs(context_ref)

    assert inputs.task_id == request.task_id
    assert inputs.project_id == request.project_id
    assert inputs.document_ref == revit["document_id"]
    assert context_ref.content_hash is not None



class _EvidencePort:
    """只记录 evidence router 委托；不执行 Host I/O。"""

    def __init__(self, label: str) -> None:
        self.label = label
        self.bundle_calls = []
        self.evidence_calls = []

    def build_bundle(self, **kwargs):
        """返回可辨认 sentinel，证明 exact runtime 路由。"""

        self.bundle_calls.append(kwargs)
        return ("bundle", self.label)

    def build_evidence(self, **kwargs):
        """返回可辨认 sentinel，证明 convergence evidence 也走同一 exact route。"""

        self.evidence_calls.append(kwargs)
        return ("evidence", self.label)


def test_cross_host_evidence_router_delegates_by_exact_runtime_without_host_io() -> None:
    """coordinator 的单 evidence seam 必须安全路由到两个 production adapter。"""

    from design_execution_planning import HostRuntimeRef
    from design_product_runtime.cross_host_reference_composition import (
        CrossHostVerificationEvidenceRouter,
    )

    autocad_runtime = HostRuntimeRef("autocad", "AUTOCAD-E2E", "DOC-A")
    revit_runtime = HostRuntimeRef("revit", "REVIT-E2E", "DOC-R")
    autocad = _EvidencePort("autocad")
    revit = _EvidencePort("revit")
    router = CrossHostVerificationEvidenceRouter(
        (
            (autocad_runtime, autocad),
            (revit_runtime, revit),
        )
    )

    class _Slice:
        def __init__(self, runtime_ref) -> None:
            self.host_runtime_ref = runtime_ref

    auto_slice = _Slice(autocad_runtime)
    revit_slice = _Slice(revit_runtime)

    assert router.build_bundle(execution_slice=auto_slice, marker="a") == (
        "bundle",
        "autocad",
    )
    assert router.build_bundle(execution_slice=revit_slice, marker="r") == (
        "bundle",
        "revit",
    )
    assert router.build_evidence(execution_slice=auto_slice, marker="a") == (
        "evidence",
        "autocad",
    )
    assert router.build_evidence(execution_slice=revit_slice, marker="r") == (
        "evidence",
        "revit",
    )
    assert len(autocad.bundle_calls) == 1
    assert len(revit.bundle_calls) == 1
    assert len(autocad.evidence_calls) == 1
    assert len(revit.evidence_calls) == 1


def test_cross_host_evidence_router_rejects_unconfigured_exact_runtime() -> None:
    """同 host type 但 instance/document 不同也不得 fuzzy resolve。"""

    import pytest
    from design_execution_planning import HostRuntimeRef
    from design_product_runtime.cross_host_reference_composition import (
        CrossHostVerificationEvidenceRouter,
    )

    configured = HostRuntimeRef("revit", "REVIT-E2E", "DOC-R")
    router = CrossHostVerificationEvidenceRouter(
        ((configured, _EvidencePort("revit")),)
    )

    class _Slice:
        host_runtime_ref = HostRuntimeRef("revit", "REVIT-E2E", "OTHER-DOC")

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        router.build_bundle(execution_slice=_Slice())
