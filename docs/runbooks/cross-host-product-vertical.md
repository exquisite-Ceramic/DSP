# Cross-Host Product Vertical — Controlled Live Acceptance Runbook

本 runbook 对应 Task 16。当前目标是验证一个 ProductTask V2 在 AutoCAD 与 Revit 两个 REQUIRED Host 上受控执行的四种结果。离线 CI 只能证明 collection、real-owner PostgreSQL matrix、V1 compatibility 与静态检查；**离线 GREEN、live skip 或模拟 Host 响应均不算真实 live PASS。**

## 1. 唯一允许的产品路径

真实模型 invocation → MCP ProductTask V2 submit → server-owned PostgreSQL request / SessionBindingV2 → LangGraph durable Operation Proposal pause → 明确 human ACCEPT → 双 Host Gate A fresh READ → Gate B observation/planning continuity → V2 policy/ApprovalScope → Step30/31/32 → 一份 Saga / 两个 REQUIRED Slice → 各 Host 独立 READ → Convergence → 同一 task 的 MCP GET。

禁止预置假的 pending checkpoint；不得复用 Phase I test-only materialization execution helper；不得使用 execution response 代替 independent READ；GET 不做 readiness、重新 admission 或 Host mutation；未知 dispatch outcome 不得重新调用普通 execute。

## 2. 受控 baseline、主机身份和安全复位

两份原始 fixture 必须均为 **200 mm**，正常目标为 **300 mm**。独立竞争编辑只允许在第四场景把 Revit 从 200 mm 改成 **201 mm**。

运行前记录：AutoCAD 版本/插件 build identity/AgentHost endpoint/DWG absolute path/native handle/Host instance；Revit 版本/真实加载 DLL build identity/named pipe/RVT absolute path/Element.UniqueId/Host instance；语义环境、project、topology revision/hash、两项 REQUIRED Host roles。

每次运行前必须关闭两个文档并选择 **DO NOT SAVE**，随后重新打开审核过的原始 fixture。每次运行后再次关闭并选择 DO NOT SAVE。两个场景不可在未恢复的文档上连续执行。

先计算两份 fixture 的 SHA-256，必须与审核过的 expected digest 一致：

~~~powershell
Get-FileHash -Algorithm SHA256 $env:DSP_AUTOCAD_FIXTURE_PATH
Get-FileHash -Algorithm SHA256 $env:DSP_REVIT_LIVE_FIXTURE_PATH
git rev-parse HEAD
~~~

记录当前 **implementation HEAD**。不允许通过修改 expected digest 为已经漂移的 fixture 背书。Revit 原生 build 与加载 DLL 要匹配当前 host/version/target framework。

## 3. 显式 live 配置与隔离

受控 Windows self-hosted runner 标签必须为 self-hosted、Windows、dsp-cross-host-product。必要环境：

~~~text
DSP_CROSS_HOST_PRODUCT_LIVE=1
DSP_CROSS_HOST_PRODUCT_SCENARIO=deny|unavailable|positive|partial_commit
DSP_TEST_POSTGRES_DSN
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
~~~

实际模型调用、MCP server、explicit human decision 的受控配置由现场测试支持模块 tests/integration/cross_host_product_live_support.py 提供。支持模块必须复用 production MCP/ProductTask/AutoCAD/Revit adapters，不能返回静态 fabricated success；尚未接通时 live 测试必须 FAIL，不能把 skip 算成 PASS。机密凭据只配置在受控环境，禁止写入 evidence manifest。

## 4. Case 1：真实 policy deny

从 fresh 200 mm baseline 经真实模型、MCP 与 human ACCEPT，然后配置的 V2 policy 明确 DENIED。验证：

- proposal pause 与 subject、request/binding/topology hash、human ACCEPT 有真实 durable lineage；
- 无任何有效 execution grant，AutoCAD ProductTask mutation=0，Revit ProductTask mutation=0；
- 两端 independent READ 的最终值保持 200 mm；
- policy deny 不可伪装成人工 REJECT、stale、或成功执行。

## 5. Case 2：一个 REQUIRED Host unavailable

在 proposal preparation 之后、governed execution 之前，让其中一个 REQUIRED Host 无法完成 readiness。验证：

- REQUIRED hosts 精确为 AutoCAD + Revit，不能将不可用成员降级为 OPTIONAL；
- all-required readiness 失败，另一端 ProductTask mutation=0；
- 没有伪造的独立 verification/convergence success；
- durable GET 不因 Host offline 而重新 admission 或发起 mutation。

## 6. Case 3：正向双 Host 300 mm

完成 all-required readiness 后执行同一 ProductTask：

- task_count=1，saga_count=1，required_slice_count=2；
- AutoCAD、Revit 各有且只有一次被授权的 ProductTask mutation；
- 每个 Host 在自己的 revision lineage 上推进一次，不要求两端 revision 数值相等；
- 每端在 committed revision 上各自执行 production **独立 READ**，观察 300 mm；
- ActualDelta、VerificationEvidenceBundle 和 semantic verification 的 body-first 持久化先于 Saga reference；
- convergence 为 **CONVERGED**，Saga 和 MCP GET 均为 **SUCCEEDED**。

不能把 command receipt、preview、或缓存 projection 冒充 independent READ。

## 7. Case 4：受控 partial commit 的不可变时序

必须严格按此顺序记录事件：

1. 双 Host all-required readiness 已经全部 READY。
2. AutoCAD ProductTask Slice 已真实提交并独立验证 **300 mm**。
3. 由独立合法 Host command 在 Revit ProductTask command 执行前，把 Revit 墙从 **200 mm** 改到 **201 mm**，记录该独立命令及新 revision。
4. Revit ProductTask 仍携带旧 expected revision；真实 Host 必须拒绝为 **REVISION_CONFLICT / BEFORE_COMMIT**。

预期 **PARTIALLY_COMMITTED**：AutoCAD 已知 commit 保留；没有 Revit ProductTask ActualDelta；Revit ProductTask mutation=0；convergence 不得成功；绝不自动 compensation。这个独立 201 mm 编辑不能发生在 Gate A、Gate B 或 readiness 之前，否则不是本验收场景。

## 8. 专用 GitHub Workflow、命令和离线门

工作流是 .github/workflows/cross-host-product-vertical.yml。GitHub-hosted job 只执行 PostgreSQL 17 matrix、AutoCAD/Revit unit/Core 回归、live collect 和 Ruff；实际 live job 仅在显式 workflow_dispatch + 受控 Windows runner 执行，且每次选择一个场景。

离线：

~~~bash
DSP_CROSS_HOST_PRODUCT_LIVE=0 uv run python -m pytest tests/integration/test_cross_host_product_vertical_live.py --collect-only -q
DSP_CROSS_HOST_PRODUCT_LIVE=0 uv run python -m pytest tests/integration/test_cross_host_product_vertical_live.py -q -vv
~~~

现场 positive 示例：

~~~powershell
$env:DSP_CROSS_HOST_PRODUCT_LIVE="1"
$env:DSP_CROSS_HOST_PRODUCT_SCENARIO="positive"
uv run python -m pytest tests/integration/test_cross_host_product_vertical_live.py -k "live_case_positive" -q -vv -s
~~~

deny、unavailable、partial_commit 也必须分别执行并保留独立 fresh 输出。未配置真实 model/MCP/Human 适配层时禁止声称 live accepted。

## 9. evidence manifest 与最终验收归档

四个 case 每次必须输出一份 JSON **evidence manifest** 与完整 pytest 日志，至少包括：

- scenario、implementation HEAD、DWG/RVT SHA-256、实际 AutoCAD/Revit 及 DLL/plugin build identities；
- 真实模型调用和 MCP request ID、task_id、request hash、SessionBindingV2 hash、topology hash；
- proposal subject hash、pause_id、human decision/ref、Gate A/B 的两端 observation revision；
- ChangeSet、ApprovalScope、policy/admission、required-set、两个 Slice/BindingSet/Grant manifest refs；
- saga_id、dispatch IDs、每端 baseline/expected/committed/observed revision、独立 READ 的内容及 hashes；
- VerificationEvidenceBundle/result hashes、convergence 与最终同 task MCP GET；
- partial case 的独立 201 mm command ID、四事件顺序、**BEFORE_COMMIT** 失败、无补偿证据。

所有报告不得包含 token、数据库密码或未脱敏的凭据。记录 exact implementation HEAD，随后把所有场景的证据和对应 CI run IDs 交给独立 review。

**本 runbook 的提交只说明仓库侧 live acceptance contract 已登记。只有同一实现 SHA 上真实四个场景全部 PASS，Task 16 才能标记 CLOSED；否则必须保持 LIVE-PENDING，不能提前进入 Task 17 merge/lifecycle。**
