"""Architecture and final-verification guards for Step32 Gateway authorization."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOT = ROOT / "platform/gateway_authorization/src/design_gateway_authorization"
SERVICE_PATH = PRODUCTION_ROOT / "service.py"
WORKFLOW_PATH = ROOT / ".github/workflows/step32-gateway-authorization.yml"

FORBIDDEN_SYMBOLS = {
    "AutoCAD",
    "AUTOCAD",
    "autocad_sidecar",
    "Revit",
    "REVIT",
    "Tekla",
    "TEKLA",
    "HostCommand",
    "ActualDelta",
    "ScopeComparator",
    "Saga",
    "psycopg",
    "asyncpg",
    "redis",
    "boto3",
    "DynamoDB",
}
FORBIDDEN_CONSTANTS = {
    "AutoCAD",
    "AUTOCAD",
    "autocad_sidecar",
    "Revit",
    "REVIT",
    "Tekla",
    "TEKLA",
    "HostCommand",
    "ActualDelta",
    "ScopeComparator",
    "Saga",
    "psycopg",
    "asyncpg",
    "redis",
    "boto3",
    "DynamoDB",
}
PRIVATE_IMPORT_PREFIXES = (
    "design_approval_scope.hashing",
    "design_changeset.builder",
    "design_execution_planning.planner",
    "design_provider_binding.hashing",
)
PUBLIC_VALIDATOR_IMPORTS = {
    ("design_approval_scope", "validate_approval_scope_boundary"),
    ("design_changeset", "validate_changeset_integrity"),
    ("design_execution_planning", "validate_execution_slice_integrity"),
    ("design_provider_binding", "validate_provider_binding_set"),
}
FROZEN_PATH_BOUNDARY = {
    ".github/workflows/step32-gateway-authorization.yml",
    "docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md",
    "docs/superpowers/plans/2026-08-30-step32-gateway-authorization.md",
    "platform/gateway_authorization/**",
    "tests/gateway_authorization/**",
    "platform/approval_scope/**",
    "tests/approval_scope/**",
    "platform/changeset/**",
    "tests/changeset/**",
    "platform/execution_planning/**",
    "tests/execution_planning/**",
    "pyproject.toml",
}
FINAL_TEST_COMMANDS = (
    "pytest -q tests/approval_scope/test_step28_integrity.py",
    "pytest -q tests/changeset/test_step29_integrity.py",
    "pytest -q tests/execution_planning/test_step30_integrity.py",
    "pytest -q tests/gateway_authorization",
    "pytest -q tests/approval_scope",
    "pytest -q tests/changeset",
    "pytest -q tests/execution_planning",
    "pytest -q tests/provider_binding",
    "pytest -q --import-mode=importlib",
)
STEP31_INSTALL_EDITABLES = (
    "-e contracts/python",
    "-e hosts/autocad/sidecar",
    "-e platform/changeset",
    "-e platform/execution_planning",
    "-e platform/provider_binding",
    "-e platform/semantic_runtime",
    "-e platform/semantic_service",
    "-e platform/semantic_mcp",
    "-e providers/semantics/dsp_core",
    "-e providers/semantics/ifc43",
    "-e providers/semantics/metro_v32",
    "-e providers/semantics/enterprise_mapping",
    "-e platform/gateway_authorization",
)
FINAL_RUFF_TARGETS = (
    "platform/approval_scope/src/design_approval_scope",
    "platform/changeset/src/design_changeset",
    "platform/execution_planning/src/design_execution_planning",
    "platform/gateway_authorization/src/design_gateway_authorization",
    "tests/approval_scope",
    "tests/changeset",
    "tests/execution_planning",
    "tests/gateway_authorization",
)


def _production_trees():
    for path in sorted(PRODUCTION_ROOT.glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_parts(node: ast.AST) -> set[str]:
    parts: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts.update(alias.name.split("."))
    elif isinstance(node, ast.ImportFrom) and node.module:
        parts.update(node.module.split("."))
    return parts


def test_production_has_no_host_product_or_database_vendor_coupling():
    violations: list[str] = []
    for path, tree in _production_trees():
        for node in ast.walk(tree):
            imported = _import_parts(node)
            for marker in sorted(imported & FORBIDDEN_SYMBOLS):
                violations.append(f"{path.name}: import {marker}")
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_SYMBOLS:
                violations.append(f"{path.name}: name {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_SYMBOLS:
                violations.append(f"{path.name}: attribute {node.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in FORBIDDEN_CONSTANTS
            ):
                violations.append(f"{path.name}: constant {node.value}")

    assert violations == []


def test_production_has_no_direct_wall_clock_reads():
    violations: list[str] = []
    for path, tree in _production_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            if (
                isinstance(value, ast.Name)
                and value.id == "datetime"
                and node.func.attr in {"now", "utcnow"}
            ):
                violations.append(f"{path.name}: datetime.{node.func.attr}")
            if (
                isinstance(value, ast.Name)
                and value.id == "time"
                and node.func.attr == "time"
            ):
                violations.append(f"{path.name}: time.time")

    assert violations == []


def test_service_consumes_only_public_owner_integrity_validators():
    tree = ast.parse(
        SERVICE_PATH.read_text(encoding="utf-8"),
        filename=str(SERVICE_PATH),
    )
    imports: set[tuple[str, str]] = set()
    private_imports: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.module.startswith(PRIVATE_IMPORT_PREFIXES):
            private_imports.append(node.module)
        for alias in node.names:
            imports.add((node.module, alias.name))

    assert PUBLIC_VALIDATOR_IMPORTS <= imports
    assert private_imports == []


def test_workflow_path_filters_match_frozen_implementation_boundary():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    quoted_list_items = set(
        re.findall(r'^\s+- "([^"]+)"\s*$', text, flags=re.MULTILINE)
    )
    assert quoted_list_items == FROZEN_PATH_BOUNDARY


def test_workflow_installs_step31_stack_plus_gateway():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for editable in STEP31_INSTALL_EDITABLES:
        assert editable in text
    assert "pytest pytest-asyncio jsonschema PyYAML==6.0.3 ruff" in text


def test_workflow_runs_frozen_final_verification_matrix():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for command in FINAL_TEST_COMMANDS:
        assert command in text

    assert "ruff check" in text
    ruff_block = text.split("ruff check", maxsplit=1)[1]
    for target in FINAL_RUFF_TARGETS:
        assert target in ruff_block
