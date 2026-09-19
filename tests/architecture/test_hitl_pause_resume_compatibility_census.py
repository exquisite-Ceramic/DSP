from pathlib import Path

CENSUS = Path(
    "docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md"
)
REQUIRED_AREAS = {
    "public_exports",
    "runtime_callers",
    "test_callers",
    "host_plugin_callers",
    "persisted_checkpoints",
    "artifact_store_impls",
}


def _rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| ") or "area" in line or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 4:
            rows.append(
                dict(zip(("area", "evidence", "finding", "decision"), cells, strict=True))
            )
    return rows


def test_hitl_compatibility_census_is_complete_and_closed() -> None:
    rows = _rows(CENSUS.read_text(encoding="utf-8"))
    assert {row["area"] for row in rows} == REQUIRED_AREAS
    for row in rows:
        assert all(row.values())
        combined = " ".join(row.values()).upper()
        assert "TBD" not in combined
        assert "TODO" not in combined
        assert "UNKNOWN" not in combined
