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

## 3A. Task 16A read-only production preflight（不是 controlled-live PASS）

受控 Windows runner 必须额外配置（均为现场显式值，不得使用示例/测试代用品）：

~~~text
DSP_AGENT_INTERPRETER_COMMAND_JSON   # 恰为当前 Python、-m、tests.integration.cross_host_product_model_interpreter 的 JSON argv
DSP_AGENT_MODEL_NAME                # 真实模型的经审查标识
DSP_CROSS_HOST_PRODUCT_MCP_URL     # 当前 dedicated case 管理的 loopback MCP；端口必须空闲
DSP_AUTOCAD_BUILD_IDENTITY         # 已审核 AutoCAD.AgentHost.dll 文件 SHA-256
DSP_REVIT_BUILD_IDENTITY           # 已审核 Revit.AgentHost.dll 文件 SHA-256
~~~

如需单独诊断，先为 read-only preflight 启动 production MCP，执行下列命令后停止该诊断 server；正式 driver 自行管理 dedicated MCP，拒绝占用端口：

~~~powershell
$env:DSP_CROSS_HOST_PRODUCT_LIVE="1"
uv run python -m tests.integration.cross_host_product_live_support --preflight
~~~

此 preflight 仅执行：两个 fixture 的 SHA-256 再检查、PostgreSQL `SELECT 1`、真实 MCP 三个固定工具的 negotiation/list_tools、AutoCAD exact LWPOLYLINE 200 mm normalized-fact READ、Revit exact selected Wall 200 mm snapshot READ。它不会执行模型解释、ProductTask submit、human ACCEPT、Gateway grant、EXECUTE、外部 201 mm 编辑或任何伪造的 scenario evidence。

preflight 若缺任何配置、读取不一致或 Host 不可达，必须失败。它只产生 `READ_ONLY_READY` 的诊断结果，不生成四场景 PASS manifest，不能当作 Controlled Live Acceptance。`run_controlled_case` 已为四场景接通生产端口；unavailable 与 partial_commit 的受控时序由下文 §3C 的真实 Host send 暂停和外部 controller 完成。仓库侧离线 GREEN 不能当作真实现场 PASS。

## 3B. 阶段一 driver：真实 proposal、显式人工 resume 和 owner 证据

`tests/integration/cross_host_product_live_driver.py` 在 dedicated case 内组合已有 helper。
`tests/integration/cross_host_product_v2_proposal_authority.py` 把 production
`SubmissionController.prepare_cross_host_submission()`、真实 `ProductFrontDoorMcpClient.submit/get`
与原有 PostgreSQL checkpoint / workflow artifact owner 组合起来，读取并核对 exact pause。
它不从 V2 MCP GET 推断不存在于公开 QueryViewV2 的 pause，也不会调用 resume。

`tests/integration/cross_host_product_v2_manual_resume.py` 接受单独取得的
`ExplicitHumanDecisionV2`；人工决定必须精确绑定 task ID、request hash、
SessionBinding hash、pause ID、subject content hash，并只能是
`OPERATION_PROPOSAL_ACCEPTED` 或 `OPERATION_PROPOSAL_REJECTED`。
在转发生产 MCP resume 前必须重新获取同一 exact task 的 GET、checkpoint 与
subject artifact，重验两端 observation 的当前已审查身份和 200 mm 基线。
任何 stale、身份漂移或 subject/hash mismatch 都必须停止，不得查询 latest task、替换 pause、
隐式改成 ACCEPT 或做普通 EXECUTE 重送。

该人工 helper 是被动执行接口；driver 发布完整 `pending-proposal.json` 后等待 pytest 外部 controller 取得用户决定并提供 `human-decision.json`。没有 UI、预选项或环境 flag 会自动产生 ACCEPT。
**只有用户正式审核两份 fixture、现场完成全部 preflight、真实人工逐项确认 proposal
且记录批准操作者/时刻/决定引用后，才能让现场 driver 调用此接口。**
`ACCEPTED` 的调用可能导致生产 Host mutation，绝不能用此模块测试当前未批准的图纸。
resume 之后只能使用同一 task 的 durable GET 识别 owner outcome；
transport 异常或 post-resume mismatch 不得盲目再次执行。

本阶段 offline contract/CI GREEN 不构成真实模型 invocation、Host 调用、人工签署或四场景 PASS 证据。

正式执行前必须是 clean committed HEAD；driver 冻结 HEAD 并在模型、Host、owner、resume 和归档边界检查漂移。子进程 PYTHONPATH 从 committed pyproject 清单构建，实际生产模块的 __file__ 必须位于当前 worktree，文件 SHA 逐项归档，防止共享虚拟环境的旧 editable 源码混入。

每个场景使用新建、无 user table 的 dedicated PostgreSQL 数据库；`database_name` 必须与实际 current_database() 一致。driver 不 truncate/drop 任何 owner。随机 case 目录使用新的 SQLite、task、binding、Saga；历史 manifest 不能作为输入。

另外配置：

~~~text
DSP_CROSS_HOST_PRODUCT_DRIVER_CONFIG  # 无凭据、经审核 JSON 的绝对路径
DSP_AGENT_MODEL_ENVIRONMENT_JSON      # 仅 ANTHROPIC_AUTH_TOKEN、ANTHROPIC_BASE_URL 等显式模型环境；按 secret 保存
DSP_CROSS_HOST_PRODUCT_EVIDENCE_DIR   # 本次新 case 的公共 evidence 根目录
~~~

driver config 必须恰有这些字段：`implementation_head`（当前完整 SHA）、`database_name`、`project_id`、`candidate_key`、`semantic_target_id`、`topology_environment_id`、`topology_revision`、`slot_ids`、`configured_reference_ids`、`policies`、`utterance`、`human_timeout_seconds`（大于 0，最多 3600）、`stage_timeout_seconds`（必须为 180）。`slot_ids` 与 `configured_reference_ids` 均为恰含 AUTOCAD/REVIT 的身份映射。`policies` 恰含 positive/deny，各自提供 production V2 policy 的 `policy_id`、`principal`、`allowed_canonical_operations`、`admission_ttl_seconds`；positive 允许 `set_wall_thickness.v1`，deny 使用经审核的不同 operation。project/target/topology/hash/roles 从同一实际配置生成，禁止复制历史 hash。模型环境禁止 controller 的 DSP authority 配置；driver 只补当前 worktree PYTHONPATH、审核过的模型名/候选键和本次证据文件路径。模型命令必须恰为当前 Python 执行 `tests.integration.cross_host_product_model_interpreter`，且该源码属于 clean committed HEAD。现场 runner 通过 `uv sync --locked --all-packages` 安装 dev group 中锁定的 Anthropic SDK 1.11.0；CLI 使用真实 SDK 调用，只把窄 proposal 写到 stdout，并将 provider invocation ID、可能缺失而保持 null 的 request ID、完整解码响应与 usage 独占写入 `model-provider-invocation.json`。driver 再将原始文本、proposal、冻结请求、模型名、候选键与源码 SHA 逐项关联。DSN、模型凭据不序列化到公共 evidence，private bootstrap 配置须放在归档目录外。

人工交接按以下顺序执行：

1. controller 从 pytest 打印的本次 pending 文件读取实际 proposal 全体、冻结请求、两端 observations，以及 case/head/task/request/binding/pause/subject 精确 lineage。
2. controller 在 pytest 外取得真实用户 ACCEPT；记录 `operator`、`decision_ref` 和带时区 `recorded_at`，且时间不得早于 pending 发布。
3. controller 用标准原子文件发布 `human-decision.json` 到该 case 目录。它必须恰好绑定 pending 的 `case_id`、`implementation_head`、`task_id`、`request_hash`、`session_binding_hash`、`pause_id`、`subject_ref`、`subject_content_hash`，以及 `decision=ACCEPT`、`resume_kind=OPERATION_PROPOSAL_ACCEPTED`。不得在测试中生成这个决定。

超时、预置决定、旧 lineage 或签署前漂移均停止。driver 在发送 resume 前独占 fsync `resume-attempt.json`。传输结果不明确时只 GET 同一 task 并保存 `ambiguous-exact-task-get.json`（查询失败时保存 `ambiguous-exact-task-get-failed.json`），不重发、不补偿、不执行 recovery/undo。deny 的真实 owner 可能保持 WAITING/POLICY_APPROVAL；正式证据要求实际 policy DENIED code、零 grant/dispatch/mutation、两端独立 200 mm READ。

loaded provenance 由只读 Windows Process.Modules 直接检查，要求准确 DLL 名称、ProductVersion `1.0.0+<完整HEAD>` 和文件 SHA 等于审核 build identity。controller 和专用 MCP 子进程均在生产 AutoCAD/Revit transport 的每次真实 `CreateFile` 返回后、任何 `WriteFile` 之前，对同一 handle 调用 pywin32 `GetNamedPipeServerProcessId`。实际 server PID 必须与审核 pipe PID 一致；不一致即关闭新 handle 并失败。`pipe-server-ownership.jsonl` 保存每次连接的 OS PID、场景阶段、locator 与冻结 HostInstanceId；正式 collector 要求两进程双 Host 的实际观察与加载 DLL 的进程清单及 production READ 身份一致。缺失或不一致不发布 manifest。

owner 审计仅在该单 case MCP 子进程内包装 production 公开 put/issue 与 convergence verifier 方法，调用原方法一次并保留返回/异常，finally 恢复。ChangeSet/ApprovalScope/MaterializationPlan/ExecutionPlan/BindingSets/Grants/Approval/readiness 的实际不可变内存快照标记 `AUDITED_IN_MEMORY_OWNER`；PostgreSQL durable Workflow collection manifest、request/decision/Saga/dispatch/reconciliation/policy owner 另行保存，不能称内存快照为 PostgreSQL persistence。`convergence-captures.jsonl` 保存 verifier 实际 plan/profile/evidence set/result 全体，collector 从六项原始 Step33 local evidence body 调用现有公开 build/hash API 重建完整 evidence set，再与 Saga、MCP GET 的 result hash 精确关联；不会重跑 verifier 判定。现有 owner integrity/hash validator 与 reconciliation/workflow codec 校验 body、full hash、refs、cardinality；缺失 capture 不发布正式 manifest。先持久化完整 evidence body，再原子发布引用它的 manifest。

## 3C. 阶段二 controller 与原始 Revit 命令交接

`unavailable` 和 `partial_commit` 各自使用全新 dedicated DB、SQLite、task、binding、Saga lineage（unavailable 的 readiness 失败发生在 Saga 创建前）及证据目录。两者在 MCP 子进程的真实 Revit transport send 前暂停；原命令 ID、operation、expected revision、Host/document/native ID 与 case/request/binding 和前置 owner hash 逐项写入 `pending-stage.json`。controller 只对本次 pending 执行相应动作，不修改 ProductTask 命令或生成 Host 回执。

controller 看到 pytest 输出的 `LIVE_AWAITING_STAGE` 后，在本次目录中读取完整 `pending-stage.json`。由另一独立人员完成下述操作并以原子文件方式提供 `stage-controller-completion.json`：`stage_id`、`pending_hash`、`case_id`、`task_id`、`original_command_id` 必须逐字等于 pending，另含 `operator`、不早于 `published_at` 的时区时间 `completed_at`、独立 `authorization_ref`，以及指定 `action`。预置、重复、旧 case、错误 command/task 或缺少前置证据均关闭阶段门。

- `unavailable`：在 Revit 中关闭审核过的当前文档，明确 **DO NOT SAVE**，保留 AgentHost 与 pipe；填写 `action=REVIT_DOCUMENT_CLOSED_UNSAVED`。runner 随后才转发原始 `check_wall_thickness_readiness` READ，要求 native `REVIT_ACTIVE_DOCUMENT_UNAVAILABLE`、`revision_after=0`，无任何 Product EXECUTE。保持文档关闭直至本次 exact-task GET、AutoCAD 独立 200 mm READ 和正式证据采集完成；再重新打开原 fixture。不可把 0 grant 当成要求：collection/grant 已在 readiness 前进行，正式归档记录实际数量。
- `partial_commit`：只有 `pending-stage.json` 已证明双端 READY、AutoCAD Product 提交及在其 committed revision 上独立验证 300 mm 后，controller 才凭**另行授权**的 native Revit UI 把同一墙 200→201 mm；填写 `action=REVIT_NATIVE_UI_EDIT_201MM` 和独立 `native_edit_command_id`。这不是 ProductTask ACCEPT 或模拟 Host response。runner 经生产 READ 再证明 201 mm 及高于原 Product 命令 expected revision 的新 revision，之后释放原 Product EXECUTE。原命令须返回 native `REVISION_CONFLICT / BEFORE_COMMIT`，保留 AutoCAD commit，不重试、不补偿。

MCP SDK Streamable HTTP 默认 read timeout 为 300 秒。阶段门最长 180 秒，并按本次 `resume-attempt.json` 开始时间进一步缩短，使暂停始终至少早于 MCP 读取超时 30 秒；实际预算写在 `pending-stage.json` 的 `deadline_seconds`。controller 应在该预算结束前至少 5 秒完成，以便独立 READ 和释放。超时或释放不明时，被阻挡的原命令不发送；保留 `pending-stage.json`、`resume-attempt.json` 与已写 owner 事实，只允许同一 task 的 GET 来判断状态。不得自动再次 resume、Product EXECUTE、recovery 或 UI undo。`stage-send-attempt.json` 在真实 dispatch 前 fsync；`stage-release-consumed.json` 阻止第二次释放。

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

deny、unavailable、positive、partial_commit 均需各自新建 dedicated case 并在同一 clean implementation HEAD 上分别通过真实验收。当前没有运行任何真实现场验收，四场景均保持 LIVE-PENDING。

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

真实 runner 将每个场景的 JSON evidence manifest 写入
`DSP_CROSS_HOST_PRODUCT_EVIDENCE_DIR=artifacts/cross-host-product-live`；
`evidence_manifest_path` 必须指向此目录内真实存在的 JSON 文件。
测试会校验 manifest 与当前执行的 implementation HEAD、scenario、request/binding/topology、
proposal/pause、task/Saga 和 Host observations 的 exact lineage 一致。
路径越界、文件缺失、JSON 损坏或 lineage 不一致全部 FAIL。
专用 workflow 在成功及失败时使用 `actions/upload-artifact@v4` 归档场景证据；
artifact 名称包含 scenario 和 implementation SHA，文件缺失时归档也 FAIL。
归档不代表真实受控 live 已通过，skip 不可计作 PASS。

**本 runbook 的提交只说明仓库侧 live acceptance contract 已登记。只有同一实现 SHA 上真实四个场景全部 PASS，Task 16 才能标记 CLOSED；否则必须保持 LIVE-PENDING，不能提前进入 Task 17 merge/lifecycle。**
