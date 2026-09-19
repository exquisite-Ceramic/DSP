from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"


def _production_python_roots() -> tuple[Path, ...]:
    """从 repository metadata 派生 production Python roots，并纳入 tools。"""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = {
        ROOT / value
        for value in config["tool"]["uv"]["workspace"]["members"]
    }
    pythonpath = {
        ROOT / value
        for value in config["tool"]["pytest"]["ini_options"]["pythonpath"]
        if not value.startswith("tests/")
    }
    roots = members | pythonpath | {ROOT / "tools"}
    return tuple(sorted(path for path in roots if path.exists()))


def _imports(path: Path) -> set[tuple[str, str | None]]:
    """用 AST 提取真实 import，不被注释、docstring 或相似字符串误导。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found.add((node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, None))
    return found


def _production_python_files() -> tuple[Path, ...]:
    """排除 tests/cache/build，只扫描 production Python。"""
    files: set[Path] = set()
    for root in _production_python_roots():
        for path in root.rglob("*.py"):
            if any(
                part in {"tests", "__pycache__", ".venv", "build", "dist"}
                for part in path.parts
            ):
                continue
            files.add(path)
    return tuple(sorted(files))


def _ledger_rows(text: str) -> list[dict[str, str]]:
    """把 compatibility Markdown 表解析为逐列 row。"""
    lines = [line for line in text.splitlines() if line.startswith("|")]
    header_index = next(i for i, line in enumerate(lines) if line.startswith("| item_id |"))
    headers = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            break
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def _split_allowlist(value: str) -> set[str]:
    """把 ledger 的 repo-relative <br> allowlist 解析成集合。"""
    if value.startswith("N/A:"):
        return set()
    return {part.strip() for part in value.split("<br>") if part.strip()}


def _legacy_targets(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """只把稳定 module:symbol 形式视为可执行 Python legacy boundary。"""
    targets: list[tuple[str, str]] = []
    for value in row["v1_contract_or_path"].split("<br>"):
        value = value.strip()
        if not value.startswith("design_") or value.count(":") != 1:
            continue
        module, symbol = value.split(":", 1)
        targets.append((module, symbol))
    return tuple(targets)


def current_consumers(module: str, symbol: str) -> set[str]:
    """返回 production roots 中对 public module:symbol 的直接 import consumer。"""
    target = (module, symbol)
    consumers: set[str] = set()
    for path in _production_python_files():
        if target in _imports(path):
            consumers.add(path.relative_to(ROOT).as_posix())
    return consumers


def test_stage_b_freezes_disposition_specific_legacy_consumers() -> None:
    """BLOCKED/KEEP/CUTOVER_READY 必须冻结现有 legacy consumer，禁止静默扩张。"""
    text = LEDGER.read_text(encoding="utf-8")
    assert "## Stage B boundary freeze" in text

    rows = _ledger_rows(text)
    assert all(row["disposition"] != "RETIREABLE" for row in rows)

    for row in rows:
        targets = _legacy_targets(row)
        if not targets:
            continue

        actual: set[str] = set()
        for module, symbol in targets:
            exported = importlib.import_module(module)
            assert hasattr(exported, symbol), f"{row['item_id']} lost public export {module}:{symbol}"
            actual |= current_consumers(module, symbol)

        expected = _split_allowlist(row["runtime_callers"])
        disposition = row["disposition"]
        if disposition in {"KEEP", "BLOCKED", "CUTOVER_READY"}:
            assert actual == expected, (
                f"{row['item_id']} legacy consumers drifted: "
                f"expected={sorted(expected)} actual={sorted(actual)}"
            )
        elif disposition == "ADAPTER_ONLY":
            adapters = _split_allowlist(row["bridge_or_adapter"])
            assert actual <= adapters
        else:
            raise AssertionError(f"unsupported Stage B disposition: {disposition}")
