# MokioClaw Local Repository Review Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本机浏览器中读取用户显式指定的多个 Git 仓库，展示提交历史，并以可复算的 V1 规则说明改动审查优先级。

**Architecture:** 在既有 Typer CLI 下增加独立的 `dashboard` 命令；它建立本次进程内仓库目录，启动仅监听 `127.0.0.1` 的 FastAPI 服务。Git 只读读取器输出规范化提交数据，纯函数计算审查优先级；同源原生 HTML/CSS/JavaScript 页面通过只读 API 展示三栏工作台。实现不接入既有 Agent 执行链或 Eval Runner。

**Tech Stack:** Python >=3.13、Typer、FastAPI、Uvicorn、原生 HTML/CSS/JavaScript、Git CLI、pytest、FastAPI TestClient/httpx、Ruff；无 Node 构建、数据库或 provider 依赖。

**Spec:** `docs/superpowers/specs/2026-09-26-mokioclaw-local-repository-review-dashboard-design.md`（已确认；每次新任务先按项目根目录 `SKILL.md` 完整阅读）

## Global Constraints

- 本计划只覆盖已确认的本地核心。私有 GitHub 登录、远端读取、Agent 修复、PR 回写和部署另行设计；不能因看到本计划而启动它们。
- 启动时只登记显式本地目录；未给目录时只尝试当前目录。拒绝非 Git 工作树、bare 仓库和不可读路径；不扫描用户磁盘。
- 所有 Git 调用用参数数组，不用 shell；禁用外部 diff、textconv、fsmonitor 等可由仓库配置触发的程序；使用 `--no-optional-locks`、超时和输出上限。不得运行仓库代码或读取 blob、完整 diff、`.env` 秘密值。
- 服务只监听 `127.0.0.1`，校验 Host，无 CORS、第三方资源或写 API；不记录提交标题、文件名、本机绝对路径、请求头或请求体。
- V1 输出仅有 `high`、`medium`、`low`、`manual_review`。合并、二进制或缺失必要统计先进入 `manual_review`；其余按敏感路径/文件数≥10/总行数≥500 判 `high`，文件数≥4/总行数≥120/删除或重命名判 `medium`，其余判 `low`。没有 0–100 概率分数。
- `manual_review` 是无法机械判断，并不表示安全。缺少 CI/测试证据只能写“未取得”；提交审查优先级与 Agent、provider、fixture/smoke 成绩隔离。
- 不读取、移动、删除或覆盖 ignored 实验证据，不修改 Rich/Click 冻结分析，不补跑正式槽位。代码树变化不改变旧 Click 批次的冻结身份。
- 文件修改一律用 `apply_patch`。测试用 `D:\envs\codeagent\Scripts\python.exe`，显式 `PYTHONPATH=src`，每次 pytest 使用新 GUID 的独立 `--basetemp`。本计划不授权 commit、push、远端修改、provider 调用或新 Agent 实验。
- 每项任务以失败测试→最小实现→通过测试→审阅差异结束。只有本地核心完整验收后，才能对外称“本地核心完成”。

## Review Focus

以下五项尤其容易在正常演示中造成错误；对应测试落在所注明的任务中。

1. **仓库路径别名、重复登记和一个无效路径混在有效路径中**：全部路径先验证，重复顶层目录只显示一次，存在失败则整体拒绝启动；Task 3 的目录测试。
2. **根提交、重命名以及含空格/换行的文件名**：零字节解析保留路径与统计，不把特殊文件名拆成两条；Task 2 的 Git fixture 测试。
3. **翻页期间 HEAD 前进或详情 SHA 不属于锚历史**：旧页只使用旧锚，给出刷新提示；不可达详情返回 404；Task 4 的接口测试。
4. **快速切换 A/B 仓库时 A 的迟到响应**：选中状态和右栏信息仍属于 B；Task 6 的浏览器交互验收。
5. **恶意提交标题/路径及非本机 Host**：页面仅输出文本，API 拒绝异常 Host 且不泄漏内部错误；Task 4 与 Task 6 的测试/浏览器验收。

## File Structure

| 文件 | 单一职责 |
|---|---|
| `pyproject.toml` | 增加 FastAPI、Uvicorn 运行依赖与 httpx 测试依赖；不引入 Node 工具链 |
| `uv.lock` | 与新增运行依赖同步，避免锁文件落后于 `pyproject.toml` |
| `src/mokioclaw/dashboard/models.py` | 固定仓库、提交、文件变更、评估及错误的数据形状 |
| `src/mokioclaw/dashboard/priority.py` | `ReviewPriorityV1` 纯函数和稳定理由模板 |
| `src/mokioclaw/dashboard/git_reader.py` | 有边界的只读 Git 调用、元数据/文件统计解析和领域错误 |
| `src/mokioclaw/dashboard/catalog.py` | 启动时登记仓库、不透明 ID、路径去重、进程内访问控制 |
| `src/mokioclaw/dashboard/pagination.py` | 绑定仓库 ID、HEAD 锚与偏移量的有界游标 |
| `src/mokioclaw/dashboard/api.py` | 四个 GET 接口、错误映射、Host/CSP、进程内详情缓存和静态资源路由 |
| `src/mokioclaw/dashboard/launcher.py` | 校验后绑定回环端口、启动服务与浏览器、关闭清理 |
| `src/mokioclaw/dashboard/static/{index.html,styles.css,app.js}` | 三栏页面、响应式布局、数据请求、文本渲染与状态切换 |
| `src/mokioclaw/cli/app.py` | 注册 `mokioclaw dashboard --repo PATH`，保持现有 Agent/TUI 命令行为 |
| `tests/dashboard/conftest.py` | 只在临时目录创建小型 Git 仓库，不使用真实项目仓库或 `.env` |
| `tests/dashboard/test_{priority,git_reader,catalog,pagination,api,launcher}.py` | 各边界的机械回归测试 |
| `README.md` 与 `docs/MOKIOCLAW_LOCAL_DASHBOARD_DEMO.md` | 产品定位、启动步骤、演示路径和明确的非主张 |
| `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md` | 记录本地核心阶段结果与真实验收数字 |

## Phase 1 — 只读数据内核与审查规则

**阶段交付：** 不启动 Web 服务即可在临时仓库中取得完整 SHA、提交列表、单提交文件统计和四类可解释评估。仓库登记只接受本次启动传入的目录。

**退出门：** Tasks 1–3 的定向测试通过；同一提交在不同绝对路径和环境设置下产生相同评估；未触碰真实实验仓库。

### Task 1: 固定数据契约与 V1 优先级

**Files:** Create `src/mokioclaw/dashboard/{__init__,models,priority}.py`; create `tests/dashboard/test_priority.py`。将这些新文件连同对应测试作为同一审阅单元。

**Interfaces:** `ChangedFile(path: str, previous_path: str | None, change_type: str, additions: int | None, deletions: int | None)`，其中 `path` 是当前路径或被删除的路径，`previous_path` 仅供重命名/复制；`CommitDetail(sha: str, title: str, committed_at: str, parent_shas: tuple[str, ...], files: tuple[ChangedFile, ...])`；`ReviewReason(code: str, message: str)`；`ReviewAssessment(sha: str, rule_version: str, priority: str, signals: dict[str, object], reasons: tuple[ReviewReason, ...], limitations: tuple[str, ...])`；`assess_commit(detail: CommitDetail) -> ReviewAssessment`。规则版本固定为 `review-priority-v1`。`signals` 至少含文件数、总增加/删除行数、删除/重命名、敏感路径命中与测试路径是否同次改动；最后一项不改变优先级。JSON 序列化层使用这些字段名，后续任务不得另造同义字段。

- [x] **Step 1: 写失败测试。** `test_priority_boundaries_and_order` 断言文件数 3/4/9/10、总行数 119/120/499/500 的边界和固定理由顺序；`test_sensitive_paths_are_exact_segments_or_fixed_names` 断言 `auth/` 命中但 `author/` 不命中；`test_manual_review_precedes_high` 断言合并、二进制和缺失统计均为 `manual_review`；`test_assessment_ignores_root_path_locale_and_worktree` 断言输入之外的本机状态不参与结果。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_priority.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t1-red-' + [guid]::NewGuid().ToString('N'))) `；预期因模块/函数尚不存在而失败。
- [x] **Step 3: 最小实现。** 用不可变 dataclass 固定输入/输出；先判 `manual_review`，再按设计 §8 的阈值和路径集合判定。路径转 `/`、大小写折叠，理由以固定 code 顺序输出；不要读文件内容、提交作者、消息正文或系统时钟。
- [x] **Step 4: 重跑同一路径测试，使用新 GUID basetemp。** 预期全通过；审阅输出中无数值概率、模型叙述或未定义状态。

### Task 2: 安全的 Git 只读读取器

**Files:** Create `src/mokioclaw/dashboard/git_reader.py`、`tests/dashboard/conftest.py`、`tests/dashboard/test_git_reader.py`。

**Interfaces:** `LocalGitReader(git_executable: str = "git", timeout_seconds: float = 10, max_output_bytes: int = 8_388_608)`；`inspect(path: Path) -> RepositoryState`，其中 `RepositoryState` 在 `models.py` 包含 `root: Path`, `name: str`, `branch: str | None`, `head_sha: str | None`, `dirty: bool`, `object_format: str`；`list_commits(root: Path, anchor_sha: str, offset: int, limit: int = 50) -> tuple[CommitSummary, ...]`；`get_commit(root: Path, sha: str, anchor_sha: str) -> CommitDetail`。`CommitSummary` 含 `sha`, `title`, `committed_at`, `parent_count`。错误类型为 `InvalidRepository`、`CommitNotFound`、`GitReadTimeout`、`GitOutputLimit`、`GitReadError`，供 API 精确映射。

- [x] **Step 1: 写失败测试。** 临时 Git fixture 覆盖普通/根/合并提交、重命名、二进制、无提交、dirty 与 detached HEAD；文件名包含空格、换行和 HTML 字符。断言 SHA-1 与 SHA-256 的长度校验、锚历史可达性、零字节文件名解析、超时和超限错误；对恶意本地 Git 配置证明不会调用外部 diff/textconv/fsmonitor 程序。读取前后比较仓库引用、index 和工作树状态。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_git_reader.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t2-red-' + [guid]::NewGuid().ToString('N'))) `；预期缺少读取器而失败。
- [x] **Step 3: 最小实现。** Git 子进程只接收参数数组；固定全局只读选项，关闭外部 diff/textconv/fsmonitor；限制时间和输出量并清理超时子进程。用 NUL 分隔解析元数据、name-status 与 numstat，根提交对空树；多父合并保留父数并标记统计不适用。无 HEAD 的仓库返回空历史；无对象、超时、截断分别抛不同领域错误。
- [x] **Step 4: 重跑定向测试，使用新 GUID basetemp。** 预期通过；核对 Git 调用未包含 fetch/checkout/reset/clean/commit/push，也未读取 blob 正文。

### Task 3: 原子仓库登记与有界游标

**Files:** Create `src/mokioclaw/dashboard/{catalog,pagination}.py`、`tests/dashboard/test_{catalog,pagination}.py`。

**Interfaces:** `RepositoryCatalog.from_paths(paths: Sequence[Path], reader: LocalGitReader) -> RepositoryCatalog`；`get(repo_id: str) -> RegisteredRepository | None`；`summaries() -> tuple[RepositorySummary, ...]`。`RegisteredRepository` 含进程内随机 ID 与规范化顶层路径；`RepositorySummary` 含 `id`, `name`, `path`, `branch`, `head_sha`, `dirty`，其中 `path` 只给本机页面展示，不能进入评估；重复顶层路径只保留第一项。`CursorCodec.encode(repo_id: str, anchor_sha: str, offset: int) -> str`；`CursorCodec.decode(token: str, expected_repo_id: str) -> PageCursor`，`PageCursor` 含 `repo_id`, `anchor_sha`, `offset`；使用进程内随机密钥校验，令牌最长 512 字符。

- [x] **Step 1: 写失败测试。** 断言双仓库分离、相同仓库的相对/绝对路径去重、一个无效路径导致整体失败且无部分目录、ID 不包含本机路径；符号链接别名仅在 Windows 测试环境具备创建能力时执行，否则明确 skip。游标篡改、跨仓库复用、负偏移、过长输入和错 SHA 均被拒绝。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_catalog.py tests/dashboard/test_pagination.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t3-red-' + [guid]::NewGuid().ToString('N'))) `；预期接口未实现而失败。
- [x] **Step 3: 最小实现。** 先完整验证并规范化所有路径，再一次性建立目录；生成不可从路径推导的 ID。游标只承载 ID、锚 SHA、非负偏移，签名只用于完整性；不存 token、路径或提交内容到磁盘。
- [x] **Step 4: 重跑定向测试，使用新 GUID basetemp。** 预期通过；复查目录失败时未启动服务。

## Phase 2 — 只读 API 与可启动的本地服务

**阶段交付：** 测试客户端可通过本机 GET 接口读取两个已登记仓库；CLI 命令可启动服务。页面在 Phase 3 接入。

**退出门：** Tasks 4–5 定向测试通过；服务只监听回环地址；所有 API 错误与 Git 异常都转成不泄密的固定结构；旧 Agent/TUI 命令回归通过。

### Task 4: API、锚一致性与安全响应

**Files:** Create `src/mokioclaw/dashboard/api.py`、`tests/dashboard/test_api.py`；modify `pyproject.toml`、`uv.lock`（FastAPI、Uvicorn 运行依赖；httpx 已在当前环境，但仍在 dev 组显式声明）。

**Interfaces:** `create_dashboard_app(catalog: RepositoryCatalog, reader: LocalGitReader, cursor_codec: CursorCodec) -> FastAPI`。响应分别为 `RepositorySummary[]`、`{repo_id, anchor_sha, current_head_sha, commits, next_cursor}`、`{repo_id, anchor_sha, detail, assessment}`、`{status: "ok"}`。错误统一 `{code: str, message: str, retryable: bool}`。详情路由要求 `anchor` 查询参数；合法 SHA 必须在该锚历史中可达。列表上限 50，详情缓存键为 `(repo_id, anchor_sha, sha, rule_version)`。

- [x] **Step 1: 准备依赖。** 当前 `D:\envs\codeagent` 已有 httpx 0.28.1，尚无 FastAPI/Uvicorn，且 `uv` 命令当前不可用。先把运行/测试依赖写入 `pyproject.toml`，在允许的包源中解析并安装到指定环境；让已有 `uv.lock` 同步。生成文件若需工具辅助，先在临时目录生成，再通过 `apply_patch` 应用仓库改动。若无法取得依赖或同步锁文件，报告阻碍，不假装 API 测试通过。
- [x] **Step 2: 写失败测试。** TestClient 使用 `base_url="http://127.0.0.1"`；断言两个仓库结果不串用、第一页与后续页固定同一锚、HEAD 变更仅提示刷新、不可达详情 404、非法 SHA/游标 400、未知 ID 404、错误不含 traceback/路径/原始 Git 输出。另以非本机 Host 请求断言拒绝；POST/PUT/DELETE 返回 405；响应有 CSP 且无 CORS 放行；恶意标题与路径作为 JSON 字符串返回，不插入 HTML。
- [x] **Step 3: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_api.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t4-red-' + [guid]::NewGuid().ToString('N'))) `；预期应用工厂不存在而失败。
- [x] **Step 4: 最小实现。** 实现四个 GET 接口、Host 检查、CSP、无缓存敏感响应、稳定错误映射和进程内缓存。第一页捕获 HEAD 锚；后续游标固定锚并同时返回当前 HEAD。任何 Git 超时/输出超限都中止评估，不使用半截统计。
- [x] **Step 5: 重跑定向测试，使用新 GUID basetemp。** 预期通过；检查测试日志未包含私有提交元数据或绝对路径。

### Task 5: Typer 命令与服务生命周期

**Files:** Create `src/mokioclaw/dashboard/launcher.py`、`tests/dashboard/test_launcher.py`；modify `src/mokioclaw/cli/app.py`、`tests/test_cli_smoke.py`。

**Interfaces:** CLI 为 `mokioclaw dashboard --repo PATH [--repo PATH ...] [--no-browser]`；无 `--repo` 时仅尝试当前目录。`launch_dashboard(paths: Sequence[Path], *, open_browser: bool = True) -> None` 负责先建立完整目录，再绑定 `127.0.0.1` 可用端口并服务，地址就绪后才打开浏览器；Ctrl-C 正常关闭。不暴露自定义 Host 选项。

- [x] **Step 1: 写失败测试。** CliRunner 断言新子命令识别成功而不触发 `stream_agent_events`；无效仓库时既不启动服务也不开浏览器；双 `--repo` 保持顺序；未给路径使用 cwd；`--no-browser` 不打开浏览器。模拟 server 生命周期，断言绑定地址严格为 `127.0.0.1`、浏览器在就绪后打开、终止时无残留后台进程；旧 CLI smoke 用例仍通过。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_launcher.py tests/test_cli_smoke.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t5-red-' + [guid]::NewGuid().ToString('N'))) `；预期新命令用例失败、旧用例仍通过。
- [x] **Step 3: 最小实现。** 在现有 Typer app 注册 `dashboard`，延迟导入服务模块以保持现有 CLI 启动路径。校验路径后启动 Uvicorn，保留已绑定的回环 socket 以免“找端口→释放→重新绑定”竞争；关闭后释放 socket 和进程内目录。
- [x] **Step 4: 重跑定向测试，使用新 GUID basetemp。** 预期全部通过；运行 `mokioclaw dashboard --help` 目视核对命令说明没有暗示 GitHub 登录或 Agent 修复。

## Phase 3 — 浏览器工作台与真实仓库演示

**阶段交付：** 用户在一个本地页面完成选仓库→翻提交→读详情/优先级；常见桌面与窄屏可用，页面把不确定性明确显示出来。

**退出门：** Task 6 的接口与浏览器验收通过；切换仓库时不出现旧详情；所有 Git 文本仅作为文本节点；同源静态资源无第三方请求。

### Task 6: 三栏页面、响应式交互与可解释性

**Files:** Create `src/mokioclaw/dashboard/static/{index.html,styles.css,app.js}`；modify `src/mokioclaw/dashboard/api.py`；create `tests/dashboard/test_static_assets.py`。

**Interfaces:** 页面从 `GET /api/repositories` 开始；选中仓库后请求其提交页；选中提交时以当前 `anchor_sha` 请求详情。URL 只记录非敏感 `repo` ID、完整 `sha` 与必要的锚 SHA；刷新后可恢复选择。前端不接收绝对磁盘路径作为请求参数。

- [x] **Step 1: 写失败测试。** 静态资源测试断言根页面和 JS/CSS 同源可访问、HTML 有三栏语义区/标题/状态区域、页面不引用 CDN、没有假 Agent 执行按钮；API 测试断言恶意标题/路径仍为原始 JSON 文本。准备一个仅在临时目录创建的双仓库演示夹具，含普通、敏感路径与合并提交。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard/test_static_assets.py tests/dashboard/test_api.py -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t6-red-' + [guid]::NewGuid().ToString('N'))) `；预期静态页面路由不存在而失败。
- [x] **Step 3: 最小实现。** 三栏以仓库、提交、审查为明确层级；CSS 覆盖桌面与窄屏；JS 使用 `textContent`/DOM 文本节点，仓库/提交切换时先清空旧详情，再取消或忽略迟到请求，并核对响应 ID 与 SHA。显示加载、空、错误、超时、HEAD 已更新、四类优先级、命中理由和信息缺口；保留键盘焦点和文字标签。
- [x] **Step 4: 重跑静态/API 测试，使用新 GUID basetemp。** 预期通过；用本机浏览器手动走完双仓库、翻页、普通/敏感/合并提交、窄屏和键盘流程。快速交替点击 A/B 仓库并制造慢请求，确认 B 选中时右栏不出现 A 详情；用含 `<script>` 的标题/路径确认只显示字面文本。记录实际截图或简短验收文字时不得包含私有路径和提交内容。

## Phase 4 — 边界加固、回归与交付说明

**阶段交付：** 本地核心在异常和安全路径上有新鲜证据，README/演示说明与当前能力一致，且原有 Agent/Eval 路径没有被误动。

**退出门：** Tasks 7–8 完成；全项目 pytest、Ruff、diff 检查和冻结证据核对有本轮结果；来源仓库状态前后相同；用户可按文档独立启动并复现演示。

### Task 7: 跨层异常与只读保证

**Files:** Extend `tests/dashboard/test_{git_reader,catalog,pagination,api,launcher}.py`；只修改确实暴露缺陷的对应实现文件。

**Interfaces:** 维持 Tasks 1–6 的既定数据与路由字段，不新增外部写接口。错误类型到 HTTP code 的映射保持稳定，所有超时/截断数据不得进入 `assess_commit`。

- [x] **Step 1: 写失败测试。** 注入 Git 缺失、仓库启动后被移走、浅克隆缺对象、输出超限、无提交、HEAD 在分页间移动、API 请求未登记 ID、非法 SHA-256 长度、同名不同根目录；断言其他仓库仍可用、错误可操作且无路径/secret、没有半截评估。用模拟 provider 初始化钩子断言 dashboard 路径未调用 Agent/provider。比较临时来源仓库的 HEAD、index、状态与文件内容前后不变。
- [x] **Step 2: 运行失败测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/dashboard -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-t7-red-' + [guid]::NewGuid().ToString('N'))) `；至少一个新边界用例应先失败，已有用例保持通过。
- [x] **Step 3: 只修复已复现缺陷。** 保持原接口与 V1 阈值；对缺对象、超时、截断分别走明确错误或 `manual_review`（按设计 §7 的区别），补齐必要的资源释放与错误文案，不扩大扫描范围。
- [x] **Step 4: 重跑 `tests/dashboard`，使用新 GUID basetemp。** 预期全通过；对每个修复点说明对应失败用例，避免添加与缺陷无关的重构。

### Task 8: 文档、全量验证与用户验收

**Files:** Modify `README.md`、`docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`、`.gitignore`（仅精确放行新的演示文档）；create `docs/MOKIOCLAW_LOCAL_DASHBOARD_DEMO.md`。不要改写旧 Rich/Click 报告或冻结分析。

**Interfaces:** 文档给出 `mokioclaw dashboard --repo <path> --repo <path>` 与 `--no-browser` 的真实命令、停止方式、四类优先级含义、演示路径、隐私边界及故障排查。明确写“本地核心已完成”只在本阶段全部验收通过后使用；GitHub 和 Agent 修复继续标为后续方向。

- [x] **Step 1: 写文档验收清单。** 从全新终端按文档启动两个临时仓库；记录三栏、翻页、普通/敏感/合并详情、关闭服务；对比启动前后的仓库引用、index、工作树和 ignored 证据目录。文案中检查无 GitHub 已接入、漏洞已发现、Agent 成绩提升或 Rich–Click 严格复现的误述。
- [x] **Step 2: 更新文档与精确 ignore 例外。** README 首页说明产品入口；演示文档提供命令和截图规范（截图不含秘密/私有路径）；进度文件只写本轮真实结果。`.gitignore` 仅放行这份演示文档，不暴露其他 ignored docs/实验产物。
- [x] **Step 3: 运行完整项目测试。** ` $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'D:\envs\codeagent\Scripts\python.exe' -m pytest -q --basetemp (Join-Path $env:TEMP ('mokio-dashboard-full-' + [guid]::NewGuid().ToString('N'))) `；记录本轮 passed/skipped/failed，不沿用旧 468/2/0。Windows 符号链接 skip 若仍存在，注明能力限制。
- [x] **Step 4: 运行静态与证据检查。** ` & 'D:\envs\codeagent\Scripts\python.exe' -m ruff check src tests `、`git diff --check`、目标文件秘密格式扫描、Rich 三份冻结 SHA-256 与最终比较产物只读核对。记录实际值；任何失败先修复并重跑对应门，不以历史通过结果代替。
- [x] **Step 5: 用户验收。** 按设计 §13.4 的双仓库路径完整演示；提供代码与验收记录供审阅。commit、push、远端写入和下一阶段启动仍等待各自明确指令。

## Phase Gates and Handoff

| 阶段 | 必须可见的结果 | 未通过时的处理 |
|---|---|---|
| 1 数据内核 | 临时 Git fixture 中四类评估、精确边界与只读证明 | 不进入服务层；修复解析/规则并重跑定向测试 |
| 2 API/CLI | 双仓库同源 GET、合法锚分页、回环监听与无泄密错误 | 不制作“可演示”声明；先修正接口/启动生命周期 |
| 3 页面 | 三栏完整路径、窄屏/键盘、切换竞态与文本安全 | 不做正式演示；修正 UI 后重复人工路径 |
| 4 验收 | 全项目测试、Ruff、冻结核对、文档和来源仓库不变 | 如实标注未完成项；不把部分通过写成阶段完成 |

**完成后才能提出的结论：** “本地浏览器工作台可以只读展示多个指定仓库的提交和可解释审查优先级。”不能推导为漏洞检测、Agent 修复能力提升或私有 GitHub 演示已实现。
