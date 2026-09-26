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
