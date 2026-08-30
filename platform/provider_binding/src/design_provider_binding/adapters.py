"""Provider-neutral Adapter protocol, registry, and native-constraint mechanics."""

from __future__ import annotations

from typing import Protocol

from design_execution_planning import ExecutionUnit, HostRuntimeRef

from .contracts import (
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
)


class ProviderBindingAdapter(Protocol):
    adapter_version: str

    def bind(
        self,
        execution_unit: ExecutionUnit,
        host_runtime_ref: HostRuntimeRef,
        selected_candidate: ProviderExecutionCandidate,
        native_target_bindings: tuple[NativeTargetBindingEvidence, ...],
    ) -> ProviderBindingMaterial:
        ...


def native_constraints_satisfied(
    constraints: tuple[NativeConstraint, ...],
    native_target_bindings: tuple[NativeTargetBindingEvidence, ...],
) -> bool:
    for constraint in constraints:
        for target in native_target_bindings:
            if constraint.operator is NativeConstraintOperator.EQ:
                if target.native_kind != constraint.values[0]:
                    return False
            elif constraint.operator is NativeConstraintOperator.IN:
                if target.native_kind not in constraint.values:
                    return False
            else:  # pragma: no cover - contracts reject unsupported operators
                return False
    return True


def validate_native_constraints(
    constraints: tuple[NativeConstraint, ...],
    native_target_bindings: tuple[NativeTargetBindingEvidence, ...],
) -> None:
    if not native_constraints_satisfied(constraints, native_target_bindings):
        raise ProviderBindingError(
            "PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED",
            "provider native constraints are not satisfied by all native targets",
        )


class ProviderBindingAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderBindingAdapter] = {}

    def register(self, provider_server: str, adapter: ProviderBindingAdapter) -> None:
        if not isinstance(provider_server, str):
            raise ProviderBindingError(
                "PROVIDER_BINDING_INPUT_INVALID",
                "provider_server must be a string",
            )
        key = provider_server.strip()
        if not key:
            raise ProviderBindingError(
                "PROVIDER_BINDING_INPUT_INVALID",
                "provider_server is required",
            )
        existing = self._adapters.get(key)
        if existing is None:
            self._adapters[key] = adapter
            return
        if existing is adapter:
            return
        raise ProviderBindingError(
            "PROVIDER_ADAPTER_CONFLICT",
            f"conflicting adapter for {key}",
        )

    def require(
        self,
        provider_server: str,
        input_adapter_version: str,
    ) -> ProviderBindingAdapter:
        adapter = self._adapters.get(provider_server)
        if (
            adapter is None
            or str(getattr(adapter, "adapter_version", "")).strip() != input_adapter_version
        ):
            raise ProviderBindingError(
                "PROVIDER_ADAPTER_UNAVAILABLE",
                "required provider adapter/version unavailable",
            )
        return adapter


__all__ = [
    "ProviderBindingAdapter",
    "ProviderBindingAdapterRegistry",
    "native_constraints_satisfied",
    "validate_native_constraints",
]
