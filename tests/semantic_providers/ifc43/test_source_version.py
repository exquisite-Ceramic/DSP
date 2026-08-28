from types import SimpleNamespace

import pytest

from ifc43_semantic_provider.errors import Ifc43SourceVersionError
from ifc43_semantic_provider.source import (
    IFC_SCHEMA_IDENTIFIER,
    IFC_SCHEMA_VERSION,
    load_ifc43_source,
)


def test_pinned_ifcopenshell_exposes_exact_ifc4320_source():
    source = load_ifc43_source()
    assert source.schema_identifier == "IFC4X3_ADD2"
    assert source.schema_version == (4, 3, 2, 0)
    assert source.schema.name() == "IFC4X3_ADD2"
    assert source.psets is not None


def test_source_loader_rejects_mismatched_probe_identifier():
    bad_probe = SimpleNamespace(
        schema_identifier="IFC4X3_ADD1",
        schema_version=(4, 3, 1, 0),
    )
    with pytest.raises(Ifc43SourceVersionError, match="IFC4X3_ADD2"):
        load_ifc43_source(
            probe_factory=lambda **_: bad_probe,
            schema_loader=lambda **_: None,
            pset_loader=lambda _: None,
        )


def test_source_loader_rejects_schema_definition_name_drift():
    good_probe = SimpleNamespace(
        schema_identifier=IFC_SCHEMA_IDENTIFIER,
        schema_version=IFC_SCHEMA_VERSION,
    )
    bad_schema = SimpleNamespace(name=lambda: "IFC4X3_ADD1")
    with pytest.raises(Ifc43SourceVersionError, match="schema definition"):
        load_ifc43_source(
            probe_factory=lambda **_: good_probe,
            schema_loader=lambda **_: bad_schema,
            pset_loader=lambda _: object(),
        )


def test_pset_loader_receives_exact_schema_identifier():
    calls = []
    good_probe = SimpleNamespace(
        schema_identifier=IFC_SCHEMA_IDENTIFIER,
        schema_version=IFC_SCHEMA_VERSION,
    )
    good_schema = SimpleNamespace(name=lambda: IFC_SCHEMA_IDENTIFIER)
    load_ifc43_source(
        probe_factory=lambda **_: good_probe,
        schema_loader=lambda **_: good_schema,
        pset_loader=lambda identifier: calls.append(identifier) or object(),
    )
    assert calls == ["IFC4X3_ADD2"]
