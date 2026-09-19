"""冻结 Python gRPC runtime/codegen family 的兼容性与 Dependabot 原子升级契约。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PYPROJECT = ROOT / "hosts/autocad/sidecar/pyproject.toml"
DEPENDABOT = ROOT / ".github/dependabot.yml"

EXPECTED_GRPCIO = "grpcio>=1.84,<2"
EXPECTED_PROTOBUF = "protobuf>=7.35.1,<8"
EXPECTED_GRPC_TOOLS = "grpcio-tools==1.84.0"
EXPECTED_DEPENDABOT_GROUP = {"grpcio", "grpcio-tools", "protobuf"}


def _sidecar_metadata() -> dict:
    """读取 AutoCAD sidecar 的 package owner 元数据。"""

    return tomllib.loads(SIDECAR_PYPROJECT.read_text(encoding="utf-8"))


def test_python_grpc_runtime_and_codegen_versions_remain_coherent() -> None:
    """生成器升级后，runtime floor 与 protobuf major 必须保持同一兼容性 family。"""

    metadata = _sidecar_metadata()
    runtime_dependencies = set(metadata["project"]["dependencies"])
    grpc_build = metadata["project"]["optional-dependencies"]["grpc-build"]

    assert EXPECTED_GRPCIO in runtime_dependencies
    assert EXPECTED_PROTOBUF in runtime_dependencies
    assert grpc_build == [EXPECTED_GRPC_TOOLS]


def test_dependabot_updates_python_grpc_family_atomically() -> None:
    """Dependabot 不得再把 grpc runtime、codegen 与 protobuf 拆成独立升级候选。"""

    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    uv_update = next(
        update for update in config["updates"] if update["package-ecosystem"] == "uv"
    )
    group = uv_update["groups"]["python-grpc-build-stack"]

    assert set(group["patterns"]) == EXPECTED_DEPENDABOT_GROUP
