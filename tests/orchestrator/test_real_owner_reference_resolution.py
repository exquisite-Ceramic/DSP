from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest
from design_approval_scope import (
    ApprovalScopeError,
    InMemoryApprovalScopeStore,
    bind_topology_snapshot_v2,
)
from design_changeset import ChangeSetError, InMemoryChangeSetStore
from design_execution_planning import (
    ExecutionPlanningError,
    InMemoryExecutionPlanV2Store,
    plan_materialized_execution,
)
from design_impact import (
    ImpactAnalysis,
    ImpactError,
    InMemoryImpactAnalysisStore,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_materialization_planning import (
    InMemoryMaterializationPlanStore,
    MaterializationPlanner,
    MaterializationPlanningError,
    MaterializationPlanningRequest,
)
from design_provider_binding import (
    InMemoryProviderBindingSetV2Store,
    ProviderBindingError,
    resolve_provider_bindings_v2,
)
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    DirtyMap,
    FreshnessResolver,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    SemanticAspect,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotRegistryError,
    SnapshotSet,
    build_operation_contract,
)

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.materialization_planning._support import build_case
from tests.provider_binding._support import build_phase_i_binding_inputs

PROJECTION_REF = SemanticProjectionRef(
    "projection-reference-store",
    "projection-hash-reference-store",
    "semantic-model-v1",
    "provider-set-hash",
    "mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef(
    "environment-reference-store",
    "environment-hash-reference-store",
)


def _planning_snapshot():
    """通过 owner 现有 FreshnessResolver 构造真实 PlanningSnapshot。"""
    resolver = FreshnessResolver(DirtyMap())
    contract = build_operation_contract(
        project_id="project-reference-store",
        document_ref="doc-reference-store",
        canonical_operation="move.v1",
        targets=("sem-reference-store",),
        arguments={"displacement": [100, 0, 0]},
        requirements=(AspectRequirement(SemanticAspect.PLACEMENT),),
    )
    return resolver.resolve(
        contract,
        expected_host_revision="17",
        reconstruct=lambda current_contract, expected_revision: ReconstructionResult(
            document_ref=current_contract.coverage.document_ref,
            host_revision=expected_revision,
            coverage=current_contract.coverage,
            guarantees=(AspectGuarantee(SemanticAspect.PLACEMENT),),
            projection_ref=PROJECTION_REF,
            semantic_environment_ref=ENVIRONMENT_REF,
        ),
    )


def _impact_analysis() -> ImpactAnalysis:
    """只使用 Step27 公共 value contracts 构造最小合法 ImpactAnalysis。"""
    environment = SemanticEnvironmentBinding("ENV-STORE", "env-hash-store")
    planning = PlanningSnapshotBinding(
        "PS-STORE",
        "ps-hash-store",
        "DOC-STORE",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-STORE",
        "pss-hash-store",
        (planning.snapshot_id,),
        environment,
    )
    return ImpactAnalysis(
        analysis_id="IA-STORE",
        canonical_operation="set_wall_thickness.v1",
        direct_targets=("WALL-001",),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        analysis_fingerprint="impact-fingerprint-store",
    )


@lru_cache(maxsize=1)
def _phase_i_artifacts():
    """复用既有 Phase-I support builders，避免在 store 测试重写 owner 语义。"""
    case = build_case()
    scope_definition_v2 = bind_topology_snapshot_v2(
        case.scope_v1,
        case.topology.topology_snapshot_hash,
    )
    materialization_plan = MaterializationPlanner().plan(
        MaterializationPlanningRequest(
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            topology_snapshot=case.topology,
            convergence_profile=case.profile,
        )
    )

    _, _, _, execution_request = build_phase_i_execution_inputs()
    execution_plan = plan_materialized_execution(execution_request)

    _, slices, snapshots = build_phase_i_binding_inputs()
    provider_binding_set = resolve_provider_bindings_v2(
        slices["revit"],
        snapshots["revit"],
    )
    return (
        case,
        scope_definition_v2,
        materialization_plan,
        execution_plan,
        provider_binding_set,
    )


def test_semantic_snapshot_registry_is_replay_safe_and_fail_closed() -> None:
    snapshot = _planning_snapshot()
    snapshot_set = SnapshotSet.create((snapshot,))
    store = InMemorySnapshotRegistry()

    store.put_snapshot(snapshot)
    store.put_snapshot(snapshot)
    assert store.get_snapshot(snapshot.snapshot_id) is snapshot

    with pytest.raises(SnapshotRegistryError) as conflict:
        store.put_snapshot(replace(snapshot, hash="f" * 64))
    assert conflict.value.code == "SNAPSHOT_REFERENCE_CONFLICT"

    with pytest.raises(SnapshotRegistryError) as missing:
        store.get_snapshot("PS-MISSING")
    assert missing.value.code == "SNAPSHOT_REFERENCE_NOT_FOUND"

    store.put_snapshot_set(snapshot_set)
    store.put_snapshot_set(snapshot_set)
    assert store.get_snapshot_set(snapshot_set.snapshot_set_id) is snapshot_set

    with pytest.raises(SnapshotRegistryError) as missing_set:
        store.get_snapshot_set("PSS-MISSING")
    assert missing_set.value.code == "SNAPSHOT_SET_REFERENCE_NOT_FOUND"


def test_impact_store_is_replay_safe_and_fail_closed() -> None:
    analysis = _impact_analysis()
    store = InMemoryImpactAnalysisStore()

    store.put(analysis)
    store.put(analysis)
    assert store.get(analysis.analysis_id) is analysis

    with pytest.raises(ImpactError) as conflict:
        store.put(replace(analysis, analysis_fingerprint="different-fingerprint"))
    assert conflict.value.code == "IMPACT_ANALYSIS_REFERENCE_CONFLICT"

    with pytest.raises(ImpactError) as missing:
        store.get("IA-MISSING")
    assert missing.value.code == "IMPACT_ANALYSIS_REFERENCE_NOT_FOUND"


def test_approval_scope_store_validates_v2_definition_and_boundary_references() -> None:
    case, definition, _, _, _ = _phase_i_artifacts()
    boundary = case.boundary_v2
    store = InMemoryApprovalScopeStore()

    store.put_definition(definition)
    store.put_definition(definition)
    assert store.get_definition(definition.scope_definition_id) is definition

    with pytest.raises(ApprovalScopeError) as definition_conflict:
        store.put_definition(replace(definition, scope_body_hash="f" * 64))
    assert definition_conflict.value.code in {
        "APPROVAL_SCOPE_REFERENCE_CONFLICT",
        "APPROVAL_SCOPE_INTEGRITY_INVALID",
    }

    store.put_boundary(boundary)
    store.put_boundary(boundary)
    assert store.get_boundary(boundary.scope_id) is boundary

    with pytest.raises(ApprovalScopeError) as boundary_conflict:
        store.put_boundary(replace(boundary, scope_hash="f" * 64))
    assert boundary_conflict.value.code in {
        "APPROVAL_SCOPE_REFERENCE_CONFLICT",
        "APPROVAL_SCOPE_INTEGRITY_INVALID",
    }

    with pytest.raises(ApprovalScopeError) as missing:
        store.get_boundary("SCOPE-MISSING")
    assert missing.value.code == "APPROVAL_SCOPE_REFERENCE_NOT_FOUND"


def test_changeset_store_is_replay_safe_and_fail_closed() -> None:
    case, _, _, _, _ = _phase_i_artifacts()
    changeset = case.changeset
    store = InMemoryChangeSetStore()

    store.put(changeset)
    store.put(changeset)
    assert store.get(changeset.changeset_id) is changeset

    with pytest.raises(ChangeSetError) as conflict:
        store.put(replace(changeset, changeset_hash="f" * 64))
    assert conflict.value.code == "CHANGESET_REFERENCE_CONFLICT"

    with pytest.raises(ChangeSetError) as missing:
        store.get("CS-MISSING")
    assert missing.value.code == "CHANGESET_REFERENCE_NOT_FOUND"


def test_materialization_plan_store_uses_hash_as_canonical_identity() -> None:
    _, _, plan, _, _ = _phase_i_artifacts()
    store = InMemoryMaterializationPlanStore()

    store.put(plan)
    store.put(plan)
    assert store.get(plan.materialization_plan_hash) is plan

    tampered = replace(plan, changeset_hash="f" * 64)
    with pytest.raises(MaterializationPlanningError):
        store.put(tampered)

    with pytest.raises(MaterializationPlanningError) as missing:
        store.get("f" * 64)
    assert missing.value.code == "MATERIALIZATION_PLAN_REFERENCE_NOT_FOUND"


def test_execution_plan_v2_store_is_replay_safe_and_fail_closed() -> None:
    _, _, _, plan, _ = _phase_i_artifacts()
    store = InMemoryExecutionPlanV2Store()

    store.put(plan)
    store.put(plan)
    assert store.get(plan.execution_plan_id) is plan

    with pytest.raises(ExecutionPlanningError) as conflict:
        store.put(replace(plan, execution_plan_hash="f" * 64))
    assert conflict.value.code in {
        "EXECUTION_PLAN_REFERENCE_CONFLICT",
        "EXECUTION_PLAN_INTEGRITY_INVALID",
    }

    with pytest.raises(ExecutionPlanningError) as missing:
        store.get("EP-MISSING")
    assert missing.value.code == "EXECUTION_PLAN_REFERENCE_NOT_FOUND"


def test_provider_binding_set_v2_store_is_replay_safe_and_fail_closed() -> None:
    _, _, _, _, binding_set = _phase_i_artifacts()
    store = InMemoryProviderBindingSetV2Store()

    store.put(binding_set)
    store.put(binding_set)
    assert store.get(binding_set.binding_set_id) is binding_set

    with pytest.raises(ProviderBindingError) as conflict:
        store.put(replace(binding_set, binding_set_hash="f" * 64))
    assert conflict.value.code in {
        "PROVIDER_BINDING_SET_REFERENCE_CONFLICT",
        "PROVIDER_BINDING_INTEGRITY_INVALID",
    }

    with pytest.raises(ProviderBindingError) as missing:
        store.get("PBS-MISSING")
    assert missing.value.code == "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND"


def test_orchestrator_does_not_gain_cross_owner_reference_repository() -> None:
    """Owner-local stores must not collapse into an orchestrator object bag."""
    orchestrator_root = (
        Path(__file__).resolve().parents[2]
        / "platform"
        / "orchestrator"
        / "src"
        / "design_orchestrator"
    )
    forbidden = {
        "reference_store.py",
        "reference_repository.py",
        "owner_repository.py",
    }
    assert not any((orchestrator_root / name).exists() for name in forbidden)
