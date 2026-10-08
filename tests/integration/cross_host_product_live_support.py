"""Task 16A：双 Host ProductTask 受控现场的生产适配器与只读预检。

本模块只装配已有 production Host/MCP 边界，不复用 Phase I 执行 helper。
在尚未完成真实 human-resume 与受控 revision-race 接线前，绝不返回四场景 PASS。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_ENV = (
    "DSP_TEST_POSTGRES_DSN",
    "DSP_AUTOCAD_ENDPOINT",
    "DSP_AUTOCAD_DOCUMENT_REF",
    "DSP_AUTOCAD_FIXTURE_PATH",
    "DSP_AUTOCAD_FIXTURE_SHA256",
    "DSP_AUTOCAD_NATIVE_ID",
    "DSP_AUTOCAD_HOST_INSTANCE_ID",
    "DSP_REVIT_LIVE_PIPE",
    "DSP_REVIT_LIVE_DOCUMENT_REF",
    "DSP_REVIT_LIVE_FIXTURE_PATH",
    "DSP_REVIT_LIVE_FIXTURE_SHA256",
    "DSP_REVIT_LIVE_WALL_UNIQUE_ID",
    "DSP_REVIT_LIVE_HOST_INSTANCE_ID",
    "DSP_AGENT_INTERPRETER_COMMAND_JSON",
    "DSP_AGENT_MODEL_NAME",
    "DSP_CROSS_HOST_PRODUCT_MCP_URL",
    "DSP_AUTOCAD_BUILD_IDENTITY",
    "DSP_REVIT_BUILD_IDENTITY",
)
_FROZEN_MCP_TOOLS = frozenset(
    {
        "product.wall_thickness.submit",
        "product.wall_thickness.get",
        "product.wall_thickness.resume_operation_proposal",
    }
)
_BASELINE_MM = 200.0


def verify_fixture_sha256(path: Path, expected: str) -> str:
    """先验证审核过的真实文件哈希，任何错配必须在网络/模型/Host I/O 前失败。"""

    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("LIVE_FIXTURE_HASH_INVALID: expected lowercase SHA-256")
    if not path.is_file():
        raise ValueError("LIVE_FIXTURE_NOT_FOUND: reviewed fixture is missing")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError("LIVE_FIXTURE_HASH_MISMATCH: reviewed fixture bytes changed")
    return actual


def _command_argv(value: str) -> tuple[str, ...]:
    """仅接受明确的 JSON argv；不通过 shell 执行，也不从字符串猜测命令。"""

    try:
        raw: Any = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "LIVE_MODEL_COMMAND_INVALID: expected JSON array of argv"
        ) from exc
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item.strip() for item in raw)
    ):
        raise ValueError("LIVE_MODEL_COMMAND_INVALID: expected nonempty string argv")
    return tuple(raw)


@dataclass(frozen=True, slots=True)
class CrossHostProductLiveConfig:
    """受控 Windows runner 的不可变 preflight 配置；不持久化凭据与 token。"""

    dsn: str
    autocad_endpoint: str
    autocad_document_ref: str
    autocad_fixture_path: Path
    autocad_fixture_sha256: str
    autocad_native_id: str
    autocad_host_instance_id: str
    revit_pipe: str
    revit_document_ref: str
    revit_fixture_path: Path
    revit_fixture_sha256: str
    revit_wall_unique_id: str
    revit_host_instance_id: str
    model_command: tuple[str, ...]
    model_name: str
    mcp_url: str
    autocad_build_identity: str
    revit_build_identity: str

    @classmethod
    def from_environment(cls) -> CrossHostProductLiveConfig:
        """验证受控身份、模型 argv、loopback MCP、文件内容，不进行外部调用。"""

        missing = tuple(
            name for name in _REQUIRED_ENV if not os.environ.get(name, "").strip()
        )
        if missing:
            raise ValueError("LIVE_ENV_MISSING: " + ", ".join(missing))
        env = {name: os.environ[name].strip() for name in _REQUIRED_ENV}
        from design_product_front_door import ProductFrontDoorMcpClient

        # MCP Client 构造阶段只验证 URL 的 loopback trust boundary，不连接网络。
        client = ProductFrontDoorMcpClient(env["DSP_CROSS_HOST_PRODUCT_MCP_URL"])
        config = cls(
            dsn=env["DSP_TEST_POSTGRES_DSN"],
            autocad_endpoint=env["DSP_AUTOCAD_ENDPOINT"],
            autocad_document_ref=env["DSP_AUTOCAD_DOCUMENT_REF"],
            autocad_fixture_path=Path(env["DSP_AUTOCAD_FIXTURE_PATH"]).resolve(),
            autocad_fixture_sha256=env["DSP_AUTOCAD_FIXTURE_SHA256"],
            autocad_native_id=env["DSP_AUTOCAD_NATIVE_ID"],
            autocad_host_instance_id=env["DSP_AUTOCAD_HOST_INSTANCE_ID"],
            revit_pipe=env["DSP_REVIT_LIVE_PIPE"],
            revit_document_ref=env["DSP_REVIT_LIVE_DOCUMENT_REF"],
            revit_fixture_path=Path(env["DSP_REVIT_LIVE_FIXTURE_PATH"]).resolve(),
            revit_fixture_sha256=env["DSP_REVIT_LIVE_FIXTURE_SHA256"],
            revit_wall_unique_id=env["DSP_REVIT_LIVE_WALL_UNIQUE_ID"],
            revit_host_instance_id=env["DSP_REVIT_LIVE_HOST_INSTANCE_ID"],
            model_command=_command_argv(env["DSP_AGENT_INTERPRETER_COMMAND_JSON"]),
            model_name=env["DSP_AGENT_MODEL_NAME"],
            mcp_url=client.endpoint_url,
            autocad_build_identity=env["DSP_AUTOCAD_BUILD_IDENTITY"],
            revit_build_identity=env["DSP_REVIT_BUILD_IDENTITY"],
        )
        for document_ref, fixture_path in (
            (config.autocad_document_ref, config.autocad_fixture_path),
            (config.revit_document_ref, config.revit_fixture_path),
        ):
            if Path(document_ref).resolve() != fixture_path:
                raise ValueError(
                    "LIVE_FIXTURE_DOCUMENT_MISMATCH: reviewed document/fixture differ"
                )
        config.verify_fixtures()
        return config

    def verify_fixtures(self) -> None:
        """每次预检再次验证原始 fixture，拒绝 config 构造之后发生的字节漂移。"""

        verify_fixture_sha256(
            self.autocad_fixture_path, self.autocad_fixture_sha256
        )
        verify_fixture_sha256(self.revit_fixture_path, self.revit_fixture_sha256)


def build_production_host_factories(config: CrossHostProductLiveConfig):
    """只为已审查 locator 装配真实 sidecar；构造不连接 Host 且绝无 fake fallback。"""

    from autocad_sidecar.adapter.host_adapter import HostAdapter
    from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
    from autocad_sidecar.ipc.transport import PipeTransport
    from revit_sidecar.named_pipe import NamedPipeTransport

    def autocad_factory(locator: str):
        """AutoCAD 独立 HostAdapter/CommandDispatcher，通过真实 Windows pipe 连接。"""

        if locator != config.autocad_endpoint:
            raise ValueError("LIVE_HOST_LOCATOR_MISMATCH: AUTOCAD")
        return CommandDispatcher(
            HostAdapter(transport=PipeTransport(config.autocad_endpoint))
        )

    def revit_factory(locator: str):
        """Revit 只用 production NamedPipeTransport，不创建模拟 response。"""

        if locator != config.revit_pipe:
            raise ValueError("LIVE_HOST_LOCATOR_MISMATCH: REVIT")
        return NamedPipeTransport(pipe_name=config.revit_pipe)

    return autocad_factory, revit_factory


def _validate_mcp_tool_catalog(names: tuple[str, ...]) -> None:
    """只接受现有 MCP 2.x 固定三 tool，不能推断新的或模拟的执行入口。"""

    if len(names) != 3 or frozenset(names) != _FROZEN_MCP_TOOLS:
        raise ValueError("LIVE_MCP_CATALOG_INVALID: ProductTask MCP tools mismatch")


def _require_windows_live() -> None:
    """真实 I/O 的第一道硬门：显式开关与 Windows self-hosted runner 缺一不可。"""

    if os.environ.get("DSP_CROSS_HOST_PRODUCT_LIVE") != "1":
        raise ValueError("LIVE_SWITCH_REQUIRED: read-only preflight is not enabled")
    if os.name != "nt":
        raise ValueError("LIVE_WINDOWS_REQUIRED: Windows dual-Host runner is required")


async def run_read_only_preflight(
    config: CrossHostProductLiveConfig,
) -> dict[str, object]:
    """对既有生产 MCP/PostgreSQL/双 Host 做只读验证，不提交 ProductTask 或 EXECUTE。"""

    _require_windows_live()
    config.verify_fixtures()

    import psycopg
    from design_fact_contracts import FactKind, NormalizedDesignFactBatch
    from mcp import Client
    from revit_sidecar import (
        RevitContextReadPort,
        RevitWallThicknessSnapshotReadPort,
    )

    # 无凭据输出的真实 PostgreSQL liveness READ；不得迁移或重置 schema。
    with psycopg.connect(config.dsn, autocommit=True) as conn:
        if conn.execute("SELECT 1").fetchone() != (1,):
            raise ValueError("LIVE_POSTGRES_NOT_READY: SELECT 1 mismatch")

    # 使用真实 MCP transport negotiation/list_tools；绝不调用 submit/resume。
    async with Client(config.mcp_url) as client:
        catalog = await client.list_tools()
    _validate_mcp_tool_catalog(tuple(tool.name for tool in catalog.tools))

    auto_factory, revit_factory = build_production_host_factories(config)
    dispatcher = auto_factory(config.autocad_endpoint)
    batch = await dispatcher.extract_design_facts([config.autocad_native_id])
    if not isinstance(batch, NormalizedDesignFactBatch):
        raise ValueError("LIVE_AUTOCAD_READ_INVALID: normalized facts unavailable")
    auto_facts = tuple(
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY
        and fact.predicate == "constant_width"
        and fact.unit == "mm"
        and fact.host_ref.host_type == "autocad"
        and fact.host_ref.host_instance_id == config.autocad_host_instance_id
        and fact.host_ref.document_id == config.autocad_document_ref
        and fact.subject_native_ref.native_id == config.autocad_native_id
        and fact.subject_native_ref.document_id == config.autocad_document_ref
        and fact.subject_native_ref.native_kind == "LWPOLYLINE"
        and fact.value == _BASELINE_MM
    )
    if len(auto_facts) != 1:
        raise ValueError("LIVE_AUTOCAD_BASELINE_INVALID: exact 200 mm READ missing")

    transport = revit_factory(config.revit_pipe)
    context = RevitContextReadPort(transport).read(
        command_id="task16a-preflight-revit-context",
        document_id=config.revit_document_ref,
        host_instance_id=config.revit_host_instance_id,
    )
    if (
        len(context.selected_elements) != 1
        or context.selected_elements[0].unique_id != config.revit_wall_unique_id
        or context.selected_elements[0].native_kind != "Wall"
    ):
        raise ValueError("LIVE_REVIT_SELECTION_INVALID: reviewed Wall not selected")
    snapshot = RevitWallThicknessSnapshotReadPort(transport).read(
        command_id="task16a-preflight-revit-wall",
        document_id=config.revit_document_ref,
        host_instance_id=config.revit_host_instance_id,
        wall_unique_id=config.revit_wall_unique_id,
        expected_revision=context.revision,
    )
    if snapshot.wall_thickness_mm != _BASELINE_MM:
        raise ValueError("LIVE_REVIT_BASELINE_INVALID: exact 200 mm READ missing")

    # 预检结果只陈述事实 READ，不含人类批准、mutation、Saga 或四场景 PASS。
    return {
        "gate": "READ_ONLY_PREFLIGHT",
        "implementation_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "mcp_catalog": sorted(_FROZEN_MCP_TOOLS),
        "autocad_revision": auto_facts[0].source_revision,
        "revit_revision": context.revision,
        "autocad_baseline_mm": _BASELINE_MM,
        "revit_baseline_mm": snapshot.wall_thickness_mm,
        "autocad_fixture_sha256": config.autocad_fixture_sha256,
        "revit_fixture_sha256": config.revit_fixture_sha256,
        "result": "READ_ONLY_READY",
    }


def run_controlled_case(
    *,
    config: CrossHostProductLiveConfig,
    scenario: str,
) -> dict[str, object]:
    """四场景 driver 尚未接通 human-resume/partial-race，不允许合成 PASS。"""

    _require_windows_live()
    if scenario not in {"deny", "unavailable", "positive", "partial_commit"}:
        raise ValueError("LIVE_SCENARIO_INVALID: unsupported scenario")
    config.verify_fixtures()
    raise RuntimeError(
        "LIVE_CASE_DRIVER_NOT_CONNECTED: pending audited model, MCP V2 "
        "human-resume and deterministic post-readiness revision-race wiring"
    )


def main() -> None:
    """显式 preflight CLI 只检查真实 READ，绝不隐式进入 controlled mutation。"""

    import sys

    if sys.argv[1:] != ["--preflight"]:
        raise SystemExit(
            "usage: python -m tests.integration.cross_host_product_live_support "
            "--preflight"
        )
    config = CrossHostProductLiveConfig.from_environment()
    report = asyncio.run(run_read_only_preflight(config))
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
