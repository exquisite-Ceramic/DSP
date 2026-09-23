from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pytest
from design_approval_scope import InMemoryApprovalScopeStore
from design_changeset import InMemoryChangeSetStore, validate_changeset_integrity_v2
from design_gateway_authorization import (
    ApprovalAdmission,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_impact import ImpactAnalyzer, ImpactError, InMemoryImpactAnalysisStore
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologyRegistry,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
)
from design_orchestrator.canonical_operations import (
    MOVE_V1,
    MVP_CANONICAL_OPERATIONS,
)
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ExternalOwnerPorts,
)
from design_orchestrator.operation_resolver import OperationResolver
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
    OperationFreshnessResult,
    StableRef,
)
from semantic_runtime import (
    ContractType,
    DirtyMap,
    FreshnessResolver,
    InMemorySnapshotRegistry,
    ReconstructionResult,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotKind,
    SnapshotSet,
    build_operation_contract,
    requirements_from_mappings,
)

_OWNER_DEPENDENCY_NAMES = (
    "snapshot_registry",
    "freshness_resolver",
    "workflow_artifact_store",
    "host_revision_observation",
    "canonical_operations",
    "impact_analyzer",
    "impact_store",
    "approval_scope_planner",
    "approval_scope_store",
    "changeset_builder",
    "changeset_store",
    "materialization_planner",
    "materialization_plan_store",
    "topology_registry",
    "topology_environment_id",
    "topology_revision",
    "execution_plan_store",
    "revision_barrier",
    "gateway_authorization",
    "gateway_authorization_store",
    "coordination_clock",
    "provider_binding_store",
    "saga_store",
    "execution_coordinator",
    "reconciliation_service",
    "convergence_verifier",
    "semantic_reconstruction",
    "preview_port",
    "approval_admission",
    "materialization_routing",
    "provider_execution_snapshot",
)

_TASK6_PROJECTION = SemanticProjectionRef(
    "projection-task6",
    "projection-hash-task6",
    "semantic-model-v1",
    "provider-set-task6",
    "mapping-profile-set-task6",
)
_TASK6_ENVIRONMENT = SemanticEnvironmentRef(
    "semantic-environment-task6",
    "semantic-environment-hash-task6",
)
_TASK6_OTHER_ENVIRONMENT = SemanticEnvironmentRef(
    "semantic-environment-task6-other",
    "semantic-environment-hash-task6-other",
)


@dataclass(frozen=True, slots=True)
class _Dependency:
    """Task 4/6 未接线的 owner 依赖只用于显式 composition shape 断言。"""

    name: str


class _SemanticReconstruction:
    """Task 4 compatibility boundary，只验证 resolve_host_context delegation。"""

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(ref_id=f"context:{task_id}", content_hash="c" * 64)


class _Task6SemanticReconstruction:
    """确定性的 semantic reconstruction IO boundary，不实现 Freshness 领域规则。"""

    def __init__(self) -> None:
        self.operation_ready = False
        self.calls: list[tuple[str, str]] = []

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(ref_id=f"context-request:{task_id}", content_hash="c" * 64)

    def load_context_inputs(self, context_ref: StableRef):
        from design_orchestrator.canonical_owner_ports import ContextFreshnessInputs

        assert context_ref.ref_id == "context-request:task-6"
        return ContextFreshnessInputs(
            task_id="task-6",
            project_id="project-task6",
            document_ref="DOC-TASK6",
            root_entities=("WALL-001",),
        )

    def reconstruct(self, contract, expected_host_revision: str):
        self.calls.append((contract.contract_type.value, expected_host_revision))
        if contract.contract_type is ContractType.OPERATION and not self.operation_ready:
            return AsyncOperationRef(
                kind=AsyncOperationKind.RECONSTRUCTION_JOB,
                owner="semantic-runtime",
                operation_id="reconstruction-task6",
            )
        return ReconstructionResult(
            document_ref=contract.coverage.document_ref,
            host_revision=expected_host_revision,
            coverage=contract.coverage,
            guarantees=contract.requirements,
            projection_ref=_TASK6_PROJECTION,
            semantic_environment_ref=_TASK6_ENVIRONMENT,
        )


class _Task6MultiRevisionSemanticReconstruction:
    """按调用方指定 Host revision 返回真实 FreshnessResolver 可消费的确定性重建事实。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve_host_context(self, task_id: str) -> StableRef:
        """返回 Task 6R.2 固定 context request ref，不拥有 freshness 判断。"""

        return StableRef(ref_id=f"context-request:{task_id}", content_hash="c" * 64)

    def load_context_inputs(self, context_ref: StableRef):
        """只提供 context freshness 的 owner 输入，不在边界内决定 freshness。"""

        from design_orchestrator.canonical_owner_ports import ContextFreshnessInputs

        assert context_ref.ref_id == "context-request:task-6"
        return ContextFreshnessInputs(
            task_id="task-6",
            project_id="project-task6",
            document_ref="DOC-TASK6",
            root_entities=("WALL-001",),
        )

    def reconstruct(self, contract, expected_host_revision: str):
        """把 expected revision 原样投影进 ReconstructionResult，领域校验仍归真实 resolver。"""

        self.calls.append((contract.contract_type.value, expected_host_revision))
        return ReconstructionResult(
            document_ref=contract.coverage.document_ref,
            host_revision=expected_host_revision,
            coverage=contract.coverage,
            guarantees=contract.requirements,
            projection_ref=_TASK6_PROJECTION,
            semantic_environment_ref=_TASK6_ENVIRONMENT,
        )


class _HostRevisionObservation:
    """Host revision 是环境事实；owner resolver 只消费该 observation。"""

    def current_revision(self, document_ref: str) -> str:
        assert document_ref == "DOC-TASK6"
        return "42"


class _MutableHostRevisionObservation:
    """Task 6R.2 测试只改变环境观测 revision，不改 freshness contract identity。"""

    def __init__(self, revision: str = "42") -> None:
        self.revision = revision

    def current_revision(self, document_ref: str) -> str:
        """返回当前测试 revision；文档身份必须仍是原 bound operation 文档。"""

        assert document_ref == "DOC-TASK6"
        return self.revision


class _CountingImpactAnalyzer:
    """外包真实 ImpactAnalyzer，只记录调用次数与真实 request，不复制 Impact 规则。"""

    def __init__(self) -> None:
        self._delegate = ImpactAnalyzer()
        self.requests: list[object] = []

    def analyze(self, request):
        """记录调用后交给真实 analyzer；负例可证明 adapter 在此前已经拒绝。"""

        self.requests.append(request)
        return self._delegate.analyze(request)


class _Preview:
    """Preview 是 presentation boundary，不拥有 ChangeSet truth。"""

    def preview(self, changeset_ref: StableRef) -> StableRef:
        return StableRef(
            ref_id=f"preview:{changeset_ref.ref_id}",
            content_hash="b" * 64,
        )


class _ApprovalAdmission:
    """Human/policy admission input 允许异步等待，但不实现 Gateway 语义。"""

    def request_approval(
        self,
        changeset_ref: StableRef,
    ) -> StableRef | AsyncOperationRef:
        return StableRef(
            ref_id=f"approval:{changeset_ref.ref_id}",
            content_hash="a" * 64,
        )


class _ArtifactStore:
    """测试用 workflow-local store；只保存 Orchestrator 自己拥有的 deterministic artifacts。"""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, object]] = {}
        self._counter = 0

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        self._counter += 1
        ref_id = f"artifact:{kind}:{self._counter}"
        self.values[ref_id] = (content_hash, value)
        return StableRef(ref_id=ref_id, content_hash=content_hash)

    def get(self, ref: StableRef) -> object:
        content_hash, value = self.values[ref.ref_id]
        if ref.content_hash != content_hash:
            raise KeyError(ref.ref_id)
        return value


class _LenientArtifactStore(_ArtifactStore):
    """只用于证明 adapter 自己校验 operation hash，而不是依赖具体 store 的额外严格性。"""

    def get(self, ref: StableRef) -> object:
        """按 ref_id 返回 owner artifact；exact hash invariant 由被测 adapter 单独承担。"""

        _, value = self.values[ref.ref_id]
        return value


def _adapter_kwargs() -> dict[str, object]:
    values = {name: _Dependency(name) for name in _OWNER_DEPENDENCY_NAMES}
    values["semantic_reconstruction"] = _SemanticReconstruction()
    values["preview_port"] = _Preview()
    values["approval_admission"] = _ApprovalAdmission()
    return values


def _task6_topology() -> MaterializationTopologySnapshot:
    draft = MaterializationTopologySnapshot(
        topology_environment_id="TOPOLOGY-TASK6",
        topology_revision=1,
        slots=(
            MaterializationSlot(
                materialization_slot_id="SLOT-TASK6",
                semantic_target_ref="WALL-001",
                required_host_type="revit",
                document_ref="DOC-TASK6",
                requirement=MaterializationRequirement.REQUIRED,
            ),
        ),
        topology_snapshot_hash="0" * 64,
    )
    return replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))


def _task6_adapter(
    *,
    changeset_builder: object | None = None,
    artifact_store: _ArtifactStore | None = None,
    overrides: dict[str, object] | None = None,
):
    from design_approval_scope import ApprovalScopePlanner
    from design_changeset import ChangeSetBuilder
    from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts

    workflow_artifact_store = artifact_store or _ArtifactStore()
    snapshot_registry = InMemorySnapshotRegistry()
    impact_store = InMemoryImpactAnalysisStore()
    approval_scope_store = InMemoryApprovalScopeStore()
    changeset_store = InMemoryChangeSetStore()
    semantic_reconstruction = _Task6SemanticReconstruction()
    topology_registry = MaterializationTopologyRegistry()
    topology_registry.register(_task6_topology())

    values = {name: _Dependency(name) for name in _OWNER_DEPENDENCY_NAMES}
    values.update(
        {
            "snapshot_registry": snapshot_registry,
            "freshness_resolver": FreshnessResolver(DirtyMap()),
            "workflow_artifact_store": workflow_artifact_store,
            "host_revision_observation": _HostRevisionObservation(),
            "canonical_operations": MVP_CANONICAL_OPERATIONS,
            "impact_analyzer": ImpactAnalyzer(),
            "impact_store": impact_store,
            "approval_scope_planner": ApprovalScopePlanner(),
            "approval_scope_store": approval_scope_store,
            "changeset_builder": changeset_builder or ChangeSetBuilder(),
            "changeset_store": changeset_store,
            "topology_registry": topology_registry,
            "topology_environment_id": "TOPOLOGY-TASK6",
            "topology_revision": 1,
            "semantic_reconstruction": semantic_reconstruction,
            "preview_port": _Preview(),
            "approval_admission": _ApprovalAdmission(),
        }
    )
    if overrides is not None:
        values.update(overrides)
    adapter = CanonicalWorkflowOwnerPorts(**values)
    return (
        adapter,
        workflow_artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
    )


def _task6_bound_operation(context_ref: StableRef):
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    return binder.bind(
        OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300, "unit": "mm"}},
        ),
        ParameterBindingContext(
            context_snapshot_id=context_ref.ref_id,
            context_snapshot_hash=context_ref.content_hash or "",
            document_ref="DOC-TASK6",
            semantic_environment_ref=_TASK6_ENVIRONMENT.environment_id,
            selection=("WALL-001",),
        ),
    )


def _task6_real_impact_case(
    *,
    overrides: dict[str, object] | None = None,
):
    (
        adapter,
        artifact_store,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
    ) = _task6_adapter(overrides=overrides)
    context_request_ref = adapter.resolve_host_context("task-6")
    context_ref = adapter.ensure_context_freshness(context_request_ref)
    assert isinstance(context_ref, StableRef)

    bound = _task6_bound_operation(context_ref)
    bound_ref = artifact_store.put(
        kind="bound_operation_proposal",
        value=bound,
        content_hash=workflow_artifact_content_hash(bound),
    )
    wait = adapter.ensure_operation_freshness(bound_ref)
    assert wait == AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-task6",
    )
    semantic_reconstruction.operation_ready = True
    freshness = adapter.ensure_operation_freshness(bound_ref)
    assert isinstance(freshness, OperationFreshnessResult)
    assert freshness.operation_ref == bound_ref
    impact_ref = adapter.analyze_impact(
        freshness.operation_ref,
        freshness.planning_snapshot_ref,
        freshness.snapshot_set_ref,
    )
    return (
        adapter,
        bound_ref,
        impact_ref,
        snapshot_registry,
        impact_store,
        approval_scope_store,
        changeset_store,
        semantic_reconstruction,
    )


def _task6_lineage_case():
    """组装可交错 revision 的真实 freshness/Impact owner，并保留 owner immutable history。"""

    revision = _MutableHostRevisionObservation("42")
    semantic_reconstruction = _Task6MultiRevisionSemanticReconstruction()
    counting_impact = _CountingImpactAnalyzer()
    artifact_store = _LenientArtifactStore()
    (
        adapter,
        _,
        snapshot_registry,
        _,
        _,
        _,
        _,
    ) = _task6_adapter(
        artifact_store=artifact_store,
        overrides={
            "host_revision_observation": revision,
            "semantic_reconstruction": semantic_reconstruction,
            "impact_analyzer": counting_impact,
        },
    )
    context_ref = adapter.ensure_context_freshness(adapter.resolve_host_context("task-6"))
    assert isinstance(context_ref, StableRef)
    bound = _task6_bound_operation(context_ref)
    bound_ref = artifact_store.put(
        kind="bound_operation_proposal",
        value=bound,
        content_hash=workflow_artifact_content_hash(bound),
    )
    return (
        adapter,
        artifact_store,
        snapshot_registry,
        counting_impact,
        revision,
        bound,
        bound_ref,
    )


def _require_freshness_result(adapter, bound_ref: StableRef) -> OperationFreshnessResult:
    """Task 6R.2 测试要求 real freshness 成功后显式返回 exact lineage envelope。"""

    result = adapter.ensure_operation_freshness(bound_ref)
    assert isinstance(result, OperationFreshnessResult)
    return result


def _operation_contract_for_bound(bound, *, document_ref: str | None = None, arguments=None):
    """复用 Semantic Runtime public helper 构造与 bound operation 对齐的 canonical contract。"""

    requirement_mappings = (
        *bound.planning_requirements.operation_freshness_requirements,
        *bound.planning_requirements.coverage_requirements,
        *bound.planning_requirements.assurance_requirements,
    )
    raw_targets = bound.arguments["targets"]
    return build_operation_contract(
        project_id="project-task6",
        document_ref=document_ref or bound.context_snapshot_ref.document_ref,
        canonical_operation=bound.operation.canonical_operation,
        targets=tuple(raw_targets),
        arguments=dict(bound.arguments) if arguments is None else arguments,
        requirements=requirements_from_mappings(requirement_mappings),
    )


def _put_planning_pair(
    snapshot_registry: InMemorySnapshotRegistry,
    contract,
    *,
    environment: SemanticEnvironmentRef,
    revision: str = "42",
) -> tuple[StableRef, StableRef]:
    """通过真实 FreshnessResolver 生成 owner-valid PlanningSnapshot/SnapshotSet 并登记。"""

    snapshot = FreshnessResolver(DirtyMap()).resolve(
        contract,
        expected_host_revision=revision,
        reconstruct=lambda owner_contract, expected_revision: ReconstructionResult(
            document_ref=owner_contract.coverage.document_ref,
            host_revision=expected_revision,
            coverage=owner_contract.coverage,
            guarantees=owner_contract.requirements,
            projection_ref=_TASK6_PROJECTION,
            semantic_environment_ref=environment,
        ),
    )
    snapshot_registry.put_snapshot(snapshot)
    snapshot_set = SnapshotSet.create((snapshot,))
    snapshot_registry.put_snapshot_set(snapshot_set)
    return (
        StableRef(snapshot.snapshot_id, snapshot.hash),
        StableRef(snapshot_set.snapshot_set_id, snapshot_set.hash),
    )


def _public_method_shape(
    cls: type[object],
) -> dict[str, tuple[tuple[str, inspect._ParameterKind], ...]]:
    """只比较既有 structural seam 的参数名与 kind，不把 annotation 文本当架构契约。"""

    return {
        name: tuple(
            (param.name, param.kind)
            for param in inspect.signature(member).parameters.values()
        )
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_canonical_owner_ports_preserves_external_owner_port_shape() -> None:
    """Production/reference adapter 必须完整实现现有 ExternalOwnerPorts，不新增 graph contract。"""

    from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts

    expected = _public_method_shape(ExternalOwnerPorts)
    actual = _public_method_shape(CanonicalWorkflowOwnerPorts)

    assert set(actual) == set(expected)
    for name, parameters in expected.items():
        assert actual[name] == parameters


def test_canonical_owner_ports_constructor_is_explicit_and_default_services_accepts_it() -> None:
    """Owner composition 必须显式列依赖，不能退化为 service locator 或 object bag。"""

    from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts

    signature = inspect.signature(CanonicalWorkflowOwnerPorts)
    assert tuple(signature.parameters) == _OWNER_DEPENDENCY_NAMES
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )

    adapter = CanonicalWorkflowOwnerPorts(**_adapter_kwargs())
    service = DefaultWorkflowServices(
        operation_resolver=OperationResolver((MOVE_V1,)),
        parameter_binder=ParameterBinder(
            MVP_CANONICAL_OPERATIONS,
            MVP_BINDING_RECIPES,
        ),
        artifact_store=_ArtifactStore(),
        external_owners=adapter,
    )

    assert service is not None


def test_canonical_owner_ports_keeps_post_planning_domain_calls_fail_closed() -> None:
    """Task 7 planning 已接真实 owner；revision barrier 及其后的领域调用仍须 fail closed。"""

    from design_orchestrator.canonical_owner_ports import (
        CanonicalOwnerPortNotWiredError,
        CanonicalWorkflowOwnerPorts,
    )

    adapter = CanonicalWorkflowOwnerPorts(**_adapter_kwargs())
    changeset_ref = StableRef("changeset-1", "1" * 64)
    execution_plan_ref = StableRef("execution-plan-1", "2" * 64)

    assert adapter.resolve_host_context("task-4") == StableRef(
        "context:task-4",
        "c" * 64,
    )
    assert adapter.preview(changeset_ref) == StableRef(
        "preview:changeset-1",
        "b" * 64,
    )
    with pytest.raises(CanonicalOwnerPortNotWiredError) as exc_info:
        adapter.check_revision_barrier(execution_plan_ref)
    assert exc_info.value.code == "CANONICAL_OWNER_PORT_NOT_WIRED"
    assert "check_revision_barrier" in str(exc_info.value)


def test_task6_real_freshness_wait_and_impact_use_owner_truth() -> None:
    """FreshnessResolver/ImpactAnalyzer 必须真实运行，workflow 只接收稳定引用。"""

    (
        _,
        _,
        impact_ref,
        snapshot_registry,
        impact_store,
        _,
        _,
        semantic_reconstruction,
    ) = _task6_real_impact_case()

    analysis = impact_store.get(impact_ref.ref_id)
    assert impact_ref.content_hash == analysis.analysis_fingerprint
    assert analysis.bound_operation_fingerprint
    assert semantic_reconstruction.calls == [
        (ContractType.CONTEXT.value, "42"),
        (ContractType.OPERATION.value, "42"),
        (ContractType.OPERATION.value, "42"),
    ]

    planning = snapshot_registry.get_snapshot(analysis.planning_snapshot_ref.snapshot_id)
    snapshot_set = snapshot_registry.get_snapshot_set(
        analysis.snapshot_set_ref.snapshot_set_id
    )
    assert planning.kind is SnapshotKind.PLANNING
    assert planning.hash == analysis.planning_snapshot_ref.snapshot_hash
    assert snapshot_set.hash == analysis.snapshot_set_ref.snapshot_set_hash


def test_task6_interleaved_revisions_keep_exact_freshness_lineage() -> None:
    """rev42/rev43 历史并存时，两次 Impact 必须各自消费 freshness 返回的 exact PS/PSS。"""

    (
        adapter,
        _,
        _,
        impact_analyzer,
        revision,
        _,
        bound_ref,
    ) = _task6_lineage_case()

    result_42 = _require_freshness_result(adapter, bound_ref)
    revision.revision = "43"
    result_43 = _require_freshness_result(adapter, bound_ref)

    assert result_42.planning_snapshot_ref != result_43.planning_snapshot_ref
    assert result_42.snapshot_set_ref != result_43.snapshot_set_ref

    adapter.analyze_impact(
        result_42.operation_ref,
        result_42.planning_snapshot_ref,
        result_42.snapshot_set_ref,
    )
    adapter.analyze_impact(
        result_43.operation_ref,
        result_43.planning_snapshot_ref,
        result_43.snapshot_set_ref,
    )

    assert [
        request.planning_snapshot_ref.snapshot_id
        for request in impact_analyzer.requests
    ] == [
        result_42.planning_snapshot_ref.ref_id,
        result_43.planning_snapshot_ref.ref_id,
    ]
    assert [
        request.snapshot_set_ref.snapshot_set_id
        for request in impact_analyzer.requests
    ] == [
        result_42.snapshot_set_ref.ref_id,
        result_43.snapshot_set_ref.ref_id,
    ]


@pytest.mark.parametrize(
    ("field_name", "replacement_hash"),
    [
        ("operation_ref", None),
        ("planning_snapshot_ref", None),
        ("snapshot_set_ref", None),
        ("operation_ref", "0" * 64),
        ("planning_snapshot_ref", "0" * 64),
        ("snapshot_set_ref", "0" * 64),
    ],
    ids=(
        "operation-missing-hash",
        "planning-missing-hash",
        "snapshot-set-missing-hash",
        "operation-wrong-hash",
        "planning-wrong-hash",
        "snapshot-set-wrong-hash",
    ),
)
def test_task6_exact_lineage_requires_all_hashes_before_impact(
    field_name: str,
    replacement_hash: str | None,
) -> None:
    """三个 exact refs 缺失或错误 hash 都必须在真实 ImpactAnalyzer 之前 fail closed。"""

    adapter, _, _, impact_analyzer, _, _, bound_ref = _task6_lineage_case()
    result = _require_freshness_result(adapter, bound_ref)
    refs = {
        "operation_ref": result.operation_ref,
        "planning_snapshot_ref": result.planning_snapshot_ref,
        "snapshot_set_ref": result.snapshot_set_ref,
    }
    original = refs[field_name]
    refs[field_name] = StableRef(original.ref_id, replacement_hash)

    with pytest.raises(ValueError):
        adapter.analyze_impact(
            refs["operation_ref"],
            refs["planning_snapshot_ref"],
            refs["snapshot_set_ref"],
        )
    assert impact_analyzer.requests == []


def test_task6_snapshot_set_membership_mismatch_fails_before_impact() -> None:
    """三个 refs 各自有效也不能把 rev42 planning snapshot 与 rev43 SnapshotSet 交叉绑定。"""

    adapter, _, _, impact_analyzer, revision, _, bound_ref = _task6_lineage_case()
    result_42 = _require_freshness_result(adapter, bound_ref)
    revision.revision = "43"
    result_43 = _require_freshness_result(adapter, bound_ref)

    with pytest.raises(ValueError):
        adapter.analyze_impact(
            result_42.operation_ref,
            result_42.planning_snapshot_ref,
            result_43.snapshot_set_ref,
        )
    assert impact_analyzer.requests == []


@pytest.mark.parametrize("mismatch_kind", ("document", "environment"))
def test_task6_document_or_environment_mismatch_fails_before_impact(
    mismatch_kind: str,
) -> None:
    """owner-valid planning pair 若与当前 bound operation 的文档/环境不一致必须拒绝。"""

    (
        adapter,
        _,
        snapshot_registry,
        impact_analyzer,
        _,
        bound,
        bound_ref,
    ) = _task6_lineage_case()
    exact = _require_freshness_result(adapter, bound_ref)
    if mismatch_kind == "environment":
        contract = _operation_contract_for_bound(bound)
        environment = _TASK6_OTHER_ENVIRONMENT
    else:
        contract = _operation_contract_for_bound(bound, document_ref="DOC-OTHER")
        environment = _TASK6_ENVIRONMENT
    planning_ref, snapshot_set_ref = _put_planning_pair(
        snapshot_registry,
        contract,
        environment=environment,
    )

    with pytest.raises(ValueError):
        adapter.analyze_impact(
            exact.operation_ref,
            planning_ref,
            snapshot_set_ref,
        )
    assert impact_analyzer.requests == []


def test_task6_freshness_contract_mismatch_fails_before_impact() -> None:
    """同文档同环境的有效 PS/PSS 若来自另一 operation contract 也不得进入 Impact。"""

    (
        adapter,
        _,
        snapshot_registry,
        impact_analyzer,
        _,
        bound,
        bound_ref,
    ) = _task6_lineage_case()
    exact = _require_freshness_result(adapter, bound_ref)
    other_arguments = dict(bound.arguments)
    other_arguments["thickness"] = {"value": 301, "unit": "mm"}
    other_contract = _operation_contract_for_bound(bound, arguments=other_arguments)
    planning_ref, snapshot_set_ref = _put_planning_pair(
        snapshot_registry,
        other_contract,
        environment=_TASK6_ENVIRONMENT,
    )

    with pytest.raises(ValueError):
        adapter.analyze_impact(
            exact.operation_ref,
            planning_ref,
            snapshot_set_ref,
        )
    assert impact_analyzer.requests == []


def test_task6_real_impact_scope_v2_and_changeset_v2_preserve_lineage() -> None:
    """Impact → Approval Scope V2 → ChangeSet V2 必须全部调用真实 owner 并绑定 owner hash。"""

    (
        adapter,
        bound_ref,
        impact_ref,
        _,
        impact_store,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case()

    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    analysis = impact_store.get(impact_ref.ref_id)
    definition = approval_scope_store.get_definition(
        changeset.approval_scope_definition_ref.scope_definition_id
    )
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")

    assert changeset_ref == StableRef(changeset.changeset_id, changeset.changeset_hash)
    assert changeset.task_id == "task-6"
    assert changeset.impact_analysis_fingerprint == analysis.analysis_fingerprint
    assert definition.topology_snapshot_hash == _task6_topology().topology_snapshot_hash
    assert boundary.changeset_hash == changeset.changeset_hash
    validate_changeset_integrity_v2(changeset, boundary)


def test_task6_missing_impact_ref_fails_closed_before_changeset_builder() -> None:
    """缺失 authoritative Impact ref 必须在 ChangeSet owner 执行前 fail closed。"""

    class _CountingChangeSetBuilder:
        def __init__(self) -> None:
            self.calls = 0

        def build(self, request):
            self.calls += 1
            raise AssertionError("ChangeSetBuilder must not run for a missing impact ref")

    builder = _CountingChangeSetBuilder()
    adapter, *_ = _task6_adapter(changeset_builder=builder)

    with pytest.raises(ImpactError) as exc_info:
        adapter.build_changeset(
            "task-6",
            StableRef("artifact:missing-bound-operation", "e" * 64),
            StableRef("IA-MISSING", "f" * 64),
        )
    assert exc_info.value.code == "IMPACT_ANALYSIS_REFERENCE_NOT_FOUND"
    assert builder.calls == 0


class _Task7ApprovalAdmission:
    """只提供 human/policy admission；不生成 Gateway approval truth。"""

    def __init__(self) -> None:
        self.admission: ApprovalAdmission | None = None
        self.calls: list[StableRef] = []

    def request_approval(self, changeset_ref: StableRef) -> ApprovalAdmission:
        self.calls.append(changeset_ref)
        if self.admission is None:
            raise AssertionError("Task 7 approval admission fixture is not configured")
        return self.admission


class _Task7Clock:
    """为 Gateway consume/issue/admit 提供确定性的共享 UTC 时钟。"""

    def now(self) -> datetime:
        return datetime.fromisoformat("2026-09-06T10:00:00+00:00")


def test_task7_request_approval_consumes_real_gateway_v2_admission() -> None:
    """Admission 只能作为输入；workflow approval_ref 必须来自真实 Gateway V2。"""

    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(gateway_store)
    admission_port = _Task7ApprovalAdmission()
    (
        adapter,
        bound_ref,
        impact_ref,
        _,
        _,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case(
        overrides={
            "gateway_authorization": gateway,
            "gateway_authorization_store": gateway_store,
            "coordination_clock": _Task7Clock(),
            "approval_admission": admission_port,
        }
    )
    changeset_ref = adapter.build_changeset("task-6", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")

    draft = ApprovalAdmission(
        admission_id="ADM-TASK7",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:task7-approver",
        policy_snapshot_hash="7" * 64,
        policy_allowed_operations=(changeset.root_operation.canonical_operation,),
        approved_at="2026-09-06T09:00:00Z",
        expires_at="2026-09-06T17:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission_port.admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )

    approval_ref = adapter.request_approval(changeset_ref)

    assert isinstance(approval_ref, StableRef)
    stored = gateway_store.get_approval(approval_ref.ref_id)
    assert stored is not None
    assert approval_ref.content_hash == stored.record.approval_hash
    assert stored.record.changeset_hash == changeset.changeset_hash
    assert stored.record.approved_scope_hash == boundary.scope_hash
    assert admission_port.calls == [changeset_ref]


def test_task7_seam_carries_authorization_store_clock_and_grant_lineage() -> None:
    """Task 7 必须显式携带授权 owner、时钟与 grant 所需的全部 StableRef。"""

    from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
    from design_orchestrator.workflow_services import WorkflowServices

    constructor = inspect.signature(CanonicalWorkflowOwnerPorts)
    assert "gateway_authorization_store" in constructor.parameters
    assert "coordination_clock" in constructor.parameters

    expected_grant_parameters = (
        "self",
        "execution_plan_ref",
        "approval_ref",
        "provider_binding_ref",
    )
    for owner_type in (
        WorkflowServices,
        ExternalOwnerPorts,
        DefaultWorkflowServices,
        CanonicalWorkflowOwnerPorts,
    ):
        parameters = tuple(
            inspect.signature(owner_type.issue_execution_grant).parameters
        )
        assert parameters == expected_grant_parameters


def test_canonical_owner_ports_import_smoke_blocks_database_and_test_imports() -> None:
    """隔离导入 composition module，不得隐式加载数据库实现或测试 helper。"""

    script = textwrap.dedent(
        """
        import builtins

        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise AssertionError(f"unexpected database import: {name}")
            if name == "tests" or name.startswith("tests."):
                raise AssertionError(f"unexpected test import: {name}")
            if "postgres_saga_store" in name:
                raise AssertionError(f"unexpected PostgreSQL implementation import: {name}")
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        import design_orchestrator.canonical_owner_ports
        """
    )

    # Step36 通过 pytest source path 运行 orchestrator tests，但不会把 orchestrator
    # 安装为 distribution；子进程不会继承 pytest 对父进程 sys.path 的注入。
    # 显式只加入 orchestrator/src，使本测试隔离验证“模块导入副作用”，而非 CI 安装布局。
    repo_root = Path(__file__).resolve().parents[2]
    orchestrator_src = repo_root / "platform" / "orchestrator" / "src"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(orchestrator_src)
        if not existing_pythonpath
        else os.pathsep.join((str(orchestrator_src), existing_pythonpath))
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr