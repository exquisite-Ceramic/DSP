"""ProductTask V2 首次服务端接受后的 immutable input 契约。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .contracts import ProductTaskRequestV2

_HEX_DIGITS = frozenset("0123456789abcdef")


def _sha256(value: object, field_name: str) -> str:
    """校验 accepted-input 关联 hash，拒绝非规范 lowercase SHA-256。"""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX_DIGITS for character in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _canonical_json(value: Mapping[str, object]) -> str:
    """把 binding body 复制成稳定 JSON；外部调用方不能持有 owner 内部可变对象。"""

    if not isinstance(value, Mapping):
        raise TypeError("session_binding_payload must be a mapping")
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("session_binding_payload must be canonical JSON data") from exc


@dataclass(frozen=True, slots=True, init=False)
class AcceptedProductTaskInputV2:
    """服务端 ProductTask owner 接管后的 exact request + binding body。"""

    request: ProductTaskRequestV2
    session_binding_hash: str
    _session_binding_payload_json: str

    def __init__(
        self,
        request: ProductTaskRequestV2,
        session_binding_hash: str,
        session_binding_payload: Mapping[str, object],
    ) -> None:
        """验证 request/binding lineage，并以 canonical JSON 冻结 binding body。"""

        if not isinstance(request, ProductTaskRequestV2):
            raise TypeError("request must be ProductTaskRequestV2")
        normalized_hash = _sha256(session_binding_hash, "session_binding_hash")
        if request.session_binding_hash != normalized_hash:
            raise ValueError(
                "session_binding_hash does not match ProductTaskRequestV2"
            )
        payload_json = _canonical_json(session_binding_payload)
        payload = json.loads(payload_json)
        if payload.get("binding_hash") != normalized_hash:
            raise ValueError(
                "session_binding_payload.binding_hash does not match accepted hash"
            )

        object.__setattr__(self, "request", request)
        object.__setattr__(self, "session_binding_hash", normalized_hash)
        object.__setattr__(self, "_session_binding_payload_json", payload_json)

    @property
    def session_binding_payload(self) -> Mapping[str, object]:
        """每次返回独立 JSON body，避免调用方改写 owner 内部 durable identity。"""

        payload = json.loads(self._session_binding_payload_json)
        return MappingProxyType(payload)


__all__ = ["AcceptedProductTaskInputV2"]
