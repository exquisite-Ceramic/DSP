"""Provider-neutral InteractionSession contracts for Step26."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from host_contracts.envelope import parse_utc
from jsonschema import SchemaError, ValidationError, validate


class InteractionType(str, Enum):
    SELECT_ENTITIES = "SELECT_ENTITIES"
    PICK_POINT = "PICK_POINT"
    PICK_DIRECTION = "PICK_DIRECTION"
    INPUT_NUMBER = "INPUT_NUMBER"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


class InteractionState(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InteractionError(RuntimeError):
    """Stable Step26 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _readonly_copy(value: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


def _validate_schema_result(schema: Mapping[str, Any], result: Any) -> None:
    try:
        validate(instance=result, schema=dict(schema))
    except SchemaError as exc:
        raise ValueError(f"result_schema is invalid: {exc.message}") from exc
    except ValidationError as exc:
        raise InteractionError(
            "INTERACTION_RESULT_INVALID",
            f"interaction result does not match result_schema: {exc.message}",
        ) from exc


@dataclass(frozen=True, slots=True)
class InteractionStartRequest:
    task_id: str
    host_instance_id: str
    document_id: str
    interaction_type: InteractionType
    input_constraints: Mapping[str, Any] = field(default_factory=dict)
    result_schema: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    created_at: str = ""
    expires_at: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "host_instance_id",
            "document_id",
            "idempotency_key",
            "created_at",
            "expires_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.interaction_type, InteractionType):
            object.__setattr__(
                self,
                "interaction_type",
                InteractionType(str(self.interaction_type)),
            )

        object.__setattr__(
            self,
            "input_constraints",
            _readonly_copy(self.input_constraints, field_name="input_constraints"),
        )
        object.__setattr__(
            self,
            "result_schema",
            _readonly_copy(self.result_schema, field_name="result_schema"),
        )

        try:
            created = parse_utc(self.created_at)
            expires = parse_utc(self.expires_at)
        except ValueError as exc:
            raise ValueError(f"created_at/expires_at must be absolute UTC: {exc}") from exc
        if expires <= created:
            raise ValueError("expires_at must be later than created_at")

        try:
            validate(instance=None, schema=dict(self.result_schema))
        except SchemaError as exc:
            raise ValueError(f"result_schema is invalid: {exc.message}") from exc
        except ValidationError:
            # A valid schema may of course reject None; only schema validity matters here.
            pass


@dataclass(frozen=True, slots=True)
class InteractionSession:
    interaction_id: str
    task_id: str
    host_instance_id: str
    document_id: str
    interaction_type: InteractionType
    input_constraints: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    state: InteractionState
    created_at: str
    expires_at: str
    result: Any = None

    def __post_init__(self) -> None:
        for field_name in (
            "interaction_id",
            "task_id",
            "host_instance_id",
            "document_id",
            "created_at",
            "expires_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.interaction_type, InteractionType):
            object.__setattr__(
                self,
                "interaction_type",
                InteractionType(str(self.interaction_type)),
            )
        if not isinstance(self.state, InteractionState):
            object.__setattr__(self, "state", InteractionState(str(self.state)))

        object.__setattr__(
            self,
            "input_constraints",
            _readonly_copy(self.input_constraints, field_name="input_constraints"),
        )
        object.__setattr__(
            self,
            "result_schema",
            _readonly_copy(self.result_schema, field_name="result_schema"),
        )

        try:
            created = parse_utc(self.created_at)
            expires = parse_utc(self.expires_at)
        except ValueError as exc:
            raise ValueError(f"created_at/expires_at must be absolute UTC: {exc}") from exc
        if expires <= created:
            raise ValueError("expires_at must be later than created_at")

        if self.state is InteractionState.COMPLETED:
            if self.result is None:
                raise ValueError("COMPLETED interaction requires result")
            _validate_schema_result(self.result_schema, self.result)
            object.__setattr__(self, "result", deepcopy(self.result))
        elif self.result is not None:
            raise ValueError(f"{self.state.value} interaction must not carry result")


__all__ = [
    "InteractionError",
    "InteractionSession",
    "InteractionStartRequest",
    "InteractionState",
    "InteractionType",
]
