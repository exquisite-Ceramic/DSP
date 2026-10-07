"""Product runtime 的 exact HostRuntimeRef → port registry。"""

from __future__ import annotations

from collections.abc import Iterable

from design_execution_planning import HostRuntimeRef

_NOT_CONFIGURED = "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED"
_CONFLICT = "PRODUCT_RUNTIME_HOST_RUNTIME_CONFLICT"


def _key(runtime_ref: HostRuntimeRef) -> tuple[str, str, str]:
    """把 provider-neutral runtime ref 投影为 exact registry key。"""

    if not isinstance(runtime_ref, HostRuntimeRef):
        raise TypeError("runtime_ref must be HostRuntimeRef")
    return (
        runtime_ref.host_type,
        runtime_ref.host_instance_id,
        runtime_ref.document_ref,
    )


class ExactHostRuntimeRegistry:
    """只按 host type + instance + document 三元组解析已注入端口。"""

    def __init__(
        self,
        entries: Iterable[tuple[HostRuntimeRef, object]],
    ) -> None:
        """冻结 registry；重复 exact key 必须 fail closed。"""

        values: dict[tuple[str, str, str], object] = {}
        for runtime_ref, port in tuple(entries):
            if port is None:
                raise ValueError(f"{_NOT_CONFIGURED}: runtime port must not be None")
            key = _key(runtime_ref)
            if key in values:
                raise ValueError(
                    f"{_CONFLICT}: duplicate exact Host runtime key {key!r}"
                )
            values[key] = port
        if not values:
            raise ValueError(f"{_NOT_CONFIGURED}: registry must not be empty")
        self._values = values

    def resolve(self, runtime_ref: HostRuntimeRef) -> object:
        """按 exact 三元组解析，不做 same-host latest/fallback。"""

        key = _key(runtime_ref)
        try:
            return self._values[key]
        except KeyError as exc:
            raise ValueError(
                f"{_NOT_CONFIGURED}: exact Host runtime is not configured"
            ) from exc


__all__ = ["ExactHostRuntimeRegistry"]
