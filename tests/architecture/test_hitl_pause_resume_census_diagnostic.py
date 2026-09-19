from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

_PROFILE_FIELDS = {
    "provider_server",
    "provider_tool",
    "canonical_operation",
    "category",
    "entity_constraints",
    "execution_freshness",
    "effects",
    "risk",
    "preview_supported",
    "rollback_supported",
    "verification_contract",
    "input_schema",
    "output_schema",
}

SEARCHES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "public_contracts",
        ("platform", "hosts", "tests", "contracts"),
        r"WorkflowResumeCommand|WorkflowCheckpointView|PendingInteraction",
    ),
    (
        "resume_callers",
        ("platform", "hosts", "tests"),
        r"WorkflowResumeCommand\(",
    ),
    (
        "artifact_store",
        ("platform", "hosts", "tests"),
        r"WorkflowArtifactStore|_MemoryArtifactStore|artifact_store",
    ),
    (
        "capability_profiles",
        ("platform", "providers", "hosts", "tests"),
        r"CapabilityProfile|provider_candidates|ResolutionResult",
    ),
    (
        "wait_resume_compatibility",
        ("platform", "hosts", "tests"),
        r"await_operation_proposal|ASYNC_OPERATION_COMPLETED|resume\(.*None",
    ),
    (
        "persisted_checkpoint",
        ("platform", "tests", "docs/runbooks", ".github/workflows"),
        r"orchestrator_checkpoint|checkpoint_ns|operation_ref",
    ),
    (
        "host_plugin_contracts",
        ("hosts", "contracts"),
        r"design_orchestrator.*workflow|workflow_contracts|workflow_port",
    ),
)


def _files(roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files))


def _scan(roots: tuple[str, ...], pattern: str) -> list[str]:
    regex = re.compile(pattern)
    matches: list[str] = []
    for path in _files(roots):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                relative = path.relative_to(ROOT).as_posix()
                matches.append(f"{relative}:{line_number}:{line.strip()}")
    return matches


def _python_classes(roots: tuple[str, ...]) -> list[tuple[Path, ast.ClassDef]]:
    classes: list[tuple[Path, ast.ClassDef]] = []
    for path in _files(roots):
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        classes.extend((path, node) for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    return classes


def _structural_profiles() -> list[str]:
    matches: list[str] = []
    for path, node in _python_classes(("platform", "providers", "hosts", "tests")):
        fields = {
            child.target.id
            for child in node.body
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
        }
        if _PROFILE_FIELDS <= fields:
            relative = path.relative_to(ROOT).as_posix()
            extras = ",".join(sorted(fields - _PROFILE_FIELDS)) or "NONE"
            matches.append(f"{relative}:{node.lineno}:{node.name}:extra_fields={extras}")
    return sorted(matches)


def _artifact_store_shapes() -> list[str]:
    matches: list[str] = []
    for path, node in _python_classes(("platform", "hosts", "tests")):
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if {"put", "get"} <= methods:
            relative = path.relative_to(ROOT).as_posix()
            matches.append(f"{relative}:{node.lineno}:{node.name}")
    return sorted(matches)


def test_emit_hitl_compatibility_inventory() -> None:
    sections: list[str] = []
    for name, roots, pattern in SEARCHES:
        matches = _scan(roots, pattern)
        sections.append(f"## {name} ({len(matches)})")
        sections.extend(matches or ["NONE_IN_REPOSITORY"])

    profiles = _structural_profiles()
    sections.append(f"## structural_profile_shapes ({len(profiles)})")
    sections.extend(profiles or ["NONE_IN_REPOSITORY"])

    stores = _artifact_store_shapes()
    sections.append(f"## artifact_store_shapes ({len(stores)})")
    sections.extend(stores or ["NONE_IN_REPOSITORY"])

    pytest.fail("\n" + "\n".join(sections), pytrace=False)
