from pathlib import Path

import semantic_runtime as s


def test_d5_public_surface_exposes_v06_types_without_old_identity_binding() -> None:
    assert not hasattr(s, "IdentityBinding")
    assert hasattr(s, "SemanticIdentity")
    assert hasattr(s, "HostBinding")
    assert hasattr(s, "ExternalIdentity")
    assert hasattr(s, "SemanticProjectionRef")
    assert hasattr(s, "SemanticEnvironmentRef")


def test_semantic_runtime_source_has_no_host_or_provider_implementation_leakage() -> None:
    runtime_dir = Path(s.__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(runtime_dir.glob("*.py"))
    )

    forbidden = (
        "Autodesk",
        "BuiltInCategory",
        "if host ==",
        "ifc_global_id",
        "SemanticProvider",
        "McpSemantic",
        "MetroProvider",
        "Ifc43Provider",
    )
    assert [token for token in forbidden if token in source] == []
