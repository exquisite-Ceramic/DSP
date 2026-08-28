import ast
from pathlib import Path

PROVIDER_ROOT = Path("providers/semantics/ifc43/src/ifc43_semantic_provider")
PLATFORM_ROOTS = (
    Path("platform/semantic_service/src"),
    Path("platform/semantic_runtime/src"),
    Path("platform/semantic_mcp/src"),
)

FORBIDDEN_PROVIDER_IMPORTS = {
    "semantic_runtime",
    "semantic_mcp",
    "dsp_core_semantic_provider",
    "autocad_sidecar",
    "Autodesk",
    "Revit",
    "Tekla",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
}

FORBIDDEN_PROVIDER_TOKENS = (
    "A-WALL",
    "metro:",
    "wall.thickness.set.v1",
    "ElementId",
    "project_facts",
    "find_mappings",
)


def import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_provider_has_no_platform_host_metro_or_network_import_leakage():
    for path in PROVIDER_ROOT.glob("*.py"):
        assert import_roots(path).isdisjoint(FORBIDDEN_PROVIDER_IMPORTS), path


def test_platform_core_does_not_import_ifcopenshell_or_concrete_ifc_provider():
    forbidden = {"ifcopenshell", "ifc43_semantic_provider"}
    for root in PLATFORM_ROOTS:
        for path in root.rglob("*.py"):
            assert import_roots(path).isdisjoint(forbidden), path


def test_provider_contains_no_host_metro_action_or_projection_ownership_tokens():
    text = "\n".join(path.read_text() for path in PROVIDER_ROOT.glob("*.py"))
    for token in FORBIDDEN_PROVIDER_TOKENS:
        assert token not in text, token
