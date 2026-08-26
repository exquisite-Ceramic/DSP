# ADR-001: Host Contract Boundary

- 状态：Accepted
- 日期：2025-01
- 关联：spec §4；`contracts/` 目录

## 背景（Context）

Agent 与 AutoCAD 宿主之间需要交换命令、结果、变更与状态。若任一侧直接依赖对方的内部类型（如插件暴露 Autodesk 类型、Sidecar 依赖插件私有 DTO），任何一侧演进都会破坏另一端，且无法进行独立测试与多宿主复用。

## 决策（Decision）

1. **`contracts/` 是宿主契约的单一事实来源**：JSON Schema（`schemas/*.json`）+ Python（`python/host_contracts`）+ .NET（`dotnet/HostContracts`）三份镜像，任一修改必须三处同步。
2. **边界规则**：
   - Plugin 内部除 `Native/` 外，禁止引用任何 `Autodesk.*` 程序集；所有 AutoCAD API 访问收敛到 `Native/` 的薄封装。
   - Plugin 与 Sidecar 之间只允许交换契约类型（Envelope 内承载 Command/Result/Delta/Error/Status）。
   - Sidecar 不得感知 AutoCAD 内部对象模型，只能通过契约抽象（EntityRef、handle）操作。
3. **契约演进**：通过 `schemaVersion` 字段做向后兼容；破坏性变更必须升版本并更新 `tests/conformance/host_contract_v1`。

## 后果（Consequences）

- 正面：宿主可替换（未来支持 Revit/Inventor 时仅新增 host 目录）；契约可独立单测；Sidecar 与 Plugin 可独立发布。
- 代价：三层同步带来维护成本；跨进程序列化开销（JSON）；EntityRef 抽象会丢失部分 AutoCAD 特有能力（需要时经 capability 机制显式暴露）。

## 备选方案

- 直接共享 .NET 程序集：放弃（无法被 Python Sidecar 复用）。
- 单一 gRPC/Protobuf：暂缓（引入代码生成与基础设施依赖，v0.5 优先最小依赖）。
