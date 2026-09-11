"""只读探测 Phase I 真实 AutoCAD/Revit Host 身份。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "contracts/python",
    "hosts/autocad/sidecar/src",
    "hosts/revit/sidecar/src",
):
    candidate = str(ROOT / relative)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from autocad_sidecar.adapter.host_adapter import HostAdapter as AutoCadHostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.ipc.transport import PipeTransport as AutoCadPipeTransport
from host_contracts import HostCommand
from revit_sidecar.named_pipe import NamedPipeTransport


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message, "values": {}}


def _one_non_empty(values: set[str], *, code: str, label: str) -> str:
    normalized = {value.strip() for value in values if isinstance(value, str) and value.strip()}
    if len(normalized) != 1:
        raise ValueError(f"{code}: {label} 必须唯一，实际为 {sorted(normalized)!r}")
    return next(iter(normalized))


async def _probe_autocad(endpoint: str) -> dict[str, Any]:
    """通过现有只读 context/fact 路径取得 AutoCAD runtime identity。"""
    host = AutoCadHostAdapter(
        pipe_name=endpoint,
        transport=AutoCadPipeTransport(endpoint),
    )
    dispatcher = CommandDispatcher(host)
    try:
        document = await dispatcher.current_document()
        if not document.ok:
            return _failure("AUTOCAD_CURRENT_DOCUMENT_FAILED", "AutoCAD current_document 失败。")
        document_ref = str((document.payload or {}).get("documentId") or "").strip()
        if not document_ref:
            return _failure("AUTOCAD_DOCUMENT_REF_MISSING", "AutoCAD 未返回 documentId。")

        selection = await dispatcher.current_selection()
        if not selection.ok:
            return _failure("AUTOCAD_CURRENT_SELECTION_FAILED", "AutoCAD current_selection 失败。")
        entity_refs = (selection.payload or {}).get("entityRefs") or []
        if not isinstance(entity_refs, list) or len(entity_refs) != 1:
            return _failure(
                "AUTOCAD_SINGLE_SELECTION_REQUIRED",
                "请在 AutoCAD 中只选中 1 个受控 LWPOLYLINE 墙体。",
            )
        selected = entity_refs[0]
        if not isinstance(selected, dict):
            return _failure("AUTOCAD_SELECTION_INVALID", "AutoCAD selection payload 不是对象。")
        native_id = str(selected.get("nativeId") or selected.get("native_id") or "").strip()
        native_type = str(selected.get("nativeType") or selected.get("native_type") or "").strip()
        if not native_id:
            return _failure("AUTOCAD_NATIVE_ID_MISSING", "选中对象没有 native handle。")

        batch = await dispatcher.extract_design_facts([native_id])
        if not batch.facts:
            return _failure("AUTOCAD_FACTS_EMPTY", "选中对象没有返回 normalized facts。")
        host_instance_id = _one_non_empty(
            {fact.host_ref.host_instance_id for fact in batch.facts},
            code="AUTOCAD_HOST_INSTANCE_AMBIGUOUS",
            label="AutoCAD host_instance_id",
        )
        fact_document_ref = _one_non_empty(
            {fact.host_ref.document_id for fact in batch.facts},
            code="AUTOCAD_DOCUMENT_REF_AMBIGUOUS",
            label="AutoCAD document_ref",
        )
        fact_native_id = _one_non_empty(
            {fact.subject_native_ref.native_id for fact in batch.facts},
            code="AUTOCAD_NATIVE_ID_AMBIGUOUS",
            label="AutoCAD native_id",
        )
        native_kinds = {
            str(fact.subject_native_ref.native_kind or "").strip() for fact in batch.facts
        }
        fact_native_kind = _one_non_empty(
            native_kinds,
            code="AUTOCAD_NATIVE_KIND_AMBIGUOUS",
            label="AutoCAD native_kind",
        )
        if fact_document_ref != document_ref or fact_native_id.lower() != native_id.lower():
            return _failure(
                "AUTOCAD_IDENTITY_MISMATCH",
                "AutoCAD context 与 normalized facts 的 document/native identity 不一致。",
            )
        if fact_native_kind != "LWPOLYLINE" or (native_type and native_type not in {"Polyline", "LWPOLYLINE"}):
            return _failure(
                "AUTOCAD_WALL_KIND_REQUIRED",
                f"选中对象必须是 LWPOLYLINE，实际为 {fact_native_kind!r}。",
            )
        return {
            "ok": True,
            "code": "OK",
            "message": "AutoCAD identity 已由只读 Host facts 验证。",
            "values": {
                "DSP_AUTOCAD_DOCUMENT_REF": document_ref,
                "DSP_AUTOCAD_NATIVE_ID": native_id,
                "DSP_AUTOCAD_HOST_INSTANCE_ID": host_instance_id,
            },
        }
    except (ConnectionError, ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return _failure("AUTOCAD_IDENTITY_PROBE_FAILED", str(exc))
    finally:
        await host.close()


def _probe_revit(pipe_name: str) -> dict[str, Any]:
    """通过 Revit 只读 context.current_selection 取得 document/UniqueId/runtime identity。"""
    transport = NamedPipeTransport(pipe_name=pipe_name)
    command = HostCommand(
        command_id=f"READ-PHASE-I-CONTEXT-{uuid.uuid4().hex}",
        document_id="",
        mode="READ",
        operation="context.current_selection",
        target_native_refs=[],
        arguments={},
        preconditions=[],
        idempotency_key=None,
    )
    try:
        response = transport.request(command)
    except (ConnectionError, ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return _failure("REVIT_IDENTITY_PROBE_FAILED", str(exc))
    if response.get("status") != "OK":
        error = response.get("error") or {}
        return _failure(
            str(error.get("code") or "REVIT_CONTEXT_FAILED"),
            str(error.get("message") or "Revit context.current_selection 失败。"),
        )
    payload = response.get("payload") or {}
    document_ref = str(payload.get("document_id") or "").strip()
    host_instance_id = str(payload.get("host_instance_id") or "").strip()
    selected = payload.get("selected_elements") or []
    if not document_ref or not host_instance_id:
        return _failure(
            "REVIT_CONTEXT_IDENTITY_MISSING",
            "Revit context response 缺少 document_id 或 host_instance_id。",
        )
    if not isinstance(selected, list) or len(selected) != 1:
        return _failure(
            "REVIT_SINGLE_SELECTION_REQUIRED",
            "请在 Revit 中只选中 1 个受控 Wall。",
        )
    target = selected[0]
    if not isinstance(target, dict):
        return _failure("REVIT_SELECTION_INVALID", "Revit selected element 不是对象。")
    unique_id = str(target.get("unique_id") or "").strip()
    native_kind = str(target.get("native_kind") or "").strip()
    if not unique_id or native_kind != "Wall":
        return _failure(
            "REVIT_WALL_SELECTION_REQUIRED",
            f"Revit 当前唯一选中对象必须是 Wall，实际为 {native_kind!r}。",
        )
    return {
        "ok": True,
        "code": "OK",
        "message": "Revit identity 已由只读 Host selection 验证。",
        "values": {
            "DSP_REVIT_LIVE_DOCUMENT_REF": document_ref,
            "DSP_REVIT_LIVE_WALL_UNIQUE_ID": unique_id,
            "DSP_REVIT_LIVE_HOST_INSTANCE_ID": host_instance_id,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读探测 Phase I 双 Host identity。")
    parser.add_argument("--autocad-endpoint", default="")
    parser.add_argument("--revit-pipe", default="")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "autocad": _failure("AUTOCAD_ENDPOINT_MISSING", "未提供 AutoCAD endpoint。"),
        "revit": _failure("REVIT_PIPE_MISSING", "未提供 Revit pipe。"),
    }
    if args.autocad_endpoint.strip():
        result["autocad"] = asyncio.run(_probe_autocad(args.autocad_endpoint.strip()))
    if args.revit_pipe.strip():
        result["revit"] = _probe_revit(args.revit_pipe.strip())

    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
