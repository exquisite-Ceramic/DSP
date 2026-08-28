from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import ifcopenshell
from ifcopenshell.util.pset import get_template

from .errors import Ifc43SourceVersionError

IFC_SCHEMA_IDENTIFIER = "IFC4X3_ADD2"
IFC_SCHEMA_VERSION = (4, 3, 2, 0)


@dataclass(frozen=True, slots=True)
class Ifc43Source:
    schema_identifier: str
    schema_version: tuple[int, int, int, int]
    schema: object
    psets: object


def load_ifc43_source(
    *,
    probe_factory: Callable[..., object] = ifcopenshell.file,
    schema_loader: Callable[..., object] = ifcopenshell.schema_by_name,
    pset_loader: Callable[[str], object] = get_template,
) -> Ifc43Source:
    probe = probe_factory(schema_version=IFC_SCHEMA_VERSION)
    identifier = getattr(probe, "schema_identifier", None)
    version = getattr(probe, "schema_version", None)
    if identifier != IFC_SCHEMA_IDENTIFIER or version != IFC_SCHEMA_VERSION:
        raise Ifc43SourceVersionError(
            f"expected {IFC_SCHEMA_IDENTIFIER} / {IFC_SCHEMA_VERSION}, "
            f"got {identifier!r} / {version!r}"
        )

    schema = schema_loader(schema_version=IFC_SCHEMA_VERSION)
    schema_name = schema.name()
    if schema_name != IFC_SCHEMA_IDENTIFIER:
        raise Ifc43SourceVersionError(
            f"schema definition must be {IFC_SCHEMA_IDENTIFIER}; got {schema_name!r}"
        )

    psets = pset_loader(IFC_SCHEMA_IDENTIFIER)
    if psets is None:
        raise Ifc43SourceVersionError("official Pset/Qto template source is unavailable")
    return Ifc43Source(identifier, version, schema, psets)
