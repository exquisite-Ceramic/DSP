"""Public API for provider-neutral immutable Step30 execution planning."""

from .contracts import (
    ApprovalScopeRef,
    ApprovedExecutionScopeRef,
    ExecutionDependency,
    ExecutionPlan,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    ExecutionSlice,
    ExecutionUnit,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
)
from .hashing import (
    compute_execution_plan_hash,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
    compute_routing_snapshot_hash,
)
from .integrity import (
    validate_execution_plan_integrity,
    validate_execution_slice_integrity,
)
from .planner import ExecutionPlanner
from .v2 import (
    ExecutionPlanningRequestV2,
    ExecutionPlanV2,
    ExecutionSliceV2,
    ExecutionUnitV2,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
    plan_materialized_execution,
    validate_execution_plan_v2,
)

__all__ = [
    "ApprovalScopeRef",
    "ApprovedExecutionScopeRef",
    "ExecutionDependency",
    "ExecutionPlan",
    "ExecutionPlanV2",
    "ExecutionPlanner",
    "ExecutionPlanningError",
    "ExecutionPlanningRequest",
    "ExecutionPlanningRequestV2",
    "ExecutionSlice",
    "ExecutionSliceV2",
    "ExecutionUnit",
    "ExecutionUnitV2",
    "HostRuntimeRef",
    "MaterializationRoutingEvidence",
    "MaterializationRuntimeRoute",
    "RuntimeEntityRoute",
    "RuntimeRoutingEvidence",
    "compute_execution_plan_hash",
    "compute_execution_slice_hash",
    "compute_execution_unit_hash",
    "compute_materialization_routing_hash",
    "compute_routing_snapshot_hash",
    "plan_materialized_execution",
    "validate_execution_plan_integrity",
    "validate_execution_plan_v2",
    "validate_execution_slice_integrity",
]
