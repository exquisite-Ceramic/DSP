from copy import deepcopy

import pytest

from metro_semantic_provider.errors import MetroSourceError
from metro_semantic_provider.source import (
    METRO_V32_SOURCE_SHA256,
    load_raw_machine_source,
    validate_root_metadata,
)

EXPECTED = "596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b"


def test_source_identity_is_exact():
    payload = load_raw_machine_source()
    assert METRO_V32_SOURCE_SHA256 == EXPECTED
    assert payload["metadata"] == {
        "provider_id": "dsp.metro.semantic",
        "provider_version": "3.2",
        "source_document_title": "IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版",
        "source_document_sha256": EXPECTED,
        "target_ifc_provider_id": "buildingSMART.ifc43",
        "target_ifc_provider_version": "4.3.2.0",
        "target_ifc_schema": "IFC4X3_ADD2",
    }


def test_wrong_source_digest_fails_closed():
    payload = deepcopy(dict(load_raw_machine_source()))
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"]["source_document_sha256"] = "0" * 64
    with pytest.raises(MetroSourceError, match="source_document_sha256"):
        validate_root_metadata(payload)
