# Phase I 真实 AutoCAD + Revit 墙厚双 Host 验收 Runbook

本 runbook 只用于受控的 Phase I 真实双 Host 验收。目标是证明同一个 canonical `set_wall_thickness.v1` ChangeSet 在 AutoCAD 与 Revit 两个 REQUIRED materialization 上完成真实 mutation、Step33 V2 本地 reconciliation 与 provider-neutral convergence。GitHub-hosted runner 只运行离线门；真实桌面 AutoCAD/Revit 必须在显式配置的 Windows self-hosted runner 上执行。

## 1. 不可变验收约束

- 受控基线：AutoCAD 与 Revit 对应墙体都必须是 **200 mm**。
- 正向目标：两个 Host 都真实提交到 **300 mm**。
- partial-commit race：AutoCAD 先成功提交 300 mm；Revit readiness 之后由测试夹具发出一条独立合法 mutation，把受控 Revit 墙体从 200 mm 改成 **201 mm**，随后 Saga 使用 readiness-time revision 发送原先冻结的 300 mm 命令。
- race 的 201 mm mutation 不是 Saga Slice，只是合法并发编辑证据。
- stale Revit Saga 命令必须返回 `REVISION_CONFLICT` 且 commit state 为 `BEFORE_COMMIT`。
- partial 场景必须得到 `PARTIALLY_COMMITTED`；Revit Slice 不得产生 ActualDelta；不得运行 convergence；不得自动执行 compensation。
- 两个场景之间必须完整恢复 fixture。**绝不能在未恢复的同一桌面文档上连续运行 positive 与 partial_commit。**
- 每次 mutation 后都关闭受控文档并选择 **DO NOT SAVE**，然后从审核过的 fixture 重新打开。
- 只有 fresh、完整的命令输出和 JSON evidence record 才能作为 PASS 证据；肉眼看到模型变更不能代替测试输出。

## 2. 受控 Host 与 fixture 身份

运行前记录以下信息：

- AutoCAD 版本、进程、AgentHost named-pipe endpoint。
- AutoCAD 受控图纸绝对路径、SHA-256、document ref、host instance id、目标 native handle。
- Revit 版本必须为 2027，目标框架必须为 `net10.0-windows`。
- Revit AgentHost named pipe、受控 RVT 绝对路径、SHA-256、document ref、host instance id、目标 `Element.UniqueId`。
- 共同 semantic id。

`DSP_AUTOCAD_ENDPOINT` 表示 AutoCAD AgentHost 的**精确 bare named-pipe 名称**，传给现有 `HostAdapter` / `PipeTransport`。不要填写模糊进程名，也不要依赖多 pipe 自动猜测。

## 3. 必需环境变量

在 Windows self-hosted runner 的受控环境中配置：

```text
DSP_PHASE_I_LIVE=1
DSP_AUTOCAD_ENDPOINT
DSP_AUTOCAD_DOCUMENT_REF
DSP_AUTOCAD_FIXTURE_PATH
DSP_AUTOCAD_FIXTURE_SHA256
DSP_AUTOCAD_NATIVE_ID
DSP_AUTOCAD_HOST_INSTANCE_ID
DSP_REVIT_LIVE_PIPE
DSP_REVIT_LIVE_DOCUMENT_REF
DSP_REVIT_LIVE_FIXTURE_PATH
DSP_REVIT_LIVE_FIXTURE_SHA256
DSP_REVIT_LIVE_WALL_UNIQUE_ID
DSP_REVIT_LIVE_HOST_INSTANCE_ID
DSP_REVIT_LIVE_VERSION
DSP_REVIT_LIVE_TFM
DSP_REVIT_LIVE_API_DIR
DSP_PHASE_I_SEMANTIC_ID
```

推荐把非敏感机器配置放在 GitHub Environment/Repository Variables；不要把本机绝对路径或运行时 identity 写进测试源码。fixture 内容不提交、不改写，验收只接收路径与预先审核的 SHA-256。

## 4. Fixture SHA-256 预检

每次运行前，在**关闭两个受控文档且确认上一轮没有保存**的状态下计算真实文件哈希：

```powershell
Get-FileHash -Algorithm SHA256 $env:DSP_AUTOCAD_FIXTURE_PATH
Get-FileHash -Algorithm SHA256 $env:DSP_REVIT_LIVE_FIXTURE_PATH
```

结果必须逐字节匹配：

- `DSP_AUTOCAD_FIXTURE_SHA256`
- `DSP_REVIT_LIVE_FIXTURE_SHA256`

Task16 helper 在任何 Host mutation 前会再次验证 SHA-256；不一致时 fail closed。不得通过修改 expected hash 来“修复”未审核 fixture。

## 5. Revit 2027 native build

先从 `C:\` 执行冻结的 native build：

```powershell
cd C:\
dotnet build E:\DAPS\enterprise-design-agent\hosts\revit\plugin\Revit.AgentHost\Revit.AgentHost.csproj `
  -p:DspRevitVersion="2027" `
  -p:DspRevitTargetFramework="net10.0-windows" `
  -p:DspRevitApiDir="C:\Program Files\Autodesk\Revit 2027"
```

构建失败时不得进入真实 mutation gate。

## 6. 离线门

GitHub-hosted 或本机无桌面 Host 环境只运行离线门：

```powershell
$env:DSP_PHASE_I_LIVE="0"
python -m pytest tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py -q -vv
```

预期：helper/config/workflow/runbook 契约测试通过；两个真实桌面 Host case 明确 skip。skip 不是 live PASS。

还必须运行完整 Phase I offline package 回归、Step34 AutoCAD regression、Phase H Revit reconciliation/live-skip，以及 Revit Core：

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

## 7. Positive：真实 200 mm -> 300 mm

开始前：

1. 关闭受控 AutoCAD/Revit 文档，选择 **DO NOT SAVE**。
2. 重新打开审核过的 fixture。
3. 重算并核对两个 SHA-256。
4. 确认两个目标墙体的 canonical baseline 都是 200 mm。
5. 确认 AutoCAD/Revit AgentHost endpoint 与环境变量一致。

手工运行：

```powershell
$env:DSP_PHASE_I_LIVE="1"
$env:DSP_PHASE_I_SCENARIO="positive"
python -m pytest tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py -k "real_positive_wall_thickness_acceptance" -q -vv -s
```

必须从 fresh 完整输出确认：

- REQUIRED hosts 精确为 `autocad -> revit`。
- 两个 readiness receipt 都是 READY。
- AutoCAD 真实 200 mm -> 300 mm，且本地 reconciliation SUCCEEDED。
- Revit 真实 200 mm -> 300 mm，且本地 reconciliation SUCCEEDED。
- 两个 canonical post-state 都是 `dsp:WallThickness = {value: 300, unit: mm}`。
- cross-host convergence = CONVERGED。
- Saga V2 = SUCCEEDED。
- materialized coordinator result = SUCCEEDED。
- 输出包含 ChangeSet/scope/topology/materialization-plan/required-set/Slice/binding/grant/readiness/ActualDelta/verification/convergence hashes。

完成后立即关闭两个受控文档并选择 **DO NOT SAVE**。不要保存 300 mm 结果到 fixture。

## 8. 恢复 fixture

positive 之后、partial_commit 之前必须执行：

1. 关闭受控 AutoCAD 文档，**DO NOT SAVE**。
2. 关闭受控 Revit 文档，**DO NOT SAVE**。
3. 从同一审核过的 fixture 路径重新打开两份文档。
4. 再次计算 SHA-256；必须与环境变量一致。
5. 再次确认两个 canonical baseline 都为 200 mm。
6. 重新确认 Host endpoint/document/native identity 未漂移。

任一条件不满足时停止，不运行 partial_commit。

## 9. Partial commit：真实 Revit post-readiness revision race

运行：

```powershell
$env:DSP_PHASE_I_LIVE="1"
$env:DSP_PHASE_I_SCENARIO="partial_commit"
python -m pytest tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py -k "real_revit_post_readiness_race_is_partial_commit" -q -vv -s
```

必须确认：

- 两个 readiness receipt 先全部 READY；readiness 阶段零 mutation。
- AutoCAD Slice 真实提交 200 mm -> 300 mm，并保持 SUCCEEDED。
- Revit test harness 在 readiness 后发送一条独立合法 200 mm -> 201 mm mutation，推进真实 DocumentChanged revision。
- 随后 Saga 的 Revit 300 mm 命令仍使用 readiness-time stale revision。
- Revit 返回 `REVISION_CONFLICT / BEFORE_COMMIT`。
- Revit Saga Slice 没有 ActualDelta。
- Saga/materialized result 为 `PARTIALLY_COMMITTED`。
- convergence 不运行。
- 不自动 compensation，不推导 inverse native command。

完成后再次关闭两个受控文档并选择 **DO NOT SAVE**，重新打开原 fixture 前必须重新核对 SHA-256。

## 10. GitHub workflow_dispatch

专用 workflow：

```text
.github/workflows/phase-i-real-cross-host-materialization-saga.yml
```

`phase-i-offline` 使用 GitHub-hosted Ubuntu，只做离线 V2/legacy/Core gate，`DSP_PHASE_I_LIVE=0`。

`phase-i-real-dual-host` 只允许显式 Windows self-hosted runner 标签：

```text
self-hosted
Windows
dsp-phase-i-dual-host
```

workflow_dispatch 每次只选择一个 scenario：`positive` 或 `partial_commit`。这是为了强制操作者在两个真实 mutation 场景之间执行 **DO NOT SAVE** close/reopen restoration，而不是在一次 job 中背靠背运行两个 live gate。

## 11. 最终证据与实现树

每个真实场景保存 fresh 完整 pytest 输出与打印的单条 JSON evidence record。最终实现 HEAD 上再执行：

```powershell
$base = git merge-base main HEAD
git diff --check $base HEAD
git status --short
git rev-parse HEAD
```

然后重新运行完整 Phase I offline gate 和 Revit Core tests。若真实证据之后任何 AutoCAD/Revit production 源码发生变化，必须重跑受影响的 native/live gate；不得复用旧输出宣称当前 HEAD 已通过。
