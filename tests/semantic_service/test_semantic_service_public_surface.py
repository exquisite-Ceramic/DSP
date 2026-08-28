import ast
from pathlib import Path

import semantic_service as s


def test_public_surface_contains_phase_c_contracts_only():
    required = (
        "SemanticProviderManifest",
        "SemanticProviderRegistry",
        "SemanticEnvironment",
        "SemanticEnvironmentStore",
        "SemanticService",
        "SemanticVocabularyProvider",
        "SemanticMappingProvider",
        "SemanticValidationProvider",
        "SemanticProjectionProvider",
    )
    assert [name for name in required if not hasattr(s, name)] == []
    assert not hasattr(s, "NormalizedDesignFactBatch")
    assert not hasattr(s, "McpSemanticProviderAdapter")
    assert not hasattr(s, "_hash_payload")


def test_semantic_service_has_no_d5_mcp_or_host_imports():
    package = Path(s.__file__).resolve().parent
    forbidden_roots = {
        "semantic_runtime",
        "mcp",
        "fastmcp",
        "autodesk",
        "revit",
        "tekla",
    }
    found = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".", 1)[0].lower() for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".", 1)[0].lower()]
            else:
                continue
            found.extend(root for root in roots if root in forbidden_roots)
    assert found == []


def test_semantic_service_source_has_no_concrete_provider_or_host_mapping_leakage():
    package = Path(s.__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package.glob("*.py"))
    )
    forbidden = (
        "Ifc43Provider",
        "MetroProvider",
        "McpSemanticProviderAdapter",
        "NormalizedDesignFactBatch",
        "BuiltInCategory",
        "A-WALL",
        "Autodesk",
    )
    assert [token for token in forbidden if token in source] == []
