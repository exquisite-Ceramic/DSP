# Architecture Modernization Phase II — Canonical V2 Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以事实普查、语义等价证明、逐项 cutover、merged-main observation 和显式 retirement authorization，将 planning / binding / reconciliation / saga 主干收敛到可审计的 canonical path，同时允许必要 compatibility bridge 以 `KEEP` / `ADAPTER_ONLY` / `BLOCKED` 合法存在。

**Architecture:** 严格遵循 `characterize -> consumer census -> parity -> cutover -> exact-head verification -> merge -> merged-main observation -> RETIREABLE -> retirement`。Stage A 只建立事实；Stage B 冻结 canonical ownership 与 legacy consumer 边界；Stage C 每个 compatibility item 独立证明 parity 并通过独立 PR cut over；Stage D 只在 merged-main observation 后授权 retirement；Stage E 完成 PR #55 债务归属与 Capability Phase handoff。

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility、pytest、Ruff、uv workspace、PostgreSQL 17 reconciliation evidence、.NET 8 canonical / Host-neutral .NET 10 compatibility、AutoCAD/Revit real-Host acceptance gates、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-19-canonical-v2-convergence-design.md`

## Global Constraints

- Phase II 不是“删除 V1”项目；legacy path 只有达到 `RETIREABLE` 才允许删除。
- canonical baseline 保持 Python 3.11 与 root .NET 8 SDK policy；Python 3.14 / Host-neutral .NET 10 仅是 compatibility evidence。
- 不改变 ADR-008 / ADR-009 / ADR-010 已冻结 authoritative ownership。
- Workflow checkpoint 只能保存 workflow-local navigation state + stable refs，不能成为 ChangeSet / Approval / Saga / Host / Semantic truth 的第二 source of truth。
- Stage A 最多 2 个工作日、最多 3 个 inventory tasks、恰好 1 个 dedicated inventory PR。
- Stage A 首个 commit 前 `dedicated_inventory_pr=PENDING` 是唯一允许的 bootstrap 值；Draft PR 创建后必须立即回填真实 `#<number>`，Task 3 closeout 必须机器验证真实 PR identity。
- 超过 inventory 任一硬上限仍缺证据的 item 必须进入 `BLOCKED`，记录缺失证据、owner、解除条件；禁止继续无限考古。
- 每个 compatibility item 只能处于 `KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE` 之一。
- `grep` 无调用不足以证明 `RETIREABLE`；public export、runtime caller、adapter、persisted identity、schema/proto、tests、CI/runbook、real-Host boundary 都算 consumer。
- 涉及 Host-visible semantics、materialization identity、Saga transitions、recovery、durable state 的 cutover 必须保留原 owner 的 real-Host / PostgreSQL / crash-recovery gate。
- Phase II 不能因普通技术债无限阻塞 Capability Phase；exit 必须冻结 `HITL pause/resume -> real E2E workflow -> semantic->plan->approve->execute->reconcile -> MCP/Agent front door -> real AutoCAD/Revit acceptance`。
- `main` 受 `protect-main` ruleset 保护；所有进入 main 的 Phase II 变更必须通过 PR 与 required checks，不允许直接 push。
- PR topology 固定为：
  - Stage A：1 个 dedicated inventory PR，Tasks 1–3 全部在此 PR 中完成。
  - Stage B：1 个 canonical-boundary-freeze PR，只冻结 disposition / guards / 必要 ADR，不做 consumer cutover。
  - Stage C：每个 compatibility item 1 个独立 PR；先提交 parity evidence，再提交最小 cutover。parity 失败时该 PR 只记录 `BLOCKED` evidence，不执行 cutover。
  - Stage D：每个已通过 merged-main observation 且真正达到 `RETIREABLE` 的 item 单独 retirement PR。
  - Stage E：1 个 ownership/handoff + final closeout PR。
- `KEEP / ADAPTER_ONLY / BLOCKED` 的 guard 语义不同，禁止用一个“全部禁止 import”的规则混用：
  - `KEEP`：contract/export 必须继续存在；当前 consumer surface 冻结，新增 consumer 必须先更新 ledger 并 review。
  - `ADAPTER_ONLY`：只有 ledger 明确列出的 adapter path 可以依赖 legacy contract；其他 production direct import 禁止。
  - `BLOCKED`：当前已登记合法 consumer 可以继续存在，但 consumer allowlist 冻结，禁止新增，直到 blocker 解除。
- Production Python scan roots 必须从 root `pyproject.toml` 的 uv workspace / pytest pythonpath 派生，并显式纳入 `tools`；不得再次手写只覆盖 `platform/providers` 的残缺 topology。
- Import guard 使用 Python AST 解析 `Import` / `ImportFrom`，不得用全文 substring 搜索模拟 import 关系。

## Review Focus

1. **Persisted/hash identity 被误判为“无 consumer”**：即使 runtime import 已消失，只要 durable state / hash / serialized contract 仍存在，就必须阻止 `RETIREABLE`；Tasks 2/3 固定。
2. **legacy consumer surface 继续扩散**：`KEEP` / `BLOCKED` 冻结现有 allowlist，`ADAPTER_ONLY` 只允许显式 adapter；Host sidecar 同样纳入 production scan；Task 4 固定。
3. **V1/V2 结构相似但语义不等价**：hash、routing、materialization identity、Saga transition、recovery 任一不一致都不得 cutover；Task 5 固定。
4. **merged-main 未观察就 retirement**：branch-local GREEN 不能直接授权删除；Task 7 解析 ledger row 并验证 merged-main evidence。
5. **checkpoint/compensation ownership 漂移**：HITL payload、DIVERGED compensation、checkpoint GC 必须有 owner contract，且 workflow checkpoint 不得吸收 authoritative domain truth；Task 8 固定。

---

## File / Responsibility Map

- `docs/superpowers/modernization/canonical-v2-convergence-ledger.md` — Phase II compatibility disposition ledger；至少包含 spec §5 的 20 个事实字段，并额外保存 exact-head / merged-main observation 字段。
- `docs/superpowers/modernization/canonical-v2-convergence-evidence.md` — workflow run/job、Host、PostgreSQL、crash-recovery evidence 索引，不复制业务 truth。
- `tests/architecture/test_canonical_v2_inventory.py` — ledger schema、row parser、inventory budget、mandatory-area completeness、consumer census closeout。
- `tests/architecture/test_canonical_v2_boundaries.py` — production root discovery、AST import census、`KEEP / ADAPTER_ONLY / BLOCKED` guard。
- `tests/architecture/test_canonical_v2_cutover_evidence.py` — exact-head / merged-main / retirement authorization。
- `tests/architecture/test_phase_ii_ownership_handoffs.py` — checkpoint / compensation / GC ownership contract guard。
- `docs/adr/ADR-011-canonical-execution-mainline.md` — 仅当 Stage B 事实结论改变 public contract / authoritative ownership / Saga semantics 时创建；否则明确记录 `NO_NEW_ADR_REQUIRED`。
- `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md` — Capability Phase HITL hard prerequisite。
- `docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md` — Workflow Orchestrator checkpoint retention/GC ownership contract。
- `docs/superpowers/specs/2026-09-19-compensation-execution-ownership.md` — DIVERGED compensation decision/proposal/authorization/dispatch/durable truth ownership contract；若存在等价 authoritative 文档则更新既有文件。

## Ledger Format Contract

Spec §5 的 20 个必需字段必须全部出现：

```text
item_id
area
v1_contract_or_path
v2_contract_or_path
bridge_or_adapter
producer
consumers
public_exports
runtime_callers
test_callers
host_dependency
authoritative_owner
persistence_owner
semantic_delta
parity_evidence
real_host_evidence
cutover_blocker
disposition
retirement_preconditions
rollback
```

为支持 executable gates，再增加：

```text
exact_head_run
merged_main_run
observation_status
```

Stage A closeout 的 `area` 列必须至少覆盖 spec §5.1 的全部 mandatory scope，使用下列稳定值：

```text
execution_planning
materialization_planning_seam
provider_binding
gateway_authorization
execution_coordination
execution_reconciliation
execution_saga
convergence_compensation
orchestrator
workflow_test_ops
real_host_acceptance
```

约定：

- Python importable contract 使用 `module:symbol`，例如 `design_execution_planning:ExecutionPlan`。
- 多个 repo-relative path 用 `<br>` 分隔，不使用自由文本逗号列表。
- 不适用字段使用 `N/A:<reason>`，不能留空。
- `EVIDENCE_MISSING:<具体证据>` **只允许出现在 `BLOCKED` row** 的 evidence/blocker 字段；这本身是合法 terminal blocker，但必须同时具备明确 owner 和 `retirement_preconditions`。
- `UNKNOWN` / `TBD` 不允许成为任何 row 的字段值。
- `RETIREABLE` row 必须有非空 `merged_main_run`、`rollback`，且 `observation_status = GREEN`。

---

### Task 1: Stage A1 — Freeze ledger contract, parser, inventory budget, and inventory PR bootstrap

**Files:**
- Create: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Create: `tests/architecture/test_canonical_v2_inventory.py`
- Modify: `docs/superpowers/modernization/architecture-modernization-review-input.md`

**Interfaces:**
- Consumes: Phase II spec §5/§6/§9/§10、MOD-016。
- Produces: 23-column ledger contract、row parser、inventory budget block、Stage A PR bootstrap identity。

- [ ] **Step 1: 写 ledger RED test，完整冻结 20+3 schema**

```python
from __future__ import annotations

import re
from pathlib import Path


LEDGER = Path("docs/superpowers/modernization/canonical-v2-convergence-ledger.md")

REQUIRED_COLUMNS = (
    "item_id",
    "area",
    "v1_contract_or_path",
    "v2_contract_or_path",
    "bridge_or_adapter",
    "producer",
    "consumers",
    "public_exports",
    "runtime_callers",
    "test_callers",
    "host_dependency",
    "authoritative_owner",
    "persistence_owner",
    "semantic_delta",
    "parity_evidence",
    "real_host_evidence",
    "cutover_blocker",
    "disposition",
    "retirement_preconditions",
    "rollback",
    "exact_head_run",
    "merged_main_run",
    "observation_status",
)


def _inventory_status(text: str) -> dict[str, str]:
    """解析 Inventory status 的稳定 key=value 区块。"""
    status: dict[str, str] = {}
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "```inventory-status":
            in_block = True
            continue
        if in_block and line == "```":
            break
        if in_block and "=" in line:
            key, value = line.split("=", 1)
            status[key.strip()] = value.strip()
    return status


def test_phase_ii_ledger_has_complete_schema() -> None:
    """Ledger 必须完整冻结 spec 20 字段和 3 个 observation 字段。"""
    text = LEDGER.read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.startswith("| item_id |"))
    for column in REQUIRED_COLUMNS:
        assert f"| {column} " in header


def test_inventory_budget_is_machine_readable_and_bounded() -> None:
    """Inventory 的 2 工作日 / 3 tasks / 1 PR 必须可执行验证。"""
    status = _inventory_status(LEDGER.read_text(encoding="utf-8"))
    assert status["working_day_budget"] == "2"
    assert status["task_budget"] == "3"
    pr_identity = status["dedicated_inventory_pr"]
    assert pr_identity == "PENDING" or re.fullmatch(r"#\d+", pr_identity)
    assert int(status["tasks_used"]) <= 3
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/architecture/test_canonical_v2_inventory.py -q`

Expected: FAIL，因为 ledger 尚不存在。

- [ ] **Step 3: 创建与 test 完全一致的 ledger skeleton**

首部必须使用：

```inventory-status
start_date=2026-09-19
working_day_budget=2
task_budget=3
dedicated_inventory_pr=PENDING
tasks_used=1
```

表格 header 使用 `REQUIRED_COLUMNS` 的全部 23 列。Task 1 只创建 schema，不写猜测 consumer 事实。

- [ ] **Step 4: GREEN + Ruff，允许 bootstrap identity 仍为 PENDING**

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py
```

Expected: PASS。

- [ ] **Step 5: 提交首个 Stage A commit 并 push 分支**

```bash
git add docs/superpowers/modernization/canonical-v2-convergence-ledger.md \
  docs/superpowers/modernization/architecture-modernization-review-input.md \
  tests/architecture/test_canonical_v2_inventory.py
git commit -m "docs: establish Phase II convergence inventory"
git push -u origin <stage-a-inventory-branch>
```

- [ ] **Step 6: 打开 Stage A Draft PR，立即回填真实 PR identity**

PR base=`main`，head=`<stage-a-inventory-branch>`。PR body 明确 Stage A 只允许 Tasks 1–3，不允许产品迁移。创建 Draft PR 后将 `dedicated_inventory_pr` 从 `PENDING` 改为真实 `#<number>`。

- [ ] **Step 7: 再跑 GREEN，并提交 PR identity 回填**

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py
git add docs/superpowers/modernization/canonical-v2-convergence-ledger.md
git commit -m "docs: record Stage A inventory PR identity"
git push
```

Task 1 完成后 `PENDING` 不得再次出现。

---

### Task 2: Stage A2 — Inventory public contracts, producers, materialization seams, Saga surface, and compensation surface

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `tests/architecture/test_canonical_v2_inventory.py`
- Read-only census targets:
  - `platform/execution_planning/src/design_execution_planning/__init__.py`
  - `platform/execution_planning/src/design_execution_planning/contracts.py`
  - `platform/execution_planning/src/design_execution_planning/v2.py`
  - `platform/materialization_planning/**`
  - `platform/provider_binding/src/design_provider_binding/__init__.py`
  - `platform/provider_binding/src/design_provider_binding/contracts.py`
  - `platform/provider_binding/src/design_provider_binding/v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/compensation.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga_v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga_contracts_v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga_state_v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga_store_v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/saga_transitions_v2.py`
  - `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_saga_store_v2.py`

**Interfaces:**
- Consumes: Task 1 ledger schema。
- Produces: inventory task 1 facts：V1/V2 public exports、producer、bridge、semantic delta、materialization seam、Saga/compensation surface、initial disposition。

- [ ] **Step 1: 写 exact-column RED test，禁止子串误判**

```python
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


def test_known_parallel_public_surfaces_are_exactly_in_ledger() -> None:
    """已证实的 V1/V2 surface 必须出现在对应列，而不是靠 V2 子串误满足 V1。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    pairs = {
        (row["v1_contract_or_path"], row["v2_contract_or_path"])
        for row in rows
    }
    assert (
        "design_execution_planning:ExecutionPlan",
        "design_execution_planning:ExecutionPlanV2",
    ) in pairs
    assert (
        "design_provider_binding:ProviderBindingSet",
        "design_provider_binding:ProviderBindingSetV2",
    ) in pairs
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/architecture/test_canonical_v2_inventory.py -q`

Expected: FAIL，直到 exact V1/V2 pairs 已进入 ledger。

- [ ] **Step 3: 只读 census 并填 ledger**

每个 item 至少记录 export file、producer、bridge、semantic delta、materialization/routing/hash identity、Saga state/store/controller、compensation relation。此 Task 禁止修改 production code / exports / runtime behavior。

- [ ] **Step 4: 处理无法在本 inventory task 证明的事实**

合法终态示例：

```text
disposition = BLOCKED
cutover_blocker = EVIDENCE_MISSING:PostgreSQL restart parity for saga state
authoritative_owner = Execution Reconciliation
retirement_preconditions = Prove PostgreSQL 17 restart/recovery parity on the recorded durable schema
```

不得继续扩大 archaeology scope；`EVIDENCE_MISSING:` 不需要伪装成其他字符串。

- [ ] **Step 5: 更新 inventory counter 并验证**

将 `tasks_used=2` 写回 status block。

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py
```

Commit: `docs: inventory canonical contract surfaces`

---

### Task 3: Stage A3 — Census runtime, tests, gateway, coordination, Host, persistence, ops, and close inventory PR

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `tests/architecture/test_canonical_v2_inventory.py`
- Read-only production census targets:
  - `platform/gateway_authorization/src/**`
  - `platform/execution_coordination/src/**`
  - `platform/orchestrator/src/**`
  - `platform/convergence/src/**`
  - `hosts/autocad/sidecar/src/**`
  - `hosts/revit/sidecar/src/**`
  - `tools/**`
  - `contracts/python/**`
  - reconciliation PostgreSQL migrations/store/recovery/outbox/inbox/delivery paths
- Read-only test/ops census targets:
  - `tests/execution_planning/**`
  - `tests/provider_binding/**`
  - `tests/execution_coordination/**`
  - `tests/execution_reconciliation/**`
  - `tests/gateway_authorization/**`
  - `tests/integration/**`
  - `tests/architecture/**`
  - orchestrator/workflow tests
  - `.github/workflows/**`
  - AutoCAD/Revit acceptance/runbooks

**Interfaces:**
- Consumes: Task 2 producer/public census。
- Produces: runtime/test/Host/persistence/ops consumer census；Stage A terminal ledger；`tasks_used=3`。

- [ ] **Step 1: 写 row-aware closeout RED，并机器强制 spec §5.1 mandatory areas**

```python
ALLOWED_DISPOSITIONS = {
    "KEEP",
    "ADAPTER_ONLY",
    "CUTOVER_READY",
    "BLOCKED",
    "RETIREABLE",
}

REQUIRED_INVENTORY_AREAS = {
    "execution_planning",
    "materialization_planning_seam",
    "provider_binding",
    "gateway_authorization",
    "execution_coordination",
    "execution_reconciliation",
    "execution_saga",
    "convergence_compensation",
    "orchestrator",
    "workflow_test_ops",
    "real_host_acceptance",
}


def test_inventory_closeout_rows_are_terminal_owned_and_complete() -> None:
    """Stage A 必须覆盖 spec mandatory areas，并把未知项收口成受约束 BLOCKED。"""
    text = LEDGER.read_text(encoding="utf-8")
    rows = _ledger_rows(text)
    assert rows

    observed_areas = {row["area"] for row in rows}
    assert REQUIRED_INVENTORY_AREAS <= observed_areas

    status = _inventory_status(text)
    assert re.fullmatch(r"#\d+", status["dedicated_inventory_pr"])
    assert status["tasks_used"] == "3"

    for row in rows:
        assert row["disposition"] in ALLOWED_DISPOSITIONS
        for field in (
            "producer",
            "consumers",
            "authoritative_owner",
            "persistence_owner",
            "retirement_preconditions",
            "rollback",
        ):
            assert row[field] not in {"", "UNKNOWN", "TBD"}

        has_missing_evidence = any(
            "EVIDENCE_MISSING:" in row[field]
            for field in ("parity_evidence", "real_host_evidence", "cutover_blocker")
        )
        if has_missing_evidence:
            assert row["disposition"] == "BLOCKED"
            assert row["cutover_blocker"].startswith("EVIDENCE_MISSING:")
            assert row["authoritative_owner"] not in {"", "UNKNOWN", "TBD"}
            assert row["retirement_preconditions"] not in {"", "UNKNOWN", "TBD"}
```

- [ ] **Step 2: 执行 runtime/test consumer census**

必须覆盖 direct import/call、adapter I/O、fixtures、architecture guards、gateway、execution coordination、orchestrator stable refs。Gateway/coordination **production src** 不能只看 tests。

- [ ] **Step 3: 执行 Host/persistence/ops census**

必须覆盖：

```text
serialized/hash identity
PostgreSQL schema/migrations/store/recovery
outbox/inbox/delivery
Saga durable state/controller
AutoCAD/Revit sidecar runtime imports
real-Host acceptance/runbook/workflow lane
checkpoint persistence / retention hooks
```

- [ ] **Step 4: 在 budget 边界强制收口**

将 `tasks_used=3` 写回 ledger。仍无法证明的 item 立即 `BLOCKED`，写 concrete missing evidence、owner、解除条件；不得创建第 4 个 inventory task。Stage A closeout 前必须保证 `REQUIRED_INVENTORY_AREAS` 每个 area 至少有一个 ledger row；不能只靠 prose 声称已覆盖。

- [ ] **Step 5: Stage A verification**

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run pytest tests/architecture -q
uv run ruff check tests/architecture
```

Expected: inventory architecture tests GREEN；Stage A diff 不包含 product behavior migration。

- [ ] **Step 6: close Stage A dedicated inventory PR**

PR body 必须记录：

```text
tasks_used = 3
working_day_budget <= 2
one dedicated inventory PR only
all mandatory inventory areas covered
all BLOCKED rows have owner + release condition
no inventory-time product migration
```

通过 required checks 和 review 后 merge 到 main。Stage B 从 merged main 新分支开始。

---

### Task 4: Stage B — Freeze canonical candidates and disposition-specific legacy boundaries

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Create: `tests/architecture/test_canonical_v2_boundaries.py`
- Conditional create/modify: `docs/adr/ADR-011-canonical-execution-mainline.md`
- Conditional modify: package `__init__.py` / adapter modules only when disposition freeze requires an explicit compatibility adapter export；默认不做 consumer cutover。

**Interfaces:**
- Consumes: merged Stage A ledger。
- Produces: canonical candidate set、`KEEP` / `ADAPTER_ONLY` / `BLOCKED` guard policy、`CUTOVER_READY` set、必要 ADR。

- [ ] **Step 1: 写 production-root + AST import helper RED**

```python
from __future__ import annotations

import ast
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
            if any(part in {"tests", "__pycache__", ".venv", "build", "dist"} for part in path.parts):
                continue
            files.add(path)
    return tuple(sorted(files))
```

- [ ] **Step 2: 写三类 disposition guard RED**

实现 helper `current_consumers(module, symbol)`，返回 repo-relative consumer path 集合。根据 ledger row：

```text
KEEP
  -> public export/contract 仍存在
  -> current consumer set == ledger runtime_callers allowlist

ADAPTER_ONLY
  -> current consumer set <= bridge_or_adapter allowlist
  -> 非 adapter production consumer 必须为 0

BLOCKED
  -> current consumer set == ledger runtime_callers allowlist
  -> 允许现有 consumer，但禁止新增
```

`CUTOVER_READY` 在 cutover 前同样冻结现有 legacy consumer set；`RETIREABLE` 在 Stage B 不允许出现。

不得通过 `if "adapter" in path.name` 猜 adapter；允许路径来自 ledger `bridge_or_adapter` 的精确 repo-relative paths。

- [ ] **Step 3: 冻结每个 item 的 Stage B disposition**

判定必须基于 Stage A facts：

```text
KEEP         -> 长期合法 contract / Host boundary
ADAPTER_ONLY -> legacy 仅存在于 explicit adapter
CUTOVER_READY-> characterization + census + parity prerequisites 已具备
BLOCKED      -> blocker + owner + release condition 完整
RETIREABLE   -> 本 Stage 禁止产生
```

- [ ] **Step 4: ADR decision gate**

若任一 Stage B 结论改变 public contract、authoritative ownership 或 Saga semantics，创建/更新 ADR-011 并在 ledger 引用；否则 ledger 记录 `NO_NEW_ADR_REQUIRED`。

- [ ] **Step 5: GREEN + repository boundary verification**

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py \
  tests/architecture/test_canonical_v2_boundaries.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py \
  tests/architecture/test_canonical_v2_boundaries.py
```

- [ ] **Step 6: Stage B PR**

只提交 ledger/guards/必要 ADR；通过 required checks 和 review 后 merge。不得把任何 consumer cutover 混入此 PR。

---

### Task 5: Stage C1 — Characterize and prove parity for one CUTOVER_READY item

**Files:**
- Modify/create focused tests under the owning package for **one** ledger item。
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`

**Interfaces:**
- Consumes: merged Stage B 中单个 `CUTOVER_READY` row。
- Produces: executable parity evidence；若失败则把该 item 转 `BLOCKED`。

- [ ] **Step 1: 为该 item 写 V1 characterization test**

示例结构；实施时替换为 inventory 中的真实 contract 与 fixture：

```python
def test_v1_characterization_freezes_semantic_identity_and_ordering() -> None:
    """先冻结现有 V1 行为，禁止用字段名相似替代 parity 证明。"""
    v1_result = build_v1_fixture_result()
    assert v1_result.semantic_identity == EXPECTED_IDENTITY
    assert v1_result.normalized_routes == EXPECTED_ROUTES
    assert v1_result.hash == EXPECTED_HASH
```

- [ ] **Step 2: 在未改 production code 前运行 characterization**

Expected: GREEN。若 characterization 本身无法稳定复现，item 直接转 `BLOCKED`，不得开始 cutover。

- [ ] **Step 3: 写 V1/V2 parity RED**

```python
def test_v2_is_semantically_equivalent_for_cutover_fixture() -> None:
    """语义、identity、hash 与 durable semantics 全部等价才允许 cutover。"""
    v1_result = build_v1_fixture_result()
    v2_result = build_v2_fixture_result()
    assert normalize_semantics(v2_result) == normalize_semantics(v1_result)
    assert identity_projection(v2_result) == identity_projection(v1_result)
```

要求：

```text
planning/binding/materialization
  -> routing + materialization identity + hash body

reconciliation/Saga
  -> transitions + idempotency + durable state + restart/recovery

Host-visible semantics
  -> existing real-Host acceptance evidence
```

- [ ] **Step 4: parity 失败时 fail closed**

Ledger：

```text
disposition = BLOCKED
cutover_blocker = PARITY_FAILURE:<具体差异>
authoritative_owner = <已冻结 owner>
retirement_preconditions = <解除该差异所需 evidence/implementation>
```

此时该 item PR 不允许进入 Task 6。

- [ ] **Step 5: parity GREEN 时记录 exact focused evidence**

单独 commit：`test: prove <item> v2 parity`

继续同一个 item PR 的 Task 6。

---

### Task 6: Stage C2 — Cut over the same compatibility item and merge its independent PR

**Files:**
- Modify: 该 ledger row `consumers/runtime_callers/public_exports` 指出的全部真实 consumer files。
- Modify: owning package public exports / explicit adapters，仅当该 item 的 cutover contract要求。
- Modify: `tests/architecture/test_canonical_v2_boundaries.py`
- Modify: focused package tests。
- Modify: ledger/evidence docs。

**Interfaces:**
- Consumes: Task 5 同一 PR 内已 GREEN 的 parity evidence。
- Produces: canonical consumers 已迁移；legacy consumer allowlist 缩减；exact-head evidence；独立 cutover PR merge。

- [ ] **Step 1: RED — 精确 consumer 必须使用 canonical path**

对 ledger 已登记 consumer 写 AST 或 import-level 精确断言；禁止 repository-wide 字符串替换。

- [ ] **Step 2: 最小迁移该 item**

只迁移当前 item；禁止顺手：
- 删除相邻 legacy API；
- rename unrelated V2；
- 修改其他 item disposition；
- 扩大 Host support matrix。

- [ ] **Step 3: focused GREEN + boundary GREEN**

运行 owning-package focused tests 与：

```bash
uv run pytest tests/architecture/test_canonical_v2_boundaries.py -q
```

- [ ] **Step 4: owner-specific evidence**

```text
ordinary pure-Python contract -> focused + repository regression
materialization / identity     -> Phase I materialization/offline + required real Host gate
reconciliation durable state   -> PostgreSQL 17 + restart/recovery + repository regression
Saga / Host-visible semantics  -> existing Saga / real-Host acceptance gate
```

- [ ] **Step 5: exact-head verification**

在最终 candidate HEAD 重新跑该 item 所需 focused + canonical regression；在 evidence doc 记录 commit SHA、workflow run/job、test counts、skip rationale。

- [ ] **Step 6: cutover commit + PR merge**

Commit: `refactor: cut over <item> canonical path`

同一 PR 只能包含这个 compatibility item 的 parity + cutover。required checks/review GREEN 后 merge 到 main。

- [ ] **Step 7: 从最新 merged main 开始下一个 item**

不得在旧长期分支连续叠加多个 cutover。重复 Tasks 5/6，直到没有可执行 `CUTOVER_READY` item。

---

### Task 7: Stage D — Observe merged main, authorize RETIREABLE, and retire only authorized legacy paths

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`
- Create/modify: `tests/architecture/test_canonical_v2_cutover_evidence.py`
- Conditional delete: 仅已转 `RETIREABLE` 的 legacy implementation/export/tests。

**Interfaces:**
- Consumes: Task 6 已 merge 到 main 的单个 cutover。
- Produces: merged-main observation；`RETIREABLE` authorization；必要时独立 retirement PR。

- [ ] **Step 1: RED — row-aware RETIREABLE gate**

```python
def test_retireable_rows_require_merged_main_observation() -> None:
    """RETIREABLE 必须由 merged-main evidence 授权，不能靠列名或 branch-local GREEN。"""
    rows = _ledger_rows(LEDGER.read_text(encoding="utf-8"))
    for row in rows:
        if row["disposition"] != "RETIREABLE":
            continue
        assert row["merged_main_run"].startswith("run:")
        assert row["observation_status"] == "GREEN"
        assert row["rollback"] not in {"", "UNKNOWN", "TBD", "N/A"}
```

- [ ] **Step 2: 在 merged main 运行 required observation**

至少运行 canonical repository regression。若 item 绑定 real-Host/PostgreSQL/recovery gate，同样必须取得 spec 允许的 post-merge evidence。

- [ ] **Step 3: 仅满足全部条件时转 RETIREABLE**

```text
all consumers cut over
merged-main observation GREEN
rollback recorded
no public compatibility obligation
no Host compatibility obligation
no persistence/hash identity obligation
```

否则保持当前 disposition 或转 `BLOCKED`；不得为了删除量降低标准。

- [ ] **Step 4: retirement RED**

先写 architecture/public API test 证明 legacy path 已不应存在，再删除 implementation/export。若只是 `ADAPTER_ONLY` / `KEEP` / `BLOCKED`，本步骤不得执行。

- [ ] **Step 5: retirement regression**

运行 focused + architecture + repository regression + required Host/durable evidence。

- [ ] **Step 6: 独立 retirement PR**

每个 `RETIREABLE` item 独立 commit/PR：

```text
refactor: retire <item> compatibility path
```

若没有 item 达到 `RETIREABLE`，记录 `NO_RETIREMENTS_AUTHORIZED`，Task 7 合法完成。

---

### Task 8: Resolve PR #55 ownership debts without expanding Phase II scope

**Files:**
- Create: `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md`
- Create/modify: `docs/superpowers/specs/2026-09-19-compensation-execution-ownership.md`
- Create: `docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: existing CI/hygiene tracking doc for legacy lane package declaration。
- Create: `tests/architecture/test_phase_ii_ownership_handoffs.py`

**Interfaces:**
- Consumes: Stage A census、ADR-010 workflow ownership、reconciliation compensation facts。
- Produces: 四项债务各有 owner / next action / acceptance evidence；HITL payload ownership 成为 Capability Phase hard prerequisite。

- [ ] **Step 1: HITL ownership contract**

必须明确：

```text
checkpoint MAY own:
- workflow-local navigation state
- stable refs
- presentation metadata

checkpoint MUST NOT own authoritative copies of:
- ChangeSet
- Approval / ExecutionGrant
- Saga truth
- Host truth
- Semantic truth
```

- [ ] **Step 2: DIVERGED compensation ownership contract**

分别冻结 decision owner、proposal builder、authorization owner、Host dispatcher/executor、durable truth owner、Workflow Orchestrator coordination role。delivery success 不能等价 compensation business success。

- [ ] **Step 3: checkpoint retention/GC contract**

至少冻结 active/paused 不 GC；terminal minimum retention semantics；checkpoint deletion 不删除外部 authoritative state；GC 归 Workflow Orchestrator persistence ops owner；保留最小 audit metadata。

- [ ] **Step 4: legacy lane package declaration**

若只属于 hygiene，ledger 记录 owner/next action；若会导致 consumer census 漏包，以独立 hygiene commit 修正，不与 canonical cutover 混合。

- [ ] **Step 5: 写 architecture tests 固定 ownership boundary**

`tests/architecture/test_phase_ii_ownership_handoffs.py` 至少检查：
- 三份 ownership contract 存在；
- HITL contract 明确 stable refs / prohibited authoritative copies；
- compensation contract 明确六类 owner；
- retention contract 明确 active/paused no-GC 与 external state isolation。

- [ ] **Step 6: 精确验证命令**

```bash
uv run pytest tests/architecture/test_workflow_runtime_boundary.py \
  tests/architecture/test_phase_ii_ownership_handoffs.py \
  tests/execution_reconciliation -q
uv run ruff check tests/architecture/test_phase_ii_ownership_handoffs.py
```

Commit: `docs: freeze Phase II ownership handoffs`

---

### Task 9: Phase II closeout and Capability Phase handoff

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`
- Create: `docs/superpowers/specs/2026-09-19-capability-phase-handoff.md`
- Modify: Phase II spec status only after all closeout gates pass。
- Modify: relevant architecture tests。

**Interfaces:**
- Consumes: Tasks 1–8。
- Produces: terminal disposition ledger；Capability Phase declared successor；no ownerless debt。

- [ ] **Step 1: Closeout RED 使用 row parser，不做全文 substring 禁令**

Architecture test 必须逐 row 验证：

```text
disposition ∈ KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE
producer / consumer / owner / rollback 不为空
UNKNOWN / TBD 不得作为字段值
EVIDENCE_MISSING 只允许 BLOCKED，且 owner + release condition 完整
KEEP / ADAPTER_ONLY / BLOCKED 均有对应 guard
RETIREABLE 均有 merged-main GREEN
四项 PR #55 债务均有 owner + next action
Capability Phase handoff doc exists
```

注意：合法 `BLOCKED` row 可以保留 `EVIDENCE_MISSING:<具体证据>`，不得用全文 `assert "EVIDENCE_MISSING" not in text` 误杀。

- [ ] **Step 2: Freeze Capability Phase order**

`2026-09-19-capability-phase-handoff.md` 必须明确：

```text
1. HITL pause/resume
2. real E2E workflow
3. semantic -> plan -> approve -> execute -> reconcile
4. MCP/Agent front door
5. real AutoCAD/Revit acceptance
```

并声明 Phase II 后续普通 hygiene / non-blocking debt 不得继续阻止 Capability Phase；只有显式 hard prerequisite 可以阻塞。

- [ ] **Step 3: Full verification**

至少：

```bash
uv lock --check
uv run pytest -q
uv run ruff check .
```

按实际 touched/cutover rows 再执行：

```text
Python 3.11 canonical regression
Python 3.14 compatibility regression
.NET 8 canonical
Host-neutral .NET 10 compatibility
Revit Core
PostgreSQL 17 reconciliation/recovery（若触及 durable reconciliation/Saga）
Phase I materialization/offline（若触及 planning/binding/materialization）
real AutoCAD/Revit acceptance（若 row owner gate 要求）
```

不得为了 closeout 新增无关 support matrix。

- [ ] **Step 4: Exact-head final evidence**

记录 commit SHA、required workflow run/job、test counts、skip rationale、Ruff new diagnostics=0、scope diff audit。

- [ ] **Step 5: Stage E closeout PR**

Final commit：

```bash
git add docs/superpowers/modernization/canonical-v2-convergence-ledger.md \
  docs/superpowers/modernization/canonical-v2-convergence-evidence.md \
  docs/superpowers/specs/2026-09-19-capability-phase-handoff.md \
  docs/superpowers/specs/2026-09-19-canonical-v2-convergence-design.md \
  tests/architecture
git commit -m "docs: close Phase II canonical convergence"
```

通过 `protect-main` required checks 与 review 后 merge。

## Plan Self-Review Result

- **Spec coverage:** Stage A–E、五种 disposition、完整 cutover protocol、2 工作日 / 3 tasks / 1 inventory PR、PR #55 四项债务、Capability Phase successor 均映射到明确 Task。
- **Ledger schema:** spec §5 的 20/20 字段全部进入 enforceable test；额外 3 个 evidence 字段支持 exact-head / merged-main gate。
- **Inventory area completeness:** spec §5.1 的 11 个 mandatory scopes 都映射到稳定 `area` 值，并在 Task 3 closeout 由 set inclusion 机器强制。
- **PR bootstrap reachability:** Task 1 首个 commit 允许 `dedicated_inventory_pr=PENDING`；branch push 后创建 Draft PR、立即回填真实 `#<number>`，Task 3 closeout 强制真实 PR identity，消除 clean-branch PR/commit 循环。
- **RED -> GREEN reachability:** inventory budget test 与 skeleton 使用同一 machine-readable `inventory-status`；不存在 Task 1 的字符串/下划线对撞。
- **Blocked evidence semantics:** `EVIDENCE_MISSING:<具体证据>` 是合法 `BLOCKED` terminal blocker；closeout 解析 row，不再做全文 substring 禁令。
- **Boundary coverage:** production roots 从 repo metadata 派生，覆盖 AutoCAD/Revit sidecar、platform packages、providers、contracts/python 与 tools；AST import guard 不依赖字符串搜索。
- **Disposition guards:** `KEEP` 保持 contract/export 并冻结 consumer；`ADAPTER_ONLY` 仅允许 explicit adapter；`BLOCKED` 冻结现有 consumer allowlist，避免误杀合法 legacy dependency。
- **Census coverage:** reconciliation Saga/state/store/controller/compensation、gateway/coordination production src、Host sidecar、persistence/ops 均进入显式 targets。
- **PR topology:** Stage A、Stage B、per-item Stage C、per-item Stage D、Stage E 都有明确 PR/merge 边界，满足 protected main 和 merged-main observation 顺序。
- **Weak assertion cleanup:** public surface 使用 parsed columns + exact pairs；RETIREABLE 使用逐 row evidence；adapter exception 使用 explicit path allowlist；Task 8 有精确 pytest/Ruff 命令。
- **Scope discipline:** Stage A 禁止产品迁移；Stage C 只执行 `CUTOVER_READY`；Stage D 只删除 `RETIREABLE`；必要 bridge 可长期 `KEEP / ADAPTER_ONLY / BLOCKED`，Phase II 不以删除数量作为成功标准。
