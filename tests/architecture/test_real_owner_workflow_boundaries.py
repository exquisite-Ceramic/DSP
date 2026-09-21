from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py"
REAL_OWNER_E2E = ROOT / "tests/orchestrator/test_real_owner_workflow_end_to_end.py"


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


def test_scenario_owner_is_forbidden_from_real_owner_surfaces() -> None:
    """Adapter 与未来 real-owner E2E 都不得导入、构造或定义 `_ScenarioOwners`。"""

    targets = [ADAPTER]
    if REAL_OWNER_E2E.exists():
        targets.append(REAL_OWNER_E2E)

    for path in targets:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        identifiers = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        defined_classes = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        }
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "_ScenarioOwners" not in identifiers | defined_classes | imported_names


def _boundary_violations(source: str) -> tuple[str, ...]:
    """Task 5 RED：下一步实现 AST boundary detector，再让 mutation tests 转绿。"""

    raise NotImplementedError("Task 5 RED: real-owner boundary detector is not implemented")
