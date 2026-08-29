from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "platform" / "semantic_runtime"
ORCHESTRATOR = ROOT / "platform" / "orchestrator"
ENTERPRISE_RULE = (
    ROOT
    / "providers"
    / "semantics"
    / "enterprise_mapping"
    / "src"
    / "enterprise_mapping_provider"
    / "data"
    / "enterprise_mappings_v1.yaml"
)


def _text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {
            ".py", ".cs", ".yaml", ".yml", ".json", ".toml"
        }:
            yield path


def _tree_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _text_files(root))


def test_d5_runtime_has_no_enterprise_or_autocad_mapping_knowledge() -> None:
    text = _tree_text(RUNTIME)
    for forbidden in ("A-WALL", "autocad.layer", "dsp.enterprise.mapping"):
        assert forbidden not in text


def test_d5_runtime_does_not_depend_on_semantic_service_or_enterprise_provider() -> None:
    text = _tree_text(RUNTIME)
    assert "semantic_service" not in text
    assert "enterprise_mapping_provider" not in text


def test_orchestrator_has_no_enterprise_mapping_knowledge_or_dependency() -> None:
    text = _tree_text(ORCHESTRATOR)
    for forbidden in (
        "A-WALL",
        "autocad.layer",
        "dsp.enterprise.mapping",
        "enterprise_mapping_provider",
    ):
        assert forbidden not in text


def test_a_wall_rule_has_one_production_source_owner() -> None:
    roots = (
        ROOT / "contracts",
        ROOT / "hosts",
        ROOT / "platform",
        ROOT / "providers" / "semantics",
    )
    hits = []
    for root in roots:
        for path in _text_files(root):
            if "A-WALL" in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(ROOT))
    assert hits == [ENTERPRISE_RULE.relative_to(ROOT)]
