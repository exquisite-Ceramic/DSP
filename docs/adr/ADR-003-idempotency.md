# ADR-003: Idempotency

- 状态：Accepted
- 日期：2025-01
- 关联：spec §7；`hosts/autocad/plugin/Execution/IdempotencyStore.cs`、`hosts/autocad/sidecar/src/autocad_sidecar/execution/idempotency.py`

## 背景（Context）

Sidecar 到 Plugin 之间是可靠的本地管道，但 Agent → Sidecar 链路可能重试（网络、编排器超时）。写命令（如 `model.move`）若被重复执行，会产生双重移动。需要一种机制让重放无害且可观测。

## 决策（Decision）

1. **每条写命令必须携带 `idempotencyKey`**（UUID 或服务端生成的稳定键），由调用方（Agent/Sidecar）负责生成；读命令（context.*、view.fit 这类无副作用命令）可省略。
2. **插件侧去重**：`IdempotencyStore` 按 `(documentId, idempotencyKey)` 记录「已执行命令 + 其结果」。重放命中时：
   - 若原命令成功 → 直接返回缓存的 `HostCommandResult`（不再执行），并在结果中标记 `replayed: true`；
   - 若原命令失败 → 重新执行（允许失败重试）。
3. **Sidecar 侧去重**：`idempotency.py` 在发送前登记待发键，防止同键并发发送；收到成功结果后归档。
4. **缓存策略**：按 documentId 分桶，最近 N 条（默认 1024）LRU 淘汰；文档关闭即清空。
5. **与 Revision 的关系**：幂等只保证「同键同结果」，不保证并发安全；并发写仍由 `revision` + `RevisionGuard` 防护（见 spec §7）。

## 后果（Consequences）

- 正面：重放安全、结果可审计（replayed 标记）、失败可安全重试。
- 代价：插件需维护状态（内存缓存）；键管理责任上移给调用方；缓存淘汰可能引入极小概率的重复执行窗口（可接受，写命令本身可验证）。
- 边界：不替代业务级校验；`revision_conflict` 仍会正常返回。

## 备选方案

- 双阶段提交（prepare/commit）：放弃（对单机管道过重）。
- 仅依赖 Sidecar 重试去重：放弃（Plugin 侧仍可能因 Sidecar 崩溃后重放而重复执行）。
