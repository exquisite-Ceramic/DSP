"""Revit 墙厚产品 vertical 的 request-aware semantic composition boundary。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from design_orchestrator.workflow_contracts import StableRef
from revit_sidecar import RevitContextObservation
from semantic_runtime import HostBinding, IdentityRegistry

from .contracts import ProductTaskRequest


class ProductTaskRequestReadPort(Protocol):
    """按 exact task id 读取 immutable ProductTask request 的最小边界。"""

    def get(self, task_id: str) -> ProductTaskRequest | None: ...


class RevitContextObservationPort(Protocol):
    """读取当前 Revit Host context evidence 的最小边界。"""

    def read(
        self,
        *,
        command_id: str,
        document_id: str,
        host_instance_id: str,
    ) -> RevitContextObservation: ...


class RevitSemanticBoundaryError(ValueError):
    """产品 request 与 authoritative Revit/semantic evidence 无法安全关联。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CapturedContext:
    """一次 exact re-read 的瞬时结果；只在当前调用栈内使用，不作为持久 authority。"""

    request: ProductTaskRequest
    observation: RevitContextObservation
    binding: HostBinding
    digest: str


def _required_text(value: object, field_name: str) -> str:
    """规范化 composition-owned identity，并拒绝空白值。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _context_hash(
    *,
    request: ProductTaskRequest,
    observation: RevitContextObservation,
    semantic_id: str,
    native_id: str,
    native_kind: str,
) -> str:
    """对 request lineage + exact Host observation + semantic binding 计算规范哈希。"""

    body = {
        "task_id": request.task_id,
        "request_hash": request.request_hash,
        "project_id": request.project_id,
        "session_ref": request.session_ref,
        "document_id": observation.document_id,
        "document_title": observation.document_title,
        "host_instance_id": observation.host_instance_id,
        "revision": observation.revision,
        "semantic_id": semantic_id,
        "native_id": native_id,
        "native_kind": native_kind,
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class RevitWallThicknessSemanticBoundary:
    """把 immutable ProductTask request 与 authoritative Revit selection 绑定起来。

    当前实现只覆盖 context capture/recovery。它不执行 semantic reconstruction、canonical
    operation resolution 或 parameter binding；这些职责在后续 Task 5 RED/GREEN 中逐步接入。
    """

    _REF_PREFIX = "revit-context:"

    def __init__(
        self,
        *,
        request_store: ProductTaskRequestReadPort,
        context_reader: RevitContextObservationPort,
        identity_registry: IdentityRegistry,
        session_ref: str,
        document_id: str,
        host_instance_id: str,
    ) -> None:
        """显式注入 environment-owned session/document/runtime identity 与 owner ports。"""

        if request_store is None or not callable(getattr(request_store, "get", None)):
            raise TypeError("request_store must provide get")
        if context_reader is None or not callable(getattr(context_reader, "read", None)):
            raise TypeError("context_reader must provide read")
        if not isinstance(identity_registry, IdentityRegistry):
            raise TypeError("identity_registry must be an IdentityRegistry")

        self._request_store = request_store
        self._context_reader = context_reader
        self._identity_registry = identity_registry
        self._session_ref = _required_text(session_ref, "session_ref")
        self._document_id = _required_text(document_id, "document_id")
        self._host_instance_id = _required_text(host_instance_id, "host_instance_id")

    def _capture(self, task_id: str) -> _CapturedContext:
        """从 durable request + fresh Host READ + existing identity binding 重建一次 exact context。"""

        normalized_task_id = _required_text(task_id, "task_id")
        request = self._request_store.get(normalized_task_id)
        if request is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_REQUEST_UNAVAILABLE",
                "exact ProductTask request is unavailable",
            )
        if not isinstance(request, ProductTaskRequest) or request.task_id != normalized_task_id:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_REQUEST_MISMATCH",
                "request store did not return the exact ProductTask request",
            )
        if request.session_ref != self._session_ref:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SESSION_MISMATCH",
                "ProductTask session_ref does not match the configured Revit session",
            )

        command_suffix = sha256(
            f"{request.task_id}\n{request.request_hash}".encode()
        ).hexdigest()[:24]
        observation = self._context_reader.read(
            command_id=f"PRODUCT-CONTEXT-{command_suffix}",
            document_id=self._document_id,
            host_instance_id=self._host_instance_id,
        )
        if not isinstance(observation, RevitContextObservation):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_INVALID",
                "context reader must return RevitContextObservation",
            )
        if (
            observation.document_id != self._document_id
            or observation.host_instance_id != self._host_instance_id
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_MISMATCH",
                "Revit context observation does not match configured document/runtime identity",
            )
        if len(observation.selected_elements) != 1:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_SELECTION_INVALID",
                "Revit product selection must contain exactly one element",
            )

        selected = observation.selected_elements[0]
        if selected.native_kind != "Wall":
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_TARGET_NOT_WALL",
                "selected Revit native entity must be Wall",
            )

        binding = self._identity_registry.by_host(
            "revit",
            observation.document_id,
            selected.unique_id,
        )
        if binding is None:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_IDENTITY_UNRESOLVED",
                "selected Revit entity has no existing semantic identity binding",
            )
        if (
            binding.host_type != "revit"
            or binding.document_id != observation.document_id
            or binding.native_id != selected.unique_id
            or binding.native_kind != "Wall"
        ):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_IDENTITY_MISMATCH",
                "resolved semantic identity binding does not match exact Revit Wall evidence",
            )

        digest = _context_hash(
            request=request,
            observation=observation,
            semantic_id=binding.semantic_id,
            native_id=binding.native_id,
            native_kind=binding.native_kind,
        )
        return _CapturedContext(
            request=request,
            observation=observation,
            binding=binding,
            digest=digest,
        )

    def resolve_host_context(self, task_id: str) -> StableRef:
        """按 exact task request 捕获当前 Revit selection 并返回 content-addressed context ref。"""

        captured = self._capture(task_id)
        return StableRef(
            f"{self._REF_PREFIX}{captured.request.task_id}",
            captured.digest,
        )

    def load_context_inputs(self, context_ref: StableRef):
        """fresh re-read 后仅在 context ref 完全匹配时重建 freshness 输入。"""

        if not isinstance(context_ref, StableRef):
            raise TypeError("context_ref must be StableRef")
        if not context_ref.ref_id.startswith(self._REF_PREFIX):
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_REF_INVALID",
                "context ref is not owned by the Revit product semantic boundary",
            )
        task_id = context_ref.ref_id[len(self._REF_PREFIX) :]
        if not task_id.strip():
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_REF_INVALID",
                "context ref does not contain an exact task id",
            )

        captured = self._capture(task_id)
        rebuilt_ref = StableRef(
            f"{self._REF_PREFIX}{captured.request.task_id}",
            captured.digest,
        )
        if rebuilt_ref != context_ref:
            raise RevitSemanticBoundaryError(
                "REVIT_PRODUCT_CONTEXT_HASH_MISMATCH",
                "Revit context hash mismatch after authoritative Host re-read",
            )

        # 避免 product_runtime 在 import-time 绑定完整 orchestrator composition；这里只构造其窄输入 DTO。
        from design_orchestrator.canonical_owner_ports import ContextFreshnessInputs

        return ContextFreshnessInputs(
            task_id=captured.request.task_id,
            project_id=captured.request.project_id,
            document_ref=captured.observation.document_id,
            root_entities=(captured.binding.semantic_id,),
        )


__all__ = [
    "ProductTaskRequestReadPort",
    "RevitContextObservationPort",
    "RevitSemanticBoundaryError",
    "RevitWallThicknessSemanticBoundary",
]
