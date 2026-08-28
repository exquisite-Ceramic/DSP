from __future__ import annotations

from types import MappingProxyType

from .errors import Ifc43CatalogBuildError, Ifc43TermNotFoundError
from .golden import EXPECTED_IFC43_CONTENT_HASH
from .hashing import canonical_hash
from .model import IfcTermRecord, freeze, plain
from .normalization import normalize_pset_qto, normalize_schema_declarations
from .source import Ifc43Source, load_ifc43_source


class Ifc43Catalog:
    def __init__(
        self,
        schema_identifier: str,
        schema_version: tuple[int, int, int, int],
        records: tuple[IfcTermRecord, ...],
    ) -> None:
        ordered = tuple(sorted(records, key=lambda item: item.term_id))
        term_ids = tuple(item.term_id for item in ordered)
        if len(term_ids) != len(set(term_ids)):
            raise Ifc43CatalogBuildError("duplicate IFC term_id")
        self._schema_identifier = schema_identifier
        self._schema_version = schema_version
        self._records = ordered
        self._by_id = MappingProxyType({item.term_id: item for item in ordered})
        self._content_hash = canonical_hash(
            {
                "schema_identifier": schema_identifier,
                "schema_version": list(schema_version),
                "terms": [item.machine_payload() for item in ordered],
            }
        )

    @property
    def schema_identifier(self) -> str:
        return self._schema_identifier

    @property
    def schema_version(self) -> tuple[int, int, int, int]:
        return self._schema_version

    @property
    def records(self) -> tuple[IfcTermRecord, ...]:
        return self._records

    @property
    def term_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    @property
    def content_hash(self) -> str:
        return self._content_hash

    def get(self, term_id: str) -> IfcTermRecord:
        try:
            return self._by_id[term_id]
        except KeyError as exc:
            raise Ifc43TermNotFoundError(term_id) from exc

    def schema_for(self, term_id: str):
        record = self.get(term_id)
        schema = plain(record.machine_schema)
        if record.kind not in {"ENTITY", "RELATIONSHIP"}:
            return freeze(schema)

        inherited: list[str] = []
        supertype = schema.get("supertype")
        while supertype:
            parent = self.get(supertype)
            parent_schema = plain(parent.machine_schema)
            inherited.extend(parent_schema.get("direct_members", ()))
            supertype = parent_schema.get("supertype")
        schema["inherited_members"] = tuple(sorted(set(inherited)))
        return freeze(schema)


def build_ifc43_catalog(source: Ifc43Source) -> Ifc43Catalog:
    records = normalize_schema_declarations(source.schema) + normalize_pset_qto(source.psets)
    return Ifc43Catalog(source.schema_identifier, source.schema_version, records)


IFC43_CATALOG = build_ifc43_catalog(load_ifc43_source())
if IFC43_CATALOG.content_hash != EXPECTED_IFC43_CONTENT_HASH:
    raise Ifc43CatalogBuildError(
        "IFC4.3.2.0 normalized catalog content hash drifted from reviewed golden hash"
    )
