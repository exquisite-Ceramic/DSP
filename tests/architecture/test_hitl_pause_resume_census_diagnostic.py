from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


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


def test_emit_hitl_compatibility_inventory() -> None:
    sections: list[str] = []
    for name, roots, pattern in SEARCHES:
        matches = _scan(roots, pattern)
        sections.append(f"## {name} ({len(matches)})")
        sections.extend(matches or ["NONE_IN_REPOSITORY"])

    pytest.fail("\n" + "\n".join(sections), pytrace=False)
