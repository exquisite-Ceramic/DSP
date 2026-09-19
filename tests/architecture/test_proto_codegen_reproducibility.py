"""M4 Task 12：冻结 Protobuf/gRPC 代码生成所有权与可重复性契约。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PYPROJECT = ROOT / "hosts/autocad/sidecar/pyproject.toml"
DOTNET_PROJECT = (
    ROOT
    / "hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj"
)
LOCK = ROOT / "uv.lock"
PROTO = ROOT / "contracts/proto/host_transport_v1.proto"
GENERATED_DIR = (
    ROOT / "hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated"
)
PB2 = GENERATED_DIR / "host_transport_v1_pb2.py"
PB2_GRPC = GENERATED_DIR / "host_transport_v1_pb2_grpc.py"

EXPECTED_PROTO_FROM_SIDECAR = "../../../../contracts/proto/host_transport_v1.proto"
EXPECTED_OUTPUT_FROM_SIDECAR = "src/autocad_sidecar/ipc/generated"
EXPECTED_PYTHON_GENERATOR = "grpcio-tools==1.84.0"
# .NET codegen 版本由 transport csproj 独占；这里冻结本次 family modernization 后的 owner 值。
EXPECTED_DOTNET_GRPC_TOOLS = "2.84.0"


def _sidecar_metadata() -> dict:
    return tomllib.loads(SIDECAR_PYPROJECT.read_text(encoding="utf-8"))


def _codegen_contract() -> dict:
    metadata = _sidecar_metadata()
    tool = metadata.get("tool", {})
    dsp = tool.get("dsp", {})
    contract = dsp.get("proto-codegen")
    assert contract is not None, (
        "hosts/autocad/sidecar/pyproject.toml must declare "
        "[tool.dsp.proto-codegen] before code generation is considered reproducible"
    )
    return contract


def _locked_package_version(package_name: str) -> str | None:
    lock_text = LOCK.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'\[\[package\]\]\s+name = "{re.escape(package_name)}"\s+'
        r'version = "([^"]+)"',
        re.MULTILINE,
    )
    match = pattern.search(lock_text)
    return match.group(1) if match else None


def test_codegen_contract_keeps_the_canonical_proto_as_the_only_source_truth():
    contract = _codegen_contract()

    assert PROTO.exists()
    assert contract["source"] == EXPECTED_PROTO_FROM_SIDECAR
    assert contract["output"] == EXPECTED_OUTPUT_FROM_SIDECAR

    project = DOTNET_PROJECT.read_text(encoding="utf-8")
    assert (
        "<DspHostTransportProto>..\\..\\..\\..\\..\\contracts\\proto\\host_transport_v1.proto"
        "</DspHostTransportProto>"
    ) in project
    assert project.count('<Protobuf Include="$(DspHostTransportProto)"') == 1


def test_python_generator_is_exactly_declared_and_present_in_the_committed_lock():
    metadata = _sidecar_metadata()
    grpc_build = metadata["project"]["optional-dependencies"]["grpc-build"]

    assert grpc_build == [EXPECTED_PYTHON_GENERATOR]
    assert _locked_package_version("grpcio-tools") == "1.84.0"


def test_dotnet_grpc_tools_ownership_remains_explicit_and_project_local():
    project = DOTNET_PROJECT.read_text(encoding="utf-8")

    assert (
        f"<DspGrpcToolsVersion>{EXPECTED_DOTNET_GRPC_TOOLS}</DspGrpcToolsVersion>"
        in project
    )
    assert (
        '<PackageReference Include="Grpc.Tools" Version="$(DspGrpcToolsVersion)" '
        'PrivateAssets="All" />'
    ) in project


def test_regeneration_command_targets_the_existing_generated_package():
    contract = _codegen_contract()
    command = contract["command"]

    assert command.startswith("python -m grpc_tools.protoc ")
    assert "-I ../../../../contracts/proto" in command
    assert "--python_out=src/autocad_sidecar/ipc/generated" in command
    assert "--grpc_python_out=src/autocad_sidecar/ipc/generated" in command
    assert command.endswith(EXPECTED_PROTO_FROM_SIDECAR)


def test_committed_python_stubs_record_the_locked_generator_provenance():
    pb2 = PB2.read_text(encoding="utf-8")
    pb2_grpc = PB2_GRPC.read_text(encoding="utf-8")

    # grpcio-tools 1.84.0 当前携带 protoc 7.35.1；
    # 锁文件中的 protobuf runtime 可取同 major 的新补丁。
    assert "# Protobuf Python Version: 7.35.1" in pb2
    assert "GRPC_GENERATED_VERSION = '1.84.0'" in pb2_grpc
    assert _locked_package_version("grpcio-tools") == "1.84.0"
    assert _locked_package_version("protobuf") == "7.36.2"
