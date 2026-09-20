from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS = ROOT / "docs/superpowers/reviews/2026-09-20-real-owner-e2e-workflow-census.md"
REQUIRED_AREAS = {
    "orchestrator_seam",
    "semantic_freshness",
    "revision_authority",
    "impact",
    "approval_scope_v2",
    "changeset_v2",
    "materialization_topology",
    "materialization_planning",
    "execution_planning_v2",
    "gateway_v2",
    "provider_binding_v2",
    "saga_v2",
    "coordination",
    "reconciliation_v2",
    "convergence",
    "owner_ref_surfaces",
    "scenario_fake_boundary",
    "import_time_dependencies",
}
MIXED_ROOT_AREAS = {
    "execution_planning_v2",
    "gateway_v2",
    "provider_binding_v2",
    "reconciliation_v2",
}
PLACEHOLDERS = {"TODO", "TBD", "UNKNOWN"}


def _census_rows() -> list[dict[str, str]]:
    """解析 census 的 machine-readable owner 表，并在文档缺失时明确 RED。"""
    assert CENSUS.is_file(), f"missing real-owner census: {CENSUS.relative_to(ROOT)}"
    lines = [line for line in CENSUS.read_text(encoding="utf-8").splitlines() if line.startswith("|")]
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith("| area |")
    )
    headers = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            break
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _split_surface(value: str) -> tuple[str, ...]:
    """把 `<br>` 分隔的 public/forbidden surface 解析成稳定 token。"""
    if value.startswith("N/A:"):
        return ()
    return tuple(part.strip().strip("`") for part in value.split("<br>") if part.strip())


def test_census_covers_required_areas_without_placeholders() -> None:
    """Task 1 census 必须完整覆盖计划冻结的区域，且不能留下占位值。"""
    rows = _census_rows()
    assert {row["area"] for row in rows} >= REQUIRED_AREAS

    problems: list[str] = []
    for row in rows:
        for column, value in row.items():
            upper_value = value.upper()
            for placeholder in PLACEHOLDERS:
                if placeholder in upper_value:
                    problems.append(f"{row['area']}:{column} contains {placeholder}")
    assert not problems, "\n" + "\n".join(problems)


def test_mixed_roots_use_symbol_level_public_allowlist() -> None:
    """V1/V2 混杂 package 必须冻结到 package-root `module:symbol`，不能粗放行模块。"""
    by_area = {row["area"]: row for row in _census_rows()}
    problems: list[str] = []
    for area in sorted(MIXED_ROOT_AREAS):
        approved = _split_surface(by_area[area]["approved_public_surface"])
        if not approved:
            problems.append(f"{area}: empty approved_public_surface")
            continue
        for token in approved:
            if token.count(":") != 1:
                problems.append(f"{area}: not module:symbol -> {token}")
                continue
            module, symbol = token.split(":", 1)
            if "." in module.removeprefix("design_"):
                problems.append(f"{area}: non-root module forbidden -> {module}")
            exported = importlib.import_module(module)
            if not hasattr(exported, symbol):
                problems.append(f"{area}: lost public export {module}:{symbol}")
    assert not problems, "\n" + "\n".join(problems)


def test_census_records_forbidden_legacy_or_private_surfaces() -> None:
    """每个混杂 root 必须显式记录 V1/private surface，防止后续 adapter 重新消费。"""
    by_area = {row["area"]: row for row in _census_rows()}
    problems: list[str] = []
    for area in sorted(MIXED_ROOT_AREAS):
        forbidden = _split_surface(by_area[area]["forbidden_surface"])
        if not forbidden:
            problems.append(f"{area}: empty forbidden_surface")
    assert not problems, "\n" + "\n".join(problems)
