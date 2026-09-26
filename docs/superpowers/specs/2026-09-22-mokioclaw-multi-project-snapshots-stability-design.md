# MokioClaw 多项目快照扩展与评测稳定性强化设计

> 日期：2026-09-22（Asia/Shanghai）<br>
> 状态：最终小修稿，等待用户确认是否进入 implementation plan<br>
> 基线：`main` / `2c68a12fc49940101ea56e8ac967d6558e74109e`<br>
> 前置阶段：Rich v14.3.4 两个 Case、三架构、四资源格、三轮共 72 次真实 Agent 运行<br>
> 下一步边界：本规格获书面批准后才编写实施计划；实施计划获批且执行方式确认后才允许改代码、创建 Click Case 或运行真实 Agent

## 1. 目的与阶段定位

本阶段名称为：**多项目快照扩展与评测稳定性强化阶段**。

目标不是立即复制 Rich 的 72-run 实验，而是先修复 Rich 阶段暴露出的测量稳定性和审计问题，再用 Click 建立完全独立的第二个开源仓库快照实验。最终回答的问题是：Rich 两个 Case 上观察到的资源方向，能否在第二个仓库上得到方向性支持，还是表现为仓库特异或仍不确定。

本阶段继续是探索性证据，不是统计显著性检验，也不宣称架构普适优劣。

### 1.1 成功标准

1. provider 失败能够被结构化分类、脱敏记录并与 Agent 任务失败分离；
2. 正常完成和中断运行均有明确的 token telemetry 覆盖语义；
3. scheduled run、实际 worker process launch 和结果 manifest 各自可审计，运行失败不能被覆盖或择优替换；
4. 人读和机器分析产物满足跨路径、跨时区和跨主机的确定性要求；
5. Click 快照、镜像、Case、schedule、fingerprint、批次根和分析产物与 Rich 完全隔离；
6. 根据零 Agent-run Case 准入结果，在真实 R1 前冻结 36 或 72 的运行预算；
7. Rich 与 Click 先独立分析，再做不混合原始计数的方向性比较；
8. 每一轮真实运行均受显式用户 gate 和预注册停止条件约束。

### 1.2 非目标

- 不修改或重算 Rich 的原始 72-run 批次、阈值和机械结论；
- 不把 provider 504 改写为 Agent 任务失败；
- 不删除、补跑或择优替换正式批次中的失败行；
- 不用 token 粗估冒充 provider 账单成本；
- 不投入 BM25、Embedding、Rerank 或 AST Index；
- 不改造 README 主叙事、MCP、FastAPI/SSE、CLI/TUI 产品化或求职演示；
- 不同时实施 Click 和 HTTPie；
- 不将 fixture red-green、reference patch 或 provider probe 写成 Agent 成绩；
- 不使用 subagent，除非用户在实施会话中另行授权；
- 不创建隔离工作树，除非用户在实施前明确确认；
- 不提交、推送或修改远端，除非用户明确授权。

## 2. 当前证据基线

### 2.1 Rich 最终账目

Rich v14.3.4 最终实验根为 `evals/reports/snapshots-20260920/`，四个资源格各有 18 个唯一 Case×架构×repeat key，合计 72 行：

| 状态 | 数量 |
|---|---:|
| passed | 17 |
| budget_exhausted | 14 |
| timed_out | 15 |
| failed | 4 |
| setup_failed | 22 |

三份稳定机器产物位于 `analysis/`：

- `thresholds.json`：`B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB`
- `per-case.json`：`167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB`
- `pooled.json`：`6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2`

Rich 的 Q1/Q2 结论保持冻结：

- Multi-Agent Q1：两个资源轴均独立产生影响，budget-priority pattern 为 true；
- Plan–Execute Q1：两个资源轴均独立产生影响，budget-priority pattern 为 true；
- Plan–Execute Q2：`no time-wall migration signal / inconclusive`。

### 2.2 稳定性审计的新发现

1. **Token 缺失与终态完全对应。** 21 个正常进入 grader 的运行（17 passed + 4 failed）全部有 token；51 个被中断运行（budget、timeout、setup failed）全部没有 token。当前问题是中断持久化缺口，不是随机 telemetry 缺失。
2. **504 缺少结构化类型，但最终 72 行的归因可机械恢复。** 四个最终 manifest 共 72 行，其中 22 行为 `setup_failed`；对应 22 个 `results.json` 全部存在、`failure_stage=worker`，且 `failure_reason` 全部包含 `504 Gateway Time-out`。工具调用数分布为 0 次×19、13 次×1、18 次×1、38 次×1。因此“最终 72 行中的 22 个 `setup_failed` 全部是 worker-stage provider 504”具有 22/22 的结果文件证据覆盖；该结论不外推到已被覆盖、详细目录不完整的历史 worker attempts。
3. **历史 worker process launch 与实验槽位未分离。** 两份 R1 manifest 备份与当前 manifest 对比显示三个槽位曾被新 run ID 替换；相同 `report_dir` 被复用，旧详细结果不再独立存在。Rich 最终 72 行账目不变，但下一阶段必须使用 append-only worker-attempt ledger。
4. **成本字段没有生产者。** `estimated_cost` 当前必然为 null；它不能作为下一阶段准入指标。
5. **人读报告含绝对 Root。** 同一数据在隔离工作树和主工作区生成不同的 `analysis/report.md` 哈希；机器 JSON 不受影响。
6. **原始实验材料是 ignored 审计证据。** `.superpowers/` 和 `evals/reports/` 在清理、移动、worktree 或批量 Git 操作中必须显式保护。
7. **Rich 三份机器分析不含新版资格字段。** 已核实 `thresholds.json`、`per-case.json` 和 `pooled.json` 没有 provider attrition、token coverage、历史 worker attempt 完整性或新版 fingerprint 字段，因此不能把 Rich 与 Click 描述为具有同等级严格审计资格。
8. **Provider SDK 重试尚未显式关闭。** 当前 `ChatOpenAI` 初始化没有设置 `max_retries=0`。下一阶段必须关闭 benchmark 路径中的 SDK 自动重试；若某个 provider/SDK 无法关闭，则必须把每一次底层传输请求显式记账，否则该配置不得进入正式 smoke 或正式批次。

### 2.3 Rich 旧证据的只读审计闭环

Rich 三份机器分析及其 SHA-256 永不修改，也不用新规则重算 Q1/Q2。新增只读 sidecar：

```text
evals/reports/snapshots-20260920/analysis/rich-legacy-audit.json
```

sidecar 只从现存 Rich schedule、manifest、result、trace、usage 和已冻结分析产物读取，至少记录：

- 三份冻结分析产物、各输入 manifest 和可用原始证据的 SHA-256；
- provider attrition 及其可机械确认的 phase/status；
- 最终 72 行中 provider 504 的证据覆盖：四个 final manifest 的 hash、22 个对应 `results.json` 的 hash、`22/22` 匹配率、worker-stage 数和工具调用分布；
- token telemetry coverage 与缺失原因；
- `audit_completeness`；
- `historical_worker_attempt_completeness`；
- 无法由旧 schema 恢复的字段及理由。

由于 Rich 历史上有三个槽位被新 run ID 替换，旧详细目录不再完整，`historical_worker_attempt_completeness` 和聚合 `audit_completeness` 都必须固定为 `limited`；不得根据最终 manifest 反推为 `complete`。sidecar 不属于原三份机器分析，不改变它们的 hash、状态或结论。

## 3. 总体架构与执行顺序

```text
稳定性代码与离线测试
  → Click 快照与镜像冻结
  → Click Case 零 Agent-run 验收
  → provider/telemetry smoke
  → G1：真实 R1 前用户 gate
  → R1
  → G2：R1 后用户 gate
  → R2
  → G3：R2 后用户 gate
  → R3
  → Click 独立机械分析
  → Rich–Click 方向性比较
```

设计和实施权限分为四层：

- **G0a：书面设计批准。** 只授权编写实施计划；
- **G0b：实施计划与执行方式批准。** 才允许代码、快照和 Case 实施；
- **G1：真实 R1 前批准。** 才允许启动第一轮真实 Agent；
- **G2/G3：R1/R2 后批准。** 分别只根据完整性、安全性和稳定性审计授权下一轮。

G2/G3 不得向决策者展示任何中间效果方向，包括 provisional Q1/Q2、逐架构成功方向、资源格标签、budget-priority pattern、逐 Case 结果或 ReAct 状态漂移。正式效果分析只允许在全部预注册轮次完成后生成；若预注册停止条件触发，则只生成一次封存后的最终 incomplete/inconclusive 结案分析，不把未完成批次提升为正式 Q1/Q2。该约束用于避免中途结果驱动的 optional stopping。

## 4. Provider 失败与 worker attempt 账目

### 4.1 结构化失败分类

保留 `RunStatus.SETUP_FAILED` 以兼容既有聚合，但新增互斥的结构化字段。`failure_kind` 的机械映射为：

- HTTP 401/403：`provider_auth`；
- HTTP 402：`provider_billing`；
- HTTP 429：`provider_rate_limit`；
- 其他 HTTP 4xx：`provider_request_rejected`；
- HTTP 5xx（包括 500/502/503/504），以及 TLS、DNS、connect、read、protocol transport error：`provider_transport`；
- 已确认发生在 provider 边界、但无法映射到上述类别：`provider_unknown`；
- 未进入 provider 边界的 worker 自身异常：`worker_internal`；
- 本地配置错误：`config`；
- sandbox/container 控制错误：`sandbox`。

`worker_internal` 不得作为未知 provider 异常的兜底。另记录：

- `provider_status`：HTTP 状态码或 null；
- `provider_phase`，按以下优先顺序机械产生，三个值互斥：
  1. 尚无成功模型响应：`before_first_model_response`；
  2. 已有成功模型响应且尚无任何工具活动：`after_model_response_before_first_tool`；
  3. 已发生至少一次工具活动：`after_tool_activity`；
- `retryable`：只描述错误性质，不授权重试；
- `sanitized_reason`：异常类别和脱敏摘要。

脱敏字段不得包含 API Key、Authorization header、完整 Base URL、query string、请求正文或响应正文。报告只允许出现 provider host，不允许完整 endpoint。

### 4.2 三层计数命名

本设计冻结三个不同概念，禁止再共用 `attempt`：

1. `scheduled_run_id`：预注册的 Case×架构×资源格×repeat 槽位；
2. `worker_attempt_id`：一次真实 worker 进程启动；
3. `agent_attempt_count`：Agent 架构内部的计划—执行或修复循环次数，仅用于行为分析。

正式批次分别维护：

1. `schedule`：所有预注册槽位；
2. `worker-attempt-ledger`：实际启动过的 worker process launch，append-only；
3. `result manifest`：每个已执行槽位对应的唯一 `worker_attempt_id`。

账目要求：

- 每个正式 `scheduled_run_id` 最多启动一个 `worker_attempt_id`；
- 每个 `worker_attempt_id` 使用独立目录，不得按 Case×架构×repeat 复用固定目录；
- worker 在首次模型响应前崩溃也必须写入最小 artifact；
- ledger 先登记 launch，再由独立终态记录闭合，既有记录不可原地删除或换成另一个进程；
- 停止后尚未启动的槽位显式记录为 `not_started`，不得伪造 worker failure；
- `agent_attempt_count` 不参与 worker 重试判定，也不生成新的 `worker_attempt_id`。

账目分离只用于保留崩溃证据，不允许失败后补跑。

### 4.3 SDK 自动重试与传输请求

正式 benchmark、stability smoke 和 provider probe 的模型配置必须显式设置 `max_retries=0`，并把 SDK 名称、SDK/config 版本及 retry 配置写入 fingerprint。

一次 `model_call_index` 是 Agent 发起的一次逻辑模型调用；一次 `transport_attempt_index` 是 SDK/provider client 发出的一次底层传输请求，两者不得混淆。若 SDK 无法关闭重试，只有在每个底层传输请求都能进入独立 transport ledger、且成功结果能说明使用了第几个 transport attempt 时才可准入；无法观测的隐式重试直接判定配置不合格。即使底层重试最终成功，该调用也不得被标为“无 provider 故障的 clean call”。

## 5. Token telemetry 与成本语义

### 5.1 Crash-consistent per-call journal

不使用单文件 append JSONL。每个逻辑模型调用使用独立文件：

```text
usage-calls/000001.json
usage-calls/000002.json
transport-attempts/000001-000001.json
```

调用发出前先把 `000001.json` 以 `status=in_flight` 落盘；回调成功或报错后，用 `completed` 或 `error` 版本原子替换同一路径。每次状态转换都必须：

1. 在同目录写唯一临时文件；
2. flush 并对文件执行 `fsync`；
3. 使用原子 replace 替换目标文件；
4. 在平台支持时对父目录执行 best-effort `fsync`。

Windows 使用同目录 `os.replace` 语义。启动时遗留的 `.tmp` 不进入统计，必须移入隔离区或报告为不完整临时文件；保留下来的 `status=in_flight` 文件是 worker 在调用中被终止的证据，不得删除或改写成零 token。

每个 model-call 文件只保存：

- `model_call_index`；
- terminal status：`in_flight/completed/error`；
- `usage_available`；
- input/output/total tokens 或 null；
- usage 来源；
- 已观测的 `transport_attempt_count`；
- 脱敏错误类别；
- 稳定的相对顺序字段。

journal 不记录 prompt、response、headers、凭据或完整 endpoint。即使首次请求直接得到 provider 504，也必须把同一 call file 原子替换成 `status=error`、`usage_available=false`、token 字段为 null 的终态记录。时间戳等不稳定审计元数据进入独立非 hash-critical audit 文件。

### 5.2 运行级覆盖状态

- `full`：运行终止时无 `in_flight` 调用，且每个成功模型响应都有可解析 usage；
- `partial`：运行被中断或仍有 `in_flight` 调用，但至少一个已完成模型响应的 usage 已保存；
- `unavailable`：没有任何已完成模型响应可提供 usage；必须附 `unavailable_reason`。

最少支持以下原因：

- `provider_error_before_usage`
- `provider_usage_missing`
- `worker_killed_before_first_model_response`
- `worker_killed_during_call`
- `usage_parse_error`

任一成功模型响应缺少 usage 均是稳定性失败；首次响应前 provider 504 没有 token 是合法 `unavailable`，不得填零。`in_flight`、completed/error call 数和 transport request 数必须能从文件集合机械复算。

### 5.3 Cost

`estimated_cost` 默认继续为 null。只有 provider 权威账单或明确返回的 billed cost 才能填充；本阶段不维护本地价格表，也不根据 token 推测真实账单。

## 6. 稳定性 smoke 与准入门

稳定性 smoke 使用独立根目录，不写入 Click Benchmark 批次：

- 6 次单调用 provider probe；
- 6 次 worker-envelope probe：Multi-Agent、Plan–Execute、ReAct 各 2 次；
- probe 任务固定、短小、不修改仓库，不计为 Agent 成绩。

执行顺序固定为：先完成 6 次单调用 probe，再按 `Multi-Agent → Plan–Execute → ReAct` 循环两次完成 6 次 worker-envelope probe。因此“最后连续 8 个”明确指单调用 probe 5–6 加全部 6 个 worker-envelope probe。

准入条件必须全部满足：

1. 12 个 probe 均有独立且不可覆盖的 artifact；
2. provider 5xx 总数不超过 1；
3. 最后连续 8 个 probe 无 provider 5xx；
4. 每个成功模型响应都有 token usage；
5. 每个错误都有结构化、脱敏分类和互斥 `provider_phase`；
6. `model_call_index` 与底层 `transport_attempt_index` 能一一审计，SDK 自动重试为 0；
7. worker config、call journal、trace 和报告均通过秘密字段扫描；
8. stability 产物与正式 batch root 完全隔离；
9. `estimated_cost` 是否存在不影响 gate。

smoke 只用于基础设施准入，不产生、展示或暗示任何 Agent 效果结论。

## 7. 正式批次停止条件

以下任一条件立即停止：

- 首次出现 `provider_auth`、`provider_billing` 或 `provider_rate_limit`；
- 首次出现 `provider_request_rejected`；
- 首次出现 `provider_unknown`，并进入人工审计；
- 首次出现 `config` 或 `sandbox`；
- 首次出现 `worker_internal`；若实施前发现可接受的 worker 内部终态，必须先拆成更具体且另有语义的 `failure_kind`，不得放宽这个兜底类别；
- 连续两个 `provider_transport` failure；
- 两 Case 协议的任一 24 行轮次内累计 3 个 provider transport failure；
- 单 Case 协议的任一 12 行轮次内累计 2 个 provider transport failure；
- 任一成功模型响应缺少 token usage；
- 发现 SDK 隐式重试或底层 transport request 无法审计；
- artifact 无法解析、`worker_attempt_id` 被覆盖或三层账目无法一一对应；
- fingerprint、镜像、Case、schedule、资源包络或分析规格漂移。

停止动作：

1. 当前 worker process 尽最大可能完成证据落盘；
2. 后续槽位标记 `not_started`；
3. 当前批次封存为 `pilot/incomplete`；
4. 不在原根恢复、补齐或替换失败槽位；
5. 封存后只生成一次最终 incomplete/inconclusive 结案分析，包含原始账目、完整性和失败审计，不生成 provisional 或正式 Q1/Q2；
6. 修正原因后必须使用新批次根，经新的 G1 批准，从完整 R1 开始。

未达到停止阈值的单个 provider 5xx 作为正式行保留，不重试、不删除，也不静默排除 scheduled denominator。

上述即时停止类均属于基础设施、配置或控制面异常，不得作为 Agent 的自然任务失败继续积累。HTTP 401/403、402、429 和其他 4xx 分别通过第 4.1 节的机械映射触发对应规则。

## 8. Analysis Artifact Determinism

稳定分析产物必须只依赖冻结输入和规范化规则。hash-critical 产物至少包括：

- `thresholds.json`
- `per-case.json`
- `pooled.json`
- `report.md`
- 跨仓库的 `comparison.json` 与 `comparison.md`

这些文件不得包含 `generated_at`、hostname、绝对路径、文件 mtime、本机时区、locale 或非确定性目录枚举顺序。规范化要求：

- UTF-8、LF；
- JSON key 排序；
- 所有 list 使用规格指定的稳定排序键；
- 固定 filesystem traversal 顺序；
- 浮点值使用预注册、跨平台一致的十进制表示；能用整数时不用浮点；
- 链接使用相对于 analysis 目录或批次根的稳定路径；
- 同一输入必须字节级复现。

时间戳、hostname、绝对执行路径、工具版本采集时刻等审计信息写入非 hash-critical 的 `analysis-audit.json`，不得反向影响稳定分析内容或其 hash。

准入测试必须把完整 fixture 批次复制到两个不同绝对路径，并在不同 timezone/locale 设置下分别运行分析，证明全部 hash-critical 产物字节一致。原始 worker config 可以保留本机执行所需绝对 workspace，但这些路径不得进入稳定分析、fingerprint canonical payload 或跨仓库比较 hash。

## 9. Click 快照选择

### 9.1 冻结版本

- Repository：`https://github.com/pallets/click`
- Release/tag：`8.4.2`
- Commit：`b2e30a175449cfda909ee4fbf4a29a6a071cad53`
- License：BSD-3-Clause
- Python：`>=3.10`
- PyPI sdist SHA-256：`9a6cea6e60b17ebe0a44c5cc636d94f09bd66142c1cd7d8b4cd731c4917a15f6`

8.4.2 是已稳定数月的修复版本。较新的 8.5.0 是 feature release，会引入不必要的版本新鲜度变量。官方来源：

- `https://pypi.org/project/click/8.4.2/`
- `https://github.com/pallets/click/releases/tag/8.4.2`
- `https://github.com/pallets/click/blob/8.4.2/pyproject.toml`

实施时仍须机械复核 tag→commit，并重新计算 GitHub source archive SHA-256。PyPI sdist 是交叉验证来源，不替代 GitHub 固定 commit 快照。

### 9.2 Vendor 与 provenance

独立路径：

- template：`evals/repos/templates/click/`
- image resources：`evals/images/click/`
- image tag：`mokioclaw-eval-click:8.4.2`
- provenance：Click template 内独立 `PROVENANCE.md`

allowlist 默认保留：

- `src/click/`
- `tests/`
- `pyproject.toml`
- `LICENSE.txt`
- `CHANGES.rst`
- upstream tests 所需的固定资源

默认裁剪 docs、CI、开发环境和非测试示例。最终 allowlist、裁剪项、适配项、归档 hash、license hash、vendor tree hash、基础镜像 digest、lock hash、Dockerfile hash、构建命令、构建时间和 image ID 全部进入 provenance。

### 9.3 镜像与 source resolution

Click 是 src layout，首选：

```text
PYTHONPATH=/workspace/src
```

镜像不得安装另一份可被 import 的 Click。公开测试、repro 和 hidden tests 必须解析到 `/workspace/src/click/`。

若 upstream tests 依赖 distribution metadata，可以采用 metadata-only 离线 fallback，但必须删除 site-packages 中的 Click 代码，并继续证明 runtime import 来自 workspace。该决策必须在任何 Case 或真实 run 前冻结。

运行包络保持：Docker `network none`、1 CPU、512 MiB、128 pids、只读 rootfs、受限 `/tmp`。

### 9.4 快照零 Agent-run 准入

- 全量或预注册确定性 upstream suite 在离线容器通过；
- 同一命令连续三次稳定；
- agent-visible pytest/repro 每次不超过 90 秒；
- 不依赖网络、随机顺序、宿主 shell、本机时区或未声明资源；
- 必要的测试排除在 Case 设计和真实运行前冻结并写入 provenance；
- 不得排除原本能够捕获候选 mutation 的 upstream test。

## 10. Click Case 设计与自适应门

### 10.1 候选池

至少审查四个候选行为，优先级固定为：

1. option/flag/default/envvar 解析；
2. argument/nargs/type conversion；
3. help/usage rendering；
4. `CliRunner` 输入输出边界。

最终两个 Case 必须来自不同子系统。候选失败必须记录拒绝理由，不得为凑足数量降低验收门槛。

每个候选在任何 red/green 验收前冻结唯一 `subsystem_id`，取值只能是 `option-parsing`、`argument-conversion`、`help-rendering` 或 `cli-runner-io`。不得在看到准入结果后修改归属。

### 10.2 每个 Case 的准入要求

1. 固定输入下行为确定；
2. bug/fix 两态 upstream-owned tests 均绿；
3. 默认 public pytest bridge 与独立 repro 在 bug 态红、fix 态绿；
4. hidden behavior tests 在 bug 态红、fix 态绿；
5. public 与 hidden 行为相关，但 hidden 增加可推断边界；
6. 不依赖不可推断的精确消息或内部实现路径；
7. task 只描述外部症状和 repro，不泄漏文件或修法；
8. controller 定位链不超过约 10 步；
9. reference patch 不超过 40 changed lines；
10. temporary broken edit 能同时让两个 public 入口变红；
11. runtime import 指向 workspace；
12. protected manifest 覆盖 tests、repro、license、provenance、缺失 hooks 和 symlink；
13. public pytest 和 repro 连续三次均通过 90 秒门；
14. fixture/reference 验收结果不进入 Agent 成绩。

### 10.3 自适应 Case 门

- 只有至少 2 个候选通过，且其中可按固定优先级选出两个不同 `subsystem_id` 的 Case，才冻结两个 Case 并执行 72-run 协议；
- Case 1 是固定优先级中第一个 PASS；Case 2 是其后第一个 PASS 且 `subsystem_id` 与 Case 1 不同的候选；
- 若完成至少四个候选的同标准审查后仍没有第二个不同子系统的 PASS，则只冻结 Case 1 并执行 36-run 协议；多个同子系统 PASS 不得触发 72-run；
- 0 个通过：停止 Click，不自动切换 HTTPie；HTTPie 需要独立设计补充和用户 gate。

Case 数量在 G1 前冻结，此后不能因 Agent 结果追加或替换 Case。

## 11. 独立实验身份、fingerprint 与预算

Click 使用独立的设计、实施计划、batch root、preflight、fingerprint、schedule、thresholds、分析产物、Case 材料、镜像和 provenance。

建议批次根：

```text
evals/reports/snapshots-click-842-<freeze-date>/
```

schedule seed 冻结为 `20260922`。继续使用固定 seed 的 base permutation 和 R2/R3 循环错位，但不得复制 Rich 的 schedule 文件或 hash。

### 11.1 `experiment-fingerprint.json`

fingerprint 使用 canonical JSON，覆盖以下身份域：

**Framework**

- framework Git commit；
- Agent implementation tree/hash；
- 三种 architecture config hash；
- prompt/config hash；
- tool schema hash。

**Provider/model**

- provider identifier/adapter name；
- provider host（不含 scheme、path、query、凭据）；
- model ID；
- generation parameters；
- provider/model version（仅在 provider 明确提供时记录，否则为 null）；
- SDK 名称与版本、provider adapter/config version；
- SDK retry 配置与可观测 transport policy。

**Repository/Case**

- Click repository commit 与 vendor tree hash；
- 每个 Case 的 YAML/definition hash；
- mutation patch hash；
- public tests hash；
- hidden behavior tests hash；
- repro hash；
- protected manifest hash。

**Environment**

- image digest；
- dependency lock hash；
- Dockerfile hash；
- 完整 resource envelope。

**Experiment**

- schedule hash；
- `analysis_spec_sha256`；
- Case set hash；
- batch protocol version。

Canonical serialization 固定为 UTF-8、LF、JSON key 排序、数组按各字段规定的稳定顺序；不得包含绝对路径。SHA-256 针对 canonical bytes 计算。

字段分三类：

1. **identity fields**：以上所有列出的身份域；任何变化立即停止当前批次，只能新建 batch root；
2. **metadata-only fields**：采集时间、hostname、操作者、本机路径等，只能写入独立 `fingerprint-audit.json`，不进入 identity hash；
3. **per-worker-attempt fields**：`worker_attempt_id`、启动/结束时刻、退出码、局部 artifact 相对路径，可在同一 fingerprint 下不同，但不得改变实验配置。

fingerprint 在 G1 前冻结；每个 worker 启动前复核 identity hash，分析器也必须拒绝混合 fingerprint。

### 11.2 两 Case：72 runs

| 轮次 | 每格新增 | 四格新增 | 累计 |
|---|---:|---:|---:|
| R1 | 6 | 24 | 24 |
| R2 | 6 | 24 | 48 |
| R3 | 6 | 24 | 72 |

### 11.3 单 Case：36 runs

| 轮次 | 每格新增 | 四格新增 | 累计 |
|---|---:|---:|---:|
| R1 | 3 | 12 | 12 |
| R2 | 3 | 12 | 24 |
| R3 | 3 | 12 | 36 |

两种规模都保留 ReAct、Plan–Execute、Multi-Agent 和四格。资源格记为 `max tool calls / wall time seconds`：A=`40/600`，B=`80/600`，T=`40/900`，J=`80/900`。第一个数字始终是最大工具调用预算，第二个数字始终是 wall-time 秒数。

## 12. 用户 gates

### 12.1 G1：真实 R1 前

必须呈现：

- 12-probe stability smoke；
- provider 分类和 token coverage；
- 秘密扫描；
- Click commit、archive、license、image、lock 身份；
- Case 数量和全部零 Agent-run 验收；
- batch root、schedule、`experiment-fingerprint.json` 与冻结 analysis spec 的 hash；
- 36 或 72 的明确预算和停止规则。

### 12.2 G2：R1 后

只呈现以下完整性与稳定性审计：

- 已启动、已闭合、`not_started` 的槽位数；
- provider failure 总数、连续失败状态、各 `failure_kind`/`provider_phase` 数；
- token coverage 的 `full/partial/unavailable` 数与缺失原因；
- 全轮聚合 token totals（不得按 Case、架构或资源格拆分）；
- call journal、transport ledger、秘密扫描、fingerprint 和 artifact 完整性；
- 是否触发预注册停止条件。

不得呈现每个资源格、Case 或架构的成功/失败分布，不得呈现 provisional per-case 状态、Q1/Q2、budget-priority、deep progress、资源迁移或 ReAct 漂移。批准只授权 R2。

### 12.3 G3：R2 后

呈现累计 24 或 48 行的同一套完整性与稳定性审计，仍不展示任何效果方向。批准只授权 R3。

任何 gate 未批准均停止，不预执行下一轮。只有 R3 全部完成，或批次按预注册停止条件封存后，才可生成正式/不完整分析；人为拒绝继续本身不授权查看此前隐藏的效果结果。

## 13. Click 机械分析

### 13.1 独立冻结规格

在任何真实 R1 前创建并冻结：

```text
evals/specs/resource-analysis-v1.json
```

该文件不依赖 Rich 批次，必须单独包含 cell 定义、counter 定义、non-resource family、deep-progress、状态优先级、Q1、Q2、provider sensitivity、单 Case 分支和 canonical output 规则。`experiment-fingerprint.json` 记录其 `analysis_spec_sha256`。只读取该文件和规范化 batch artifact，即足以独立重实现分析器；不得用“沿用 Rich 公式”代替规范内容。

稳定输出为：

- `analysis/thresholds.json`
- `analysis/per-case.json`
- `analysis/pooled.json`
- `analysis/provider-sensitivity.json`
- `analysis/react-canary.json`
- `analysis/report.md`

不稳定执行元数据单独写入非 hash-critical `analysis/analysis-audit.json`。

### 13.2 资源格与 counter

四格固定为：

- A：`max_tool_calls=40`，`wall_time_seconds=600`；
- B：`max_tool_calls=80`，`wall_time_seconds=600`；
- T：`max_tool_calls=40`，`wall_time_seconds=900`；
- J：`max_tool_calls=80`，`wall_time_seconds=900`。

两 Case/72-run 分支中，每个 architecture×cell 的 scheduled `n=6`。对 Multi-Agent 和 Plan–Execute 计算：

- `ts`：`status=passed` 的数量；
- `bud`：`status=budget_exhausted` 的数量；
- `tout`：`status=timed_out` 的数量；
- `res := bud + tout`；
- `tool_ge_45`：`tool_calls >= 45` 的数量；A/T 因最大预算为 40，机械上恒为 0；
- `deep`：符合下述 deep-progress 的数量；
- `nonres`：失败归因属于冻结 non-resource family 的数量；
- `provider_attrition`：被 provider failure 中断、不能观察自然 Agent 终态的数量。

冻结的 non-resource family 只有：

```text
patch_generation_failure
public_regression_failed
hidden_contract_miss_after_validation
protected_file_violation
```

`deep=1` 的机械规则：

- Plan–Execute：`last_stage == verify` 或 `agent_attempt_count >= 2`；
- Multi-Agent：`last_stage ∈ {context_monitor, context_compressor, verifier, final}` 或 `agent_attempt_count >= 2`；
- ReAct：不计算 deep，不进入 Q1/Q2。

### 13.3 Pooled 状态公式

对 relaxed cell `R ∈ {B,T,J}` 与 anchor A：

```text
S(R)      := ts(R) >= ts(A) + 2
E(R)      := res(R) <= res(A) - 2
P(R)      := tool_ge_45(R) >= 2 OR deep(R) >= deep(A) + 2
Relief(R) := E(R) OR P(R)
N(R)      := nonres(R) >= nonres(A) + 2
```

`N` 只产生 `failure_migration=true` 注记，不参与 `Relief`，也不单独改变 state。

逐格 state 必须按以下顺序取第一个命中项：

1. `resource-relief-success`：`S(R) AND Relief(R)`；
2. `resource-relief-no-success`：`NOT S(R) AND Relief(R)`；
3. `resource-still-binding`：`NOT S(R) AND NOT Relief(R) AND res(R) >= 3`；
4. `no-resource-signal / inconclusive`：其余。

### 13.4 Q1 完整映射

先计算 `Relief(B)`、`Relief(T)`、`Relief(J)`：

```text
Relief(B) AND NOT Relief(T)
  => budget-axis directional signal

NOT Relief(B) AND Relief(T)
  => timeout-axis directional signal

Relief(B) AND Relief(T)
  => both axes independently influential

NOT Relief(B) AND NOT Relief(T) AND Relief(J)
  => joint constraint / interaction

otherwise
  => no axis-order signal / inconclusive
```

次级字段：

```text
budget_priority_pattern := Relief(B)
                           AND Relief(T)
                           AND bud(B)=0
                           AND bud(T)>=1
```

该字段不改变 Q1 主标签。规范来源是已批准的 Rich 设计 §7.3.1：budget-priority 只在 `Relief(B) AND Relief(T)` 的 `both axes independently influential` 分支内追加。当前 HEAD 的历史分析器和旧实施计划伪代码漏写了 `Relief(T)`，属于实现偏差，不构成另一个获准公式；实施计划必须修正并增加“`Relief(B)=true`、`Relief(T)=false` 时 pattern=false”的回归测试。该修正不重算 Rich 产物；Rich 冻结 Q1 已为双轴均有影响，所以其已报告的 pattern=true 不变。

### 13.5 Q2 完整映射

Q2 仅用于 Plan–Execute：

```text
TimeWallShift := bud(B)=0
                 AND tout(B)>=2
                 AND deep(B)>=deep(A)+2

DualAxisConversion := TimeWallShift
                      AND ts(J)>=ts(B)+2
                      AND tout(J)<=tout(B)-2

TimeStillBinding := TimeWallShift
                    AND NOT DualAxisConversion
                    AND tout(J)>=2
```

输出优先级：

1. `DualAxisConversion` 为真：`dual-axis conversion`；
2. 否则 `TimeStillBinding` 为真：`time still binding`；
3. 否则：`no time-wall migration signal / inconclusive`。

### 13.6 Provider 分析资格与边界敏感性

Provider 失败行保留在 scheduled denominator，绝不删除或补跑。正式 Q1/Q2 的最低完整性门为：

- 对正在分析的 architecture，其 A/B/T/J 每格至少 5/6 个槽位没有被 provider failure 中断；
- 该 architecture 四格的 `provider_attrition` 最大值与最小值之差不超过 1；
- 该 architecture 的所有 provider failure 都有结构化 kind、phase、call/transport ledger 与 telemetry coverage。

资格按 architecture 独立判定：

- Multi-Agent Q1 只检查 Multi-Agent 的 A/B/T/J；
- Plan–Execute Q1 和 Q2 只检查 Plan–Execute 的 A/B/T/J；
- ReAct 只检查自身 `react-canary` 的完整性，不参与 Multi-Agent 或 Plan–Execute 的 Q1/Q2 qualification；
- 一个 architecture 的 provider attrition 不得取消另一个 architecture 的分析资格。

某个 architecture 的最低门不满足，只把该 architecture 对应的 Q1，以及 Plan–Execute 对应的 Q2，输出为：

```text
provider-attrition / inconclusive
```

即使最低门满足，也必须执行保守的 provider 边界敏感性穷举。对每个 provider-failed 槽位，枚举其在没有 provider 中断时可能出现的终态：

```text
passed
budget_exhausted
timed_out
non_resource_failed
other_failed
```

终态 counter 约束为：

- `passed`：`ts=1`，其余 `bud/tout/nonres=0`；
- `budget_exhausted`：`bud=1`，其余 `ts/tout/nonres=0`；
- `timed_out`：`tout=1`，其余 `ts/bud/nonres=0`；
- `non_resource_failed`：`nonres=1`，其余 `ts/bud/tout=0`；
- `other_failed`：`ts/bud/tout/nonres=0`；
- 对 Multi-Agent/Plan–Execute，`deep ∈ {0,1}`；
- 对 B/J，`tool_ge_45 ∈ {0,1}`；对 A/T 固定为 0；
- 每个槽位的 counter 必须满足上述互斥关系，不能同时分配两个终态。

敏感性穷举也按 architecture 独立执行，不得对整个 batch 的 provider-failed slots 做全局笛卡尔积：

- Multi-Agent 只枚举 Multi-Agent A/B/T/J 中的 provider-failed slots，生成 candidate pooled states、candidate Q1 labels 和 candidate `budget_priority_pattern`；
- Plan–Execute 只枚举 Plan–Execute A/B/T/J 中的 provider-failed slots，除上述候选外再生成 candidate Q2 labels，以及 candidate `TimeWallShift`、`DualAxisConversion`、`TimeStillBinding`；
- ReAct 不进入 Q1/Q2 provider-sensitivity enumeration，只在 `react-canary.json` 中报告自身完整性和 attrition。

对每个 architecture 的每个完整补全重新计算对应输出：

- 若某个 B/T/J pooled state 在所有补全中相同，才输出该正式 state；否则该格输出 `provider-sensitive / inconclusive` 并保留候选 state 集合；
- 若一个架构的 Q1 主标签和 `budget_priority_pattern` 在所有补全中完全相同，该 Q1 才 qualified；否则输出 `provider-sensitive / inconclusive`，并列出可导致变化的边界结果；
- 若 Plan–Execute 的 Q2 主标签及 `TimeWallShift/DualAxisConversion/TimeStillBinding` 在所有补全中完全相同，Q2 才 qualified；否则输出 `provider-sensitive / inconclusive`；
- 不得只用“观察到的 provider 行按全零计数”作为正式结论。

`resource-analysis-v1.json` 必须显式编码上述 per-architecture qualification scope、enumeration scope 和输出集合；分析器不得从批次全局 failure 数推断单个架构的资格。

选择该方法而不是简单要求 6/6 provider-clean：6/6 规则实现更简单，但一次均衡、可审计的外部 provider 故障就会废弃整批方向证据；边界穷举允许保留这类批次，同时只有在所有合理补全下结论不变时才授予资格。5/6 最低门把每格缺失槽位限制为至多一个，使穷举规模有界；若未来放宽该门，必须升级 analysis spec 并新建批次。

### 13.7 单 Case/36-run 分支

单 Case 时每个 architecture×cell 只有 `n=3`，仅输出：

- 原始终态计数；
- 相对 A 的原始整数 delta；
- provider attrition；
- telemetry coverage；
- 不带正式标签的描述性资源迁移表；
- 最终 ReAct canary distribution。

该分支不得输出或缩放 `S/E/P/Relief/N`，不得输出 `resource-relief-success`、`resource-relief-no-success`、`resource-still-binding`、`no-resource-signal` 等 pooled state，也不得产生 Q1、Q2 或按 `n=3` 缩小阈值。

跨仓库资格固定为：

```text
single-case evidence / repository-level corroboration inconclusive
```

### 13.8 ReAct canary 的机械定义

ReAct 只在全部预注册轮次完成后生成 `react-canary.json`。每个 Case×cell 报告以下终态向量：

```text
[passed, budget_exhausted, timed_out, failed, setup_failed, provider_attrition]
```

并给出 B/T/J 相对 A 的逐分量整数差。它不计算 deep、S/E/P/Relief、state、Q1 或 Q2，不产生“架构更好/更差”的方向标签，也不在 G2/G3 展示。所谓 ReAct drift 仅指该终态向量至少一个分量相对 A 非零，是最终分析中的描述性 canary，不是 gate 条件或因果结论。

## 14. Rich–Click 方向性比较

Rich 三份机器分析产物保持字节不变，不使用新规则重写 Q1/Q2。第 2.3 节的 `rich-legacy-audit.json` 只补充审计资格，不进入 Rich 方向公式。

独立比较根：

```text
evals/reports/cross-repo-rich-click-<date>/
```

比较器只读取两个仓库已经完成的机器分析、Click provider sensitivity、Rich legacy audit sidecar 和对应 hash，不读取或合并原始 manifest。输出：

- `comparison.json`
- `comparison.md`

跨仓库输出必须包含三个互不混淆的顶层字段：`dimension_results`、`direction_comparison` 和 `strict_audit_status`。per-case divergence、provider attrition、telemetry coverage、historical worker-attempt completeness 作为支持性审计字段，不参与方向聚合。

`dimension_results` 固定包含：

```text
multi_agent_q1
plan_execute_q1
plan_execute_q2
```

每个维度记录 `required`、`rich_label`、`click_label`、`same_label`、`directional_corroboration` 和 `result`。本阶段的 repository-level comparison 固定要求三个维度，故两 Case 和单 Case 分支中的 `required` 都为 true。单 Case/36-run 不产生仓库级 Q1/Q2，因此三个 required dimensions 均为 `not_applicable`，顶层按下述规则降级为 `inconclusive`。

每个维度的 `result` 只允许：

- `consistent`：Rich 和 Click 都有 qualified、determinate 的方向标签，且标签相同；
- `divergent`：两边都有 qualified、determinate 的方向标签，但标签不同；
- `inconclusive`：任一侧标签本身含 `/ inconclusive`，或该侧因 batch incomplete、provider attrition、provider sensitivity 或分析完整性而不具备方向资格；
- `not_applicable`：该实验分支按规格不产生此维度，例如单 Case/36-run。

Q1 的 determinate 标签为 `budget-axis directional signal`、`timeout-axis directional signal`、`both axes independently influential`、`joint constraint / interaction`；`no axis-order signal / inconclusive` 不是 determinate。Q2 的 determinate 标签只有 `dual-axis conversion` 和 `time still binding`；`no time-wall migration signal / inconclusive` 不是 determinate。

`same_label` 只表示字符串相同，不等于方向得到支持。若 Rich 与 Click 都是 `no time-wall migration signal / inconclusive`，则 `same_label=true`、`directional_corroboration=false`、`result=inconclusive`，不得记为 `consistent`。Q1 的 `budget_priority_pattern` 作为独立次级字段比较；主 Q1 维度为 `consistent` 但该布尔值不同，只追加 `secondary-divergence`，不改写主维度结果。

`direction_comparison` 按以下 precedence 唯一聚合：

1. 任一 required dimension 的 `result ∈ {inconclusive, not_applicable}`：`inconclusive`；
2. 否则三个 required dimensions 全部为 `consistent`：`directionally consistent`；
3. 否则全部 required dimensions 均 determinate，且至少一个为 `divergent`：`repository-specific / divergent`。

不存在第四种回退路径；若 comparator 无法命中上述任一分支，必须拒绝产出而不是自行解释。由于 Rich 冻结的 Plan–Execute Q2 是 `no time-wall migration signal / inconclusive`，本次 Rich–Click 顶层 `direction_comparison` 的机械上限是 `inconclusive`；Multi-Agent Q1 和 Plan–Execute Q1 仍可在 `dimension_results` 中分别报告 consistent 或 divergent，但不能越过 required Q2 把顶层提升为 `directionally consistent`。

`strict_audit_status` 只允许：

1. `strict-audit-comparable`：两仓库都有新版 fingerprint、完整 call/transport journal、完整 worker-attempt ledger 和相同审计定义；
2. `legacy-audit-limited`：Click 审计完整，但 Rich 的历史 worker attempt 或 telemetry 只能由旧产物有限恢复；
3. `click-audit-limited`：Rich 审计满足所需定义，但 Click 审计不完整；
4. `both-audit-limited`：两侧均存在审计缺口。

鉴于已知的 Rich 三槽位历史覆盖，当前预期上限是：

```text
plan_execute_q2.result = inconclusive
direction_comparison = inconclusive
strict_audit_status = legacy-audit-limited
```

`directionally consistent` 与 `legacy-audit-limited` 在通用 schema 中是可组合的两个正交字段，但受 Rich 当前冻结 Q2 限制，本次比较不能实际产生该组合。报告可以陈述两个 Q1 维度的局部一致性，但顶层必须保持 `inconclusive`，并同时报告 `legacy-audit-limited`。不得把局部同向写成严格复制、统计显著或等质量复现。

禁止合并 passed/failed/setup failed 计数、计算跨仓库总成功率、使用统一 pooled denominator，或把 108/144 runs 写成一个统计样本。

## 15. 测试策略

### 15.1 Provider 与 telemetry

- 504 在 `before_first_model_response`、`after_model_response_before_first_tool` 和 `after_tool_activity` 的互斥分类；
- HTTP 401/403、402、429、其他 4xx、5xx 和 TLS/DNS/connect/read/protocol error 的机械 `failure_kind` 映射；
- `worker_internal` 不吸收 provider 边界未知异常；
- `provider_auth`、`provider_billing`、`provider_rate_limit`、`provider_request_rejected`、`provider_unknown`、`config`、`sandbox`、`worker_internal` 首次出现即停止；
- `provider_transport` 只按连续失败和轮内累计阈值停止；
- SDK `max_retries=0`，逻辑 model call 与 transport attempt 分离；无法观测的隐式重试拒绝准入；
- timeout、budget exhaustion、途中异常后的 partial usage 恢复；
- 每次 call 的 `in_flight → completed/error` 原子替换，崩溃后遗留 `in_flight` 可恢复；
- `.tmp` 不计入 usage，且会被隔离或报告；
- 成功响应缺少 usage 时触发 gate failure；
- `before_first_model_response` provider failure 正确产生 unavailable reason；
- 脱敏器不输出 key、完整 URL、query、headers 或 payload。

### 15.2 账目、fingerprint 与停止

- `worker_attempt_id` 目录不可覆盖；
- scheduled run 最多一个正式 `worker_attempt_id`；
- `agent_attempt_count` 不会触发 worker 补跑；
- stop 后未执行槽位标记 `not_started`；
- pilot 根不可恢复正式执行；
- canonical fingerprint 的 key/list/path 规范和 identity/metadata/per-attempt 字段分层；
- framework/provider/repository/environment/experiment 任一 identity 漂移时拒绝续跑；
- G2/G3 输出快照不含资源格、Case、架构效果方向或 ReAct drift；
- 36/72 自适应门要求第二个 PASS 来自不同 `subsystem_id`。

### 15.3 Click 快照与 Case

- tag/commit/archive/license/provenance 可复核；
- source resolution 只指向 workspace；
- upstream tests、public pytest、repro、hidden tests 的 bug/fix 矩阵；
- protected manifest 的 file/directory/absent/symlink/cache 语义；
- broken-edit、feedback equivalence、连续三次时长门；
- 原 Rich Case、镜像和历史产物无变化。

### 15.4 分析与比较

- 两 Case n=6 才产生正式 Click Q1/Q2；
- `resource-analysis-v1.json` 的 golden vectors 覆盖 state 优先级、完整 Q1 映射、含 `Relief(T)` 的 budget-priority 和 Q2 三个布尔量；
- `Relief(B)=true`、`Relief(T)=false`、`bud(B)=0`、`bud(T)>=1` 时 `budget_priority_pattern=false`；
- `N` 只产生 failure migration 注记，不改变 Relief/state；
- 单 Case n=3 只输出原始计数、delta、attrition、coverage 和描述性迁移，不产生 state/S/E/P/Q1/Q2；
- provider attrition 超最低门时降级为 `provider-attrition / inconclusive`；
- Multi-Agent 与 Plan–Execute 的 provider qualification 和边界穷举彼此独立；ReAct attrition 不改变两者资格；
- per-architecture provider 边界穷举能同时覆盖不变与会翻转 Q1/Q2 的 fixture，后者降级为 `provider-sensitive / inconclusive`；
- 比较器拒绝原始 manifest 或混合 pooled count 输入；
- `rich-legacy-audit.json` 不改变 Rich 三份冻结分析 hash，记录 final 22/22 worker-stage 504 证据覆盖，并固定历史 worker-attempt completeness 为 `limited`；
- `dimension_results` 覆盖 consistent/divergent/inconclusive/not_applicable 的全部组合与 aggregate precedence；
- 两侧 Q2 同为 `no time-wall migration signal / inconclusive` 时，`same_label=true` 但 dimension 和 overall 均为 `inconclusive`；
- 批次复制到不同绝对路径，并切换 timezone/locale 后，所有 hash-critical 分析产物字节相同；
- `analysis-audit.json` 的不稳定元数据不影响任何稳定产物 hash；
- comparison 的方向标签与严格审计状态各自只能使用预注册枚举。

Windows 测试必须显式设置当前 checkout 的 `PYTHONPATH=src`，并使用独立 pytest `--basetemp`。

## 16. 安全与审计约束

- 不读取、打印或复制 `.env` 的秘密值；
- API Key 不进入 Case、worker config、worker-attempt ledger、call/transport journal、trace、报告、fingerprint 或容器参数；
- 容器继续 `network none`，provider 调用只发生在宿主控制平面；
- hidden tests 永不进入 Agent workspace；
- ignored 实验产物不得被清理、覆盖、移动或纳入批量 Git 操作；
- 执行清理、worktree 或批量 Git 操作前同时检查 tracked、untracked 和 ignored 内容；
- `git add` 只允许精确路径；
- 不 push，不修改远端；
- 所有失败、停止和 unavailable 都是证据，不做结果导向修正。

## 17. 里程碑

| 里程碑 | 内容 | 真实 Agent runs |
|---|---|---:|
| S0 | provider 分类、crash-consistent call journal、worker-attempt ledger、fingerprint、analysis determinism 和离线测试 | 0 |
| S1 | Click 8.4.2 vendor、镜像、provenance 和 upstream suite 准入 | 0 |
| S2 | 至少四个候选审查，冻结 1 或 2 个合格 Case | 0 |
| S3 | 12-probe stability smoke，准备 G1 材料 | 0（非 Benchmark） |
| E1 | G1 后执行 R1 | 12 或 24 |
| E2 | G2 后执行 R2 | +12 或 +24 |
| E3 | G3 后执行 R3 | +12 或 +24 |
| A0 | Rich 只读 legacy audit sidecar | 0 |
| A1 | Click 独立分析、provider sensitivity 与阶段报告 | 0 |
| A2 | Rich–Click 双轨方向/审计比较 | 0 |

## 18. 完成定义

- [x] provider 失败、token coverage、model/transport call 和 worker-attempt 账目可以机械分类与复算；
- [x] stability smoke 达到准入门且没有秘密泄漏；
- [x] Click 8.4.2 快照、镜像和 provenance 身份完整；
- [x] 至少四个候选已审查，最终 1/2/0 Case 决策遵守不同子系统规则并有拒绝理由；
- [x] 36/72 预算、schedule、fingerprint、analysis spec 和 batch root 在 G1 前冻结；
- [x] 每轮真实运行均获得对应用户批准；
- [x] G2/G3 没有暴露中间效果方向；
- [x] 正式行未被删除、替换或补跑；
- [x] Click 分析可仅凭冻结 spec 与独立批次复算；
- [x] provider sensitivity 已对全部缺失终态边界穷举；
- [x] provider qualification 与 sensitivity 按 architecture 独立执行，ReAct 不污染 Q1/Q2 资格；
- [x] Rich 三份机器分析 hash 保持不变；
- [x] Rich legacy sidecar 记录 final 22/22 provider 504 证据覆盖，并明示历史 worker-attempt completeness `limited`；
- [x] 跨仓库比较不混合 pooled 计数，输出逐维度结果、预注册 aggregate 和严格审计状态；
- [x] 所有 hash-critical 分析产物跨路径、时区和 locale 字节一致；
- [x] 全项目测试、Ruff、diff check、秘密扫描和分析复算通过；
- [x] 阶段报告明确样本量、provider attrition、telemetry coverage、限制和 non-claims；
- [x] README、Retrieval、MCP、服务化和产品化未混入核心实验。

## 19. 书面规格之后的权限边界

本文件只是设计规格。用户审阅并明确批准本文件后，下一步只能调用 `superpowers:writing-plans` 编写详细实施计划。实施计划完成后必须再次交给用户审阅，并由用户选择执行方式。设计批准不自动授权实施计划，实施计划批准也不自动授权真实 R1；G1/G2/G3 继续独立生效。

## 20. 本轮没有修改的核心实验原则

- Click 仍是第二个开源仓库首选；HTTPie 只在 Click 无法满足准入条件时作为另行设计、另行批准的备选。
- 仍采用自适应门：满足两个不同子系统 Case 才执行 72 runs，否则在完成至少四候选审查且仅有一个可用 Case 时执行 36 runs。
- schedule、worker-attempt ledger 和正式结果仍是 append-only、不可覆盖、不可择优补跑的审计账目。
- provider 失败仍与 Agent 任务失败严格分离；Rich 最终冻结 72 行中经 22/22 结果文件确认的 worker-stage provider 504 不改写为 Agent 失败。
- G1/G2/G3 仍是逐轮用户授权边界；本轮只收紧了 G2/G3 可展示的信息，未削弱用户 gate。
- Rich 与 Click 仍先分别分析，再做跨仓库方向性比较。
- 仍不合并两个仓库的 pooled count，不计算跨仓库总成功率，不宣称统计显著或普适结论。
- fixture red-green、reference patch、provider probe 和 smoke 仍不计为 Agent 成绩。
- BM25、Embedding、Rerank、AST Index、README、MCP、FastAPI/SSE 和产品化工作仍不进入本阶段核心实验。
- 在设计与实施计划获得明确批准前，仍不实施代码、Click Case 或真实 Agent runs；worktree、提交、推送和远端修改仍需单独授权。
