from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
from types import MappingProxyType

import yaml

from .errors import EnterpriseSourceError


EXPECTED_METADATA = {
    "provider_id": "dsp.enterprise.mapping",
    "provider_version": "1.0.0",
    "target_ifc_provider_id": "buildingSMART.ifc43",
    "target_ifc_provider_version": "4.3.2.0",
    "target_ifc_schema": "IFC4X3_ADD2",
}


def validate_root_metadata(payload: Mapping[str, object]) -> None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise EnterpriseSourceError("metadata must be a mapping")
    for key, expected in EXPECTED_METADATA.items():
        if metadata.get(key) != expected:
            raise EnterpriseSourceError(f"{key} mismatch")


def load_raw_machine_source() -> Mapping[str, object]:
    resource = files("enterprise_mapping_provider").joinpath("data").joinpath(
        "enterprise_mappings_v1.yaml"
    )
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EnterpriseSourceError("failed to load enterprise mapping source") from exc
    if not isinstance(payload, Mapping):
        raise EnterpriseSourceError("root must be a mapping")
    validate_root_metadata(payload)
    return MappingProxyType(dict(payload))
