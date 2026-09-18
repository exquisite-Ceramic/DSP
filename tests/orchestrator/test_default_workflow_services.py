from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Any

import pytest

from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    BoundOperationProposal,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_contracts import StableRef


@dataclass(frozen=True, slots=True)
class _Profile:
    """Task 8 测试用的最小 provider capability profile。"""

    provider_server: str = "autocad.local"
    provider_tool: str = "cad.move"
    canonical_operation: str = "move.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PLACEMENT", "GEOMETRY")
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["handles", "dx", "dy"],
        }
    )
    output_schema: dict[str, Any] | None = None


class _MemoryArtifactStore:
    """只用于验证 workflow-local artifact/ref 边界的内存 store。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.kinds: dict[str, str] = {}
        self.hashes: dict[str, str] = {}

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        ref_id = f"artifact-{len(self.values) + 1}"
        self.values[ref_id] = value
        self.kinds[ref_id] = kind
        self.hashes[ref_id] = content_hash
        return StableRef(ref_id=ref_id, content_hash=content_hash)

    def get(self, ref: StableRef) -> object:
        return self.values[ref.ref_id]


class _ExternalOwners:
    """Task 8 只提供 resolver/binder 所需 owner read models；其余端口不在本测试调用。"""

    def __init__(self) -> None:
        self.resolution_inputs: OperationResolutionInputs | None = None
        self.binding_inputs: ParameterBindingInputs | None = None
        self.resolution_calls: list[StableRef] = []
        self.binding_calls: list[StableRef] = []

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        self.resolution_calls.append(snapshot_ref)
        assert self.resolution_inputs is not None
        return self.resolution_inputs

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
    ) -> ParameterBindingInputs:
        self.binding_calls.append(operation_space_ref)
        assert self.binding_inputs is not None
        return self.binding_inputs


def _resolution_context() -> ResolutionContext:
    """构造与 MOVE_V1 对齐的真实 ResolutionContext。"""

    return ResolutionContext(
        host_provider_servers=frozenset({"autocad.local"}),
        semantic_context=SemanticEligibilityContext(
            context_snapshot_id="CS-task8",
            context_snapshot_hash="snapshot-task8",
            document_ref="drawing-task8",
            semantic_environment_ref="semantic-env@task8",
            entities=(),
        ),
    )


def _binding_context() -> ParameterBindingContext:
    """构造 ParameterBinder 所需的真实 snapshot-bound read model。"""

    return ParameterBindingContext(
        context_snapshot_id="CS-task8",
        context_snapshot_hash="snapshot-task8",
        document_ref="drawing-task8",
        semantic_environment_ref="semantic-env@task8",
        selection=("S-001", "S-002"),
    )


def _service() -> tuple[DefaultWorkflowServices, _MemoryArtifactStore, _ExternalOwners]:
    """使用真实 OperationResolver 与 ParameterBinder 组装默认 workflow services。"""

    store = _MemoryArtifactStore()
    owners = _ExternalOwners()
    service = DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=store,
        external_owners=owners,
    )
    return service, store, owners


def test_operation_resolver_adapter_persists_resolution_and_returns_only_ref() -> None:
    """resolver 结果可以保存在 workflow-local store，但 checkpoint-facing 返回值只能是 ref。"""

    service, store, owners = _service()
    owners.resolution_inputs = OperationResolutionInputs(
        profiles=(_Profile(),),
        context=_resolution_context(),
    )
    snapshot_ref = StableRef("snapshot-task8")

    operation_space_ref = service.resolve_operations(snapshot_ref)

    assert isinstance(operation_space_ref, StableRef)
    assert owners.resolution_calls == [snapshot_ref]
    assert store.kinds[operation_space_ref.ref_id] == "operation_resolution"
    stored = store.get(operation_space_ref)
    assert isinstance(stored, ResolutionResult)
    assert [item.canonical_operation for item in stored.resolved_operations] == ["move.v1"]
    assert stored.provider_candidates
    assert operation_space_ref.content_hash == store.hashes[operation_space_ref.ref_id]
    assert operation_space_ref.content_hash is not None
    assert len(operation_space_ref.content_hash) == 64


def test_parameter_binder_adapter_persists_bound_proposal_and_returns_only_ref() -> None:
    """binder 必须消费真实 proposal/context，并把 BoundOperationProposal 隐藏在 artifact ref 后。"""

    service, store, owners = _service()
    owners.resolution_inputs = OperationResolutionInputs(
        profiles=(_Profile(),),
        context=_resolution_context(),
    )
    operation_space_ref = service.resolve_operations(StableRef("snapshot-task8"))
    owners.binding_inputs = ParameterBindingInputs(
        proposal=OperationProposal(
            "move.v1",
            {"displacement": [300, 0, 0]},
        ),
        context=_binding_context(),
    )

    bound_ref = service.bind_parameters(operation_space_ref)

    assert isinstance(bound_ref, StableRef)
    assert owners.binding_calls == [operation_space_ref]
    assert store.kinds[bound_ref.ref_id] == "bound_operation_proposal"
    stored = store.get(bound_ref)
    assert isinstance(stored, BoundOperationProposal)
    assert stored.operation.canonical_operation == "move.v1"
    assert dict(stored.arguments) == {
        "targets": ["S-001", "S-002"],
        "displacement": [300, 0, 0],
    }
    assert bound_ref.content_hash is not None
    assert len(bound_ref.content_hash) == 64


def test_parameter_binding_rejects_proposal_outside_persisted_operation_space() -> None:
    """adapter 只检查已冻结 operation-space membership，不复制 resolver eligibility 算法。"""

    service, _, owners = _service()
    owners.resolution_inputs = OperationResolutionInputs(
        profiles=(_Profile(),),
        context=_resolution_context(),
    )
    operation_space_ref = service.resolve_operations(StableRef("snapshot-task8"))
    owners.binding_inputs = ParameterBindingInputs(
        proposal=OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300, "unit": "mm"}},
        ),
        context=_binding_context(),
    )

    try:
        service.bind_parameters(operation_space_ref)
    except ValueError as exc:
        assert "operation space" in str(exc)
    else:
        raise AssertionError("proposal outside persisted operation space must fail closed")


def test_langgraph_runtime_does_not_copy_deterministic_domain_algorithms() -> None:
    """LangGraph 只能路由 service，不得吸收 resolver/binder/Saga/dispatch transition 规则。"""

    # 旧 deterministic lane 不安装 LangGraph；该源码守卫只在 runtime 依赖存在时有意义。
    pytest.importorskip("langgraph")
    from design_orchestrator import langgraph_graph, langgraph_runtime

    source = inspect.getsource(langgraph_graph) + inspect.getsource(langgraph_runtime)
    forbidden_identifiers = (
        "_supports_canonical_entities",
        "_validate_recipe_match",
        "ExecutionSagaStatusV2",
        "HostDispatchStatus",
        "compute_changeset_hash",
        "compute_execution_slice_hash",
    )
    for identifier in forbidden_identifiers:
        assert identifier not in source
