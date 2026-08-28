from __future__ import annotations

from .errors import Ifc43CatalogBuildError
from .model import IfcTermRecord, TypeExpression

_SIMPLE_NAMES = {
    "binary": "BINARY",
    "boolean": "BOOLEAN",
    "integer": "INTEGER",
    "logical": "LOGICAL",
    "number": "NUMBER",
    "real": "REAL",
    "string": "STRING",
}


def _add_record(records: dict[str, IfcTermRecord], record: IfcTermRecord) -> None:
    existing = records.get(record.term_id)
    if existing is None:
        records[record.term_id] = record
        return
    if existing.machine_payload() != record.machine_payload():
        raise Ifc43CatalogBuildError(f"conflicting IFC term: {record.term_id}")


def normalize_parameter_type(raw: object) -> TypeExpression:
    aggregation = raw.as_aggregation_type()
    if aggregation is not None:
        upper = aggregation.bound2()
        return TypeExpression(
            kind="AGGREGATION",
            aggregate_kind=aggregation.type_of_aggregation_string(),
            lower=aggregation.bound1(),
            upper=None if upper == -1 else upper,
            element=normalize_parameter_type(aggregation.type_of_element()),
        )

    named = raw.as_named_type()
    if named is not None:
        return TypeExpression(kind="NAMED", name=f"ifc:{named.declared_type().name()}")

    primitive = raw.as_simple_type()
    if primitive is not None:
        try:
            name = _SIMPLE_NAMES[primitive.declared_type()]
        except KeyError as exc:
            raise Ifc43CatalogBuildError("unsupported IFC simple type") from exc
        return TypeExpression(kind="SIMPLE", name=name)

    raise Ifc43CatalogBuildError("unsupported IFC parameter type")


def normalize_schema_declarations(schema: object) -> tuple[IfcTermRecord, ...]:
    records: dict[str, IfcTermRecord] = {}

    for declaration in sorted(schema.declarations(), key=lambda item: item.name()):
        entity = declaration.as_entity()
        if entity is not None:
            owner = f"ifc:{entity.name()}"
            attributes = tuple(entity.attributes())
            derived_flags = tuple(entity.derived())
            if len(attributes) != len(derived_flags):
                raise Ifc43CatalogBuildError(
                    f"attribute/derived mismatch for {entity.name()}"
                )
            direct_members = tuple(
                sorted(f"{owner}.{attribute.name()}" for attribute in attributes)
            )
            supertype = entity.supertype()
            kind = "RELATIONSHIP" if entity.name().startswith("IfcRel") else "ENTITY"
            _add_record(
                records,
                IfcTermRecord(
                    term_id=owner,
                    kind=kind,
                    machine_schema={
                        "supertype": f"ifc:{supertype.name()}" if supertype else None,
                        "abstract": entity.is_abstract(),
                        "direct_members": direct_members,
                    },
                    description=f"IFC4X3_ADD2 {kind} {entity.name()}.",
                ),
            )
            for attribute, derived in zip(attributes, derived_flags, strict=True):
                _add_record(
                    records,
                    IfcTermRecord(
                        term_id=f"{owner}.{attribute.name()}",
                        kind="ATTRIBUTE",
                        machine_schema={
                            "owner": owner,
                            "declared_type": normalize_parameter_type(
                                attribute.type_of_attribute()
                            ).payload(),
                            "optional": attribute.optional(),
                            "derived": derived,
                        },
                        description=(
                            f"IFC4X3_ADD2 ATTRIBUTE {entity.name()}.{attribute.name()}."
                        ),
                    ),
                )
            continue

        enumeration = declaration.as_enumeration_type()
        if enumeration is not None:
            enum_id = f"ifc:{enumeration.name()}"
            values = tuple(enumeration.enumeration_items())
            literal_ids = tuple(sorted(f"{enum_id}.{value}" for value in values))
            _add_record(
                records,
                IfcTermRecord(
                    term_id=enum_id,
                    kind="ENUM",
                    machine_schema={"literals": literal_ids},
                    description=f"IFC4X3_ADD2 ENUM {enumeration.name()}.",
                ),
            )
            for value in values:
                _add_record(
                    records,
                    IfcTermRecord(
                        term_id=f"{enum_id}.{value}",
                        kind="ENUM_LITERAL",
                        machine_schema={"owner": enum_id, "value": value},
                        description=(
                            f"IFC4X3_ADD2 ENUM_LITERAL {enumeration.name()}.{value}."
                        ),
                    ),
                )
            continue

        select = declaration.as_select_type()
        if select is not None:
            _add_record(
                records,
                IfcTermRecord(
                    term_id=f"ifc:{select.name()}",
                    kind="SELECT",
                    machine_schema={
                        "members": tuple(
                            sorted(f"ifc:{member.name()}" for member in select.select_list())
                        )
                    },
                    description=f"IFC4X3_ADD2 SELECT {select.name()}.",
                ),
            )
            continue

        type_declaration = declaration.as_type_declaration()
        if type_declaration is not None:
            _add_record(
                records,
                IfcTermRecord(
                    term_id=f"ifc:{type_declaration.name()}",
                    kind="DEFINED_TYPE",
                    machine_schema={
                        "underlying": normalize_parameter_type(
                            type_declaration.declared_type()
                        ).payload()
                    },
                    description=f"IFC4X3_ADD2 DEFINED_TYPE {type_declaration.name()}.",
                ),
            )
            continue

        raise Ifc43CatalogBuildError(
            f"unsupported IFC declaration kind: {declaration.name()}"
        )

    return tuple(sorted(records.values(), key=lambda item: item.term_id))
