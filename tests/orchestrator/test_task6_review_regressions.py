from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from design_approval_scope import ApprovalScopePlanner
from design_changeset import ChangeSetBuilder
from design_impact import ImpactAnalyzer
from design_materialization_topology import MaterializationTopologyRegistry
from design_orchestrator.canonical_operations import MVP_CANONICAL_OPERATIONS
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    OperationResolutionInputs,
    ParameterBindingInputs,
)
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    StableRef,
    WorkflowPhase,
    WorkflowStartRequest,
)
from langgraph.checkpoint.memory import InMemorySaver
from semantic_runtime import DirtyMap, FreshnessResolver
from tests.orchestrator.test_canonical_owner_ports import (
    _ApprovalAdmission,
    _Dependency,
    _HostRevisionObservation,
    _OWNER_DEPENDENCY_NAMES,
    _Preview,
    _TASK6_ENVIRONMENT,
    _Task6SemanticReconstruction,
    _task6_adapter,
    _task6_bound_operation,
    _task6_topology,
)


@dataclass(frozen=True, slots=True)
class _MoveProfile:
    """只为真实 OperationResolver 提供 MOVE_V1 所需的 provider capability 输入。"""

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


class _Task6WorkflowInputs(_Task6SemanticReconstruction):
    """真实 resolver/binder 之前允许存在的窄 read-model/environment 输入边界。"""

    def __init__(self) -> None:
        super().__init__()
        self.context_ref: StableRef | None = None

    def load_operation_resolution_inputs(
        self,
        snapshot_ref: StableRef,
    ) -> OperationResolutionInputs:
        """返回 provider/context read model；OperationResolver 仍负责 eligibility 规则。"""

        self.context_ref = snapshot_ref
        return OperationResolutionInputs(
            profiles=(_MoveProfile(),),
            context=ResolutionContext(
                host_provider_servers=frozenset({"autocad.local"}),
                semantic_context=SemanticEligibilityContext(
                    context_snapshot_id=snapshot_ref.ref_id,
                    context_snapshot_hash=snapshot_ref.content_hash or "",
                    document_ref="DOC-TASK6",
                    semantic_environment_ref=_TASK6_ENVIRONMENT.environment_id,
                    entities=(),
                ),
            ),
        )

    def load_parameter_binding_inputs(
        self,
        operation_space_ref: StableRef,
    ) -> ParameterBindingInputs:
        """返回用户 proposal 与 snapshot-bound context；ParameterBinder 仍负责 slot/schema 规则。"""

        del operation_space_ref
        if self.context_ref is None:
            raise AssertionError("operation resolution inputs must be loaded first")
        return ParameterBindingInputs(
            proposal=OperationProposal(
                "move.v1",
                {"displacement": [300, 0, 0]},
            ),
            context=ParameterBindingContext(
                context_snapshot_id=self.context_ref.ref_id,
                context_snapshot_hash=self.context_ref.content_hash or "",
                document_ref="DOC-TASK6",
                semantic_environment_ref=_TASK6_ENVIRONMENT.environment_id,
                selection=("WALL-001",),
            ),
        )


def _rebuild_adapter(
    *,
    artifact_store: object,
    snapshot_registry: object,
    impact_store: object,
    approval_scope_store: object,
    changeset_store: object,
    semantic_reconstruction: object,
) -> CanonicalWorkflowOwnerPorts:
    """只重建 composition object，并复用所有 authoritative owner stores。"""

    topology_registry = MaterializationTopologyRegistry()
    topology_registry.register(_task6_topology())
    values = {name: _Dependency(name) for name in _OWNER_DEPENDENCY_NAMES}
    values.update(
        {
            "snapshot_registry": snapshot_registry,
            "freshness_resolver": FreshnessResolver(DirtyMap()),
            "workflow_artifact_store": artifact_store,
            "host_revision_observation": _HostRevisionObservation(),
            "canonical_operations": MVP_CANONICAL_OPERATIONS,
            "impact_analyzer": ImpactAnalyzer(),
            "impact_store": impact_store,
            "approval_scope_planner": ApprovalScopePlanner(),
            "approval_scope_store": approval_scope_store,
            "changeset_builder": ChangeSetBuilder(),
            "changeset_store": changeset_store,
            "topology_registry": topology_registry,
            "topology_environment_id": "TOPOLOGY-TASK6",
            "topology_revision": 1,
            "semantic_reconstruction": semantic_reconstruction,
            "preview_port": _Preview(),
            "approval_admission": _ApprovalAdmission(),
        }
    )
    return CanonicalWorkflowOwnerPorts(**values)


def _impact_case():
    """生成一组可跨 adapter 重建继续使用的 Task 6 authoritative owner truth。"""

    (
        adapter,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
    ) = _task6_adapter()
    context_request_ref = adapter.resolve_host_context("task-6")
    context_ref = adapter.ensure_context_freshness(context_request_ref)
    assert isinstance(context_ref, StableRef)

    bound = _task6_bound_operation(context_ref)
    bound_ref = artifact_store.put(
        kind="bound_operation_proposal",
        value=bound,
        content_hash=workflow_artifact_content_hash(bound),
    )
    semantic_reconstruction.operation_ready = True
    assert adapter.ensure_operation_freshness(bound_ref) == bound_ref
    impact_ref = adapter.analyze_impact(bound_ref)
    return (
        adapter,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
        bound_ref,
        impact_ref,
    )


def test_task6_changeset_uses_explicit_task_and_operation_lineage() -> None:
    """task_id/operation_ref 必须来自显式 workflow lineage，不能反查 content-addressed snapshot。"""

    (
        adapter,
        _,
        _,
        _,
        _,
        changeset_store,
        _,
        bound_ref,
        impact_ref,
    ) = _impact_case()

    changeset_ref = adapter.build_changeset("task-A", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)

    assert changeset.task_id == "task-A"


def test_task6_adapter_rebuild_preserves_required_lineage_via_refs_and_owner_stores() -> None:
    """只重建 adapter 时，保留的 owner stores + 显式 refs 必须足以继续构造 ChangeSet。"""

    (
        _,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
        bound_ref,
        impact_ref,
    ) = _impact_case()
    rebuilt = _rebuild_adapter(
        artifact_store=artifact_store,
        snapshot_registry=snapshot_registry,
        impact_store=impact_store,
        approval_scope_store=approval_scope_store,
        changeset_store=changeset_store,
        semantic_reconstruction=semantic_reconstruction,
    )

    changeset_ref = rebuilt.build_changeset("task-6", bound_ref, impact_ref)
    assert changeset_store.get(changeset_ref.ref_id).task_id == "task-6"


def test_task6_adapter_has_no_process_local_required_lineage_maps() -> None:
    """composition object 不得保存 task/snapshot、operation/freshness 或 impact/operation 必需映射。"""

    forbidden = {
        "_task_ids_by_context_snapshot",
        "_freshness_refs_by_operation",
        "_operation_refs_by_impact",
    }
    assert forbidden.isdisjoint(CanonicalWorkflowOwnerPorts.__slots__)


def test_task6_real_runtime_start_reaches_operation_proposal_hitl() -> None:
    """真实 runtime 必须穿过 context freshness 与真实 OperationResolver，而不是在前置 loader 阻断。"""

    (
        _,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_adapter()
    workflow_inputs = _Task6WorkflowInputs()
    adapter = _rebuild_adapter(
        artifact_store=artifact_store,
        snapshot_registry=snapshot_registry,
        impact_store=impact_store,
        approval_scope_store=approval_scope_store,
        changeset_store=changeset_store,
        semantic_reconstruction=workflow_inputs,
    )
    services = DefaultWorkflowServices(
        operation_resolver=OperationResolver(MVP_CANONICAL_OPERATIONS),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=artifact_store,
        external_owners=adapter,
    )
    runtime = LangGraphWorkflowRuntime(services=services, checkpointer=InMemorySaver())

    checkpoint = runtime.start(
        WorkflowStartRequest(
            task_id="task-6",
            request_data={"intent": "move selected entity"},
            initial_host_ref=StableRef("host-task6", "9" * 64),
            initial_context_ref=None,
        )
    )

    assert checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert checkpoint.pending_interaction is not None
    assert checkpoint.operation_ref is not None


def test_task6_parameter_binding_inputs_are_wired_before_task7() -> None:
    """Task 6 收口时 binder read-model loader 也必须可调用，不能把阻断推迟到 HITL resume。"""

    (
        _,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_adapter()
    workflow_inputs = _Task6WorkflowInputs()
    adapter = _rebuild_adapter(
        artifact_store=artifact_store,
        snapshot_registry=snapshot_registry,
        impact_store=impact_store,
        approval_scope_store=approval_scope_store,
        changeset_store=changeset_store,
        semantic_reconstruction=workflow_inputs,
    )
    context_request_ref = adapter.resolve_host_context("task-6")
    context_ref = adapter.ensure_context_freshness(context_request_ref)
    assert isinstance(context_ref, StableRef)
    resolution_inputs = adapter.load_operation_resolution_inputs(context_ref)
    assert isinstance(resolution_inputs, OperationResolutionInputs)

    operation_space_ref = StableRef("operation-space-task6", "8" * 64)
    binding_inputs = adapter.load_parameter_binding_inputs(operation_space_ref)

    assert isinstance(binding_inputs, ParameterBindingInputs)
    assert binding_inputs.context.context_snapshot_id == context_ref.ref_id
