"""M1 Task 6、M2 Task 8 与 M3 Task 10 的 .NET toolchain / compatibility 契约。"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLOBAL_JSON = ROOT / "global.json"
TRANSPORT = ROOT / (
    "hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj"
)
TRANSPORT_TESTS = ROOT / (
    "hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/"
    "AutoCAD.AgentHost.Grpc.Tests.csproj"
)
AUTOCAD_NATIVE = ROOT / "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj"
REVIT_CORE = ROOT / "hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj"
REVIT_CORE_TESTS = ROOT / (
    "hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj"
)
REVIT_NATIVE = ROOT / "hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj"
WORKFLOW = ROOT / ".github/workflows/repository-regression.yml"
INVENTORY = ROOT / "docs/superpowers/modernization/dependency-inventory.md"
CENTRAL_PACKAGES = ROOT / "Directory.Packages.props"
NET10_OPT_IN = "'$(DspEnableNet10Compatibility)' == 'true'"


def _xml_root(path: Path) -> ET.Element:
    """读取 SDK-style csproj；当前项目没有 XML namespace。"""

    return ET.fromstring(path.read_text(encoding="utf-8"))


def _property_values(project: ET.Element) -> dict[str, str]:
    """把无条件项目级属性折叠成名称到文本值，便于验证唯一 owner。"""

    values: dict[str, str] = {}
    for group in project.findall("PropertyGroup"):
        for child in group:
            if child.attrib.get("Condition"):
                continue
            assert child.tag not in values, f"重复的项目属性 owner: {child.tag}"
            values[child.tag] = (child.text or "").strip()
    return values


def _target_frameworks(path: Path) -> set[tuple[str | None, str]]:
    """读取 TargetFrameworks 的默认值与显式 compatibility opt-in。"""

    project = _xml_root(path)
    return {
        (item.attrib.get("Condition"), (item.text or "").strip())
        for item in project.findall(".//TargetFrameworks")
    }


def _package_references(project: ET.Element) -> dict[str, ET.Element]:
    """按 NuGet package 名称索引当前项目的直接 PackageReference。"""

    references: dict[str, ET.Element] = {}
    for item in project.findall(".//PackageReference"):
        include = item.attrib["Include"]
        assert include not in references, f"重复的 PackageReference: {include}"
        references[include] = item
    return references


def test_global_json_preserves_m0_sdk_policy() -> None:
    """Task 8 兼容性证明不得把 repository SDK policy 提前切到 .NET 10。"""

    data = json.loads(GLOBAL_JSON.read_text(encoding="utf-8"))
    assert data["sdk"] == {
        "version": "8.0.100",
        "rollForward": "latestFeature",
        "allowPrerelease": False,
    }


def test_transport_keeps_project_local_nuget_owners_explicit() -> None:
    """MOD-013=KEEP：版本仍归 transport csproj 所有，不引入中央包管理。"""

    assert not CENTRAL_PACKAGES.exists(), "MOD-013=KEEP 时不得创建 Directory.Packages.props"

    project = _xml_root(TRANSPORT)
    properties = _property_values(project)
    references = _package_references(project)
    expected_owners = {
        "Google.Protobuf": ("DspGoogleProtobufVersion", "3.36.1"),
        "Grpc.AspNetCore": ("DspGrpcAspNetCoreVersion", "2.83.0"),
        "Grpc.Tools": ("DspGrpcToolsVersion", "2.83.0"),
        "System.IO.FileSystem.AccessControl": (
            "DspSystemIOFileSystemAccessControlVersion",
            "5.0.0",
        ),
    }

    for package, (property_name, version) in expected_owners.items():
        assert properties.get(property_name) == version, f"{package} 缺少唯一项目级版本 owner"
        assert references[package].attrib.get("Version") == f"$({property_name})"

    assert references["Grpc.Tools"].attrib.get("PrivateAssets") == "All"


def test_transport_tests_share_refreshed_grpc_client_family() -> None:
    """测试 consumer 不得把 Grpc.Net.Client 钉回旧版本形成 NU1605 downgrade。"""

    references = _package_references(_xml_root(TRANSPORT_TESTS))
    assert references["Grpc.Net.Client"].attrib.get("Version") == "2.83.0"


def test_transport_proto_codegen_owner_is_explicit_and_semantics_unchanged() -> None:
    """proto 仍是唯一 source-of-truth，Task 10 只刷新已批准的 toolchain family。"""

    project = _xml_root(TRANSPORT)
    properties = _property_values(project)
    protobuf_items = project.findall(".//Protobuf")

    assert properties.get("DspHostTransportProto") == (
        "..\\..\\..\\..\\..\\contracts\\proto\\host_transport_v1.proto"
    )
    assert len(protobuf_items) == 1
    assert protobuf_items[0].attrib.get("Include") == "$(DspHostTransportProto)"
    assert protobuf_items[0].attrib.get("GrpcServices") == "Server"


def test_native_host_target_frameworks_remain_host_defined() -> None:
    """Host-neutral .NET 10 compatibility 不得变成 Autodesk native TFM cutover。"""

    autocad = _property_values(_xml_root(AUTOCAD_NATIVE))
    revit = _property_values(_xml_root(REVIT_NATIVE))

    assert autocad["TargetFramework"] == "net8.0-windows"
    assert revit["TargetFramework"] == "$(DspRevitTargetFramework)"


def test_revit_core_net10_target_is_explicitly_opt_in() -> None:
    """8.x consumers 默认只看到 net8；Task 8 lane 显式 opt-in 后才暴露 net10。"""

    expected = {
        (None, "net8.0"),
        (NET10_OPT_IN, "net8.0;net10.0"),
    }
    assert _target_frameworks(REVIT_CORE) == expected
    assert _target_frameworks(REVIT_CORE_TESTS) == expected
    assert not _xml_root(REVIT_CORE).findall(".//TargetFramework")
    assert not _xml_root(REVIT_CORE_TESTS).findall(".//TargetFramework")


def test_repository_regression_has_host_neutral_dotnet10_compatibility_lane() -> None:
    """canonical net8 与 candidate net10 分离，candidate 只测试 Host-neutral Core.Tests。"""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "dotnet10-compat:" in workflow
    assert 'dotnet-version: "10.0.x"' in workflow
    assert (
        "dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/"
        "Revit.AgentHost.Core.Tests.csproj -f net8.0"
    ) in workflow
    assert "DspEnableNet10Compatibility=true" in workflow
    assert "hosts/revit/plugin/global.json" in workflow
    assert "Revit.AgentHost.Core.Tests.csproj -f net10.0" in workflow
    assert "hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj" not in workflow.split(
        "dotnet10-compat:", 1
    )[1]
    assert "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj" not in workflow.split(
        "dotnet10-compat:", 1
    )[1]


def test_inventory_freezes_dotnet_package_and_codegen_ownership() -> None:
    """M1 ownership 必须成为治理事实，而不能只存在于实现者记忆中。"""

    inventory = INVENTORY.read_text(encoding="utf-8")
    assert "### M1 .NET SDK, NuGet and code-generation ownership" in inventory

    for token in (
        "`global.json`",
        "`DspGoogleProtobufVersion`",
        "`DspGrpcAspNetCoreVersion`",
        "`DspGrpcToolsVersion`",
        "`DspSystemIOFileSystemAccessControlVersion`",
        "`DspHostTransportProto`",
        "`contracts/proto/host_transport_v1.proto`",
        "`Directory.Packages.props` remains absent",
    ):
        assert token in inventory
