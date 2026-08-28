from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def freeze(item: object) -> object:
    if isinstance(item, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in item.items()})
    if isinstance(item, (tuple, list)):
        return tuple(freeze(v) for v in item)
    if isinstance(item, (set, frozenset)):
        return frozenset(freeze(v) for v in item)
    return item


def plain(item: object) -> object:
    if isinstance(item, Mapping):
        return {str(k): plain(v) for k, v in item.items()}
    if isinstance(item, (tuple, list)):
        return [plain(v) for v in item]
    if isinstance(item, (set, frozenset)):
        return sorted((plain(v) for v in item), key=repr)
    return item


@dataclass(frozen=True, slots=True)
class TypeExpression:
    kind: str
    name: str | None = None
    aggregate_kind: str | None = None
    lower: int | None = None
    upper: int | None = None
    element: "TypeExpression | None" = None

    def payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "aggregate_kind": self.aggregate_kind,
            "lower": self.lower,
            "upper": self.upper,
            "element": self.element.payload() if self.element else None,
        }


@dataclass(frozen=True, slots=True)
class IfcTermRecord:
    term_id: str
    kind: str
    machine_schema: Mapping[str, object]
    description: str

    def __post_init__(self) -> None:
        if not self.term_id.startswith("ifc:"):
            raise ValueError("IFC term_id must use ifc: namespace")
        object.__setattr__(self, "machine_schema", freeze(self.machine_schema))

    def machine_payload(self) -> dict[str, object]:
        return {
            "term_id": self.term_id,
            "kind": self.kind,
            "schema": plain(self.machine_schema),
        }
