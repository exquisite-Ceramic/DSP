# Durable Persistence Reference Runbook

本 runbook 定义 DSP 当前 **Execution Saga V2 durable persistence reference implementation** 的部署、迁移、运行与故障检查方式。它实现 ADR-008 的 owner-local durable state 原则，并保持 ADR-009 的 crash-recovery / CAS 语义；它不是“平台共享数据库”的授权，也不改变 Host、D5、ChangeSet、Gateway 等其他 owner 的权威边界。

当前参考实现使用 PostgreSQL，owner schema 为 `execution_saga`。PostgreSQL 是物理持久化参考实现，不是领域契约；`ExecutionSagaStoreV2` 的可观察语义仍由 provider-neutral domain contract 与共享 transition engine 定义。

## 1. 权威边界

Execution Saga owner 只持久化自己的执行与 reconciliation truth：

- immutable `ExecutionSagaDefinitionV2`；
- `saga_revision`；
- Saga status；
- 各 REQUIRED Slice 的 admission / Host commit / reconciliation evidence；
- convergence outcome；
- 用于恢复的完整版本化 Saga snapshot。

它 **不是** 以下状态的 owner：

- Host-native design state；
- D5 projection / Snapshot / DirtyMap；
- ChangeSet；
- ApprovalRecord / ExecutionGrant；
- InteractionSession；
- workflow checkpoint。

因此运行时、运维脚本和人工 SQL 都不得把 `execution_saga` 当作这些 owner 的镜像数据库，也不得通过跨 schema SQL join 绕过公开 contract。

## 2. PostgreSQL owner schema

当前 migration 创建：

```text
execution_saga.schema_migrations
execution_saga.saga_v2
```

`saga_v2` 的关键列包括：

```text
saga_id
saga_revision
definition_hash
status
snapshot
updated_at
```

`snapshot` 是版本化 JSONB persistence payload；`saga_revision`、`definition_hash`、`status` 同时作为可索引/可检查的冗余列。读取时 adapter 会核对这些列与 snapshot 内容是否一致；不一致视为持久化完整性错误，而不是自动“修复”。

## 3. 迁移责任

`PostgresExecutionSagaStoreV2` **不会在构造时自动执行 migration**。部署/启动边界必须先显式迁移，再创建 store。这样 schema lifecycle 与业务请求 lifecycle 不混在一起，也避免每个 worker 都隐式拥有 DDL 权限。

当前 migration API：

```python
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)

conn = connect_postgres(postgres_dsn)
try:
    apply_execution_saga_migrations(conn)
finally:
    conn.close()
```

Migration 文件位于：

```text
platform/execution_reconciliation/src/design_execution_reconciliation/migrations/
```

迁移按版本文件名单调执行，并登记到 `execution_saga.schema_migrations`。不得通过手工修改 migration ledger 来跳过未执行的 DDL。

## 4. Credential scope

推荐区分 **migration credential** 与 **runtime credential**。

Migration credential 需要创建/修改 `execution_saga` owner schema 所需的 DDL 权限。Runtime credential 只需要 Execution Saga 运行所需的最小读写权限，例如对 `execution_saga.saga_v2` 的 `SELECT / INSERT / UPDATE`，以及读取必要 migration 状态时的最小权限。

无论是否在同一个 PostgreSQL deployment 中，Execution Saga credential 都：

- MUST NOT 读写 `semantic_runtime` / D5 owner schema；
- MUST NOT 读写 Gateway owner schema；
- MUST NOT 读写 ChangeSet owner schema；
- MUST NOT 通过跨 owner foreign key、trigger 或 SQL transaction 建立新的隐藏耦合；
- MUST NOT 获得“为了方便”而授予的全库超级用户权限。

共享 PostgreSQL 实例不等于共享 ownership。

## 5. 显式 backend 选择

公共运行时入口：

```python
from design_execution_reconciliation import create_execution_saga_store_v2
```

内存 backend：

```python
store = create_execution_saga_store_v2(backend="memory")
```

PostgreSQL backend：

```python
store = create_execution_saga_store_v2(
    backend="postgres",
    postgres_dsn=postgres_dsn,
)
```

规则：

- `backend` 必须由调用方显式选择；
- `postgres` 必须显式传入非空 `postgres_dsn`；
- unknown backend fail closed；
- factory **不会**因为环境中碰巧存在 DSN 就自动从 `memory` 切到 `postgres`；
- PostgreSQL adapter 使用 lazy import，provider-neutral package import 不应隐式加载数据库 driver。

`DSP_TEST_POSTGRES_DSN` 是当前测试/CI 的 PostgreSQL test DSN 名称，不是生产 backend 自动发现机制。

## 6. CAS 与并发语义

每个会改变 Saga state 的持久化 transition 都必须保留外部可观察的 revision CAS：

```sql
UPDATE execution_saga.saga_v2
SET saga_revision = :next_revision,
    status = :next_status,
    snapshot = :next_snapshot,
    updated_at = now()
WHERE saga_id = :saga_id
  AND saga_revision = :expected_revision;
```

如果受影响行数不是 1，adapter 返回 `SAGA_CONFLICT`。不得仅依赖行锁并删除 `WHERE saga_revision = expected_revision`，因为 CAS 是 `ExecutionSagaStoreV2` contract 的一部分。

同 evidence replay 如果领域 transition 判定为 no-op，则返回当前 durable state，不额外递增 revision；这与 InMemory backend 的 observable semantics 必须一致。

## 7. 查看当前 Saga 状态

只读排障可以使用：

```sql
SELECT
    saga_id,
    saga_revision,
    status,
    definition_hash,
    updated_at
FROM execution_saga.saga_v2
ORDER BY updated_at DESC;
```

查看指定 Saga：

```sql
SELECT
    saga_id,
    saga_revision,
    status,
    definition_hash,
    snapshot,
    updated_at
FROM execution_saga.saga_v2
WHERE saga_id = 'SGV2-...';
```

排障时重点确认：

1. `saga_revision` 是否符合预期的单调增长；
2. `status` 是否与 snapshot 中状态一致；
3. `definition_hash` 是否与 snapshot 中 immutable definition 一致；
4. crash/restart 后相同 `saga_id` 是否仍能读取到同一 durable evidence。

**禁止直接 UPDATE `saga_revision`、`status` 或 `snapshot` 来“修复”业务状态。** 状态恢复必须通过 owner contract、reconciliation 或明确批准的数据修复流程完成。

## 8. Crash / restart 恢复

进程重启后，创建新的 PostgreSQL store 连接并按 `saga_id` 重新读取：

```python
store = create_execution_saga_store_v2(
    backend="postgres",
    postgres_dsn=postgres_dsn,
)
try:
    stored = store.get_saga(saga_id)
finally:
    store.close()
```

恢复逻辑必须以 durable Saga state 为准，不得依赖：

- Python 进程内对象；
- 未持久化 callback；
- 隐藏 session；
- 进程本地 revision counter；
- workflow checkpoint 对 Host side effect 的推测。

如果 Host 调用结果未知，按 ADR-009 的 read-back / ActualDelta / reconciliation 路径确认真实 Host 状态；不能因为 workflow checkpoint 落后就假设 Host 未提交。

## 9. Backup / restore

Execution Saga durable store 属于需要备份的权威执行证据。备份责任属于运行 PostgreSQL 的平台/基础设施运维边界，至少必须覆盖：

```text
execution_saga.schema_migrations
execution_saga.saga_v2
```

恢复必须保证表内 row 与 JSONB snapshot 在同一数据库一致性点上恢复；不要从不同时间点分别拼接 `saga_revision` 与 snapshot。

ADR-008 当前没有冻结统一的 RPO/RTO 数值，因此每个部署环境必须单独定义并审批自己的 backup frequency、retention、restore drill 与 RPO/RTO；本 runbook 不擅自给出平台级数字。

恢复演练至少要证明：

- migration ledger 完整；
- 已存在 Saga 可按稳定 `saga_id` 读取；
- revision 未倒退；
- 继续 transition 时 strict CAS 仍生效；
- 不需要读取其他 owner 的私有表才能恢复 Saga。

## 10. PostgreSQL test lane

本地或 CI 运行 PostgreSQL persistence suite：

```bash
DSP_TEST_POSTGRES_DSN="postgresql://postgres:postgres@localhost:5432/dsp_test" \
  uv run python -m pytest \
    tests/execution_reconciliation/test_postgres_schema_v2.py \
    tests/execution_reconciliation/test_postgres_saga_store_v2.py -q
```

这些测试覆盖：

- owner-scoped migration 与 migration 幂等性；
- InMemory / PostgreSQL 共享的 Saga V2 conformance contract；
- process/store restart durability；
- 两个独立 PostgreSQL connection 的 revision CAS；
- public factory 的显式 PostgreSQL backend 选择。

普通 Phase I/offline 回归在没有 `DSP_TEST_POSTGRES_DSN` 时会 skip PostgreSQL integration cases，并且测试模块不会在 collection 阶段提前 import PostgreSQL infrastructure。这是刻意的依赖边界，不应改回 module-top `psycopg` 依赖。

## 11. 变更纪律

以下修改不能被当成普通存储重构直接落地：

- 改变 `ExecutionSagaStoreV2` 可观察状态机语义；
- 删除 strict revision CAS；
- 让 PostgreSQL adapter 自己实现第二套 transition 规则；
- 把 Host / D5 / Gateway / ChangeSet truth 复制成 Execution Saga owner 的权威状态；
- 引入跨 owner database transaction；
- 让测试 DSN 或任意环境变量自动决定生产 backend；
- 为了方便 import 而把 PostgreSQL adapter/driver 变成 provider-neutral package 的 eager dependency。

这些变化需要先回到相应 ADR / architecture review，而不是通过基础设施 adapter 悄悄改变系统 contract。
