"""Task12 RED: freeze Step33 architecture and exact CI/workflow boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

_PACKAGE = Path("platform/execution_reconciliation/src/design_execution_reconciliation")
_WORKFLOW = Path(".github/workflows/step33-execution-reconciliation.yml")

_FROZEN_PATHS = [
    ".github/workflows/step33-execution-reconciliation.yml",
    "docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md",
    "docs/superpowers/plans/2026-08-30-step33-execution-reconciliation.md",
    "platform/execution_reconciliation/**",
    "tests/execution_reconciliation/**",
    "platform/execution_planning/**",
    "tests/execution_planning/**",
    "pyproject.toml",
]

_FORBIDDEN_PRIVATE_IMPORTS = {
    "design_approval_scope.hashing",
    "design_changeset.builder",
    "design_execution_planning.planner",
    "design_gateway_authorization.store",
    "design_gateway_authorization.service",
    "semantic_runtime.freshness",
}
_FORBIDDEN_IMPORT_ROOTS = {
    "autocad_sidecar",
    "psycopg",
    "asyncpg",
    "redis",
    "boto3",
    "DynamoDB",
}
_FORBIDDEN_PRODUCT_TERMS = ("autocad", "revit", "tekla")
_FORBIDDEN_DISPATCH_CALLS = {"undo", "rollback", "begintransaction", "transaction"}
_REQUIRED_VALIDATORS = {
    "saga.py": {
        "validate_approval_scope_boundary",
        "validate_changeset_integrity",
        "validate_execution_plan_integrity",
    },
    "scope_comparator.py": {
        "validate_approval_scope_boundary",
        "validate_execution_slice_integrity",
    },
    "verifier.py": {
        "validate_approval_scope_boundary",
        "validate_changeset_integrity",
    },
}

_STEP32_EDITABLE_STACK = (
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
    "-e platform/execution_reconciliation",
)
_REQUIRED_TEST_COMMANDS = (
    "pytest -q tests/approval_scope/test_step28_integrity.py",
    "pytest -q tests/changeset/test_step29_integrity.py",
    "pytest -q tests/execution_planning/test_step30_integrity.py",
    "pytest -q tests/execution_reconciliation",
    "pytest -q tests/approval_scope",
    "pytest -q tests/changeset",
    "pytest -q tests/execution_planning",
    "pytest -q tests/provider_binding",
    "pytest -q tests/gateway_authorization",
    "pytest -q --import-mode=importlib",
)
_RUFF_TARGETS = (
    "platform/execution_planning/src/design_execution_planning",
    "platform/execution_reconciliation/src/design_execution_reconciliation",
    "tests/execution_planning",
    "tests/execution_reconciliation",
)


def _python_files() -> tuple[Path, ...]:
    return tuple(sorted(_PACKAGE.glob("*.py")))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _workflow() -> dict:
    return yaml.load(_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _workflow_runs() -> str:
    workflow = _workflow()
    jobs = workflow["jobs"]
    return "\n".join(
        step.get("run", "")
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    )


def test_step33_production_has_no_host_product_private_storage_or_native_dispatch_coupling() -> None:
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        tree = _tree(path)
        modules = _imported_modules(tree)
        imported_names = _imported_names(tree)

        assert not any(
            module in _FORBIDDEN_PRIVATE_IMPORTS
            or any(module.startswith(f"{private}.") for private in _FORBIDDEN_PRIVATE_IMPORTS)
            for module in modules
        ), path
        assert not any(
            module.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS for module in modules
        ), path
        assert "HostCommand" not in imported_names, path
        assert not any(term in source.lower() for term in _FORBIDDEN_PRODUCT_TERMS), path

        calls = {_call_name(node).lower() for node in ast.walk(tree) if isinstance(node, ast.Call)}
        assert "datetime.now" not in calls, path
        assert "datetime.utcnow" not in calls, path
        assert "time.time" not in calls, path
        assert not any(
            call.rsplit(".", 1)[-1] in _FORBIDDEN_DISPATCH_CALLS for call in calls
        ), path


def test_scope_comparator_never_uses_native_type_for_authorization() -> None:
    tree = _tree(_PACKAGE / "scope_comparator.py")
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "native_type" not in attributes


def test_step33_uses_public_upstream_validators_at_ownership_boundaries() -> None:
    for filename, expected in _REQUIRED_VALIDATORS.items():
        imported = _imported_names(_tree(_PACKAGE / filename))
        assert expected <= imported, (filename, expected - imported)


def test_workflow_paths_are_exactly_the_frozen_step33_boundary() -> None:
    workflow = _workflow()
    triggers = workflow["on"]
    assert triggers["push"]["paths"] == _FROZEN_PATHS
    assert triggers["pull_request"]["paths"] == _FROZEN_PATHS


def test_workflow_has_step33_pr_diff_gate() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "github.head_ref == 'feat/step33-execution-reconciliation'" in text
    assert "git diff --name-only" in text
    assert "cef76e111f74d10f063eedfebc7efc0d805caefa" not in text


def test_workflow_installs_step32_stack_plus_step33_and_runs_final_matrix() -> None:
    runs = _workflow_runs()
    for editable in _STEP32_EDITABLE_STACK:
        assert editable in runs
    for command in _REQUIRED_TEST_COMMANDS:
        assert command in runs
    assert "ruff check" in runs
    for target in _RUFF_TARGETS:
        assert target in runs
