import ast
from pathlib import Path

import enterprise_mapping_provider
import semantic_service


ROOT = Path(__file__).resolve().parents[3]


def import_roots(package_dir: Path):
    found = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(alias.name.split(".", 1)[0].lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module.split(".", 1)[0].lower())
    return found


def source_text(package_dir: Path):
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package_dir.rglob("*.py"))
    )


def test_enterprise_provider_has_no_host_d5_mcp_or_concrete_semantic_provider_imports():
    package = Path(enterprise_mapping_provider.__file__).resolve().parent
    forbidden = {
        "autocad_sidecar",
        "autodesk",
        "revit",
        "tekla",
        "semantic_runtime",
        "semantic_mcp",
        "metro_semantic_provider",
        "ifc43_semantic_provider",
        "ifcopenshell",
    }
    found = [root for root in import_roots(package) if root in forbidden]
    assert found == []


def test_enterprise_mapping_tokens_live_in_machine_data_not_python_product_branches():
    package = Path(enterprise_mapping_provider.__file__).resolve().parent
    python_source = source_text(package)
    assert "A-WALL" not in python_source
    assert "autocad.layer" not in python_source
    assert "ifc:IfcWall" not in python_source

    machine_source = (package / "data" / "enterprise_mappings_v1.yaml").read_text(encoding="utf-8")
    assert "A-WALL" in machine_source
    assert "autocad.layer" in machine_source
    assert "ifc:IfcWall" in machine_source


def test_semantic_service_has_no_enterprise_or_autocad_mapping_knowledge():
    package = Path(semantic_service.__file__).resolve().parent
    source = source_text(package)
    forbidden = (
        "A-WALL",
        "autocad.layer",
        "ifc:IfcWall",
        "enterprise_mapping_provider",
        "autocad_sidecar",
        "semantic_runtime",
        "semantic_mcp",
    )
    assert [token for token in forbidden if token in source] == []
    assert not hasattr(semantic_service, "NormalizedDesignFactBatch")


def test_semantic_mcp_does_not_expose_project_facts_endpoint_in_step20():
    package = ROOT / "platform" / "semantic_mcp" / "src"
    source = source_text(package)
    assert "semantic.project_facts" not in source
    assert "project_facts" not in source


def test_enterprise_provider_runtime_source_uses_no_network_or_markdown_parser():
    package = Path(enterprise_mapping_provider.__file__).resolve().parent
    roots = set(import_roots(package))
    assert roots.isdisjoint({"requests", "httpx", "aiohttp", "markdown", "mistune"})
