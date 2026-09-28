# MokioClaw Local CodeAgent Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地工作台从已登记仓库的固定提交创建受控 CodeAgent 任务，并审阅独立副本中的补丁与验证证据。

**Architecture:** 保留现有只读提交 API 与 `review-priority-v1`，新增任务预览、准备、状态与脱敏结果接口。固定 SHA 下的许可普通文件复制到来源仓库之外的任务目录；假执行器先贯通页面，再引入统一命令审批、容器执行和完整工作流。真实 provider 试点另设用户授权门。

**Tech Stack:** Python ≥3.13、现有 Typer/FastAPI/Uvicorn/LangGraph、Git CLI、原生 HTML/CSS/JavaScript、Docker 命令容器、pytest、Ruff；不新增数据库、Node 构建或远端服务。

**Spec:** `docs/superpowers/specs/2026-09-28-mokioclaw-local-codeagent-dashboard-design.md`。执行者须先按项目根 `SKILL.md` 完整阅读 V1 设计，再读本设计与本计划。

## Global Constraints

- 阶段 B 只接受启动时登记的本地仓库 ID、完整 base SHA 和历史锚；保留 V1 只读 API 与 `review-priority-v1` 语义，不自动从优先级启动 Agent。
- `--task-root` 必须由启动者显式给出，并位于所有来源仓库及冻结证据目录之外；缺少该参数时旧 dashboard 保持只读，任务执行入口不可用。
- 预览只读 Git 树元数据；准备只读取用户批准范围中的普通 blob。`.env`、凭据／私钥、ignored、未提交文件、symlink、gitlink、LFS 指针与不安全路径不得进入任务副本。
- 上限为路径选择 100 项、普通文件 5,000 个、单文件 4 MiB、复制总量 64 MiB、描述 4,000 字符、预览 10 分钟、单任务 30 分钟、单命令 600 秒、Agent 尝试 3 次、预先指定验证命令 10 条；超限报错而不截断执行。
- 用户为每个真实任务明示 provider 预算，上限为 20 次请求、100,000 个已报告累计 token、单次 4,096 个输出 token；用量缺失即停止，最后一次调用可能越过累计阈值，不把它称为严格费用上限。
- 所有项目文件修改用 `apply_patch`；不得改写 Rich/Click 冻结分析、清理 ignored 实验证据、补跑正式槽位。
- 不继承全量环境到任务 worker 或命令容器；不从 `.env` 为网页任务自动加载 provider；禁用网页任务的 web search、原始 trace 和 checkpoint。
- 真实运行还要求显式 `--task-image` 固定镜像 digest 与 `--enable-agent`；provider 只取显式进程环境变量 `MOKIO_TASK_API_KEY`、`MOKIO_TASK_MODEL`、`MOKIO_TASK_BASE_URL`，不回退旧变量或 `.env`。任务运行确认与真实试点授权仍独立。
- `TaskSpec` 统一使用设计 §4 的完整字段表；`source_read_scope/source_write_scope/task_scratch_scope` 各司其职，`manifest_digest` 是规范清单的 SHA-256。`network=none` 是不可由用户覆盖的执行策略。第一版无队列，活跃任务冲突返回 `409 task_busy`。
- `POST /api/tasks` 先持久化 `preparing` 任务并立即返回 `202/task_id`，可信后台执行器准备副本；GET 观察进度与结果。attempt 只在 verifier 明确失败后沿用当前 work 重试，审批在切换时失效。
- 所有 Agent 和 verifier 命令经同一网关逐条批准，默认拒绝；`auto` 审批不能用于网页任务。命令只在挂载 work 目录的受限容器内运行，默认无网络、无后台任务。
- 终态必须在归属 worker 退出且全部归属 Docker 容器停止移除后发布；清理不能确认则保持非终态 `cleanup_failed` 并禁用新运行。按可核验的 worker 身份和 `instance_id/task_id/command_request_id` 清理，不波及无关进程／容器。
- work 的软上限为 5,000 个普通文件、总量 128 MiB、单文件 8 MiB；在命令前后和运行中周期检查。CPU／内存／PID 限制不提供宿主 bind mount 的磁盘硬配额。
- `--task-root` 中的 baseline/work/完整补丁不自动删除，可能含私有源码；启动者避开同步盘和公开目录，Web 不提供原始补丁下载。
- 任务结果 API 只返回白名单、限长、脱敏摘要；不返回原始 prompt/response、凭据、完整 endpoint/query、headers、payload、完整 stdout/stderr 或完整补丁。
- 实施代码的授权、Docker 执行、真实 provider/Agent 试点、commit、push、远端修改分别需要用户后续指令。本计划本身只供审阅；本轮不执行步骤。
- 将来运行 pytest 时指定 `D:\envs\codeagent\Scripts\python.exe`，显式设置 `PYTHONPATH=src`，每次用新 GUID 的独立 `--basetemp`。测试只使用临时仓库和假 provider，除非用户另外批准真实试点。

## Review Focus

1. **页面切换仓库或历史锚后提交旧预览**：创建应因 repo/base/anchor/范围摘要不一致而拒绝；Task 2、Task 4 测试。
2. **大小写冲突、symlink、gitlink、LFS 与秘密文件混入范围**：预览明确列出阻断项，准备不读取其 blob；Task 2、Task 3 测试。
3. **verifier 绕过 Bash 审批，或批准一条命令后执行另一条**：统一网关绑定命令与策略版本，单次使用；Task 6 测试。
4. **取消／完成竞态与重启后的残留容器**：按身份清理全部归属资源后才发布终态；不确定时 `cleanup_failed`，迟到事件和审批无效；Task 1、Task 7 测试。
5. **命令更换链接、越界搜索或私有文本进入结果**：每次宿主文件访问重新检查 scope 和 reparse point，投影失败时隐藏字段；Task 3B、Task 5、Task 8B 测试。

## File Structure

| 文件 | 职责 |
| --- | --- |
| `src/mokioclaw/dashboard/task_models.py` | 不可变任务请求／预览／状态／结果数据类型与状态枚举 |
| `src/mokioclaw/dashboard/task_store.py` | 任务 ID、原子状态变迁、幂等键、最小 JSON 元数据、重启恢复 |
| `src/mokioclaw/dashboard/task_source.py` | 固定 SHA 树枚举、范围校验、阻断项与预览身份 |
| `src/mokioclaw/dashboard/task_copy.py` | 许可 blob 复制、baseline/work、路径安全及准备证明 |
| `src/mokioclaw/dashboard/task_patch.py` | baseline/work 差异、文件统计与受限补丁产物 |
| `src/mokioclaw/dashboard/task_filesystem.py` | Web Task 宿主文件工具的统一 scope、路径与 reparse point 检查 |
| `src/mokioclaw/dashboard/task_events.py` | 原始事件白名单投影、限长脱敏与有界事件序号 |
| `src/mokioclaw/dashboard/task_api.py` | 任务路由、请求身份、CSRF／Origin、固定错误结构 |
| `src/mokioclaw/dashboard/task_service.py` | 预览、准备、运行与取消的协调接口 |
| `src/mokioclaw/dashboard/task_approval.py` | 单次命令请求、决定、超时与审批账目 |
| `src/mokioclaw/dashboard/task_executor.py` | 容器命令策略和 `CommandExecutor` 兼容网关 |
| `src/mokioclaw/dashboard/task_worker.py` | 独立进程入口、最小环境、受限 IPC、完整工作流调用 |
| `src/mokioclaw/dashboard/task_worker_control.py` | worker 生命周期、单任务并发、取消、崩溃清理 |
| `src/mokioclaw/dashboard/static/{index.html,app.js,styles.css}` | 任务预览、审批、状态与结果页面；保留三栏提交审查 |
| `src/mokioclaw/dashboard/{api.py,launcher.py}`、`src/mokioclaw/cli/app.py` | 在兼容旧调用的前提下挂接可选任务服务和 `--task-root` |
| `src/mokioclaw/core/{agent.py,state.py,approval.py}`、`src/mokioclaw/tools/{bash_tool.py,grep_tool.py,registry.py}`、`src/mokioclaw/providers/openai_provider.py`、相关 graph 节点 | 显式任务 provider、全工具范围与统一命令网关；旧 CLI/TUI 默认路径不变 |
| `tests/dashboard/test_task_*.py`、相关 `tests/tools/`／`tests/core/` | 临时 Git、假 worker／provider、隔离与网页安全回归 |
| `README.md`、`docs/MOKIOCLAW_LOCAL_DASHBOARD_DEMO.md`、`docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md` | 实际可用边界、启动演示与新鲜验收记录 |

## Phase B1 — 任务契约与预览

### Task 1: 状态机与最小持久记录

**Files:** Create `src/mokioclaw/dashboard/task_models.py`、`task_store.py`；test `tests/dashboard/test_task_store.py`。

**Interfaces:** `TaskSpec` 精确包含 `task_id/repo_id/base_sha/anchor_sha/description/source_read_scope/source_write_scope/task_scratch_scope/manifest_digest/max_seconds/max_attempts/verification_commands/max_provider_calls/max_total_tokens/max_output_tokens_per_call/created_at`；`TaskRecord` 包含状态、当前 `attempt_id`、全任务单调 `sequence`、`failure_kind`、`verification_status` 及归属资源身份；`PublicTaskEvent` 在 `task_models.py` 定义，Task 5 实现投影。`TaskStore.create(spec, idempotency_key) -> TaskRecord`、`transition(task_id, expected, target, update) -> TaskRecord`、`record_event(task_id, attempt_id, event) -> PublicTaskEvent`。`TaskWorkerController.reconcile()` 在 Task 7 提供；重启不能由 store 单独宣布 `interrupted`。

- [ ] 写失败测试：同幂等键同规范请求只创建一次、同键异请求拒绝；重复运行、非法跳转、终态迟到事件、旧 attempt 事件和序号倒退均拒绝；`cleanup_failed` 非终态并阻止新运行；store 重启不抢先宣布 `interrupted` 或重放审批。
- [ ] 用指定 Python、`PYTHONPATH=src`、独立 `--basetemp` 运行 `tests/dashboard/test_task_store.py`，确认因接口不存在而失败。
- [ ] 用 `apply_patch` 实现原子写入／替换与单调序号；任务 ID 随机，磁盘 JSON 不含任务描述、源码、命令输出或 provider 设置。敏感描述仅存受限任务内存，重启后不能自动续跑。
- [ ] 使用新 `--basetemp` 重跑同一测试，确认通过；审阅磁盘元数据字段。

### Task 2: 固定提交树预览与范围身份

**Files:** Create `src/mokioclaw/dashboard/task_source.py`；test `tests/dashboard/test_task_source.py`。

**Interfaces:** `TaskSource.preview(repo_id: str, base_sha: str, anchor_sha: str, source_read_scope: tuple[str, ...]) -> TaskPreview`；`TaskPreview` 包含随机 `preview_id`、规范请求摘要、`manifest_digest`、文件数、总字节数、阻断项与 10 分钟到期时间。`manifest_digest` 是按规范化相对路径稳定排序的 `(relative_path, git_mode, blob_oid, blob_size)` 元组清单之规范 JSON UTF-8 字节的 SHA-256。第一版 `source_write_scope=source_read_scope`，scratch scope 固定为 work 下 `.mokioclaw/task-scratch/`。复用 V1 `RepositoryCatalog` 与 `LocalGitReader` 的 Git 环境／SHA 校验，不改变历史详情 API。

- [ ] 写失败测试：不可达或非完整 SHA、跨仓库复用、空范围、非法相对路径、预览过期／范围变更拒绝；已跟踪 `.env` 与 symlink 只由树元数据识别，测试桩断言从不读取其 blob。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行 `tests/dashboard/test_task_source.py`，确认失败。
- [ ] 用 `apply_patch` 实现 `git ls-tree -r -z` 等有界只读枚举、规范化范围与 `manifest_digest`；按设计 §5 的精确文件名、前缀、后缀和路径段排除规则过滤；禁用 Git 外部程序，保留 V1 超时／输出上限，不使用 checkout/archive/clone。
- [ ] 新 `--basetemp` 重跑，确认通过；审阅 SHA-1/SHA-256、大小写冲突、Windows 保留名、gitlink、LFS 指针识别测试。其中 LFS 指针只对用户已批准的普通 blob 在准备阶段检测，预览标注“待内容检查”，不提前读取内容。

## Phase B2 — 固定提交与独立副本

### Task 3A: 固定提交副本准备

**Files:** Create `src/mokioclaw/dashboard/task_copy.py`；test `tests/dashboard/test_task_copy.py`。

**Interfaces:** `prepare_task(preview: TaskPreview, task_root: Path) -> PreparedTask` 仅从预览的 `base_sha/manifest_digest` 所指普通 blob 建立不可变 `baseline/` 和可写 `work/`；准备完复算清单。`task_root` 位于所有来源仓库、`.git` 和冻结证据路径之外。

- [ ] 写失败测试：task-root 越界；symlink、gitlink、LFS、大小写冲突、路径穿越、单文件及总量超限；预览 A 后 HEAD 变 B 仍复制 A，准备完成后 HEAD 再移动也不改变副本；来源移动、仓库身份替换、对象缺失或清单变更时失败且无可运行副本。双临时仓库的 HEAD、refs、index、status 和 ignored 夹具字节前后相同。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 实现 blob ID 定址读取、安全文件落盘、准备完成后原子发布；准备失败清理或隔离临时副本，绝不发布 `prepared`。
- [ ] 新 `--basetemp` 重跑并核对失败准备无残留可运行状态。

### Task 3B: 统一任务文件边界与补丁收集

**Files:** Create `src/mokioclaw/dashboard/task_filesystem.py`、`task_patch.py`；test `tests/dashboard/test_task_filesystem.py`、`test_task_patch.py`。

**Interfaces:** `TaskFilesystem(prepared: PreparedTask, source_read_scope, source_write_scope, task_scratch_scope)` 为宿主读、写、新建、重命名、删除和递归遍历提供逐次授权操作；`collect_patch(prepared: PreparedTask) -> PatchSummary` 只比较 baseline/work 普通文件，超限或不安全返回 `patch_unavailable`。

- [ ] 写失败测试：绝对路径、`..`、其它 task/baseline/来源目录、symlink／junction／reparse、命令后目录替换为链接、rename 的源或目标越界、delete 与递归 search 越界均拒绝；无法避免检查到打开之间替换竞态时 fail closed；scratch 数据不进入补丁；新增 symlink、越界变更、5,000 文件／128 MiB 总量／8 MiB 单文件触发不可用而不读半截补丁。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行两个目标测试，确认失败。
- [ ] 用 `apply_patch` 实现三种 scope 的统一路径检查与安全文件访问、work 软上限扫描和 baseline/work 补丁收集；完整补丁只放受限 task-root 产物目录，不设下载 API。
- [ ] 新 `--basetemp` 重跑；人工审查 Windows 路径打开机制是否真正防重解析与竞态，无法保证的操作保持拒绝。

## Phase B3 — 假执行页面、受控执行与审批

### Task 4: 任务 API 与写操作防护

**Files:** Create `src/mokioclaw/dashboard/task_api.py`、`task_service.py`；modify `src/mokioclaw/dashboard/api.py`、`launcher.py`、`src/mokioclaw/cli/app.py`；test `tests/dashboard/test_task_api.py`、`test_task_launcher.py`。

**Interfaces:** `create_dashboard_app(catalog, reader, cursor_codec, task_service: TaskService | None = None)` 保持旧三参数用法；`launch_dashboard(paths, *, open_browser=True, task_root: Path | None = None, task_image: str | None = None, enable_agent: bool = False)`。`TaskService.create_task(...) -> TaskRecord` 先持久化 `preparing`，将 `prepare_task()` 交给独立后台执行器，`POST /api/tasks` 立即返回 `202` 和 `task_id`；GET 轮询到 `prepared/failed`。无 `--task-root` 时返回 `task_unavailable` 且只读页面照常工作。

- [ ] 写失败测试：旧 GET 响应字节契约不变；慢 Git 准备时 POST 快速返回 `202/preparing/task_id`、GET 后续观察、准备失败不留下可运行任务；预览 ID 与 repo/base/anchor/范围摘要不匹配、过期、跨任务 ID 访问拒绝；同幂等键同请求返回同一任务、异请求拒绝；active task 的第二个 run 返回 `409 task_busy`；无 Origin、外站 Origin、无／错 CSRF、超长 JSON 或未知字段的 POST 拒绝；异常不回显路径和私有文本。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行 `test_task_api.py test_task_launcher.py`，确认失败。
- [ ] 用 `apply_patch` 实现进程令牌、精确 Origin/Host、请求大小与状态校验；任务路由只接受 JSON 和不透明 ID；CLI 仅新增可选 `--task-root`，不改变旧 dashboard 启动。
- [ ] 新 `--basetemp` 重跑，并运行现有 `tests/dashboard/test_api.py tests/dashboard/test_launcher.py tests/test_cli_smoke.py`。

### Task 5: 假执行器、事件投影与页面纵向切片

**Files:** Create `src/mokioclaw/dashboard/task_events.py`；modify `src/mokioclaw/dashboard/static/{index.html,app.js,styles.css}`、`task_service.py`；test `tests/dashboard/test_task_events.py`、`test_task_static.py`。

**Interfaces:** `project_task_event(raw: dict, task_id: str, attempt_id: int | None, sequence: int) -> PublicTaskEvent` 仅保留设计 §7 的枚举字段；`FakeTaskRunner` 注入 `TaskService`，不导入 provider 或启动真实 Agent。页面以任务 ID 轮询有界序号。

- [ ] 写失败测试：原始 prompt/response、headers、endpoint/query、路径和秘密样例不会出现在 API、页面或任务 JSON；未知字段、错误 task ID、旧 attempt、重复／倒退序号不透传；A/B 仓库切换与迟到仓库／任务响应不串用；假运行显示 preparing/prepared/running/approval/verification/stopping/completed 与失败、取消、`cleanup_failed` 态。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 实现白名单投影、保守脱敏和页面任务面板；只用 `textContent`，保持现有三栏审查与窄屏／键盘可达。假运行控件标明“演示／无 provider”，真实运行能力门默认关闭。
- [ ] 新 `--basetemp` 重跑；使用两个临时仓库的真实回环服务检查选仓库、固定 SHA、预览、准备、假状态、结果和停止后来源不变。

### Task 6: 单次命令审批网关

**Files:** Create `src/mokioclaw/dashboard/task_approval.py`、`task_executor.py`；modify `src/mokioclaw/core/{state.py,approval.py}`、`src/mokioclaw/tools/bash_tool.py`、`src/mokioclaw/graph/architectures.py` 及其它直接验证执行点；test `tests/dashboard/test_task_approval.py`、`tests/tools/test_task_command_policy.py`。

**Interfaces:** `TaskCommandGateway.run(workspace, command, timeout_seconds, max_output_chars) -> dict` 实现现有 `CommandExecutor` 协议；`ApprovalBroker.request(execution_request: ExecutionRequest) -> ApprovalDecision`。`ExecutionRequest` 不可变，规范摘要绑定 `task_id/attempt_id/command_request_id/command UTF-8 bytes/cwd/timeout/image digest/network=none/work-only mount/env allowlist/CPU-memory-PID-output limits/policy_version`；`approval_mode="task"` 只用于该网关，旧 `inline/deny/auto` 行为不变。

- [ ] 写失败测试：所有 Bash 与 verifier 命令先待批；拒绝、审批恰逢超时、重复、跨任务／attempt、命令原始字节、cwd、timeout、image、network、mount、env、资源限制或策略版本任一变更均不执行；attempt 切换作废待决及未消费批准；一次批准只执行一次，两个外观相同但 `command_request_id` 不同的请求不能复用批准；正则未识别的命令仍待批；旧 CLI/TUI 审批测试仍通过。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 实现任务审批模式、`ExecutionRequest` 的规范摘要与有界等待；将 verifier 也接到同一网关，禁止 task 模式退回主机 `shell=True` 或 CLI `auto`。
- [ ] 新 `--basetemp` 重跑，并针对旧 Bash/approval/graph 测试做回归。

### Task 7: 受限容器与 worker 生命周期

**Files:** Complete `task_executor.py`；create `task_worker.py`、`task_worker_control.py`；modify `task_service.py`；test `tests/dashboard/test_task_executor.py`、`test_task_worker_control.py`。

**Interfaces:** `IsolatedCommandExecutor.run(...)` 只挂载 work 目录，镜像固定 digest；`TaskWorkerController.start(task_id) -> None`、`cancel(task_id) -> None`、`reconcile() -> None`。worker 以 `subprocess.Popen` 的显式筛选环境启动，使用仅回环、随机令牌的有界 JSON IPC；最多一个活跃任务。worker 身份使用 PID 加创建身份，每个容器记录固定命名空间下的 `instance_id/task_id/command_request_id` label 和名称。

- [ ] 写失败测试：Docker 参数无来源、baseline、home、socket、provider 凭据挂载，Task A 容器不能挂 Task B work，含 `--network none`、资源限制、只读根与非特权用户；不可用 Docker 时 run 拒绝；两个并发 run 恰有一个 worker，run/cancel、approval/cancel、超时/完成竞态按同一任务锁处理；取消、超时、worker 崩溃先停止匹配 worker 再清理**全部**归属容器，完成前也须清理；worker 已退出但容器仍存活时继续发现并移除；残留容器或无法确认移除时保持 `cleanup_failed` 且不能启动第二任务；重启 reconcile 仅处理身份匹配的旧实例资源，不触碰其它任务／无关容器；清理成功后才发布终态，迟到审批／事件与终态后 Agent 写 work 被拒绝。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败；此步只用假 Docker 命令，不启动真实容器。
- [ ] 用 `apply_patch` 实现执行器与控制器；worker 不读取 `.env`，不继承全量环境，IPC 只接收经校验的任务指令和投影事件。封禁后台命令；输出限长；命令前后及有界周期检查 work 软上限，超限记 `workspace_limit_exceeded` 并清理；Docker 的 CPU／内存限制不得被记录为磁盘硬配额。
- [ ] 新 `--basetemp` 重跑；在获得另行授权的本机 Docker 测试环境前，只报告参数级与假进程证据，不宣称实际容器隔离已验收。

## Phase B3.5 — 真实 Docker、无 provider 沙箱门

### Task 7.5: 临时仓库实际容器验收

**Files:** Test `tests/dashboard/test_task_docker_acceptance.py`；record nonsecret results in `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md` only when implementation and Docker test are separately authorized.

**Interfaces:** 使用 Task 7 的 `IsolatedCommandExecutor` 与 `TaskWorkerController`；此门只接临时仓库、测试镜像和假任务，绝不创建 provider 或真实 Agent 调用。没有本机 Docker 测试授权时保留未通过状态，不以 mock 结果替代。

- [ ] 写可选择运行的验收测试：实际容器只见 work，来源、baseline、home、Docker socket 和 provider 环境不可见；network none 阻断网络，非特权、只读根、CPU／内存／PID 与输出限制生效；取消／超时后容器停止移除，遗留容器可按精确 label reconcile；无关容器不受影响，来源与 ignored 夹具前后不变。
- [ ] 获得单独 Docker 测试授权后，用指定 Python、显式 `PYTHONPATH=src`、独立 `--basetemp` 运行此测试并记录实际镜像 digest、通过项和限制；未获授权时不运行 Docker，明确标记该门未通过。
- [ ] 根据实际结果修复边界问题并重验；所有权与清理不通过时维持真实运行能力关闭。

## Phase B4 — 完整工作流接入与审阅证据

### Task 8A: Provider 上下文与预算

**Files:** Modify `src/mokioclaw/providers/openai_provider.py`、`src/mokioclaw/core/agent.py`、`src/mokioclaw/dashboard/task_worker.py`；test `tests/dashboard/test_task_provider_context.py`。

**Interfaces:** `ProviderSettings` 只取 `MOKIO_TASK_API_KEY/MOKIO_TASK_MODEL/MOKIO_TASK_BASE_URL` 三项显式环境；`TaskRunContext` 注入显式模型工厂、累计 provider 用量账本及 `allow_web_search=False/trace_mode="off"/checkpoint_mode="off"`。旧 CLI/TUI 入口默认行为不变。

- [ ] 写失败测试：缺任一必需任务设置时零 provider 调用；请求数阈值、累计已报告 token 阈值或用量缺失时下一次调用前停止；`max_output_tokens_per_call` 实际进入模型请求；最后一次可能越限如实记录；任务上下文不读 `.env`／旧变量，含 API key／URL query 的 provider 异常被脱敏，凭据不进入命令容器、JSON、日志或事件；旧入口回归不变。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 实现显式设置与预算；不以 token 上限承诺固定金额。
- [ ] 新 `--basetemp` 重跑，审阅任务路径上每个 `create_model()` 调用点。

### Task 8B: 宿主文件工具统一接入

**Files:** Modify `src/mokioclaw/tools/{registry.py,grep_tool.py,file_tools.py}` 及 Notepad／Search 的实际注册点；test `tests/tools/test_task_scope.py`。

**Interfaces:** Task 3B 的 `TaskFilesystem` 是 Web Task FileRead/FileWrite/FileEdit/Grep/Search/Notepad 和上下文枚举的唯一文件访问入口；普通 CLI/TUI 工具路径维持原行为。

- [ ] 写失败测试：read/write/scratch 各只访问对应 scope；绝对路径、`..`、跨任务、baseline/来源、链接与 junction、rename/delete/递归 search 越界均拒绝；命令后把目录改成链接再调用宿主工具仍拒绝；旧工具测试不受影响。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 将所有 Web Task 文件工具接到同一 `TaskFilesystem`，修复 Grep 递归链接路径；无法可靠无竞态打开的操作 fail closed。
- [ ] 新 `--basetemp` 重跑并逐项审阅工具注册表，确认不存在绕过入口。

### Task 8C: 图节点与命令网关注入

**Files:** Modify `src/mokioclaw/graph/{nodes.py,architectures.py,workflow.py}`、`src/mokioclaw/agents/code_agent.py`、`src/mokioclaw/core/{state.py,approval.py}`；test `tests/dashboard/test_task_graph_injection.py`。

**Interfaces:** `stream_agent_events(..., task_context: TaskRunContext | None = None)` 保持旧调用兼容；task_context 将 Task 8A 的模型工厂、Task 8B 的文件工具、Task 6 的 `TaskCommandGateway` 注入所有 planner/CodeAgent/verifier 节点。

- [ ] 写失败测试：假模型遍历 entry→planner→CodeAgent→verifier，每个节点均使用注入模型；模型生成命令及验证命令均经网关审批，无直接主机 `CommandExecutor.run()`／`shell=True`；attempt 切换条件仅为明确 verifier 失败，旧批准失效且 work 继承；provider／工具／拒绝／超时不自动重试。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 接入上下文与 attempt 规则，不改变旧 CLI/TUI 默认入口。
- [ ] 新 `--basetemp` 重跑，并代码审阅全部直接 `create_model()`、`CommandExecutor.run()` 调用点。

### Task 8D: 完整假 provider 工作流

**Files:** Complete `src/mokioclaw/dashboard/task_worker.py`、`task_service.py`、`task_events.py`；test `tests/dashboard/test_task_workflow.py`。

**Interfaces:** `TaskWorkerController.start(task_id)` 使用 Task 8C 的完整图而非单独 `run_code_agent()`；只接假 provider／假容器完成端到端验收，worker 向服务发送经白名单投影的 `PublicTaskEvent`。

- [ ] 写失败测试：完整 entry→planner→CodeAgent→verifier 的两次 attempt、验证失败后沿用 work、批准按 attempt 作废、预算跨 attempt 累计；原始 prompt/response、凭据、trace/checkpoint 不落盘；provider、工具、审批、取消和总超时各自正确停止且不自动重试。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 串接完整工作流与投影，保留旧 `stream_agent_events` 行为。
- [ ] 新 `--basetemp` 重跑，并对照图节点清单核实没有真实 provider 调用。

### Task 9: 结果、验证与边界验收

**Files:** Complete `task_patch.py`、`task_events.py`、`task_service.py` 和任务页面；test `tests/dashboard/test_task_result.py`、`test_task_end_to_end.py`；modify `README.md`、`docs/MOKIOCLAW_LOCAL_DASHBOARD_DEMO.md`、`docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`。

**Interfaces:** `TaskResult` 含 `base_sha/status/failure_kind/changed_files/patch_summary/verification_results/limitations`；每条验证记录含确切命令、批准 ID、退出码、时长、通过／失败／未运行与脱敏／截断标志。完整补丁只保留在任务本地受限产物，不设网页下载或来源应用接口。

- [ ] 写失败测试：无补丁、修改／新增／删除、二进制、无效 UTF-8、symlink、疑似秘密、超限 work 各有正确摘要或 `patch_unavailable`，不输出半截内容；`completed + verification_failed`、`cancelled + partial evidence`、provider 失败、工具失败和补丁失败分别记账；每条验证结果绑定实际命令与批准 ID、退出码和耗时；HTML／控制字符安全处理；两仓库任务互不串用。端到端夹具比较来源 HEAD、refs、index、状态及 ignored 文件字节前后相同。
- [ ] 用指定 Python、显式 `PYTHONPATH=src`、新 `--basetemp` 运行目标测试，确认失败。
- [ ] 用 `apply_patch` 完成结果页与文档；说明 `--task-root` 中私有 baseline/work/完整补丁无限期留存且启动者负责清理、避免同步盘／公开目录、源码范围、审批、Docker 能力门、真实试点授权、截图隐私和“任务完成／验证通过”的区别。修正上次审阅发现的 `.gitignore` 放行描述与实际不一致之处。
- [ ] 新 `--basetemp` 重跑定向及全项目 pytest；运行 Ruff、`git diff --check`、目标文本秘密格式扫描、Rich 三份冻结哈希及最终比较文件只读核对。记录真实数字与 Windows skip；若 Docker 权限不足，标明未通过实际容器门。

## Phase B5 — 真实试点授权门（不由本计划自动启动）

### Task 10: 受控真实试点与审计记录

**Files:** 仅在用户后续明确授权后，按获准范围更新 `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md` 或单独的非秘密试点记录；不得触碰旧 Rich/Click 冻结证据。

**Interfaces:** 用户须先指定仓库、base SHA、允许读取范围、provider／模型、预算、最多运行次数、验证命令和 Docker 镜像 digest。计划中的假测试通过不等于这项授权。

- [ ] 先展示 B1–B4 及 B3.5 真实 Docker、无 provider 门的实际隔离、审批、脱敏和全项目验证证据；缺任一门则保持真实运行按钮关闭。
- [ ] 获得上述逐项明确授权后，才运行一次限定试点；记录 base SHA、任务 ID、实际命令批准、补丁与验证摘要、provider／工具／测试失败类别和来源前后不变证明。
- [ ] 如实报告真实结果；不补跑 Rich/Click 正式槽位，不提交、push、回写来源或创建 PR，除非用户分别明确指示。

## Execution Handoff

本计划是待审阅的实施文件，不因写成而授权执行。建议先按 B1→B3→B3.5→B4 顺序实施并逐阶段验收；B3.5 必须获得单独 Docker 测试授权，B5 保持独立真实 provider 授权门。接口和隔离策略存在前后依赖，实施时逐任务核对测试与失败门；用户确认设计、计划及执行方式后再开始。当前仓库改动继续保持未提交，任何 commit 或远端动作仍须用户单独指令。
