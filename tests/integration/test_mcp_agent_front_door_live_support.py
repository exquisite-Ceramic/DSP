"""Task 10：MCP / Agent Front Door controlled live acceptance 的非交互 support gate。"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from design_product_front_door import (
    ConfiguredProductApprovalPolicy,
    ConfiguredRevitCandidateCatalog,
)
from mcp import Client
from revit_sidecar.context import RevitCurrentContextProbe
from revit_sidecar.named_pipe import NamedPipeTransport

_REQUIRED_LIVE_ENV = (
    "DSP_AGENT_INTERPRETER_COMMAND",
    "DSP_AGENT_MODEL_NAME",
    "DSP_FRONT_DOOR_CANDIDATES_FILE",
    "DSP_FRONT_DOOR_POLICY_FILE",
    "DSP_FRONT_DOOR_STATE_DB",
    "DSP_FRONT_DOOR_HOST",
    "DSP_FRONT_DOOR_PORT",
    "DSP_REVIT_VERSION",
    "DSP_REVIT_TFM",
    "DSP_REVIT_API_DIR",
    "DSP_REVIT_PIPE",
    "DSP_REVIT_FIXTURE",
    "DSP_TEST_POSTGRES_DSN",
)
_FROZEN_TOOLS = {
    "product.wall_thickness.submit",
    "product.wall_thickness.get",
    "product.wall_thickness.resume_operation_proposal",
}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _live_skip_reason() -> str | None:
    """默认仓库/CI 只收集并 SKIP；显式 live switch 才允许触碰本机 Revit/MCP。"""

    if os.environ.get("DSP_FRONT_DOOR_LIVE") != "1":
        return "set DSP_FRONT_DOOR_LIVE=1 to run Front Door live-support readiness"
    missing = tuple(name for name in _REQUIRED_LIVE_ENV if not os.environ.get(name))
    if missing:
        return "missing Front Door live-support environment: " + ", ".join(missing)
    return None


_LIVE_SKIP_REASON = _live_skip_reason()
pytestmark = pytest.mark.skipif(
    _LIVE_SKIP_REASON is not None,
    reason=_LIVE_SKIP_REASON or "Front Door live-support readiness disabled",
)


def _load_json(path: Path) -> object:
    """读取本地非秘密配置；错误只暴露文件路径，不打印配置正文。"""

    return json.loads(path.read_text(encoding="utf-8"))


def _configured_live_candidate():
    """从冻结候选配置中定位与本次 fixture/pipe 精确对应的唯一 Revit candidate。"""

    candidates_path = Path(os.environ["DSP_FRONT_DOOR_CANDIDATES_FILE"]).resolve()
    payload = _load_json(candidates_path)
    catalog = ConfiguredRevitCandidateCatalog.from_mapping(payload)

    assert isinstance(payload, dict)
    raw_candidates = payload.get("candidates")
    assert isinstance(raw_candidates, list)

    fixture_path = Path(os.environ["DSP_REVIT_FIXTURE"]).resolve()
    pipe_name = os.environ["DSP_REVIT_PIPE"].strip()
    matching_keys: list[str] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            continue
        document_id = raw_candidate.get("document_id")
        transport_locator = raw_candidate.get("transport_locator")
        candidate_key = raw_candidate.get("candidate_key")
        if not isinstance(document_id, str) or not isinstance(candidate_key, str):
            continue
        try:
            same_fixture = Path(document_id).resolve() == fixture_path
        except OSError:
            same_fixture = False
        if same_fixture and transport_locator == pipe_name:
            matching_keys.append(candidate_key)

    assert len(matching_keys) == 1, (
        "live candidates config must contain exactly one candidate matching "
        "DSP_REVIT_FIXTURE + DSP_REVIT_PIPE"
    )
    candidate = catalog.get(matching_keys[0])
    assert candidate is not None
    return candidate


def _live_mcp_endpoint() -> str:
    """构造受冻结 loopback trust boundary 约束的 MCP endpoint。"""

    host = os.environ["DSP_FRONT_DOOR_HOST"].strip()
    assert host in _LOOPBACK_HOSTS
    port = int(os.environ["DSP_FRONT_DOOR_PORT"])
    assert 1 <= port <= 65535
    rendered_host = f"[{host}]" if host == "::1" else host
    return f"http://{rendered_host}:{port}/mcp"


def test_live_support_environment_and_revit_context_are_ready() -> None:
    """support gate 只证明真实环境可用；不创建 ProductTask，也不触发任何 Host mutation。"""

    if os.name != "nt":
        pytest.fail("DSP_FRONT_DOOR_LIVE=1 requires the pinned Windows/Revit machine")

    fixture_path = Path(os.environ["DSP_REVIT_FIXTURE"]).resolve()
    api_dir = Path(os.environ["DSP_REVIT_API_DIR"]).resolve()
    candidates_path = Path(os.environ["DSP_FRONT_DOOR_CANDIDATES_FILE"]).resolve()
    policy_path = Path(os.environ["DSP_FRONT_DOOR_POLICY_FILE"]).resolve()
    state_db = Path(os.environ["DSP_FRONT_DOOR_STATE_DB"]).resolve()

    assert fixture_path.is_file()
    assert api_dir.is_dir()
    assert candidates_path.is_file()
    assert policy_path.is_file()
    assert state_db.parent.is_dir()
    assert os.environ["DSP_REVIT_VERSION"].strip()
    assert os.environ["DSP_REVIT_TFM"].strip()
    assert os.environ["DSP_AGENT_INTERPRETER_COMMAND"].strip()
    assert os.environ["DSP_AGENT_MODEL_NAME"].strip()

    candidate = _configured_live_candidate()
    policy = ConfiguredProductApprovalPolicy.from_mapping(_load_json(policy_path))
    assert policy.policy_id
    assert policy.policy_snapshot_hash

    # 这里只做 SELECT 1 readiness，不创建/迁移任何业务 schema，也不记录 DSN。
    with psycopg.connect(os.environ["DSP_TEST_POSTGRES_DSN"], autocommit=True) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)

    transport = NamedPipeTransport(pipe_name=os.environ["DSP_REVIT_PIPE"])
    observation = RevitCurrentContextProbe(transport).discover(
        command_id=f"CMD-T10-FRONT-DOOR-READY-{uuid.uuid4().hex}",
        document_id=candidate.document_id,
    )

    assert observation.document_id == candidate.document_id
    assert Path(observation.document_id).resolve() == fixture_path
    assert observation.host_instance_id
    assert observation.revision >= 0
    assert len(observation.selected_elements) == 1
    selected = observation.selected_elements[0]
    assert selected.native_kind == "Wall"
    assert selected.unique_id == candidate.native_target_unique_id


@pytest.mark.asyncio
async def test_live_support_loopback_mcp_catalog_is_ready_without_business_calls() -> None:
    """只通过真实 Streamable HTTP negotiation/list-tools 证明 server 就绪，不调用业务工具。"""

    endpoint = _live_mcp_endpoint()
    async with Client(endpoint) as client:
        catalog = await client.list_tools()

    assert {tool.name for tool in catalog.tools} == _FROZEN_TOOLS
