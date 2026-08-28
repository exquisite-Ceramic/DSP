from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_semantic_service_remains_mcp_free():
    src = ROOT / "platform/semantic_service/src/semantic_service"
    text = "\n".join(path.read_text() for path in src.glob("*.py"))
    assert "import mcp" not in text
    assert "from mcp" not in text
    assert "semantic_mcp" not in text


def test_semantic_mcp_has_no_forbidden_runtime_dependencies():
    src = ROOT / "platform/semantic_mcp/src/semantic_mcp"
    text = "\n".join(path.read_text() for path in src.glob("*.py"))
    forbidden = (
        "fastmcp",
        "autocad_sidecar",
        "Ifc43Provider",
        "MetroProvider",
        "EnterpriseProvider",
        "project_facts",
    )
    assert all(token not in text for token in forbidden)


def test_semantic_mcp_declares_only_required_runtime_dependencies():
    pyproject = (ROOT / "platform/semantic_mcp/pyproject.toml").read_text()
    assert '"semantic-service>=0.1.0"' in pyproject
    assert '"mcp>=2,<3"' in pyproject
    assert '"pydantic>=2,<3"' in pyproject
    assert "fastmcp" not in pyproject.lower()
