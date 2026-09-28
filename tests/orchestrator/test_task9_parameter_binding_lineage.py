"""Task 9 amendment：冻结 ParameterBinder 的 exact ContextSnapshot lineage seam。"""

from __future__ import annotations

from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionResult,
    ResolvedOperation,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


class _LineageGraphServices:
    """只验证 graph 把 saver 中 exact context ref 转发到 binder seam。"""

    def __init__(self) -> None:
        self.context_ref = StableRef("CS-TASK9", "a" * 64)
        self.operation_space_ref = StableRef("OPSPACE-TASK9", "b" * 64)
        self.binding_calls: list[tuple[StableRef, StableRef]] = []

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(f"context-request:{task_id}", "c" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        del snapshot_ref
        return self.context_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        assert snapshot_ref == self.context_ref
        return self.operation_space_ref

    def bind_parameters(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> AsyncOperationRef:
        self.binding_calls.append((operation_ref, context_snapshot_ref))
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="parameter-binding",
            operation_id="task9-binding-wait",
        )

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected downstream service call: {name}")


class _MemoryArtifactStore:
    """只保存 workflow-local operation-space/bound-operation artifact。"""

    def __init__(self) -> None:
        self._items: dict[str, object] = {}

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        ref_id = f"{kind}:{len(self._items) + 1}"
        self._items[ref_id] = value
        return StableRef(ref_id, content_hash)

    def get(self, ref: StableRef) -> object:
        return self._items[ref.ref_id]


class _BindingOwners:
    """记录 DefaultWorkflowServices 是否原样转发两个 exact refs。"""

    def __init__(self, inputs: ParameterBindingInputs) -> None:
        self.inputs = inputs
        self.calls: list[tuple[StableRef, StableRef]] = []

    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs:
        self.calls.append((operation_space_ref, context_snapshot_ref))
        return self.inputs


def _resolved_move_operation() -> ResolvedOperation:
    """构造真实 ParameterBinder 可消费的最小 operation-space entry。"""

    return ResolvedOperation(
        operation_id="move.v1",
        canonical_operation="move.v1",
        input_schema=dict(MOVE_V1.input_schema),
        canonical_entity_constraints=(),
        context_freshness_requirements=(),
        operation_freshness_requirements=(),
        effects=tuple(MOVE_V1.effects),
        existence_effects=tuple(MOVE_V1.existence_effects),
        policy_decision="ALLOW",
        risk=None,
        task_score=1.0,
        preview_supported=False,
        rollback_supported=False,
        verification_contract=dict(MOVE_V1.verification_contract),
        candidate_provider_ids=(),
    )


def test_graph_parameter_binding_forwards_persisted_context_snapshot_ref() -> None:
    """Human ACCEPT 后 binder 必须同时收到 operation-space 与 saver 中的 ContextSnapshot ref。"""

    services = _LineageGraphServices()
    graph = build_workflow_graph(services).compile(checkpointer=InMemorySaver())
    config = {
        "configurable": {
            "thread_id": "task9-parameter-binding-lineage",
            "checkpoint_ns": "",
        }
    }
    graph.invoke(
        {
            "checkpoint_contract_version": 2,
            "task_id": "task9-parameter-binding-lineage",
            "phase": WorkflowPhase.RESOLVE_HOST_CONTEXT.value,
        },
        config,
    )
    pause_id = graph.get_state(config).values["pending_interaction"]["pause_id"]

    graph.invoke(
        Command(
            resume={
                "pause_id": pause_id,
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "payload": {},
            }
        ),
        config,
    )

    assert services.binding_calls == [
        (services.operation_space_ref, services.context_ref)
    ]


def test_default_services_forwards_exact_context_ref_to_binding_owner() -> None:
    """DefaultWorkflowServices 不得从 operation-space artifact 推断或替换 ContextSnapshot。

    authoritative identity 必须来自调用方显式传入的 ref。
    """

    context_ref = StableRef("CS-TASK9", "d" * 64)
    binding_inputs = ParameterBindingInputs(
        proposal=OperationProposal("move.v1", {"displacement": [300, 0, 0]}),
        context=ParameterBindingContext(
            context_snapshot_id=context_ref.ref_id,
            context_snapshot_hash=context_ref.content_hash or "",
            document_ref="DOC-TASK9",
            semantic_environment_ref="semantic-env-task9",
            selection=("ENTITY-1",),
        ),
    )
    owners = _BindingOwners(binding_inputs)
    store = _MemoryArtifactStore()
    operation_space = ResolutionResult(
        resolved_operations=(_resolved_move_operation(),),
        provider_candidates={},
    )
    operation_space_ref = store.put(
        kind="operation_resolution",
        value=operation_space,
        content_hash=workflow_artifact_content_hash(operation_space),
    )
    service = DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=store,
        external_owners=owners,
    )

    bound_ref = service.bind_parameters("task-test",
                                        operation_space_ref, context_ref)

    assert owners.calls == [(operation_space_ref, context_ref)]
    bound = store.get(bound_ref)
    assert getattr(bound, "context_snapshot_ref").context_snapshot_id == context_ref.ref_id
    assert (
        getattr(bound, "context_snapshot_ref").context_snapshot_hash
        == context_ref.content_hash
    )
