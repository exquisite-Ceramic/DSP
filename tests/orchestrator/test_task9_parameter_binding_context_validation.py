"""Task 9 closing regression：canonical adapter 必须校验 ParameterBinder context lineage。"""

from __future__ import annotations

import inspect

import pytest
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.default_workflow_services import ParameterBindingInputs
from design_orchestrator.parameter_binder import (
    OperationProposal,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import StableRef


class _BindingBoundary:
    """返回调用方指定的 snapshot-bound ParameterBindingInputs。"""

    def __init__(self, context: ParameterBindingContext) -> None:
        self.context = context
        self.calls: list[tuple[StableRef, StableRef]] = []

    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        """记录两个显式 refs；故意允许测试构造错误 lineage 的 context。"""

        self.calls.append((operation_space_ref, context_snapshot_ref))
        return ParameterBindingInputs(
            proposal=OperationProposal(
                "move.v1",
                {"displacement": [300, 0, 0]},
            ),
            context=self.context,
        )


def _adapter(boundary: _BindingBoundary) -> CanonicalWorkflowOwnerPorts:
    """只替换本测试会触达的 semantic reconstruction 依赖。"""

    dependencies = {
        name: object()
        for name in inspect.signature(CanonicalWorkflowOwnerPorts).parameters
    }
    dependencies["semantic_reconstruction"] = boundary
    return CanonicalWorkflowOwnerPorts(**dependencies)


def _context(snapshot_id: str, snapshot_hash: str) -> ParameterBindingContext:
    """构造合法的 binder context，lineage 是否匹配由 adapter 负责判断。"""

    return ParameterBindingContext(
        context_snapshot_id=snapshot_id,
        context_snapshot_hash=snapshot_hash,
        document_ref="DOC-TASK9",
        semantic_environment_ref="semantic-env-task9",
        selection=("ENTITY-1",),
    )


def test_matching_parameter_binding_context_lineage_is_accepted() -> None:
    """返回 context 与 authoritative ref 完全一致时必须保持原 read model。"""

    authoritative = StableRef("CS-TASK9", "a" * 64)
    boundary = _BindingBoundary(_context(authoritative.ref_id, "a" * 64))
    adapter = _adapter(boundary)
    operation_space_ref = StableRef("OPSPACE-TASK9", "c" * 64)

    result = adapter.load_parameter_binding_inputs(
        "task-test",
        operation_space_ref,
        authoritative,
    )

    assert result.context.context_snapshot_id == authoritative.ref_id
    assert result.context.context_snapshot_hash == authoritative.content_hash
    assert boundary.calls == [(operation_space_ref, authoritative)]


@pytest.mark.parametrize(
    ("returned_id", "returned_hash"),
    [
        ("CS-OTHER", "a" * 64),
        ("CS-TASK9", "b" * 64),
    ],
    ids=("snapshot-id-mismatch", "snapshot-hash-mismatch"),
)
def test_parameter_binding_context_lineage_mismatch_fails_closed(
    returned_id: str,
    returned_hash: str,
) -> None:
    """类型正确但指向其它 ContextSnapshot 的 read model 也必须 fail closed。"""

    authoritative = StableRef("CS-TASK9", "a" * 64)
    adapter = _adapter(_BindingBoundary(_context(returned_id, returned_hash)))

    with pytest.raises(ValueError, match="ParameterBindingContext lineage"):
        adapter.load_parameter_binding_inputs(
            "task-test",
            StableRef("OPSPACE-TASK9", "c" * 64),
            authoritative,
        )


def test_parameter_binding_requires_hashed_authoritative_context_ref() -> None:
    """缺失 content_hash 的 ContextSnapshot ref 不能降级为仅按 ID 信任。"""

    authoritative = StableRef("CS-TASK9")
    adapter = _adapter(_BindingBoundary(_context(authoritative.ref_id, "a" * 64)))

    with pytest.raises(ValueError, match="ContextSnapshot StableRef requires content_hash"):
        adapter.load_parameter_binding_inputs(
            "task-test",
            StableRef("OPSPACE-TASK9", "c" * 64),
            authoritative,
        )
