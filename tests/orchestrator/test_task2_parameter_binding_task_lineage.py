"""Real Product Vertical Task 2：ParameterBinder input assembly 的 task lineage RED。"""

from __future__ import annotations

import inspect

from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.parameter_binder import (
    OperationProposal,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import StableRef
from design_orchestrator.workflow_services import WorkflowServices


def _parameter_names(callable_object: object) -> tuple[str, ...]:
    """返回可调用对象公开签名的参数名，冻结本次窄 seam amendment。"""

    return tuple(inspect.signature(callable_object).parameters)


def test_parameter_binding_public_seams_require_explicit_task_id() -> None:
    """Protocol、默认 service 与 canonical adapter 必须同时显式携带 task_id。"""

    expected_service = ("self", "task_id", "operation_ref", "context_snapshot_ref")
    expected_owner = (
        "self",
        "task_id",
        "operation_space_ref",
        "context_snapshot_ref",
    )

    assert _parameter_names(WorkflowServices.bind_parameters) == expected_service
    assert _parameter_names(DefaultWorkflowServices.bind_parameters) == expected_service
    assert (
        _parameter_names(CanonicalWorkflowOwnerPorts.load_parameter_binding_inputs)
        == expected_owner
    )


def test_langgraph_parameter_binding_forwards_existing_state_task_id() -> None:
    """Graph 必须消费已有 task_id；本 amendment 不允许新增 checkpoint 字段。"""

    source = inspect.getsource(build_workflow_graph)
    expected_call = (
        'services.bind_parameters(\n'
        '            cast(str, state["task_id"]),\n'
        '            _require_stable_ref(state, "operation_ref"),'
    )

    assert expected_call in source


class _TaskAwareSemanticBoundary:
    """记录 canonical adapter 是否把 exact task/context lineage 原样送到 semantic boundary。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, StableRef, StableRef]] = []

    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        self.calls.append((task_id, operation_space_ref, context_snapshot_ref))
        return ParameterBindingInputs(
            proposal=OperationProposal(
                "move.v1",
                {"displacement": [300, 0, 0]},
            ),
            context=ParameterBindingContext(
                context_snapshot_id=context_snapshot_ref.ref_id,
                context_snapshot_hash=context_snapshot_ref.content_hash or "",
                document_ref="DOC-TASK2",
                semantic_environment_ref="semantic-env-task2",
                selection=("ENTITY-1",),
            ),
        )


def _adapter(boundary: _TaskAwareSemanticBoundary) -> CanonicalWorkflowOwnerPorts:
    """只替换 Task 2 会触达的 semantic reconstruction 依赖。"""

    dependencies = {
        name: object()
        for name in inspect.signature(CanonicalWorkflowOwnerPorts).parameters
    }
    dependencies["semantic_reconstruction"] = boundary
    return CanonicalWorkflowOwnerPorts(**dependencies)


def test_canonical_adapter_forwards_task_id_and_preserves_context_validation() -> None:
    """task lineage 新增后，既有 authoritative ContextSnapshot exact-match 校验仍必须成立。"""

    boundary = _TaskAwareSemanticBoundary()
    adapter = _adapter(boundary)
    operation_ref = StableRef("OPSPACE-TASK2", "b" * 64)
    context_ref = StableRef("CS-TASK2", "a" * 64)

    inputs = adapter.load_parameter_binding_inputs(
        "task-2-lineage",
        operation_ref,
        context_ref,
    )

    assert inputs.context.context_snapshot_id == context_ref.ref_id
    assert inputs.context.context_snapshot_hash == context_ref.content_hash
    assert boundary.calls == [("task-2-lineage", operation_ref, context_ref)]
