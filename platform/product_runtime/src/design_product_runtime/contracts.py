"""首个真实产品 vertical 的 immutable ProductTask request 契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any

_REQUEST_INVALID = "PRODUCT_TASK_REQUEST_INVALID"
_REQUEST_INTEGRITY_INVALID = "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
_REQUIRED_HOST_KIND = "REVIT"
_REQUIRED_ACTION = "SET_SELECTED_WALL_THICKNESS"
_HEX_DIGITS = frozenset("0123456789abcdef")


class ProductTaskRequestError(ValueError):
    """ProductTask request 在结构、vertical 约束或完整性上不合法。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> ProductTaskRequestError:
    """构造稳定的请求输入错误。"""

    return ProductTaskRequestError(_REQUEST_INVALID, message)


def _integrity_invalid(message: str) -> ProductTaskRequestError:
    """构造稳定的请求完整性错误。"""

    return ProductTaskRequestError(_REQUEST_INTEGRITY_INVALID, message)


def _require_nonblank(value: object, field: str) -> str:
    """要求 lineage locator 是非空字符串，并保留调用方的原始非空值。"""

    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-blank string")
    return value


def _normalize_intent_arguments(
    value: Mapping[str, object] | object,
) -> dict[str, dict[str, object]]:
    """只接受冻结 vertical 的 thickness intent，不让 Host/model truth 混入请求。"""

    if not isinstance(value, Mapping) or set(value) != {"thickness"}:
        raise _invalid("intent_arguments must contain only thickness")

    thickness = value.get("thickness")
    if not isinstance(thickness, Mapping) or set(thickness) != {"value", "unit"}:
        raise _invalid("thickness must contain exactly value and unit")

    raw_value = thickness.get("value")
    if (
        isinstance(raw_value, bool)
        or not isinstance(raw_value, (int, float))
        or not math.isfinite(float(raw_value))
        or float(raw_value) <= 0.0
    ):
        raise _invalid("thickness.value must be a finite positive number")

    unit = thickness.get("unit")
    if unit != "mm":
        raise _invalid("thickness.unit must be mm")

    return {
        "thickness": {
            "value": float(raw_value),
            "unit": "mm",
        }
    }


def _freeze_intent_arguments(
    value: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object]:
    """深度冻结 canonical intent，避免调用方持有的可变 dict 改写 durable identity。"""

    thickness = value["thickness"]
    frozen_thickness = MappingProxyType(
        {
            "value": thickness["value"],
            "unit": thickness["unit"],
        }
    )
    return MappingProxyType({"thickness": frozen_thickness})


def _plain_intent_arguments(value: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """把冻结 mapping 投影为可 JSON 序列化的规范 body。"""

    thickness = value["thickness"]
    if not isinstance(thickness, Mapping):
        raise _integrity_invalid("frozen thickness body is not a mapping")
    return {
        "thickness": {
            "value": thickness["value"],
            "unit": thickness["unit"],
        }
    }


def _request_hash_body(
    *,
    task_id: str,
    project_id: str,
    host_kind: str,
    session_ref: str,
    requested_action: str,
    intent_arguments: Mapping[str, object],
) -> dict[str, Any]:
    """返回 Design 冻结的六字段 request authority body。"""

    return {
        "task_id": task_id,
        "project_id": project_id,
        "host_kind": host_kind,
        "session_ref": session_ref,
        "requested_action": requested_action,
        "intent_arguments": _plain_intent_arguments(intent_arguments),
    }


def _compute_request_hash(
    *,
    task_id: str,
    project_id: str,
    host_kind: str,
    session_ref: str,
    requested_action: str,
    intent_arguments: Mapping[str, object],
) -> str:
    """对规范 ProductTask authority body 计算确定性的 SHA-256。"""

    body = _request_hash_body(
        task_id=task_id,
        project_id=project_id,
        host_kind=host_kind,
        session_ref=session_ref,
        requested_action=requested_action,
        intent_arguments=intent_arguments,
    )
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validate_request_hash(value: object) -> str:
    """要求 supplied request hash 是规范 lowercase SHA-256。"""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX_DIGITS for character in value)
    ):
        raise _integrity_invalid("request_hash must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ProductTaskRequest:
    """按 task_id 定位、按完整 body 哈希保护的不可变产品请求。"""

    task_id: str
    project_id: str
    host_kind: str
    session_ref: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    request_hash: str

    def __post_init__(self) -> None:
        """所有构造路径都执行同一 vertical 约束与完整性校验。"""

        task_id = _require_nonblank(self.task_id, "task_id")
        project_id = _require_nonblank(self.project_id, "project_id")
        host_kind = _require_nonblank(self.host_kind, "host_kind")
        session_ref = _require_nonblank(self.session_ref, "session_ref")
        requested_action = _require_nonblank(self.requested_action, "requested_action")

        if host_kind != _REQUIRED_HOST_KIND:
            raise _invalid(f"host_kind must be {_REQUIRED_HOST_KIND}")
        if requested_action != _REQUIRED_ACTION:
            raise _invalid(f"requested_action must be {_REQUIRED_ACTION}")

        normalized_intent = _normalize_intent_arguments(self.intent_arguments)
        frozen_intent = _freeze_intent_arguments(normalized_intent)
        supplied_hash = _validate_request_hash(self.request_hash)
        expected_hash = _compute_request_hash(
            task_id=task_id,
            project_id=project_id,
            host_kind=host_kind,
            session_ref=session_ref,
            requested_action=requested_action,
            intent_arguments=frozen_intent,
        )
        if supplied_hash != expected_hash:
            raise _integrity_invalid("request_hash does not match canonical request body")

        object.__setattr__(self, "intent_arguments", frozen_intent)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        project_id: str,
        host_kind: str,
        session_ref: str,
        requested_action: str,
        intent_arguments: Mapping[str, object],
    ) -> ProductTaskRequest:
        """从用户 INTENT 字段创建规范、完整性受保护的 ProductTask request。"""

        canonical_task_id = _require_nonblank(task_id, "task_id")
        canonical_project_id = _require_nonblank(project_id, "project_id")
        canonical_host_kind = _require_nonblank(host_kind, "host_kind")
        canonical_session_ref = _require_nonblank(session_ref, "session_ref")
        canonical_action = _require_nonblank(requested_action, "requested_action")
        if canonical_host_kind != _REQUIRED_HOST_KIND:
            raise _invalid(f"host_kind must be {_REQUIRED_HOST_KIND}")
        if canonical_action != _REQUIRED_ACTION:
            raise _invalid(f"requested_action must be {_REQUIRED_ACTION}")

        normalized_intent = _normalize_intent_arguments(intent_arguments)
        frozen_intent = _freeze_intent_arguments(normalized_intent)
        request_hash = _compute_request_hash(
            task_id=canonical_task_id,
            project_id=canonical_project_id,
            host_kind=canonical_host_kind,
            session_ref=canonical_session_ref,
            requested_action=canonical_action,
            intent_arguments=frozen_intent,
        )
        return cls(
            task_id=canonical_task_id,
            project_id=canonical_project_id,
            host_kind=canonical_host_kind,
            session_ref=canonical_session_ref,
            requested_action=canonical_action,
            intent_arguments=frozen_intent,
            request_hash=request_hash,
        )


def product_task_request_payload(request: ProductTaskRequest) -> dict[str, object]:
    """导出可持久化的规范请求 payload；不加入时间戳或任何 Host/model truth。"""

    return {
        "project_id": request.project_id,
        "host_kind": request.host_kind,
        "session_ref": request.session_ref,
        "requested_action": request.requested_action,
        "intent_arguments": _plain_intent_arguments(request.intent_arguments),
    }
