from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py"
REAL_OWNER_E2E = ROOT / "tests/orchestrator/test_real_owner_workflow_end_to_end.py"
CENSUS = ROOT / "docs/superpowers/reviews/2026-09-20-real-owner-e2e-workflow-census.md"

# Task 5 只允许 production/reference adapter 从 owner 的 package root 消费公开契约。
# 这些 root 来自 Task 1 frozen census；子模块路径一律视为实现细节，不能成为新 consumer。
OWNER_ROOTS = {
    "semantic_runtime",
    "design_impact",
    "design_approval_scope",
    "design_changeset",
    "design_materialization_topology",
    "design_materialization_planning",
    "design_execution_planning",
    "design_gateway_authorization",
    "design_provider_binding",
    "design_execution_reconciliation",
    "design_execution_coordination",
    "design_convergence",
}

# Census 冻结在 Task 1 exact head；Task 2/3 按已批准 Plan 新增了这些 package-root public
# surfaces。这里只登记已经完成并通过 exact-head gate 的新增 API，不预先为后续 Task 开口子。
POST_CENSUS_PUBLIC_SURFACE = {
    ("semantic_runtime", "RevisionBarrier"),
    ("semantic_runtime", "HostRevisionObservationPort"),
    ("semantic_runtime", "InMemorySnapshotRegistry"),
    ("design_impact", "InMemoryImpactAnalysisStore"),
    ("design_approval_scope", "InMemoryApprovalScopeStore"),
    ("design_changeset", "InMemoryChangeSetStore"),
    ("design_materialization_planning", "InMemoryMaterializationPlanStore"),
    ("design_execution_planning", "InMemoryExecutionPlanV2Store"),
    ("design_provider_binding", "InMemoryProviderBindingSetV2Store"),
}

# 这些名字属于 authoritative owners 的确定性算法/状态机实现。Adapter 可以导入并调用
# package-root public symbol，但不能在本地重新定义同名 evaluator/builder/coordinator。
OWNER_SEMANTIC_IMPLEMENTATION_NAMES = {
    "ChangeSetBuilder",
    "GatewayAuthorizationService",
    "GatewayAuthorizationServiceV2",
    "MaterializedExecutionSagaCoordinator",
    "ExecutionReconciliationService",
    "ExecutionReconciliationServiceV2",
    "CrossHostConvergenceVerifier",
    "plan_materialized_execution",
    "resolve_provider_bindings_v2",
    "validate_changeset_integrity_v2",
    "validate_execution_plan_v2",
}

_PUBLIC_SURFACE_PATTERN = re.compile(r"`([A-Za-z0-9_.]+):([A-Za-z0-9_]+)`")


@pytest.mark.parametrize(
    ("source", "expected_fragment"),
    (
        (
            "from design_gateway_authorization import GatewayAuthorizationService\n",
            "legacy-or-unapproved-symbol",
        ),
        (
            "from design_gateway_authorization.v2 import GatewayAuthorizationServiceV2\n",
            "owner-private-module",
        ),
        (
            "from design_execution_reconciliation.postgres_saga_store import "
            "ExecutionSagaPostgresStore\n",
            "postgres-implementation",
        ),
        (
            "from tests.orchestrator.test_workflow_end_to_end import _ScenarioOwners\n",
            "test-or-scenario-dependency",
        ),
        (
            "from autocad_sidecar.execution.readiness import AutoCADReadinessPort\n",
            "host-implementation",
        ),
        (
            "class GatewayAuthorizationServiceV2:\n    pass\n",
            "duplicated-owner-semantics",
        ),
    ),
)
def test_boundary_guard_rejects_forbidden_consumers(
    source: str,
    expected_fragment: str,
) -> None:
    """Guard 本身必须能检测 V1/private/Postgres/tests/Host/语义复制。"""

    violations = _boundary_violations(source)
    assert any(expected_fragment in violation for violation in violations), violations


def test_boundary_guard_accepts_approved_package_root_v2_symbol() -> None:
    """混合 V1/V2 package 必须按 module:symbol 放行 approved V2，而非整包放行。"""

    source = (
        "from design_gateway_authorization import "
        "GatewayAuthorizationServiceV2, ExecutionGrantV2\n"
    )
    assert _boundary_violations(source) == ()


def test_production_adapter_obeys_real_owner_boundary() -> None:
    """Production/reference adapter 只能消费 census-approved public owner surface。"""

    assert _boundary_violations(ADAPTER.read_text(encoding="utf-8")) == ()


def test_impact_path_does_not_reverse_lookup_freshness_lineage() -> None:
    """Impact canonical success path 必须只消费 exact refs，禁止按 contract/member 反查。"""

    source = ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    adapter_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CanonicalWorkflowOwnerPorts"
    )
    analyze_method = next(
        node
        for node in adapter_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "analyze_impact"
    )
    method_source = ast.get_source_segment(source, analyze_method)
    assert method_source is not None
    assert "get_snapshot_for_freshness_contract" not in method_source
    assert "get_snapshot_set_for_member" not in method_source


def test_scenario_owner_is_forbidden_from_real_owner_surfaces() -> None:
    """Adapter 与未来 real-owner E2E 都不得导入、构造或定义 `_ScenarioOwners`。"""

    targets = [ADAPTER]
    if REAL_OWNER_E2E.exists():
        targets.append(REAL_OWNER_E2E)

    for path in targets:
        source = path.read_text(encoding="utf-8")
        assert not any(
            "test-or-scenario-dependency" in violation
            for violation in _boundary_violations(source)
        ), path


def _census_public_surface() -> dict[str, set[str]]:
    """从 Task 1 machine-readable census 派生 package-root module:symbol allowlist。"""

    approved = {root: set() for root in OWNER_ROOTS}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 6 or cells[0] in {"area", "---"}:
            continue
        for module, symbol in _PUBLIC_SURFACE_PATTERN.findall(cells[1]):
            if module in OWNER_ROOTS:
                approved[module].add(symbol)

    for module, symbol in POST_CENSUS_PUBLIC_SURFACE:
        approved[module].add(symbol)
    return approved


def _is_postgres_implementation(module: str) -> bool:
    """数据库 driver 与 owner-private PostgreSQL adapter 都不能成为 composition import。"""

    return (
        module == "psycopg"
        or module.startswith("psycopg.")
        or any(part.startswith("postgres") for part in module.split("."))
    )


def _is_test_or_scenario_module(module: str) -> bool:
    return module == "tests" or module.startswith("tests.")


def _is_host_implementation(module: str) -> bool:
    return (
        module == "autocad_sidecar"
        or module.startswith("autocad_sidecar.")
        or module == "revit_sidecar"
        or module.startswith("revit_sidecar.")
        or module.startswith("hosts.autocad")
        or module.startswith("hosts.revit")
    )


def _module_violation(module: str) -> str | None:
    """先判定绝对禁止的依赖，再判断 owner package-root/private boundary。"""

    if _is_test_or_scenario_module(module):
        return f"test-or-scenario-dependency:{module}"
    if _is_postgres_implementation(module):
        return f"postgres-implementation:{module}"
    if _is_host_implementation(module):
        return f"host-implementation:{module}"

    root = module.split(".", 1)[0]
    if root in OWNER_ROOTS and module != root:
        return f"owner-private-module:{module}"
    return None


def _boundary_violations(source: str) -> tuple[str, ...]:
    """返回 adapter source 对 frozen owner/public-surface boundary 的全部违规。"""

    tree = ast.parse(source)
    approved = _census_public_surface()
    violations: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            module_problem = _module_violation(module)
            if module_problem is not None:
                violations.add(module_problem)
                continue

            root = module.split(".", 1)[0]
            if root in OWNER_ROOTS:
                for alias in node.names:
                    if alias.name == "*" or alias.name not in approved[root]:
                        violations.add(
                            f"legacy-or-unapproved-symbol:{module}:{alias.name}"
                        )

            if any(alias.name == "_ScenarioOwners" for alias in node.names):
                violations.add("test-or-scenario-dependency:_ScenarioOwners")

        elif isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                module_problem = _module_violation(module)
                if module_problem is not None:
                    violations.add(module_problem)
                    continue

                root = module.split(".", 1)[0]
                if root in OWNER_ROOTS:
                    # `import owner` 会绕过 module:symbol whitelist，因此 production adapter
                    # 必须使用 `from owner import ApprovedSymbol` 的显式消费形式。
                    violations.add(f"unscoped-owner-import:{module}")

        if isinstance(node, ast.Name) and node.id == "_ScenarioOwners":
            violations.add("test-or-scenario-dependency:_ScenarioOwners")

    # 只检查本模块实际定义的 class/function 名，不把合法 import 的 owner symbol 误判为复制。
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in OWNER_SEMANTIC_IMPLEMENTATION_NAMES:
                violations.add(f"duplicated-owner-semantics:{node.name}")
            if node.name == "_ScenarioOwners":
                violations.add("test-or-scenario-dependency:_ScenarioOwners")

    return tuple(sorted(violations))
