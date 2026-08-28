from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PY_PACKAGE = ROOT / "contracts" / "python" / "design_fact_contracts"
DOTNET_PROJECT = ROOT / "contracts" / "dotnet" / "DesignFactContracts" / "DesignFactContracts.csproj"


def test_design_fact_contracts_are_independent_shared_contracts():
    assert PY_PACKAGE.is_dir(), "design_fact_contracts must be an independent Python package"
    assert DOTNET_PROJECT.is_file(), "DesignFactContracts must be an independent .NET project"


def test_contract_sources_do_not_depend_on_host_sdk_semantic_provider_or_d5_implementations():
    assert PY_PACKAGE.is_dir(), "design_fact_contracts package is missing"
    forbidden = (
        "Autodesk.",
        "autocad_sidecar",
        "semantic_service",
        "semantic_runtime",
        "ifc43_semantic_provider",
        "metro_v32",
        "ifcopenshell",
        "SemanticIdentity",
        "semantic_id",
    )
    sources = "\n".join(path.read_text(encoding="utf-8") for path in PY_PACKAGE.rglob("*.py"))
    for token in forbidden:
        assert token not in sources, f"forbidden dependency/identity leaked into contract: {token}"
