"""Task 5 Step 5：ProductTask INTENT 与 exact ContextSnapshot binding lineage contract。"""

from __future__ import annotations

import pytest
from design_orchestrator.default_workflow_services import ParameterBindingInputs
from design_orchestrator.parameter_binder import OperationProposal, ParameterBindingContext
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime import ProductTaskRequest, RevitWallThicknessSemanticBoundary
from semantic_runtime import (
    AspectGuarantee,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    build_context_contract,
)


class _RequestStore:
    """按 exact task id 返回 immutable request，并记录所有 lookup。"""

    def __init__(self, *requests: ProductTaskRequest) -> None:
        self._requests = {request.task_id: request for request in requests}
        self.lookups: list[str] = []

    def get(self, task_id: str) -> ProductTaskRequest | None:
        self.lookups.append(task_id)
        return self._requests.get(task_id)


class _NoHostReread:
    """Parameter binding 已有 ContextSnapshot authority 后不得重新读取当前 Host context。"""

    def read(self, **kwargs):
        del kwargs
        raise AssertionError("parameter binding must not re-read current Revit context")


def _request(task_id: str, thickness_mm: float) -> ProductTaskRequest:
    """构造本 vertical 的 exact immutable user INTENT。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id="project-1",
        host_kind="REVIT",
        session_ref="revit-session-1",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={
            "thickness": {
                "value": thickness_mm,
                "unit": "mm",
            }
        },
    )


def _context_snapshot() -> SemanticSnapshot:
    """构造只携带 authoritative semantic target/lineage 的 ContextSnapshot。"""

    contract = build_context_contract(
        "DOC-1",
        ("semantic-wall-1",),
        project_id="project-1",
    )
    return SemanticSnapshot.create(
        contract,
        ReconstructionResult(
            document_ref="DOC-1",
            host_revision="41",
            coverage=contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.IDENTITY),),
            projection_ref=SemanticProjectionRef(
                "projection-binding-step5",
                "a" * 64,
                "dsp.semantic.projection-facts.v1",
                "b" * 64,
                "c" * 64,
            ),
            semantic_environment_ref=SemanticEnvironmentRef(
                "semantic-env-binding-step5",
                "d" * 64,
            ),
        ),
    )


def _boundary():
    """同一 fresh boundary 同时可按 task id 读取 A/B，两者共享相同 snapshot authority。"""

    request_store = _RequestStore(
        _request("task-A", 300.0),
        _request("task-B", 350.0),
    )
    snapshot = _context_snapshot()
    snapshots = InMemorySnapshotRegistry()
    snapshots.put_snapshot(snapshot)
    boundary = RevitWallThicknessSemanticBoundary(
        request_store=request_store,
        context_reader=_NoHostReread(),
        identity_registry=__import__("semantic_runtime").IdentityRegistry(),
        session_ref="revit-session-1",
        document_id="DOC-1",
        host_instance_id="revit-runtime-1",
        snapshot_registry=snapshots,
    )
    return boundary, request_store, snapshot


def _load_binding_inputs(
    boundary: RevitWallThicknessSemanticBoundary,
    task_id: str,
    snapshot: SemanticSnapshot,
) -> ParameterBindingInputs:
    """把 Step 5 缺失收敛为单一 focused RED，而不是 attribute collection error。"""

    method = getattr(boundary, "load_parameter_binding_inputs", None)
    assert method is not None, "load_parameter_binding_inputs is not implemented"
    result = method(
        task_id,
        StableRef("operation-space-step5", "e" * 64),
        StableRef(snapshot.snapshot_id, snapshot.hash),
    )
    assert isinstance(result, ParameterBindingInputs)
    return result


def test_binding_inputs_split_user_intent_from_snapshot_context() -> None:
    """thickness 只来自 ProductTask；target/lineage 只来自 exact ContextSnapshot。"""

    boundary, request_store, snapshot = _boundary()

    inputs = _load_binding_inputs(boundary, "task-A", snapshot)

    assert isinstance(inputs.proposal, OperationProposal)
    assert inputs.proposal.canonical_operation == "set_wall_thickness.v1"
    assert inputs.proposal.intent_arguments == {
        "thickness": {"value": 300.0, "unit": "mm"}
    }
    assert "targets" not in inputs.proposal.intent_arguments
    assert isinstance(inputs.context, ParameterBindingContext)
    assert inputs.context.context_snapshot_id == snapshot.snapshot_id
    assert inputs.context.context_snapshot_hash == snapshot.hash
    assert inputs.context.document_ref == "DOC-1"
    assert inputs.context.semantic_environment_ref == "semantic-env-binding-step5"
    assert inputs.context.selection == ("semantic-wall-1",)
    assert request_store.lookups == ["task-A"]


def test_binding_inputs_keep_300_and_350_task_intents_isolated() -> None:
    """同一 snapshot 下交错读取 task-B/A 仍必须返回各自 immutable INTENT。"""

    boundary, request_store, snapshot = _boundary()

    task_b = _load_binding_inputs(boundary, "task-B", snapshot)
    task_a = _load_binding_inputs(boundary, "task-A", snapshot)

    assert task_b.proposal.intent_arguments["thickness"]["value"] == 350.0
    assert task_a.proposal.intent_arguments["thickness"]["value"] == 300.0
    assert task_b.context.selection == task_a.context.selection == ("semantic-wall-1",)
    assert request_store.lookups == ["task-B", "task-A"]


def test_binding_inputs_reject_context_snapshot_hash_mismatch() -> None:
    """binding target 必须来自 exact owner snapshot；相同 id 的错误 hash 不得被接受。"""

    boundary, _, snapshot = _boundary()
    method = getattr(boundary, "load_parameter_binding_inputs", None)
    assert method is not None, "load_parameter_binding_inputs is not implemented"

    with pytest.raises((KeyError, ValueError), match="hash|snapshot|lineage"):
        method(
            "task-A",
            StableRef("operation-space-step5", "e" * 64),
            StableRef(snapshot.snapshot_id, "f" * 64),
        )
