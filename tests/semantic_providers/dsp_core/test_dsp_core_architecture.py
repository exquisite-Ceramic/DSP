import ast
from pathlib import Path

PROVIDER_ROOT = Path("providers/semantics/dsp_core/src/dsp_core_semantic_provider")

FORBIDDEN_IMPORT_ROOTS = {
    "semantic_runtime",
    "semantic_mcp",
    "autocad_sidecar",
    "Autodesk",
    "Revit",
    "Tekla",
}

FORBIDDEN_DOMAIN_TOKENS = (
    "A-WALL",
    "AutoCAD",
    "Revit",
    "Tekla",
    "Autodesk",
    "ifc:",
    "metro:",
    "Ifc43Provider",
    "MetroProvider",
    "ElementId",
)


def test_production_provider_has_no_forbidden_import_dependency():
    for path in PROVIDER_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".", 1)[0]}
            else:
                continue
            assert roots.isdisjoint(FORBIDDEN_IMPORT_ROOTS), (path, roots)


def test_production_provider_has_no_host_ifc_metro_execution_leakage():
    text = "\n".join(path.read_text() for path in PROVIDER_ROOT.glob("*.py"))
    for token in FORBIDDEN_DOMAIN_TOKENS:
        assert token not in text, token
