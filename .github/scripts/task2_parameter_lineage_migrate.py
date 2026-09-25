"""Task 2 临时迁移脚本：在批准的 seam census 内机械加入显式 task_id。

该文件只为当前 TDD GREEN 迁移服务。所有替换均做 AST/文本 fail-fast 校验；成功后脚本与
对应临时 workflow 会在同一个 GREEN commit 中自删除，不进入最终 product tree。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PRODUCTION_FILES = {
    Path("platform/orchestrator/src/design_orchestrator/workflow_services.py"),
    Path("platform/orchestrator/src/design_orchestrator/default_workflow_services.py"),
    Path("platform/orchestrator/src/design_orchestrator/langgraph_graph.py"),
    Path("platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py"),
}

APPROVED_TEST_FILES = {
    Path("tests/orchestrator/test_default_workflow_services.py"),
    Path("tests/orchestrator/test_langgraph_graph.py"),
    Path("tests/orchestrator/test_canonical_owner_ports.py"),
    Path("tests/orchestrator/test_real_owner_workflow_end_to_end.py"),
    Path("tests/orchestrator/test_task9_parameter_binding_lineage.py"),
    Path("tests/orchestrator/test_task9_real_owner_acceptance.py"),
    Path("tests/orchestrator/test_task10_durable_recovery.py"),
    Path("tests/orchestrator/test_workflow_end_to_end.py"),
    Path("tests/orchestrator/test_workflow_resume_authoritative_truth.py"),
    Path("tests/orchestrator/test_hitl_resume_observability.py"),
    Path("tests/orchestrator/test_langgraph_runtime.py"),
    Path("tests/orchestrator/test_legacy_hitl_migration.py"),
    Path("tests/orchestrator/test_legacy_hitl_resume_observability.py"),
    Path("tests/orchestrator/test_postgres_checkpoint.py"),
    Path("tests/orchestrator/test_task6_review_regressions.py"),
    Path("tests/orchestrator/test_task9_parameter_binding_context_validation.py"),
    Path("tests/orchestrator/test_v2_hitl_artifact_validation.py"),
}

RED_TEST = Path("tests/orchestrator/test_task2_parameter_binding_task_lineage.py")
METHODS = {"bind_parameters", "load_parameter_binding_inputs"}


def _tree(path: Path) -> ast.AST:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=str(path))


def _seam_occurrences(path: Path) -> tuple[int, int]:
    tree = _tree(path)
    defs = 0
    calls = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in METHODS:
            defs += 1
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in METHODS:
                calls += 1
    return defs, calls


def _assert_census() -> None:
    """任何计划外旧 consumer 都先阻断迁移，不能靠兼容 shim 掩盖。"""

    approved = APPROVED_TEST_FILES | {RED_TEST}
    unexpected: list[str] = []
    for absolute in sorted((ROOT / "tests/orchestrator").rglob("*.py")):
        relative = absolute.relative_to(ROOT)
        defs, calls = _seam_occurrences(relative)
        if (defs or calls) and relative not in approved:
            unexpected.append(f"{relative}: defs={defs}, calls={calls}")
    if unexpected:
        raise SystemExit("Task 2 census found unlisted consumers:\n" + "\n".join(unexpected))


def _add_task_to_defs(text: str, method: str) -> tuple[str, int]:
    """只改 multiline class/protocol method signature；已含 task_id 的定义保持不动。"""

    pattern = re.compile(
        rf"(def {method}\(\n(?P<indent>[ \t]+)self,\n)(?![ \t]+task_id: str,\n)"
    )

    def replacement(match: re.Match[str]) -> str:
        return match.group(1) + match.group("indent") + "task_id: str,\n"

    return pattern.subn(replacement, text)


def _offsets(text: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _insert_task_into_test_calls(text: str, path: Path) -> tuple[str, int]:
    """把旧两参数 direct call 迁成三参数；新 RED 已是三参数，不会重复修改。"""

    tree = ast.parse(text, filename=str(path))
    starts = _offsets(text)
    insertions: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in METHODS:
            continue
        if any(keyword.arg == "task_id" for keyword in node.keywords):
            continue
        if len(node.args) == 3:
            continue
        if len(node.args) == 2 and not node.keywords:
            first = node.args[0]
            offset = starts[first.lineno - 1] + first.col_offset
            indent = " " * first.col_offset
            insertions.append((offset, '"task-test",\n' + indent))
            continue
        raise SystemExit(
            f"Unsupported {node.func.attr} call shape in {path}:{node.lineno}: "
            f"args={len(node.args)} keywords={[item.arg for item in node.keywords]}"
        )

    for offset, insertion in sorted(insertions, reverse=True):
        text = text[:offset] + insertion + text[offset:]
    return text, len(insertions)


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one replacement target, found {count}")
    return text.replace(old, new, 1)


def _migrate_production(path: Path, text: str) -> str:
    for method in sorted(METHODS):
        text, _ = _add_task_to_defs(text, method)

    if path.name == "default_workflow_services.py":
        text = _replace_once(
            text,
            "        inputs = self._external_owners.load_parameter_binding_inputs(\n"
            "            operation_ref,\n"
            "            context_snapshot_ref,\n"
            "        )",
            "        inputs = self._external_owners.load_parameter_binding_inputs(\n"
            "            task_id,\n"
            "            operation_ref,\n"
            "            context_snapshot_ref,\n"
            "        )",
            label="DefaultWorkflowServices parameter-input delegation",
        )
    elif path.name == "langgraph_graph.py":
        text = _replace_once(
            text,
            "        result = services.bind_parameters(\n"
            "            _require_stable_ref(state, \"operation_ref\"),\n"
            "            _require_stable_ref(state, \"context_snapshot_ref\"),\n"
            "        )",
            "        result = services.bind_parameters(\n"
            "            cast(str, state[\"task_id\"]),\n"
            "            _require_stable_ref(state, \"operation_ref\"),\n"
            "            _require_stable_ref(state, \"context_snapshot_ref\"),\n"
            "        )",
            label="LangGraph parameter-binding task delegation",
        )
    elif path.name == "canonical_owner_ports.py":
        text = _replace_once(
            text,
            "        inputs = self._semantic_reconstruction.load_parameter_binding_inputs(\n"
            "            operation_space_ref,\n"
            "            context_snapshot_ref,\n"
            "        )",
            "        inputs = self._semantic_reconstruction.load_parameter_binding_inputs(\n"
            "            task_id,\n"
            "            operation_space_ref,\n"
            "            context_snapshot_ref,\n"
            "        )",
            label="Canonical owner parameter-input delegation",
        )
    return text


def _assert_migrated(path: Path) -> None:
    tree = _tree(path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in METHODS:
            names = [arg.arg for arg in node.args.args]
            if len(names) < 2 or names[1] != "task_id":
                raise SystemExit(f"{path}:{node.lineno} still lacks explicit task_id: {names}")
        if path in APPROVED_TEST_FILES and isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in METHODS:
                if len(node.args) != 3 and not any(
                    keyword.arg == "task_id" for keyword in node.keywords
                ):
                    raise SystemExit(
                        f"{path}:{node.lineno} still has unmigrated {node.func.attr} call"
                    )


def main() -> None:
    _assert_census()

    for path in sorted(PRODUCTION_FILES):
        absolute = ROOT / path
        migrated = _migrate_production(path, absolute.read_text(encoding="utf-8"))
        ast.parse(migrated, filename=str(path))
        absolute.write_text(migrated, encoding="utf-8")

    for path in sorted(APPROVED_TEST_FILES):
        absolute = ROOT / path
        text = absolute.read_text(encoding="utf-8")
        for method in sorted(METHODS):
            text, _ = _add_task_to_defs(text, method)
        text, _ = _insert_task_into_test_calls(text, path)
        ast.parse(text, filename=str(path))
        absolute.write_text(text, encoding="utf-8")

    for path in sorted(PRODUCTION_FILES | APPROVED_TEST_FILES):
        _assert_migrated(path)

    # 新 RED 本身已经使用 task-aware seam，仅做 syntax proof。
    ast.parse((ROOT / RED_TEST).read_text(encoding="utf-8"), filename=str(RED_TEST))

    # helper 不属于产品树；成功迁移时与 workflow 一起在同一 GREEN commit 中删除。
    Path(__file__).unlink()
    (ROOT / ".github/workflows/task2-parameter-lineage-migration.yml").unlink()


if __name__ == "__main__":
    main()
