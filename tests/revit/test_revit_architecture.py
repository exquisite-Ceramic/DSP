from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "hosts/revit/plugin/Revit.AgentHost.Core"
NATIVE_HOST_ROOT = REPO_ROOT / "hosts/revit/plugin/Revit.AgentHost"
NATIVE_SOURCE_ROOT = NATIVE_HOST_ROOT / "Native"
SIDECAR_ROOT = REPO_ROOT / "hosts/revit/sidecar"
NATIVE_PROJECT = NATIVE_HOST_ROOT / "Revit.AgentHost.csproj"

PROTECTED_PLATFORM_ROOTS = (
    REPO_ROOT / "platform/impact/src",
    REPO_ROOT / "platform/approval_scope/src",
    REPO_ROOT / "platform/changeset/src",
    REPO_ROOT / "platform/execution_planning/src",
    REPO_ROOT / "platform/provider_binding/src",
    REPO_ROOT / "platform/gateway_authorization/src",
    REPO_ROOT / "platform/execution_reconciliation/src",
    REPO_ROOT / "platform/execution_coordination/src",
)
FORBIDDEN_PLATFORM_TOKENS = (
    "revit",
    "walltype",
    "ost_walls",
    "compoundstructure",
    "externalevent",
)


def _text_files(root: Path, suffixes: tuple[str, ...]) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def test_revit_project_boundary_exists() -> None:
    required = (
        CORE_ROOT / "Revit.AgentHost.Core.csproj",
        NATIVE_PROJECT,
        REPO_ROOT
        / "hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj",
    )

    missing = [path.relative_to(REPO_ROOT).as_posix() for path in required if not path.is_file()]

    assert missing == []


def test_autodesk_revit_api_is_confined_to_native_source_boundary() -> None:
    for forbidden_root in (CORE_ROOT, SIDECAR_ROOT):
        for path in _text_files(forbidden_root, (".cs", ".py", ".csproj")):
            assert "Autodesk.Revit" not in path.read_text(encoding="utf-8")

    revit_root = REPO_ROOT / "hosts/revit"
    for path in _text_files(revit_root, (".cs",)):
        text = path.read_text(encoding="utf-8")
        if "Autodesk.Revit" not in text:
            continue
        assert path.is_relative_to(NATIVE_SOURCE_ROOT), (
            f"Autodesk.Revit reference escaped Native boundary: "
            f"{path.relative_to(REPO_ROOT).as_posix()}"
        )


def test_native_project_uses_machine_supplied_revit_baseline() -> None:
    assert NATIVE_PROJECT.is_file()
    text = NATIVE_PROJECT.read_text(encoding="utf-8")

    assert "<TargetFramework>$(DspRevitTargetFramework)</TargetFramework>" in text
    assert "DspRevitVersion" in text
    assert "DspRevitTargetFramework" in text
    assert "DspRevitApiDir" in text
    assert "$(DspRevitApiDir)\\RevitAPI.dll" in text
    assert "$(DspRevitApiDir)\\RevitAPIUI.dll" in text

    lowered = text.lower()
    for forbidden in ("net8.0-windows", "net10.0-windows", "2025", "2026"):
        assert forbidden not in lowered


def test_step27_to_step37_platform_production_remains_revit_free() -> None:
    violations: list[str] = []
    for root in PROTECTED_PLATFORM_ROOTS:
        for path in _text_files(root, (".py", ".json", ".yaml", ".yml", ".toml")):
            lowered = path.read_text(encoding="utf-8").lower()
            tokens = [token for token in FORBIDDEN_PLATFORM_TOKENS if token in lowered]
            if tokens:
                relative = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{relative}: {','.join(tokens)}")

    assert violations == []
