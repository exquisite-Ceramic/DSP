"""Host-neutral orchestrator components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from design_orchestrator.canonical_operations import (
    CanonicalCreationContract,
    CanonicalExistenceEffect,
    CanonicalOperationDefinition,
    MOVE_V1,
    MVP_CANONICAL_OPERATIONS,
    OFFSET_V1,
    SET_WALL_THICKNESS_V1,
    SlotBindingClass,
)
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ExternalOwnerPorts,
    OperationResolutionInputs,
    ParameterBindingInputs,
    WorkflowArtifactStore,
)
from design_orchestrator.operation_resolver import (
    CapabilityConflictError,
    OperationPolicy,
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
    ResolvedOperation,
    TaskConstraints,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    MOVE_V1_BINDING_RECIPE,
    OFFSET_V1_BINDING_RECIPE,
    SET_WALL_THICKNESS_V1_BINDING_RECIPE,
    BindingError,
    BindingResolverKind,
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    OperationBindingRecipe,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
    PlanningRequirements,
    SlotBindingEvidence,
    SlotBindingRecipe,
)
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_port import WorkflowOrchestratorPort

if TYPE_CHECKING:
    # Interaction 子树当前仍是 repository source-only package，并非 uv workspace distribution。
    # 静态类型检查可以看到这些公共符号；普通 Orchestrator 消费方只有真正访问它们时才加载。
    from design_orchestrator.interactive_binding import (
        InteractionBindingContext,
        InteractionRequired,
        InteractiveParameterResolver,
        OperationInteractionRecipe,
        SlotInteractionRecipe,
    )

    # PostgreSQL adapter 是可选的 durable infrastructure dependency。
    # 仅在静态类型检查阶段导入，避免普通 Orchestrator/D6 消费方在运行时被迫安装 psycopg。
    from design_orchestrator.artifact_postgres import (
        PostgresWorkflowArtifactStore,
        create_postgres_artifact_store,
    )


_INTERACTION_EXPORTS = {
    "InteractionBindingContext",
    "InteractionRequired",
    "InteractiveParameterResolver",
    "OperationInteractionRecipe",
    "SlotInteractionRecipe",
}

_POSTGRES_EXPORTS = {
    "PostgresWorkflowArtifactStore",
    "create_postgres_artifact_store",
}


def __getattr__(name: str) -> Any:
    """按需暴露 source-only interaction 与 PostgreSQL adapter 公共符号。"""

    if name in _INTERACTION_EXPORTS:
        # `platform/interaction` 仍由仓库 pytest pythonpath 提供，不是 workspace distribution。
        # package root 因而不能在每次基础导入时强制加载它；真正消费 interaction API 时再解析。
        from design_orchestrator import interactive_binding

        return getattr(interactive_binding, name)

    if name in _POSTGRES_EXPORTS:
        # 只有调用方真正访问 PostgreSQL adapter 公共符号时才加载 psycopg。
        # 这样既保留既有 package-level public API，也不会污染不使用 PostgreSQL 的执行路径。
        from design_orchestrator import artifact_postgres

        return getattr(artifact_postgres, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AsyncOperationKind",
    "AsyncOperationRef",
    "BindingError",
    "BindingResolverKind",
    "BoundOperationProposal",
    "CanonicalCreationContract",
    "CanonicalExistenceEffect",
    "CanonicalOperationDefinition",
    "CanonicalOperationRef",
    "CapabilityConflictError",
    "ContextSnapshotRef",
    "DefaultWorkflowServices",
    "ExternalOwnerPorts",
    "InteractionBindingContext",
    "InteractionRequired",
    "InteractiveParameterResolver",
    "MOVE_V1",
    "MOVE_V1_BINDING_RECIPE",
    "MVP_BINDING_RECIPES",
    "MVP_CANONICAL_OPERATIONS",
    "OFFSET_V1",
    "OFFSET_V1_BINDING_RECIPE",
    "OperationBindingRecipe",
    "OperationInteractionRecipe",
    "OperationPolicy",
    "OperationProposal",
    "OperationResolutionInputs",
    "OperationResolver",
    "ParameterBinder",
    "ParameterBindingContext",
    "ParameterBindingInputs",
    "PendingInteractionKind",
    "PendingInteractionView",
    "PlanningRequirements",
    "PostgresWorkflowArtifactStore",
    "ResolutionContext",
    "ResolutionResult",
    "ResolvedOperation",
    "SET_WALL_THICKNESS_V1",
    "SET_WALL_THICKNESS_V1_BINDING_RECIPE",
    "SlotBindingClass",
    "SlotBindingEvidence",
    "SlotBindingRecipe",
    "SlotInteractionRecipe",
    "StableRef",
    "TaskConstraints",
    "WorkflowArtifactStore",
    "WorkflowCheckpointView",
    "WorkflowOrchestratorPort",
    "WorkflowPhase",
    "WorkflowResumeCommand",
    "WorkflowStartRequest",
    "create_postgres_artifact_store",
]
