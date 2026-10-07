"""Task 15：Cross-Host Product Vertical real-owner E2E acceptance。"""

from __future__ import annotations

from design_product_runtime.revit_semantics import RevitWallThicknessSemanticBoundary
from semantic_runtime import HostBinding, IdentityRegistry

from tests.product_runtime.test_product_task_query_v2 import _accepted


class _V2AcceptedReader:
    """只暴露 server-owned V2 accepted input；禁止测试回退到 V1 request。"""

    def __init__(self) -> None:
        self.accepted = _accepted()

    def get_v2(self, task_id: str):
        """按 exact task 返回 V2 accepted input。"""

        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get(self, task_id: str):
        """V2 semantic path 若尝试 V1 request reader，立即暴露 authority 回退。"""

        raise AssertionError(f"V2 semantic path must not use V1 request reader: {task_id}")


class _ContextReader:
    """外部 Host transport double；只返回当前 Revit selection evidence。"""

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
                    unique_id="revit-wall-1",
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
    identities.register(
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
        context_reader=_ContextReader(),
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
