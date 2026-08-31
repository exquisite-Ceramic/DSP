from design_fact_contracts import (
    DesignFactHostRef,
    FactKind,
    NativeSubjectRef,
    NormalizedDesignFact,
    NormalizedDesignFactBatch,
    ValueType,
)
from enterprise_mapping_provider.provider import EnterpriseMappingProvider


def test_autocad_constant_width_projects_to_dsp_wall_thickness() -> None:
    document_id = "C:/models/step34.dwg"
    fact = NormalizedDesignFact(
        fact_id="fact-step34-width",
        producer="autocad.sidecar.design_fact_adapter.v1",
        host_ref=DesignFactHostRef("autocad", "session-step34", document_id),
        source_revision=7,
        subject_native_ref=NativeSubjectRef(document_id, "A31", "LWPOLYLINE"),
        fact_kind=FactKind.PROPERTY,
        predicate="constant_width",
        value=200.0,
        value_type=ValueType.NUMBER,
        unit="mm",
        source_scheme="autocad.property",
        source_code="LWPOLYLINE.ConstantWidth",
        provenance=("autocad://source",),
    )

    claims = EnterpriseMappingProvider().project_facts(NormalizedDesignFactBatch((fact,)))

    assert len(claims) == 1
    claim = claims[0]
    assert claim.predicate == "property"
    assert claim.canonical_term_id == "dsp:WallThickness"
    assert claim.value == 200.0
    assert claim.unit == "mm"
    assert claim.assurance == "RULE_DERIVED"
    assert claim.evidence == (
        "design-fact:fact-step34-width",
        "mapping:enterprise.autocad.property.lwpolyline-constant-width.v1",
    )
