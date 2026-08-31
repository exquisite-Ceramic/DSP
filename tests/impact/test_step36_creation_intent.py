from __future__ import annotations

from hashlib import sha256
import json

from design_impact import (
    ImpactAnalyzer,
    ImpactAnalysisRequest,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import CanonicalExistenceEffect
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    PlanningRequirements,
)


def _bound_offset() -> BoundOperationProposal:
    return BoundOperationProposal(
        operation=CanonicalOperationRef("offset.v1", "1.0.0"),
        arguments={
            "targets": ["WALL-001"],
            "distance": {"value": 300.0, "unit": "mm"},
            "side_point": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
        },
        binding_evidence={},
        context_snapshot_ref=ContextSnapshotRef("CS-36", "ctx-hash-36", "DOC-1"),
        planning_requirements=PlanningRequirements(),
        semantic_environment_ref="ENV-1",
    )


def _bindings():
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    return environment, planning, snapshot_set


def _request(intent: IntentBoundary) -> ImpactAnalysisRequest:
    environment, planning, snapshot_set = _bindings()
    return ImpactAnalysisRequest(
        bound_operation=_bound_offset(),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        intent_boundary=intent,
    )


def _legacy_fingerprint(request: ImpactAnalysisRequest) -> str:
    payload = {
        "operation": {
            "canonical_operation": request.bound_operation.operation.canonical_operation,
            "version": request.bound_operation.operation.version,
            "arguments": dict(request.bound_operation.arguments),
        },
        "direct_targets": ["WALL-001"],
        "planning_snapshot": {
            "snapshot_id": request.planning_snapshot_ref.snapshot_id,
            "snapshot_hash": request.planning_snapshot_ref.snapshot_hash,
            "document_ref": request.planning_snapshot_ref.document_ref,
        },
        "snapshot_set": {
            "snapshot_set_id": request.snapshot_set_ref.snapshot_set_id,
            "snapshot_set_hash": request.snapshot_set_ref.snapshot_set_hash,
            "member_snapshot_ids": list(request.snapshot_set_ref.member_snapshot_ids),
        },
        "semantic_environment": {
            "environment_id": request.semantic_environment_ref.environment_id,
            "content_hash": request.semantic_environment_ref.content_hash,
        },
        "dependency_edges": [],
        "constraint_rules": [],
        "observed_facts": {},
        "intent_boundary": {
            "direct_targets": list(request.intent_boundary.direct_targets),
            "allowed_canonical_effects": list(
                request.intent_boundary.allowed_canonical_effects
            ),
            "allowed_derived_rule_refs": list(
                request.intent_boundary.allowed_derived_rule_refs
            ),
        },
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def test_intent_boundary_normalizes_create_existence_effect() -> None:
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_existence_effects=("CREATE", "CREATE"),
    )

    assert intent.allowed_existence_effects == (CanonicalExistenceEffect.CREATE,)


def test_empty_existence_intent_preserves_pre_step36_analysis_fingerprint() -> None:
    request = _request(
        IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=(),
            allowed_derived_rule_refs=(),
        )
    )

    result = ImpactAnalyzer().analyze(request)

    assert result.analysis_fingerprint == _legacy_fingerprint(request)


def test_create_existence_intent_changes_analysis_fingerprint() -> None:
    legacy_request = _request(IntentBoundary(direct_targets=("WALL-001",)))
    create_request = _request(
        IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_existence_effects=(CanonicalExistenceEffect.CREATE,),
        )
    )

    legacy = ImpactAnalyzer().analyze(legacy_request)
    create = ImpactAnalyzer().analyze(create_request)

    assert create.analysis_fingerprint != legacy.analysis_fingerprint
