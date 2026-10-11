"""Task 16：现有生产端口的受控组合、显式人工交接与 owner evidence 收集。

本模块仅使用标准文件/subprocess 与仓库 MCP/owner codec，不定义新业务协议。
人工决定由 pytest 外部 controller 提供；任何不能证明的授权都 fail closed。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .cross_host_product_v2_manual_resume import (
    ExplicitHumanDecisionV2,
    resume_reviewed_v2_proposal,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_MODULE = "tests.integration.cross_host_product_model_interpreter"
MODEL_SOURCE = ROOT / "tests/integration/cross_host_product_model_interpreter.py"


def worktree_source_paths():
    """用已提交项目清单绑定源码，不继承 primary editable/PYTHONPATH。"""

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    relative = project["tool"]["pytest"]["ini_options"]["pythonpath"]
    members = project["tool"]["uv"]["workspace"]["members"]
    candidates = [ROOT, *(ROOT / item for item in relative)]
    candidates.extend(
        ROOT / item / "src" if (ROOT / item / "src").is_dir() else ROOT / item for item in members
    )
    return list(dict.fromkeys(str(item.resolve()) for item in candidates))


def audit_imported_product_sources(modules=None):
    """审计真实已导入的仓库模块位置与文件字节，primary editable 导入 fail closed。"""

    prefixes = {"tests"}
    for source in worktree_source_paths()[1:]:
        prefixes.update(
            item.name
            for item in Path(source).iterdir()
            if item.is_dir() and (item / "__init__.py").is_file()
        )
    result = {}
    for name, module in dict(sys.modules if modules is None else modules).items():
        if name.split(".")[0] not in prefixes:
            continue
        raw = getattr(module, "__file__", None)
        if raw is None:
            namespace = tuple(getattr(module, "__path__", ()))
            if not namespace or any(
                not Path(item).resolve().is_relative_to(ROOT) for item in namespace
            ):
                raise ValueError(
                    "LIVE_PYTHON_PROVENANCE_INVALID: repository namespace outside tree"
                )
            continue
        path = Path(raw).resolve()
        if not path.is_relative_to(ROOT) or path.suffix != ".py" or not path.is_file():
            raise ValueError("LIVE_PYTHON_PROVENANCE_INVALID: imported source outside frozen tree")
        result[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return result


def validate_python_source_manifest(body):
    """要求核心生产模块及逐项当前源码 SHA，绝不信任 ready 中任意 provenance 标志。"""

    required = {"design_product_front_door", "design_product_runtime", "design_orchestrator"}
    if not isinstance(body, dict) or not required.issubset(body):
        raise ValueError("LIVE_PYTHON_PROVENANCE_INVALID: required production imports absent")
    for name, item in body.items():
        if (
            not isinstance(name, str)
            or not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
        ):
            raise ValueError("LIVE_PYTHON_PROVENANCE_INVALID: module source entry malformed")
        path = (ROOT / item["path"]).resolve()
        module_suffix = name.replace(".", "/")
        relative = "/" + path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else ""
        if (
            not path.is_relative_to(ROOT)
            or not path.is_file()
            or path.suffix != ".py"
            or not relative.endswith(
                ("/" + module_suffix + ".py", "/" + module_suffix + "/__init__.py")
            )
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("LIVE_PYTHON_PROVENANCE_INVALID: source identity/hash differs")
    return body


def validate_reviewed_model_command(command):
    """只允许当前解释器运行本工作树内、受 exact HEAD 约束的模型 CLI。"""

    expected = (sys.executable, "-m", MODEL_MODULE)
    if tuple(command) != expected or not MODEL_SOURCE.is_file():
        raise ValueError("LIVE_MODEL_SOURCE_INVALID: reviewed in-tree interpreter required")
    return {
        "module": MODEL_MODULE,
        "path": MODEL_SOURCE.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(MODEL_SOURCE.read_bytes()).hexdigest(),
    }


def validate_model_provider_record(
    record, *, client_submission_ref, model_name, candidate_key, result
):
    """把 provider 原始响应、usage、请求 ID 与 production freeze 输入逐字段关联。"""

    try:
        response = record["raw_response"]
        content = response["content"]
        text = "".join(block["text"] for block in content if block["type"] == "text")
        proposal = json.loads(text)
        usage = response["usage"]
        if (
            record["client_submission_ref"] != client_submission_ref
            or record["model_name"] != model_name
            or record["response_model"] != model_name
            or response["model"] != model_name
            or not isinstance(record["invocation_id"], str)
            or not record["invocation_id"].strip()
            or response["id"] != record["invocation_id"]
            or (
                record["request_id"] is not None
                and (
                    not isinstance(record["request_id"], str)
                    or not record["request_id"].strip()
                )
            )
            or response["stop_reason"] != "end_turn"
            or not isinstance(usage, dict)
            or not isinstance(usage.get("input_tokens"), int)
            or not isinstance(usage.get("output_tokens"), int)
            or usage["input_tokens"] < 0
            or usage["output_tokens"] < 0
            or record["usage"] != usage
            or record["proposal"] != proposal
            or proposal["kind"] != "PROPOSAL"
            or proposal["candidate_key"] != candidate_key
            or proposal["candidate_key"] != result.candidate_key
            or proposal["thickness"]["unit"] != result.thickness_unit
            or proposal["thickness"]["value"] != result.thickness_value
        ):
            raise ValueError("model lineage differs")
        return record
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            "LIVE_MODEL_PROVENANCE_INVALID: raw provider/freeze lineage differs"
        ) from exc


def plain(value):
    """保留原始 int/float，只转换现有 owner DTO 的 JSON 表示。"""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime, UUID)):
        return str(value)
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def write_once(path: Path, body: object) -> None:
    """独占持久化并 fsync；attempt 创建成功是允许发送的必要前置条件。"""

    staging = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with staging.open("x", encoding="utf-8") as handle:
            json.dump(plain(body), handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        # 标准 NTFS/POSIX hard-link 原子发布且不覆盖 winner，读者看不到半写 JSON。
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    """JSON 文件只作为数据读取，不输出来源内容或异常中的机密。"""

    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("LIVE_JSON_INVALID: structured artifact unavailable") from exc
    if not isinstance(body, dict):
        raise ValueError("LIVE_JSON_INVALID: expected object")
    return body


def current_head() -> str:
    """只读当前 checkout，不访问远程或改变 Git 状态。"""

    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def source_tree_clean():
    """拒绝 tracked source 修改与新增 Python shadow modules；场景输出不属于实现。"""

    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True
    ).strip()
    untracked_python = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
        cwd=ROOT,
        text=True,
    ).strip()
    return not changed and not untracked_python


def freeze_clean_head():
    """live 实现必须已提交；不能给工作区未提交代码贴当前 HEAD 的标签。"""

    head = current_head()
    if not source_tree_clean():
        raise ValueError("LIVE_HEAD_DIRTY: implementation checkout is not committed")
    return head


def load_driver_settings(head):
    """审核配置不含凭据；所有业务身份显式提供，并冻结到本次 implementation HEAD。"""

    configured = os.environ.get("DSP_CROSS_HOST_PRODUCT_DRIVER_CONFIG", "").strip()
    if not configured:
        raise ValueError("LIVE_DRIVER_CONFIG_REQUIRED: reviewed driver JSON missing")
    body = read_json(Path(configured))
    if body.get("implementation_head") != head:
        raise ValueError("LIVE_HEAD_DRIFT: reviewed configuration belongs to another HEAD")
    keys = {
        "implementation_head",
        "database_name",
        "project_id",
        "candidate_key",
        "semantic_target_id",
        "topology_environment_id",
        "topology_revision",
        "slot_ids",
        "configured_reference_ids",
        "policies",
        "utterance",
        "human_timeout_seconds",
        "stage_timeout_seconds",
    }
    if set(body) != keys:
        raise ValueError("LIVE_DRIVER_CONFIG_INVALID: unknown/missing fields")
    for key in (
        "database_name",
        "project_id",
        "candidate_key",
        "semantic_target_id",
        "topology_environment_id",
        "utterance",
    ):
        if not isinstance(body[key], str) or not body[key].strip():
            raise ValueError("LIVE_DRIVER_CONFIG_INVALID: explicit identity missing")
    timeout = body["human_timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 3600
    ):
        raise ValueError("LIVE_DRIVER_CONFIG_INVALID: finite human timeout required")
    from .cross_host_product_live_stages import STAGE_DEADLINE_SECONDS

    if body["stage_timeout_seconds"] != STAGE_DEADLINE_SECONDS:
        raise ValueError("LIVE_DRIVER_CONFIG_INVALID: reviewed stage deadline required")
    for key in ("slot_ids", "configured_reference_ids"):
        if not isinstance(body[key], dict) or set(body[key]) != {"AUTOCAD", "REVIT"}:
            raise ValueError("LIVE_DRIVER_CONFIG_INVALID: exact required Host set missing")
    if not isinstance(body["policies"], dict) or set(body["policies"]) != {"positive", "deny"}:
        raise ValueError("LIVE_DRIVER_CONFIG_INVALID: reviewed phase-one policies missing")
    operation = "set_wall_thickness.v1"
    for scenario in ("positive", "deny"):
        policy = body["policies"][scenario]
        operations = (
            policy.get("allowed_canonical_operations") if isinstance(policy, dict) else None
        )
        if (
            not isinstance(operations, list)
            or not operations
            or any(not isinstance(item, str) or not item.strip() for item in operations)
            or (operation in operations) != (scenario == "positive")
        ):
            raise ValueError("LIVE_POLICY_SCENARIO_INVALID: reviewed operation policy differs")
    return body


def check_frozen_head(head: str) -> None:
    """每个可产生外部副作用的边界都必须拒绝运行期间 HEAD 漂移。"""

    if not re.fullmatch(r"[0-9a-f]{40}", head) or current_head() != head:
        raise ValueError("LIVE_HEAD_DRIFT: implementation HEAD changed")
    if not source_tree_clean():
        raise ValueError("LIVE_HEAD_DIRTY: implementation source changed")


def new_case_directory(root: Path, *, scenario: str, head: str) -> Path:
    """每次创建新的场景目录，不允许用历史 manifest 作为当前执行入口。"""

    case_id = f"{scenario}-{uuid4().hex}"
    directory = root.resolve() / case_id
    directory.mkdir(parents=True, exist_ok=False)
    write_once(
        directory / "case.json",
        {
            "case_id": case_id,
            "scenario": scenario,
            "implementation_head": head,
        },
    )
    return directory


def human_lineage(reviewed, *, case_id: str, implementation_head: str) -> dict:
    """只从真实冻结 winner 与 authoritative pending subject 投影人工关联字段。"""

    return {
        "case_id": case_id,
        "implementation_head": implementation_head,
        "task_id": reviewed.frozen.request.task_id,
        "request_hash": reviewed.frozen.request.request_hash,
        "session_binding_hash": reviewed.frozen.session_binding.binding_hash,
        "pause_id": reviewed.pause_id,
        "subject_ref": reviewed.subject_ref.ref_id,
        "subject_content_hash": reviewed.subject_ref.content_hash,
    }


def publish_pending_proposal(directory, reviewed, *, case_id, head) -> None:
    """先发布完整 owner proposal；禁止预先存在的决定被当作本次人工动作。"""

    if (directory / "human-decision.json").exists():
        raise ValueError("LIVE_HUMAN_PRESELECTED: decision predates published proposal")
    write_once(
        directory / "pending-proposal.json",
        {
            "lineage": human_lineage(reviewed, case_id=case_id, implementation_head=head),
            "proposal": plain(reviewed),
            "published_at": datetime.now(UTC).isoformat(),
            "status": "AWAITING_EXPLICIT_HUMAN",
        },
    )


def load_human_decision(path, reviewed, *, case_id, head) -> ExplicitHumanDecisionV2:
    """必须读取 controller 单独提供的 ACCEPT，不从环境或场景选项推断决定。"""

    body = read_json(path)
    expected = human_lineage(reviewed, case_id=case_id, implementation_head=head)
    if any(body.get(key) != value for key, value in expected.items()):
        raise ValueError("LIVE_HUMAN_DECISION_LINEAGE_INVALID: exact authority mismatch")
    if body.get("decision") != "ACCEPT" or body.get("resume_kind") != "OPERATION_PROPOSAL_ACCEPTED":
        raise ValueError("LIVE_HUMAN_ACCEPT_REQUIRED: mandatory case requires explicit ACCEPT")
    for key in ("operator", "decision_ref", "recorded_at"):
        if not isinstance(body.get(key), str) or not body[key].strip():
            raise ValueError("LIVE_HUMAN_DECISION_INVALID: audit identity absent")
    try:
        recorded_at = datetime.fromisoformat(body["recorded_at"].replace("Z", "+00:00"))
        if recorded_at.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ValueError("LIVE_HUMAN_DECISION_INVALID: timestamp invalid") from exc
    pending_path = path.parent / "pending-proposal.json"
    if pending_path.is_file():
        pending = read_json(pending_path)
        published_at = datetime.fromisoformat(pending["published_at"])
        if pending.get("lineage") != expected or recorded_at < published_at:
            raise ValueError("LIVE_HUMAN_DECISION_STALE: decision predates current proposal")
    return ExplicitHumanDecisionV2(
        **{
            key: body[key]
            for key in (
                "task_id",
                "request_hash",
                "session_binding_hash",
                "pause_id",
                "subject_content_hash",
                "resume_kind",
            )
        }
    )


def await_human_decision(directory, reviewed, *, case_id, head, timeout_seconds, check_head):
    """有限等待独立 controller 原子发布文件；超时只保留 pending。"""

    deadline = time.monotonic() + timeout_seconds
    path = directory / "human-decision.json"
    while True:
        check_head()
        if path.is_file():
            return load_human_decision(path, reviewed, case_id=case_id, head=head)
        if time.monotonic() >= deadline:
            raise ValueError("LIVE_HUMAN_TIMEOUT: no explicit decision supplied")
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


async def resume_once(directory, reviewed, decision, *, human_body, check_head, **ports):
    """先记录 attempt，失败后仅查询 exact task，永不自动重发 resume。"""

    check_head()
    try:
        write_once(
            directory / "resume-attempt.json",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "human_decision": human_body,
            },
        )
    except FileExistsError as exc:
        raise ValueError("LIVE_RESUME_ALREADY_ATTEMPTED: query exact task manually") from exc
    try:
        final = await resume_reviewed_v2_proposal(
            reviewed=reviewed, human_decision=decision, **ports
        )
        check_head()
        return final
    except Exception:
        try:
            queried = await ports["mcp_client"].get(reviewed.frozen.request.task_id)
            write_once(directory / "ambiguous-exact-task-get.json", plain(queried))
        except Exception:
            write_once(
                directory / "ambiguous-exact-task-get-failed.json",
                {
                    "task_id": reviewed.frozen.request.task_id,
                    "status": "QUERY_UNAVAILABLE",
                },
            )
        raise RuntimeError(
            "LIVE_RESUME_AMBIGUOUS: attempt preserved; manual exact-task query required"
        ) from None


class ManagedMcpProcess:
    """管理本次 exact-head MCP 子进程，拒绝任意外部 server 的伪 provenance。"""

    def __init__(self, directory, *, case_id, head, timeout_seconds=30, check_head=None):
        self.directory, self.case_id, self.head = directory, case_id, head
        self.timeout_seconds = timeout_seconds
        self.check_head = check_head or (lambda: check_frozen_head(head))
        self.process = None

    def __enter__(self):
        self.check_head()
        # stdout/stderr 均不使用 PIPE；Windows MCP 日志不会填满缓冲区导致死锁。
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(worktree_source_paths())
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.integration.cross_host_product_live_composition",
                str(self.directory),
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                self.check_head()
                if self.process.poll() is not None:
                    raise ValueError("LIVE_MCP_PROCESS_FAILED: composition stopped")
                ready_path = self.directory / "mcp-ready.json"
                if ready_path.is_file():
                    body = read_json(ready_path)
                    if any(
                        body.get(key) != value
                        for key, value in {
                            "case_id": self.case_id,
                            "implementation_head": self.head,
                            "pid": self.process.pid,
                        }.items()
                    ):
                        raise ValueError(
                            "LIVE_MCP_PROVENANCE_INVALID: current case process mismatch"
                        )
                    validate_python_source_manifest(body.get("python_sources"))
                    return self
                if time.monotonic() >= deadline:
                    raise ValueError("LIVE_MCP_START_TIMEOUT: no managed composition readiness")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def pipe_pid(locator: str, host_kind: str) -> int:
    """解析项目默认 named-pipe PID；只接受规范名称与正整数输入。"""

    prefix = "EnterpriseDesignAgent.Revit." if host_kind == "REVIT" else "EnterpriseDesignAgent."
    match = re.fullmatch(re.escape(prefix) + r"[^\\/]+-([1-9][0-9]*)", locator)
    if match is None or int(match[1]) > 2147483647:
        raise ValueError("LIVE_PLUGIN_PIPE_INVALID: PID locator absent")
    return int(match[1])


def inspect_loaded_module(locator: str, host_kind: str) -> dict:
    """用恒定 PowerShell/.NET 只读脚本检查当前 Host 的实际 loaded module。"""

    pid = pipe_pid(locator, host_kind)
    script = """$ErrorActionPreference='Stop'
$p=Get-Process -Id ([int]$env:DSP_INSPECT_PROCESS_ID)
$wanted=@('AutoCAD.AgentHost.dll','Revit.AgentHost.dll')
$mods=@($p.Modules | Where-Object {$_.ModuleName -in $wanted} | ForEach-Object {
  @{file_name=$_.FileName; product_version=$_.FileVersionInfo.ProductVersion}
})
@{pid=$p.Id; process_name=$p.ProcessName; modules=$mods} | ConvertTo-Json -Depth 5 -Compress
"""
    # inspect 输入只传已校验整数；不拼接 locator/path 为可执行 shell 文本。
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "DSP_INSPECT_PROCESS_ID": str(pid)},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("LIVE_PLUGIN_INSPECTION_FAILED: loaded modules unavailable")
    try:
        return json.loads(completed.stdout)
    except ValueError as exc:
        raise ValueError("LIVE_PLUGIN_INSPECTION_FAILED: invalid module inventory") from exc


def validate_loaded_module(raw, *, host_kind, locator, host_instance_id, expected_sha, head):
    """要求真实 PID、exact HEAD 与实际 DLL 字节 SHA 全部匹配。"""

    name = "Revit.AgentHost.dll" if host_kind == "REVIT" else "AutoCAD.AgentHost.dll"
    if not isinstance(raw, dict) or raw.get("pid") != pipe_pid(locator, host_kind):
        raise ValueError("LIVE_PLUGIN_PID_MISMATCH: loaded process differs")
    modules = [item for item in raw.get("modules", []) if Path(item["file_name"]).name == name]
    if len(modules) != 1 or modules[0].get("product_version") != "1.0.0+" + head:
        raise ValueError("LIVE_PLUGIN_HEAD_MISMATCH: exact loaded DLL unavailable")
    path = Path(modules[0]["file_name"])
    if not path.is_file():
        raise ValueError("LIVE_PLUGIN_BYTES_MISSING: loaded DLL missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha:
        raise ValueError("LIVE_PLUGIN_HASH_MISMATCH: loaded DLL differs from reviewed build")
    return {
        "host_kind": host_kind,
        "host_instance_id": host_instance_id,
        "locator": locator,
        "sha256": actual,
        "inspection": raw,
    }


def validate_pipe_ownership_records(rows, members, plugins):
    """Join every actual client connection to frozen Host identity and loaded DLL process."""

    expected = {(stage, member.host_kind): member for stage in ("CONTROLLER", "MCP")
                for member in members}
    if set(plugins) != {"AUTOCAD", "REVIT"} or set(expected) != {
        (stage, kind) for stage in ("CONTROLLER", "MCP") for kind in ("AUTOCAD", "REVIT")
    }:
        raise ValueError("LIVE_PLUGIN_PIPE_OWNER_INVALID: reviewed Host set differs")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("LIVE_PLUGIN_PIPE_OWNER_INVALID: observation body absent")
        key = (row.get("stage"), row.get("host_kind"))
        member = expected.get(key)
        plugin = plugins.get(row.get("host_kind"))
        pid = plugin.get("inspection", {}).get("pid") if isinstance(plugin, dict) else None
        if (
            member is None
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or row.get("host_instance_id") != member.host_instance_id
            or row.get("locator") != member.transport_locator
            or row.get("expected_pid") != pid
            or row.get("server_pid") != pid
        ):
            raise ValueError("LIVE_PLUGIN_PIPE_OWNER_INVALID: actual server/READ/DLL differs")
        seen.add(key)
    if seen != set(expected):
        raise ValueError(
            "LIVE_PLUGIN_PIPE_OWNER_MISSING: each process/Host needs actual connection"
        )
    return rows


def validate_reconciliation_rows(rows):
    """对 raw PostgreSQL evidence rows 使用既有 codec 逐个重验完整 body/hash。"""

    from design_execution_reconciliation.evidence_store import (
        decode_reconciliation_evidence,
        evidence_kind_and_hash,
    )

    result = {}
    for row in rows:
        try:
            if row["codec_version"] != 1 or row["evidence_hash"] in result:
                raise ValueError("evidence row version/cardinality differs")
            decoded = decode_reconciliation_evidence(row["body"])
            if evidence_kind_and_hash(decoded) != (row["evidence_kind"], row["evidence_hash"]):
                raise ValueError("kind or hash mismatch")
            result[row["evidence_hash"]] = decoded
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("LIVE_OWNER_EVIDENCE_INVALID: body/identity/hash mismatch") from exc
    return result


def require_evidence_body(bodies, content_hash, kind):
    """引用缺少完整 owner body 必须关闭验收门，不能从 query summary 猜测。"""

    from design_execution_reconciliation.evidence_store import evidence_kind_and_hash

    body = bodies.get(content_hash)
    if body is None or evidence_kind_and_hash(body) != (kind, content_hash):
        raise ValueError("LIVE_OWNER_EVIDENCE_MISSING: exact referenced body unavailable")
    return body


def policy_denied_outcome(
    *, final_status, workflow_phase, saga_count, dispatch_count, grant_count, policy_attempts
):
    """保留生产实际 WAITING/POLICY_APPROVAL，拒绝用猜测的 FAILED 来替代 policy truth。"""

    if (
        final_status != "WAITING"
        or workflow_phase != "POLICY_APPROVAL"
        or saga_count
        or dispatch_count
        or grant_count
        or len(policy_attempts) != 1
        or policy_attempts[0].get("status") != "DENIED"
        or policy_attempts[0].get("error_code") != "FRONT_DOOR_APPROVAL_POLICY_DENIED"
    ):
        raise ValueError("LIVE_POLICY_DENY_UNPROVEN: governing result or zero authority absent")
    return "DENIED"


def validate_owner_snapshots(rows, topology):
    """Pydantic 重建原 owner DTO，然后调用原有完整性/hash API；不自造 codec。"""

    from design_approval_scope import ApprovalScopeBoundaryV2, validate_approval_scope_boundary_v2
    from design_changeset import CanonicalChangeSet, validate_changeset_integrity_v2
    from design_execution_coordination import ReadinessBarrierResult, compute_readiness_receipt_hash
    from design_execution_planning import ExecutionPlanV2, validate_execution_plan_v2
    from design_gateway_authorization import (
        ApprovalRecord,
        ExecutionGrantV2,
        compute_approval_hash,
        compute_grant_hash_v2,
    )
    from design_impact import (
        IntentBoundary,
        PlanningSnapshotBinding,
        SemanticEnvironmentBinding,
        SnapshotSetBinding,
    )
    from design_materialization_planning import (
        MaterializationPlan,
        compute_materialization_intent_hash,
        compute_materialization_plan_hash,
        compute_required_set_hash,
    )
    from design_provider_binding import ProviderBindingSetV2, validate_provider_binding_set_v2
    from pydantic import TypeAdapter

    types = {
        "changeset": CanonicalChangeSet,
        "scope": ApprovalScopeBoundaryV2,
        "execution_plan": ExecutionPlanV2,
        "materialization_plan": MaterializationPlan,
        "binding_set": ProviderBindingSetV2,
        "grant": ExecutionGrantV2,
        "readiness": ReadinessBarrierResult,
        "approval": ApprovalRecord,
    }
    result = {kind: [] for kind in types}
    try:
        for row in rows:
            kind = row["kind"]
            body = dict(row["body"])
            # Scope 的公开契约为解耦使用 Any；显式选择其原 production binding DTO。
            if kind == "scope":
                for key, typ in {
                    "intent_boundary": IntentBoundary,
                    "planning_snapshot_ref": PlanningSnapshotBinding,
                    "snapshot_set_ref": SnapshotSetBinding,
                    "semantic_environment_ref": SemanticEnvironmentBinding,
                }.items():
                    body[key] = TypeAdapter(typ).validate_python(body[key])
            value = TypeAdapter(types[kind]).validate_python(body)
            if value not in result[kind]:
                result[kind].append(value)
        if len(result["changeset"]) != 1 or len(result["scope"]) != 1:
            raise ValueError("exact changeset/scope capture absent")
        scope = result["scope"][0]
        validate_approval_scope_boundary_v2(scope)
        validate_changeset_integrity_v2(result["changeset"][0], scope)
        for materialization in result["materialization_plan"]:
            expected = compute_materialization_plan_hash(
                **{
                    key: getattr(materialization, key)
                    for key in (
                        "changeset_hash",
                        "approved_scope_hash",
                        "topology_snapshot_hash",
                        "intents",
                        "required_set_hash",
                        "convergence_profile_hash",
                    )
                }
            )
            if expected != materialization.materialization_plan_hash:
                raise ValueError("materialization hash mismatch")
            if (
                compute_required_set_hash(materialization.intents)
                != materialization.required_set_hash
            ):
                raise ValueError("required set mismatch")
            for intent in materialization.intents:
                if compute_materialization_intent_hash(intent) != intent.intent_hash:
                    raise ValueError("intent hash mismatch")
        slices = {}
        for plan in result["execution_plan"]:
            validate_execution_plan_v2(plan, topology, scope)
            slices.update({item.execution_slice_hash: item for item in plan.execution_slices})
        for binding in result["binding_set"]:
            validate_provider_binding_set_v2(binding, slices[binding.execution_slice_hash])
        for grant in result["grant"]:
            expected = compute_grant_hash_v2(
                **{
                    key: getattr(grant, key)
                    for key in (
                        "approval_hash",
                        "changeset_hash",
                        "approved_scope_hash",
                        "materialization_plan_hash",
                        "materialization_id",
                        "execution_slice_hash",
                        "binding_set_hash",
                        "host_instance_id",
                        "allowed_operations",
                        "issued_at",
                        "expires_at",
                    )
                }
            )
            if expected != grant.grant_hash or grant.grant_id != "EGV2-" + expected[:12]:
                raise ValueError("grant body hash mismatch")
        for approval in result["approval"]:
            expected = compute_approval_hash(
                **{
                    key: getattr(approval, key)
                    for key in (
                        "admission_fingerprint",
                        "changeset_hash",
                        "approved_scope_hash",
                        "semantic_environment_ref",
                        "approver",
                        "policy_snapshot_hash",
                        "allowed_operations",
                        "approved_at",
                    )
                }
            )
            if expected != approval.approval_hash:
                raise ValueError("approval hash mismatch")
        for readiness in result["readiness"]:
            for receipt in readiness.receipts:
                if receipt.receipt_hash != compute_readiness_receipt_hash(receipt):
                    raise ValueError("readiness receipt hash mismatch")
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_OWNER_CAPTURE_INVALID: original owner integrity failed") from exc


def validate_collection_capture(plan, bindings_manifest, grant_manifest, bindings, grants):
    """durable manifests 必须 exact join 到本次实际写入/签发的完整内存 owner body。"""

    from design_orchestrator.workflow_contracts import StableRef

    slices = plan.execution_slices
    required = tuple(
        StableRef(item.execution_slice_id, item.execution_slice_hash) for item in slices
    )
    for manifest, values, id_name, hash_name in (
        (bindings_manifest, bindings, "binding_set_id", "binding_set_hash"),
        (grant_manifest, grants, "grant_id", "grant_hash"),
    ):
        if (
            manifest.execution_plan_id != plan.execution_plan_id
            or manifest.execution_plan_hash != plan.execution_plan_hash
            or manifest.materialization_plan_hash != plan.materialization_plan_hash
            or manifest.required_slice_refs != required
            or len(values) != 2
            or len(manifest.members) != 2
        ):
            raise ValueError("LIVE_OWNER_CAPTURE_MISSING: exact collection bodies absent")
        by_hash = {getattr(value, hash_name): value for value in values}
        for member, execution_slice in zip(manifest.members, slices, strict=True):
            value = by_hash.get(member.owner_ref.content_hash)
            if (
                value is None
                or getattr(value, id_name) != member.owner_ref.ref_id
                or member.execution_slice_hash != execution_slice.execution_slice_hash
                or member.materialization_id != execution_slice.materialization_id
                or value.execution_slice_hash != member.execution_slice_hash
                or value.materialization_id != member.materialization_id
            ):
                raise ValueError("LIVE_OWNER_CAPTURE_LINEAGE_INVALID: referenced body differs")


def publish_validated_evidence(
    directory, *, result, owner_snapshots, topology, required_capture_kinds
):
    """完整 body 校验成功后才发布正式 manifest；缺 body 时保留诊断且绝不报 PASS。"""

    captures = validate_owner_snapshots(owner_snapshots, topology)
    if any(not captures.get(kind) for kind in required_capture_kinds):
        raise ValueError("LIVE_OWNER_CAPTURE_MISSING: closure archive incomplete")
    manifest = directory / "evidence-manifest.json"
    body = {**result, "evidence_manifest_path": str(manifest.resolve())}
    write_once(manifest, body)
    return body


def _host_failure(message):
    """证据缺失保持稳定错误码，不把敏感原始异常写入日志。"""

    raise ValueError("LIVE_HOST_EVIDENCE_INVALID: " + message)


def width_from_read(record, member):
    """只解析已经由生产 READ adapter 接收的实际 native response，保留数值表示。"""

    command, response = record["command"], record.get("response", {})
    if command.get("mode") != "READ" or response.get("status") != "OK":
        _host_failure("independent successful READ absent")
    payload = response.get("payload", {})
    if member.host_kind == "AUTOCAD":
        if (
            command.get("operation") != "design.extract_native_snapshot"
            or payload.get("hostInstanceId") != member.host_instance_id
            or payload.get("documentId") != member.document_id
        ):
            _host_failure("AutoCAD READ identity mismatch")
        entities = [
            item
            for item in payload.get("entities", [])
            if item.get("nativeId") == member.native_target_id
        ]
        if len(entities) != 1:
            _host_failure("AutoCAD native target cardinality differs")
        width = entities[0].get("properties", {}).get("constantWidth", {})
        revision = payload.get("revision")
        if width.get("unit") != "mm":
            _host_failure("AutoCAD normalized unit differs")
        value = width.get("value")
    else:
        if (
            command.get("operation") != "read_wall_thickness_snapshot"
            or payload.get("host_instance_id") != member.host_instance_id
            or payload.get("document_id") != member.document_id
            or payload.get("wall_unique_id") != member.native_target_id
            or payload.get("revision_before") != payload.get("revision_after")
        ):
            _host_failure("Revit READ identity/revision mismatch")
        value, revision = payload.get("wall_thickness_mm"), payload.get("revision_after")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or isinstance(revision, bool)
        or not isinstance(revision, int)
    ):
        _host_failure("native width/revision type differs")
    return {"value": value, "unit": "mm"}, revision


def independent_host_reads(reviewed, commands, *, expected_mm):
    """每端独立最终 READ 必须有唯一实际命令、exact native identity 和审查基线。"""

    result = {}
    observations = {item.host_kind: item for item in reviewed.subject.observations}
    for member in reviewed.frozen.session_binding.members:
        reads = [
            item
            for item in commands
            if item["host_kind"] == member.host_kind
            and item["phase"] == "RECEIVE"
            and item.get("stage") == "INDEPENDENT_FINAL"
            and item["command"].get("operation")
            == (
                "design.extract_native_snapshot"
                if member.host_kind == "AUTOCAD"
                else "read_wall_thickness_snapshot"
            )
        ]
        if len(reads) != 1:
            _host_failure("one exact independent final READ required")
        width, revision = width_from_read(reads[0], member)
        baseline = observations[member.host_kind]
        if width["value"] != expected_mm or baseline.normalized_thickness_mm != 200:
            _host_failure("baseline/final width differs")
        result[member.host_kind] = {
            "baseline_revision": baseline.host_revision,
            "independent_baseline_read": {"value": baseline.normalized_thickness_mm, "unit": "mm"},
            "independent_final_read": width,
            "verification_revision": revision,
            "independent_read_command_id": reads[0]["command"]["command_id"],
            "verification_source": "INDEPENDENT_HOST_READ",
        }
    return result


def project_positive_hosts(reviewed, final, dispatches, evidence, commands):
    """把实际 dispatch/body/独立 READ 关联到每个 exact materialization，不信任 receipt 验证。"""

    hosts = independent_host_reads(reviewed, commands, expected_mm=300)
    if len(final.materializations) != 2 or len(dispatches) != 2 or len(evidence) != 6:
        _host_failure("positive slice/dispatch/evidence cardinality differs")
    mutation_order = [
        item["host_kind"]
        for item in commands
        if item["phase"] == "SEND" and item["command"].get("mode") == "EXECUTE"
    ]
    if mutation_order != ["AUTOCAD", "REVIT"]:
        _host_failure("exact AutoCAD then Revit mutation order absent")
    members = {item.host_kind: item for item in reviewed.frozen.session_binding.members}
    for item in final.materializations:
        member = members.get(item.host_kind)
        if (
            member is None
            or any(
                getattr(item, field) != getattr(member, field)
                for field in (
                    "host_instance_id",
                    "document_id",
                    "native_target_id",
                )
            )
            or item.semantic_target_id != reviewed.frozen.session_binding.semantic_target_id
        ):
            _host_failure("query materialization differs from frozen Host member")
        delta = require_evidence_body(evidence, item.actual_delta_hash, "actual_delta")
        bundle = require_evidence_body(evidence, item.evidence_bundle_hash, "verification_bundle")
        verification = require_evidence_body(
            evidence, item.verification_hash, "verification_result"
        )
        intent = [
            row for row in dispatches if row["execution_slice_hash"] == item.execution_slice_hash
        ]
        if len(intent) != 1:
            _host_failure("exact dispatch missing")
        intent = intent[0]
        if (
            intent["saga_id"] != final.saga_id
            or intent["grant_hash"] != delta.grant_hash
            or intent["binding_set_hash"] != delta.binding_set_hash
            or intent["host_instance_id"] != member.host_instance_id
            or intent["document_ref"] != member.document_id
            or intent["status"] not in {"HOST_COMMITTED", "RECONCILED"}
            or str(intent["expected_host_revision"]) != str(delta.revision_before)
        ):
            _host_failure("dispatch authority differs from ActualDelta")
        if (
            item.status != "SUCCEEDED"
            or delta.document_ref != member.document_id
            or delta.host_instance_id != member.host_instance_id
            or delta.execution_slice_hash != item.execution_slice_hash
            or delta.revision_before != hosts[item.host_kind]["baseline_revision"]
            or delta.revision_after != delta.revision_before + 1
            or (item.expected_revision, item.committed_revision, item.observed_revision)
            != (delta.revision_before, delta.revision_after, delta.revision_after)
            or hosts[item.host_kind]["verification_revision"] != delta.revision_after
            or bundle.execution_slice_hash != item.execution_slice_hash
            or bundle.actual_delta_hash != delta.actual_delta_hash
            or bundle.base_host_revision != str(delta.revision_after)
            or verification.execution_slice_hash != item.execution_slice_hash
            or verification.evidence_bundle_hash != bundle.evidence_bundle_hash
            or verification.status.value != "PASSED"
        ):
            _host_failure("committed body/query/READ lineage mismatch")
        subjects = [
            body for body in bundle.subject_evidence if body.semantic_id == item.semantic_target_id
        ]
        if (
            len(subjects) != 1
            or subjects[0].properties.get("dsp:WallThickness", {}).get("value") != 300
        ):
            _host_failure("semantic verification body does not prove 300 mm")
        sends = [
            row
            for row in commands
            if row["host_kind"] == item.host_kind
            and row["phase"] == "SEND"
            and row["command"].get("mode") == "EXECUTE"
        ]
        receives = [
            row
            for row in commands
            if row["host_kind"] == item.host_kind
            and row["phase"] == "RECEIVE"
            and row["command"].get("mode") == "EXECUTE"
        ]
        if (
            len(sends) != 1
            or len(receives) != 1
            or sends[0]["command"] != receives[0]["command"]
            or str(sends[0]["command"].get("idempotency_key")) != str(intent["idempotency_key"])
            or receives[0]["response"].get("status") != "OK"
            or receives[0]["response"].get("revision_after") != delta.revision_after
        ):
            _host_failure("one actual authorized commit absent")
        after_commit = commands[commands.index(receives[0]) + 1 :]
        product_reads = [
            row
            for row in after_commit
            if row["host_kind"] == item.host_kind
            and row["phase"] == "RECEIVE"
            and row.get("stage") == "MCP"
            and row["command"].get("operation")
            == (
                "design.extract_native_snapshot"
                if item.host_kind == "AUTOCAD"
                else "read_wall_thickness_snapshot"
            )
        ]
        if not product_reads:
            _host_failure("production verification READ absent after commit")
        for read in product_reads:
            width, revision = width_from_read(read, member)
            if width["value"] != 300 or revision != delta.revision_after:
                _host_failure("production READ does not prove committed revision")
        final_command = hosts[item.host_kind]["independent_read_command_id"]
        if any(read["command"]["command_id"] == final_command for read in product_reads):
            _host_failure("independent READ reused product verification command")
        hosts[item.host_kind].update(
            product_mutation_count=1,
            committed_revision=delta.revision_after,
            actual_delta_hash=delta.actual_delta_hash,
            verification_hash=verification.verification_hash,
            evidence_bundle_hash=bundle.evidence_bundle_hash,
            original_bundle_value=plain(subjects[0].properties["dsp:WallThickness"]["value"]),
        )
    return hosts


def project_staged_outcome(directory, reviewed, final, checkpoint, sagas, raw, evidence,
                           captures, commands):
    """Project failure truth from original commands, owner bodies and exact stage records."""

    from .cross_host_product_live_stages import (
        stage_hash,
        validate_native_stage_failure,
        validate_partial_event_order,
        validate_stage_completion,
        validate_stage_release,
    )

    case = read_json(directory / "case.json")
    pending = read_json(directory / "pending-stage.json")
    completion = validate_stage_completion(
        pending, read_json(directory / "stage-controller-completion.json")
    )
    release = read_json(directory / "stage-release.json")
    validate_stage_release(
        pending, release, completion_hash=stage_hash(completion),
        proof_hash=stage_hash(pending["prerequisite_hashes"]),
    )
    if read_json(directory / "stage-release-consumed.json") != release:
        _host_failure("stage release was not consumed once")
    attempt = read_json(directory / "stage-send-attempt.json")
    if (
        attempt.get("stage_id") != pending["stage_id"]
        or attempt.get("pending_hash") != pending["pending_hash"]
        or attempt.get("command_id") != pending["original_command_id"]
    ):
        _host_failure("original stage send attempt missing")
    member = next(item for item in reviewed.frozen.session_binding.members
                  if item.host_kind == "REVIT")
    if any(pending.get(key) != value for key, value in {
        "case_id": case["case_id"],
        "scenario": case["scenario"],
        "implementation_head": case["implementation_head"],
        "task_id": reviewed.frozen.request.task_id,
        "request_hash": reviewed.frozen.request.request_hash,
        "session_binding_hash": reviewed.frozen.session_binding.binding_hash,
        "host_instance_id": member.host_instance_id,
        "document_id": member.document_id,
        "native_target_id": member.native_target_id,
    }.items()):
        _host_failure("stage lineage differs from frozen request/member")
    stage_sends = [row for row in commands if row["host_kind"] == "REVIT"
                   and row["phase"] == "SEND"
                   and row["command"].get("command_id") == pending["original_command_id"]]
    stage_receives = [row for row in commands if row["host_kind"] == "REVIT"
                      and row["phase"] == "RECEIVE"
                      and row["command"].get("command_id") == pending["original_command_id"]]
    if (
        len(stage_sends) != 1 or len(stage_receives) != 1
        or stage_sends[0]["command"] != stage_receives[0]["command"]
        or stage_hash(stage_sends[0]["command"]) != pending["original_command_hash"]
        or stage_hash(stage_sends[0]["command"]) != attempt.get("command_hash")
    ):
        _host_failure("original command was not sent and received exactly once")
    if case["scenario"] == "unavailable":
        response = stage_receives[0]["response"]
        validate_native_stage_failure("unavailable", response)
        if (
            pending["operation"] != "check_wall_thickness_readiness"
            or len(sagas) != 0 or raw["dispatches"] or evidence
            or final.saga_id is not None or final.materializations
            or final.convergence_result_hash is not None
            or final.status.value != (
                "FAILED" if checkpoint.phase.value == "FAILED" else "WAITING"
            )
            or checkpoint.phase.value == "COMPLETED"
            or len(captures["readiness"]) != 1
            or captures["readiness"][0].status.value != "NOT_READY"
            or len(captures["readiness"][0].receipts) != 2
            or captures["readiness"][0].failure_ref
            != "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE"
            or any(row["phase"] == "SEND" and row["command"].get("mode") == "EXECUTE"
                   for row in commands)
        ):
            _host_failure("native unavailable/readiness/no-commit facts differ")
        auto = next(item for item in reviewed.frozen.session_binding.members
                    if item.host_kind == "AUTOCAD")
        auto_reads = [row for row in commands if row["host_kind"] == "AUTOCAD"
                      and row["phase"] == "RECEIVE" and row.get("stage") == "INDEPENDENT_FINAL"]
        if len(auto_reads) != 1:
            _host_failure("available Host final READ absent")
        width, revision = width_from_read(auto_reads[0], auto)
        baseline = next(item for item in reviewed.subject.observations
                        if item.host_kind == "AUTOCAD")
        get = read_json(directory / "host-independent-get.json")
        if (
            width != {"value": 200, "unit": "mm"}
            or revision != baseline.host_revision
            or get.get("task_id") != final.task_id
            or get.get("before") != get.get("after")
            or get.get("result") != plain(final)
        ):
            _host_failure("available baseline or Host-independent exact GET differs")
        hosts = {
            "AUTOCAD": {
                "baseline_revision": baseline.host_revision,
                "independent_baseline_read": {"value": 200, "unit": "mm"},
                "independent_final_read": width,
                "verification_revision": revision,
                "verification_source": "INDEPENDENT_HOST_READ",
                "product_mutation_count": 0,
            },
            "REVIT": {
                "baseline_revision": next(item.host_revision for item in
                    reviewed.subject.observations if item.host_kind == "REVIT"),
                "independent_baseline_read": {"value": 200, "unit": "mm"},
                "independent_final_read": None,
                "evidence_absent_reason": (
                    "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE: reviewed document closed unsaved"
                ),
                "product_mutation_count": 0,
            },
        }
        return {
            "hosts": hosts,
            "readiness_status": "NOT_READY",
            "saga_status": None,
            "convergence_status": None,
            "stage_pending_path": str((directory / "pending-stage.json").resolve()),
            "stage_completion_path": str(
                (directory / "stage-controller-completion.json").resolve()
            ),
            "host_independent_get_path": str((directory / "host-independent-get.json").resolve()),
        }
    validate_native_stage_failure("partial_commit", stage_receives[0]["response"])
    if (
        pending["operation"] != "set_wall_thickness"
        or len(sagas) != 1 or sagas[0].status.value != "PARTIALLY_COMMITTED"
        or final.status.value != "PARTIALLY_COMMITTED"
        or final.saga_id != sagas[0].definition.saga_id
        or final.convergence_result_hash is not None
        or _jsonl(directory / "convergence-captures.jsonl")
        or len(captures["readiness"]) != 1
        or captures["readiness"][0].status.value != "READY"
        or len(captures["readiness"][0].receipts) != 2
        or len(final.materializations) != 2
        or len(raw["dispatches"]) != 2
    ):
        _host_failure("partial Saga/READY/native BEFORE_COMMIT lineage differs")
    states = sagas[0].slice_states
    if (
        [item.status.value for item in states] != ["SUCCEEDED", "FAILED_BEFORE_COMMIT"]
        or states[1].actual_delta_hash is not None
        or states[1].verification_hash is not None
        or states[0].actual_delta_hash is None
        or len([row for row in commands if row["phase"] == "SEND"
                and row["command"].get("mode") == "EXECUTE"]) != 2
        or len([row for row in commands if row["host_kind"] == "AUTOCAD"
                and row["phase"] == "SEND"
                and row["command"].get("mode") == "EXECUTE"]) != 1
    ):
        _host_failure("partial Saga Slice states or exact mutation attempts differ")
    by_host = {item.host_kind: item for item in final.materializations}
    auto, revit = by_host["AUTOCAD"], by_host["REVIT"]
    delta = require_evidence_body(evidence, auto.actual_delta_hash, "actual_delta")
    bundle = require_evidence_body(evidence, auto.evidence_bundle_hash, "verification_bundle")
    verified = require_evidence_body(evidence, auto.verification_hash, "verification_result")
    if (
        len(evidence) != 3 or auto.status != "SUCCEEDED"
        or delta.revision_after != auto.committed_revision
        or verified.status.value != "PASSED"
        or verified.evidence_bundle_hash != bundle.evidence_bundle_hash
        or bundle.actual_delta_hash != delta.actual_delta_hash
        or revit.actual_delta_hash is not None
        or revit.verification_hash is not None
        or revit.evidence_bundle_hash is not None
        or revit.committed_revision is not None
        or revit.expected_revision != pending["expected_revision"]
    ):
        _host_failure("partial durable body/query revisions differ")
    observation = read_json(directory / "independent-edit-observation.json")
    if (
        observation.get("command_id") != pending["stage_id"] + ":independent-edit-read"
        or observation.get("normalized_thickness_mm") != 201
        or observation.get("host_revision", -1) <= pending["expected_revision"]
        or observation.get("host_instance_id") != member.host_instance_id
        or observation.get("document_id") != member.document_id
        or observation.get("native_target_id") != member.native_target_id
    ):
        _host_failure("separate advanced-revision native edit READ differs")
    final_reads = [row for row in commands if row["phase"] == "RECEIVE"
                   and row.get("stage") == "INDEPENDENT_FINAL"
                   and row["command"].get("operation") in {
                       "design.extract_native_snapshot", "read_wall_thickness_snapshot"
                   }]
    if len(final_reads) != 2:
        _host_failure("two independent final READs absent")
    final_by_host = {row["host_kind"]: row for row in final_reads}
    auto_member = next(item for item in reviewed.frozen.session_binding.members
                       if item.host_kind == "AUTOCAD")
    auto_width, auto_revision = width_from_read(final_by_host["AUTOCAD"], auto_member)
    revit_width, revit_revision = width_from_read(final_by_host["REVIT"], member)
    if (
        auto_width != {"value": 300, "unit": "mm"}
        or auto_revision != delta.revision_after
        or revit_width != {"value": 201, "unit": "mm"}
        or revit_revision != observation["host_revision"]
    ):
        _host_failure("partial independent final READs differ")
    ready_rows = [row for row in _jsonl(directory / "owner-captures.jsonl")
                  if row["kind"] == "readiness"]
    auto_receives = [row for row in commands if row["host_kind"] == "AUTOCAD"
                     and row["phase"] == "RECEIVE"
                     and row["command"].get("mode") == "EXECUTE"]
    edit_reads = [row for row in commands if row["host_kind"] == "REVIT"
                  and row["phase"] == "RECEIVE"
                  and row.get("stage") == "INDEPENDENT_EDIT_READ"
                  and row["command"].get("operation") == "read_wall_thickness_snapshot"]
    if len(ready_rows) != 1 or len(auto_receives) != 1 or len(edit_reads) != 1:
        _host_failure("four real ordered event sources absent")
    timestamps = [ready_rows[0]["timestamp"], auto_receives[0]["timestamp"],
                  edit_reads[0]["timestamp"], stage_receives[0]["timestamp"]]
    event_order, event_timestamps = validate_partial_event_order(timestamps)
    return {
        "hosts": {
            "AUTOCAD": {
                "baseline_revision": delta.revision_before,
                "independent_baseline_read": {"value": 200, "unit": "mm"},
                "independent_final_read": auto_width,
                "committed_revision": delta.revision_after,
                "verification_revision": auto_revision,
                "verification_source": "INDEPENDENT_HOST_READ",
                "product_mutation_count": 1,
                "actual_delta_hash": delta.actual_delta_hash,
                "verification_hash": verified.verification_hash,
            },
            "REVIT": {
                "baseline_revision": pending["expected_revision"],
                "independent_baseline_read": {"value": 200, "unit": "mm"},
                "independent_final_read": revit_width,
                "verification_revision": revit_revision,
                "verification_source": "INDEPENDENT_HOST_READ",
                "product_mutation_count": 0,
            },
        },
        "required_slice_count": 2,
        "readiness_status": "READY",
        "all_required_readiness_passed": True,
        "event_order": event_order,
        "event_timestamps": event_timestamps,
        "independent_edit": {
            "host_kind": "REVIT", "before_mm": 200, "after_mm": 201,
            "command_id": completion["native_edit_command_id"],
            "authorization_ref": completion["authorization_ref"],
            "read_evidence": observation,
        },
        "revit_failure_ref": "REVISION_CONFLICT",
        "revit_failure_phase": "BEFORE_COMMIT",
        "revit_product_actual_delta_hash": None,
        "convergence_status": None,
        "saga_status": sagas[0].status.value,
        "automatic_compensation_count": 0,
        "stage_pending_path": str((directory / "pending-stage.json").resolve()),
        "stage_completion_path": str((directory / "stage-controller-completion.json").resolve()),
    }


def _jsonl(path):
    """读取专用场景目录中自己的公开命令/owner审计文件。"""

    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _require_empty_database(config, database_name):
    """只读验证 dedicated 新数据库；不清理、迁移或重写任何历史 owner。"""

    import psycopg

    with psycopg.connect(config.dsn, autocommit=True) as connection:
        if connection.execute("SELECT current_database()").fetchone() != (database_name,):
            raise ValueError("LIVE_DATABASE_IDENTITY_INVALID: dedicated case database differs")
        if connection.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
        ).fetchall():
            raise ValueError("LIVE_DATABASE_NOT_FRESH: dedicated database already owns tables")


def _verify_listener_pid(url, pid):
    """独立查实际 loopback listener 的 OS PID，拒绝已有外部 MCP 服务的伪造身份。"""

    port = urlsplit(url).port or 80
    script = """$ErrorActionPreference='Stop'
@(Get-NetTCPConnection -State Listen -LocalPort ([int]$env:DSP_INSPECT_PORT) |
  Select-Object -ExpandProperty OwningProcess -Unique) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "DSP_INSPECT_PORT": str(port)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return False
    try:
        body = json.loads(completed.stdout)
        return body == pid or body == [pid]
    except ValueError:
        return False


def _wait_managed_catalog(config, managed, check_head):
    """只在被 OS 确認为本次进程的 MCP listener 上 negotiation，避免任意 caller flag。"""

    from mcp import Client

    from .cross_host_product_live_support import _validate_mcp_tool_catalog

    async def catalog():
        async with Client(config.mcp_url) as client:
            result = await client.list_tools()
        _validate_mcp_tool_catalog(tuple(tool.name for tool in result.tools))

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        check_head()
        if managed.process.poll() is not None:
            raise ValueError("LIVE_MCP_PROCESS_FAILED: managed server exited")
        if _verify_listener_pid(config.mcp_url, managed.process.pid):
            asyncio.run(catalog())
            return
        time.sleep(0.1)
    raise ValueError("LIVE_MCP_PROVENANCE_INVALID: listener is not the managed process")


def stage_prerequisites(config, directory, case, command, *, check_head):
    """Validate real owner/Host evidence before allowing the exact Revit stage pause."""

    from design_execution_reconciliation.contracts import (
        SemanticVerificationResult,
        VerificationEvidenceBundle,
    )
    from design_orchestrator.execution_collection_artifacts import (
        ExecutionGrantCollectionManifest,
        ProviderBindingCollectionManifest,
    )

    from .cross_host_product_live_composition import reviewed_runtime_inputs
    from .cross_host_product_live_stages import (
        require_all_ready,
        require_autocad_committed_delta,
        stage_hash,
    )

    check_head()
    if any((directory / name).exists() for name in (
        "pending-stage.json", "stage-controller-completion.json", "stage-release.json",
        "stage-send-attempt.json",
    )):
        raise ValueError("LIVE_STAGE_PRESELECTED: stage/action already exists")
    frozen = read_json(directory / "frozen-submission.json")
    binding = frozen["session_binding"]
    request = frozen["request"]
    member = next(item for item in binding["members"] if item["host_kind"] == "REVIT")
    _, topology, _ = reviewed_runtime_inputs(
        config, read_json(directory / "driver-settings.json"), case["scenario"]
    )
    captures = validate_owner_snapshots(_jsonl(directory / "owner-captures.jsonl"), topology)
    if (
        len(captures["execution_plan"]) != 1
        or len(captures["materialization_plan"]) != 1
        or len(captures["binding_set"]) != 2
        or len(captures["grant"]) != 2
        or len(captures["approval"]) != 1
    ):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: two admitted required members absent")
    plan = captures["execution_plan"][0]
    materialization = captures["materialization_plan"][0]
    if [item.host_runtime_ref.host_type for item in plan.execution_slices] != [
        "autocad", "revit"
    ] or materialization.topology_snapshot_hash != binding["topology_snapshot_hash"]:
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: frozen required order differs")
    raw, accepted, _, sagas, _ = _read_durable_owners(config, request["task_id"])
    expected_sagas = 0 if case["scenario"] == "unavailable" else 1
    if (accepted is None or plain(accepted.request) != request
        or dict(accepted.session_binding_payload) != binding
        or len(sagas) != expected_sagas):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: durable task/Saga lineage absent")
    artifacts = validate_workflow_rows(raw["artifacts"])
    bindings = [value for value in artifacts.values()
                if isinstance(value, ProviderBindingCollectionManifest)]
    grants = [value for value in artifacts.values()
              if isinstance(value, ExecutionGrantCollectionManifest)]
    if len(bindings) != 1 or len(grants) != 1:
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: durable collection manifests absent")
    validate_collection_capture(
        plan, bindings[0], grants[0], captures["binding_set"], captures["grant"]
    )
    proposal = read_json(directory / "pending-proposal.json")["proposal"]
    if (
        proposal["frozen"]["request"] != request
        or proposal["frozen"]["session_binding"] != binding
    ):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: reviewed freeze differs")
    subject = proposal["subject"]
    baseline = next(
        item for item in subject["observations"] if item["host_kind"] == "REVIT"
    )
    if (
        baseline["host_instance_id"] != member["host_instance_id"]
        or baseline["document_id"] != member["document_id"]
        or baseline["native_target_id"] != member["native_target_id"]
        or baseline["normalized_thickness_mm"] != 200
    ):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: exact 200 mm Revit baseline absent")
    commands = _jsonl(directory / "host-commands.jsonl")
    if any(row["host_kind"] == "REVIT" and row["phase"] == "SEND"
           and row["command"].get("mode") == "EXECUTE" for row in commands):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: Revit Product command sent early")
    proof = {
        "expected_revision": baseline["host_revision"],
        "execution_plan_hash": plan.execution_plan_hash,
        "required_set_hash": materialization.required_set_hash,
        "binding_manifest_hash": stage_hash(plain(bindings[0])),
        "grant_manifest_hash": stage_hash(plain(grants[0])),
        "approval_hash": captures["approval"][0].approval_hash,
    }
    if case["scenario"] == "unavailable":
        if any(row["phase"] == "SEND" and row["command"].get("mode") == "EXECUTE"
               for row in commands):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: mutation before unavailable stage")
        if command.operation != "check_wall_thickness_readiness":
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: first readiness not intercepted")
        auto_member = SimpleNamespace(**next(item for item in binding["members"]
                                             if item["host_kind"] == "AUTOCAD"))
        auto_baseline = next(
            item for item in subject["observations"] if item["host_kind"] == "AUTOCAD"
        )
        auto_reads = [row for row in commands if row["host_kind"] == "AUTOCAD"
                      and row["phase"] == "RECEIVE" and row.get("stage") == "MCP"
                      and row["command"].get("operation")
                      == "design.extract_native_snapshot"]
        if not auto_reads or width_from_read(auto_reads[-1], auto_member) != (
            {"value": 200, "unit": "mm"}, auto_baseline["host_revision"]
        ):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: available readiness READ absent")
        proof["autocad_readiness_read_hash"] = stage_hash(auto_reads[-1])
    else:
        readiness = captures["readiness"]
        ready_hashes = require_all_ready(
            readiness, materialization, captures["grant"], subject["observations"]
        )
        if command.preconditions != [{"revision": baseline["host_revision"]}]:
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: original revision drift")
        evidence = validate_reconciliation_rows(raw["evidence"])
        auto_slice = plan.execution_slices[0]
        delta = require_autocad_committed_delta(
            evidence, config.autocad_host_instance_id, auto_slice.execution_slice_hash
        )
        bundles = [body for body in evidence.values()
                   if isinstance(body, VerificationEvidenceBundle)
                   and body.actual_delta_hash == delta.actual_delta_hash]
        if len(bundles) != 1:
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: AutoCAD bundle absent")
        bundle = bundles[0]
        verifications = [body for body in evidence.values()
                         if isinstance(body, SemanticVerificationResult)
                         and body.evidence_bundle_hash == bundle.evidence_bundle_hash]
        if len(verifications) != 1 or verifications[0].status.value != "PASSED":
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: AutoCAD verification absent")
        width = [item.properties.get("dsp:WallThickness", {}).get("value")
                 for item in bundle.subject_evidence]
        auto_baseline = next(
            item for item in subject["observations"] if item["host_kind"] == "AUTOCAD"
        )
        if (
            width != [300]
            or delta.revision_before != auto_baseline["host_revision"]
            or delta.revision_after != delta.revision_before + 1
            or bundle.base_host_revision != str(delta.revision_after)
            or verifications[0].execution_slice_hash != auto_slice.execution_slice_hash
            or verifications[0].actual_delta_hash != delta.actual_delta_hash
        ):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: committed 300 mm absent")
        dispatch = [row for row in raw["dispatches"]
                    if row["execution_slice_hash"] == auto_slice.execution_slice_hash]
        if (len(dispatch) != 1 or dispatch[0]["status"] not in {
            "HOST_COMMITTED", "RECONCILED"
        } or str(dispatch[0]["expected_host_revision"]) != str(delta.revision_before)):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: AutoCAD durable dispatch differs")
        auto_commands = [row for row in commands if row["host_kind"] == "AUTOCAD"]
        sends = [row for row in auto_commands if row["phase"] == "SEND"
                 and row["command"].get("mode") == "EXECUTE"]
        receives = [row for row in auto_commands if row["phase"] == "RECEIVE"
                    and row["command"].get("mode") == "EXECUTE"]
        if (len(sends) != 1 or len(receives) != 1
            or sends[0]["command"] != receives[0]["command"]
            or receives[0]["response"].get("status") != "OK"
            or receives[0]["response"].get("revision_after") != delta.revision_after):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: AutoCAD actual commit absent")
        auto_member = SimpleNamespace(**next(item for item in binding["members"]
                                             if item["host_kind"] == "AUTOCAD"))
        reads = [row for row in auto_commands if row["phase"] == "RECEIVE"
                 and row["command"].get("operation") == "design.extract_native_snapshot"
                 and commands.index(row) > commands.index(receives[0])]
        if not reads or any(width_from_read(row, auto_member) != (
            {"value": 300, "unit": "mm"}, delta.revision_after
        ) for row in reads):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: verified committed READ absent")
        proof.update({
            "all_ready_hashes": ready_hashes,
            "autocad_actual_delta_hash": delta.actual_delta_hash,
            "autocad_verification_hash": verifications[0].verification_hash,
            "autocad_commit_command_hash": stage_hash(receives[0]),
        })
    check_head()
    return proof


def run_stage_controller(config, directory, reviewed, *, check_head, stop_event=None):
    """Wait for external operator action, then publish one exact evidence-backed release."""

    from .cross_host_product_live_composition import audited_host_factories, read_host_observation
    from .cross_host_product_live_stages import (
        stage_hash,
        validate_stage_action_evidence,
        validate_stage_completion,
    )

    stop_event = stop_event or Event()
    pending_path = directory / "pending-stage.json"
    deadline = time.monotonic() + 240
    while not pending_path.is_file():
        if stop_event.is_set():
            raise ValueError("LIVE_STAGE_NOT_REACHED: original command was never presented")
        check_head()
        if time.monotonic() >= deadline:
            raise ValueError("LIVE_STAGE_NOT_REACHED: original command was never presented")
        time.sleep(0.1)
    pending = read_json(pending_path)
    print("LIVE_AWAITING_STAGE: " + str(pending_path.resolve()), flush=True)
    completion_path = directory / "stage-controller-completion.json"
    deadline = time.monotonic() + pending["deadline_seconds"] - 5
    while not completion_path.is_file():
        if stop_event.is_set():
            raise ValueError("LIVE_STAGE_ABORTED: resume ended before operator completion")
        check_head()
        if time.monotonic() >= deadline:
            raise ValueError("LIVE_STAGE_TIMEOUT: operator completion absent")
        time.sleep(0.1)
    completion = validate_stage_completion(pending, read_json(completion_path))
    action = (
        "REVIT_DOCUMENT_CLOSED_UNSAVED" if pending["scenario"] == "unavailable"
        else "REVIT_NATIVE_UI_EDIT_201MM"
    )
    # 与实际发送侧使用同一门槛；partial 的独立 READ 在本流程执行后再统一校验。
    if completion.get("action") != action:
        raise ValueError("LIVE_STAGE_RELEASE_INVALID: scenario operator action differs")
    if pending["scenario"] == "partial_commit":
        binding = reviewed.frozen.session_binding
        member = next(item for item in binding.members if item.host_kind == "REVIT")
        factories = audited_host_factories(
            config, directory, check_head=check_head, stage="INDEPENDENT_EDIT_READ"
        )
        observed = read_host_observation(
            config, member, target=binding, factories=factories,
            command_id=pending["stage_id"] + ":independent-edit-read",
        )
        if (
            observed.normalized_thickness_mm != 201
            or observed.host_revision <= pending["expected_revision"]
            or observed.host_instance_id != pending["host_instance_id"]
            or observed.document_id != pending["document_id"]
            or observed.native_target_id != pending["native_target_id"]
        ):
            raise ValueError("LIVE_STAGE_EDIT_INVALID: real 201 mm advanced-revision READ absent")
        write_once(directory / "independent-edit-observation.json", plain(observed))
    # 在发布 release 前，仍应复核原始 audit SEND/RECEIVE 与持久化 observation。
    validate_stage_action_evidence(directory, pending, completion)
    check_head()
    write_once(directory / "stage-release.json", {
        "stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"], "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": stage_hash(completion),
        "proof_hash": stage_hash(pending["prerequisite_hashes"]),
    })
    return pending



def read_unavailable_exact_task_without_host_io(client, task_id, directory):
    """真实 MCP 同一 task GET 必须保持 Host 调用数量为零。

    GET 是 owner 状态查询；不得因为 REQUIRED Revit 已不可达而重查 Host，
    也不得切换到 latest-task fallback 或创建业务命令。
    """

    before = len(_jsonl(directory / "host-commands.jsonl"))
    final = asyncio.run(client.get(task_id))
    after = len(_jsonl(directory / "host-commands.jsonl"))
    if after != before or getattr(final, "task_id", None) != task_id:
        raise ValueError(
            "LIVE_GET_HOST_IO_INVALID: exact GET changed Host audit or task identity"
        )
    write_once(
        directory / "host-independent-get.json",
        {
            "task_id": task_id,
            "before": before,
            "after": after,
            "result": plain(final),
        },
    )
    return final


def run_phase_one(config, scenario):
    """真实 model→freeze→managed MCP→显式人工→resume→owner collect 的唯一 live 路径。"""

    sys.path[:0] = worktree_source_paths()
    audit_imported_product_sources()

    from design_orchestrator.artifact_postgres import create_postgres_artifact_store
    from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
    from design_orchestrator.langgraph_checkpoint_reader import LangGraphWorkflowCheckpointReader
    from design_product_front_door import (
        FrozenSubmissionV2,
        ProductFrontDoorMcpClient,
        SqliteFrontDoorStateStore,
        SubmissionController,
        SubprocessAgentInterpreter,
    )
    from revit_sidecar import RevitCurrentContextProbe

    from .cross_host_product_live_composition import (
        append_audit,
        audited_host_factories,
        audited_pipe_ownership,
        production_probe_factory,
        read_host_observation,
        reviewed_runtime_inputs,
    )
    from .cross_host_product_v2_proposal_authority import prepare_and_read_v2_proposal

    head = current_head()
    settings = load_driver_settings(head)
    freeze_clean_head()
    model_source = validate_reviewed_model_command(config.model_command)

    def check_head():
        check_frozen_head(head)
        audit_imported_product_sources()

    check_head()
    config.verify_fixtures()
    target, topology, policy = reviewed_runtime_inputs(config, settings, scenario)
    root = os.environ.get("DSP_CROSS_HOST_PRODUCT_EVIDENCE_DIR", "").strip()
    if not root:
        raise ValueError("LIVE_EVIDENCE_MANIFEST_DIR_MISSING: controlled output directory required")
    # 模型只继承显式模型环境，绝不继承 controller DSN 或执行授权配置。
    try:
        model_environment = json.loads(os.environ.get("DSP_AGENT_MODEL_ENVIRONMENT_JSON", "{}"))
    except ValueError:
        raise ValueError("LIVE_MODEL_ENV_INVALID: expected explicit string mapping") from None
    if (
        not isinstance(model_environment, dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in model_environment.items()
        )
        or any(
            key.startswith("DSP_") and key != "DSP_AGENT_MODEL_NAME" for key in model_environment
        )
    ):
        raise ValueError("LIVE_MODEL_ENV_INVALID: controller authority must remain absent")
    if any(
        not model_environment.get(key, "").strip()
        for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
    ) or model_environment.get("ANTHROPIC_MODEL", config.model_name) != config.model_name:
        raise ValueError("LIVE_MODEL_ENV_INVALID: reviewed provider auth/base/model missing")
    _require_empty_database(config, settings["database_name"])
    parsed = urlsplit(config.mcp_url)
    with socket.socket() as reservation:
        try:
            reservation.bind((parsed.hostname, parsed.port or 80))
        except OSError:
            raise ValueError(
                "LIVE_MCP_PORT_OCCUPIED: stop external MCP before controlled case"
            ) from None
    directory = new_case_directory(Path(root), scenario=scenario, head=head)
    case = read_json(directory / "case.json")
    case_id = case["case_id"]
    write_once(directory / "driver-settings.json", settings)
    write_once(directory / "controller-python-sources.json", audit_imported_product_sources())
    write_once(directory / "model-interpreter-source.json", model_source)
    model_environment["PYTHONPATH"] = os.pathsep.join(worktree_source_paths())
    model_environment["ANTHROPIC_MODEL"] = config.model_name
    model_environment["DSP_MODEL_CANDIDATE_KEY"] = target.candidate_key
    model_environment["DSP_MODEL_EVIDENCE_FILE"] = str(
        (directory / "model-provider-invocation.json").resolve()
    )
    factories = audited_host_factories(config, directory, check_head=check_head, stage="CONTROLLER")

    class TargetSource:
        def get(self, candidate_key):
            return target if candidate_key == target.candidate_key else None

    class AuditedModel(SubprocessAgentInterpreter):
        def interpret(self, **kwargs):
            check_head()
            result = super().interpret(**kwargs)
            provider = validate_model_provider_record(
                read_json(directory / "model-provider-invocation.json"),
                client_submission_ref=kwargs["client_submission_ref"],
                model_name=config.model_name,
                candidate_key=target.candidate_key,
                result=result,
            )
            check_head()
            append_audit(
                directory / "model-invocations.jsonl",
                {
                    "model_name": config.model_name,
                    "client_submission_ref": kwargs["client_submission_ref"],
                    "interpreter": "design_product_front_door.agent.SubprocessAgentInterpreter",
                    "invocation_kind": "ANTHROPIC_SDK_PROVIDER_RESPONSE",
                    "invocation_id": provider["invocation_id"],
                    "request_id": provider["request_id"],
                    "response_model": provider["response_model"],
                    "usage": provider["usage"],
                    "interpreter_source_sha256": model_source["sha256"],
                    "controller_authority_env_absent": True,
                },
            )
            return result

    with ExitStack() as resources:
        resources.enter_context(
            audited_pipe_ownership(
                config, directory, stage="CONTROLLER", check_head=check_head
            )
        )
        state = SqliteFrontDoorStateStore(str(directory / "front-door.sqlite3"))
        resources.callback(state.close)
        controller = SubmissionController(
            state_store=state,
            agent_interpreter=AuditedModel(
                command=config.model_command, environment=model_environment
            ),
            candidate_source=TargetSource(),
            context_probe_factory=lambda locator: RevitCurrentContextProbe(factories[1](locator)),
            session_ref_factory=lambda: "session-" + uuid4().hex,
            task_id_factory=lambda: "task-" + uuid4().hex,
            cross_host_target_source=TargetSource(),
            cross_host_probe_factory=production_probe_factory(config, target, factories, directory),
        )
        client_submission_ref = "submission-" + uuid4().hex
        frozen = controller.prepare_cross_host_submission(
            client_submission_ref=client_submission_ref, utterance=settings["utterance"]
        )
        if not isinstance(frozen, FrozenSubmissionV2):
            raise ValueError("LIVE_V2_MODEL_CLARIFICATION_REQUIRED: model did not freeze request")
        if frozen.request.intent_arguments["thickness"] != {"value": 300, "unit": "mm"}:
            raise ValueError("LIVE_MODEL_INTENT_INVALID: approved case requires 300 mm")
        write_once(directory / "frozen-submission.json", plain(frozen))
        plugins = {}
        for member in frozen.session_binding.members:
            expected = (
                config.autocad_build_identity
                if member.host_kind == "AUTOCAD"
                else config.revit_build_identity
            )
            plugins[member.host_kind] = validate_loaded_module(
                inspect_loaded_module(member.transport_locator, member.host_kind),
                host_kind=member.host_kind,
                locator=member.transport_locator,
                host_instance_id=member.host_instance_id,
                expected_sha=expected,
                head=head,
            )
        write_once(directory / "loaded-plugin-provenance.json", plugins)
        managed = resources.enter_context(
            ManagedMcpProcess(directory, case_id=case_id, head=head, check_head=check_head)
        )
        _wait_managed_catalog(config, managed, check_head)
        saver = create_postgres_checkpointer(config.dsn)
        resources.callback(saver.close)
        artifacts = create_postgres_artifact_store(config.dsn)
        resources.callback(artifacts.close)
        checkpoints = LangGraphWorkflowCheckpointReader(checkpointer=saver)
        client = ProductFrontDoorMcpClient(config.mcp_url)
        reviewed = asyncio.run(
            prepare_and_read_v2_proposal(
                submission_controller=controller,
                mcp_client=client,
                checkpoint_reader=checkpoints,
                artifact_reader=artifacts,
                client_submission_ref=client_submission_ref,
                utterance=settings["utterance"],
            )
        )
        check_head()
        publish_pending_proposal(directory, reviewed, case_id=case_id, head=head)
        print(
            "LIVE_AWAITING_HUMAN: " + str((directory / "pending-proposal.json").resolve()),
            flush=True,
        )
        decision = await_human_decision(
            directory,
            reviewed,
            case_id=case_id,
            head=head,
            timeout_seconds=settings["human_timeout_seconds"],
            check_head=check_head,
        )
        human_body = read_json(directory / "human-decision.json")
        with ThreadPoolExecutor(max_workers=1) as stage_pool:
            stage_stop = Event()
            stage_future = (
                stage_pool.submit(
                    run_stage_controller, config, directory, reviewed,
                    check_head=check_head, stop_event=stage_stop,
                )
                if scenario in {"unavailable", "partial_commit"}
                else None
            )
            try:
                try:
                    final = asyncio.run(
                        resume_once(
                            directory,
                            reviewed,
                            decision,
                            human_body=human_body,
                            check_head=check_head,
                            mcp_client=client,
                            checkpoint_reader=checkpoints,
                            artifact_reader=artifacts,
                        )
                    )
                except RuntimeError:
                    # deny/unavailable retain owner truth after actual fail-closed response.
                    if scenario not in {"deny", "unavailable"}:
                        raise
                    final = asyncio.run(client.get(frozen.request.task_id))
                if stage_future is not None:
                    stage_future.result()
            finally:
                stage_stop.set()
        if scenario == "unavailable":
            # The reviewed Revit document is still closed. Prove exact GET is Host-free.
            final = read_unavailable_exact_task_without_host_io(
                client, frozen.request.task_id, directory
            )
        final_factories = audited_host_factories(
            config, directory, check_head=check_head, stage="INDEPENDENT_FINAL"
        )
        for member in frozen.session_binding.members:
            if scenario == "unavailable" and member.host_kind == "REVIT":
                continue
            read_host_observation(
                config,
                member,
                target=frozen.session_binding,
                factories=final_factories,
                command_id=case_id + ":independent-final:" + member.host_kind.lower(),
            )
        check_head()
        config.verify_fixtures()
        return collect_formal_evidence(
            config, directory, reviewed, final, checkpoints, topology, policy, plugins, check_head
        )


def validate_workflow_rows(rows):
    """验证实际 durable Workflow artifact 的版本、body 与原 content hash。"""

    from design_orchestrator.workflow_artifacts import (
        decode_workflow_artifact,
        workflow_artifact_content_hash,
    )

    result = {}
    try:
        for row in rows:
            value = decode_workflow_artifact(
                kind=row["kind"], codec_version=row["codec_version"], payload=row["payload"]
            )
            if (
                row["artifact_id"] in result
                or workflow_artifact_content_hash(value) != row["content_hash"]
            ):
                raise ValueError("durable artifact identity mismatch")
            result[row["artifact_id"]] = value
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_OWNER_ARTIFACT_INVALID: durable body/ref/hash mismatch") from exc


def _read_durable_owners(config, task_id):
    """通过原 owner public READ 及只读 PostgreSQL snapshot 收集 exact 当前事实。"""

    import psycopg
    from design_execution_reconciliation.postgres_dispatch_intent import (
        PostgresHostDispatchIntentStore,
    )
    from design_execution_reconciliation.postgres_saga_store_v2 import PostgresExecutionSagaStoreV2
    from design_orchestrator.proposal_decision_postgres import PostgresProposalDecisionStore
    from design_product_front_door import PostgresConfiguredPolicyAdmissionStore
    from design_product_runtime import create_postgres_product_task_request_store
    from psycopg.rows import dict_row

    tables = {
        "requests": "product_task.request",
        "decisions": "orchestrator_proposal.decision",
        "artifacts": "orchestrator_artifact.workflow_artifact",
        "sagas": "execution_saga.saga_v2",
        "dispatches": "execution_saga.host_dispatch_intent",
        "evidence": "execution_saga.reconciliation_evidence",
        "admissions": "product_policy.admission",
    }
    with psycopg.connect(config.dsn, autocommit=True, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            raw = {
                kind: connection.execute("SELECT * FROM " + table).fetchall()
                for kind, table in tables.items()
            }
    with ExitStack() as resources:
        requests = create_postgres_product_task_request_store(config.dsn)
        resources.callback(requests.close)
        decisions = PostgresProposalDecisionStore(config.dsn)
        resources.callback(decisions.close)
        sagas = PostgresExecutionSagaStoreV2(config.dsn)
        resources.callback(sagas.close)
        dispatches = PostgresHostDispatchIntentStore(config.dsn)
        resources.callback(dispatches.close)
        admissions = PostgresConfiguredPolicyAdmissionStore(config.dsn)
        resources.callback(admissions.close)
        accepted = requests.get_v2(task_id)
        decision = decisions.get_for_task(task_id)
        decoded_sagas = [sagas.get_saga(row["saga_id"]) for row in raw["sagas"]]
        for row in raw["dispatches"]:
            actual = dispatches.get_for_saga_slice(row["saga_id"], row["execution_slice_hash"])
            if actual is None or any(
                str(row[key]) != str(plain(actual)[key])
                for key in (
                    "dispatch_intent_id",
                    "saga_id",
                    "execution_slice_hash",
                    "grant_hash",
                    "binding_set_hash",
                    "host_instance_id",
                    "document_ref",
                    "idempotency_key",
                    "expected_host_revision",
                    "status",
                )
            ):
                raise ValueError("LIVE_OWNER_DISPATCH_INVALID: public owner READ differs from row")
        decoded_admissions = [
            admissions.get_v2(
                changeset_hash=row["changeset_hash"], approved_scope_hash=row["approved_scope_hash"]
            )
            for row in raw["admissions"]
        ]
    return raw, accepted, decision, decoded_sagas, decoded_admissions


def validate_positive_owner_lineage(
    changeset, scope, materialization, plan, grants, approval, saga, final, checkpoint
):
    """拒绝单独 hash 合法但属于另一条 authority 链的 owner body。"""

    if (
        saga.definition.required_set_hash != materialization.required_set_hash
        or saga.definition.approved_scope_hash != scope.scope_hash
        or checkpoint.execution_plan_ref is None
        or checkpoint.execution_plan_ref.ref_id != plan.execution_plan_id
        or checkpoint.execution_plan_ref.content_hash != plan.execution_plan_hash
        or len(grants) != 2
        or len(saga.slice_states) != 2
        or len(final.materializations) != 2
    ):
        raise ValueError("LIVE_OWNER_AUTHORITY_INVALID: required set/checkpoint authority differs")
    for grant, state, query in zip(grants, saga.slice_states, final.materializations, strict=True):
        if (
            grant.approval_hash != approval.approval_hash
            or grant.changeset_hash != changeset.changeset_hash
            or grant.approved_scope_hash != scope.scope_hash
            or grant.materialization_plan_hash != materialization.materialization_plan_hash
            or state.status.value != "SUCCEEDED"
            or state.execution_slice_hash != query.execution_slice_hash
            or state.materialization_id != query.materialization_id
            or state.execution_slice_hash != grant.execution_slice_hash
            or state.materialization_id != grant.materialization_id
            or state.approval_hash != grant.approval_hash
            or state.grant_hash != grant.grant_hash
            or state.binding_set_hash != grant.binding_set_hash
            or state.admitted_host_instance_id != grant.host_instance_id
            or state.actual_delta_hash != query.actual_delta_hash
            or state.verification_hash != query.verification_hash
        ):
            raise ValueError("LIVE_OWNER_AUTHORITY_INVALID: exact Slice grant/Saga/query differs")


def validate_positive_convergence_capture(
    rows, materialization, execution_plan, profile, evidence, saga, final
):
    """Rebuild the captured full set from exact local Step33 bodies; never rerun verify."""

    from design_convergence import (
        ConvergenceResult,
        build_convergence_evidence_set,
        build_materialization_canonical_evidence,
        compute_convergence_profile_hash,
        compute_convergence_result_hash,
    )
    from pydantic import TypeAdapter

    def same_body(left, right):
        options = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
        return json.dumps(left, **options) == json.dumps(right, **options)

    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("LIVE_CONVERGENCE_CAPTURE_MISSING: one public verifier call required")
    row = rows[0]
    try:
        if not same_body(row["plan"], plain(materialization)) or not same_body(
            row["profile"], plain(profile)
        ):
            raise ValueError("captured plan/profile differs")
        if (
            compute_convergence_profile_hash(profile.profile_version, profile.field_rules)
            != profile.profile_hash
            or profile.profile_hash != materialization.convergence_profile_hash
        ):
            raise ValueError("captured profile hash differs")
        queries = {item.materialization_id: item for item in final.materializations}
        slices = {item.materialization_id: item for item in execution_plan.execution_slices}
        if len(queries) != 2 or set(queries) != set(slices):
            raise ValueError("captured required set differs")
        items = []
        for materialization_id, execution_slice in slices.items():
            query = queries[materialization_id]
            if query.execution_slice_hash != execution_slice.execution_slice_hash:
                raise ValueError("captured execution slice differs")
            items.append(
                build_materialization_canonical_evidence(
                    materialization_id=materialization_id,
                    execution_slice=execution_slice,
                    actual_delta=require_evidence_body(
                        evidence, query.actual_delta_hash, "actual_delta"
                    ),
                    verification_result=require_evidence_body(
                        evidence, query.verification_hash, "verification_result"
                    ),
                    verification_evidence_bundle=require_evidence_body(
                        evidence, query.evidence_bundle_hash, "verification_bundle"
                    ),
                    convergence_profile=profile,
                )
            )
        rebuilt = build_convergence_evidence_set(
            plan=materialization, profile=profile, evidence_items=items
        )
        if not same_body(row["evidence_set"], plain(rebuilt)):
            raise ValueError("captured full evidence set differs from local Step33 bodies")
        result = TypeAdapter(ConvergenceResult).validate_python(row["result"])
        if (
            not same_body(row["result"], plain(result))
            or result.status.value != "CONVERGED"
            or result.materialization_plan_hash != materialization.materialization_plan_hash
            or result.required_set_hash != materialization.required_set_hash
            or result.convergence_profile_hash != profile.profile_hash
            or result.evidence_set_hash != rebuilt.evidence_set_hash
            or compute_convergence_result_hash(result) != result.convergence_result_hash
            or result.convergence_result_hash != saga.convergence_result_hash
            or result.convergence_result_hash != final.convergence_result_hash
        ):
            raise ValueError("captured verifier result/Saga/query differs")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_CONVERGENCE_INVALID: public verifier inputs/result differ") from exc
    return row


def _capture_profile(directory, materialization):
    """Decode the public verifier's exact profile; plan hash is checked before use."""

    from design_convergence import ConvergenceComparisonProfile, compute_convergence_profile_hash
    from pydantic import TypeAdapter

    rows = _jsonl(directory / "convergence-captures.jsonl")
    if len(rows) != 1:
        raise ValueError("LIVE_CONVERGENCE_CAPTURE_MISSING: one public verifier call required")
    try:
        profile = TypeAdapter(ConvergenceComparisonProfile).validate_python(rows[0]["profile"])
        if (
            profile.profile_hash != materialization.convergence_profile_hash
            or compute_convergence_profile_hash(profile.profile_version, profile.field_rules)
            != profile.profile_hash
        ):
            raise ValueError("profile hash differs")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_CONVERGENCE_PROFILE_INVALID: captured profile differs") from exc
    return profile


def collect_formal_evidence(
    config, directory, reviewed, final, checkpoints, topology, policy, plugins, check_head
):
    """所有字段来自本次 production owners/actual command，完整验证后才落正式 manifest。"""

    from design_execution_reconciliation.saga_contracts_v2 import (
        compute_execution_saga_definition_hash_v2,
    )
    from design_execution_reconciliation.saga_persistence_v2 import decode_stored_saga_v2
    from design_gateway_authorization import compute_admission_fingerprint
    from design_orchestrator.execution_collection_artifacts import (
        ExecutionGrantCollectionManifest,
        ProviderBindingCollectionManifest,
    )
    from design_orchestrator.proposal_decision import HumanDecisionState, ProposalContinuationState
    from design_product_front_door import ConfiguredProductApprovalPolicyV2
    from design_product_runtime import ProductProposalStateV2, ProductTaskQueryViewV2

    check_head()
    case = read_json(directory / "case.json")
    head, scenario, case_id = case["implementation_head"], case["scenario"], case["case_id"]
    check_frozen_head(head)
    ready = read_json(directory / "mcp-ready.json")
    if ready.get("case_id") != case_id or ready.get("implementation_head") != head:
        raise ValueError(
            "LIVE_MCP_PROVENANCE_INVALID: archived composition belongs to another case"
        )
    validate_python_source_manifest(ready.get("python_sources"))
    validate_python_source_manifest(read_json(directory / "controller-python-sources.json"))
    write_once(directory / "final-python-sources.json", audit_imported_product_sources())
    request, binding = reviewed.frozen.request, reviewed.frozen.session_binding
    human = read_json(directory / "human-decision.json")
    load_human_decision(directory / "human-decision.json", reviewed, case_id=case_id, head=head)
    if not (directory / "resume-attempt.json").is_file():
        raise ValueError("LIVE_HUMAN_RESUME_UNPROVEN: durable attempt absent")
    if read_json(directory / "resume-attempt.json").get("human_decision") != human:
        raise ValueError("LIVE_HUMAN_DECISION_STALE: supplied decision changed after attempt")
    raw, accepted, decision, sagas, admissions = _read_durable_owners(config, request.task_id)
    checkpoint = checkpoints.get_checkpoint(request.task_id)
    if (
        accepted is None
        or accepted.request != request
        or dict(accepted.session_binding_payload) != plain(binding)
        or len(raw["requests"]) != 1
        or raw["requests"][0]["task_id"] != request.task_id
        or raw["requests"][0]["request_hash"] != request.request_hash
        or not isinstance(final, ProductTaskQueryViewV2)
        or final.task_id != request.task_id
        or final.request_hash != request.request_hash
        or final.proposal_state is not ProductProposalStateV2.ACCEPTED
        or checkpoint is None
        or checkpoint.task_id != request.task_id
        or len(raw["decisions"]) != 1
        or decision is None
        or decision.task_id != request.task_id
        or decision.pause_id != reviewed.pause_id
        or decision.subject_ref != reviewed.subject_ref
        or decision.human_decision is not HumanDecisionState.ACCEPTED
        or decision.continuation is not ProposalContinuationState.CONTINUABLE
    ):
        raise ValueError(
            "LIVE_OWNER_LINEAGE_INVALID: exact accepted task/decision/query/checkpoint differs"
        )
    artifacts = validate_workflow_rows(raw["artifacts"])
    if artifacts.get(reviewed.subject_ref.ref_id) != reviewed.subject:
        raise ValueError("LIVE_OWNER_ARTIFACT_MISSING: authoritative reviewed subject unavailable")
    snapshots = _jsonl(directory / "owner-captures.jsonl")
    captures = validate_owner_snapshots(snapshots, topology)
    changeset, scope = captures["changeset"][0], captures["scope"][0]
    if (
        changeset.task_id != request.task_id
        or changeset.project_id != request.project_id
        or checkpoint.changeset_ref is None
        or checkpoint.changeset_ref.ref_id != changeset.changeset_id
        or checkpoint.changeset_ref.content_hash != changeset.changeset_hash
        or scope.topology_snapshot_hash != binding.topology_snapshot_hash
    ):
        raise ValueError("LIVE_OWNER_CAPTURE_LINEAGE_INVALID: ChangeSet/scope not current task")
    attempts = _jsonl(directory / "policy-attempts.jsonl")
    if len(attempts) != 1:
        raise ValueError("LIVE_POLICY_EVIDENCE_INVALID: one real governing policy call required")
    attempt = attempts[0]
    actual_policy = ConfiguredProductApprovalPolicyV2.from_mapping(attempt["policy"])
    if (
        actual_policy != policy
        or attempt.get("policy_snapshot_hash") != policy.policy_snapshot_hash
        or actual_policy.reviewed_configuration_hash != reviewed.frozen.reviewed_configuration_hash
        or attempt.get("task_id") != request.task_id
        or attempt.get("changeset_ref") != plain(checkpoint.changeset_ref)
        or attempt.get("scope_hash") != scope.scope_hash
    ):
        raise ValueError("LIVE_POLICY_EVIDENCE_INVALID: governing policy/task lineage differs")
    models = _jsonl(directory / "model-invocations.jsonl")
    model_source = read_json(directory / "model-interpreter-source.json")
    if model_source != validate_reviewed_model_command(config.model_command):
        raise ValueError("LIVE_MODEL_SOURCE_INVALID: interpreter source changed")
    from design_product_front_door.agent import AgentProposal

    provider = validate_model_provider_record(
        read_json(directory / "model-provider-invocation.json"),
        client_submission_ref=reviewed.frozen.client_submission_ref,
        model_name=config.model_name,
        candidate_key=read_json(directory / "driver-settings.json")["candidate_key"],
        result=AgentProposal(
            candidate_key=read_json(directory / "driver-settings.json")["candidate_key"],
            thickness_value=float(request.intent_arguments["thickness"]["value"]),
            thickness_unit=request.intent_arguments["thickness"]["unit"],
        ),
    )
    if (
        len(models) != 1
        or models[0].get("client_submission_ref") != reviewed.frozen.client_submission_ref
        or models[0].get("invocation_kind") != "ANTHROPIC_SDK_PROVIDER_RESPONSE"
        or models[0].get("invocation_id") != provider["invocation_id"]
        or models[0].get("request_id") != provider["request_id"]
        or models[0].get("response_model") != provider["response_model"]
        or models[0].get("usage") != provider["usage"]
        or models[0].get("interpreter_source_sha256") != model_source["sha256"]
        or models[0].get("controller_authority_env_absent") is not True
    ):
        raise ValueError(
            "LIVE_MODEL_EVIDENCE_INVALID: one actual production interpreter invocation required"
        )
    commands = _jsonl(directory / "host-commands.jsonl")
    if set(plugins) != {"AUTOCAD", "REVIT"}:
        raise ValueError("LIVE_PLUGIN_PROVENANCE_MISSING: required loaded plugins absent")
    for member in binding.members:
        plugin = plugins[member.host_kind]
        if (
            plugin["host_instance_id"] != member.host_instance_id
            or plugin["locator"] != member.transport_locator
        ):
            raise ValueError(
                "LIVE_PLUGIN_PROVENANCE_INVALID: exact Host pipe READ identity differs"
            )
        refreshed = validate_loaded_module(
            inspect_loaded_module(member.transport_locator, member.host_kind),
            host_kind=member.host_kind,
            locator=member.transport_locator,
            host_instance_id=member.host_instance_id,
            expected_sha=plugin["sha256"],
            head=head,
        )
        write_once(directory / ("final-plugin-" + member.host_kind.lower() + ".json"), refreshed)
    pipe_owners = validate_pipe_ownership_records(
        _jsonl(directory / "pipe-server-ownership.jsonl"), binding.members, plugins
    )
    evidence = validate_reconciliation_rows(raw["evidence"])
    result = {
        **case,
        "model_invocation_kind": "REAL",
        "model_invocation": models[0],
        "model_provider_evidence_path": str(
            (directory / "model-provider-invocation.json").resolve()
        ),
        "model_interpreter_source_path": str(
            (directory / "model-interpreter-source.json").resolve()
        ),
        "entrypoint": "MCP_PRODUCT_TASK_V2",
        "human_decision": "ACCEPTED",
        "human_decision_ref": human["decision_ref"],
        "task_id": request.task_id,
        "task_count": len(raw["requests"]),
        "saga_id": final.saga_id,
        "saga_count": len(sagas),
        "request_hash": request.request_hash,
        "session_binding_hash": binding.binding_hash,
        "topology_snapshot_hash": binding.topology_snapshot_hash,
        "proposal_subject_hash": reviewed.subject_ref.content_hash,
        "pause_id": reviewed.pause_id,
        "fixture_sha256": {
            "AUTOCAD": config.autocad_fixture_sha256,
            "REVIT": config.revit_fixture_sha256,
        },
        "autocad_build_identity": plugins["AUTOCAD"]["sha256"],
        "revit_build_identity": plugins["REVIT"]["sha256"],
        "required_host_set": ["AUTOCAD", "REVIT"],
        "required_host_downgraded": False,
        "mcp_get_status": final.status.value,
        "workflow_phase": checkpoint.phase.value,
        "execution_grant_count": len(captures["grant"]),
        "policy_snapshot_hash": policy.policy_snapshot_hash,
        "changeset_hash": changeset.changeset_hash,
        "approval_scope_hash": scope.scope_hash,
        "planning_snapshot_ref": plain(scope.planning_snapshot_ref),
        "snapshot_set_ref": plain(scope.snapshot_set_ref),
        "owner_storage_provenance": {
            "durable_owners": "POSTGRESQL",
            "captured_owners": "AUDITED_IN_MEMORY_OWNER",
        },
        "python_source_provenance_paths": [
            str((directory / name).resolve())
            for name in (
                "controller-python-sources.json",
                "mcp-ready.json",
                "final-python-sources.json",
            )
        ],
        "raw_owner_records_path": str((directory / "durable-owner-records.json").resolve()),
        "owner_capture_path": str((directory / "owner-captures.jsonl").resolve()),
        "host_command_records_path": str((directory / "host-commands.jsonl").resolve()),
        "human_decision_path": str((directory / "human-decision.json").resolve()),
        "loaded_plugin_provenance_path": str(
            (directory / "loaded-plugin-provenance.json").resolve()
        ),
        "pipe_server_ownership_path": str((directory / "pipe-server-ownership.jsonl").resolve()),
    }
    convergence = None
    if scenario == "deny":
        if _jsonl(directory / "convergence-captures.jsonl"):
            raise ValueError("LIVE_CONVERGENCE_UNEXPECTED: denied task reached verifier")
        result["policy_status"] = policy_denied_outcome(
            final_status=final.status.value,
            workflow_phase=checkpoint.phase.value,
            saga_count=len(sagas),
            dispatch_count=len(raw["dispatches"]),
            grant_count=len(captures["grant"]),
            policy_attempts=attempts,
        )
        if (
            admissions
            or evidence
            or captures["approval"]
            or any(row["command"].get("mode") == "EXECUTE" for row in commands)
        ):
            raise ValueError("LIVE_POLICY_DENY_UNPROVEN: denied task obtained authority/effect")
        hosts = independent_host_reads(reviewed, commands, expected_mm=200)
        for host in hosts.values():
            if host["verification_revision"] != host["baseline_revision"]:
                _host_failure("denied task changed baseline revision")
            host["product_mutation_count"] = 0
        result["hosts"] = hosts
        required = ("changeset", "scope")
    elif scenario == "positive":
        if (
            len(sagas) != 1
            or len(raw["sagas"]) != 1
            or len(admissions) != 1
            or len(captures["approval"]) != 1
        ):
            raise ValueError(
                "LIVE_OWNER_EVIDENCE_INVALID: exact Saga/admission/approval cardinality differs"
            )
        saga = decode_stored_saga_v2(raw["sagas"][0]["snapshot"])
        if (
            saga != sagas[0]
            or saga.definition.saga_id != final.saga_id
            or saga.definition.changeset_hash != changeset.changeset_hash
            or compute_execution_saga_definition_hash_v2(saga.definition)
            != saga.definition.saga_definition_hash
            or saga.status.value != "SUCCEEDED"
            or saga.convergence_outcome.value != "CONVERGED"
            or saga.convergence_result_hash != final.convergence_result_hash
            or final.status.value != "SUCCEEDED"
            or checkpoint.phase.value != "COMPLETED"
        ):
            raise ValueError(
                "LIVE_OWNER_SAGA_INVALID: final convergence/Saga/query lineage differs"
            )
        admission = admissions[0]
        approval = captures["approval"][0]
        if (
            admission is None
            or ConfiguredProductApprovalPolicyV2.from_mapping(admission.policy_snapshot_payload)
            != policy
            or compute_admission_fingerprint(admission.admission)
            != admission.admission.admission_fingerprint
            or admission.admission.changeset_hash != changeset.changeset_hash
            or admission.admission.approved_scope_hash != scope.scope_hash
            or approval.admission_id != admission.admission.admission_id
            or approval.admission_fingerprint != admission.admission.admission_fingerprint
            or checkpoint.approval_ref is None
            or checkpoint.approval_ref.content_hash != approval.approval_hash
        ):
            raise ValueError("LIVE_OWNER_APPROVAL_INVALID: durable admission/approval body differs")
        if (
            len(captures["execution_plan"]) != 1
            or len(captures["materialization_plan"]) != 1
            or len(captures["readiness"]) != 1
        ):
            raise ValueError(
                "LIVE_OWNER_CAPTURE_MISSING: positive execution/readiness bodies absent"
            )
        plan = captures["execution_plan"][0]
        materialization = captures["materialization_plan"][0]
        if (
            saga.definition.execution_plan_hash != plan.execution_plan_hash
            or saga.definition.materialization_plan_hash
            != materialization.materialization_plan_hash
            or tuple(item.execution_slice_hash for item in plan.execution_slices)
            != saga.definition.ordered_slice_hashes
            or [item.host_runtime_ref.host_type for item in plan.execution_slices]
            != ["autocad", "revit"]
            or len(materialization.intents) != 2
            or materialization.topology_snapshot_hash != binding.topology_snapshot_hash
        ):
            raise ValueError(
                "LIVE_OWNER_CAPTURE_LINEAGE_INVALID: one exact required plan/order absent"
            )
        binding_manifests = [
            item
            for item in artifacts.values()
            if isinstance(item, ProviderBindingCollectionManifest)
        ]
        grant_manifests = [
            item
            for item in artifacts.values()
            if isinstance(item, ExecutionGrantCollectionManifest)
        ]
        if len(binding_manifests) != 1 or len(grant_manifests) != 1:
            raise ValueError("LIVE_OWNER_ARTIFACT_MISSING: durable collection manifests absent")
        validate_collection_capture(
            plan,
            binding_manifests[0],
            grant_manifests[0],
            captures["binding_set"],
            captures["grant"],
        )
        grants_by_slice = {item.execution_slice_hash: item for item in captures["grant"]}
        validate_positive_owner_lineage(
            changeset,
            scope,
            materialization,
            plan,
            [grants_by_slice[item] for item in saga.definition.ordered_slice_hashes],
            approval,
            saga,
            final,
            checkpoint,
        )
        convergence = validate_positive_convergence_capture(
            _jsonl(directory / "convergence-captures.jsonl"),
            materialization,
            plan,
            # The verified public profile is reconstructed from the exact capture only
            # after checking its hash against the materialization plan.
            _capture_profile(directory, materialization),
            evidence,
            saga,
            final,
        )
        readiness = captures["readiness"][0]
        if (
            readiness.status.value != "READY"
            or len(readiness.receipts) != 2
            or {item.execution_slice_hash for item in readiness.receipts}
            != set(saga.definition.ordered_slice_hashes)
        ):
            raise ValueError("LIVE_OWNER_READINESS_INVALID: actual all-required READY absent")
        for receipt in readiness.receipts:
            grants = [item for item in captures["grant"] if item.grant_hash == receipt.grant_hash]
            if (
                receipt.status.value != "READY"
                or len(grants) != 1
                or grants[0].binding_set_hash != receipt.binding_set_hash
                or grants[0].execution_slice_hash != receipt.execution_slice_hash
                or grants[0].host_instance_id != receipt.host_runtime_ref.host_instance_id
                or receipt.materialization_plan_hash != materialization.materialization_plan_hash
                or receipt.materialization_id != grants[0].materialization_id
                or receipt.observed_revision
                != next(
                    item.host_revision
                    for item in reviewed.subject.observations
                    if item.host_kind.lower() == receipt.host_runtime_ref.host_type
                )
            ):
                raise ValueError("LIVE_OWNER_READINESS_INVALID: readiness/grant authority differs")
        result.update(
            hosts=project_positive_hosts(reviewed, final, raw["dispatches"], evidence, commands),
            required_slice_count=len(plan.execution_slices),
            readiness_status=readiness.status.value,
            convergence_status=saga.convergence_outcome.value,
            saga_status=saga.status.value,
            required_set_hash=materialization.required_set_hash,
            execution_plan_hash=plan.execution_plan_hash,
            materialization_plan_hash=materialization.materialization_plan_hash,
            convergence_result_hash=saga.convergence_result_hash,
            convergence_evidence_set_hash=convergence["evidence_set"]["evidence_set_hash"],
            convergence_capture_path=str((directory / "convergence-captures.jsonl").resolve()),
            policy_status="ADMITTED",
        )
        required = (
            "changeset",
            "scope",
            "execution_plan",
            "materialization_plan",
            "binding_set",
            "grant",
            "approval",
            "readiness",
        )
    elif scenario in {"unavailable", "partial_commit"}:
        if (
            len(admissions) != 1
            or len(captures["approval"]) != 1
            or attempt.get("status") != "ADMITTED"
            or _jsonl(directory / "convergence-captures.jsonl")
        ):
            raise ValueError("LIVE_STAGE_OWNER_INVALID: admission/convergence differs")
        bindings = [item for item in artifacts.values()
                    if isinstance(item, ProviderBindingCollectionManifest)]
        grants = [item for item in artifacts.values()
                  if isinstance(item, ExecutionGrantCollectionManifest)]
        if (
            len(captures["execution_plan"]) != 1
            or len(captures["materialization_plan"]) != 1
            or len(bindings) != 1 or len(grants) != 1
        ):
            raise ValueError("LIVE_STAGE_OWNER_INVALID: exact collection manifests absent")
        validate_collection_capture(
            captures["execution_plan"][0], bindings[0], grants[0],
            captures["binding_set"], captures["grant"],
        )
        staged = project_staged_outcome(
            directory, reviewed, final, checkpoint, sagas, raw, evidence, captures, commands
        )
        result.update(staged)
        result.update(
            policy_status="ADMITTED",
            required_set_hash=captures["materialization_plan"][0].required_set_hash,
            execution_plan_hash=captures["execution_plan"][0].execution_plan_hash,
            materialization_plan_hash=(
                captures["materialization_plan"][0].materialization_plan_hash
            ),
        )
        required = (
            "changeset", "scope", "execution_plan", "materialization_plan",
            "binding_set", "grant", "approval", "readiness",
        )
    else:
        raise ValueError("LIVE_SCENARIO_INVALID: unsupported formal projection")
    write_once(
        directory / "durable-owner-records.json",
        {
            "raw_rows": raw,
            "checkpoint": plain(checkpoint),
            "proposal_decision": plain(decision),
            "accepted_input": {
                "request": plain(accepted.request),
                "session_binding_payload": dict(accepted.session_binding_payload),
            },
            "final_mcp_get": plain(final),
            "audited_owner_snapshots": snapshots,
            "actual_pipe_server_ownership": pipe_owners,
            "actual_convergence_capture": convergence,
        },
    )
    check_head()
    return publish_validated_evidence(
        directory,
        result=result,
        owner_snapshots=snapshots,
        topology=topology,
        required_capture_kinds=required,
    )
