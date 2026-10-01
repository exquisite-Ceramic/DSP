from pathlib import Path

ROOT = Path(__file__).parents[2]
SUPERPOWERS = ROOT / "docs" / "superpowers"
INDEX = SUPERPOWERS / "README.md"
ROOT_README = ROOT / "README.md"


def _markdown_filenames(directory: Path) -> set[str]:
    """返回目录下所有 Markdown artifact 文件名。"""

    return {path.name for path in directory.glob("*.md")}


def _index_text() -> str:
    """读取生命周期索引，并在文件缺失时立即失败。"""

    assert INDEX.is_file(), "docs/superpowers/README.md must exist"
    return INDEX.read_text(encoding="utf-8")


def test_lifecycle_index_covers_every_design_and_plan() -> None:
    """生命周期索引必须覆盖全部 Design Spec 与 Implementation Plan。"""

    text = _index_text()
    expected = _markdown_filenames(SUPERPOWERS / "specs") | _markdown_filenames(
        SUPERPOWERS / "plans"
    )
    missing = sorted(filename for filename in expected if filename not in text)
    assert not missing, f"lifecycle index is missing: {missing}"


def test_authority_rows_name_current_and_superseded_specs() -> None:
    """系统级规格 authority 必须继续指向 v0.6，并保留 v0.5 的 superseded 状态。"""

    lines = _index_text().splitlines()

    assert any(
        "Enterprise_Collaborative_Design_Agent_Spec_v0.6.md" in line
        and "CURRENT" in line
        for line in lines
    )
    assert any(
        "Enterprise_Collaborative_Design_Agent_Spec_v0.5.md" in line
        and "SUPERSEDED" in line
        for line in lines
    )


def test_lifecycle_summary_names_current_repository_state() -> None:
    """根 README 与生命周期索引必须反映 Front Door 已完成并关闭 lifecycle。"""

    text = _index_text()
    root_text = ROOT_README.read_text(encoding="utf-8")

    assert "Phase I — latest completed capability phase" in text
    assert "Technology Modernization — COMPLETED" in text
    assert "Architecture Modernization Phase II — COMPLETED" in text
    assert "Capability Phase — HITL pause/resume COMPLETED" in text
    assert "Capability Phase — real E2E workflow COMPLETED" in text
    assert "Capability Phase — Revit wall-thickness product vertical COMPLETED" in text
    assert "Capability Phase — MCP / Agent front door COMPLETED" in text
    assert "Capability Phase successor — NOT YET DEFINED / NOT YET STARTED" in text
    assert "**Latest completed capability phase:** MCP / Agent front door" in root_text
    assert (
        "**Current engineering activity:** MCP / Agent front door — COMPLETED"
        in root_text
    )
    assert "**Next capability phase:** NOT YET DEFINED / NOT YET STARTED" in root_text
    assert "**Latest product acceptance:** MCP / Agent front door controlled live GREEN" in root_text


def test_front_door_design_and_plan_are_closed_after_implementation_merge() -> None:
    """Front Door capability 合并并完成 merged-main 验证后，Design 与 Plan 必须标记 COMPLETED。"""

    lines = _index_text().splitlines()
    completed_artifacts = (
        "2026-09-28-mcp-agent-front-door-design.md",
        "2026-09-28-mcp-agent-front-door.md",
    )

    for artifact in completed_artifacts:
        assert any(artifact in line and "COMPLETED" in line for line in lines), (
            f"{artifact} must be COMPLETED after MCP / Agent front door closeout"
        )
        assert not any(artifact in line and "CURRENT" in line for line in lines), (
            f"{artifact} must not remain CURRENT after MCP / Agent front door closeout"
        )


def test_hitl_design_and_plan_are_closed_only_after_implementation_merge() -> None:
    """HITL capability 完成后，其 Design Spec 与 Plan 必须保持 COMPLETED。"""

    lines = _index_text().splitlines()

    assert any(
        "2026-09-19-hitl-pause-resume-design.md" in line and "COMPLETED" in line
        for line in lines
    )
    assert any(
        "2026-09-19-hitl-pause-resume.md" in line and "COMPLETED" in line
        for line in lines
    )


def test_real_owner_e2e_artifacts_are_closed_only_after_implementation_merge() -> None:
    """real-owner E2E 及其 amendment artifacts 必须保持 COMPLETED。"""

    lines = _index_text().splitlines()
    completed_artifacts = (
        "2026-09-20-real-owner-e2e-workflow-design.md",
        "2026-09-20-real-owner-e2e-workflow.md",
        "2026-09-23-task8-execution-owner-lookup-amendment-design.md",
        "2026-09-23-task8-execution-owner-lookup-amendment.md",
        "2026-09-24-task9-parameter-binding-context-lineage-amendment.md",
    )

    for artifact in completed_artifacts:
        assert any(artifact in line and "COMPLETED" in line for line in lines), (
            f"{artifact} must be COMPLETED after the real-owner E2E implementation merge"
        )
        assert not any(artifact in line and "CURRENT" in line for line in lines), (
            f"{artifact} must not remain CURRENT after lifecycle closeout"
        )


def test_revit_product_vertical_artifacts_are_closed_after_merge() -> None:
    """Revit 产品 vertical 合并后，其 Design Spec 与 Implementation Plan 不得继续标记 CURRENT。"""

    lines = _index_text().splitlines()
    completed_artifacts = (
        "2026-09-25-revit-wall-thickness-product-vertical-design.md",
        "2026-09-25-revit-wall-thickness-product-vertical.md",
    )

    for artifact in completed_artifacts:
        assert any(artifact in line and "COMPLETED" in line for line in lines), (
            f"{artifact} must be COMPLETED after the Revit product vertical merge"
        )
        assert not any(artifact in line and "CURRENT" in line for line in lines), (
            f"{artifact} must not remain CURRENT after the Revit product vertical closeout"
        )
