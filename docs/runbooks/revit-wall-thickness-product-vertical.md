# Revit Wall Thickness Product Vertical — Live Acceptance Runbook

本 runbook 是 Task 10 的 **mandatory real-Revit product gate**。它验证的不是单个 HostCommand，而是同一条 `WallThicknessProductFlow -> authoritative workflow owners -> real Revit named pipe -> independent READ -> Step33 -> Saga/Product terminal` lineage。

GitHub-hosted CI 中该测试默认必须 **SKIP**。CI 的收集成功、Ruff GREEN 或 SKIP 都不能作为“Revit 已真实执行”的证据。Task 10 只有在固定 Windows/Revit acceptance machine 上得到 fresh live happy-path PASS 后，才能从 `LIVE-PENDING` 转为 live GREEN。

## 1. Acceptance 前置基线

每次运行都记录以下事实，不能复用另一台机器或旧运行的值：

| 字段 | 必须记录 |
|---|---|
| Git branch / exact HEAD | 当前 acceptance checkout 与 `git rev-parse HEAD` |
| Revit product / build | 实际安装版本与 build/file version |
| `DSP_REVIT_VERSION` | Revit major version |
| `DSP_REVIT_TFM` | 与该版本匹配的 target framework |
| `DSP_REVIT_API_DIR` | 当前安装的 `RevitAPI.dll` / `RevitAPIUI.dll` 所在目录 |
| Plugin DLL / `.addin` | 实际部署路径 |
| `DSP_REVIT_FIXTURE` | reviewed Phase H controlled `.rvt` 绝对路径 |
| fixture SHA-256 | sibling `.phase-h.json` 中的 `rvt_sha256` |
| isolated Wall UniqueId | manifest 中的 `isolated_wall_unique_id` |
| `DSP_REVIT_PIPE` | 当前 Revit process 的真实 named-pipe name |
| `DSP_TEST_POSTGRES_DSN` | Task 10 acceptance 专用 PostgreSQL 17 测试数据库连接 |

不要把数据库 DSN、凭据或机器本地路径提交到仓库。

## 2. 继续使用 reviewed Phase H fixture

Task 10 不创建一个放宽条件的新 RVT。继续使用 Phase H 已审查的 controlled fixture 和 sibling manifest：

```text
<fixture>.rvt
<fixture>.phase-h.json
```

manifest 必须至少包含：

```json
{
  "rvt_sha256": "<lowercase sha256>",
  "isolated_wall_unique_id": "<Element.UniqueId>",
  "shared_type_wall_unique_id": "<Element.UniqueId>",
  "insert_wall_unique_id": "<Element.UniqueId>",
  "join_wall_unique_id": "<Element.UniqueId>"
}
```

live test 会复用 Phase H manifest validator，因此以下任一条件都会拒绝运行：RVT 缺失、manifest 缺失、文件 hash 不一致、所需 UniqueId 为空或四个 scenario id 不唯一。

Task 10 mandatory happy path 只使用 `isolated_wall_unique_id`。该墙仍必须满足 Phase H strict conditions：一个 approved Basic Wall、其 existing WallType 仅被该墙使用、没有支持范围内的 hosted insert/opening、没有实际 wall join、当前厚度不是 300 mm，且 compound structure 为支持的单 editable-layer shape。

## 3. Reset canonical fixture

每次 fresh acceptance 前：

1. 关闭或放弃上一次运行后已被修改的文档；
2. 从 reviewed canonical bytes 恢复 `DSP_REVIT_FIXTURE`；
3. 重新验证 `.rvt` SHA-256 与 `.phase-h.json` 完全一致；
4. 在 Revit 中打开 **exact** `DSP_REVIT_FIXTURE`；
5. 在 UI 中只选择 manifest 的 `isolated_wall_unique_id` 对应墙；
6. 不要在运行开始前执行其它会改变文档 revision 的编辑；
7. acceptance 完成后不要把 300 mm mutation 保存覆盖 canonical fixture。

测试启动时会通过真实 `context.current_selection` 做只读 discovery，并要求：active document 就是该 fixture、选择集恰好一个元素、`UniqueId` 精确等于 `isolated_wall_unique_id`、native kind 为 `Wall`。这些 identity 只用于 environment-owned runtime/identity registry seed，不会进入用户 ProductTask request body。

## 4. Build and deploy exact Revit plugin

使用当前 exact HEAD 对当前安装 Revit 编译：

```powershell
dotnet build hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj `
  -p:DspRevitVersion="$env:DSP_REVIT_VERSION" `
  -p:DspRevitTargetFramework="$env:DSP_REVIT_TFM" `
  -p:DspRevitApiDir="$env:DSP_REVIT_API_DIR"
```

要求 0 build errors。将该 build 的 `Revit.AgentHost.dll` 通过当前版本对应的本地 `.addin` 部署到 Revit，并重新启动 Revit。

找到当前进程的 pipe：

```powershell
Get-ChildItem \\.\pipe\ |
  Where-Object { $_.Name -like "EnterpriseDesignAgent.Revit.*" } |
  Select-Object -ExpandProperty Name
```

`DSP_REVIT_PIPE` 只填写 pipe name，不包含 `\\.\pipe\` 前缀。

## 5. Prepare PostgreSQL acceptance owners

Task 10 复用 Task 9 的真实 durable owner composition，因此需要 PostgreSQL。为 live acceptance 使用隔离的 PostgreSQL 17 测试数据库，并设置：

```powershell
$env:DSP_TEST_POSTGRES_DSN = "<acceptance PostgreSQL DSN>"
```

测试会在开始该 case 时重建以下 test-owner schemas：

```text
product_task
orchestrator_checkpoint
orchestrator_artifact
execution_saga
```

不要把 live acceptance DSN 指向共享生产数据库。

## 6. Set live environment

在同一个 PowerShell session 设置：

```powershell
$env:DSP_REVIT_VERSION = "<exact Revit major version>"
$env:DSP_REVIT_TFM = "<official TFM for that release>"
$env:DSP_REVIT_API_DIR = "<directory containing RevitAPI.dll>"
$env:DSP_REVIT_FIXTURE = "<absolute path to reviewed Phase H .rvt>"
$env:DSP_REVIT_PIPE = "<EnterpriseDesignAgent.Revit....>"
$env:DSP_TEST_POSTGRES_DSN = "<acceptance PostgreSQL DSN>"
$env:DSP_REVIT_LIVE = "1"
```

缺少 `DSP_REVIT_LIVE=1` 或任一 required env 时，测试必须 SKIP，而不是退化成 fake Host success。

## 7. Run mandatory product live gate

从 repository root 执行：

```powershell
python -m pytest tests/integration/test_revit_wall_thickness_product_live.py -q -vv -s
```

mandatory happy path 必须真实经过：

```text
immutable ProductTask request (300 mm intent only)
  -> WallThicknessProductFlow
  -> LangGraphWorkflowRuntime
  -> DefaultWorkflowServices
  -> CanonicalWorkflowOwnerPorts
  -> Resolver / Binder / Impact / Scope / ChangeSet
  -> Approval / Planning / Provider Binding / Grant
  -> MaterializedExecutionSagaCoordinator
  -> real named pipe EXECUTE/set_wall_thickness
  -> Host commit at revision R
  -> separate named pipe READ/read_wall_thickness_snapshot
  -> exact host/document/Wall.UniqueId/revision R correlation
  -> semantic evidence build
  -> Step33 verification
  -> convergence
  -> Saga SUCCEEDED
  -> Product SUCCEEDED
```

产品请求本身只能携带 task/project/host/session/action 与 `{thickness: {value: 300, unit: mm}}`。选择墙、document identity、host runtime identity、当前厚度和 revision 都必须来自真实环境/owner evidence。

## 8. Mandatory assertions

本次 live run 只有同时满足以下事实才算 happy-path PASS：

- ProductTask request 被 durable store 读回，`request_hash` 与提交的 immutable request 精确一致；
- real context 只选择 manifest 的 isolated Wall；
- workflow 在 operation proposal pause 后通过原 `pause_id` resume；
- 只出现一次 `EXECUTE/set_wall_thickness`；
- EXECUTE target 是同一个 `Wall.UniqueId`，thickness 为 `300 mm`；
- EXECUTE precondition revision 等于 binding/planning 使用的 baseline revision；
- Host commit revision 恰好发生一次 increment；
- EXECUTE 之后恰好出现一条 mandatory `READ/read_wall_thickness_snapshot`；
- READ 的 document、host instance、Wall.UniqueId 与本次 execution 完全一致；
- `ActualDelta` committed revision 与 READ `revision_before == revision_after == top-level revision_after` 精确一致；
- independent READ 测得 `300.0 ± 1e-6 mm`；
- Saga slice 拥有 `actual_delta_hash`、`scope_comparison_hash`、`verification_hash`；
- Saga terminal 为 `SUCCEEDED`，convergence result 已持久化；
- Product projection 最终为 `SUCCEEDED`，且重新读取仍引用同一 Saga。

注意：mutation response 的 `width_after_mm` 不能替代 independent READ。Task 10 的 semantic success 必须由 READ evidence 进入 Step33。

## 9. Evidence emitted by the test

使用 `-s` 运行时，happy path 会输出一条 JSON audit record。保存原始 pytest 输出，并至少归档：

- `task_id` / request hash；
- context snapshot ref/hash；
- operation-space ref/hash 与最终 bound operation ref；
- ChangeSet / approval / execution-plan refs；
- Saga id；
- exact Revit host instance / document / Wall.UniqueId；
- fixture SHA-256；
- mutation `revision_before` / `revision_after`；
- independent READ command id 与 read revision window；
- measured width；
- verification hash / convergence result hash；
- final product/Saga status；
- Revit version、TFM、API dir、pipe；
- exact Git HEAD。

建议把这一整段 stdout 与本次 build log 一起作为 Task 10 external evidence 保存，不要只记录“pytest passed”。

## 10. Conditional live negatives

Design §18 要求以下 live negatives 仅在现有 harness 有 **reviewed deterministic seam** 时强制：

- scope extra entity/aspect；
- independent READ revision newer than commit。

当前 pinned Revit harness 没有经过审查的 deterministic external-change injection seam，因此 Task 10 测试明确记录：

```text
NOT_RUN_ENVIRONMENT_LIMITATION
```

这不是把负例标成 PASS，也不能削弱 Task 9 offline mandatory negative matrix。禁止通过修改 production Host 逻辑、伪造 mutation response 或在测试里直接制造假的 Step33 bundle 来补一个“live negative GREEN”。未来如果引入可审查、可确定性的 external-change injection seam，应新增真实 live negative，并保持 product/workflow composition 不变。

## 11. Ruff / repository verification

Task 10 新 live file 需要绝对 clean；由于 `tests/integration` 是历史目录，还要遵守 repository 的 no-new-diagnostics delta gate。最终以 exact Task 10 HEAD 的 repository-regression 结果为准。

默认 GitHub Actions 看到 live test SKIP 是正确行为，但它只证明：模块可导入/收集、非 live 环境不会误触 Revit，以及静态/仓库回归没有新增问题。它 **不** 证明本节的 real-Revit acceptance。

## 12. Closure record template

每次 live run 结束后至少记录：

```text
Task 10 exact HEAD: <sha>
Revit product/build: <value>
DSP_REVIT_VERSION: <value>
DSP_REVIT_TFM: <value>
DSP_REVIT_API_DIR: <value>
DSP_REVIT_PIPE: <value>
DSP_REVIT_FIXTURE: <value>
fixture SHA-256: <value>
isolated Wall.UniqueId: <value>
request task_id/hash: <value>
mutation revision: <before> -> <after>
independent READ revision: <before> -> <after>
independent READ measured width: <value> mm
Step33 verification hash/status: <value> / PASSED
Saga status: SUCCEEDED
Product status: SUCCEEDED
conditional live negatives: NOT_RUN_ENVIRONMENT_LIMITATION | <actual evidence>
pytest result: <exact summary>
```

只有 mandatory happy path 的 fresh real-Revit PASS 才能解除 `LIVE-PENDING`。如果测试在 CI 或非 Windows 环境 SKIP，Task 10 仍然保持 live evidence pending。
