from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = (
    REPO_ROOT
    / "providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml"
)


def _rules() -> list[dict]:
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return payload["rules"]


def _resolve(source_scheme: str, source_code: str) -> tuple[str, str]:
    matches: list[tuple[str, str]] = []
    for rule in _rules():
        if rule["source_scheme"] != source_scheme:
            continue
        match = rule["match"]
        pattern = match["pattern"]
        candidate = source_code
        if not match["case_sensitive"]:
            pattern = pattern.casefold()
            candidate = candidate.casefold()
        if match["type"] == "EXACT" and candidate == pattern:
            matches.append((rule["target_term_id"], rule["assurance"]))
        elif match["type"] == "PREFIX" and candidate.startswith(pattern):
            matches.append((rule["target_term_id"], rule["assurance"]))

    assert matches, f"no enterprise mapping for {source_scheme} / {source_code}"
    assert len(set(matches)) == 1
    return matches[0]


def test_revit_builtin_wall_category_maps_to_ifc_wall() -> None:
    assert _resolve("revit.builtin_category", "OST_Walls") == (
        "ifc:IfcWall",
        "RULE_DERIVED",
    )


def test_revit_compound_structure_total_width_maps_to_wall_thickness() -> None:
    assert _resolve(
        "revit.property",
        "WallType.CompoundStructure.TotalWidth",
    ) == ("dsp:WallThickness", "RULE_DERIVED")


def test_existing_autocad_mapping_semantics_remain_unchanged() -> None:
    assert _resolve("autocad.layer", "A-WALL") == ("ifc:IfcWall", "RULE_DERIVED")
    assert _resolve("autocad.layer", "A-WALL-EXTERIOR") == (
        "ifc:IfcWall",
        "RULE_DERIVED",
    )
    assert _resolve("autocad.property", "LWPOLYLINE.ConstantWidth") == (
        "dsp:WallThickness",
        "RULE_DERIVED",
    )
