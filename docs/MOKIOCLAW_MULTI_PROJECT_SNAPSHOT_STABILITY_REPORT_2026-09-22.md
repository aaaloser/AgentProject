# MokioClaw 多项目快照扩展与评测稳定性强化阶段报告

> 计划基线：2026-09-22；报告日期：2026-09-26（Asia/Shanghai）<br>
> 范围：Rich v14.3.4 冻结分析、Click 8.4.2 独立批次，以及二者的方向性与审计资格比较<br>
> 状态：Tasks 1–20 的本地实施与验收已完成；下文 Git 清单记录 Task 20 提交前检查点

## 1. 阶段结论

本阶段把固定开源仓库快照评测从 Rich 扩展到 Click，并将 provider 失败分类、调用与传输账目、worker-attempt 账目、身份冻结、逐轮授权和分析复算纳入同一套审计边界。Click 最终采用两个不同子系统的 Case，因此选择预注册的 **72-run 分支**，没有启用单 Case 的 36-run 分支。Click 的 R1、R2、R3 各 24 个正式槽位均在各自授权后按顺序执行一次；最终 72 个全部封账。

Rich–Click 比较的三个必需维度分别为两个 Q1 `divergent`、Plan–Execute Q2 `inconclusive`。因此顶层方向结论只能是 **`inconclusive`**；独立的严格审计状态是 **`legacy-audit-limited`**。这不构成严格复制、统计显著性或普适性主张。

## 2. Click 独立批次

Click 8.4.2 的源码、许可证、来源记录、依赖锁与离线镜像已在 S1 准入中冻结。四个候选 Case 经零 Agent-run bug/fix、公开/隐藏行为和时长矩阵验收；机械选择了不同子系统的 `click-double-percent-option-prefix-01`（option parsing）与 `click-choice-unicode-casefold-02`（argument conversion）。候选 fixture、reference patch 和 zero-agent 验收不是 Agent 成绩。

正式批次位于 `evals/reports/snapshots-click-842-tokendance-qwen3-5-flash-20260924-01/`。其 72 个槽位由 `2 Case × 3 架构 × 4 资源格 × 3 轮` 构成；四格为 40/600、80/600、40/900、80/900。身份 SHA-256 为 `01baaa8a3cab209495f20093b42615f00c3d82e2e0fd4635991caa92ae29f7c1`，预注册 schedule 的 canonical SHA-256 为 `1af480c562da6b3287da3e4283335978fc5d19c3800dfd06aa2f9d4a53a37157`。12-probe stability smoke 与后续 6-probe 资格检查属于非 Benchmark 的 provider 准入证据，不进入正式 Agent 计数。

G1、G2、G3 均在相应用户授权前保持停止。R1、R2、R3 各 24/24 个槽位封账，合计 scheduled=72、started=72、closed=72、not_started=0；没有补跑、替换、删除或择优保留。累计遥测覆盖为 full=66、partial=6、unavailable=0。正式结果的 provider attrition=0，`failure_kinds={}`；R3 完整性摘要中的 artifact、call journal、transport ledger、worker ledger、fingerprint、secret scan 六项均为 true。partial 表示遥测覆盖等级，不应自动改写为 Agent 任务失败。

最终分析器仅在原 Click 批次上运行一次，产出 `complete` 的 two-case 分析。Multi-Agent 与 Plan–Execute 分别满足 provider qualification：各架构在每个资源格都有 6 个 provider-clean 槽位、零 provider attrition，并独立完成边界敏感性判读。ReAct 只在 `react-canary.json` 中报告两个 Case 的描述性终态向量，不参与 Q1/Q2 资格或方向聚合。分析保留 10 条未知阶段标签提示（实际工作流节点 `intent_router` 6 条、`plan` 4 条）；未为消除提示而重算或改写一次性正式分析。

## 3. Rich 冻结证据与跨仓库比较

Rich 与 Click 是**两个独立批次**，不合并成功/失败计数，不计算跨仓库成功率，也不把两个 72-run 批次视为一个统一统计样本。Rich 最终 72 行中有 22 行 `setup_failed`，其最终结果文件均可核对为 worker-stage provider 504（22/22）；它们不被改写成 Agent 任务失败。历史 token telemetry 为 full=21、unavailable=51；历史 worker-attempt 与结构化 provider/transport 证据无法完整恢复，因此 Rich legacy sidecar 的审计资格为 `limited`。

Rich 冻结文件的 SHA-256 保持为：

| 文件 | SHA-256 |
|---|---|
| `thresholds.json` | `B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB` |
| `per-case.json` | `167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB` |
| `pooled.json` | `6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2` |

最终比较位于 `evals/reports/cross-repo-rich-click-20260926-01/`，由冻结框架树之外的 `evals/cross_repo_gate_adapter.py` 生成；它只使用哈希绑定的完成态机器分析、Click provider sensitivity、Rich legacy sidecar 与 Click R3 gate-safe 完整性摘要，不读取原始 manifest，也不改变冻结的 `src/mokioclaw`。较早的 `cross-repo-rich-click-20260922/` 是保留未覆盖的初版比较证据，其 JSON 缺少支持性审计字段；**应使用 `-20260926-01` 作为最终比较结果**。最终 JSON、Markdown 与 audit 已在另两个绝对路径、时区和 locale 设置下逐字节复现。

| 必需维度 | Rich 标签 | Click 标签 | 维度结果 |
|---|---|---|---|
| Multi-Agent Q1 | `both axes independently influential` | `budget-axis directional signal` | `divergent` |
| Plan–Execute Q1 | `both axes independently influential` | `budget-axis directional signal` | `divergent` |
| Plan–Execute Q2 | `no time-wall migration signal / inconclusive` | 同一标签 | `inconclusive`，即使 `same_label=true` 也没有方向佐证 |

两个 Q1 的 `budget_priority_pattern` 次级字段也不同，但不改写主维度。逐 Case 差异、各仓库 provider attrition 和遥测覆盖仅列在 `supporting_audit` 中，不进入方向聚合。三个维度中有必需的 Q2 `inconclusive`，故顶层 `direction_comparison=inconclusive`；Click 审计完整而 Rich 历史审计有限，故独立的 `strict_audit_status=legacy-audit-limited`。

## 4. 限制与非主张

- 结果只适用于冻结的两个 Rich Case、两个 Click Case、三种架构、四个资源格、每格三次，以及各自当时的环境和 provider；不推断到其他仓库或模型。
- 两个 Q1 标签跨仓库不同只表示这些固定任务上的机械方向不一致，不构成统计显著或因果解释；Q2 的同名 `inconclusive` 也不是方向复现。
- Rich 历史证据只能支持 `legacy-audit-limited`，不得提升为严格同口径审计或严格复制。
- 先前未过 provider 准入的诊断与 pilot 批次按其原始状态保留，不并入 Tokendance 正式批次；provider failure、fixture red-green、reference patch、zero-agent 验收和 smoke 均不算 Agent 成绩。
- 本阶段没有混入 README 产品化、检索栈、MCP、FastAPI/SSE 或服务化工作。

## 5. 验收与交付边界

Rich sidecar 的 72 行、22/22 provider 504、limited 状态和三份冻结哈希已只读复核。Click 的 72-slot 账目、六项完整性标志、canonical identity/schedule 与分析跨路径字节确定性复核通过。最终比较的 JSON、Markdown、audit 也在两条不同绝对路径和不同时区、locale 下与现存最终产物逐字节一致。安全扫描覆盖相关产物及本报告共 8,054 个文本文件，敏感格式命中 0，`.env` 文件 0；未读取 `.env` 秘密值。

使用指定 Python 环境、显式 `PYTHONPATH=src` 和独立工作区 `--basetemp` 的全项目 pytest：**468 passed、2 skipped、0 failed**；两个 skip 均为本机符号链接创建能力不可用。`ruff check --no-cache src tests evals/cross_repo_gate_adapter.py` 与 `git diff --check` 均通过。Task 20 提交前检查点的 `main` HEAD 为 `7c5c260fe632896d5e10cb5c6d96dd502655aa62`；当时 tracked 修改 0、untracked 2（报告层适配器及其测试），报告、比较和实验产物处于 ignored 路径，未清理或覆盖。这是历史检查点，不代表后续获授权提交后的 Git 状态。

Task 20 验收时只交付本地文件与独立比较产物；没有新真实 Agent run，没有修改冻结的 Rich 或 Click 分析，也没有提交、push 或修改远端。此后的本地提交由用户另行授权，且不包含 push。

## 6. 设计 §18 完成定义逐项审计

以下勾选表示对应实施及验证证据达到设计中的完成定义；不把 Rich 的历史审计限制或 Windows 的两项能力 skip 隐去。

1. [x] Provider 失败、token coverage、逻辑 call/transport 与 worker-attempt 账目可由结构化记录机械分类和复算；Rich 旧账目仍单列有限审计。
2. [x] Tokendance 12-probe smoke 与 6-probe 资格检查通过，秘密扫描无命中；均不记为 Benchmark。
3. [x] Click 8.4.2 快照、离线镜像、许可证、来源与依赖锁身份完成 S1 核验。
4. [x] 四个候选均有 PASS review；按不同子系统的预注册顺序选择前两个，余两个未因失败被错误淘汰。
5. [x] 两 Case 的 72-run 预算、schedule、fingerprint、analysis spec 和 batch root 均在 G1 前冻结。
6. [x] R1、R2、R3 分别在 G1、G2、G3 用户授权后运行。
7. [x] G2/G3 仅含 gate-safe 审计摘要，未提前展示中间效果方向。
8. [x] 72 个正式槽位各启动并封账一次，无删除、替换或补跑。
9. [x] Click 的一次性正式分析可从冻结 spec 与独立批次读入复算；六份稳定产物跨路径字节相同。
10. [x] Provider sensitivity 的终态边界穷举由 fixture/golden tests 覆盖；本正式批次 provider attrition=0，缺失终态集合为空。
11. [x] Multi-Agent 与 Plan–Execute 分别获得资格；ReAct 单列 canary，不污染 Q1/Q2。
12. [x] Rich 三份冻结机器分析 SHA-256 精确不变。
13. [x] Rich legacy sidecar 的 worker-stage 504 覆盖 22/22，历史 worker-attempt 明示 `limited`。
14. [x] 跨仓库比较不合并 pooled count；三个预注册维度、顶层方向与严格审计状态分开输出。
15. [x] Click 六份稳定分析产物与最终比较三份产物跨绝对路径、时区、locale 字节一致；不稳定 audit 元数据独立。
16. [x] 全项目测试、Ruff、diff、秘密扫描、身份/账目和分析/比较复算通过；两项 Windows 符号链接 skip 保留说明。
17. [x] 本报告分别列出两仓库样本量、provider attrition、telemetry coverage、限制及 non-claims。
18. [x] README 产品化、Retrieval、MCP 与服务化均未混入核心实验。
