"""首个真实产品 vertical 的 immutable ProductTask request 与产品投影契约。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from design_orchestrator import WorkflowCheckpointView, WorkflowPhase

_REQUEST_INVALID = "PRODUCT_TASK_REQUEST_INVALID"
_REQUEST_INTEGRITY_INVALID = "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
_REQUIRED_HOST_KIND = "REVIT"
_REQUIRED_ACTION = "SET_SELECTED_WALL_THICKNESS"
_V2_REQUEST_VERSION = "V2"
_V2_INITIATING_HOST_KIND = "REVIT"
_V2_REQUIRED_ACTION = "SET_BOUND_WALL_THICKNESS"
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


def _validate_v2_authority_hash(value: object, field: str) -> str:
    """验证 V2 关联 authority hash；结构错误仍属于 request 输入错误而非 hash 完整性漂移。"""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX_DIGITS for character in value)
    ):
        raise _invalid(f"{field} must be lowercase SHA-256")
    return value


def _v2_request_hash_body(
    *,
    version: str,
    task_id: str,
    project_id: str,
    initiating_host_kind: str,
    session_ref: str,
    session_binding_hash: str,
    requested_action: str,
    intent_arguments: Mapping[str, object],
) -> dict[str, Any]:
    """返回 V2 冻结的完整 request authority body；task_id 继续参与业务 identity。"""

    return {
        "version": version,
        "task_id": task_id,
        "project_id": project_id,
        "initiating_host_kind": initiating_host_kind,
        "session_ref": session_ref,
        "session_binding_hash": session_binding_hash,
        "requested_action": requested_action,
        "intent_arguments": _plain_intent_arguments(intent_arguments),
    }


def _compute_v2_request_hash(
    *,
    version: str,
    task_id: str,
    project_id: str,
    initiating_host_kind: str,
    session_ref: str,
    session_binding_hash: str,
    requested_action: str,
    intent_arguments: Mapping[str, object],
) -> str:
    """独立计算 V2 hash，避免改变既有 V1 六字段 hash 算法。"""

    body = _v2_request_hash_body(
        version=version,
        task_id=task_id,
        project_id=project_id,
        initiating_host_kind=initiating_host_kind,
        session_ref=session_ref,
        session_binding_hash=session_binding_hash,
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


@dataclass(frozen=True, slots=True)
class ProductTaskRequestV2:
    """显式版本化的双 Host 产品请求；只冻结 intent 与 accepted binding locator。"""

    version: str
    task_id: str
    project_id: str
    initiating_host_kind: str
    session_ref: str
    session_binding_hash: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    request_hash: str

    def __post_init__(self) -> None:
        """统一校验 V2 vertical 约束，并重新计算完整 request hash。"""

        version = _require_nonblank(self.version, "version")
        task_id = _require_nonblank(self.task_id, "task_id")
        project_id = _require_nonblank(self.project_id, "project_id")
        initiating_host_kind = _require_nonblank(
            self.initiating_host_kind,
            "initiating_host_kind",
        )
        session_ref = _require_nonblank(self.session_ref, "session_ref")
        session_binding_hash = _validate_v2_authority_hash(
            self.session_binding_hash,
            "session_binding_hash",
        )
        requested_action = _require_nonblank(self.requested_action, "requested_action")

        if version != _V2_REQUEST_VERSION:
            raise _invalid(f"version must be {_V2_REQUEST_VERSION}")
        if initiating_host_kind != _V2_INITIATING_HOST_KIND:
            raise _invalid(
                f"initiating_host_kind must be {_V2_INITIATING_HOST_KIND}"
            )
        if requested_action != _V2_REQUIRED_ACTION:
            raise _invalid(f"requested_action must be {_V2_REQUIRED_ACTION}")

        normalized_intent = _normalize_intent_arguments(self.intent_arguments)
        frozen_intent = _freeze_intent_arguments(normalized_intent)
        supplied_hash = _validate_request_hash(self.request_hash)
        expected_hash = _compute_v2_request_hash(
            version=version,
            task_id=task_id,
            project_id=project_id,
            initiating_host_kind=initiating_host_kind,
            session_ref=session_ref,
            session_binding_hash=session_binding_hash,
            requested_action=requested_action,
            intent_arguments=frozen_intent,
        )
        if supplied_hash != expected_hash:
            raise _integrity_invalid(
                "request_hash does not match canonical V2 request body"
            )

        object.__setattr__(self, "version", version)
        object.__setattr__(self, "intent_arguments", frozen_intent)

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        project_id: str,
        initiating_host_kind: str,
        session_ref: str,
        session_binding_hash: str,
        requested_action: str,
        intent_arguments: Mapping[str, object],
    ) -> ProductTaskRequestV2:
        """从规范化 intent 与 exact binding hash 创建不可变 V2 request。"""

        canonical_task_id = _require_nonblank(task_id, "task_id")
        canonical_project_id = _require_nonblank(project_id, "project_id")
        canonical_host_kind = _require_nonblank(
            initiating_host_kind,
            "initiating_host_kind",
        )
        canonical_session_ref = _require_nonblank(session_ref, "session_ref")
        canonical_binding_hash = _validate_v2_authority_hash(
            session_binding_hash,
            "session_binding_hash",
        )
        canonical_action = _require_nonblank(requested_action, "requested_action")
        if canonical_host_kind != _V2_INITIATING_HOST_KIND:
            raise _invalid(
                f"initiating_host_kind must be {_V2_INITIATING_HOST_KIND}"
            )
        if canonical_action != _V2_REQUIRED_ACTION:
            raise _invalid(f"requested_action must be {_V2_REQUIRED_ACTION}")

        normalized_intent = _normalize_intent_arguments(intent_arguments)
        frozen_intent = _freeze_intent_arguments(normalized_intent)
        request_hash = _compute_v2_request_hash(
            version=_V2_REQUEST_VERSION,
            task_id=canonical_task_id,
            project_id=canonical_project_id,
            initiating_host_kind=canonical_host_kind,
            session_ref=canonical_session_ref,
            session_binding_hash=canonical_binding_hash,
            requested_action=canonical_action,
            intent_arguments=frozen_intent,
        )
        return cls(
            version=_V2_REQUEST_VERSION,
            task_id=canonical_task_id,
            project_id=canonical_project_id,
            initiating_host_kind=canonical_host_kind,
            session_ref=canonical_session_ref,
            session_binding_hash=canonical_binding_hash,
            requested_action=canonical_action,
            intent_arguments=frozen_intent,
            request_hash=request_hash,
        )


def product_task_request_v2_payload(
    request: ProductTaskRequestV2,
) -> dict[str, object]:
    """导出 V2 持久化/wire body；task_id 仍由外层 owner row/DTO 独立定位。"""

    if not isinstance(request, ProductTaskRequestV2):
        raise TypeError("request must be ProductTaskRequestV2")
    return {
        "version": request.version,
        "project_id": request.project_id,
        "initiating_host_kind": request.initiating_host_kind,
        "session_ref": request.session_ref,
        "session_binding_hash": request.session_binding_hash,
        "requested_action": request.requested_action,
        "intent_arguments": _plain_intent_arguments(request.intent_arguments),
    }


class ProductFlowStatus(str, Enum):
    """Wall-thickness 产品 surface 的闭集状态；只投影既有 owner truth。"""

    WAITING = "WAITING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    DIVERGED = "DIVERGED"


@dataclass(frozen=True, slots=True)
class ProductFlowView:
    """产品层的瞬时投影视图，不持久化也不复制 Saga/verification 领域事实。"""

    status: ProductFlowStatus | str
    checkpoint: WorkflowCheckpointView

    def __post_init__(self) -> None:
        """冻结状态枚举，并要求视图只能包裹 framework-neutral workflow checkpoint。"""

        object.__setattr__(self, "status", ProductFlowStatus(self.status))
        if not isinstance(self.checkpoint, WorkflowCheckpointView):
            raise TypeError("checkpoint must be a WorkflowCheckpointView")

    @property
    def task_id(self) -> str:
        """直接暴露 checkpoint 的 exact task identity，不复制第二份 task truth。"""

        return self.checkpoint.task_id

    @property
    def workflow_phase(self) -> WorkflowPhase:
        """暴露 workflow owner 的当前导航阶段，便于产品 UI 呈现等待状态。"""

        return self.checkpoint.phase

    @property
    def saga_id(self) -> str | None:
        """返回 checkpoint 已持有的 authoritative Saga locator。"""

        return self.checkpoint.saga_id


class ProductTaskQueryState(str, Enum):
    """exact ProductTask query 可公开的 durable 组合状态。"""

    ACCEPTED_PRE_WORKFLOW = "ACCEPTED_PRE_WORKFLOW"
    WORKFLOW = "WORKFLOW"


@dataclass(frozen=True, slots=True)
class ProductTaskQueryView:
    """只组合 request owner 与 workflow/Saga owner truth，不持久化第二份任务状态。"""

    task_id: str
    request_hash: str
    state: ProductTaskQueryState | str
    flow: ProductFlowView | None

    def __post_init__(self) -> None:
        """冻结 query state，并验证 request/workflow identity 没有发生漂移。"""

        task_id = _require_nonblank(self.task_id, "task_id")
        request_hash = _validate_request_hash(self.request_hash)
        state = ProductTaskQueryState(self.state)
        if state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW and self.flow is not None:
            raise ValueError("ACCEPTED_PRE_WORKFLOW query view must not contain workflow state")
        if state is ProductTaskQueryState.WORKFLOW:
            if not isinstance(self.flow, ProductFlowView):
                raise ValueError("WORKFLOW query view requires ProductFlowView")
            if self.flow.task_id != task_id:
                raise ValueError("query flow task_id does not match request task_id")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "state", state)


class ProductTaskV2Status(str, Enum):
    """V2 ProductTask aggregate status；stale 与 human reject 保持语义分离。"""

    WAITING = "WAITING"
    STALE = "STALE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    DIVERGED = "DIVERGED"


class ProductProposalStateV2(str, Enum):
    """V2 proposal decision/continuation 的只读产品投影。"""

    AWAITING = "AWAITING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STALE_GATE_A = "STALE_GATE_A"
    STALE_GATE_B = "STALE_GATE_B"


def _optional_nonblank(value: object | None, field: str) -> str | None:
    """规范化 V2 query 可选文本字段。"""

    if value is None:
        return None
    return _require_nonblank(value, field)


def _optional_query_hash(value: object | None, field: str) -> str | None:
    """校验 V2 query 中可选 canonical hash。"""

    if value is None:
        return None
    return _validate_v2_authority_hash(value, field)


def _optional_revision(value: object | None, field: str) -> int | None:
    """校验 V2 query 中可选 Host revision。"""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer or None")
    return value


def _optional_positive_number(value: object | None, field: str) -> float | None:
    """校验产品层可展示的正有限实测值。"""

    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{field} must be a finite positive number or None")
    return float(value)


@dataclass(frozen=True, slots=True)
class ProductMaterializationQueryViewV2:
    """一个 REQUIRED materialization 的 durable owner-derived query projection。"""

    host_kind: str | None
    host_instance_id: str | None
    document_id: str | None
    native_target_id: str | None
    semantic_target_id: str | None
    materialization_id: str | None
    execution_slice_hash: str
    status: str
    expected_revision: int | None = None
    committed_revision: int | None = None
    observed_revision: int | None = None
    verified_thickness_mm: float | None = None
    actual_delta_hash: str | None = None
    verification_hash: str | None = None
    evidence_bundle_hash: str | None = None
    convergence_result_hash: str | None = None
    recovery_disposition: str | None = None
    evidence_unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        """冻结展示字段，同时保持“未知/尚无证据”与空字符串严格分离。"""

        for field_name in (
            "host_kind",
            "host_instance_id",
            "document_id",
            "native_target_id",
            "semantic_target_id",
            "materialization_id",
            "recovery_disposition",
            "evidence_unavailable_reason",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_nonblank(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "execution_slice_hash",
            _validate_v2_authority_hash(
                self.execution_slice_hash,
                "execution_slice_hash",
            ),
        )
        object.__setattr__(self, "status", _require_nonblank(self.status, "status"))
        for field_name in (
            "expected_revision",
            "committed_revision",
            "observed_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_revision(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "verified_thickness_mm",
            _optional_positive_number(
                self.verified_thickness_mm,
                "verified_thickness_mm",
            ),
        )
        for field_name in (
            "actual_delta_hash",
            "verification_hash",
            "evidence_bundle_hash",
            "convergence_result_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_query_hash(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class ProductTaskQueryViewV2:
    """显式版本化的双 Host ProductTask durable query surface。"""

    version: str
    task_id: str
    request_hash: str
    state: ProductTaskQueryState | str
    status: ProductTaskV2Status | str
    proposal_state: ProductProposalStateV2 | str | None
    saga_id: str | None
    convergence_result_hash: str | None
    materializations: tuple[ProductMaterializationQueryViewV2, ...]

    def __post_init__(self) -> None:
        """验证 V2 view 自身一致性，不把它升级为新的 durable truth。"""

        if self.version != _V2_REQUEST_VERSION:
            raise ValueError(f"version must be {_V2_REQUEST_VERSION}")
        task_id = _require_nonblank(self.task_id, "task_id")
        request_hash = _validate_request_hash(self.request_hash)
        state = ProductTaskQueryState(self.state)
        status = ProductTaskV2Status(self.status)
        proposal_state = (
            None
            if self.proposal_state is None
            else ProductProposalStateV2(self.proposal_state)
        )
        saga_id = _optional_nonblank(self.saga_id, "saga_id")
        convergence_hash = _optional_query_hash(
            self.convergence_result_hash,
            "convergence_result_hash",
        )
        materializations = tuple(self.materializations)
        if any(
            not isinstance(item, ProductMaterializationQueryViewV2)
            for item in materializations
        ):
            raise TypeError(
                "materializations must contain ProductMaterializationQueryViewV2"
            )
        slice_hashes = tuple(item.execution_slice_hash for item in materializations)
        if len(set(slice_hashes)) != len(slice_hashes):
            raise ValueError("materializations must not duplicate execution Slice")
        if state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW and (
            saga_id is not None or materializations
        ):
            raise ValueError(
                "ACCEPTED_PRE_WORKFLOW V2 view cannot expose Saga/materializations"
            )
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "proposal_state", proposal_state)
        object.__setattr__(self, "saga_id", saga_id)
        object.__setattr__(self, "convergence_result_hash", convergence_hash)
        object.__setattr__(self, "materializations", materializations)
