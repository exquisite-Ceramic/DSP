from pathlib import Path

ROOT = Path(__file__).parents[2]
SUPERPOWERS = ROOT / "docs" / "superpowers"
INDEX = SUPERPOWERS / "README.md"


def _markdown_filenames(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.md")}


def _index_text() -> str:
    assert INDEX.is_file(), "docs/superpowers/README.md must exist"
    return INDEX.read_text(encoding="utf-8")


def test_lifecycle_index_covers_every_design_and_plan() -> None:
    text = _index_text()
    expected = _markdown_filenames(SUPERPOWERS / "specs") | _markdown_filenames(
        SUPERPOWERS / "plans"
    )
    missing = sorted(filename for filename in expected if filename not in text)
    assert not missing, f"lifecycle index is missing: {missing}"


def test_authority_rows_name_current_and_superseded_specs() -> None:
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
    text = _index_text()

    assert "Phase I — latest completed capability phase" in text
    assert "Engineering Hygiene / Stabilization — current engineering activity" in text
    assert "Next capability phase — NOT YET DEFINED" in text
