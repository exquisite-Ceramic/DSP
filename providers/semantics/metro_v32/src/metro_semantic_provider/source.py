"""Load the pinned Metro V3.2 machine source."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
from types import MappingProxyType

import yaml

from .errors import MetroSourceError


METRO_V32_SOURCE_SHA256 = (
    "596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b"
)

_EXPECTED = {
    "provider_id": "dsp.metro.semantic",
    "provider_version": "3.2",
    "source_document_title": "IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版",
    "source_document_sha256": METRO_V32_SOURCE_SHA256,
    "target_ifc_provider_id": "buildingSMART.ifc43",
    "target_ifc_provider_version": "4.3.2.0",
    "target_ifc_schema": "IFC4X3_ADD2",
}


def validate_root_metadata(payload: Mapping[str, object]) -> None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise MetroSourceError("metadata must be a mapping")
    for key, expected in _EXPECTED.items():
        if metadata.get(key) != expected:
            raise MetroSourceError(f"{key} mismatch")


def load_raw_machine_source() -> Mapping[str, object]:
    resource = files("metro_semantic_provider").joinpath("data", "metro_v3_2.yaml")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MetroSourceError("failed to load Metro V3.2 machine source") from exc
    if not isinstance(payload, Mapping):
        raise MetroSourceError("root must be a mapping")
    validate_root_metadata(payload)
    return MappingProxyType(dict(payload))
