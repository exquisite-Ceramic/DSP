from __future__ import annotations

import hashlib
import json

from design_impact import (
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import MVP_CANONICAL_OPERATIONS
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _bound_move(*, displacement=(100.0, 0.0, 0.0)):
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP29",
        context_snapshot_hash="context-hash-step29",
        document_ref="DOC-1",
        semantic_environment_ref="ENV-1",
        selection=("WALL-001",),
        context_values={},
    )
    return binder.bind(
        OperationProposal("move.v1", {"displacement": list(displacement)}),
        context,
    )


def _request(*, bound=None):
    bound = bound or _bound_move()
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    return ImpactAnalysisRequest(
        bound_operation=bound,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        intent_boundary=IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
        ),
    )


def _material_operation_hash(bound) -> str:
    payload = {
        "canonical_operation": bound.operation.canonical_operation,
        "canonical_operation_version": bound.operation.version,
        "arguments": dict(bound.arguments),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_impact_analysis_exposes_exact_bound_operation_fingerprint() -> None:
    bound = _bound_move()
    result = ImpactAnalyzer().analyze(_request(bound=bound))

    assert result.bound_operation_fingerprint == _material_operation_hash(bound)


def test_material_argument_change_changes_bound_operation_fingerprint() -> None:
    first = ImpactAnalyzer().analyze(_request(bound=_bound_move()))
    second = ImpactAnalyzer().analyze(
        _request(bound=_bound_move(displacement=(101.0, 0.0, 0.0)))
    )

    assert first.bound_operation_fingerprint != second.bound_operation_fingerprint
