from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = ROOT / "tests"


def _is_forbidden_module(module: str) -> bool:
    parts = module.split(".")
    return "conftest" in parts or any(part.startswith("test_") for part in parts)


def _forbidden_imports() -> list[str]:
    violations: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_forbidden_module(module):
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: from {module} import ..."
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_forbidden_module(alias.name):
                        violations.append(
                            f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: import {alias.name}"
                        )
    return violations


def test_reusable_test_support_never_imports_test_modules_or_conftest() -> None:
    violations = _forbidden_imports()
    assert not violations, "forbidden reusable-test imports:\n" + "\n".join(violations)
