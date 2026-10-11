"""Case-specific, test-side handoff at an existing production Host send seam.

The MCP/Win32 transports remain the only execution ports. This small bridge exists
because those libraries cannot bind an external operator's exact case, task and
command to a local acceptance pause.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

STAGE_DEADLINE_SECONDS = 180
MCP_READ_TIMEOUT_SECONDS = 300
MCP_TIMEOUT_MARGIN_SECONDS = 30


def stage_hash(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def stage_budget_seconds(caller_started_at):
    """Leave a 30s margin inside the installed MCP SDK's 300s read timeout."""

    started = datetime.fromisoformat(caller_started_at.replace("Z", "+00:00"))
    if started.tzinfo is None:
        raise ValueError("LIVE_STAGE_TIMEOUT: caller start lacks timezone")
    elapsed = (datetime.now(UTC) - started).total_seconds()
    remaining = min(
        STAGE_DEADLINE_SECONDS,
        MCP_READ_TIMEOUT_SECONDS - MCP_TIMEOUT_MARGIN_SECONDS - elapsed,
    )
    if remaining <= 0:
        raise ValueError("LIVE_STAGE_TIMEOUT: caller transport budget exhausted")
    return remaining


def stage_identity(case, request, member, command, *, prerequisite_hashes,
                   caller_started_at=None):
    """Bind the unmodified command to the frozen case and reviewed Revit member."""

    body = command.to_dict()
    scenario = case["scenario"]
    required = {
        "unavailable": ("READ", "check_wall_thickness_readiness"),
        "partial_commit": ("EXECUTE", "set_wall_thickness"),
    }
    expected = required.get(scenario)
    refs = body.get("target_native_refs")
    if (
        expected is None
        or (body.get("mode"), body.get("operation")) != expected
        or body.get("document_id") != member["document_id"]
        or not isinstance(refs, list)
        or len(refs) != 1
        or refs[0] != {
            "document_id": member["document_id"],
            "native_id": member["native_target_id"],
            "native_type": "Wall",
        }
        or not isinstance(body.get("command_id"), str)
        or not body["command_id"]
        or not prerequisite_hashes
    ):
        raise ValueError("LIVE_STAGE_COMMAND_INVALID: original Revit command/identity differs")
    revisions = body.get("preconditions", [])
    if scenario == "partial_commit" and (
        not isinstance(revisions, list)
        or len(revisions) != 1
        or set(revisions[0]) != {"revision"}
        or isinstance(revisions[0]["revision"], bool)
        or not isinstance(revisions[0]["revision"], int)
    ):
        raise ValueError("LIVE_STAGE_COMMAND_INVALID: immutable expected revision absent")
    expected_revision = (
        revisions[0]["revision"] if scenario == "partial_commit"
        else prerequisite_hashes.get("expected_revision")
    )
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise ValueError("LIVE_STAGE_COMMAND_INVALID: readiness revision absent")
    pending = {
        "stage_id": uuid4().hex,
        "case_id": case["case_id"],
        "scenario": scenario,
        "implementation_head": case["implementation_head"],
        "task_id": request["task_id"],
        "request_hash": request["request_hash"],
        "session_binding_hash": request["session_binding_hash"],
        "host_kind": "REVIT",
        "host_instance_id": member["host_instance_id"],
        "document_id": member["document_id"],
        "native_target_id": member["native_target_id"],
        "operation": body["operation"],
        "original_command_id": body["command_id"],
        "expected_revision": expected_revision,
        "original_command_hash": stage_hash(body),
        "prerequisite_hashes": prerequisite_hashes,
        "published_at": datetime.now(UTC).isoformat(),
        "deadline_seconds": (
            STAGE_DEADLINE_SECONDS if caller_started_at is None
            else stage_budget_seconds(caller_started_at)
        ),
    }
    return {**pending, "pending_hash": stage_hash(pending)}


def validate_stage_completion(pending, completion):
    if (
        completion.get("stage_id") != pending["stage_id"]
        or completion.get("pending_hash") != pending["pending_hash"]
        or completion.get("case_id") != pending["case_id"]
        or completion.get("task_id") != pending["task_id"]
        or completion.get("original_command_id") != pending["original_command_id"]
        or not isinstance(completion.get("operator"), str)
        or not completion["operator"].strip()
    ):
        raise ValueError("LIVE_STAGE_RELEASE_INVALID: exact pending stage not acknowledged")
    try:
        completed = datetime.fromisoformat(completion["completed_at"].replace("Z", "+00:00"))
        published = datetime.fromisoformat(pending["published_at"].replace("Z", "+00:00"))
        if completed.tzinfo is None or completed < published:
            raise ValueError("stale")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_STAGE_RELEASE_INVALID: completion time is stale") from exc
    return completion



def validate_stage_action_evidence(
    directory: Path, pending, completion, *, require_read: bool = True
):
    """发送侧与 controller 共用同一动作证明，在任何发送标记前验证。

    partial 不信任人工提供的观察哈希：从同一场景写入的原始 Host SEND/RECEIVE
    审计记录重建实际 READ，并与独立观察 DTO 精确关联。
    """

    from types import SimpleNamespace

    from .cross_host_product_live_driver import _jsonl, read_json, width_from_read

    validate_stage_completion(pending, completion)
    scenario = pending.get("scenario")
    expected_action = {
        "unavailable": "REVIT_DOCUMENT_CLOSED_UNSAVED",
        "partial_commit": "REVIT_NATIVE_UI_EDIT_201MM",
    }.get(scenario)
    authorization = completion.get("authorization_ref")
    if (
        expected_action is None
        or completion.get("action") != expected_action
        or not isinstance(authorization, str)
        or not authorization.strip()
    ):
        raise ValueError(
            "LIVE_STAGE_RELEASE_INVALID: scenario action or authorization absent"
        )
    if scenario == "unavailable":
        if completion.get("native_edit_command_id") is not None:
            raise ValueError(
                "LIVE_STAGE_RELEASE_INVALID: unrelated native edit identity"
            )
        return completion

    edit_id = completion.get("native_edit_command_id")
    if (
        not isinstance(edit_id, str)
        or not edit_id.strip()
        or edit_id == pending["original_command_id"]
        or pending.get("host_kind") != "REVIT"
    ):
        raise ValueError(
            "LIVE_STAGE_RELEASE_INVALID: distinct Revit native edit absent"
        )
    # controller 在发起额外 READ 前只验证操作授权；发出 release 与消费 release
    # 必须使用完整校验（包含生产 Host 原始 SEND/RECEIVE）。
    if not require_read:
        return completion

    try:
        observation = read_json(directory / "independent-edit-observation.json")
    except ValueError as exc:
        # 缺失、损坏或无法读取的独立观察，必须作为未验证的 Host READ 拒绝。
        raise ValueError(
            "LIVE_STAGE_EDIT_INVALID: independent READ observation unavailable"
        ) from exc
    expected_command_id = pending["stage_id"] + ":independent-edit-read"
    expected = {
        "host_kind": "REVIT",
        "host_instance_id": pending["host_instance_id"],
        "document_id": pending["document_id"],
        "native_target_id": pending["native_target_id"],
        "command_id": expected_command_id,
    }
    if (
        any(observation.get(key) != value for key, value in expected.items())
        or type(observation.get("normalized_thickness_mm")) not in (int, float)
        or observation["normalized_thickness_mm"] != 201
        or type(observation.get("host_revision")) is not int
        or observation["host_revision"] <= pending["expected_revision"]
    ):
        raise ValueError(
            "LIVE_STAGE_EDIT_INVALID: exact advanced-revision observation absent"
        )

    # READ 本身必须存在唯一的一发一收，不允许其它 stage 或文档的记录借用哈希。
    rows = _jsonl(directory / "host-commands.jsonl")
    matches = [
        row for row in rows
        if row.get("host_kind") == "REVIT"
        and row.get("stage") == "INDEPENDENT_EDIT_READ"
        and isinstance(row.get("command"), dict)
        and row["command"].get("command_id") == expected_command_id
    ]
    sends = [row for row in matches if row.get("phase") == "SEND"]
    receives = [row for row in matches if row.get("phase") == "RECEIVE"]
    if (
        len(matches) != 2
        or len(sends) != 1
        or len(receives) != 1
        or sends[0]["command"] != receives[0]["command"]
        or receives[0]["command"].get("document_id") != pending["document_id"]
        or receives[0]["command"].get("mode") != "READ"
        or receives[0]["command"].get("operation") != "read_wall_thickness_snapshot"
    ):
        raise ValueError(
            "LIVE_STAGE_EDIT_INVALID: unique actual independent READ absent"
        )
    member = SimpleNamespace(
        host_kind="REVIT",
        host_instance_id=pending["host_instance_id"],
        document_id=pending["document_id"],
        native_target_id=pending["native_target_id"],
    )
    value, revision = width_from_read(receives[0], member)
    if (
        value != {"value": 201, "unit": "mm"}
        or revision != observation["host_revision"]
    ):
        raise ValueError(
            "LIVE_STAGE_EDIT_INVALID: observed body differs from audited Host READ"
        )
    return completion


def validate_stage_release(pending, release, *, completion_hash, proof_hash):
    if release != {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"],
        "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": completion_hash,
        "proof_hash": proof_hash,
    }:
        raise ValueError("LIVE_STAGE_RELEASE_INVALID: exact stage/proof mismatch")
    return release


def validate_native_stage_failure(scenario, response):
    """Require the original native error body, including pre-commit truth."""

    if scenario == "unavailable":
        valid = (
            response.get("status") == "ERROR"
            and response.get("error", {}).get("code")
            == "REVIT_ACTIVE_DOCUMENT_UNAVAILABLE"
            and response.get("revision_after") == 0
        )
    elif scenario == "partial_commit":
        valid = (
            response.get("status") == "ERROR"
            and response.get("error", {}).get("code") == "REVISION_CONFLICT"
            and response.get("error", {}).get("commit_state") == "BEFORE_COMMIT"
        )
    else:
        valid = False
    if not valid:
        raise ValueError("LIVE_STAGE_NATIVE_ERROR_INVALID: original Host failure differs")
    return response


def require_all_ready(readiness, materialization, grants, observations):
    """Require both actual READY receipts at their frozen Host/grant revisions."""

    if (
        len(readiness) != 1 or readiness[0].status.value != "READY"
        or len(readiness[0].receipts) != 2
        or any(item.status.value != "READY" for item in readiness[0].receipts)
    ):
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: all-required READY absent")
    observed_by_host = {item["host_kind"].lower(): item for item in observations}
    grants_by_hash = {item.grant_hash: item for item in grants}
    for receipt in readiness[0].receipts:
        grant = grants_by_hash.get(receipt.grant_hash)
        observed = observed_by_host.get(receipt.host_runtime_ref.host_type)
        if (
            grant is None or observed is None
            or receipt.execution_slice_hash != grant.execution_slice_hash
            or receipt.binding_set_hash != grant.binding_set_hash
            or receipt.materialization_plan_hash
            != materialization.materialization_plan_hash
            or receipt.observed_revision != observed["host_revision"]
            or receipt.host_runtime_ref.host_instance_id != observed["host_instance_id"]
        ):
            raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: READY lineage differs")
    return tuple(item.receipt_hash for item in readiness[0].receipts)


def require_autocad_committed_delta(evidence, host_instance_id, execution_slice_hash):
    """Select one codec-verified AutoCAD delta from the committed Slice only."""

    from design_execution_reconciliation.contracts import ActualDelta

    deltas = [body for body in evidence.values()
              if isinstance(body, ActualDelta) and body.host_instance_id == host_instance_id]
    if len(deltas) != 1 or deltas[0].execution_slice_hash != execution_slice_hash:
        raise ValueError("LIVE_STAGE_PREREQUISITE_INVALID: AutoCAD durable delta absent")
    return deltas[0]


def validate_partial_event_order(timestamps):
    """Preserve four real audit timestamps in the approved native event order."""

    names = (
        "ALL_REQUIRED_READY",
        "AUTOCAD_PRODUCT_COMMITTED",
        "INDEPENDENT_REVIT_EDIT_201MM",
        "REVIT_PRODUCT_REVISION_CONFLICT",
    )
    if len(timestamps) != len(names):
        raise ValueError("LIVE_STAGE_EVENT_ORDER_INVALID: four source events required")
    try:
        parsed = [datetime.fromisoformat(value.replace("Z", "+00:00"))
                  for value in timestamps]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("LIVE_STAGE_EVENT_ORDER_INVALID: malformed source timestamp") from exc
    if any(value.tzinfo is None for value in parsed) or any(
        left >= right for left, right in zip(parsed, parsed[1:])
    ):
        raise ValueError("LIVE_STAGE_EVENT_ORDER_INVALID: source timestamps reordered")
    return list(names), dict(zip(names, timestamps, strict=True))


def wait_for_stage_release(directory: Path, pending, *, proof_hash, check_head):
    """Fail before the SDK's 300s read timeout; never forward on ambiguous I/O."""

    from .cross_host_product_live_driver import read_json, write_once

    deadline = time.monotonic() + pending["deadline_seconds"]
    path = directory / "stage-release.json"
    while time.monotonic() < deadline:
        check_head()
        if path.exists():
            release = read_json(path)
            completion = read_json(directory / "stage-controller-completion.json")
            # 必须重建动作及独立 READ 证据，才能创建 consumed marker 和发送记录。
            validate_stage_action_evidence(directory, pending, completion)
            validate_stage_release(
                pending, release,
                completion_hash=stage_hash(completion),
                proof_hash=proof_hash,
            )
            try:
                write_once(directory / "stage-release-consumed.json", release)
            except FileExistsError as exc:
                raise ValueError("LIVE_STAGE_RELEASE_DUPLICATE: command remains blocked") from exc
            return
        time.sleep(0.1)
    raise ValueError("LIVE_STAGE_TIMEOUT: blocked command was not sent; retain exact GET")
