from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
_SELF = "tests/architecture/test_hitl_pause_resume_census_diagnostic.py:"

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

COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "public_exports",
        (
            "rg",
            "-n",
            "WorkflowResumeCommand|WorkflowCheckpointView|PendingInteraction",
            "platform",
            "hosts",
            "tests",
            "contracts",
        ),
    ),
    (
        "resume_callers",
        ("rg", "-n", r"WorkflowResumeCommand\(", "platform", "hosts", "tests"),
    ),
    (
        "artifact_store",
        (
            "rg",
            "-n",
            "WorkflowArtifactStore|_MemoryArtifactStore|artifact_store",
            "platform",
            "hosts",
            "tests",
        ),
    ),
    (
        "capability_profiles",
        (
            "rg",
            "-n",
            "CapabilityProfile|provider_candidates|ResolutionResult",
            "platform",
            "providers",
            "hosts",
            "tests",
        ),
    ),
    (
        "wait_resume_compatibility",
        (
            "rg",
            "-n",
            r"await_operation_proposal|ASYNC_OPERATION_COMPLETED|resume\(.*None",
            "platform",
            "hosts",
            "tests",
        ),
    ),
    (
        "persisted_checkpoint",
        (
            "rg",
            "-n",
            "orchestrator_checkpoint|checkpoint_ns|operation_ref",
            "platform",
            "tests",
            "docs/runbooks",
            ".github/workflows",
        ),
    ),
    (
        "host_plugin_callers",
        (
            "rg",
            "-n",
            "design_orchestrator.*workflow|workflow_contracts|workflow_port",
            "hosts",
            "contracts",
        ),
    ),
)


def _python_files(roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root_name in roots:
        root = ROOT / root_name
        if root.exists():
            files.extend(root.rglob("*.py"))
    return sorted(set(files))


def _python_classes(roots: tuple[str, ...]) -> list[tuple[Path, ast.ClassDef]]:
    classes: list[tuple[Path, ast.ClassDef]] = []
    for path in _python_files(roots):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        classes.extend((path, node) for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    return classes


def _structural_profiles() -> list[str]:
    matches: list[str] = []
    for path, node in _python_classes(("platform", "providers", "hosts", "tests")):
        if path == Path(__file__).resolve():
            continue
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
        if path == Path(__file__).resolve():
            continue
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if {"put", "get"} <= methods:
            relative = path.relative_to(ROOT).as_posix()
            matches.append(f"{relative}:{node.lineno}:{node.name}")
    return sorted(matches)


def _run_exact_command(name: str, command: tuple[str, ...]) -> list[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        pytest.fail(
            f"{name} command failed with {completed.returncode}: {completed.stderr}",
            pytrace=False,
        )
    return [
        line
        for line in completed.stdout.splitlines()
        if line and not line.startswith(_SELF)
    ]


def test_emit_hitl_compatibility_inventory() -> None:
    sections: list[str] = []
    for name, command in COMMANDS:
        matches = _run_exact_command(name, command)
        sections.append(f"## {name} ({len(matches)})")
        sections.extend(matches or ["NONE_IN_REPOSITORY"])

    profiles = _structural_profiles()
    sections.append(f"## structural_profile_shapes ({len(profiles)})")
    sections.extend(profiles or ["NONE_IN_REPOSITORY"])

    stores = _artifact_store_shapes()
    sections.append(f"## artifact_store_shapes ({len(stores)})")
    sections.extend(stores or ["NONE_IN_REPOSITORY"])

    pytest.fail("\n" + "\n".join(sections), pytrace=False)
