from pathlib import Path


METRO_PRODUCTION = Path("providers/semantics/metro_v32/src/metro_semantic_provider")
PLATFORM_PRODUCTION = (
    Path("platform/semantic_service/src"),
    Path("platform/semantic_runtime/src"),
    Path("platform/semantic_mcp/src"),
)


FORBIDDEN_METRO_TOKENS = (
    "ifcopenshell",
    "ifc43_semantic_provider",
    "semantic_runtime",
    "semantic_mcp",
    "ElementId",
    "OST_Walls",
    "AutoCAD",
    "A-WALL",
    "Tekla",
)


def _python_texts(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def test_metro_provider_does_not_import_concrete_ifc_host_runtime_or_mcp_code():
    failures = []
    for path, text in _python_texts(METRO_PRODUCTION):
        for token in FORBIDDEN_METRO_TOKENS:
            if token in text:
                failures.append(f"{path}: {token}")
    assert failures == []


def test_platform_production_does_not_import_concrete_metro_provider():
    failures = []
    for root in PLATFORM_PRODUCTION:
        for path, text in _python_texts(root):
            if "metro_semantic_provider" in text:
                failures.append(str(path))
    assert failures == []
