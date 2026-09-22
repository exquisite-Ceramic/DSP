from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from design_approval_scope import InMemoryApprovalScopeStore
from design_changeset import InMemoryChangeSetStore, validate_changeset_integrity_v2
from design_impact import ImpactAnalyzer, InMemoryImpactAnalysisStore, ImpactError
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
    SET_WALL_THICKNESS_V1,
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


class _HostRevisionObservation:
    """Host revision 是环境事实；owner resolver 只消费该 observation。"""

    def current_revision(self, document_ref: str) -> str:
        assert document_ref == "DOC-TASK6"
        return "42"


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


def _task6_adapter(*, changeset_builder: object | None = None):
    from design_approval_scope import ApprovalScopePlanner
    from design_changeset import ChangeSetBuilder
    from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts

    artifact_store = _ArtifactStore()
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
            "workflow_artifact_store": artifact_store,
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
    adapter = CanonicalWorkflowOwnerPorts(**values)
    return (
        adapter,
        artifact_store,
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


def _task6_real_impact_case():
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
    wait = adapter.ensure_operation_freshness(bound_ref)
    assert wait == AsyncOperationRef(
        kind=AsyncOperationKind.RECONSTRUCTION_JOB,
        owner="semantic-runtime",
        operation_id="reconstruction-task6",
    )
    semantic_reconstruction.operation_ready = True
    assert adapter.ensure_operation_freshness(bound_ref) == bound_ref
    impact_ref = adapter.analyze_impact(bound_ref)
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


def test_canonical_owner_ports_keeps_task7_plus_domain_calls_fail_closed() -> None:
    """Task 6 接 freshness/impact/changeset；planning 之后的领域 owner 仍须 fail closed。"""

    from design_orchestrator.canonical_owner_ports import (
        CanonicalOwnerPortNotWiredError,
        CanonicalWorkflowOwnerPorts,
    )

    adapter = CanonicalWorkflowOwnerPorts(**_adapter_kwargs())
    changeset_ref = StableRef("changeset-1", "1" * 64)

    assert adapter.resolve_host_context("task-4") == StableRef(
        "context:task-4",
        "c" * 64,
    )
    assert adapter.preview(changeset_ref) == StableRef(
        "preview:changeset-1",
        "b" * 64,
    )
    assert adapter.request_approval(changeset_ref) == StableRef(
        "approval:changeset-1",
        "a" * 64,
    )

    with pytest.raises(CanonicalOwnerPortNotWiredError) as exc_info:
        adapter.plan_execution(
            StableRef("changeset-1", "1" * 64),
            StableRef("approval-1", "2" * 64),
        )
    assert exc_info.value.code == "CANONICAL_OWNER_PORT_NOT_WIRED"
    assert "plan_execution" in str(exc_info.value)


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


def test_task6_real_impact_scope_v2_and_changeset_v2_preserve_lineage() -> None:
    """Impact → Approval Scope V2 → ChangeSet V2 必须全部调用真实 owner 并绑定 owner hash。"""

    (
        adapter,
        _,
        impact_ref,
        _,
        impact_store,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case()

    changeset_ref = adapter.build_changeset(impact_ref)
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
        adapter.build_changeset(StableRef("IA-MISSING", "f" * 64))
    assert exc_info.value.code == "IMPACT_ANALYSIS_REFERENCE_NOT_FOUND"
    assert builder.calls == 0


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
