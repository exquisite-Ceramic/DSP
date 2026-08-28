from __future__ import annotations

from ifcopenshell.util.pset import get_pset_template_type, parse_applicable_entity

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


def _direct_derived_flags(entity: object, attributes: tuple[object, ...]) -> tuple[bool, ...]:
    if not attributes:
        return ()
    all_attributes = tuple(entity.all_attributes())
    all_derived = tuple(entity.derived())
    if len(all_attributes) != len(all_derived):
        raise Ifc43CatalogBuildError(
            f"all-attribute/derived mismatch for {entity.name()}"
        )
    direct_names = tuple(attribute.name() for attribute in attributes)
    tail_names = tuple(attribute.name() for attribute in all_attributes[-len(attributes):])
    if tail_names != direct_names:
        raise Ifc43CatalogBuildError(
            f"direct attributes are not the all-attribute tail for {entity.name()}"
        )
    return tuple(bool(value) for value in all_derived[-len(attributes):])


def normalize_schema_declarations(schema: object) -> tuple[IfcTermRecord, ...]:
    records: dict[str, IfcTermRecord] = {}

    for declaration in sorted(schema.declarations(), key=lambda item: item.name()):
        entity = declaration.as_entity()
        if entity is not None:
            owner = f"ifc:{entity.name()}"
            attributes = tuple(entity.attributes())
            derived_flags = _direct_derived_flags(entity, attributes)
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


def _text(value: object) -> str | None:
    if value is None:
        return None
    wrapped = getattr(value, "wrappedValue", None)
    return str(wrapped if wrapped is not None else value)


def _template_files(psets: object) -> tuple[object, ...]:
    return tuple(getattr(psets, "templates", ()))


def _applicability(template: object) -> tuple[dict[str, object], ...]:
    raw = getattr(template, "ApplicableEntity", None) or ""
    values = []
    for item in parse_applicable_entity(raw):
        values.append(
            {
                "ifc_class": item.ifc_class,
                "predefined_type": item.predefined_type,
                "performance_history": item.performance_history,
            }
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item["ifc_class"],
                item["predefined_type"] or "",
                item["performance_history"],
            ),
        )
    )


def _enum_values(property_template: object) -> tuple[str, ...]:
    enumerators = getattr(property_template, "Enumerators", None)
    if enumerators is None:
        return ()
    values = getattr(enumerators, "EnumerationValues", ()) or ()
    normalized = tuple(_text(value) for value in values)
    return tuple(sorted(value for value in normalized if value is not None))


def _unit_ref(property_template: object) -> dict[str, object] | None:
    unit = getattr(property_template, "PrimaryUnit", None)
    if unit is None:
        return None
    return {
        "ifc_class": unit.is_a(),
        "UnitType": _text(getattr(unit, "UnitType", None)),
        "Name": _text(getattr(unit, "Name", None)),
        "Prefix": _text(getattr(unit, "Prefix", None)),
    }


def normalize_pset_qto(psets: object) -> tuple[IfcTermRecord, ...]:
    records: dict[str, IfcTermRecord] = {}

    for template_file in _template_files(psets):
        templates = tuple(template_file.by_type("IfcPropertySetTemplate"))
        for template in sorted(templates, key=lambda item: item.Name or ""):
            name = template.Name
            if not isinstance(name, str) or not name:
                raise Ifc43CatalogBuildError("official Pset/Qto template has no Name")
            if name.startswith("PsetProj_") or name.startswith("QtoProj_"):
                continue

            set_kind = get_pset_template_type(template)
            if set_kind not in {"PSET", "QTO"}:
                continue

            owner = f"ifc:{name}"
            members = tuple(
                sorted(
                    tuple(template.HasPropertyTemplates or ()),
                    key=lambda item: item.Name or "",
                )
            )
            member_ids = tuple(
                f"{owner}.{member.Name}"
                for member in members
                if isinstance(member.Name, str) and member.Name
            )
            if len(member_ids) != len(members):
                raise Ifc43CatalogBuildError(f"unnamed member in {name}")

            _add_record(
                records,
                IfcTermRecord(
                    term_id=owner,
                    kind=set_kind,
                    machine_schema={
                        "applicability": _applicability(template),
                        "members": member_ids,
                    },
                    description=f"IFC4X3_ADD2 {set_kind} {name}.",
                ),
            )

            member_kind = "PSET_PROPERTY" if set_kind == "PSET" else "QTO_QUANTITY"
            for member in members:
                member_name = member.Name
                _add_record(
                    records,
                    IfcTermRecord(
                        term_id=f"{owner}.{member_name}",
                        kind=member_kind,
                        machine_schema={
                            "owner": owner,
                            "template_type": _text(getattr(member, "TemplateType", None)),
                            "primary_measure_type": _text(
                                getattr(member, "PrimaryMeasureType", None)
                            ),
                            "enum_values": _enum_values(member),
                            "unit": _unit_ref(member),
                        },
                        description=(
                            f"IFC4X3_ADD2 {member_kind} {name}.{member_name}."
                        ),
                    ),
                )

    return tuple(sorted(records.values(), key=lambda item: item.term_id))
