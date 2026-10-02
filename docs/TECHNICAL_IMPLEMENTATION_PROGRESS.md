# MokioClaw 技术实现进度与新会话交接

> 更新时间：2026-09-21（Asia/Shanghai）
>
> 仓库：`D:\MokioAgent\MokioAgent`
>
> Python 环境：`D:\envs\codeagent`
>
> 当前分支：`main`
>
> 当前提交：`2c68a12 docs(eval): record rich snapshot experiment report`

本文最初记录 2026-09-13 的 Eval 纵向切片状态，现已将总览、完成度和后续路线同步到 2026-09-21。早期章节仍保留当时的实施细节和历史验证值；当前阶段的权威汇总见 `docs/MOKIOCLAW_OPENSOURCE_SNAPSHOT_PHASE_SUMMARY_2026-09-21.md`。

文档严格区分以下状态：

- **已实现**：代码已经存在于当前 `main`。
- **已验证**：已经运行对应命令并取得成功结果。
- **局部实现**：接口或单个纵向样例已经落地，但尚未达到完整设计目标。
- **仅设计**：已写入设计或原始升级指南，尚无对应实现。
- **未验证**：代码入口存在，但尚未取得真实运行成功证据。

---

## 1. 一句话状态

MokioClaw 已经完成从“单 Case Eval 纵向切片”到“固定开源仓库快照探索性评测”的连续升级：

> 固定 Case/开源快照 → 注入缺陷 → 三种 Agent 架构运行 → 捕获 Patch → 独立 Grader → 四格资源矩阵 → 预注册调度 → 机械复算 → 阶段验收。

截至 2026-09-21，项目已完成六个核心自建 Case、三架构消融与资源校准，并在 Rich v14.3.4 的两个冻结 Case 上完成 72 次真实 Agent 运行。当前全项目验证为 `291 passed, 2 skipped`；机器分析状态为 `pooled.status=complete`。

当前最准确的项目描述是：

> MokioClaw 已具备可复现的 Repository Maintenance Agent 评测链路，包括离线 Docker 工具平面、双信任区、批量运行、三架构对比、资源矩阵、固定开源快照、逐 Case 镜像、完整性保护和机械判读。下一步不是补齐基础闭环，而是先强化 provider/遥测稳定性，再用第二个开源仓库检验 Rich 阶段信号能否跨项目迁移。

---

## 2. 项目升级背景与目标

### 2.1 原项目基线

在本轮升级前，MokioClaw 已具备以下能力：

- LangGraph 驱动的显式 Agent 工作流。
- `planner/supervisor` 负责生成计划并分派任务。
- `searchAgent` 负责网络研究。
- `codeAgent` 负责文件操作、代码修改和命令执行。
- `verifier` 负责读取产物、运行检查并决定通过或重试。
- `context_monitor` 和 `context_compressor` 负责上下文监测与压缩。
- rules、working memory、history summary-store 三层记忆。
- `TODO.md`、`NOTEPAD.md`、`HISTORY_SUMMARY.md` 等工作区持久化文件。
- Bash Harness：超时、长输出落盘、后台任务、环境文件、Python/pip shim、基础危险命令识别。
- Human-in-the-loop 审批模式：`inline`、`deny`、`auto`。
- Checkpoint/Resume：`light`、`strict`、`off`。
- Trace：`events.jsonl`、`summary.json`、`timeline.md`。
- Rich 单轮 CLI。
- Textual 多轮 TUI 与 Session。
- 轻量聊天路由与复杂任务路由。

原项目更偏“教学型 Mini CodeAgent”，能够说明 Agent 各组件如何工作，但缺少面向真实仓库维护任务的量化证据。

### 2.2 原始两周升级目标

附件《MokioClaw 两周极速升级实施指南》的目标是把项目收敛为：

> 面向真实代码仓库的 Issue → Patch → Test → Review 自动维护 Agent。

目标场景包括：

1. 接收 Issue 或自然语言需求。
2. 检索代码库上下文。
3. 制定修改计划。
4. 修改代码。
5. 在隔离环境运行测试和 lint。
6. 根据公开反馈重试。
7. 由独立评分器验收最终 Patch。
8. 输出变更总结、Trace、资源消耗与失败归因。

原始指南还包含 Repo Retrieval、MCP、Skills、FastAPI/SSE、最终求职包装等内容。

### 2.3 讨论后确认的 Eval-first 路线

后续 brainstorming 没有机械照搬原始“两周每日清单”，而是选择了更稳健的 Eval-first 混合方案：

1. 先解决安全卫生、测试收尾和 CI 基线。
2. 先建立可复现、可信的评测闭环。
3. 先以一个自建小仓库 Case 打通纵向链路。
4. 再扩展至三个自建仓库、六个核心 Case。
5. 先获得 Single ReAct + Grep 基线，再比较 Plan–Execute 和 Multi-Agent。
6. 只有 Trace 和失败数据证明检索是瓶颈时，才实现 BM25 或 Hybrid Retrieval。
7. MCP、Skills、FastAPI/SSE 等放到第二阶段，不抢占核心证据链优先级。

已确认的完整设计位于：

- `docs/superpowers/specs/2026-09-13-mokioclaw-eval-first-upgrade-design.md`

第一阶段纵向切片实施计划位于：

- `docs/superpowers/plans/2026-09-13-mokioclaw-eval-vertical-slice.md`

---

## 3. 已确认的关键设计决策

### 3.1 数据集策略

- 使用混合数据集。
- 先构建三个本地自建 Python 小仓库。
- 每个仓库规划两个任务，共六个核心 Case。
- 六 Case 稳定后，再加入一至两个真实开源仓库的固定版本快照。
- 不在首版追求 SWE-bench 规模。

### 3.2 双信任区

Agent 可见：

- Issue 文本。
- 缺陷注入后的任务仓库。
- 仓库自带公开测试。
- 随仓库提供的公开文档。
- 允许执行的公开验证命令。

Agent 不可见：

- 干净仓库模板的可信来源目录。
- mutation 源文件。
- reference patch。
- Case 配置源文件。
- Grader 实现。
- 隐藏测试。
- Provider API Key。

隐藏测试只在 Agent Worker 退出、最终 Patch 已生成后，复制到新的评分工作区。

### 3.3 网络边界

- 模型调用属于控制平面，宿主 Agent 进程可以访问固定 Provider。
- 任务命令属于工具平面，默认在 Docker 容器内离线执行。
- Eval 模式下不注册 `WebSearchTool`。
- Eval 模式下不向 Planner 暴露 `CallSearchAgentTool`。
- 任务容器不接收 Provider 凭证。

### 3.4 评分原则

唯一主指标是 Task Success Rate。

`success=true` 的设计目标是同时满足：

1. 隐藏行为测试通过。
2. 公开回归测试通过。
3. 受保护文件未被修改。
4. Patch 可以安全应用。
5. 没有违反网络、路径和安全策略。
6. 没有超过尝试次数、工具调用和超时预算。
7. 最终产生与 Issue 相关的有效 Patch。

当前纵向切片已经实现其中的核心子集，完整性差距见本文后续章节。

### 3.5 对比实验原则

正式对比需要固定：

- 模型。
- 温度。
- Provider。
- Prompt 可见信息。
- Case 和仓库快照。
- 公开测试与隐藏 Grader。
- 最大尝试次数。
- 最大工具调用次数。
- 命令与 Agent 总超时。
- Retrieval 策略。

每个候选架构在核心 Case 上计划重复运行三次，不能只挑最好结果。

---

## 4. 当前 Git、分支和环境状态

### 4.1 Git 状态快照

截至 2026-09-21 本次同步：

- 当前分支：`main`；
- 当前 HEAD：`2c68a12fc49940101ea56e8ac967d6558e74109e`；
- `main` 与当前本地 `origin/main` 引用一致；
- 开源快照功能分支 `codex/mokioclaw-opensource-snapshots` 已快进合并；
- 该功能分支和隔离工作树均已安全删除；
- 当前只保留主工作区 `D:\MokioAgent\MokioAgent`；
- 原始实验产物位于被忽略的 `evals/reports/snapshots-20260920/`，不会自动随普通 Git 提交进入远端。

### 4.2 本地忽略内容与保护边界

后续会话必须继续保护用户已有文档、`.env`、实验产物和 SDD 记录，不得因为它们未出现在普通 `git status` 中就删除或覆盖。重点包括：

- `.superpowers/`；
- `evals/reports/`；
- `.mokioclaw/eval-runs/`；
- `docs/` 下被仓库规则忽略但由用户保留的技术、面试和阶段文档；
- `D:\MokioAgent\merge-backups\` 下的冲突文件备份。

执行清理、worktree 移除或批量 Git 操作前，应分别检查 tracked、untracked 和 ignored 内容，并只对明确目标采取操作。

### 4.3 Python 环境

- 当前验证环境：`D:\envs\codeagent`；
- 开源快照阶段所有关键测试均显式将 `PYTHONPATH` 指向当前 checkout 的 `src`，避免 editable install 指向其他工作树；
- 完整测试使用独立 `--basetemp`，绕过本机默认 pytest 临时目录的权限问题；
- 最终合并后测试：`291 passed, 2 skipped in 383.46s`。

> 历史阅读说明：§5–§22 主要保留 2026-09-13 纵向切片的实现细节、当时路径和当时验证值，不应被当作 2026-09-21 的当前状态。当前状态以 §1、§4、§23、§25–§32 及开源快照阶段总结为准。

建议后续始终显式使用：

```bash
/data/liyifan24/envs/codeagent/bin/python
/data/liyifan24/envs/codeagent/bin/pytest
/data/liyifan24/envs/codeagent/bin/ruff
/data/liyifan24/envs/codeagent/bin/mokioclaw
/data/liyifan24/envs/codeagent/bin/mokioclaw-eval
```

重新同步环境时使用：

```bash
cd /data/liyifan24/MokioAgent
UV_PROJECT_ENVIRONMENT=/data/liyifan24/envs/codeagent \
  uv sync --locked --offline \
  --python /data/liyifan24/envs/codeagent/bin/python
```

---

## 5. 第一阶段实施提交历史

从设计到实现的本地提交如下：

| 提交 | 内容 | 状态 |
|---|---|---|
| `20499b8` | `docs: design eval-first MokioClaw upgrade` | 已完成，保存已确认架构设计 |
| `ad1b7b4` | `docs: plan MokioClaw eval vertical slice` | 已完成，保存纵向切片实施计划 |
| `248b6de` | `chore: ignore local worktrees` | 已完成，隔离本地 worktree |
| `d15352c` | `chore: establish secure test baseline` | 已完成，安全卫生、依赖与测试基线 |
| `721d2f8` | `test: establish deterministic CI baseline` | 已完成，TUI 确定性测试与 CI |
| `d9927ab` | `feat: define evaluation case contracts` | 已完成，Eval 类型与 YAML 加载 |
| `d686920` | `feat: prepare isolated evaluation workspaces` | 已完成，工作区与首个 Case fixture |
| `60a6842` | `refactor: inject task command executor` | 已完成，命令执行器注入缝 |
| `514017a` | `feat: isolate evaluation command execution` | 已完成，Eval Docker 沙箱与离线工具策略 |
| `ffbf87c` | `feat: add independent hidden evaluation grader` | 已完成，Patch 与独立隐藏评分 |
| `c8c19d7` | `feat: supervise evaluation agent runs` | 已完成，Adapter、Worker、Runner 与预算 |
| `837bbf2` | `chore: isolate eval patch operations and clear lint baseline` | 已完成，嵌套 Git 隔离与 lint 清理 |
| `effe2e0` | `feat: complete evaluation vertical slice` | 已完成，报告、CLI、文档和纵向闭环 |

上述 10 个实现提交已通过 fast-forward 合并到本地 `master`。

---

## 6. 已完成实现：安全、依赖与测试基线

### 6.1 仓库卫生

已在 `.gitignore` 增加：

```gitignore
.codegraph/
.superpowers/
evals/reports/
.mokioclaw/eval-runs/
```

已从 Git 跟踪中删除陈旧文件：

```text
.codegraph/daemon.pid
```

这一步只取消跟踪 PID 文件和忽略本地运行目录，没有递归删除用户数据。

### 6.2 依赖声明

运行时依赖新增：

- `pyyaml>=6.0.2`：加载 Eval Case YAML。

开发依赖组新增：

- `pytest>=8.0.0`
- `pytest-timeout>=2.4.0`
- `ruff>=0.13.0`

项目 Python 要求为：

```toml
requires-python = ">=3.13"
```

### 6.3 pytest 与 Ruff 配置

`pyproject.toml` 当前配置：

- pytest 默认加载参数移除 ROS/launch 环境插件干扰。
- 单测试默认超时 30 秒。
- 测试目录固定为 `tests`。
- 增加 `docker` marker。
- Ruff 行长 140。
- Ruff 目标 Python 3.13。
- 当前 lint 规则聚焦 `E4`、`E7`、`E9`、`F`。

### 6.4 TUI 挂起修复

原审计中完整测试无法收尾，主要风险来自 Textual TUI 异步测试依赖真实线程和流式 Worker。

本轮已将相关测试改为确定性事件注入，使测试不再依赖不可控后台线程，并为完整测试配置明确超时。

效果：完整测试套件可以在外层 120 秒限制内正常结束。

### 6.5 GitHub Actions CI

新增：`.github/workflows/ci.yml`。

CI 当前步骤：

1. Checkout。
2. 使用 `astral-sh/setup-uv@v6` 安装 uv 和 Python 3.13。
3. `uv sync --locked`。
4. 扫描已跟踪文件中的常见密钥形状。
5. `uv run ruff check .`。
6. 构建 `mokioclaw-eval-python:3.13` Docker 镜像。
7. `timeout 120 uv run pytest -q`。

重要边界：CI 文件已在本地实现并由本地测试覆盖，但本地分支尚未推送，所以还没有远端 GitHub Actions 成功记录。

安全说明：本轮没有读取、打印或提交 `.env` 中的任何密钥；也不能据此声称历史密钥已经完成轮换。密钥轮换仍需用户在 Provider 侧确认。

---

## 7. 已完成实现：Eval 数据契约

核心文件：

- `src/mokioclaw/evals/models.py`
- `src/mokioclaw/evals/cases.py`
- `src/mokioclaw/evals/__init__.py`
- `tests/evals/test_cases.py`

### 7.1 `RunStatus`

当前定义六个终态：

- `passed`
- `failed`
- `timed_out`
- `budget_exhausted`
- `policy_blocked`
- `setup_failed`

注意：枚举契约已包含 `policy_blocked`，但当前 Runner 尚未形成完整的策略违规到该状态的映射，属于接口预留而非完整实现。

### 7.2 `CaseSpec`

`CaseSpec` 使用 frozen dataclass，由以下对象组成：

- `RepositorySpec`
  - `template`
  - `mutation`
- `VerificationSpec`
  - `commands`
- `GraderSpec`
  - `id`
  - `hidden_tests`
  - `protected_paths`
- `Limits`
  - `max_attempts=3`
  - `max_tool_calls=40`
  - `agent_timeout_seconds=600`
  - `command_timeout_seconds=120`
- `Policy`
  - `network="provider_only"`
  - `writable_paths=(Path("."),)`

YAML Loader 当前验证：

- YAML 根节点必须是 mapping。
- `id` 必填。
- `task` 必填。
- `repository.template` 必填。
- `repository.mutation` 必填。
- 至少一个公开验证命令。
- `policy.network` 当前只能是 `provider_only`。
- 四项预算必须为正数。

### 7.3 `AgentRunConfig`

Worker 接收的运行配置包含：

- `run_id`
- `case_id`
- `task`
- `workspace`
- `architecture`
- `retrieval`
- `model`
- `base_url_host`
- `temperature`
- `sandbox_image`
- `max_attempts`
- `max_tool_calls`
- `timeout_seconds`

配置不包含：

- API Key。
- 完整 Base URL。
- Case 源路径。
- mutation 源路径。
- reference patch 路径。
- hidden tests 路径。
- Grader 实现路径。

### 7.4 `CaseResult`

结果对象当前可以记录：

- run/case 标识。
- 状态与成功布尔值。
- first-pass success。
- Grader checks。
- attempts。
- tool calls / tool errors。
- latency。
- input/output tokens。
- estimated cost。
- compression count。
- failure stage / failure reason。
- needs review。
- artifact 路径。
- metadata。

当前部分字段虽然已定义，但真实 Runner 尚未完整填充，详见“已知限制”。

---

## 8. 已完成实现：首个可复现 Case

### 8.1 Case 标识

```text
mini-api-pagination-boundary-01
```

类别：`bugfix`。

任务：

> 修复分页函数在最后一页仍返回 next_page 的问题，保持现有返回结构和参数校验行为不变。

### 8.2 Fixture 目录

```text
evals/
├── cases/
│   └── mini-api-pagination-boundary-01.yaml
├── repos/
│   ├── templates/mini_api/
│   │   ├── pyproject.toml
│   │   ├── src/mini_api/__init__.py
│   │   ├── src/mini_api/pagination.py
│   │   └── tests/test_pagination.py
│   ├── mutations/
│   │   └── mini-api-pagination-boundary.patch
│   └── reference-patches/
│       └── mini-api-pagination-boundary.patch
└── graders/cases/mini_api/pagination_boundary/
    └── test_pagination_hidden.py
```

### 8.3 缺陷设计

干净实现判断下一页的逻辑为：

```python
"next_page": page + 1 if end < len(items) else None
```

mutation 将其改为：

```python
"next_page": page + 1 if start < len(items) else None
```

这样第一页等普通路径仍可通过公开测试，但最后一个非空页会错误地返回下一页。

### 8.4 公开测试与隐藏测试

公开测试验证：

- 第一页正常指向第二页。
- 非正数 `page` 或 `page_size` 仍抛出 `ValueError`。

隐藏测试验证：

- 最后一个非空页的 `next_page` 必须为 `None`。
- 超过最后一页的空页也必须返回 `next_page=None`。

`tests/test_pagination.py` 被列入 `protected_paths`，Agent 修改公开测试会触发完整性失败。

### 8.5 三态验证目标

Case 设计满足：

1. clean template：公开测试与隐藏测试通过。
2. mutation state：公开测试通过、隐藏测试失败。
3. reference patch state：公开测试与隐藏测试再次通过。

这证明隐藏测试确实覆盖了公开测试遗漏的行为边界，而不是重复公开断言。

---

## 9. 已完成实现：隔离工作区准备

核心文件：

- `src/mokioclaw/evals/workspace.py`
- `tests/evals/test_workspace.py`

`prepare_workspace()` 当前流程：

1. 为新 `run_id` 创建独占 `run_root`，使用 `exist_ok=False` 防止覆盖旧运行。
2. 定位可信 template 和 mutation。
3. 将 template 复制为 `baseline/`。
4. 在 `baseline/` 上应用 mutation。
5. 将缺陷注入后的 `baseline/` 复制为 `agent/`。
6. 返回 `PreparedWorkspace(run_root, baseline, agent)`。

术语注意：当前代码中的 `baseline` 指的是“该 Case 的缺陷起始状态”，不是原始 clean template。

最终目录形态：

```text
.mokioclaw/eval-runs/<run_id>/
├── baseline/       # 已注入 mutation，供可信侧对比和评分
├── agent/          # Agent 可见、可修改工作区
├── worker-config.json
├── run-artifacts.json
├── final.patch
└── grading/        # Worker 结束后才创建
```

工作区准备与 Patch 操作显式设置：

```text
GIT_DIR=/dev/null
```

原因是主项目本身处于 Git worktree 时，子目录中的 `git apply` 或 `git diff --no-index` 可能错误继承外层 Git 上下文。该隔离已修复并加入测试。

---

## 10. 已完成实现：可注入命令执行器

核心文件：

- `src/mokioclaw/core/execution.py`
- `src/mokioclaw/core/state.py`
- `src/mokioclaw/core/agent.py`
- `src/mokioclaw/tools/bash_tool.py`
- `tests/test_runtime.py`
- `tests/test_tools.py`

### 10.1 `CommandExecutor` 协议

新增协议：

```python
class CommandExecutor(Protocol):
    def run(
        self,
        *,
        workspace: Path,
        command: str,
        timeout_seconds: int,
        max_output_chars: int,
    ) -> dict[str, Any]: ...
```

### 10.2 Runtime 注入点

`RuntimeState` 新增：

- `command_executor: CommandExecutor | None`
- `allow_web_search: bool = True`

以下入口已经贯通这两个参数：

- `create_runtime()`
- `stream_agent_events()`
- `stream_session_events()`
- `_stream_complex_workflow()`

### 10.3 默认行为兼容

- 普通 CLI/TUI 未注入 executor 时，`BashTool` 仍使用原宿主执行逻辑。
- Eval 注入 `DockerCommandExecutor` 后，前台任务命令改由 Docker 工具平面执行。
- 此改造保留原有事件流接口，因此 Eval 不需要侵入 LangGraph 工作流结构。

重要边界：当前 Docker 沙箱只用于 Eval 注入路径，并没有把普通 CLI/TUI 的所有命令默认迁移到 Docker。

---

## 11. 已完成实现：Eval 离线工具策略

核心文件：

- `src/mokioclaw/tools/registry.py`
- `src/mokioclaw/graph/nodes.py`
- `tests/test_graph.py`

当 `RuntimeState.allow_web_search=False` 时：

- 工具注册表不提供 `WebSearchTool`。
- Planner 工具列表不提供 `CallSearchAgentTool`。
- Verifier 的只读工具也不提供 WebSearch。

真实 Eval Adapter 固定调用：

```python
stream_agent_events(
    ...,
    approval_mode="deny",
    checkpoint_mode="off",
    trace_mode="on",
    command_executor=self.command_executor,
    allow_web_search=False,
)
```

含义：

- 不允许交互式审批阻塞无人值守评测。
- 不为临时 Eval workspace 建立 Checkpoint。
- 保留 Trace 观测。
- 所有 Bash 前台命令走 Docker executor。
- 任务工具不能联网搜索。

---

## 12. 已完成实现：Docker 命令沙箱

核心文件：

- `src/mokioclaw/evals/sandbox.py`
- `evals/images/python/Dockerfile`
- `tests/evals/test_sandbox.py`

### 12.1 镜像

镜像名：

```text
mokioclaw-eval-python:3.13
```

Dockerfile 当前基于：

```dockerfile
FROM python:3.13-slim
RUN python -m pip install --no-cache-dir pytest==9.0.3
WORKDIR /workspace
ENTRYPOINT ["/bin/sh", "-lc"]
```

实施期间成功构建的镜像 ID：

```text
sha256:a41dd6cce4b646cad7cc4ed78c6c07873824f9864b1b7201229f8e572f8cc627
```

该 ID 是当时本机验证结果，不应假定其他机器或重新构建后仍一致。

### 12.2 容器限制

`DockerCommandExecutor` 每条命令创建一个临时容器，参数包括：

- `--rm`
- 唯一容器名 `mokioclaw-eval-<12 hex>`
- `--network none`
- `--cpus 1`
- `--memory 512m`
- `--pids-limit 128`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- `--read-only`
- `/tmp` 使用 `rw,noexec,nosuid,size=64m` tmpfs
- 使用宿主当前 UID:GID
- 只将当前任务 workspace 挂载到 `/workspace`
- 工作目录固定为 `/workspace`

容器没有通过 `-e` 接收宿主环境变量，因此 Provider 密钥不会被主动传入任务容器。

### 12.3 超时与输出

- 命令超时由 `subprocess.run(..., timeout=...)` 控制。
- 超时后执行 `docker rm -f <container_name>` 清理残留容器。
- 返回结构包含 `ok`、`timed_out`、`command`、`exit_code`、`stdout`、`stderr`、`duration_ms`。
- stdout/stderr 按 `max_output_chars` 截断。
- `image_id()` 在运行前检查镜像是否可用；缺失时抛出 `SandboxSetupError`。

### 12.4 已验证隔离属性

Docker 集成测试覆盖：

- 任务命令无法访问网络。
- 任务命令无法读取未挂载的任意宿主路径。
- 超时命令会触发容器回收。
- Docker 参数包含预期的资源与安全限制。

### 12.5 当前隔离局限

- `python:3.13-slim` 尚未使用 digest 固定，严格可复现性仍可加强。
- 当前镜像只预装 pytest，暂不支持复杂项目的完整工具链。
- `Policy.writable_paths` 已进入数据契约，但 Docker executor 当前只按整个 workspace 挂载，没有实现子路径级写权限。
- 当前是“每条命令一个容器”，不是“每个 Agent Run 一个持久容器”。
- 通用 CLI/TUI 仍默认使用宿主 Bash Harness。

---

## 13. 已完成实现：Patch 捕获与安全处理

核心文件：

- `src/mokioclaw/evals/patches.py`
- `tests/evals/test_grader.py`

`create_patch()` 当前流程：

1. 将 Agent workspace 复制为临时 `agent-export/`。
2. 将缺陷 baseline 复制为临时 `baseline-export/`。
3. 排除 `.mokioclaw`、`__pycache__`、`.pytest_cache` 等运行产物。
4. 使用 `git diff --no-index --binary` 生成二进制安全 Patch。
5. 将绝对临时目录前缀改写为标准 `a/`、`b/` Patch 路径。
6. 检查 `---`/`+++` header，拒绝绝对路径和包含 `..` 的路径。
7. 写入 `final.patch`。
8. 无论成功或失败，都清理两个 export 目录。

Patch 生成同样使用 `GIT_DIR=/dev/null`，防止外层仓库或 worktree 污染结果。

---

## 14. 已完成实现：独立隐藏 Grader

核心文件：

- `src/mokioclaw/evals/grader.py`
- `evals/graders/cases/mini_api/pagination_boundary/test_pagination_hidden.py`
- `tests/evals/test_grader.py`

### 14.1 评分顺序

`grade_case()` 严格按以下顺序执行：

1. **integrity**
   - 对 `protected_paths` 计算 SHA-256。
   - 比较缺陷 baseline 与 Agent workspace。
   - 若 Agent 修改受保护文件，立即失败，后续检查标记为 skipped。
2. **patch_apply**
   - 从缺陷 baseline 创建全新的 `grading/`。
   - 将 `final.patch` 应用到 grading workspace。
   - Patch 不可应用则终止后续评分。
3. **public_regression**
   - 在 Docker executor 中运行 Case 定义的公开验证命令。
   - 公开回归失败时不运行隐藏测试。
4. **hidden_tests**
   - 只有上述检查通过后，才将隐藏测试复制到 `grading/tests_hidden/`。
   - 在 Docker 中运行 `python -m pytest -q tests_hidden`。

当前成功判定是所有返回的 `GraderCheck.passed` 均为真。

### 14.2 信任边界

- 隐藏测试不复制到 Agent workspace。
- 隐藏测试不挂载到 Agent 的任务命令容器。
- Grader 只在 Worker 完成后运行。
- 隐藏测试输出不会回传到同一次 Agent 事件流。
- Agent 提交的是 Patch，而不是直接让 Grader信任其最终工作目录。

### 14.3 当前完整性局限

- 当前只对 Case 中显式声明的 `protected_paths` 做 SHA-256 比较。
- Case、mutation、reference patch、Grader 和 hidden tests 主要通过目录不暴露来保护，尚未建立统一的策略审计报告。
- `policy_blocked` 终态尚未由完整策略审计器产生。
- 尚未检查“无关大范围修改”或 Patch 语义相关性。

---

## 15. 已完成实现：Agent Adapter

核心文件：

- `src/mokioclaw/evals/adapters.py`
- `tests/evals/test_adapters.py`

### 15.1 统一接口

```python
class AgentAdapter(Protocol):
    def run(self, config: AgentRunConfig) -> RunArtifacts: ...
```

`RunArtifacts` 可记录：

- 原始事件列表。
- attempts。
- tool calls。
- tool errors。
- first-pass success。
- input/output tokens。
- compression count。
- trace path。

### 15.2 `MokioAgentAdapter`

真实适配器复用现有 `stream_agent_events()`，没有把 Eval 逻辑写入 LangGraph 节点。

它从事件流统计：

- `tool_call` 数量。
- 失败 `tool_result` 数量。
- `trace_summary` 中的工具调用、失败工具、token、压缩次数和 Trace 路径。
- graph update 中的 `attempts`。

当工具调用数超过 `max_tool_calls` 时抛出 `ToolBudgetExceeded`，并主动关闭事件生成器。

### 15.3 `ScriptedPatchAdapter`

当前包含三个基础设施专用脚本适配器：

- `apply-reference`
  - 不调用模型。
  - 对分页实现执行确定性 marker 替换。
  - 用于验证工作区、Patch、Docker、Grader 和报告全链路。
- `sleeping-script`
  - 故意休眠，用于测试 Agent 总超时。
- `over-budget-script`
  - 构造 41 次工具调用，用于测试工具预算耗尽。

`apply-reference` 只能作为基础设施 smoke test，不能计入 Benchmark。

---

## 16. 已完成实现：可终止 Worker 与 Eval Runner

核心文件：

- `src/mokioclaw/evals/worker.py`
- `src/mokioclaw/evals/runner.py`
- `tests/evals/test_runner.py`

### 16.1 Worker 进程

Runner 不在主进程内直接运行 Agent，而是启动：

```bash
python -m mokioclaw.evals.worker \
  --config <worker-config.json> \
  --adapter <adapter>
```

这样可以用外层 subprocess timeout 终止卡死 Agent。

Worker 退出码约定：

- `0`：adapter 完成并写出 artifacts。
- `2`：工具调用预算耗尽。
- `3`：配置、adapter 或运行异常，记录为 setup failure。

Worker 将结果写到：

```text
run-artifacts.json
```

### 16.2 Worker 环境

Runner 构造最小环境：

- 保留 `PATH`。
- 保留 `LANG`。
- 设置项目 `src` 到 `PYTHONPATH`。
- 仅在父进程存在时，将 `API_KEY`、`MODEL`、`BASE_URL` 传给 Worker。

Worker config 文件不写 API Key，只记录脱敏后的 `base_url_host`。

### 16.3 Runner 主流程

`EvalRunner.run_case()` 当前流程：

1. 加载 Case YAML。
2. 创建唯一 `run_id`。
3. 准备缺陷 baseline 和 Agent workspace。
4. 从当前环境生成 `AgentRunConfig`。
5. 写入 `worker-config.json`。
6. 以 subprocess 启动 Worker。
7. 强制执行 Agent wall-clock timeout。
8. 解析 `run-artifacts.json`。
9. 将 Worker 状态映射为 Eval 状态。
10. Worker 成功后生成 `final.patch`。
11. 检查 Docker 镜像并记录 image ID。
12. 在独立 grading workspace 执行 Grader。
13. 汇总为 `CaseResult`。

### 16.4 当前状态映射

- Worker 正常完成：暂时映射到内部 `RunStatus.PASSED`，随后由 Grader 决定最终 passed/failed。
- subprocess 超时：`timed_out`。
- 工具超预算：`budget_exhausted`。
- 配置或 Worker 异常：`setup_failed`。
- Grader 检查失败：`failed`。

当前 `failure_stage` 主要使用 `setup`、`worker`、`sandbox`、`grader`，尚未达到设计中的 planning/retrieval/editing/execution/verification/policy/budget 精细归因。

---

## 17. 已完成实现：报告与 CLI

核心文件：

- `src/mokioclaw/evals/report.py`
- `src/mokioclaw/evals/cli.py`
- `tests/evals/test_report.py`
- `tests/evals/test_cli.py`
- `docs/evaluation.md`
- `docs/evaluation_cn.md`（新建、未提交）

### 17.1 CLI 入口

`pyproject.toml` 已注册：

```toml
[project.scripts]
mokioclaw = "mokioclaw.cli.app:app"
mokioclaw-eval = "mokioclaw.evals.cli:app"
```

评测命令：

```bash
mokioclaw-eval run \
  --case <case.yaml> \
  --adapter <adapter> \
  --output <report-dir>
```

默认 adapter 为 `multi-agent`，默认输出目录为 `evals/reports/latest`。

运行失败时，CLI 仍会先写报告，再以非零退出码结束。

### 17.2 报告文件

每次 CLI 调用生成：

- `results.json`
- `summary.json`
- `report.md`

写文件使用同目录临时文件加 `Path.replace()`，避免生成半写入报告。

### 17.3 当前 summary 指标

单 Run summary 继续包含：

- `runs`
- `passed`
- `task_success_rate`
- `first_pass_success_rate`
- `average_tool_calls`
- `average_latency_ms`

此后已经补充 Batch Runner、多 Case/多重复实验聚合、按架构与资源格报告，以及 snapshot analysis 的 per-case/pooled/Q1/Q2 机械判读。当前仍未完成的是可靠 cost 汇总、跨仓库比较层和统计推断；Rich 阶段只按探索性口径报告计数与方向。

---

## 18. 当前测试覆盖

本轮新增或扩展的测试覆盖以下方面：

### 18.1 Case 和类型

- YAML 正常解析。
- 默认预算和策略。
- 缺少必填字段。
- 空公开验证命令。
- 非法网络策略。
- 非正数预算。
- 结果状态和序列化结构。

### 18.2 Workspace 和 Fixture

- run root 不覆盖既有目录。
- template、mutation 缺失时失败。
- baseline/agent 相互隔离。
- mutation 正确应用。
- public/hidden/reference 三态。

### 18.3 命令执行注入

- Runtime 接收 executor。
- Bash 前台命令委托 executor。
- 未注入时保留原行为。
- Eval Runtime 禁用网络工具。

### 18.4 Docker Sandbox

- Docker 参数集合。
- 网络禁用。
- 只挂载任务 workspace。
- 环境变量不透传。
- stdout/stderr 截断。
- 超时后强制清理容器。
- 镜像缺失错误。
- 真实 Docker 隔离测试。

### 18.5 Patch 和 Grader

- 忽略运行时垃圾目录。
- 生成可应用 Patch。
- 拒绝危险 Patch header。
- 公开测试保护。
- Patch 应用失败短路。
- 公开回归失败短路。
- 隐藏测试只在最后运行。
- reference patch 通过完整评分。

### 18.6 Adapter、Worker 和 Runner

- 禁网、deny approval、trace on 等固定策略。
- 事件指标采集。
- Worker 配置不含秘密与隐藏资源路径。
- Agent timeout。
- 工具调用预算。
- setup failure。
- 成功链路。

### 18.7 Report 和 CLI

- dataclass、Enum、Path 的稳定 JSON 化。
- JSON 和 Markdown 文件生成。
- 原子写入。
- CLI 成功与失败退出码。
- 输出报告路径。

### 18.8 主项目回归

- TUI 确定性事件渲染。
- Graph 工具策略。
- Runtime 参数透传。
- Bash executor 委托。
- 原有 Agent、工具、Checkpoint、Trace、Session 等回归测试。

---

## 19. 已完成验证证据

在功能分支完成后、合并到 `master` 前后均执行过验证。最近一次合并后完整验证结果：

```text
163 passed in 20.00s
```

对应命令：

```bash
timeout 180 /data/liyifan24/envs/codeagent/bin/python -m pytest -q
```

Ruff 结果：

```text
All checks passed!
```

对应命令：

```bash
/data/liyifan24/envs/codeagent/bin/ruff check .
```

锁文件检查也已通过：

```bash
uv lock --check --offline \
  --python /data/liyifan24/envs/codeagent/bin/python
```

纵向闭环的 `apply-reference` CLI smoke 已在实施期间运行成功，生成过：

```text
/tmp/mokioclaw-eval-vertical-slice/report.md
```

该 `/tmp` 产物是临时验证文件，不应被视为仓库内长期报告。

---

## 20. 当前可运行与可演示内容

### 20.1 原有 Rich CLI

```bash
cd /data/liyifan24/MokioAgent
/data/liyifan24/envs/codeagent/bin/mokioclaw \
  "检查一个代码仓库问题并完成修改与验证"
```

需要配置模型 Provider。涉及 WebSearch 时还需要 Tavily 配置。

### 20.2 Textual TUI

```bash
cd /data/liyifan24/MokioAgent
/data/liyifan24/envs/codeagent/bin/mokioclaw tui
```

TUI 可以展示：

- 多轮 Session。
- Planner 和 Agent 事件。
- Tool call/result。
- HITL 审批。
- TODO 状态。
- Checkpoint 与 Trace 路径。
- 同一 workspace 的后续任务。

### 20.3 离线 Eval 基础设施 smoke

若镜像尚未构建：

```bash
docker build \
  -t mokioclaw-eval-python:3.13 \
  evals/images/python
```

运行不依赖模型的确定性闭环：

```bash
cd /data/liyifan24/MokioAgent
/data/liyifan24/envs/codeagent/bin/mokioclaw-eval run \
  --case evals/cases/mini-api-pagination-boundary-01.yaml \
  --adapter apply-reference \
  --output /tmp/mokioclaw-eval-demo
```

预期输出：

```text
/tmp/mokioclaw-eval-demo/results.json
/tmp/mokioclaw-eval-demo/summary.json
/tmp/mokioclaw-eval-demo/report.md
```

这条命令验证基础设施，但不验证 Agent 智能。

### 20.4 真实 Multi-Agent Eval

需要在启动进程环境中提供：

- `API_KEY`
- `MODEL`
- `BASE_URL`

然后运行：

```bash
cd /data/liyifan24/MokioAgent
/data/liyifan24/envs/codeagent/bin/mokioclaw-eval run \
  --case evals/cases/mini-api-pagination-boundary-01.yaml \
  --adapter multi-agent \
  --output evals/reports/multi-agent-smoke
```

安全要求：不要把密钥写进 Case、命令参数、报告、提交或任务容器。

---

## 21. 当前真实 Multi-Agent Smoke 状态

仓库本地存在一个被 `.gitignore` 忽略的运行报告：

```text
evals/reports/multi-agent-smoke/
```

该次运行没有进入 Agent，实际结果为：

```text
status: setup_failed
failure_stage: setup
failure_reason: ValueError: MODEL, BASE_URL, and API_KEY are required for multi-agent evaluation
tool_calls: 0
attempts: 0
```

因此当前只能声称：

- 真实 Multi-Agent Eval 入口已经实现。
- 缺少 Provider 环境变量时能安全失败并生成结构化报告。

当前不能声称：

- 真实 Multi-Agent 已成功解决分页 Case。
- 当前架构取得任何 Task Success Rate。
- Multi-Agent 比其他架构更有效。

一个值得下一会话检查的细节：普通 Agent 入口会调用 `load_dotenv()`，但 `EvalRunner._run_config()` 在启动 Worker 前直接读取父进程 `os.environ`。如果只把 Provider 配置放在 `.env`、没有导出到当前 shell，Eval CLI 可能仍判定变量缺失。后续可以选择：

1. 文档明确要求先导出变量；或
2. 在 Eval CLI/Runner 的可信宿主侧安全调用 `load_dotenv()`，并为此补测试。

不要在诊断时打印密钥值。

---

## 22. 第一阶段计划完成度

第一阶段纵向切片实施计划包含 9 个 Task，当前均已实现：

| Task | 内容 | 状态 |
|---|---|---|
| 1 | Repository hygiene、依赖、测试工具基线 | 已完成 |
| 2 | 确定性 TUI 测试与 CI | 已完成 |
| 3 | Eval 类型契约与 YAML Loader | 已完成 |
| 4 | 隔离 Workspace 与首个 mutation fixture | 已完成 |
| 5 | 可注入命令执行接口 | 已完成 |
| 6 | 离线 Eval 工具策略与 Docker executor | 已完成 |
| 7 | 独立隐藏 Grader 与 Patch integrity | 已完成 |
| 8 | Agent Adapter、可终止 Worker、预算 | 已完成 |
| 9 | JSON/Markdown 报告与一条命令闭环 | 已完成 |

第一阶段 Milestone Gate 的状态：

| Gate | 状态 | 证据/说明 |
|---|---|---|
| 完整 pytest 可收尾 | 已通过 | 本交接文档创建时复验：`163 passed in 20.00s` |
| Ruff 通过 | 已通过 | `All checks passed!` |
| Docker 禁网与宿主路径隔离 | 已通过 | Docker 集成测试包含在完整套件 |
| Worker config 不含秘密/隐藏资源路径 | 已通过 | 单测覆盖 |
| mutation 公开通过、隐藏失败 | 已通过 | fixture/grader 测试覆盖 |
| apply-reference 生成 passing CaseResult 与报告 | 已通过 | CLI smoke 已运行 |
| `git diff --check` | 实施完成时通过 | 新文档新增后需重新检查 |
| 不误暂存用户文件 | 已遵守 | 当前未执行 `git add` |

---

## 23. 完整升级设计的完成度

### 23.1 已完成

- 安全、依赖、测试和最小 CI 基线；
- 六个核心自建 Case 及其 clean/mutated/reference 三态验证；
- ReAct、Plan–Execute、Multi-Agent 三种架构 Adapter；
- Batch Runner、断点续跑、批次 identity 和重复实验；
- 公开资源与隐藏 Grader 的双信任区；
- 离线 Docker 工具平面、Worker 总超时和工具调用预算；
- Patch 捕获、独立 grading workspace 和公开/隐藏验证；
- Protected manifest 的文件、目录、absent-path 和 symlink 语义；
- 逐 Case 镜像、fingerprint schema v3 和同批同镜像公平性检查；
- last-stage telemetry、预注册 schedule 和 snapshot analysis；
- Rich v14.3.4 固定开源快照、许可证、PROVENANCE、hash-locked 镜像；
- 两个 Rich Case 的公开反馈、repro、隐藏行为验证和 Case 设计 checklist；
- 四格资源矩阵的 R1/R2/R3 共 72 次真实 Agent 运行；
- per-case/pooled 状态、Q1/Q2 机械复算和阶段报告；
- 合并后全项目验证：`291 passed, 2 skipped`。

### 23.2 局部实现

- **遥测**：72 次 Rich 运行中仅 21 次具有 token telemetry；`estimated_cost` 全部不可用；
- **Provider 稳定性**：22 次 worker-stage 504 已能识别并留账，但仍需要更稳定的准入、重试和分类机制；
- **跨仓库外部效度**：真实开源快照能力已完成，但目前只有 Rich 一个仓库；
- **报告稳定性**：机器 JSON 可复现，人读报告仍会因绝对根路径变化而改变文本哈希；
- **Symlink 实机覆盖**：语义和测试已实现，但当前 Windows 主机无法创建 symlink，因此两项测试跳过；
- **策略审计**：protected manifest 已加强，但仍没有统一的 policy audit 总报告；
- **对外叙事**：实验报告已存在，README 图表和主叙事尚未更新。

### 23.3 仅设计、尚未实现

- 第二个开源仓库固定快照和跨仓库方向性复验；
- Click 候选仓库的具体 commit、镜像和 Case 设计；
- Provider/telemetry 稳定性准入与可靠成本记录；
- Grep/BM25/Hybrid Retrieval 对比。
- AST/Symbol Index。
- Embedding/Rerank。
- README 的 Repository Maintenance Agent 主叙事改造。
- README 中由报告生成的真实实验数字。
- 通用 CLI/TUI Docker Sandbox。
- MCP Client 和标准 MCP 工具接入。
- 任务型 Skills。
- FastAPI `POST /tasks`、状态查询和 SSE 事件接口。
- 多模型兼容性抽查。
- 最终 3 分钟 Demo 和求职包装。

---

## 24. 原始两周指南中尚未执行的事项

原始附件与后续 Eval-first 设计存在优先级调整。以下原指南内容没有在本轮纵向切片中实现：

### 24.1 Day 2 Bash 后台任务增强

原指南提出：

- `BashJobListTool`
- `BashJobStopTool`
- 后台任务启动、查询、停止、回收完整测试
- 修正危险命令检测对 Python `format()` 的误伤

这些不属于当前纵向 Eval 计划，不能标记为已完成。

### 24.2 Day 3 主叙事与 Demo 改造

尚未完成：

- 删除 `graph/nodes.py` 中 Amiya 特例。
- `_is_amiya_task()` 当前仍存在。
- 尚未创建三个通用 `examples/tasks/` 场景。
- README 首屏仍是教学型 Mini CodeAgent 叙事。
- README 当前仍以阿米娅 HTML 为标志性演示。

### 24.3 Repo Retrieval

尚未创建：

```text
src/mokioclaw/retrieval/
├── models.py
├── indexer.py
├── symbol_index.py
├── lexical.py
├── semantic.py
├── reranker.py
└── tool.py
```

当前 `AgentRunConfig.retrieval` 固定记录为 `grep`，但没有可切换 Retrieval 实现。

### 24.4 MCP、Skills、FastAPI/SSE

均未进入当前实现。不要因为原 README 描述未来“Skill/Claw”阶段就误认为它们已经完成。

---

## 25. 当前已知技术限制与潜在改进点

### 25.1 遥测完整性和成本记录不足

Runner、checkpoint 和聚合链路已经能够保留工具调用、attempt、last-stage 及部分 token 信息，但 Rich 批次只有 21/72 行具有 token telemetry，72/72 的 `estimated_cost` 均为 `null`。

下一阶段应先定义 telemetry 可用率、unavailable 原因和 provider 支持边界，再决定成本字段如何进入报告。不得使用不完整 token 记录推测真实账单。

### 25.2 Provider 失败仍占较高比例

Rich 批次 72 行中有 22 行为 worker-stage provider 504，其中 19 行发生在零工具调用时。当前已经能够区分 provider 中断与 Agent 任务失败，并保留 manifest 证据，但下一阶段仍需把预检、有限重试、批次停止条件和异常分类机械化。

任何增强都只能记录 requested architecture、不敏感的 model 标识和经过脱敏的 provider host；绝不能记录 API Key 或含凭据/query 的完整 URL。

### 25.3 `.env` 加载一致性

Eval Runner 在检查环境变量时可能早于普通 Agent 的 `load_dotenv()`。需要统一用户体验，并用测试保证不会把秘密写入 Worker config/report。

### 25.4 工具预算只在事件边界检查

当前 Adapter 在每个事件到达后统计工具调用。如果单次工具调用本身长时间卡住，主要依赖 Worker 总超时和命令 executor 超时，而不是预算检查。

### 25.5 Attempt/First-pass 语义

`attempts` 来源依赖 graph update 是否包含对应字段。脚本 adapter 默认 attempts 为 0。后续架构消融前需要统一“第一次完成”的定义和计数起点。

### 25.6 Grader 输出诊断较少

当前 `GraderCheck.detail` 只记录简短通过/失败描述，没有把容器 stdout/stderr 保存为 artifact。后续失败审计需要增加命令日志路径，同时避免把隐藏断言内容反馈给 Agent。

### 25.7 Patch 相关性与禁止路径

目前有路径 header 安全检查和公开测试保护，但尚未：

- 限制最大 Patch 大小。
- 限制允许修改的文件类型。
- 检测大范围无关修改。
- 对 Case/Grader 等宿主目录做统一策略审计报告。

### 25.8 报告尚缺跨仓库比较层

单 Run、单批次聚合、四格 snapshot analysis 和 per-case/pooled 报告均已实现。当前缺口是跨仓库比较：下一阶段需要在保持每个仓库独立身份、阈值和判读的前提下，生成方向一致、仓库特异和仍不确定三类对照，不应直接把不同仓库的 runs 混入同一个 pooled 计数。

### 25.9 仓库镜像仍需逐项目设计

Per-case image 和 Rich 的 hash-locked 离线镜像已经证明仓库专用镜像路线可行，但每个新开源仓库仍需独立确定依赖锁、source resolution、测试时长和裁剪策略。不能在任务容器默认禁网的同时假设可以临时 `pip install`，也不能复用 Rich 镜像冒充通用环境。

### 25.10 真实 Agent 证据仍缺跨仓库复验

真实 Agent 成功证据已经存在：Rich 批次有 17/72 passed，并完成了三架构、四格和三轮重复。当前缺口不再是“是否能跑通真实 Agent”，而是这些资源信号能否在第二个开源仓库上复现，以及 provider 504 和 telemetry 缺失是否会妨碍解释。

---

## 26. 推荐的后续实施顺序

### 已完成阶段

1. Eval 纵向切片与可信评分底座；
2. 六个核心自建 Case；
3. ReAct、Plan–Execute、Multi-Agent 架构消融；
4. 数据驱动资源校准；
5. Rich 固定开源快照的 72-run 迁移性探索与验收。

### 下一阶段：多项目快照扩展与评测稳定性强化

推荐顺序：

1. 先设计 provider 504、telemetry 和稳定报告路径的准入规则；
2. 固定 Click 源码、许可证、归档 hash、裁剪和离线镜像；
3. 设计一个或两个 Click Case，并完成零 Agent-run 验收；
4. 为第二仓库建立独立 schedule、fingerprint、批次根和分析产物；
5. 执行小规模 provider/telemetry smoke；
6. 经用户批准后执行 R1，并按预注册 gate 决定是否补满 R2/R3；
7. 分别报告 Rich 和 Click，再形成跨仓库方向性比较；
8. 跨仓库证据形成后，再决定 README 图表、Demo 和产品化工作的优先级。

Click 是预注册首选，HTTPie 仅作为 Click 无法满足离线、确定性和资源准入条件时的备选。第二仓库必须另写设计和实施计划，不能追加到 Rich 的 72-run 批次。

---

## 27. 下一会话建议优先任务

推荐下一会话先完成下一阶段的设计，不直接启动 Click 真实 runs：

> 为“多项目快照扩展与评测稳定性强化阶段”明确 provider/telemetry 准入、Click 快照选择、Case 数量、36/72-run 预算和停止条件。

设计成功标准：

1. Rich 阶段 22 次 provider 504 和 51 次 token telemetry 缺失均有明确处置目标；
2. Click 的候选 commit、license、测试包络和依赖风险得到只读核验；
3. 一个或两个 Case 的行为面、公开反馈和隐藏契约可以在真实运行前机械验证；
4. 新批次与 Rich 批次在 identity、阈值、目录和结论上完全隔离；
5. R1 用户 gate、费用/遥测报告、停止条件和 R2/R3 准入在计划中预先冻结；
6. 跨仓库比较只比较方向和分歧，不混合原始 pooled 计数；
7. README、Retrieval 和服务化不进入该阶段核心范围。

---

## 28. 后续开发的安全与协作约束

新会话必须继续遵守：

1. 不读取或输出 `.env` 的秘密值。
2. 不把 API Key 写入 Case、Worker config、Trace、报告或容器参数。
3. 不擅自修改、暂存或提交用户个人文档。
4. 不擅自覆盖 `.env.example`。
5. 运行 Git 操作前先检查脏工作区和重叠路径。
6. 新功能使用独立 `codex/` 分支和 worktree（如继续采用该工作流）。
7. 每个 Case 使用 clean/mutated/reference 三态测试。
8. 隐藏测试永远不进入 Agent workspace。
9. 不把 `apply-reference` 结果写成 Agent Benchmark 成绩。
10. 不在没有重复实验时宣称架构优劣。
11. 不在数据证明检索瓶颈前直接投入复杂 Hybrid Retrieval。
12. 不将 Eval 专用 Docker 隔离误述为普通 CLI/TUI 已全面沙箱化。
13. 不将本地 CI 配置误述为远端 CI 已通过。

---

## 29. 关键源码索引

| 文件 | 当前职责 |
|---|---|
| `src/mokioclaw/core/agent.py` | Agent/Session 事件流入口；接收 executor 和网络策略 |
| `src/mokioclaw/core/state.py` | RuntimeState；保存命令执行器和网络开关 |
| `src/mokioclaw/core/execution.py` | `CommandExecutor` 协议 |
| `src/mokioclaw/tools/bash_tool.py` | 默认宿主 Bash Harness；可委托注入 executor |
| `src/mokioclaw/tools/registry.py` | 根据 Runtime 策略构造工具集合 |
| `src/mokioclaw/graph/nodes.py` | Planner/Verifier/上下文节点；Eval 模式过滤 SearchAgent |
| `src/mokioclaw/evals/models.py` | Eval 数据契约 |
| `src/mokioclaw/evals/cases.py` | YAML 加载与验证 |
| `src/mokioclaw/evals/workspace.py` | template 复制、mutation 注入、baseline/agent 隔离 |
| `src/mokioclaw/evals/sandbox.py` | Docker 命令执行器和镜像检查 |
| `src/mokioclaw/evals/patches.py` | Agent 变更导出与安全 Patch 生成 |
| `src/mokioclaw/evals/grader.py` | integrity、Patch、公开回归、隐藏测试评分 |
| `src/mokioclaw/evals/adapters.py` | AgentAdapter、真实 Adapter、脚本 Adapter、指标采集 |
| `src/mokioclaw/evals/worker.py` | 子进程执行入口与 artifact 落盘 |
| `src/mokioclaw/evals/runner.py` | 单 Case 编排、超时、预算、评分和结果构造 |
| `src/mokioclaw/evals/report.py` | 单 Run JSON/Markdown 报告 |
| `src/mokioclaw/evals/cli.py` | `mokioclaw-eval run` 命令 |
| `evals/cases/mini-api-pagination-boundary-01.yaml` | 首个 Case 配置 |
| `evals/images/python/Dockerfile` | Eval Python 沙箱镜像 |
| `evals/repos/templates/mini_api/` | 首个本地仓库模板 |
| `evals/repos/mutations/` | 缺陷注入 Patch |
| `evals/repos/reference-patches/` | 可信 Case 验证补丁，不提供给 Agent |
| `evals/graders/cases/` | Agent 不可见的 Case 隐藏测试 |
| `tests/evals/` | Eval 基础设施单元/集成测试 |
| `.github/workflows/ci.yml` | 本地定义的 GitHub Actions CI |
| `docs/evaluation.md` | 英文运行说明 |
| `docs/evaluation_cn.md` | 中文运行说明，当前未提交 |

---

## 30. 常用验证命令

### 30.1 Git 与环境

```powershell
Set-Location 'D:\MokioAgent\MokioAgent'
git status -sb
git log --oneline --decorate -15
& 'D:\envs\codeagent\Scripts\python.exe' --version
$env:PYTHONPATH = (Resolve-Path 'src').Path
& 'D:\envs\codeagent\Scripts\python.exe' -c 'import pathlib, mokioclaw; print(pathlib.Path(mokioclaw.__file__).resolve())'
```

### 30.2 完整测试与 lint

```powershell
Set-Location 'D:\MokioAgent\MokioAgent'
$env:PYTHONPATH = (Resolve-Path 'src').Path
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest -q --basetemp='D:/MokioAgent/pytest-mokioclaw-current'
& 'D:\envs\codeagent\Scripts\python.exe' -m ruff check .
git diff --check
```

完整 pytest 包含 Docker 集成测试，需要访问本机 Docker daemon。

### 30.3 Docker 镜像

```powershell
Set-Location 'D:\MokioAgent\MokioAgent'
docker build -t mokioclaw-eval-python:3.13 evals/images/python
docker image inspect mokioclaw-eval-python:3.13 --format '{{.Id}}'
docker image inspect mokioclaw-eval-rich:14.3.4 --format '{{.Id}}'
```

### 30.4 快照分析复算

```powershell
Set-Location 'D:\MokioAgent\MokioAgent'
$env:PYTHONPATH = (Resolve-Path 'src').Path
& 'D:\envs\codeagent\Scripts\python.exe' -m mokioclaw.evals.snapshot_analysis --root 'evals/reports/snapshots-20260920'
Get-FileHash -Algorithm SHA256 `
  'evals/reports/snapshots-20260920/analysis/thresholds.json', `
  'evals/reports/snapshots-20260920/analysis/per-case.json', `
  'evals/reports/snapshots-20260920/analysis/pooled.json'
```

### 30.5 查看报告

```powershell
Get-Content -LiteralPath 'docs\MOKIOCLAW_OPENSOURCE_SNAPSHOT_PHASE_SUMMARY_2026-09-21.md'
Get-Content -LiteralPath 'docs\AGENT_OPENSOURCE_SNAPSHOTS_REPORT_2026-09-20.md'
Get-Content -LiteralPath 'evals\reports\snapshots-20260920\analysis\report.md'
```

---

## 31. 新会话可直接复制的提示词

```text
当前项目位于 D:\MokioAgent\MokioAgent，Python 环境位于
D:\envs\codeagent。

请先完整阅读：
1. docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md
2. docs/MOKIOCLAW_OPENSOURCE_SNAPSHOT_PHASE_SUMMARY_2026-09-21.md
3. docs/AGENT_OPENSOURCE_SNAPSHOTS_REPORT_2026-09-20.md
4. docs/superpowers/specs/2026-09-20-mokioclaw-opensource-snapshots-design.md
5. docs/superpowers/plans/2026-09-20-mokioclaw-opensource-snapshots.md

当前 main HEAD 应为 2c68a12。Rich v14.3.4 的两个固定 Case、三架构、
四资源格、三轮共 72 次真实 Agent 运行已经完成；机械分析状态为 complete，
合并后全项目测试为 291 passed、2 skipped。

原始实验产物位于 evals/reports/snapshots-20260920/，属于本地 ignored 内容。
不要删除、覆盖或把 provider 504 改写成 Agent 任务失败。

开始前请：
- 运行 git status -sb，并检查 ignored 内容；
- 显式让 PYTHONPATH 指向当前 checkout 的 src；
- 使用独立 basetemp 运行完整 pytest；
- 不要擅自 git add/commit/push；
- 不要读取、打印或复制 .env 的秘密值；
- 不要把 fixture red-green 当成 Agent 成绩。

下一步优先目标：为“多项目快照扩展与评测稳定性强化阶段”编写独立设计，
先明确 provider/telemetry 准入，再以 Click 为第二仓库首选。不要直接启动真实 runs；
设计和实施计划审阅通过后，才进入 R1 用户 gate。
```

---

## 32. 最终交接结论

MokioClaw 已经从“建立不会自欺的最小 Eval 底座”推进到“能够对固定开源仓库执行可复现探索性评测”：

- Case、快照、镜像和实验身份可以固定；
- Agent 可见资源与隐藏评分资源保持分离；
- 三种架构能在相同任务、镜像和资源格下运行；
- 公开反馈、隐藏行为和 protected manifest 共同约束解题边界；
- R1/R2/R3 的执行顺序、失败账目和阈值可以审计；
- 72 次运行可以从 manifest 机械复算到逐 Case、逐格、Q1/Q2 和人读报告；
- 失败、超时、预算耗尽和 provider 504 均保留为数据，而不是被择优删除。

当前证据仍只覆盖 Rich 两个 Case，因此下一阶段的核心是：先提高 provider/遥测稳定性，再用 Click 建立第二个独立快照实验，判断 Rich 阶段的资源信号是可迁移模式、仓库特异模式，还是仍需更多证据。完整范围和准入条件见 `docs/MOKIOCLAW_OPENSOURCE_SNAPSHOT_PHASE_SUMMARY_2026-09-21.md`。

---

## 33. 2026-09-22 多项目快照稳定性 S0 离线冻结

### 33.1 授权与边界

已按批准的 `2026-09-22-mokioclaw-multi-project-snapshots-stability.md` 在当前 `main` checkout 完成 Tasks 1–12 的离线实施。执行期间未创建 worktree，未提交、未 push、未修改远端，未下载或 vendor Click，未构建 Docker image，未调用外部 provider，未执行真实 Agent run，也未运行 G1/G2/G3。`HEAD` 与 `origin/main` 均保持：

```text
2c68a12fc49940101ea56e8ac967d6558e74109e
```

Task 13 是下一授权边界；S0 通过不等于 G1，也不授权任何网络、Docker build、provider smoke 或真实 Agent run。

### 33.2 已实现的离线基础设施

- 冻结并严格校验 `resource-analysis-v1`，包含两 Case/单 Case 分支、Q1/Q2、provider sensitivity 和 canonical output 规则；
- provider failure 使用结构化 kind/phase，安全原因不携带 endpoint、query、header 或 payload；
- call/transport journal 原子落盘，支持并发 call index、临时文件隔离和 token coverage 恢复；
- OpenAI transport retry 固定为零，三种 Agent adapter 的 token/call 计数以 journal 为准；
- worker 在 adapter 启动前写最小 artifact，并保留 scheduled run、worker attempt、Agent attempt 五层身份；
- worker-attempt ledger append-only，每个预注册槽位最多一次正式 launch，停止后的槽位显式写 `not_started`；
- experiment fingerprint v4 分离五域 identity、非 hash-critical metadata 和 per-attempt 字段，每次 launch 前复核；
- 自适应 Case 门固定 36/72 预算，seed `20260922` 的 schedule 具有最终 schedule hash 派生的稳定 slot ID；
- stop controller 实现即时失败类、连续/轮内 transport 阈值、missing usage、transport 不可审计和 integrity drift 硬停止；
- G2/G3 gate-safe 摘要只输出聚合完整性/稳定性字段，并递归拒绝 Case、架构、资源格和效果方向泄漏；
- Click analyzer 实现两 Case正式判读、单 Case禁用正式标签、按 architecture 独立的 5/6 provider 门和有界保守补全枚举；
- analyzer 的 hash-critical JSON/Markdown 对绝对路径、时区和 locale 稳定，运行时 metadata 只进入独立 audit；
- Rich 只读 legacy sidecar 与 Rich–Click 三维 comparator 已实现；comparator 不读取 raw manifest，也不跨仓库合并 pooled counts。

### 33.3 S0 验证证据

所有 pytest 均使用 `D:\envs\codeagent\Scripts\python.exe`、显式 `PYTHONPATH=src` 和独立 `--basetemp`。

```text
pytest -m "not docker" -q
421 passed, 2 skipped, 25 deselected in 59.34s

ruff check src tests
All checks passed!

git diff --check
通过

determinism + sanitized provider reason focused verification
3 passed in 0.12s

新增稳定 artifact secret-pattern scan
0 matches
```

两个 skip 都是 Windows 当前环境不支持测试所需 symlink 创建的 capability skips：`tests/evals/test_grader.py:204` 与 `:219`。25 个 deselected 测试均带 `docker` marker；本次授权明确禁止 Docker build/运行，因此未执行。

### 33.4 Rich 只读审计结果

真实 Rich 根只新增 ignored sidecar `analysis/rich-legacy-audit.json`，未重算或改写原分析：

```text
final manifest rows                  72
setup_failed                         22
worker-stage provider 504 coverage   22/22
tool-call distribution               0×19, 13×1, 18×1, 38×1
token telemetry                      full=21, unavailable=51
audit_completeness                    limited
historical_worker_attempt_completeness limited
```

三份冻结分析 SHA-256 在 sidecar 生成前后均精确匹配：

```text
thresholds.json  B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB
per-case.json    167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB
pooled.json      6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2
```

### 33.5 精确变更文件

实现与测试工作树包含以下文件；另有明确列出的 ignored 审计/执行账本文件。不存在 README、MCP、FastAPI/SSE、服务化、BM25、Embedding、Rerank 或 AST Index 变更。

```text
evals/specs/resource-analysis-v1.json
src/mokioclaw/evals/adapters.py
src/mokioclaw/evals/analysis_spec.py
src/mokioclaw/evals/batch.py
src/mokioclaw/evals/cli.py
src/mokioclaw/evals/cross_repo_comparison.py
src/mokioclaw/evals/experiment_identity.py
src/mokioclaw/evals/models.py
src/mokioclaw/evals/plan_execute_adapter.py
src/mokioclaw/evals/protocol.py
src/mokioclaw/evals/provider_failures.py
src/mokioclaw/evals/react_adapter.py
src/mokioclaw/evals/report.py
src/mokioclaw/evals/rich_legacy_audit.py
src/mokioclaw/evals/runner.py
src/mokioclaw/evals/snapshot_analysis.py
src/mokioclaw/evals/snapshot_schedule.py
src/mokioclaw/evals/telemetry.py
src/mokioclaw/evals/worker.py
src/mokioclaw/evals/worker_ledger.py
src/mokioclaw/providers/call_journal.py
src/mokioclaw/providers/openai_provider.py
src/mokioclaw/providers/usage.py
tests/evals/fixtures/snapshot-analysis/q1-sensitive.json
tests/evals/fixtures/snapshot-analysis/q2-sensitive.json
tests/evals/fixtures/snapshot-analysis/qualified-stable.json
tests/evals/test_adapters.py
tests/evals/test_analysis_spec.py
tests/evals/test_batch.py
tests/evals/test_cross_repo_comparison.py
tests/evals/test_experiment_identity.py
tests/evals/test_protocol.py
tests/evals/test_provider_failures.py
tests/evals/test_report.py
tests/evals/test_rich_legacy_audit.py
tests/evals/test_runner.py
tests/evals/test_snapshot_analysis.py
tests/evals/test_snapshot_schedule.py
tests/evals/test_telemetry.py
tests/evals/test_worker_ledger.py
tests/providers/test_call_journal.py
tests/providers/test_openai_provider.py
tests/test_usage.py
docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md

ignored/local-only:
docs/superpowers/plans/2026-09-22-mokioclaw-multi-project-snapshots-stability.md
.superpowers/sdd/2026-09-22-mokioclaw-multi-project-snapshots-stability/plan-path
.superpowers/sdd/2026-09-22-mokioclaw-multi-project-snapshots-stability/progress.md
evals/reports/snapshots-20260920/analysis/rich-legacy-audit.json
```

### 33.6 尚未解决且必须保留的风险

- Click 8.4.2 尚未下载、vendor 或冻结；其 license、source archive、commit、依赖锁、Dockerfile 与 image digest 尚无 S1 证据；
- Click 候选 Case 尚未执行零 Agent-run 准入，最终 36/72 分支尚未冻结；
- provider smoke、真实 R1/R2/R3、G1/G2/G3 均未授权且未运行；
- 当前 comparator 只能等待未来已完成且 hash-verified 的 Click 分析输入；没有 Click 成绩，也没有跨仓库方向结论；
- Rich 历史 worker attempt 证据永久为 `limited`，不得提升为 strict-audit-comparable；
- 本次测试没有把 fixture red-green、reference patch、zero-agent 验收或 provider failure 描述为 Agent 成绩。

S0 离线基建冻结具备验证证据；整体“多项目快照扩展与评测稳定性强化阶段”尚未完成，必须停在 Task 13 前等待新的明确授权。

---

## 34. 2026-09-22 Click 8.4.2 快照与镜像 S1 准入

### 34.1 范围与身份

Task 13 已在用户单独授权下完成；仅下载并核验 Click 8.4.2、构建离线镜像和运行 zero-agent upstream acceptance。没有执行 Task 14、provider 调用、真实 Agent run 或 G1/G2/G3，也没有 commit、push 或远端修改。

```text
annotated tag object  c6b2d71ee056a96b8e6e06e6c29f67c1a766f8e4
peeled commit         b2e30a175449cfda909ee4fbf4a29a6a071cad53
GitHub archive SHA-256 D8D8D38A9AA4ED9216C78A3A153F772A380466302A1332F39C60396CA8FA6878
PyPI sdist SHA-256     9A6CEA6E60B17EBE0A44C5CC636D94F09BD66142C1CD7D8B4CD731C4917A15F6
license SHA-256        9A8AD106A394E853BFE21F42F4E72D592819A22805D991B5F3275029292B658D
vendor tree SHA-256    28C080E63CD9BA5CB050589C0C892031343A84F533C92A1FFBAA1356D6B9ADFB
```

上游实际文件名是 `CHANGES.md`，不是计划草稿中的 `CHANGES.rst`；快照保留真实上游文件名且不改源码。allowlist 只保留 `src/click`、`tests`、`pyproject.toml`、`LICENSE.txt`、`CHANGES.md` 与 provenance，裁剪 docs、CI、devcontainer、examples、README 和 `uv.lock`。源码适配列表为空。

### 34.2 离线镜像

```text
base image  python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0
image tag   mokioclaw-eval-click:8.4.2
image ID    sha256:47142d38ecbb3be8ec5ad6c549f743b0b51ba413afa0bd82476b4249341a0d94
created     2026-09-22T11:06:46.165379302Z
system dep  less=668-1
Dockerfile SHA-256       D292B6F30B15DA6CDD35F22F80AB30D329EF48E2BBB7440D338FF7216C9AD248
requirements.in SHA-256  F40723C374D8534AB2A6295025F6D643F81EEAC4D826DB1E48947662A073A520
requirements.lock SHA-256 62AB584CF26216FCFF3ABA05176A8E6E8C4BA9AD38E8B806D75AABBAF2A5B47F
```

Python 依赖全部使用 hash lock；镜像没有安装另一份 Click，运行时由 `PYTHONPATH=/workspace/src` 直接解析快照源码。验收容器使用 `network none`、1 CPU、512 MiB、128 pids、只读 rootfs、受限 `/tmp`、drop all capabilities 和 `no-new-privileges`。

### 34.3 S1 验证证据

```text
Click snapshot/image acceptance
5 passed in 31.17s

每轮 upstream suite
1661 passed, 24 skipped, 31000 deselected, 1 xfailed
连续三轮均通过；每轮均 <=90s

全项目非 Docker 回归
424 passed, 2 skipped, 27 deselected in 66.06s

ruff check src tests
All checks passed!

git diff --check
通过

Task 13 authored-artifact secret-pattern scan
0 matches

Click cache contamination scan
0 __pycache__ / .pytest_cache / .pyc
```

第一次容器验收暴露 Debian slim 缺少上游 pager 测试所需的 `less`，随后将其固定为 `668-1`。重建后 upstream suite 已通过；外层测试最初仍错误使用 Windows 主机的 `1590 passed` 计数，修正为 Linux 镜像的 `1661 passed` 后，在用户明确授权的一次重跑中连续三轮通过。以上均为快照环境准入，不是 Agent 成绩。

### 34.4 边界与下一检查点

`main`、`HEAD` 与 `origin/main` 仍为 `2c68a12fc49940101ea56e8ac967d6558e74109e`。`.superpowers/`、Rich ignored 根和 legacy sidecar 仍存在；Rich 三份冻结分析 SHA-256 保持不变。Task 13 新增路径只有：

```text
evals/repos/templates/click/**
evals/images/click/Dockerfile
evals/images/click/requirements.in
evals/images/click/requirements.lock
tests/evals/test_click_snapshot.py
```

S1 已达到，但整体阶段尚未完成。当前硬停在 Task 14 之前；未授权 Click 候选 Case 的 zero-agent red/green、Task 15 身份冻结、provider smoke、真实 Agent run 或任何后续 gate。

---

## 35. 2026-09-26 多项目快照与稳定性阶段收束（Tasks 14–20）

### 35.1 Click Case、身份与逐轮权限

Task 14 对四个 Click 候选完成零 Agent-run bug/fix、隐藏行为、broken-edit 与时长矩阵；按预注册的不同子系统规则选择 option-parsing 与 argument-conversion 两个 Case，冻结 `two-case-72` 分支，而不是 36-run 单 Case 分支。Task 15 冻结 Click 8.4.2 镜像、两个 Case、四资源格、三架构、三轮的 72-slot schedule 与 batch identity。Tokendance `qwen3.5-flash` 的 12-probe smoke 和 6-probe 资格检查通过后生成 G1；这些 probe 与 Case fixture/reference 验收均不是 Benchmark Agent 成绩。G1、G2、G3 均经用户逐轮批准后才执行相应 R1、R2、R3，各轮 24/24，正式槽位没有补跑、替换或择优删除。

正式 Click 批次：`evals/reports/snapshots-click-842-tokendance-qwen3-5-flash-20260924-01/`。最终 scheduled=72、started=72、closed=72、not_started=0；覆盖 full=66、partial=6、unavailable=0；正式 provider attrition=0、failure_kinds={}，六项 R3 完整性标志均为 true。最终分析器在原批次只运行一次，`pooled.status=complete`、`branch=two_case`；Multi-Agent 与 Plan–Execute 按架构分别 qualified，ReAct 仅为独立 canary。10 条 `unknown stage observed` 提示来自真实工作流节点 `intent_router` 与 `plan`，保留原分析，不重算抹平。

### 35.2 Rich–Click 独立比较与接口裁定

Rich `snapshots-20260920/analysis` 三份冻结 SHA-256 仍与第 33.4 节完全一致；legacy sidecar 的 72 行及 worker-stage 504 证据为 22/22，历史 worker-attempt 和审计完整性仍为 `limited`。Click provider-sensitivity 的冻结产物不含 `audit_completeness` 字段。为避免原比较器将字段缺失误当 Click 审计受限，Task 20 用 RED→GREEN 测试在 `evals/cross_repo_gate_adapter.py` 报告层绑定第五份 R3 gate-safe 完整性摘要；从六项完整性标志与已封账 schedule 判定 Click 审计，不读取原始 manifest，也不改写 Click 的一次性分析产物。曾尝试直接修改 `src/mokioclaw/evals/cross_repo_comparison.py`，但全量测试发现冻结身份覆盖整个 `src/mokioclaw` Python 树；该源文件已精确恢复，适配器留在冻结树之外，原身份复算测试重新通过。

最终比较根为 `evals/reports/cross-repo-rich-click-20260926-01/`。先前 `cross-repo-rich-click-20260922/` 的初版输出保留未覆盖，但缺少设计要求的支持性审计字段，不作为最终交付。最终比较的三个 required dimensions 为 Multi-Agent Q1 `divergent`、Plan–Execute Q1 `divergent`、Plan–Execute Q2 `inconclusive`；顶层 `direction_comparison=inconclusive`，与独立的 `strict_audit_status=legacy-audit-limited` 分开。Rich 与 Click 的逐 Case 差异、provider attrition 和 telemetry coverage 只作各自支持证据，不混合 pooled count 或 denominator。

### 35.3 限制、交付与验证

详细边界、样本量、哈希、三个比较维度、provider/telemetry 账目和 non-claims 见 `docs/MOKIOCLAW_MULTI_PROJECT_SNAPSHOT_STABILITY_REPORT_2026-09-22.md`。本阶段不宣称统计显著、普适、跨仓库总成功率或严格复制；Rich 22 条 provider 504 不改写为 Agent 失败，非 Benchmark probe 与 fixture 不记为 Agent 成绩。没有 README 产品化、检索栈、MCP 或服务化扩项。

Task 20 最终验收：指定 Windows Python、显式 `PYTHONPATH=src`、独立工作区 basetemp 的完整 pytest 为 **468 passed、2 Windows symlink capability skips、0 failed**；Ruff `--no-cache` 检查 `src tests evals/cross_repo_gate_adapter.py` 与 `git diff --check` 均通过。只读复算确认 Rich 三份冻结 hash、legacy 72 行和 22/22 worker-stage 504，Click 72-slot ledger/manifest/attempt/call/transport、canonical identity/schedule，Click 六份稳定分析产物和最终比较三份产物跨路径/时区/locale 字节一致。对相关产物与本报告共 8,054 个文本文件的秘密格式扫描为 0 命中、`.env` 文件为 0；没有读取 `.env` 秘密值。设计 §18 的 18 项完成定义已在阶段报告逐条审计，Rich `legacy-audit-limited` 与两项 Windows skip 继续明示。

Task 20 提交前检查点的 checkout 为 `main`、HEAD `7c5c260fe632896d5e10cb5c6d96dd502655aa62`；当时 tracked 修改 0，untracked 为 `evals/cross_repo_gate_adapter.py` 与 `tests/evals/test_cross_repo_gate_adapter.py` 两个文件，报告和比较证据位于 ignored 路径。该检查点未清理 ignored 实验证据，也没有提交、push 或修改远端。后续本地提交由用户另行授权，此处记录的是集成前状态。

---

## 36. 2026-09-27 本地仓库审查工作台 V1（四阶段验收）

### 36.1 范围与功能

按已批准的本地工作台设计及四阶段计划，完成显式本地路径登记、只读 Git 读取、`review-priority-v1` 纯规则、回环 GET 服务、三栏浏览器页面和演示说明。页面左栏切换多个本地仓库，中栏按固定 HEAD 锚每页显示最多 50 条提交，右栏按需展示文件统计、固定理由和 `high`、`medium`、`low`、`manual_review` 四种人工审查优先级。普通/敏感路径/合并提交、浅克隆统计缺失、空历史、仓库移动、HEAD 更新、非法 SHA、输出超限与超时均有明确边界。没有 GitHub 登录、页面内 Agent 修复、provider 调用或新的正式实验槽位。

Phase 4 新增边界测试发现 Git 可执行文件缺失时，登记层和 CLI 原先只显示笼统错误；现保留预定义且不含路径的可操作提示。还补了同名不同根目录、非法 SHA-256 长度、详情读取超时/截断不触发评估，以及双仓库真实回环服务的只读校验。后者使用 52 条普通提交、敏感路径提交和双父合并提交，检查 50+2 翻页与 `low`/`high`/`manual_review`，并比较两个临时来源仓库的 refs、index、含 ignored 项的状态与全部非 `.git` 文件内容，启动前后相同。该路径模拟禁止 Agent 流和 provider 初始化；演示文档中的临时夹具命令实际生成 52 条/5 条历史及双父合并。

### 36.2 完整回归与冻结身份

第一次受限环境完整 pytest 为 **504 passed、3 skipped、30 failed**：29 项 Docker fixture 因本机 Docker API 在沙箱内被拒绝，另 1 项旧 Click 测试把冻结实验的 `agent_tree_sha256` 与新增工作台后的活动源码树比较。本机 Docker daemon 经只读检查可用；在批准的本机 Docker 访问下重跑为 **533 passed、3 skipped、1 failed**，仅剩该旧断言。该测试现从指纹记录的冻结提交 `5e104fdfd5a9f24fbc3b7e1d9232983a484a421f` 读取 Git 树、按原 canonical 规则复算；所得 `3b8b8147ff36d9efd7a544b3acf8bbd607532de03d3bd4eb0dd4b39176d09908` 与原指纹相同。没有改动冻结指纹、分析产物或正式批次。

修正后用指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 和已批准的 Docker 访问重跑完整项目：**535 passed、3 skipped、0 failed**，耗时 768.04 秒。3 项 skip 全为 Windows 符号链接创建能力限制（dashboard 1、eval grader 2）。FastAPI/Starlette TestClient 发出 1 条 `httpx` 弃用警告，不影响本轮通过；未来依赖升级再处理。`ruff check src tests`、`git diff --check` 和 `uv lock --check --offline` 通过。目标 32 个作者相关文件的秘密格式扫描为 0 命中；设计文档第 3–5 行有 3 处原有 Markdown 双空格换行，其他目标文件无行尾空白。
最终单独重跑 `tests/dashboard tests/test_cli_smoke.py` 为 **74 passed、1 skipped、0 failed**。本轮最后一次范围扩展到 33 个作者相关文件（含 ignored 进度账），秘密格式扫描仍为 0 命中；排除设计文档原有 3 处 Markdown 换行后，行尾空白为 0。

Rich 冻结 `thresholds.json`、`per-case.json`、`pooled.json` 的本轮只读 SHA-256 依次为 `B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB`、`167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB`、`6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2`，与第 35 节记录一致。最终比较根仍为 `evals/reports/cross-repo-rich-click-20260926-01/`，四个文件均在原位；本轮哈希分别为 `comparison.json`=`CFC2FA399B97DF5608A29374B1668813F72F42FDC77702FE8661781E0772A719`、`comparison.md`=`90E520EDEE820E42F58A98E1CCEDB49FDFC42BE71DE9358B3E5450105CC6892E`、`comparison-audit.json`=`045A1A23C4970E8E7AB065B80951D2D7D9003B86EA17975A021EF06AF169CAAB`、`input-hashes.json`=`843D52EF568E84391701A107F8CF58C827E51A5D98F150AB9CA0DC96A36B7675`。只读核对其两个 Q1 为 `divergent`、Q2 为 `inconclusive`、总方向 `inconclusive`、严格审计 `legacy-audit-limited`；这些不是本地工作台成绩。

### 36.3 交付边界

README 首页与 `docs/MOKIOCLAW_LOCAL_DASHBOARD_DEMO.md` 现在给出双仓库启动、`--no-browser`、指定 Python 环境备用命令、停止方式、四种优先级、临时夹具演示、截图隐私和故障排查。`.gitignore` 对演示、交接及已起草的工作台设计／计划文档使用精确放行规则；其他 ignored 评测证据仍在原位。工作在当前 `main` checkout 保持未提交；本阶段没有 commit、push、远端写入、真实 Agent run、provider 调用或正式槽位补跑。本地核心已完成本轮验收；GitHub 账户接入与 Agent 修复仍需后续单独设计与授权。

---

## 37. 2026-09-28 阶段 B3.5 无 provider 实际 Docker 沙箱验收

用户另行明确授权本机 Docker 验收后，在 `codex/mokioclaw-stage-b` 独立工作树使用临时 Git 仓库和本机已有 Linux 测试镜像 `sha256:c9f6b3d0c618a75614fe5814e9ff9219d712f0e8a46c517dd6ef2650f9f31632`。测试未调用 provider、未启动真实 Agent，也未运行 Rich/Click 正式槽位。`tests/dashboard/test_task_docker_acceptance.py` 只在显式提供 `MOKIO_TASK_DOCKER_TEST_IMAGE` 且选择 Docker 标记时运行；本轮指定 Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的四项实际测试为 **4 passed**。

首次容器测试返回退出码 0 却没有执行检查语句。只读镜像检查发现其预置 `Entrypoint=["/bin/sh","-lc"]`；执行器原先在镜像名之后追加 `/bin/sh -c`，被当作入口参数。新增失败测试后，固定 `docker create --entrypoint /bin/sh <digest> -c <command>`，参数级及实际容器测试均通过。这次实测说明仅靠假 Docker 参数测试不能证明命令确实运行。

实测覆盖：容器仅挂载任务 `work`；固定 `network=none`，对外连接失败；容器内 UID/GID 为 `65534:65534`；Docker `HostConfig` 显示只读根、非特权、1 CPU、512 MiB 内存、64 PID；来源、baseline、ignored 文件、Docker socket、用户 Docker 配置和测试用 provider 环境变量均不可见。容器只在 work 写出测试文件，输出按上限截断。临时来源仓库的 HEAD、refs、index、工作树状态及 ignored 夹具 SHA-256 在执行前后相同。超时后归属容器移除；取消与重启 reconcile 只清理匹配 instance/task 标签的容器，另一只无关测试容器保留。验收后只读列表确认本轮测试容器无残留。

此门仅证明上述固定镜像与本机 Docker 环境的无 provider 命令隔离。任务 worker 当前仍是无 Agent 的生命周期骨架，网页 `/run` 继续关闭；Task 3B 的部分 Windows 宿主文件操作仍 fail closed，B4 的 provider、文件工具与完整图接入未完成。work 的周期扫描是软上限，不能作为磁盘硬配额；真实试点仍需独立授权。

代码修正后的全项目非 Docker 回归为 **610 passed、3 skipped、35 deselected、0 failed**（3 项 skip 均为 Windows symlink 能力限制；35 项 deselected 包含本轮新增的 4 项 opt-in Docker 测试）。实际 Docker 验收另行为 **4 passed**。未将两组测试合并冒充真实 Agent 验收。

---

## 38. 2026-09-28 阶段 B4 假 provider 配置与文件工具边界（进行中）

Task 8A 新增任务专用 `ProviderSettings`，只从显式 `MOKIO_TASK_API_KEY/MOKIO_TASK_MODEL/MOKIO_TASK_BASE_URL` 读取，不装载 `.env`、不回退旧变量；构造异常只保留固定错误类别。`TaskRunContext` 使用同一预算账本跨绑定模型计数，限制请求数、已报告累计 token 和单次输出 token；用量缺失时阻止下一次请求，最后一次可能超过累计阈值则如实记录。worker 仅在显式收到设置时注入这三项，命令容器仍无 provider 环境。旧 `create_model()` 入口未改变。定向假模型、旧 provider 与 worker 测试 **27 passed**；无真实 provider 请求。

Task 8B 已建立 `TaskFilesystem` 专用文件工具注册表，现有文件的读／写／唯一片段编辑、显式单文件字面搜索、scratch 记事本均由同一范围检查处理；越界路径、Windows junction 替换、旧工具回退会拒绝。任务图的记忆读取转向 scratch，TODO 在任务模式仅保留内存，不写工作目录根文件。Windows 上安全创建、重命名、删除、递归遍历仍 fail closed，因而这些功能尚不可用于真实任务。图节点与命令网关的接入进展见 §38.1；网页 `/run` 保持关闭。

本阶段一次全项目非 Docker 回归为 **634 passed、3 skipped、35 deselected、0 failed**，1 条 Starlette TestClient 弃用警告；3 项 skip 仍为 Windows symlink 能力限制。随后补充 TODO 绕过防护的定向回归 **92 passed**，Ruff `--no-cache` 与 `git diff --check` 通过。图节点审阅确认旧直接模型创建及验证工具注册点仍需 Task 8C 逐一注入；本记录不宣称完整工作流、真实 Agent 或 provider 已通过。

### 38.1 B4 图适配与 worker 投影进展

Task 8C 已用显式 `TaskRunContext` 接入 entry、planner、CodeAgent、verifier 和上下文压缩模型；任务 `create_runtime` 固定关闭 web search、原始 trace/checkpoint，跳过旧 `.env` 装载。CodeAgent／verifier 使用任务专用文件工具与同一命令网关；固定验证命令来自任务创建时的清单，记录实际命令、请求 ID、退出码和耗时。无命令证据时不把模型声称的“通过”记成验证通过。只有 verifier 明确返回失败才能进入下一 attempt，网关随之作废旧批准并沿用当前 work。假模型完整 entry→planner→CodeAgent→verifier 两次 attempt 测试通过；provider、工具或审批异常不沿该重试路线继续。旧 CLI/TUI 的无 `task_context` 路径保持默认行为，冻结工具与 graph 架构文件未改动。

Task 8D 已把任务专用配置、文件工具、完整图入口与 worker 的回环消息接起。worker 在发送前将原始图事件投影为白名单摘要，服务再次核对任务实例、attempt、事件类别和序号；prompt、response、完整输出、provider 字段和私有路径不进入事件。最后一次 provider 响应缺用量时不会先发“完成”。父进程保存命令策略、审批和 Docker 执行权；worker 只发送请求并等待返回。人工审批等待使用无固定 5 秒超时的已认证 socket，命令输出上限的最坏 JSON 转义仍可在有界通道内传送。`ApprovalBroker` 通知服务后，待决命令的完整文本及规范摘要可在本地 API 审阅；决定只接受当前 task／attempt／request/digest 的单次批准或拒绝。失败通过固定类别回传，不转发异常原文。配置能力构造测试证明这一步没有创建 provider 模型或接触 Docker。

上述是真实 worker 接线的无 provider 假注入测试，**不是**真实 Agent 的端到端验收。后续用假 worker 验证总时限会先停止 worker、确认资源清理，再发布 `timed_out`；已准备任务可通过受保护 API 取消且不接触 Docker。重启恢复测试确认私有 `spec.json` 仅在请求摘要与任务身份一致时恢复固定范围和预算；公开 `record.json` 不含描述或验证命令。真实运行的启动能力门、结果收集和网页审阅尚需补齐；`/run` 与 `run_available` 继续固定关闭。未调用 provider、未运行真实 Agent、未提交或 push 本工作树。本轮指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 的全项目非 Docker 回归为 **672 passed、3 skipped、35 deselected、0 failed**，1 条已知 Starlette 警告；3 项 skip 均为 Windows symlink 创建能力限制。Ruff `--no-cache` 与 `git diff --check` 通过。B4 尚未到完整验收门。

---

## 39. 2026-09-29 阶段 B4 假工作流与结果审阅补齐

本轮在独立 `codex/mokioclaw-stage-b` 工作树补上内部 `start_agent` 启动桥，连接已保存的固定任务规格、worker、命令网关与受限执行器；页面 `/run` 和 `run_available` 仍关闭，未调用 provider、未启动真实 Agent。假模型完整图的两次 attempt 现在同时经过 worker 投影测试，固定验证事件仅带经核对的命令序号、审批请求 ID、实际退出码、耗时和输出截断标志。父进程在审批后、命令实际执行完毕时保存只含规范请求摘要、命令 SHA-256、退出码、耗时和截断标志的回执；公开结果必须将固定命令、批准记录、唯一执行回执和投影事件逐项匹配才认可通过。一份回执不能重复满足两条相同的固定命令；模型自述、孤立或篡改的事件不算证据。

Task 9 的只读 `/api/tasks/{id}/result` 分开展示任务状态、失败类别、补丁摘要与每条固定命令的验证结果。网页使用文本节点和控制字符可见转义，展示待批命令与单次批准／拒绝操作；真实运行按钮保持关闭。补丁收集拒绝超范围、链接、二进制、无效 UTF-8、超限和疑似秘密内容，失败时清除旧补丁，完整 `patch.diff` 只在私有任务根保存、不提供下载或回写路由。结果首次读取后以私有 `result.json` 固定，重启后沿用与任务记录序号、请求摘要一致的快照；本机用户后来修改 work 不会改写已展示的摘要。`--task-root` 中的 baseline、work、结果和完整补丁不自动删除，需启动者自行保管与清理。

两个临时来源仓库的无 provider 夹具分别准备固定提交副本并修改各自 work；来源 HEAD、refs、index、含 ignored 项的状态、普通源码和 ignored 夹具字节在前后相同。代码审阅指出命令容器创建与取消清理之间的竞态、关闭服务时审批等待可能持续到超时、验证事件缺少父进程执行证明、无末尾换行的补丁和大量空目录的边界；已分别用控制器创建锁、关闭前撤销审批并清理、持久执行回执、补丁 fail closed 与目录计数上限修复，新增针对性失败再通过测试。工作台显示完整 base SHA、当前 HEAD、来源脏状态及所有阻断路径，`cleanup_failed` 仍属未完成清理，不开放结果快照。

第二轮只读复核又指出越界序号的重复验证事件可复用一次批准回执，以及目录上限在入队后才检查的问题；分别补失败用例，改为所有同请求 ID 的验证事件计数和发现目录时立即计数，随后定向与完整回归通过。最终全项目非 Docker 回归使用指定 Windows Python、显式 `PYTHONPATH=src` 和新 `--basetemp`，结果为 **699 passed、3 skipped、35 deselected、0 failed**，耗时 219.93 秒；3 项 skip 均为 Windows 符号链接能力限制，另有一条既有 TestClient 弃用警告。Ruff `--no-cache src tests`、JavaScript 语法检查与 `git diff --check` 通过；目标源码、测试和文档的秘密格式文件名扫描没有命中。Rich 三份冻结分析与最终 Rich–Click 比较四份文件的只读 SHA-256 与第 36 节一致，未修改冻结工具、图架构或工作流文件。Task 8D、9 的**假 provider／无真实 Agent**验收据此通过；此前 **684 passed** 和 **697 passed** 都只是修复前检查点。真实运行按钮仍关闭，B5 真实试点没有授权也未执行。本轮没有重跑正式槽位或 Docker 实测，没有提交、push 或远端写入。

---

## 40. 2026-09-29 Task 10 真实试点准备门（等待固定参数）

用户已同意继续 Task 10，但尚未指定计划所需的试点仓库、完整 base SHA、读取范围、具体任务、provider／模型、运行次数、请求与 token 预算、固定验证命令和 Docker 镜像 digest。本节只记录不调用 provider 的准备工作；真实 Agent 任务、命令容器和试点结果尚未产生。

Task 9 验收后审阅发现启动桥虽存在，CLI 尚不能显式启用真实任务，网页 `/run` 和 `run_available` 一直固定关闭。为使 Task 10 的授权门可实际核对，本轮补充 `--enable-agent`、`--task-root`、固定 `--task-image sha256:<64 hex>` 的组合校验；任务专用 provider 只从三项显式进程环境配置，不读取 `.env`。服务在开始 worker 前检查本机镜像精确 digest，不可用时拒绝；只读运行清单展示固定提交、读写范围、模型、镜像、无网络、预算和验证命令，不展示凭据或完整 provider URL。页面只有在能力门开放、任务已准备且清单身份与当前仓库／提交一致时才显示真实运行确认操作；运行确认与每条命令审批彼此独立。默认无 provider 状态演示保留。

定向测试以假 Docker 和假 provider 覆盖镜像拒绝／可用、固定清单无凭据、启动路由、CLI 参数以及页面控制；没有建立真实模型。全项目非 Docker 回归使用指定 Windows Python、显式 `PYTHONPATH=src`、独立系统临时 `--basetemp`，结果为 **704 passed、3 skipped、35 deselected、0 failed**，耗时 160.47 秒；3 项 skip 为既有 Windows 符号链接限制。初次回归中旧内部启动测试因新增镜像门失败，现该测试显式模拟已通过门，并由独立测试证明门拒绝逻辑；另一次因 `--basetemp` 名含 `baseline` 与既有断言冲突，改用中性名称后通过。实际 Docker B3.5 的四项通过证据仍为第 37 节的历史结果，本轮未重跑；也未补跑正式槽位、提交、push 或写远端。真实试点仍需用户补齐逐项参数后才能开始。

---

## 41. 2026-09-29 Task 10 单次真实试点结果

用户随后确认了逐项参数：来源为 `D:\agent work\project\MokioAgent` 的固定提交 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`，读取与写入范围为 `pyproject.toml`、`src/mokioclaw/__init__.py`、`src/mokioclaw/core/`、`src/mokioclaw/tools/`、`tests/`；目标是修复 grep 的符号链接越界、正则校验与读取上限，以及 Bash 输出的内存和落盘上限。任务根为 `D:\agent work\project\MokioAgent-task10-private`，模型标识为 `qwen3.5-flash`，本机镜像固定为 `sha256:83ff408c0f9ce6007afbc9b468815ae4fbdde79d7a702e4b7eb5ee21c91a72b2`。上限为 1 次运行／1 次尝试、1200 秒、16 次 provider 请求、30000 总 token 和单次输出 3072 token。启动者在同一 PowerShell 进程显式设置任务专用 provider 环境变量；工作台没有读取或复制 `.env` 值。

试点前从该固定提交预览并复制了 27 个文件、179494 字节，阻断路径为 0；复制前后来源观察一致。无 provider 的实际 Docker 预检重新运行 B3.5 四项测试，结果 **4 passed**。固定来源副本在同一本机镜像中的 `tests/test_tools.py` 全量基线为 **41 passed、2 failed**，失败是 `test_bash_prefers_runtime_python_on_path` 与 `test_bash_env_file_expands_existing_variables`；排除这两项后的预检为 **41 passed、2 deselected**。试点固定验证命令采用该已通过子集，并要求新增针对三个目标的回归测试；排除项不得被视为已修复。

网页创建的真实任务 ID 为 `ZCiH-d68Fyuqjh8xeseDT1tF`。运行清单在启动前展示固定提交、读写范围、模型、镜像、无网络、预算与验证命令。一次真实 Agent 运行进入 CodeAgent 阶段，并提出 `find . -type f -name "*.py" | head -30`；审批记录为 approved，唯一容器执行回执为退出码 0、耗时 5124 ms、未截断，任务容器在结束后无残留。随后任务以 **failed / task_tool_failed** 结束：补丁为 0 个文件、+0/-0，固定验证为 `not_run`，限制为 `verification_not_run`。公开投影没有保存下一次失败工具调用的名称或参数，因此不能断言具体根因，也不能把本次算作三个缺陷已修复。此前通过服务直接准备的 `wGBM_c1SZUp4rAW2IyHb9DC7` 仍为未运行的 prepared 副本，未计作第二次真实运行。

无 provider 的后续定位复现了一个独立接口问题：任务版 `GrepTool` 的默认 `path="."` 被 `TaskFilesystem` 拒绝，返回 `task_file_access_denied`；显式给出范围内文件路径则可成功。任务工作流把工具返回的 `ok=false` 归为终止性 `task_tool_failed`。公开投影无法证明本次 Agent 正是省略了这个参数，因此该复现只列为后续调查线索，不作为本次失败的确证原因，也未据此改写安全策略或发起第二次真实运行。

结束后只读核对来源 `HEAD` 仍为 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`，与本地 `origin/master` 左右计数均为 0；`git status --short` 仍只显示原有的一个未跟踪文档，没有已跟踪文件改动。真实任务 work 中不存在 `.env`。本次有真实 provider／Agent 试运行，实际 provider 请求数未由公开结果给出，不能推定精确数量；没有重跑正式槽位、回写来源、提交、push 或修改远端。已确认的一次运行额度用尽，后续真实重试须重新授权。

---

## 42. 2026-09-29 Task 10 后续工具接口修复（无 provider）

经用户确认，仅修正任务版 `GrepTool` 的参数契约：`path` 现在是 Agent 可见工具 schema 中的必填项，调用者须给出单个范围内文件路径。省略参数会在工具入参校验处拒绝；显式路径搜索可用，目录、越界路径和链接替换仍按原有文件边界拒绝。没有加入递归搜索，也没有改变工具失败即终止的策略。

先增加 schema 回归断言，确认旧实现只要求 `pattern` 时测试失败；再去掉 `TaskFileTools.grep()` 的 `path="."` 默认值。指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的任务文件边界测试为 **15 passed**，全项目非 Docker 回归为 **704 passed、3 skipped、35 deselected、0 failed**（162.20 秒）。3 项 skip 是既有 Windows 符号链接能力限制，1 条 Starlette TestClient 弃用警告仍在；Ruff `--no-cache src tests` 与 `git diff --check` 通过。

本轮没有调用 provider、启动真实 Agent、运行 Docker 或补跑正式槽位，也没有提交、push 或写远端。公开投影仍不足以确认第 41 节真实试点的失败工具调用，故本修复不能被视为该试点根因已证实或三个目标已完成；第二次真实运行仍须另行授权。

---

## 43. 2026-09-29 Task 10 后续两次受控真实运行

用户另行授权最多两次独立真实运行。沿用第 41 节固定来源提交 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`、五项读写范围、三个修复目标、`qwen3.5-flash`、镜像 digest 和每次 1 attempt／1200 秒／16 次 provider 请求／30000 总 token／单次输出 3072 token；验证命令仍是排除两个既有 Linux 容器基线失败后的 `tests/test_tools.py` 子集。启动服务的页面资源与阶段 B 工作树一致，`run_available=true`；来源开始时仅有原有未跟踪文档，HEAD 与 `origin/master` 相同。

第 1 次使用此前未运行的 prepared 任务 `wGBM_c1SZUp4rAW2IyHb9DC7`。Agent 请求在隔离副本内列文件；审批请求在固定的 120 秒等待期内没有收到决定，随后过期，任务终态为 `failed / task_tool_failed`。事件没有审批决定，私有记录的执行回执为 0，未执行容器命令；补丁为 0 个文件，固定验证 `not_run`。用户后来对该旧摘要作出的批准已失效，没有用于任何后续请求。此失败由审批期限解释，不证明第 42 节接口修复有效或无效。

第 2 次重新预览同一提交，清单 digest 与原规格相同：27 个普通文件、179494 字节、0 个阻断路径。因工作台重启后本次登记的 `repo_id` 与旧任务记录不同，准备新任务时使用当前仓库登记 ID；新任务为 `w88SYgGwfgm9KeJkgTQIaTv-`。用户分别明确批准其三个请求：列出最多 50 个源码文件、`ls -la`、再次 `ls -la`。三份父进程执行回执分别为退出码 0、4880／516／432 ms，均未截断；重复命令使用不同请求 ID 和摘要，未复用批准。随后任务终态为 `failed / provider_failed`，补丁仍为 0 个文件，固定验证 `not_run`。公开投影和私有回执不包含可确定 provider 原始异常或精确请求数的材料，因此不推断失败的具体原因，也不把三个目标记为已修复。

本轮两次真实运行由助手调用工作台本机 API 启动，逐条取得用户在对话中的明确批准后，再提交绑定请求 ID 与摘要的审批；**运行时没有在 Codex 内置浏览器中操作工作台页面**。用户指出此执行方式与期望的浏览器流程不一致后，助手才在内置浏览器打开当前地址并核对页面。新开的页面显示真实 Agent 可用，但任务区只提示先选择仓库和提交，没有恢复上述已有任务的选中状态；本轮不把 API 审批冒称为页面审批。后续应先在无 provider 条件下处理任务恢复与页面审批可见性，再考虑新的真实试点。

两次任务的 `cleanup_confirmed=true`，只读 Docker 列表对两个 task ID 均为 0 个残留容器。来源结束时 HEAD、全部 refs、index SHA-256 和原有未跟踪状态与开始时一致；没有读取 `.env` 秘密值或触碰冻结 Rich／Click 分析与 ignored 实验证据。没有提交、push、远端写入或正式槽位补跑。本轮获准的两次运行额度已经用尽；进一步 provider 诊断或真实运行须另行授权。重启后旧任务的页面选中状态与单次审批期限对人工操作形成限制，后续应先用无 provider 测试改善任务恢复与审批可见性。

---

## 44. 2026-09-29 内置浏览器任务恢复与新试点第 1 次结果

用户另行批准最多两次真实运行，并确认先修复页面任务恢复。页面现在在创建任务后将不透明任务 ID 加入本机地址；刷新时按 ID 读取记录，仅在仓库 ID、固定提交和历史锚均匹配时恢复状态、审批和结果，切换选择会清除旧 ID。先写 Node 驱动的真实页面脚本测试，旧代码因刷新后 `taskId=null` 失败，修改后通过；浏览器里打开并刷新旧任务 `w88SYgGwfgm9KeJkgTQIaTv-` 后，任务失败类别、结果和事件仍可见。定向测试 **7 passed**；指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的全项目非 Docker 回归 **705 passed、3 skipped、35 deselected**，1 条既有 TestClient 弃用警告。Ruff、JavaScript 语法和 `git diff --check` 均通过。验证不调用 provider。

随后首次通过 Codex 内置浏览器填写和预览同一固定提交、五项范围与三个目标，预览仍为 27 文件、179494 字节、0 阻断，并准备任务 `cJ7RHyPrvHSsVSKMr2olRr41`。页面清单显示 `qwen3.5-flash`、原镜像 digest、`network=none`、1200 秒／1 attempt／16 次请求／30000 总 token／单次输出 3072 token 和原固定验证命令。页面创建新任务后曾短暂保留旧任务结果面板；刷新到新任务链接后只显示新任务清单，该展示问题待独立处理。

用户本轮额度中的第 1 次从浏览器页面启动，任务在公开 `entry` 事件后以 **failed / task_tool_failed** 结束，没有待审批命令或执行回执，补丁为 0 个文件，固定验证 `not_run`。公开事件无法定位具体工具及参数，不能断言根因。只读代码核对发现一个可复现的独立缺口：任务已固定验证命令，但 `TodoWriteTool` 仍要求模型另给非空验证命令，否则规划工具返回失败；此缺口可能解释早期终止，尚无事件证据证明本次恰好触发它。该修复须按用户对简短设计的回复再实施，剩余 1 次额度未用。

来源 HEAD 仍为 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`，已跟踪文件无改动，原有未跟踪文档仍在。任务记录 `cleanup_confirmed=true`，只读 Docker 列表无 MokioClaw 任务容器。未读取 `.env` 秘密值、未修改冻结证据、未补跑正式槽位，也未提交、push 或写远端。

---

## 45. 2026-09-29 任务版固定验证清单修复与最后一次运行

用户确认简短设计：任务版 `TodoWriteTool` 始终使用创建任务时已确认的固定验证清单，模型省略、传空列表或提出其它命令时都不能改变它；普通 CLI/TUI 的参数契约不变。先给省略、空列表、替换命令以及无固定命令四种情况增加实际 `StructuredTool.invoke` 路径的测试，旧实现分别因参数校验、`ok=false` 或接受模型命令而失败；修改后测试通过。任务图模块 **17 passed**，指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的全项目非 Docker 回归 **710 passed、3 skipped、35 deselected**，1 条既有 TestClient 弃用警告；Ruff 与 `git diff --check` 通过。测试未调用真实 provider。

随后在 Codex 内置浏览器用同一固定提交、五项范围、三个修复目标、预算、模型、镜像和验证命令重新预览，结果仍为 27 文件、179494 字节、0 阻断；准备任务 `P11KhyuUxz2ZytjnUKTtpRaN`。页面创建新任务后仍短暂显示前一任务的运行清单，刷新到新任务链接后，新任务清单和身份正确；这是独立的页面状态缺陷，不能把旧清单视为新任务的已确认策略。

用户新增两次额度中的最后一次从该浏览器页面启动。浏览器控制在提交按键时超时，但后续页面与私有最小记录均确认本任务确实进入 `running`，公开事件只到 `entry`，随后终态为 **failed / task_tool_failed**。没有待审批命令、执行回执或修改文件；补丁 0 个文件，固定验证 `not_run`。这表明第 44 节规划清单缺口的修复不足以让该任务通过；公开事件不包含失败工具身份或参数，不能断言两次入口失败有相同根因，也不能宣称三个原始目标完成。

结束后只读核对来源 HEAD 为 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`，已跟踪文件无改动，原有未跟踪文档仍在；任务记录 `cleanup_confirmed=true`，Docker 列表无 MokioClaw 任务容器。两次新增真实运行额度现已用尽。没有读取 `.env` 秘密值、补跑正式槽位、改写冻结证据、提交、push 或修改远端。继续真实试点需新授权；宜先设计仅暴露固定工具名与失败类别的脱敏诊断，完成无 provider 验证后再申请真实额度。

---

## 46. 2026-09-29 Task 10 脱敏诊断与新任务页面隔离（无 provider）

用户确认简短设计后，在阶段 B 工作树补充终止性任务工具失败摘要。规划、CodeAgent 与 verifier 的任务工具在返回拒绝或抛出非 provider 异常时，先发出仅含固定工具身份和受控失败类别的 `tool_failure`；未知名称与类别折叠为 `unknown`。类别仅为 `invalid_arguments`、`scope_denied`、`approval_denied_or_expired`、`tool_rejected`、`tool_exception`、`unknown`。内层已发诊断时外层委派不重复报错；内层未报告而外层工具终止时，外层给出固定身份。worker 继续只投影白名单字段，参数、路径、异常原文、prompt、源码、工具输出和 provider 信息不进入公开事件。

页面开始创建新任务即清除旧任务 ID、运行清单、结果、事件与审批，作废旧轮询并从 URL 移除旧 ID；新记录的仓库、固定提交及历史锚均匹配后才绑定。创建响应不确定时保留同一幂等键供核对后的同请求重试。Node 驱动的实际页面脚本覆盖等待新建响应时旧面板消失、新任务返回后加载自己的清单与 URL 身份，以及固定工具失败标签。假模型完整图分别覆盖规划参数校验失败、CodeAgent 文件范围拒绝和外层独立失败；内层失败只产生一条公开摘要，私有输入未出现。先红后绿的定向测试均按预期失败和通过。

最终全项目**非 Docker**回归用指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 与关闭 pytest 缓存运行，结果为 **717 passed、3 skipped、35 deselected、0 failed**，耗时 166.58 秒。3 项 skip 均为既有 Windows symlink 能力限制；1 条既有 Starlette TestClient 弃用警告。Ruff `--no-cache src tests`、JavaScript 语法和 `git diff --check` 通过；本次改动文件的常见密钥格式扫描无命中。Rich 三份冻结分析及最终比较四份文件的只读 SHA-256 均与第 36 节记录一致。未运行 Docker 实测、真实 Agent、provider 或正式 Rich/Click 槽位。

这些新诊断只能用于以后运行，不能倒推出第 44–45 节已结束任务的失败工具或根因。本轮没有新真实任务、补丁或固定验证结果；三个原始修复目标仍未完成，B5 仍未通过，真实运行次数额度仍为零。未改动来源仓库、冻结分析或 ignored 证据，也未提交、push 或修改远端。

---

## 47. 2026-09-29 Task 10 入口失败的无 provider 定位探针

用户确认先调查阶段 B Task 10 未成功完成的 Agent 维护试点。沿 `stream_agent_events`、`planner_node`、`_execute_planner_tool` 和 `run_code_agent` 的事件顺序核对：`entry` 表示路由节点已完成，规划节点完成后才会有 `planner`；`CallCodeAgentTool` 在进入内层执行前先发 `handoff`，公开为 `code_agent`。因此第 44–45 节两次旧任务的“只到 `entry`”现象可将调查范围收窄至规划阶段，但不证明具体工具调用或根因。旧运行没有新增的 `tool_failure` 摘要，无法补取固定工具名和类别。

无 provider 验证使用指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 与 `-p no:cacheprovider`：任务图和文件边界模块 **37 passed**。相关假模型测试分别证明规划入参失败可在终止前公开固定的 `TodoWriteTool / invalid_arguments`，以及临时工作区的完整流程可修改已有文件并进入固定验证；没有调用 provider 或真实 Agent。先前一次定向命令误写不存在的 pytest 节点，0 项收集并退出 1；改正节点名后的三项测试 **3 passed**。这不是代码回归。

另有独立接口限制：CodeAgent 提示说 `FileWriteTool` 可新建文件，任务工具却明确只改写已有文件；Windows 的 `TaskFilesystem.create_bytes` 故意 fail closed，现有测试验证新建会拒绝。此点不能解释两次尚未进入 `code_agent` 的旧失败，也不阻止在已有 `tests/test_tools.py` 增加 Task 10 回归用例。本轮只更新交接与调查记录，没有修改行为；此前五次仍无补丁、固定验证仍均为 `not_run`，三个 Grep/Bash 修复目标未完成，真实运行额度为零。未读取 `.env` 值、改写冻结或 ignored 证据、触碰来源仓库，也未提交、push 或写远端。

---

## 48. 2026-09-29 Task 10 新额度前两轮与 provider 失败分类

用户另行批准最多三次真实试点，并明确同意固定选中 27 个文件范围发送到 `tokendance.space` 配置的 `qwen3.5-flash` provider。沿用第 41 节同一来源 SHA、任务范围、镜像、预算和固定验证命令；没有扩大读取范围。用户在原有任务专用环境的终端将工作台重启至本机端口 51461；健康与运行能力检查通过。开始前的指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 全项目非 Docker 回归为 **717 passed、3 skipped、35 deselected**；Ruff、JavaScript 语法及 `git diff --check` 通过。

第 1 次新试点 `A44GAezHveH-qFcUWns_Rypq` 由内置浏览器创建并启动。预览仍为 27 文件、179494 字节、0 阻断。一条列文件命令经单次审批后退出 0、耗时 4810 ms、未截断。此后有若干内层 `tool_result` 失败项，但公开记录无工具身份和参数；终态 **failed / provider_failed**，补丁 0 文件、+0/-0，固定验证 `not_run`。不能从工具状态推断 provider 的原始异常。启动确认的自动审批审查曾拒绝，随后实际核对发现任务已运行；因此计为已用一次，并保留此异常观察，不在页面控制中断后盲目重试。

第 2 次 `RrziZ1uM7UqvIy3gQN4SDyW7` 从内置浏览器再次预览、核对清单、创建和启动。待批列文件命令在 120 秒内没有收到批准，私有执行回执为 0；公开 `tool_failure` 为 `BashTool / approval_denied_or_expired`。终态 **failed / task_tool_failed**，补丁 0，固定验证 `not_run`。用户事后表示错过了审批；过期请求未复用。两次任务均 `cleanup_confirmed=true`，Docker 列表无残留任务容器。来源 HEAD、refs、index 哈希及原有未跟踪状态保持不变。三次新增额度已使用两次，剩余一次。

用户确认先补限定诊断后，在阶段 B 工作树按 OpenAI SDK 异常类型映射固定 provider 终态类别：认证／权限、限流、格式错误、连接／超时、服务端错误、未知；本地预算耗尽单独记录。异常消息、响应体、URL、凭据不进入 worker／父进程消息，未知异常仍折叠为 `provider_failed`。假模型及本机 worker socket 测试先红后绿，定向 **48 passed**。指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的全项目非 Docker 回归 **736 passed、3 skipped、35 deselected**，1 条既有 Starlette 弃用警告；Ruff `--no-cache src tests` 与 `git diff --check` 通过。该改动不调整预算、重试、源码范围或审批边界，不能回溯第 1 次的 provider 根因。三个原始 Grep/Bash 修复目标未完成，没有生成补丁、没有执行固定验证；没有补跑正式槽位、改写冻结或 ignored 证据、应用补丁到来源、提交、push 或修改远端。

---

## 49. 2026-09-29 五次新额度中的前三轮

用户再授权从现在起最多五次真实运行，并允许助手在审查具体命令后自行逐条审批；先前未用的一次不叠加到五次。仍沿用固定来源提交、27 文件选中范围、已明确的 provider 目的地、`qwen3.5-flash`、镜像、每轮 16 请求／30000 token／1200 秒和固定验证。用户从保有任务 provider 设置的终端重启本机工作台；新服务启动时间晚于 provider 类别代码修改，健康、任务及运行能力门均可用。

首轮 `s9y_GZNQ6tK9sWFXa91MEs49` 从内置浏览器预览、准备，清单显示固定 SHA、读写范围、模型、镜像、`network=none`、预算与验证命令一致。启动按键遇到 JavaScript 确认中断，先核对页面确认任务已运行，未重复提交。待批 `find . -type f -name "*.py" | head -50` 在隔离工作目录且命令网络关闭，助手按新授权逐条批准；公开事件记录 approved。审批后 8 条工具结果均为 `passed`，最终 **failed / provider_budget_exhausted**；补丁 0 文件、固定验证 `not_run`，任务清理确认。公开结果不区分触发的是请求次数还是已报告 token 上限，也不给出精确 provider 请求数；不能将其推断为原始 Grep/Bash 缺陷的根因或修复结果。五次额度已使用一次，剩余四次。

用户同意保持预算及范围不变、将三个修复目标拆成聚焦试点。第 2 轮 `O6GyUZBfLvmtwsGrOVY5ZYgU` 聚焦 Grep 符号链接边界，浏览器预览与准备后，JavaScript 运行确认控制连续超时；先只读核对任务仍为 `prepared`，后用同一本机工作台 API 核对清单并启动。只读列文件命令由助手按新授权逐项核对并批准，执行回执 1 条。终态 **failed / task_tool_failed**，新增脱敏摘要为 `FileReadTool / scope_denied`，补丁 0，固定验证 `not_run`；被拒绝路径没有公开，不能判定具体入参或根因。

第 3 轮 `S4oVjjNUxJahxiqZgeY8Sa5U` 聚焦 Grep 非法正则与读取上限；浏览器确认标签仍无响应，改用本机 API 预览、准备、核对固定清单并启动。没有命令待批；公开 CodeAgent 后续 11 条工具结果均为 `passed`，终态 **failed / provider_budget_exhausted**，补丁 0，固定验证 `not_run`。不能由工具事件数推断精确 provider 调用量或 token 数，也不能据此确证通用提示为根因。三轮任务均清理确认，Docker 列表无任务容器残留；来源 HEAD、refs 关系、index 哈希及原有未跟踪状态保持原状。五次额度已用三次，剩余两次。

代码检查显示任务版 CodeAgent 仍使用通用提示，其中要求每项待办开始、完成时更新进度；已向用户提出仅对隔离任务精简提示并以假模型先行验证的具体设计，待回复前不修改行为。没有应用补丁到来源、提交、push、改动远端、读取 `.env` 值、修改冻结分析或 ignored 证据，也没有补跑正式 Rich/Click 槽位。第 2、3 轮实际启动／审批走本机 API，不能记为完整浏览器操作。

---

## 50. 2026-09-30 Task 10 隔离任务提示与第 4 次试点

用户批准任务版 CodeAgent 使用简短系统提示，优先按准确路径读取并尽早编辑、验证已有文件，待办状态按实际变化更新；普通 CLI/TUI 保持原提示。无 provider 假模型测试先红后绿，**2 passed**。首次把提示放入 `src/mokioclaw/prompts/stage3.py` 后，完整测试暴露 Click 冻结身份哈希不匹配；将新提示移到 `src/mokioclaw/agents/code_agent.py`，提示文件恢复 Git 原字节，定向提示及 Click 身份测试 **3 passed**。首次全量命令误纳入 Docker 标记测试，得 **30 failed、739 passed、3 skipped、4 deselected**；除 Click 身份项外，其余失败属于本轮 Docker 测试环境。改用 `-m 'not docker'`，指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 的完整非 Docker 回归 **738 passed、3 skipped、35 deselected、0 failed**，1 条既有 Starlette 弃用警告。Ruff `--no-cache` 和 `git diff --check` 通过。没有把失败的首次运行或未重跑的 Docker 测试记作通过。

新 worker 由独立 Python 进程从阶段 B 工作树 `src` 导入代码，本机运行能力门仍开放。第 4 次新额度通过本机 API 在固定来源 SHA、27 文件范围、镜像、模型、provider 目的地、预算与验证命令下创建并运行 Bash 输出上限聚焦任务 `OuufbzR3ud-AQ-rKZLGjJUt0`。预览 179494 字节、0 阻断；没有待批命令。公开事件在 `entry` 后到 `code_agent`，其后五条工具结果均为通过，最终 **failed / provider_budget_exhausted**，补丁 0，固定验证 `not_run`，清理确认。公开事件不给出精确 provider 请求或 token 用量，不能确认是哪个上限触发，也不能把提示与失败作因果断言。来源 HEAD、与本地 `origin/master` 的 0/0 关系及原有未跟踪状态不变。五次额度已用四次，剩余一次，暂留待无 provider 的阶段预算调查后再判断。未应用补丁到来源、提交、push、改远端、读取 `.env` 值、补跑正式 Rich/Click 槽位或改写冻结／ignored 证据。

---

## 51. 2026-09-30 Task 10 无 provider 阶段预算调查

用一次性假模型和临时工作区实际穿过任务图，复核共享预算在入口、规划、CodeAgent、verifier 之间的计数。完整假流程各阶段模型调用为 **1／3／3／1**，共 8 次，固定验证由无 Docker 的假网关返回。模拟 30000 token 累计上限时，入口 1 次、规划 2 次、CodeAgent 5 次后即报 `provider_budget_exhausted`，公开形态为规划工具结果 1 条与 CodeAgent 后结果 5 条；模拟 16 次请求上限时，入口 1 次、规划 2 次、CodeAgent 13 次后才报同一类别。三个探针均由断言核对通过，未调用 provider。现有任务 provider 与图注入测试使用指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 得 **40 passed**。

重查三项真实预算终态的公开事件，规划交接前各 1 条工具结果，CodeAgent 交接后分别 8、10、5 条；第 3 轮此前所写 11 条是两阶段总和。由当前调用与事件投影路径，入口固定 1 次、交接前规划至多 2 次、CodeAgent 每条已公开工具结果至多对应 1 次模型调用，因此失败前启动调用数上界分别为 **11、13、8**，均小于固定 16 次。结合 `_TaskModel.invoke` 的两种预算检查，三轮可以归于**已报告累计 token 达到或超过 30000**，而非请求次数上限。假模型中的分阶段 token 值只是机制测试；历史真实任务的精确请求数、逐阶段 token 分摊及最后一次响应可能超出阈值多少，因未保存该计数，仍不可恢复。没有证据证明提示修改或任一原始 Grep/Bash 缺陷造成高 token 消耗。最后一次额度继续保留；若需精确阶段数据，先审阅仅输出固定阶段名和数值计数的脱敏诊断，再做假模型验证。本轮未修改产品行为、调用真实 provider、运行任务或 Docker，也未触碰来源、冻结／ignored 证据、提交、push 或远端。

---

## 52. 2026-09-30 Task 10 固定阶段用量诊断（无 provider）

用户审阅并认可只公开固定阶段、已启动模型调用数和已报告 token 数的设计后，在阶段 B 工作树给任务模型包装器增加六个显式阶段的独立计数。`bind_tools` 保留阶段，规划中嵌套的 CodeAgent 调用不再混入规划计数。worker 在正常结束或异常退出工作流时发布一条跨 attempts 累计的 `budget_usage` 快照，当前 attempt 仅用于事件身份；父进程只接受完整固定字段和有界非负整数，不传播额外原始数据。页面显示各阶段数值，缺少快照时说明用量未知。失败调用计入已启动调用，但不等于 provider 已接收或计费；缺失 usage 时显示已知部分并保持 `usage_unavailable` 终态。历史任务不可回填。

无 provider 假模型与任务图、worker 通道及页面脚本测试先红后绿，覆盖正常完成、跨两次尝试、token 和请求上限、provider 异常、缺失用量、字段拒绝及私有内容丢弃。最终指定 Windows Python、显式 `PYTHONPATH=src`、独立 `--basetemp`、禁用 pytest 缓存的全项目非 Docker 回归为 **754 passed、3 skipped、35 deselected、0 failed**；3 项 skip 为既有 Windows 符号链接能力限制，1 条既有 Starlette 弃用警告。Ruff、JavaScript 语法、`git diff --check`、目标文件常见密钥格式扫描通过；主项目 Rich 三份与 Rich–Click 四份冻结文件的只读哈希与第 36 节一致。本轮未重启旧工作台父进程；新事件投影在后续真实任务前需要由重启后的父进程加载。最后一次真实运行额度未使用，实际阶段用量、零补丁和固定验证未运行仍未解决；未调用 provider、启动 Agent 或 Docker、补跑正式槽位、改写来源／冻结／ignored 证据、提交、push 或修改远端。

---

## 53. 2026-09-30 Task 10 重启后 Grep 聚焦试点

用户重启本机工作台并另给最多三次真实运行额度。本轮只使用一次：固定提交 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`，27 文件／179494 字节／0 阻断，固定五项范围和原模型、镜像、无网络、预算及验证命令。页面预览按钮未显示结果，故本次预览、创建、运行经同一工作台本机 API；任务 `Bj4zjkW1CWSkib4QoDD2ZahW` 在核对 `prepared` 和完整运行门后单次启动，没有待批命令。公开终态 **failed / task_tool_failed**，`FileEditTool / scope_denied`，补丁 0，固定验证 `not_run`。

新增阶段快照首次给出真实已报告用量：入口 **1／1086**、规划 **2／3815**、CodeAgent **4／36527**（调用／token），其它固定阶段 0，合计 **7／41428**。这是 worker 的已启动调用与 provider 返回的有效 usage 累加，不等于 provider 已接收或计费请求数；单次响应可越过任务的 30000 token 门，本次实际先因工具失败结束。无 provider 复现表明 `FileEditTool` 的旧文本缺失／不唯一也返回 `task_file_access_denied`，投影后与真实范围拒绝同为 `scope_denied`；本次事件不能确定实际失败路径或内容，更不能确认 Grep 原始缺陷根因。先改进此受控类别区分并假模型验证，再决定是否动用剩余两次；未做同配置重跑。来源 HEAD、与本地 `origin/master` 的 0/0、index SHA-256 `80809046112C918D18367AEFEB36A318A39BD5E8EC764D00178B539E1ADA1BF4` 及原有未跟踪状态均不变。只读 Docker 列表遇权限拒绝，未声称容器列表已检查。未应用补丁到来源、提交、push、改远端、读取 `.env` 值或触碰冻结／ignored 证据。

---

## 54. 2026-09-30 Task 10 编辑误分类与第二次聚焦试点

阶段 B 任务版 `FileEditTool` 对文本未命中／非唯一改用内部 `task_edit_match_failed`，公开归为现有 `tool_rejected`；路径／文件拒绝仍为 `scope_denied`。新增真实文件工具测试先 **2 failed、5 passed**，最小修正后 **7 passed**；全项目非 Docker 回归 **756 passed、3 skipped、35 deselected、0 failed**，1 条既有弃用警告，Ruff 与 `git diff --check` 通过。均使用指定 Windows Python、显式 `PYTHONPATH=src`、各次独立 `--basetemp`，无 provider。工作台父服务无须加载新公开枚举，新 worker 按现有启动路径从阶段 B 工作树导入修正。

第二轮新授权任务 `B2MdMCP7IObV4BCeA_gPdgRK` 在固定来源、27 文件范围、原预算和验证清单下经本机 API 创建、核对并启动；终态 **failed / provider_budget_exhausted**，没有待批命令或工具失败。阶段累计入口 **1／586**、规划 **2／4021**、CodeAgent **4／37227**，总 **7 次已启动调用／41834 已报告 token**，其它阶段 0。隔离副本仅新增 `tests/test_tools.py` 25 行，Grep 实现无修改，固定验证 `not_run`。新增测试的搜索模式 `should be found` 不匹配越界目标 `This should not be found`，即使链接被读取也可能通过，故不构成有效安全回归。未应用部分补丁到来源。新给三次额度已用两次、剩余一次；当前固定预算下尚无完成的修复，暂不盲目重试。未提交、push、改远端或冻结证据。

---

## 55. 2026-09-30 Task 10 无 provider 手工候选验证

固定镜像中显式覆盖原 `/bin/sh -lc` entrypoint 后，以无网络、非特权、只读源码挂载运行第二轮原始部分测试得 **1 passed、43 deselected**，确认它在未修实现上不报警。Windows 本机没有符号链接创建权限，故另复制固定任务 baseline 到临时目录，在该副本中增加越界文件和普通文件使用同一搜索词的测试。容器中该测试先 **1 failed、43 deselected**，结果确实包含越界链接；仅在临时副本的 Grep 遍历中跳过符号链接候选后 **1 passed、43 deselected**。原定验证命令在手工候选上 **42 passed、2 deselected**，另有只读挂载的 pytest 缓存警告。Agent 第二轮的固定验证状态仍为 `not_run`，两者不能混记。手工候选补丁保存为 `docs/task10_grep_symlink_candidate.patch`，对干净 baseline 的 `git apply --check --whitespace=error-all` 通过；未应用到来源、任务产物或阶段 B 冻结源码。候选尚未证明目录链接或并发替换竞态的安全性，不能称为最终 Grep 修复。剩余一次真实运行额度继续保留。

---

## 56. 2026-09-30 最后一次授权试点：80000 token 上限

按用户明确要求，保留固定来源 `4ca74f958301228cb48cb1e9c7d15463fa1d8e74`、27 文件／179494 字节、五项读写范围、清单摘要、模型、镜像、无网络、任务说明、16 次调用、1 attempt／1200 秒／3072 输出 token 和原验证命令，仅把任务已报告 token 上限由 30000 改为 **80000**。任务 `6QKRh-o6P2mrL8yQBLNSIW7B` 在本机工作台经 API 预览、准备、核对清单后单次启动，没有命令待批；本次三次额度已全部使用。

终态 **failed / task_tool_failed**，固定摘要 **FileEditTool / tool_rejected**；公开信息不足以确定具体编辑内容或失败路径。预算快照：入口 **1／577**、规划 **2／3941**、CodeAgent **6／63752**，合计 **9 次已启动调用／68270 已报告 token**，其它阶段 0；不是 token 或调用次数耗尽。补丁仅在隔离任务副本，可用摘要为 **2 文件、+32/-0**，Agent 固定验证 **not_run**，清理确认且无 MokioClaw 容器残留。

---

## 57. 2026-09-30 Task 10 完整 Grep 链接边界（无 provider）与 tool_rejected 分类调查

先按根 `SKILL.md` 完整重读两份设计、瓶颈文档、交接全文与 §51–56，只读重新核对三处 Git：阶段 B 工作树原未提交内容已提交为 `dc9f016`（当前干净），主项目 `main=4134081` 仅比它多两个纯文档提交（代码无差异），试点来源仍为 `4ca74f95`、与本地 `origin/master` 0/0。全程无 provider、无真实 Agent、无 Docker。

**完整链接边界在隔离副本实现。** 开发副本复制最后一次真实任务的 `workspace/work`（含其部分补丁）到 `MokioAgent-task10-private/grep-boundary-dev-20260930/work`，仅改动 `src/mokioclaw/tools/grep_tool.py` 与 `tests/test_tools.py`。边界为：显式 `os.scandir` 递归枚举（弃用 `rglob`，不依赖 pathlib 版本语义），每目录列出前后逐组件 `lstat`（到 workspace 根含）链核实、不一致即丢弃列表；reparse point（symlink/junction/全部 reparse，经 `st_reparse_tag` 与 `S_ISLNK`）条目跳过、目录链接不递归；候选文件 `os.open` 后以 `os.fstat` 核对 `(st_dev, st_ino)` 与枚举身份一致才读，闭合检查到打开的替换竞态；显式单文件路径加 `realpath` 包含复检；身份 `(0,0)` 一律 fail-closed 跳过并以 `skipped_insecure` 计数；字节解码复现 `read_text_lossy` 编码阶梯。Windows 关键发现：`DirEntry.stat(follow_symlinks=False)` 返回 `dev=0, ino=0`，必须 `os.lstat(entry.path)` 取身份。

**测试先红后绿。** 新增 10 个边界测试，搜索词与越界内容相同。部分补丁状态红：**6 failed、3 skipped、43 passed**（junction 兄弟目录、目录链接、打开身份不匹配、显式越界路径、链接参数越界真实失败；本机 3.13 `rglob` 确认会进入 junction；Agent 原 symlink 测试因本机无 symlink 权限 OSError，补能力门控）。修复后绿：**48 passed、4 skipped、2 deselected**（skip 均为 symlink 权限门控）；副本内 test_checkpoint/test_session **11 passed**；对干净 baseline `git apply --check --whitespace=error-all` 通过（顺带清理部分补丁两处尾随空格）；阶段 B ruff 配置检查两个文件通过。补丁存于 `grep-boundary-dev-20260930/patchcheck/grep-boundary-complete.patch`。以上全部为独立测试，Agent 固定验证仍 `not_run`；symlink 专属 3 项门控测试需 POSIX/Docker 复核；目录列表中途替换测试在旧实现上空转（3.13 `rglob` 无 Python 级枚举 seam），旧实现越界由静态 junction 测试承担。

**FileEditTool / tool_rejected 用假模型定位到类别边界。** 真实 `TaskFilesystem`+任务工具+`execute_code_agent_tool` 一次性探针证明：`tool_rejected` ⇔ schema 合法、`old_text` 非空、路径在范围且可读、且出现次数≠1；缺文件/越界/空 `old_text` 为 `scope_denied`；schema 参数错误为 `invalid_arguments`。可复现同签名机制：行号前缀片段、CRLF/LF 不一致、片段重复、过期片段；任务工具失败是终止性的，attempt 内无重试。公开事件精确为 `FileEditTool/tool_rejected` 且无参数泄漏；分类实现无缺陷，任务提示未复述逐字唯一匹配属提示缺口，是否补提示或改为非终止性属设计变更，未获批不实施。不能回溯最后一次真实任务的具体原因。

**回归与漂移。** 全项目非 Docker 回归（指定 Python、显式 `PYTHONPATH=src`、外部独立 `--basetemp`、禁用 pytest 缓存）**755 passed、4 skipped、35 deselected、0 failed**：skip 从 3 变 4，新增 `test_task_ui_restore.py` 因 Node.js 已从本机消失跳过（JS 语法检查同样无法执行），总数 759 与此前一致，属环境漂移。另记录：`--basetemp` 放在 git 仓库内会使 catalog/git_reader 两个非仓库测试误报失败（已用外部 basetemp 复核通过）。Ruff `--no-cache src tests` 通过；主项目 Rich 三份与 Rich–Click 四份冻结文件只读 SHA-256 与第 36 节一致。未应用补丁到来源或阶段 B 冻结源码，未提交、push、改远端、读取 `.env` 值或补跑正式槽位；真实运行额度为零，新试点须重新逐项授权。

---

## 58. 2026-09-30 Task 10 三次授权真实试点：Grep 聚焦（额度用尽）

用户授权三次真实运行、命令批准由助手执行；工作台重启至本机 `127.0.0.1:56818`（非持久入口）。固定配置沿用 §18（来源 SHA、27 文件／179494 字节／清单摘要 `9063265bec…`、五项范围、`qwen3.5-flash`、镜像、`network=none`、1 attempt／1200 秒／16 调用／80000 token／3072 输出、原固定验证命令）；三轮均 API 预览并逐项核对 run-policy 后单次启动。结果依次：`9BULBLf9dU5IFh_APBMDupGJ` **failed / provider_budget_exhausted**（11 次调用／92436 已报告 token）；`qAam453za3Tn6sU7sc_7YsmF` **failed / task_tool_failed（`FileEditTool / tool_rejected`）**（7／48099）；`BbWpkINEt1tHTCJBoa585h-L` **failed / provider_budget_exhausted**（8／80317）。三轮 `cleanup_confirmed=true`、无 MokioClaw 容器残留；来源 HEAD、0/0 关系、index 与原有未跟踪文档不变；未应用补丁、未提交、push、改远端、读 `.env` 值。**额度用尽，三个原始目标仍无完成修复，固定验证均为 `not_run`。**

只读审阅三轮私有副本：第 1 轮实现又用已禁用的 `startswith(root)` 前缀判断、新增 1 个搜索词与越界内容匹配的真回归，获批的 pytest 两用例通过，但该命令在可写挂载留下 `.pytest_cache`／`__pycache__`，`collect_patch` 的 `_scan` 无缓存忽略规则，补丁整体 `patch_unavailable(change_outside_write_scope)`——**新的工作流缺陷：任何 Agent 运行 pytest 都会使补丁不可用**。第 2 轮实现改 `os.scandir`+跳过链接，但身份核对用"打开后再 stat 路径"自比，竞态窗口未闭合，随后编辑匹配失败即终止。第 3 轮按"小文件 FileWriteTool 整文件写回"策略全部写入成功（绕开了编辑匹配失败），架构最接近完整边界（lstat、枚举身份、打开核对、`(0,0)` fail-closed、`skipped_insecure`），但把枚举身份统一改写为 `(0,0)` 使竞态核对成为死代码，另有 `os.read` 只读前 64KB 的截断；两个新测试（文件链接＋目录链接、断言 `skipped_insecure`）质量好，未及自测即撞 80000 门。

跨轮结论：CodeAgent 每次调用已报告 1.0 万–1.3 万 token，80000 门只够约 6 次调用，读+写即用尽，第 1、3 轮都无法收尾；FileEditTool 匹配失败是单点致命步，第 3 轮证明整文件重写可绕开；补丁收集器需缓存产物忽略规则（或命令策略禁写字节码缓存）。三项均为设计/工作流语义调整，未经批准不实施。无 provider 开发副本 `grep-boundary-dev-20260930` 的 10 个边界测试仍是当前最完整参照（含能测出第 3 轮死代码缺陷的身份不匹配用例），其 symlink 门控用例需 POSIX/Docker 执行。新真实试点须重新逐项授权。

独立只读审查发现补丁用路径字符串前缀判断越界，固定镜像的无 provider 临时夹具证明兄弟目录 `work-extra` 可经 `work` 内链接被读到；检查至打开的替换竞态仍未处理。隔离 work 上独立执行同一固定 pytest 命令得 **42 passed、2 deselected**，另有只读挂载缓存警告，但不能记为 Agent 验证通过；`git apply --check --whitespace=error-all` 发现两处新增尾随空格。来源 HEAD、相对本地 `origin/master` 的 0/0、index SHA-256 `80809046112C918D18367AEFEB36A318A39BD5E8EC764D00178B539E1ADA1BF4` 及原有未跟踪状态保持不变。未应用补丁到来源、提交、push、改远端、读 `.env` 值或动冻结／ignored 证据。此补丁不能称为完整链接修复；后续真实试点须重新授权次数。

---

## 59. 2026-09-30 Task 10 试点工作流修复（补丁缓存噪声 + 编辑匹配可重试）

按用户指示先更新主项目瓶颈文档（三次失败与修复项），再在阶段 B 工作树以测试驱动修复两项真实运行暴露的工作流缺陷，全程无 provider。`task_patch._scan` 把 `__pycache__/`、`.pytest_cache/` 目录与 `*.pyc`/`*.pyo` 文件在 baseline/work 两侧对称剪除：它们不再触发 `change_outside_write_scope`、不进入补丁、不影响限额；非缓存越界改动仍整体拒绝（3 个新测试覆盖不阻断、对称剪除、仍拒绝）。`task_executor` 容器创建参数固定注入 `PYTHONDONTWRITEBYTECODE=1`，参数测试改为断言唯一 `--env` 且固定值、宿主 provider 变量不出现。`execute_code_agent_tool` 在任务模式下把 `task_edit_match_failed` 作为普通工具结果回传模型（公开投影 `tool_result/failed`，不发 `tool_failure`、不终止 attempt）；范围拒绝等其余失败仍终止（2 个单元测试 + 1 个全图假模型测试：坏编辑→错误回传→好编辑成功→流程完成）。任务 CodeAgent 提示补充整文件重写优先与逐字唯一匹配要求，提示测试扩展。阶段 B 设计增补"2026-09-30 Task 10 试点修复补充"段落；下轮真实运行预算建议 100000（设计上限）由授权明确。

调试侧记录：全图测试三次自伤均为测试侧问题（假模型成功后仍循环改单行锚点、夹具 `write_text` 默认 CRLF 使带换行 old_text 匹配失败、断言短语与提示词原文不一致），真实任务副本为 LF 不受影响。最终全项目非 Docker 回归（指定 Python、显式 `PYTHONPATH=src`、外部独立 `--basetemp`、禁用 pytest 缓存）**761 passed、4 skipped、35 deselected、0 failed**（755+6 新测试；4 个 skip 为 3 项 symlink 能力 + 1 项 Node.js 缺失漂移）。Ruff `--no-cache src tests`、`git diff --check`、改动文件秘密格式扫描（0 命中）通过；Click 冻结身份校验随全量回归通过，冻结源码未动。未调用 provider、未启动真实 Agent 或 Docker、未应用补丁到来源、未提交、push 或修改远端；下一轮真实运行待用户单独授权。

---

## 60. 2026-10-02 Task 10 第二批五次试点：四项修复落地、Agent 实现通过独立验证

用户重启工作台（`127.0.0.1:58182`）并授权五次真实运行（token 门 100000）。五轮依次：`1neWBSz…` 预算耗尽（103284 token，实现首次正确锚定枚举身份但有显式路径/glob/fd 缺陷）；`xk6end…` `BashTool/tool_rejected`（Agent 转录把 `\n` 写成真实换行致测试文件 SyntaxError，pytest 退出码 2 被判终止）；`YIX2wq…` **worker_failed**（模型非法 Bash 参数经代理转发被父进程消息校验拒绝）；`gW5tia…` 预算耗尽（自愈循环首次工作：pytest 失败→修复→通过，但任务说明内嵌验收测试位置错误——"范围外"目录建在工作区内——驱动不可修复迭代）；`wbIVH4…` `unknown/unknown`（模型幻觉工具名即终止）。五轮均清理确认、来源不变。

针对第 2、3、5 轮暴露的缺陷完成三项 TDD 修复：(1) BashTool 已执行命令（含 `exit_code`、无 `error`）的非零退出改为可重试工具结果；(2) `RemoteTaskGateway.run` 发送前本地校验参数（镜像父进程网关规则），`invalid_task_command` 本地返回且可重试；(3) 三个分发点的 `unknown tool:` 错误改为回传模型。设计增补"2026-10-02 试点修复补充（续）"。第 2 轮同时实测容器级 `PYTHONDONTWRITEBYTECODE=1` 有效（work 无字节码缓存）。第 4 轮失败根因是任务说明内嵌测试自身位置错误（非实现缺陷）——把"范围外"目录修正到 `tmp_path.parent` 后，该轮 Agent 实现以固定镜像只读容器运行原固定验证命令得 **42 passed、2 deselected**，即 Grep 符号链接边界修复本体已被 Agent 独立达成（scandir、lstat 跳链接、(0,0) fail-closed、枚举身份竞态核对、skipped_insecure 计数）。

最终全项目非 Docker 回归 **768 passed、4 skipped、35 deselected、0 failed**（+6 新测试）；Ruff、`git diff --check`、秘密扫描通过；Click 冻结身份校验随回归通过。五次额度用尽，下一次试点须重新授权；建议使用第 4 轮说明+修正版测试，并正视 100000 token 上限与迭代成本的矛盾。
