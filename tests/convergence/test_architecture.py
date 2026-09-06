from __future__ import annotations

import ast
from pathlib import Path


_PACKAGE_ROOT = Path("platform/convergence/src/design_convergence")
_FORBIDDEN_NATIVE_TERMS = (
    "AutoCAD",
    "LWPOLYLINE",
    "ConstantWidth",
    "Handle",
    "Autodesk.Revit",
    "ElementId",
    "UniqueId",
    "WallType",
)


def _production_sources() -> tuple[Path, ...]:
    return tuple(sorted(_PACKAGE_ROOT.glob("*.py")))


def test_convergence_core_contains_no_host_native_vocabulary() -> None:
    joined = "\n".join(path.read_text(encoding="utf-8") for path in _production_sources())

    for term in _FORBIDDEN_NATIVE_TERMS:
        assert term not in joined
    assert "304.8" not in joined
    assert "0.00328084" not in joined


def test_convergence_core_imports_no_host_specific_packages() -> None:
    forbidden_prefixes = (
        "hosts",
        "autocad",
        "revit",
        "Autodesk",
    )

    for path in _production_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith(forbidden_prefixes)
            elif isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith(forbidden_prefixes)
                    for alias in node.names
                )


def test_convergence_verifier_has_no_tolerance_or_unit_conversion_branch() -> None:
    verifier_path = _PACKAGE_ROOT / "verifier.py"
    if not verifier_path.exists():
        return

    source = verifier_path.read_text(encoding="utf-8")
    assert "tolerance" not in source.lower()
    assert "convert" not in source.lower()
    assert "feet" not in source.lower()
    assert "foot" not in source.lower()
