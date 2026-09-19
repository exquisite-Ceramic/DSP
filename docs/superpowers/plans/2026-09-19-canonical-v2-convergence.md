# Architecture Modernization Phase II — Canonical V2 Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以事实普查、语义等价证明、逐项 cutover、merged-main observation 和显式 retirement authorization，将 planning / binding / reconciliation / saga 主干收敛到可审计的 canonical path，同时允许必要的 compatibility bridge 以 `KEEP` / `ADAPTER_ONLY` 合法存在。

**Architecture:** 本计划严格遵循 `characterize -> consumer census -> parity -> cutover -> exact-head verification -> merge -> merged-main observation -> RETIREABLE -> retirement`。Stage A 只建立事实，不修改产品行为；Stage B 冻结 canonical ownership；Stage C 仅处理已被证明为 `CUTOVER_READY` 的 item；Stage D 只在 merged-main observation 后允许 retirement；Stage E 完成 PR #55 债务归属与 Capability Phase handoff。所有 cutover 均按 compatibility item 独立 TDD、独立 commit、独立验证，禁止大爆炸式迁移。

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility、pytest、Ruff、uv workspace、PostgreSQL 17 reconciliation evidence、.NET 8 canonical / Host-neutral .NET 10 compatibility、AutoCAD/Revit real-Host acceptance gates、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-19-canonical-v2-convergence-design.md`

## Global Constraints

- Phase II 不是“删除 V1”项目；V1 只有达到 `RETIREABLE` 才允许删除。
- canonical baseline 保持 Python 3.11 与 root .NET 8 SDK policy；Python 3.14 / Host-neutral .NET 10 仅是 compatibility evidence。
- 不改变 ADR-008 / ADR-009 / ADR-010 已冻结 authoritative ownership。
- Workflow checkpoint 只能保存 workflow-local navigation state + stable refs，不能成为 ChangeSet / Approval / Saga / Host / Semantic truth 的第二 source of truth。
- Stage A 最多 2 个工作日、最多 3 个 inventory tasks、最多 1 个 dedicated inventory PR。
- 超过 inventory 任一硬上限仍缺证据的 item 必须进入 `BLOCKED`，记录缺失证据、owner、解除条件；禁止继续无限考古。
- 每个 compatibility item 最终只能是 `KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE` 之一。
- `grep` 无调用不足以证明 `RETIREABLE`；public export、runtime caller、adapter、persisted identity、schema/proto、tests、CI/runbook、real-Host boundary 都算 consumer。
- 涉及 Host-visible semantics、materialization identity、Saga transitions、recovery、durable state 的 cutover 必须保留原 owner 的 real-Host / PostgreSQL / crash-recovery gate。
- Phase II 不能因普通技术债无限阻塞 Capability Phase；exit 必须冻结 `HITL pause/resume -> real E2E workflow -> semantic->plan->approve->execute->reconcile -> MCP/Agent front door -> real AutoCAD/Revit acceptance`。

## Review Focus

1. **Persisted/hash identity 被误判为“无 consumer”**：即使 runtime import 已消失，只要 durable state / hash / serialized contract 仍存在，就必须阻止 `RETIREABLE`；Task 2/3 用 ledger validation test 固定。
2. **新业务代码继续直接 import legacy V1**：`ADAPTER_ONLY` 或已 cutover item 必须由 architecture guard 拒绝新增 direct import；Task 4/6 固定。
3. **V1/V2 结构相似但语义不等价**：hash、routing、materialization identity、Saga transition、recovery 任一不一致都不得 cutover；Task 5 固定 parity characterization。
4. **merged-main 未观察就 retirement**：branch-local GREEN 不能直接授权删除；Task 7 要求 observation evidence 才能转 `RETIREABLE`。
5. **checkpoint/compensation ownership 漂移**：HITL payload、DIVERGED compensation、checkpoint GC 必须有 owner contract，且 workflow checkpoint 不得吸收 authoritative domain truth；Task 8 固定。

---

## File / Responsibility Map

- `docs/superpowers/modernization/canonical-v2-convergence-ledger.md` — Phase II 唯一 compatibility disposition ledger；记录 item、consumer、owner、parity、blocker、rollback、observation、disposition。
- `docs/superpowers/modernization/canonical-v2-convergence-evidence.md` — exact-head / merged-main / Host / PostgreSQL / crash-recovery evidence 索引，不复制业务 truth。
- `tests/architecture/test_canonical_v2_inventory.py` — ledger schema、inventory completeness、无 `UNKNOWN/TBD`、inventory budget 与 disposition 合法性。
- `tests/architecture/test_canonical_v2_boundaries.py` — canonical / adapter-only import boundary、public export policy、新 legacy dependency 防扩散。
- `tests/architecture/test_canonical_v2_cutover_evidence.py` — `CUTOVER_READY -> RETIREABLE` 必须具备 exact-head、merged-main observation、rollback 与 required owner evidence。
- `docs/adr/ADR-011-canonical-execution-mainline.md` — 仅当 Stage B 事实结论改变 public contract / authoritative ownership / Saga semantics 时创建；否则不得为了形式强行新增 ADR。
- `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md` — Capability Phase 的 HITL payload ownership hard prerequisite。
- `docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md` — Workflow Orchestrator checkpoint retention/GC ownership contract。
- `docs/superpowers/specs/2026-09-19-compensation-execution-ownership.md` — DIVERGED compensation decision/proposal/authorization/dispatch/durable truth ownership contract；若已有等价 ADR/Spec，则更新既有文件而不是重复建模。

---

### Task 1: Stage A1 — Freeze the compatibility ledger contract and inventory budget

**Files:**
- Create: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Create: `tests/architecture/test_canonical_v2_inventory.py`
- Modify: `docs/superpowers/modernization/architecture-modernization-review-input.md`（仅增加 Phase II ledger 链接与 inventory PR/budget 状态；若文件实际命名不同，先读取现有 review-input 文件并修改该真实路径）

**Interfaces:**
- Consumes: Phase II spec §5/§6/§9/§10、MOD-016、现有 package exports。
- Produces: ledger row schema；`KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE` 唯一终态；inventory start date、task counter、dedicated PR identity。

- [ ] **Step 1: 写 ledger RED architecture test**

```python
from pathlib import Path


LEDGER = Path("docs/superpowers/modernization/canonical-v2-convergence-ledger.md")


def test_phase_ii_ledger_has_required_columns_and_dispositions() -> None:
    """Phase II ledger 必须包含完整事实字段，且处置值只能来自冻结集合。"""
    text = LEDGER.read_text(encoding="utf-8")
    for required in (
        "item_id",
        "area",
        "v1_contract_or_path",
        "v2_contract_or_path",
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
    ):
        assert required in text

    for disposition in (
        "KEEP",
        "ADAPTER_ONLY",
        "CUTOVER_READY",
        "BLOCKED",
        "RETIREABLE",
    ):
        assert disposition in text


def test_inventory_budget_is_explicit_and_bounded() -> None:
    """Inventory 必须保留 2 工作日 / 3 tasks / 1 PR 的硬边界。"""
    text = LEDGER.read_text(encoding="utf-8")
    assert "2 个工作日" in text
    assert "3" in text and "inventory task" in text.lower()
    assert "1" in text and "inventory PR" in text
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/architecture/test_canonical_v2_inventory.py -q`

Expected: FAIL，因为 Phase II ledger 尚不存在。

- [ ] **Step 3: 创建 ledger skeleton，但不填猜测事实**

Ledger 首部必须包含：

```text
Inventory status
- start_date
- working_day_budget = 2
- task_budget = 3
- dedicated_inventory_pr = <PR identity after opening>
- tasks_used = 0

Disposition values
KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE
```

表格使用 spec 的完整字段。无法证明的字段写 `EVIDENCE_MISSING:<具体证据>`，最终 inventory close 前必须转 `BLOCKED` 并补 owner/解除条件，禁止 `UNKNOWN` / `TBD`。

- [ ] **Step 4: GREEN + Ruff**

Run:

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/modernization/canonical-v2-convergence-ledger.md \
  docs/superpowers/modernization/architecture-modernization-review-input.md \
  tests/architecture/test_canonical_v2_inventory.py
git commit -m "docs: establish Phase II convergence inventory"
```

---

### Task 2: Stage A2 — Inventory public contracts, producers, and materialization/planning seams

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Test: `tests/architecture/test_canonical_v2_inventory.py`
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

**Interfaces:**
- Consumes: Task 1 ledger schema。
- Produces: inventory task 1 facts：V1/V2 public exports、producer、bridge、semantic delta、materialization seam、initial owner/disposition candidate。

- [ ] **Step 1: 先写“已知并行 public surface 必须入账”的 RED test**

```python
from pathlib import Path


def test_known_parallel_public_surfaces_are_in_ledger() -> None:
    """当前已证实的 V1/V2 public surface 不能遗漏在 inventory 外。"""
    text = Path(
        "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
    ).read_text(encoding="utf-8")
    for symbol in (
        "ExecutionPlan",
        "ExecutionPlanV2",
        "ExecutionPlanningRequest",
        "ExecutionPlanningRequestV2",
        "ProviderBindingSet",
        "ProviderBindingSetV2",
        "ProviderExecutionSnapshot",
        "ProviderExecutionSnapshotV2",
        "design_execution_reconciliation",
        "materialization_planning",
    ):
        assert symbol in text
```

- [ ] **Step 2: 运行 RED**

Run: `uv run pytest tests/architecture/test_canonical_v2_inventory.py -q`

Expected: FAIL，直到上述并行 surface 都进入 ledger。

- [ ] **Step 3: 只读 census 并填 ledger**

必须记录每个 item 的：export file、producer file、V1/V2 semantic delta、materialization identity/routing 是否参与 hash、是否存在 adapter、当前 owner。此 Task **禁止修改 production code / exports / tests behavior**。

- [ ] **Step 4: 对无法证明的字段按硬规则处理**

若 task 1 范围内无法证明 persistence/public consumer，写：

```text
cutover_blocker = EVIDENCE_MISSING:<具体证据>
disposition = BLOCKED
authoritative_owner = <明确 owner>
retirement_preconditions = <解除条件>
```

不得扩大考古范围。

- [ ] **Step 5: GREEN + commit**

Run:

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py
```

Commit: `docs: inventory canonical contract surfaces`

---

### Task 3: Stage A3 — Census runtime/test/Host/persistence/ops consumers and close inventory PR

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `tests/architecture/test_canonical_v2_inventory.py`
- Read-only census targets:
  - `tests/execution_planning/**`
  - `tests/provider_binding/**`
  - `tests/execution_coordination/**`
  - `tests/execution_reconciliation/**`
  - `tests/gateway_authorization/**`
  - `tests/integration/**`
  - orchestrator/workflow packages and tests
  - `.github/workflows/**`
  - AutoCAD/Revit acceptance/runbook paths
  - reconciliation PostgreSQL migrations/store/recovery/outbox/inbox paths

**Interfaces:**
- Consumes: Task 2 public/producers census。
- Produces: inventory tasks 2 + 3 的完整 consumer census；Stage A terminal ledger，没有 `UNKNOWN/TBD/EVIDENCE_MISSING` 未处置项。

- [ ] **Step 1: RED — ledger closeout 必须拒绝未知 owner / 无期限占位**

```python
from pathlib import Path


def test_inventory_closeout_has_no_unknown_or_tbd() -> None:
    """Stage A 结束时未知项必须显式 BLOCKED，而不是继续保留未知状态。"""
    text = Path(
        "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
    ).read_text(encoding="utf-8")
    assert "UNKNOWN" not in text
    assert "TBD" not in text
    assert "EVIDENCE_MISSING:" not in text
```

- [ ] **Step 2: 运行 RED，然后执行 runtime/test consumer census**

必须覆盖 direct import/call、adapter input/output、fixtures、architecture guards、gateway/execution coordination、orchestrator stable refs。

- [ ] **Step 3: 执行 Host/persistence/ops evidence census**

必须覆盖：

```text
serialized/hash identity
PostgreSQL schema/migrations/store/recovery
outbox/inbox/delivery
Saga durable state/controller
AutoCAD/Revit real-Host acceptance/runbook/workflow lane
checkpoint persistence / retention hooks
```

- [ ] **Step 4: 在 budget 边界强制收口**

到 2 工作日 / 第 3 inventory task / dedicated inventory PR 边界仍无法证明的 item：立刻转 `BLOCKED`，写 owner、缺什么 evidence、如何解除。不得开第 4 inventory task。

- [ ] **Step 5: Stage A verification**

Run:

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py -q
uv run pytest tests/architecture -q
uv run ruff check tests/architecture
```

Expected: inventory architecture tests GREEN；没有产品代码 diff。

- [ ] **Step 6: Commit / dedicated inventory PR closeout**

Commit: `docs: complete Phase II consumer census`

PR 描述必须记录 `tasks_used <= 3`、calendar budget、所有 `BLOCKED` owner 和没有 inventory-time product migration。

---

### Task 4: Stage B — Freeze canonical candidates and compatibility boundaries

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Create: `tests/architecture/test_canonical_v2_boundaries.py`
- Conditional create/modify: `docs/adr/ADR-011-canonical-execution-mainline.md`
- Conditional modify: package `__init__.py` / adapter modules **only after** disposition is frozen；本 Task 默认只加 guard，不做 consumer cutover。

**Interfaces:**
- Consumes: Stage A complete ledger。
- Produces: canonical candidate set、long-term `KEEP` set、`ADAPTER_ONLY` boundary、`CUTOVER_READY`/`BLOCKED` set；如 authoritative/public/Saga semantics 改变则产出 ADR。

- [ ] **Step 1: RED — 新 domain code 不得越过 ADAPTER_ONLY boundary**

```python
from pathlib import Path


FORBIDDEN_DIRECT_IMPORTS = (
    # 这里填 Stage A ledger 明确判为 ADAPTER_ONLY 的真实 legacy module。
)


def test_adapter_only_legacy_modules_are_not_imported_by_new_domain_code() -> None:
    """兼容路径只能停留在明确 adapter 边界，不能继续扩散到业务代码。"""
    roots = [Path("platform"), Path("providers")]
    for root in roots:
        for path in root.rglob("*.py"):
            if "adapter" in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            for module in FORBIDDEN_DIRECT_IMPORTS:
                assert module not in text, f"{path} directly imports {module}"
```

实现时 `FORBIDDEN_DIRECT_IMPORTS` 必须由 ledger 的真实 `ADAPTER_ONLY` rows 精确生成，不能预先假定 V1 都属于此集合。

- [ ] **Step 2: 对每个 item 冻结 Stage B disposition**

判定规则：

```text
KEEP         -> 长期合法 contract / Host boundary；补 guard 防误删。
ADAPTER_ONLY -> 只允许 explicit adapter 依赖；domain/business direct import 禁止。
CUTOVER_READY-> 已完成 characterization + census + parity proof。
BLOCKED      -> blocker + owner + release condition 完整。
RETIREABLE   -> Stage B 不得直接产生；必须等 Stage D merged-main observation。
```

- [ ] **Step 3: ADR decision gate**

若任何 Stage B 结论改变 public contract、authoritative ownership 或 Saga semantics：创建/更新 ADR，并在 ledger 引用。否则明确记录 `NO_NEW_ADR_REQUIRED`，避免无意义 ADR。

- [ ] **Step 4: GREEN + commit**

Run:

```bash
uv run pytest tests/architecture/test_canonical_v2_inventory.py \
  tests/architecture/test_canonical_v2_boundaries.py -q
uv run ruff check tests/architecture/test_canonical_v2_inventory.py \
  tests/architecture/test_canonical_v2_boundaries.py
```

Commit: `test: freeze canonical compatibility boundaries`

---

### Task 5: Stage C1 — Characterize and prove parity for each CUTOVER_READY item

**Files:**
- Modify/create focused tests under the owning package, one compatibility item at a time。
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`

**Interfaces:**
- Consumes: Stage B `CUTOVER_READY` rows only。
- Produces: executable parity evidence for semantic output、identity/hash、persistence/recovery where applicable。

- [ ] **Step 1: 为第一个 CUTOVER_READY item 写 V1 characterization test**

示例骨架；字段必须替换为该 item 的真实 contract：

```python
def test_v1_characterization_freezes_semantic_identity_and_ordering() -> None:
    """先冻结现有 V1 行为；V2 parity 不能靠字段名相似推断。"""
    v1_result = build_v1_fixture_result()
    assert v1_result.semantic_identity == EXPECTED_IDENTITY
    assert v1_result.normalized_routes == EXPECTED_ROUTES
    assert v1_result.hash == EXPECTED_HASH
```

- [ ] **Step 2: 运行 characterization，确认在未修改 production code 前 GREEN**

- [ ] **Step 3: 写 V1/V2 parity RED**

```python
def test_v2_is_semantically_equivalent_for_cutover_fixture() -> None:
    """只有语义、identity 与 durable semantics 全部等价才允许 cutover。"""
    v1_result = build_v1_fixture_result()
    v2_result = build_v2_fixture_result()
    assert normalize_semantics(v2_result) == normalize_semantics(v1_result)
    assert identity_projection(v2_result) == identity_projection(v1_result)
```

对于 planning/binding/materialization，必须比较 routing/materialization identity 与 hash body；对于 reconciliation/Saga，必须比较 transition、idempotency、recovery、durable state，而不是只比较最终 status string。

- [ ] **Step 4: 若 parity 失败，转 BLOCKED，不修改 consumer**

Ledger：

```text
disposition = BLOCKED
cutover_blocker = PARITY_FAILURE:<具体差异>
owner = <owner>
retirement_preconditions = <解除条件>
```

- [ ] **Step 5: 若 parity GREEN，记录 exact test evidence**

每个 item 单独 commit：`test: prove <item> v2 parity`

---

### Task 6: Stage C2 — Cut over one compatibility item at a time

**Files:**
- Modify: 由该 ledger row `consumers` 列出的**全部真实 consumer files**。
- Modify: owning package public exports / adapters only when该 item 的 cutover contract要求。
- Modify: `tests/architecture/test_canonical_v2_boundaries.py`
- Modify: focused package tests。
- Modify: ledger/evidence docs。

**Interfaces:**
- Consumes: 单个已完成 Task 5 parity proof 的 `CUTOVER_READY` item。
- Produces: canonical consumer set 已迁移；legacy path 无新增 direct consumer；rollback 明确。

- [ ] **Step 1: RED — architecture test 先要求 consumer 使用 canonical path**

对该 item 的实际 consumer 写精确断言；不要使用 repository-wide 模糊字符串替换。

- [ ] **Step 2: 最小迁移 consumer**

只迁移该 item；禁止同时清理相邻 V1/V2、重命名无关 API、顺手删除 bridge。

- [ ] **Step 3: focused GREEN**

Run owning-package focused tests + architecture boundary tests。

- [ ] **Step 4: owner-specific evidence**

按 ledger row 风险执行：

```text
ordinary pure-Python contract -> focused + repository regression
materialization / identity     -> Phase I materialization/offline + required real Host gate
reconciliation durable state   -> PostgreSQL 17 + restart/recovery + repository regression
Saga / Host-visible semantics  -> existing Saga/real-Host acceptance gate
```

- [ ] **Step 5: exact-head verification**

在最终候选 HEAD 上重新运行该 item 的 focused gate + repository canonical regression；证据写入 evidence doc，记录 commit SHA 和 workflow run/job identity。

- [ ] **Step 6: Commit**

每个 item 一个 cutover commit：`refactor: cut over <item> canonical path`

重复 Task 5/6 直到没有剩余可执行 `CUTOVER_READY` item；`BLOCKED` item 不允许为了 Phase 完成度被强行迁移。

---

### Task 7: Stage D — Merged-main observation, RETIREABLE authorization, and retirement

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`
- Create/modify: `tests/architecture/test_canonical_v2_cutover_evidence.py`
- Conditional delete: 仅 ledger 已转 `RETIREABLE` 的 legacy implementation/export/tests。

**Interfaces:**
- Consumes: Task 6 已 merge 到 main 的 cutover。
- Produces: merged-main observation；`RETIREABLE` authorization；必要时 legacy retirement。

- [ ] **Step 1: RED — RETIREABLE 必须拥有 merged-main evidence**

```python
from pathlib import Path


def test_retireable_rows_require_merged_main_observation() -> None:
    """Branch-local GREEN 不能授权 retirement。"""
    text = Path(
        "docs/superpowers/modernization/canonical-v2-convergence-ledger.md"
    ).read_text(encoding="utf-8")
    # 实现时解析 ledger rows；每个 RETIREABLE row 都必须有 merged_main_run 与 rollback。
    assert "merged_main_run" in text
    assert "rollback" in text
```

- [ ] **Step 2: merge 后在 main 运行 required observation**

至少包括 canonical repository regression；若该 item 有 real-Host/PostgreSQL/recovery owner gate，同样必须在 merged main 或 spec 允许的 post-merge observation lane 取得证据。

- [ ] **Step 3: 仅满足全部条件时转 RETIREABLE**

必须同时满足：

```text
all consumers cut over
merged-main observation GREEN
rollback recorded
no public compatibility obligation
no Host compatibility obligation
no persistence/hash identity obligation
```

- [ ] **Step 4: retirement RED**

先写 architecture/public API test 证明旧 path 已不应存在，再删除 legacy implementation/export。

- [ ] **Step 5: retirement regression**

Run focused + architecture + repository regression + required Host/durable evidence。

- [ ] **Step 6: Commit**

一个 retirement item 一个 commit：`refactor: retire <item> compatibility path`

如果 Phase II 最终没有任何 row 达到 `RETIREABLE`，Task 7 仍可合法完成；记录 `NO_RETIREMENTS_AUTHORIZED`，不得为了制造删除量降低门槛。

---

### Task 8: Resolve PR #55 ownership debts without expanding Phase II scope

**Files:**
- Create: `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md`
- Create: `docs/superpowers/specs/2026-09-19-compensation-execution-ownership.md`（若 Stage A 找到现有 authoritative 文档则改为修改该文件）
- Create: `docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: existing CI/hygiene tracking doc for legacy lane package declaration；若 census 证明声明错误会污染 inventory，则用独立 hygiene commit 修复并跑 workflow architecture tests。
- Create/modify: architecture tests that assert checkpoint ownership boundary where existing workflow code exposes payload/state types。

**Interfaces:**
- Consumes: Stage A consumer census、ADR-010 workflow ownership、reconciliation compensation facts。
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

分别冻结：decision owner、proposal builder、authorization owner、Host dispatcher/executor、durable truth owner、Workflow Orchestrator coordination role。禁止用 delivery success 代替 compensation business success。

- [ ] **Step 3: checkpoint retention/GC contract**

至少冻结：active/paused 不 GC；terminal minimum retention semantics；删除 checkpoint 不删除外部 authoritative state；GC 归 Workflow Orchestrator persistence ops owner；保留最小 audit metadata。

- [ ] **Step 4: legacy lane package declaration**

若它只属于 hygiene，ledger 记录 owner/next action 即可；若会导致 consumer census 漏包，则以独立 hygiene TDD/commit 修正，不和 canonical cutover 混在同一 commit。

- [ ] **Step 5: architecture verification + commit**

Run workflow/orchestrator architecture tests、reconciliation ownership tests、Ruff。

Commit: `docs: freeze Phase II ownership handoffs`

---

### Task 9: Phase II closeout and Capability Phase handoff

**Files:**
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-ledger.md`
- Modify: `docs/superpowers/modernization/canonical-v2-convergence-evidence.md`
- Create: `docs/superpowers/specs/2026-09-19-capability-phase-handoff.md`
- Modify: Phase II spec status from review-frozen to closed/implemented only after all closeout gates pass。
- Modify: relevant architecture tests to lock final state。

**Interfaces:**
- Consumes: Tasks 1–8。
- Produces: Phase II terminal disposition ledger；Capability Phase declared successor；no open ownerless debt。

- [ ] **Step 1: Closeout RED**

Architecture test 必须验证：

```text
all ledger rows have one terminal disposition
no UNKNOWN / TBD / EVIDENCE_MISSING
all BLOCKED rows have owner + release condition
all RETIREABLE rows have merged-main evidence
all four PR #55 debts have owner + next action
Capability Phase handoff doc exists
```

- [ ] **Step 2: Freeze Capability Phase order**

`2026-09-19-capability-phase-handoff.md` 必须明确：

```text
1. HITL pause/resume
2. real E2E workflow
3. semantic -> plan -> approve -> execute -> reconcile
4. MCP/Agent front door
5. real AutoCAD/Revit acceptance
```

并声明：Phase II 后续普通 hygiene / non-blocking debt 不得继续阻止 Capability Phase；只有显式 hard prerequisite 可以阻塞。

- [ ] **Step 3: Full verification**

至少运行：

```bash
uv lock --check
uv run pytest -q
uv run ruff check .
```

并按实际最终 touched/cutover rows 执行：

```text
Python 3.11 canonical regression
Python 3.14 compatibility regression
.NET 8 canonical
Host-neutral .NET 10 compatibility
Revit Core
PostgreSQL 17 reconciliation/recovery (若本 Phase cutover 触及 durable reconciliation/Saga)
Phase I materialization/offline (若本 Phase cutover 触及 planning/binding/materialization)
real AutoCAD/Revit acceptance (若对应 row 的 owner gate 要求)
```

不得为了 closeout 跑与实际 disposition 无关的新 support matrix。

- [ ] **Step 4: Exact-head final evidence**

在最终 HEAD 记录：commit SHA、每个 required workflow run/job、test counts、skip rationale、Ruff new diagnostics=0、scope diff audit。

- [ ] **Step 5: Final commit**

```bash
git add docs/superpowers/modernization/canonical-v2-convergence-ledger.md \
  docs/superpowers/modernization/canonical-v2-convergence-evidence.md \
  docs/superpowers/specs/2026-09-19-capability-phase-handoff.md \
  docs/superpowers/specs/2026-09-19-canonical-v2-convergence-design.md \
  tests/architecture
git commit -m "docs: close Phase II canonical convergence"
```

## Plan Self-Review Result

- **Spec coverage:** Stage A–E、五种 disposition、完整 cutover protocol、inventory 三重硬上限、PR #55 四项债务、Capability Phase successor 均有明确 Task。
- **No-placeholder check:** implementation 阶段不允许 `TBD/TODO/UNKNOWN` 作为 terminal ledger 值；唯一条件性内容是由 Stage A 事实决定真实 item/path/ADR 是否需要，这是 spec 要求的 evidence-driven branch，不是未设计实现。
- **Type consistency:** 本 Phase 不提前发明新的 domain V3 contract；所有 cutover interface 名称必须取自 inventory 的真实 package exports。计划只新增 governance ledger/evidence/architecture guards 与 ownership handoff contracts。
- **Review Focus coverage:** durable identity、legacy import expansion、semantic parity、merged-main observation、checkpoint/compensation ownership 分别由 Tasks 2/3、4/6、5、7、8 的 tests/gates 固定。
- **Scope discipline:** Stage A 禁止产品迁移；Stage C 只执行 `CUTOVER_READY`；Stage D 只删除 `RETIREABLE`；必要 bridge 可长期 `KEEP/ADAPTER_ONLY`，Phase II 不以删除数量作为成功标准。
