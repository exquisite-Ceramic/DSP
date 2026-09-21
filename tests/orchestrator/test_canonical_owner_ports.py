from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.default_workflow_services import (
    DefaultWorkflowServices,
    ExternalOwnerPorts,
)
from design_orchestrator.operation_resolver import OperationResolver
from design_orchestrator.parameter_binder import MVP_BINDING_RECIPES, ParameterBinder
from design_orchestrator.workflow_contracts import AsyncOperationRef, StableRef


_OWNER_DEPENDENCY_NAMES = (
    "snapshot_registry",
    "impact_analyzer",
    "impact_store",
    "approval_scope_planner",
    "approval_scope_store",
    "changeset_builder",
    "changeset_store",
    "materialization_planner",
    "materialization_plan_store",
    "topology_registry",
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


@dataclass(frozen=True, slots=True)
class _Dependency:
    """Task 4 只验证显式 composition shape，不在 skeleton 测试里复制 owner 语义。"""

    name: str


class _SemanticReconstruction:
    """真实语义重建的环境边界在 Task 4 只负责 Host context ref。"""

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(ref_id=f"context:{task_id}", content_hash="c" * 64)


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
    """DefaultWorkflowServices 构造测试用的最小 workflow-local store。"""

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        return StableRef(ref_id=f"artifact:{kind}", content_hash=content_hash)

    def get(self, ref: StableRef) -> object:
        raise KeyError(ref.ref_id)


def _adapter_kwargs() -> dict[str, object]:
    values = {name: _Dependency(name) for name in _OWNER_DEPENDENCY_NAMES}
    values["semantic_reconstruction"] = _SemanticReconstruction()
    values["preview_port"] = _Preview()
    values["approval_admission"] = _ApprovalAdmission()
    return values


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


def test_canonical_owner_ports_delegates_only_narrow_task4_boundaries() -> None:
    """Skeleton 只委托 environment/presentation seams，其余领域 owner wiring 留给后续 Tasks。"""

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
        adapter.analyze_impact(StableRef("operation-1", "2" * 64))
    assert exc_info.value.code == "CANONICAL_OWNER_PORT_NOT_WIRED"
    assert "analyze_impact" in str(exc_info.value)


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
