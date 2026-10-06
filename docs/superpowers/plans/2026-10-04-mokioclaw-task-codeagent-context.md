# Task CodeAgent Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development only if the user chooses delegation. Steps use checkbox syntax. No commits or pushes are authorized.

**Goal:** 在任务 CodeAgent 内部实现已审阅的确定性上下文整理、有版本的正文窗口与受控结果续读，保留现有权限、预算和正式验证语义。

**Architecture:** 任务上下文持有固定策略和当前委派服务，CodeAgent 在实际模型调用前整理完整历史，在工具组第一项执行前预留整组最小反馈。文件工具负责最终可见源码窗口及覆盖证明；独立内存结果服务只提供已执行工具的不可变片段。普通 CLI/TUI 沿用原分支。

**Tech Stack:** 现有 Python ≥3.13、LangChain 消息／StructuredTool、pytest、Ruff；不增加依赖、网络服务或磁盘结果缓存。

**Spec:** [已审阅设计](../specs/2026-10-04-mokioclaw-task-codeagent-context-design.md)。执行前须读完整设计和本计划，不能仅凭任务列表实施。

**Status:** 用户已批准本会话逐项离线实施与输入域调整；任务1–8及作者最终自审已完成，最终相关291 passed、非Docker894 passed／3 skipped／35 deselected。96／72／48KiB保持，合法大TaskSpec基线超界明确拒绝；历史失败记录保留。用户禁止子agent，未作独立最终审阅；真实恢复与收尾保留量不在本次实施内。

## Global Constraints

- 实施树为 `C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent`，当前 `codex/mokioclaw-stage-b / 033fedbc48b428a221289f227a999c1beed0c5b4` 加原十一项未提交修改。主项目只保存审阅材料；不混用其旧产品设计授权。
- 固定 B_hard=98304、B_trigger=73728、B_target=49152、封装裕量=4096；胶囊≤8192、单 ToolMessage 规范 JSON≤16384、单页正文≤8192、组首屏 ToolMessage 总和≤32768 字节。
- FileRead默认100／最大2000行；结果库≤32MiB／32结果。阈值不是token或费用承诺。完整基线≥48KiB固定拒绝；三式在准许运行输入域内失败仍停止重审，不能改值、删锚点或换成字符估算。
- 不改变 16 轮 CodeAgent 工具循环、planner／verifier 路由、attempt 规则、总预算、输出设置、固定验证命令、Bash executor 输出上限或 Grep 一文件字面查找语义。
- system、完整 task/planner、acceptance criteria、fixed verification commands 必须保留；AI 参数不裁、完整 AI→Tool 组不拆、最近两组和必要失败保留。无效配对不得再 invoke。
- FileWrite 仍只改写已有文件，增加同路径／当前 revision 完整覆盖前置门；FileEdit 仍逐字唯一匹配。续读重新授权，不放宽 scope／安全句柄／symlink／reparse／审批。
- 冻结 `src/mokioclaw/tools/*.py`、`graph/architectures.py`、`graph/workflow.py` 禁止修改。不 reset／clean／覆盖既有修改，不改来源、旧补丁、冻结报告或私有试点资产。
- 计划编写阶段只写文档；用户已另行批准在本会话逐项离线实施与合成测试。provider、Docker、真实任务、用户 temp.py、读取 .env 秘密、提交、push 或远端修改仍未授权。
- boltons 一次真实额度已用完；Task10 第五批已用 3／余 2 保留，停止讨论状态不解除。内部整理完成并离线验收后，才另审同一总门内收尾保留量。

## Review Focus

1. 同一请求连续 prepare 两次：胶囊只替换，不再叠加；计量、组顺序与锚点保持幂等。由任务 1 的 T2/T3 测试锁定。
2. 首屏分配因 JSON 转义再次缩页：coverage 只能计最终交回片段，不能提前计整次 read_bytes。由任务 3 的 T4 和任务 5 的 T8 锁定。
3. verifier 独立读取和下一次 CodeAgent 委派：不能借旧委派 coverage／cursor 获得写入前置证明。由任务 3/5 的 T5 锁定。
4. 工具先真实失败、随后投影或 finally 又失败：保留先有固定根因，不以最后异常归类。由任务 6 的 T10 锁定。
5. 行末 CRLF、无换行 EOF、空文件与 Unicode 控制字符混合：编号／片段标记不成为源码，页拼接和覆盖坐标一致。由任务 3 的 T4 锁定。

---

## 文件结构与接口约定

所有下列产品／测试路径相对于实施树；本计划和设计文件位于主项目，不在实施时复制产品源码到主项目。

| 文件 | 单一职责 |
| --- | --- |
| 新 `src/mokioclaw/dashboard/task_context.py` | 策略、规范计量、合法组、胶囊、覆盖元数据、委派会话与工具配额；固定 TaskContextError |
| 新 `src/mokioclaw/dashboard/task_result_windows.py` | 不可变结果载荷、容量预留、cursor／片段映射、FIFO／失效；不解释活文件路径 |
| `src/mokioclaw/dashboard/task_tools.py` | 文件／notepad 窗口、coverage 提交、写入前置条件、diff／Grep 结果声明 |
| `src/mokioclaw/dashboard/task_filesystem.py` | 同既有安全句柄读取当前字节、核对预期 revision 后写入；原权限语义 |
| `src/mokioclaw/dashboard/task_graph.py` | 显式注入 TaskToolServices；只给 CodeAgent 增加结果续读工具 |
| `src/mokioclaw/agents/code_agent.py` | 任务分支生命周期、实际历史替换、组预检与有界反馈；普通分支不变 |
| `src/mokioclaw/core/agent.py` | TaskRunContext 服务注入／attempt 生命周期、模型绑定计量、锁内最终门及根因记录 |
| `src/mokioclaw/graph/nodes.py` | 有限任务异常透传、只读窗口恢复策略、真实验证结果记录；不改路由 |
| `src/mokioclaw/dashboard/task_worker.py`、`task_events.py` | 单一新失败类别、工具身份白名单、先有根因与预算 finally |
| 新 `tests/dashboard/test_task_context.py`、`test_task_result_windows.py` | 纯计量／整理与内存服务契约 |
| 新 `tests/dashboard/test_task_context_flow.py`、`task_context_fakes.py` | 合成真实流程与显式禁止防护；辅助文件不提供真实执行器 |
| 现有 `test_task_filesystem.py`、`test_task_graph_injection.py`、`test_task_provider_context.py`、`test_task_workflow.py`、`test_task_events.py`、`test_task_result.py`、`tests/test_graph.py` | 安全／预算／收尾／普通行为回归；只因新显式注入调整夹具，不削弱原断言 |

核心类型在任务 1 定义，其余任务沿用：

- `TaskContextPolicy`：冻结 dataclass，数值取上述常量。新增覆盖元数据工程参数在任务 3 明列，不作为 TaskSpec／环境配置。
- `TaskContextError(reason: str)`：reason 只允许 input_too_large、invalid_message_group、result_capacity、unsupported_content；异常文本固定为 task_context_error，reason 仅内存属性。
- `RequestBinding(schemas: tuple[dict, ...], options: dict)`：纯数据；由已选择工具及实际 bind/invoke 选项产生。不得保存 underlying model、prompt 副本或 provider 输出。
- `MessageGroup(ai, tools, sequence, recoverable_failure)`：原消息引用／不可变视图，ID 严格配对。
- `ReadReceipt(path, revision, coverage_complete, eof_covered, receipt_id)`：仅元数据；receipt_id 取可信覆盖元数据规范 JSON 的 SHA256，同一证明确定性相同；它是索引而非权限能力，require_complete 必须查本地 ledger，不接收模型声称的完成状态。
- `TaskToolServices(filesystem, policy)`：绑定一个 TaskFilesystem 身份；管理一个当前 CodeAgent 委派及其 GroupPlan／CoverageLedger／ResultWindowStore。无全局文件内容缓存。
- `TaskContextSession`：每次委派创建；包含 anchors、binding、胶囊与当前组配额。`close()` 清空 coverage／结果库／cursor；普通 runtime 不创建它。

循环依赖约定：task_result_windows 不导入 core 或 task_tools，只抛内部 `ResultWindowError(reason)`；task_context 的服务构造局部导入窗口服务并映射为 TaskContextError。task_tools 对 TaskRunContext 仅 TYPE_CHECKING，实际只接收 TaskToolServices。

## 离线执行边界及命令模板

获批实施前，先重新只读核对四仓 status／HEAD／本地 heads/remotes、既有十一项 diff 和冻结字节，保存内存／审阅记录中的基线。新文件如与现有用户文件同名则停止，不能覆盖。实施时仅用 apply_patch。

新增假模型场景启动前，由 `offline_context_guard` 拦截 create_task_model、create_model、ChatOpenAI 构造、dotenv 加载、socket connect/connect_ex/create_connection、DockerCLI.run、subprocess.run/Popen、os.system 及真实 CommandExecutor。触碰即 AssertionError；不 mock 成成功。不得在新增场景中创建临时 Git 仓库，所有源码／diff／输出全合成。模型只保存数值／组 ID／断言结果，不保存或打印输入正文；禁止捕获异常 repr 输出私有值。

worker／父进程协议新增测试使用内存帧通道，实现 sendall／recv 的字节接口，复用真实 _send／_receive／consume_worker_messages；不以 socketpair 或真实回环替代上述网络禁止。已有回环／临时 Git 测试仍沿原范围运行，不把新增严格防护扩散到其它夹具，但全项目始终不调用 provider／Docker。

以下是将来每次 pytest 独立执行的命令模板；本轮不执行。一次 Run-ContextPytest 调用只启动一次 pytest，不复用 basetemp：

```powershell
Set-Location -LiteralPath 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent'
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
function Run-ContextPytest {
    param([string[]]$TestArgs, [int]$ExpectedExit = 0)
    $taskBase = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ('mokioclaw-context-' + [guid]::NewGuid().ToString('N'))))
    $taskAncestor = [IO.DirectoryInfo]([IO.Path]::GetDirectoryName($taskBase))
    while ($null -ne $taskAncestor) {
        if (Test-Path -LiteralPath (Join-Path $taskAncestor.FullName '.git')) { throw 'basetemp has Git ancestor' }
        $taskAncestor = $taskAncestor.Parent
    }
    $taskRepos = @('D:\MokioAgent\MokioAgent', 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent', 'D:\agent work\project\MokioAgent', 'D:\agent work\project\boltons-mokioclaw-pilot')
    foreach ($taskRepo in $taskRepos) {
        if ($taskBase.Equals($taskRepo, [StringComparison]::OrdinalIgnoreCase) -or $taskBase.StartsWith($taskRepo + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'basetemp inside protected repository' }
    }
    & 'D:\envs\codeagent\Scripts\python.exe' -B -m pytest @TestArgs -p no:cacheprovider --basetemp $taskBase
    if ($LASTEXITCODE -ne $ExpectedExit) { throw 'unexpected pytest exit' }
}
```

RED 要求 exit1 且失败原因属于正在增加的行为；collection/import setup exit2、禁止防护被触碰、旧用例退化或环境问题不能算 RED 成功。GREEN 要求 exit0。新模块测试在测试函数内导入尚不存在的模块，避免 collection error 被当作有效 RED。每项记录实际结果，不使用预设 passed 数。

## Task 1：纯计量、基线校准与完整历史整理（T1–T3）

**Files:** 创建 task_context.py、test_task_context.py、task_context_fakes.py。

**Interfaces:**

- `canonical_request_bytes(messages: list[Any], binding: RequestBinding, *, invocation_options: dict | None = None) -> bytes`；`measure_request(messages: list[Any], binding: RequestBinding, *, invocation_options: dict | None = None) -> int` 返回规范 UTF-8 字节数＋4096，裕量只算一次。
- `validate_groups(history: list[Any]) -> list[MessageGroup]`；`prepare_request(anchors: tuple[Any, ...], history: list[Any], capsule: dict, binding: RequestBinding, *, invocation_options: dict | None = None) -> list[Any]`。返回实际替换列表，不修改原 AI 参数。
- `measure_baseline(anchors: tuple[Any, ...], minimal_capsule: dict, binding: RequestBinding) -> int`；`assert_baseline_feasible(base: int, minimal_two_delta: int, common_two_delta: int, failure_delta: int) -> None`，任一严格不等式不成立抛固定上下文错误并标记测试／设计门失败。

- [x] **Step 1：编写失败测试。** `test_meter_counts_schemas_options_ids_and_args`、`test_baseline_requires_real_anchors_and_tools`、`test_threshold_boundaries`、`test_groups_reject_orphan_duplicate_or_partial`、`test_prepare_is_idempotent`、`test_repeat_reads_keep_latest_two_and_required_failure`。断言 bytes 等于紧凑 sort_keys／ensure_ascii=False／allow_nan=False JSON 的长度＋4096；硬门 +1 零 invoke；基线三式使用 `<49152/<73728/<98304`，软门等值触发；prepare 两次相等，消息组原参数／ID 逐字段一致。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context.py') -ExpectedExit 1`；核对失败源于未实现契约。
- [x] **Step 3：实现上述纯接口及固定类型。** 规范字段计角色、name／ID、content、全部 tool_calls 参数及实际发送的附加字段；未知内容块或非 JSON 值拒绝。只支持当前任务实际出现的字符串和文本块，未知多模态内容 fail closed；不将 usage_metadata／response_metadata 当作发送内容。用现有纯工具 schema 转换器取得绑定 schema，bind 选项与逐次 invoke 选项均计入，不能用 str(message)。保留锚点与最近两组／独立必要失败，旧重复每轮按版本／范围去重，达到触发门才 FIFO 删除其它完整组；胶囊只替换一次，≤8192，路径≤32、历史 receipt≤8。state todos 仍是模型状态，不能变成验收事实。
- [x] **Step 4：运行 GREEN。** 同上命令省略 ExpectedExit。本步骤先验计量算法；实际新 schema 的最终 B_base 可行性在任务 5 再测，不能以临时空 schema 宣布校准通过。

## Task 2：不可变结果库与 cursor 能力（T5/T6）

**Files:** 创建 task_result_windows.py、test_task_result_windows.py；扩展 task_context_fakes.py。

**Interfaces:**

- `ResultSegment(kind: str, value: str | tuple[dict, ...])`：仅 text 或 records 两类不可变片段；名字只供服务内部登记。
- `ResultWindowStore(identity: tuple[str, int, str], *, max_bytes: int, max_results: int, max_cursors: int = 1024)`。
- `reserve(result: dict, segments: dict[str, ResultSegment], *, preserve_failure: bool = False) -> Reservation`；`commit(reservation, *, executed: bool) -> ResultRef`；`abort(reservation) -> None`。
- `first_page(ref: ResultRef, *, json_budget: int) -> dict`；`read(cursor: str, limit: int, *, identity: tuple[str, int, str], json_budget: int) -> dict`；`clear() -> None`。

- [x] **Step 1：编写失败测试。** `test_cursor_only_reads_exposed_segment`、`test_cursor_identity_and_eviction`、`test_page_json_and_body_limits`、`test_reservation_cannot_publish_candidate_diff`、`test_result_capacity_keeps_required_failure`。用可预测测试随机源验证 segment/位置由服务签发，外部 field/offset/JSONPath 没有入口；断言每页≤16384、正文≤8192，32MiB／32 结果边界，FIFO 失效不返回 complete=true；已执行提交前任何 cursor 都不能访问候选结果。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_result_windows.py') -ExpectedExit 1`。
- [x] **Step 3：实现内存服务。** cursor 用 secrets.token_urlsafe(24)，映射身份、结果、固定片段、下一位置，不包含路径／命令；有效 cursor 无隐式共享读指针，允许重复同页，限额缩页后的下一能力由服务生成。最多 1024 活跃 cursor，超过时淘汰最旧能力并明确 result_unavailable；不淘汰当前正在返回的下一能力。每次 read 重新验证当前委派身份；失效／跨身份一律同一固定错误，不回显归属。结果载荷计完整规范字节，预留也计入 32MiB；最新必要失败固定保留，容量不足抛 ResultWindowError(result_capacity)。源文件正文不入库；Bash 已丢尾部保留 upstream 不完整标记，读到库尾不宣称上游完整。无磁盘、prompt、AI 原始响应或 provider 内容。
- [x] **Step 4：运行 GREEN。** 同上命令省略 ExpectedExit；增加不安全来源不能自动重跑的恢复断言。ResultWindowError 在工具／会话边界转换成 TaskContextError，不被通用工具异常包装改类。

## Task 3：源码窗口、累计覆盖与写入前置门（T4/T5/T7/T9）

**Files:** 修改 task_tools.py、task_filesystem.py；扩展 task_context.py、test_task_filesystem.py；新增测试放 test_task_context_flow.py。

**Interfaces:**

- `CoverageLedger(max_files: int = 32, max_intervals_per_file: int = 128, max_metadata_bytes: int = 262144)`；`record_visible(path: str, revision: str, start: int, end: int, *, eof: int | None) -> ReadReceipt`；`require_complete(path, revision) -> ReadReceipt`；`invalidate(path: str | None = None) -> None`。
- `TaskFileTools(filesystem: TaskFilesystem, *, services: TaskToolServices)`；`read(file_path, offset=0, limit=100, char_offset=0, revision=None) -> dict`；`notepad_read(offset=0, limit=100, char_offset=0, revision=None) -> dict`。参数类型沿现有 task 转换兼容，新增 bool／非整数等非法坐标固定 window_invalid，不以 scope 拒绝掩盖它。
- Notepad 的 next_read 只含其自身 schema 的 offset／limit／char_offset／revision，固定 next_read_tool=NotepadReadTool；不引导模型拿 scratch path 调 FileRead，以免绕权限或得到错误的源码覆盖。
- `TaskFilesystem.canonical_path(path: str, *, scratch: bool = False) -> str`：授权后的规范相对 key，在 Windows 与原 normcase 校验一致，不能 resolve 任意路径代替安全打开。
- `TaskFilesystem.write_bytes(path, content, *, scratch=False, expected_revision: str | None = None) -> None`；新 `TaskFileRevisionChanged` 独立异常，不能被 TaskFilesystemError 捕获后映射成 scope_denied。

- [x] **Step 1：编写失败测试。** `test_multipage_coverage_is_gap_sensitive`、`test_long_line_unicode_crlf_round_trip`、`test_final_visible_page_only_contributes_coverage`、`test_revision_change_invalidates_receipt`、`test_write_requires_current_complete_coverage`、`test_write_checks_revision_before_truncate`。断言 100000 字符单行多页无缺口才 coverage_complete；漏页／尾页不完整，重复和重叠不虚增；最后页可 eof=true、complete=false、coverage_complete=true；无完整当前 receipt、窗口之间变更或写前版本变更均零写入；模型文字不能注册 receipt。补已有 scope／reparse／替换拒绝断言。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_filesystem.py') -ExpectedExit 1`；已有安全测试不能退化为意外失败。
- [x] **Step 3：实现有界窗口与 ledger。** 经原 fs.read_bytes 每次安全取得≤8MiB 原字节并 SHA256；沿原 UTF-8 replace 解码规则，用 CRLF／LF／CR 划行，其它码点仍作正文。维护内部解码后全局半开码点区间，包含完整换行；外部保持零起始行／列与行尾 metadata，编号／片段标记不入 coverage。正文、metadata、转义和首屏配额最终确定后才 record_visible，非空页至少取得一个源码码点或完整行尾以保证进展。空文件在可信 EOF 上覆盖 [0,0)。合并重叠／相邻区间；任一 ledger 上限超出时撤销对应证明、显式要求重读，不遗留完整 receipt。元数据字节门只计规范元数据，不宣称 Python 总内存上界；这三个新工程值属于本计划审阅项。
- [x] **Step 4：实现 FileWrite guard 与同句柄版本检查。** 对任何已有源码文件改写，先核对当前委派 ledger，再以原授权／write=True 安全句柄重新读原字节核对 SHA256，之后在同句柄 seek/write/truncate。expected_revision 仅来自可信 receipt，不能从模型声称生成。覆盖不足返回 task_write_coverage_required，retry_same_operation=false、recovery=reread_current_revision；版本变化返回 task_read_revision_changed 并撤销旧 coverage。门只增加读取前置条件，原写／文件大小规则不变；FileEdit 不增加全文覆盖要求。写／编辑成功撤销该路径 receipt；命令未知改动范围撤销全部。notepad 使用 scratch 原权限、不贡献源码 coverage。
- [x] **Step 5：运行 GREEN 与平台边界核对。** 同上命令省略 ExpectedExit。必须验证 fd 关闭、版本不符时尚未 truncate、同句柄读写与原链接拒绝；Windows 原共享模式不放宽。POSIX 同句柄不是对任意外部进程的原子 CAS，不宣称排除本机用户另改文件；如新增校验依赖平台无法可靠提供的身份约束，fail closed 并停在审阅门，不改用普通按路径读写。pytest 不借 Docker 补平台证据，实际能力 skip 单列。

## Task 4：任务工具接线、diff 与反馈来源（T5/T6/T9）

**Files:** 修改 task_graph.py、task_tools.py、core/agent.py 的 attach_tools／begin_attempt、task_worker.py 的 _run_real_task；扩展 test_task_graph_injection.py、test_task_filesystem.py、test_task_workflow.py。

**Interfaces:**

- `build_task_file_tools(filesystem, *, services: TaskToolServices) -> list[StructuredTool]`。
- `build_task_graph_tools(filesystem, gateway, workspace, *, services: TaskToolServices) -> list[StructuredTool]`：基础列表仍不含 ToolResultReadTool。
- `build_task_result_read_tool(services: TaskToolServices) -> StructuredTool`：schema 只有 cursor: str、limit: int，正整数；limit 非法为 window_invalid，身份无效优先拒绝，不披露句柄存在性。
- `TaskRunContext.attach_tools(filesystem, tools, *, services: TaskToolServices, gateway=None, verification_commands=()) -> None`；验证 fs／服务身份一致。worker 显式创建 services，再构建工具和 attach，不从普通 runtime 或全局变量回退。

- [x] **Step 1：编写失败测试。** `test_result_read_is_code_agent_only`、`test_grep_context_uses_revision_and_file_read`、`test_diff_capacity_checked_before_write`、`test_bash_upstream_tail_is_not_recoverable`、`test_services_identity_is_required`。检查 planner／verifier 的基础工具名单不变、cursor schema 无 field/路径、Grep 搜索前 2000 字符且 searched_prefix_only 明确、diff>4000 可复原、候选 diff 不成为实际 receipt、网关真实 field command_request_id 原样保留。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_graph_injection.py','tests/dashboard/test_task_context_flow.py') -ExpectedExit 1`。
- [x] **Step 3：实现显式注入与固定结果 profile。** 为 FileRead／Notepad、FileEdit／FileWrite diff、Grep 匹配元数据、Bash stdout/stderr 和 TodoUpdate 的已知正文登记固定片段；模型不能选择 profile 或任意字段。能完整放入首屏的小结果直接返回 JSON，不强存结果库或生成无用 cursor，避免 32 结果门误杀多个小调用。diff 在有限输入上完整生成、写前 reserve，操作成功再 commit，失败 abort 并保留真实工具根因。Grep 继续一文件字面查找，给可信位置／revision，源码上下文只能 FileRead；仅把已经查找得到的不可变匹配列表入库。Bash 只存网关实际返回，不重跑，不更改执行上限或审批。必要结构／todos 无法有界表示时固定上下文错误，不裁权限／任务状态。
- [x] **Step 4：运行 GREEN。** 同上命令省略 ExpectedExit。现有 task 测试夹具统一显式传 services；旧行为断言保留，新增覆盖前置条件需要的读取用例真实完成分页，不能直接注入伪造完整 receipt。非 CodeAgent 阶段没有委派结果库入口，也不能贡献 CodeAgent coverage；任务 verifier FileRead 仍可按自己 next_read 续读。

## Task 5：CodeAgent 内部 prepare、整组预检与模型最终门（T1/T2/T3/T7/T8/T12）

**Files:** 修改 agents/code_agent.py、core/agent.py；扩展 task_context.py、test_task_context.py、test_task_context_flow.py、test_task_provider_context.py、tests/test_graph.py。

**Interfaces:**

- `TaskToolServices.begin_delegation(attempt_id: int) -> TaskContextSession`；拒绝并发／嵌套活动委派；`close_delegation() -> None` 在 finally 清空所有旧能力。
- `TaskContextSession.set_request(anchors: tuple[Any, ...], binding: RequestBinding) -> None`；`prepare(history: list[Any], todos: list[dict], *, invocation_options: dict | None = None) -> list[Any]`；`plan_group(response: AIMessage, history: list[Any], todos: list[dict]) -> GroupPlan`；`start_call(call_id: str) -> None`；`visible_budget(call_id: str) -> int`。
- `GroupPlan` 持原 AI、工具原顺序、每项最小反馈预留与实际组剩余预算；`finish_group(history: list[Any], result_messages: list[ToolMessage]) -> list[Any]` 验证完整 JSON／配对和最终页 receipt，不制造未执行结果。start_call 激活当前调用；工具通过 `TaskToolServices.result_json_budget() -> int` 得到当前内容 JSON 配额，已扣该 ToolMessage 的固定封装／ID开销；最终页之后不能再隐式缩正文，否则必须撤销旧覆盖并重新提交最终区间。
- `TaskRunContext.preflight_provider_budget() -> None` 只读；`_TaskModel.bind_tools` 保存 RequestBinding 与当前委派身份；`invoke` 在锁内沿原 usage／budget 门后，stage=code_agent 再测实际 B，通过后才递增计数。

- [x] **Step 1：编写失败测试。** `test_many_small_tools_are_not_reserved_as_n_times_16k`、`test_one_large_result_uses_cursor`、`test_impossible_group_stops_before_first_effect`、`test_huge_ai_args_are_never_cut`、`test_task_internal_history_is_bounded`、`test_normal_code_agent_is_unchanged`。用六项小结果构造旧 6×16KiB 会拒而实际表示可容纳的组；检查全部执行、每条≤16384／整组≤32768／B≤98304。真正放不下的组含文件改写与 Bash，断言 write_count=0、approval_count=0；原参数字节一致，响应 usage 计一次。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_provider_context.py','tests/test_graph.py') -ExpectedExit 1`。
- [x] **Step 3：实现 task-only 循环接入。** 在 run_code_agent 的 bind 之前开启当前委派、校验 state.task_context 与 runtime.task_filesystem、增加仅 CodeAgent 续读工具与 TodoUpdate；普通分支使用原 selected_tools／prompt。任务原 Human 锚点显式含完整 task／instruction／acceptance／固定命令，layered memory 只属可整理状态而不能代替它。set_request 实测本次 B_base，≥49152 则固定上下文错误，不通过删锚点降低基线；其它两项可行性约束按最终 binding 的合成夹具验收，实际每轮仍独立检查硬门。每次 invoke 前先预算只读门、prepare 并替换 messages；工具组第一项前测原 AI＋必要历史＋整组最小反馈，不按 N×16KiB。按固定 profile 预留每项最小合法结果，剩余正文原顺序分配，有效组门=min(32768,硬门剩余空间)，仍复算完整请求。原 scope／审批／真实异常先分类，之后才做分页；终止时不执行剩余工具。produced_messages 使用同一有界历史视图，tool_events 在既有投影后只留≤8条固定状态／receipt 引用，无第二份完整原文列表。
- [x] **Step 4：实现锁内模型后备检查与有界返回。** 保存真实 bound schemas、bind kwargs 与 invoke kwargs，不丢工具参数／JSON escaping。非法／孤儿 tool_calls 不执行；unknown tool 按原固定可恢复结果做最小预留。无工具最终摘要及 max_loops 既有收束消息也计量，错误不能返回 ok=true；16 轮与 planner summary/todos 契约不变。代码中实际 gateway 回执字段是 command_request_id，沿原名保留而不发明另一个 request_id。bind/setup 的真实 provider 失败不被新 serializer 覆盖。
- [x] **Step 5：最终基线校准和 GREEN。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context.py','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_provider_context.py','tests/test_graph.py')`。T1 使用最终真实 schema（文件工具、Bash、TodoUpdate、ToolResultRead）和 task-only 原锚点；常见合成夹具固定为 100 行×60 ASCII 字符读取、单处 40 字符编辑／8KiB diff、小 Bash 两路各 1KiB反馈、短 todo、多小组，以及中文／emoji／转义变体；AI 参数全计入，记录具体输入尺寸。不将这些尺寸称为真实分布。三式与胶囊 8KiB 变体不成立即停止审阅，不能进入后续产品验收。

## Task 6：恢复策略、异常透传和先有根因（T5/T10）

**Files:** 修改 code_agent.py 的 execute_code_agent_tool、graph/nodes.py 的两处分发与 verifier、core/agent.py、task_worker.py、task_events.py；扩展 test_task_context_flow.py、test_task_workflow.py、test_task_events.py、test_task_result.py。

**Interfaces:**

- `recovery_for(error_code: str) -> dict | None` 固定映射：window_invalid→retry_same_operation=true；revision_changed／write_coverage_required→false+reread_current_revision；result_unavailable→false+rerun_source_tool_or_reread。不把 scope／approval 加入恢复名单。
- `TaskRunContext.record_terminal_root(kind: str) -> None`：只收已有固定可信类别，首次真实终止优先；`resolve_context_failure(error: TaskContextError) -> str`：有先有根因则原类别，否则缺失 usage／已知预算门优先，最后 task_context_error。不接受模型字符串作为 kind。

- [x] **Step 1：编写失败测试。** `test_window_errors_have_distinct_recovery`、`test_terminal_root_survives_context_and_finally_error`、`test_context_failure_round_trips_fixed_kind_only`、`test_prior_verification_evidence_survives_next_attempt_context_stop`。分别注入 scope/approval、provider、usage、预算、终止执行/回执、verification_command_failed 之后的 TaskContextError，要求 worker/parent 原 kind 不变、usage 快照只一次、内部 reason/sentinel 不公开；可恢复 exit1／edit_match_failed 不锁成终止。正式验证逐条回执／结果不能改 not_run 或自测 passed。
- [x] **Step 2：运行 RED。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_workflow.py','tests/dashboard/test_task_events.py','tests/dashboard/test_task_result.py') -ExpectedExit 1`。
- [x] **Step 3：实现固定恢复与异常透传。** 本地只有明确枚举错误可交模型修正；同一失效 cursor 不自动重试，FileWrite/Edit 不重放，Bash 重跑必须新请求／审批。CodeAgent、planner 委派、verifier 只读分发在通用 except 之前透传 TaskContextError。真正工具失败先锁其可信现有类别，才投影/裁页；不重复外层 tool_failure。Provider 包装保留现有分类与计数，缺失 usage 标志在上下文失败决策中优先，不新增预扣或回减。
- [x] **Step 4：实现 worker／父进程映射与 finally。** 只增加 task_context_error 到 done 白名单、ToolResultReadTool 到固定工具身份。保存先有异常再发既有 budget_usage；若 snapshot/emit 又失败，不能掩盖原真实异常，不能称快照已发布。没有先有异常时仍沿原 worker_failed 等收尾处理，不把所有 finally 错误归上下文。所有终态仍经原 controller 清理，不能绕过 cleanup_failed。
- [x] **Step 5：审阅验证失败的现有映射，再运行 GREEN。** 现有 verifier 正常负 verdict 是图状态与可重试反馈，没有新的终止 failure_kind；缺退出码等命令故障才是 verification_command_failed。本计划按“真实终止根因”保留这一差别：已抛出的验证终止优先；上一 attempt 的正常失败保留其全部 verification_results，下一 attempt 未运行仍按原结果聚合，不改写旧回执。若后续真正 ContextError 停止，只有不存在既有终止类别才使用 task_context_error。这里不新造或扩大 verification_command_failed 语义；若审阅要求正常负 verdict 本身也占后续最终 failure_kind，应先明确设计／现有类别映射，本任务停止，不能自行决定。确认后运行 Step 2 同范围 GREEN。

## Task 7：真实图配假模型的完整流程与普通行为（T7/T11/T12）

**Files:** 扩展 test_task_context_flow.py、test_task_graph_injection.py、test_task_workflow.py、tests/test_graph.py；按失败仅修前述允许文件。

**Interfaces:** 消费任务 1–6 的 TaskRunContext／TaskToolServices／TaskContextSession 与固定恢复／失败契约；产出上述真实入口配假模型的流程测试，不新增产品接口。

- [x] **Step 1：编写流程测试。** `test_reread_then_edit_selftest_and_formal_verifier` 运行真实 TaskRunContext/run_code_agent/TaskFilesystem/图节点配脚本假模型：缺页写入拒绝→重读取得完整同 revision→编辑→假自测 exit1→修复→假自测 exit0→CodeAgent摘要→planner收束→正式原固定命令 request/receipt→verifier verdict。每步检查工具 ID、原命令、固定验证事件、输出标志，绝不执行真实命令；假 usage 不转换为费用。
- [x] **Step 2：编写三个收尾阻断和隐私对照。** `test_budget_blocks_each_closeout_call` 分别在 CodeAgent 摘要／planner／verifier 下一调用处达门；明确 verifier_calls=0 时正式命令可已真实假执行有 receipt。`test_normal_cli_tui_contract_unchanged` 保留普通默认行数／长行／历史返回形状。`test_private_sentinels_never_leave_projection` 检查公开错误、事件、trace/checkpoint/log无合成源码／参数／provider输出 sentinel，task 模式 trace/checkpoint 仍 off。
- [x] **Step 3：运行并修复相关 GREEN。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_graph_injection.py','tests/dashboard/test_task_workflow.py','tests/test_graph.py')`。需要修复时先保留对应失败断言，不弱化 scope／审批／固定验证／计数；新实验仍受上述禁止防护。
- [x] **Step 4：核对设计覆盖。** T1–T12 必须能各指到测试名及实际输出，标记平台 skip／未验证项；32KiB 组预算或完整覆盖门使正常合成路径不可行时回到设计审阅，不提高总门或跳过 planner。

## Task 8：非 Docker 全回归、冻结核验与交接

**Files:** 仅在实施完成后更新实施树交接 `docs/MOKIOCLAW_NEXT_SESSION_HANDOFF_2026-09-29.md`、技术进度 `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`、实施树阶段 B 设计的当前增补，以及主项目瓶颈／接续摘要。不得覆盖其它段落或把新结果写进旧试点记录。

**Interfaces:** 消费任务 1–7 的产品及测试；产出实际回归／冻结比对／文档记录，不提供运行、provider 或远端接口。

- [x] **Step 1：相关整组回归。** `Run-ContextPytest -TestArgs @('-q','tests/dashboard/test_task_context.py','tests/dashboard/test_task_result_windows.py','tests/dashboard/test_task_context_flow.py','tests/dashboard/test_task_filesystem.py','tests/dashboard/test_task_graph_injection.py','tests/dashboard/test_task_provider_context.py','tests/dashboard/test_task_workflow.py','tests/dashboard/test_task_events.py','tests/dashboard/test_task_result.py','tests/test_graph.py')`。
- [x] **Step 2：全项目非 Docker 回归。** `Run-ContextPytest -TestArgs @('-q','-m','not docker')`；记录真实 passed/failed/skipped/deselected、时长与 basetemp。相关步骤通过后才跑这一轮；没有变化或未解失败时不重复无意义全跑。
- [x] **Step 3：Ruff 与 diff。** 指定 Python 执行 `-B -m ruff check --no-cache src tests`；实施树与主项目分别 `git --no-optional-locks -c core.fsmonitor=false diff --check`。新未跟踪文件另做全文行尾空白检查，不能以 Git diff 未包含它为已检查。只修本次引入项，旧 CRLF 警示单独记账。
- [x] **Step 4：秘密格式与冻结字节。** 仅扫本次源码／测试／文档 diff及新增文件，输出类别／位置，不输出值；不读 .env 或用户脚本。前后核对全部冻结 tools/*.py、architectures.py/workflow.py 与既有 Rich／Rich–Click 七份报告清单；路径从既有冻结清单取，缺文件／不一致必须停止，不更新基准哈希。另核对四来源/工作树 HEAD／本地 refs／status及私有诊断资产未改变，不 fetch。
- [x] **Step 5：记录实际验收和授权边界。** 分别写产品改动、纯本地行为证据、实际测试、skip／未运行门、阈值校准结论、平台限度与新固定 kind。计划勾选仅代表确实完成，未运行项不勾；普通模型／真实 token／费用／真实修复能力未验收。工作台旧地址不作在线保证；boltons 无余次，Task10 余 2 不用。收尾保留量、新真实恢复、每个 prepared 启动、Docker、来源补丁应用、提交/push继续单独授权。

## 自审与本轮实际记录

设计覆盖映射：§4→任务1/5；§5→任务1/3/5；§6.1→任务3/4；§6.2→任务2/4；§6.3→任务5；§7→任务4/6；§8 T1–T12→任务1–7及任务8回归；§9→基线停止门、任务3平台门、任务6映射审阅门与任务8的后续授权。

本轮仅只读代码与本地依赖源码，未初始化模型或执行 Python／pytest／Ruff。重新核对四仓：main=4134081、阶段B=033fedb、旧来源=4ca74f9、boltons detached=967864f89791509f9eb36b22b4579d36b72a6df2；本地 heads/remotes 重新查询，未 fetch，既有状态符合前轮。根 SKILL 对同一目标的多个步骤无需重复阅读；完整两树 V1／阶段B设计已在本目标前序步骤阅读，本轮又核对根技能与 AGENTS，不以旧摘要代替设计。

本计划的新增覆盖／cursor 容量、显式 services 注入、恢复内部码与验证映射解释须随计划审阅；没有改产品或测试文件，没有新增离线实验。后续执行方式仍待选择；native 由当前助手逐任务实施，委派需用户明确选择。禁止提交／push覆盖技能的常规 commit 步骤，不安排自动提交。

合法 TaskSpec 的长度上限本身不保证 B_base<48KiB，尤其是多条长命令与多字节任务锚点；这是需要实际夹具揭示的可行性风险，不在本轮用推测结果宣称阈值通过。较大合法任务如果被新输入策略拒绝必须明确报告；如果审阅要求所有合法上限组合都可运行，而夹具不能满足三式，则应修订设计后再继续。

本轮实际文档核对：两树 diff --check 均 exit0，主项目仅有既有 real_test.md CRLF 提示；计划八个任务／36个未勾选步骤，计划与设计行尾空白及有限秘密格式扫描均零项。32份保护清单中新取前后哈希有31份一致，仅主项目 .gitignore 因增加本计划单文件白名单发生预期变化；原十一项产品／测试修改、冻结工具／图、私有诊断资产和其它保护文档未写入。本轮只新增本计划、更新设计批准状态／计划指针和 .gitignore 白名单；这不是产品行为或测试通过证据。

## 逐项离线实施的实际记录与停止门

用户已确认修订设计并明确“在本会话逐项实施”。沿用阶段B工作树，重新查询四仓status／HEAD／本地heads-remotes；主项目main4134081、阶段B codex/mokioclaw-stage-b/033fedb、旧来源master4ca74f9、boltons干净detached967864f保持，未fetch。原十一项修改保留；300000／24是本轮开始前既有代码取值，本轮没有提高它、具体试点预算或输出设置。

已实施任务1–4的基础接口：规范JSON UTF-8计量与完整AI→Tool组整理，固定TaskContextError内部reason；不可变32MiB／32结果／1024cursor内存服务；FileRead／Notepad显式窗口、长行／Unicode／CRLF、最终可见区间coverage和同安全句柄版本写入门；显式TaskToolServices接线、完整diff写前预留、Grep前缀范围声明、Bash上游尾部标记。普通工具冻结树未改。生产CodeAgent尚未begin_delegation，当前任务FileWrite无新coverage证明将拒绝；此为部分实现，不能作为真实任务可运行版本。

任务5先做实际所选9项StructuredTool schema＋完整system／task／planner／acceptance／原固定命令的基线校准。通过本地纯转换器，不构造模型。上限合成TaskSpec为4000码点description、10条各2000码点命令；短夹具与ASCII上限通过，CJK与emoji上限失败。规范字节均已含一次4096裕量：

| 合成夹具 | B_base | 最小两组增量 | 常见两组增量 | 独立失败增量 |
| --- | ---: | ---: | ---: | ---: |
| 短任务 | 9395 | 1686 | 25990 | 2399 |
| ASCII上限 | 33414 | 1686 | 25990 | 2399 |
| CJK上限 | 81314 | 1686 | 22380 | 2399 |
| emoji上限 | 105264 | 1686 | 21311 | 2399 |

CJK的81314≥49152、83000≥73728、106093≥98304，三式均失败；emoji基线本身105264>98304。常见夹具固定100行×60码点＋LF（6100码点）读取、40码点编辑参数、8192字节ASCII diff、stdout／stderr各1024字节；不是模型真实分布或费用证据。按已审设计§4“任一基线约束或核心路径不成立，判定当前阈值方案验证失败，报告并重新审阅参数”停止，不删锚点、不调门、不把失败改成xfail。

TDD实际记录：任务1先12 failed后12 passed；任务2先7 failed后7 passed，收尾补测多段正文合计门先1 failed后8 passed（修正为整页合计≤8192，而非每段各8192）；任务3有效RED 10 failed／11 passed，GREEN 21 passed，首轮参数ID过长导致4个Windows setup errors不算有效RED；任务4新场景6 failed／10 passed，显式迁移旧fixture后121 passed，再补StructuredTool布尔／小数坐标先2 failed后123 passed。基线接口先4 failed（未实现完整锚点builder），实测校准2 failed／2 passed。这些小组结果不与最后整组相加计成绩。

最终指定Python、显式PYTHONPATH=src、-B／PYTHONDONTWRITEBYTECODE=1、无pytest缓存、仓库外独立basetemp的相关整组（含保留的基线门）为 **240 passed、2 failed、0 skipped、14.30秒，exit1**，1条既有Starlette/httpx弃用警告；两项失败只为CJK／emoji基线门，仍是未通过验收。basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-context-371958561846469c93c331356b07e87e。单独不含校准门的较早相关组237 passed／13.88秒不覆盖后来新增合计门；最终以240／2为准。Ruff --no-cache src tests exit0；首次F401仅本轮未用Path导入，已用apply_patch移除。

新增合成实验在构造工作流前封锁provider构造／普通模型、dotenv及已导入别名、socket连接／监听、DockerCLI、真实IsolatedCommandExecutor、subprocess.run/Popen和os.system，触碰即失败；不复制真实任务文本或调用真实命令。相关回归中的既有回环／junction夹具沿原边界运行，不把新增禁止fixture套到它们。没有provider、Docker、真实Task、工作台连接、.env秘密读取、temp.py执行、旧补丁处理／来源写回、commit／push／远端变更；boltons余0／Task10第五批余2保留，停止讨论仍在。

未解决／未运行：任务5内循环实际替换历史、组首屏32KiB与单ToolMessage完整JSON16KiB配额、真实绑定模型锁内后备门、六小工具／巨大参数零副作用、最终摘要及返回有界尚未接入；任务6异常透传／先有根因／单公开kind、任务7真实图配假模型的自测与正式收尾、任务8全项目非Docker回归／独立最终审阅未开始。8KiB胶囊增长、全部绑定组合、T10根因竞合与T11／T12新增全链路验收未执行；已有普通图／提示回归不能替代它们。未运行provider／Docker／真实逐次token或费用测量，不以旧803／12项探针或正文65.3%当新证据。

下一步审阅基线适用域：建议保留96／72／48KiB，明确较大合法TaskSpec在CodeAgent完整锚点基线预检固定拒绝，并把三式可行性验收限定为准许运行的输入域；若要求所有合法TaskSpec上限组合都可运行，必须先明确另一套阈值设计。两方向都需书面确认，不能自行提高总预算、删要求或改TaskSpec/API字段。确认后从任务5继续，不重做1–4；完成内部离线验收后才另审同一总门内收尾保留量。具体真实恢复、每prepared启动、Docker、来源补丁应用、提交／push仍分别授权。执行ledger及全部裁定位于实施树.superpowers/sdd/2026-10-04-mokioclaw-task-codeagent-context/progress.md；用户禁止提交，ledger保留。

最终保留性／格式核验：24份本轮新增文件、目标修改行及新文档段落的有限私钥／凭据格式扫描0命中，全文行尾空白0项；这是有限格式检查，不宣称完整秘密检测。主项目与实施树diff --check均exit0，主项目只有既有real_test.md CRLF提示，未改它。新取32份保护清单前后有23份相同、9份为本轮明确修改的产品／测试／记录；原静态页面／事件／API服务与对应既有测试、主项目.gitignore／旧阶段B设计／real_test、四份私有诊断资产保持。全部8份tools/*.py＋architectures.py／workflow.py共10份冻结源码保持；主项目Rich三份与Rich–Click四份共7份冻结报告SHA256逐项与既有清单及本轮起始匹配。四仓结束HEAD与全部本地heads/remotes未变，两个来源status保持（旧来源原未跟踪文档、boltons干净）；Git全局ignore不可读警告仍在，未修改配置。文件保留核验不把未跟踪／未提交内容当成已发布版本。

## 接续任务5–8的实际验收（修复前历史验收；最终结果见下节）

用户“批准调整”后，从任务5接续，保留96／72／48KiB、原预算／16轮／planner与verifier／attempt路径。现在任务CodeAgent在每次内部调用前实际替换有界历史，锁内按真实绑定schema与调用选项再次检查，完整锚点基线≥48KiB明确拒绝，非法工具组或不能容纳整组最小反馈在第一项工具前停止。单ToolMessage完整规范JSON≤16KiB、整组首屏≤32KiB；最终源码窗口才贡献coverage，已有文件FileWrite要求当前委派／同版本完整证明，同安全句柄写前核对revision；FileEdit仍逐字唯一匹配。

ResultRead只给CodeAgent，不给planner／verifier；结果库仅内存、当前委派，已执行片段才能签发cursor。巨大diff先做私有容量及首屏预留，写失败不公布候选；Bash上游丢尾部明确不可恢复，重跑仍须新请求／审批。已有安全／provider／usage／预算／终止工具／verification_command_failed优先；正常负verdict仍沿图状态，上一attempt的正式回执不抹除。公开只新增task_context_error与固定工具身份，无内部reason／路径／字节／prompt／源码／provider输出字段。

新增实验只使用合成文件／反馈、脚本模型和明确注入的假执行器，封锁provider／dotenv／真实网络／Docker／真实命令；协议新测试为内存帧，审批只对应确切合成请求，不能带入产品。真实图路径观察到缺页写入拒绝→重读同版本完整覆盖→写入→自测exit1→唯一编辑修复→自测exit0→摘要→planner→原固定命令独立请求／回执→verdict。正向12次假模型调用；三个收尾门9／10／11分别挡摘要、planner、verifier。最后一种verifier模型0调用而正式命令已取得第三份回执，不据零调用改not_run。

指定Python、PYTHONPATH=src、无字节码／pytest缓存、仓库外独立basetemp：相关整组287 passed／16.66秒，exit0（mokioclaw-context-22fc7a11a31c4f2db6827207bb587f5e）；全项目非Docker890 passed、3 skipped、35 deselected、169.74秒，exit0（mokioclaw-context-636bec3eb96945fca6fb7661cc37a904）。三项skip为tests/dashboard/test_catalog.py:76及tests/evals/test_grader.py:204、219的symlink创建不可用；35项Docker标记未运行。两组均1条既有Starlette/httpx弃用警告。Ruff --no-cache src tests exit0。以上为修复前历史验收；最终作者自审与修正后回归见下节，不能当作真实模型能力或费用证据。

未解决边界：字节门不等于SDK报文／token／费用；合法TaskSpec可能被基线门拒绝；整理后信息不足仍需重读；覆盖不证明理解／重建正确，POSIX不声称跨进程原子CAS；不可分的超大Grep单项记录可能在只读查找后显式失败；库淘汰不能恢复旧diff或上游丢尾。真实重复读轨迹、逐次token、真实修复成功率及同一总门内交接／verifier保留量仍未验收。没有provider、Docker、真实任务、.env秘密读取、temp.py、旧补丁／来源写回、提交／push／fetch；boltons余0、Task10第五批余2保留，停止讨论不解除。真实恢复／每prepared启动、Docker、来源补丁应用、提交／push和收尾保留量继续分别授权。旧49485地址不作在线保证或运行许可。
当前最终9项schema与实际会话最小胶囊的纯本地校准（6 passed／1.35秒，独立basetemp mokioclaw-context-e0cda26897514c158ffaad03540f7c2a）：短任务B_base=9385、ASCII上限33404；对应最小两组增量1686、预定义保守常见两组25990、独立失败2399；8KiB胶囊变体基线17385／41404，准入域三式成立。CJK／emoji合法上限81304／105254在完整锚点门明确拒绝，真实入口已测零invoke／零写入／零审批。Schema差异与实际胶囊字段使数字不同于旧停门记录，旧81314／105264与2 failed不倒改。保守常见组来自固定100×60码点窗口／40码点参数／8192字节diff／两路各1024字节反馈，独立于真实模型分布；实际首屏还受完整ToolMessage及组配额。原8KiB胶囊增长、语言／转义、绑定／调用选项与硬门±1均有离线断言，不承诺费用下降。

## 任务1–8最终离线验收与作者自审

用户最后明确“不要使用子agent执行任务”；已中断此前只读审阅者，未采用其实现或审阅结论，后续均在本会话直接完成。本次最终审阅为作者自审，独立盲点发现能力较弱，不称独立审阅通过。当前任务1–8已完成授权的产品实施、离线验收和记录，无待实施计划项；未发现需要延期的Minor项，但这不等于完整独立审计。

作者自审在一个修复回合内确认并修正四项Important边界，每项均先有失败断言：
1. 整组第一项工具执行前，原AI响应及全部最小ToolMessage反馈一并计入整理压力；旧可删完整组先FIFO整理，保留原参数、最近两组及必要失败，不因可删历史提前拒绝或先执行副作用。
2. 多段结果首屏先为每段最小进展及其JSON转义预留，再分配剩余空间；私有preview不签发cursor，整页正文与规范JSON同时受限，续读可精确恢复全部已保存段。
3. 空AI摘要只查产出的AI／Tool历史，不把锚点胶囊误当摘要返回；普通CLI/TUI分支未改。
4. Grep明确保留head_limit／长行前缀的上游不完整性，结果库读到保存尾部仍complete=false，不伪造已丢弃匹配项。

实际RED两组各2 failed（1.49／1.51秒），修复后核心四文件90 passed／4.10秒；最终相关12文件 **291 passed、0 failed、16.65秒、exit0**，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-context-212ec312843d4bd797a76702668fae10。最终全项目 **894 passed、3 skipped、35 deselected、168.24秒、exit0**，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-context-70e6eced452e4caaa46a1ff3c43f33b6。均使用指定Python、显式PYTHONPATH=src、无字节码／pytest缓存、仓库外独立basetemp；新增实验仍封锁provider初始化、网络、Docker与真实执行器／命令。3项skip仍为catalog.py:76、grader.py:204／219的符号链接创建不可用，35项Docker未运行；均1条既有Starlette/httpx弃用警告。此前287／890只是修复前历史结果，240／2仍是调整前基线门失败，不倒改。

修复后Ruff --no-cache src tests exit0；最新21份保护哈希（10冻结源码、7冻结Rich／Rich–Click报告、4私有boltons诊断资产）与本轮起始逐项一致。四仓HEAD／本地heads-remotes重新查询均不变，旧来源仅原未跟踪文档，boltons干净detached；既有修改保留，未fetch。最终文档后两树diff --check均exit0，主项目仅既有real_test.md CRLF提示；31个明确源码／测试／文档／ledger目标的新增全文或修改行有限私钥／凭据格式、行尾空白扫描均0命中，缺文件0。这是有限格式检查，不宣称完整秘密检测。

阈值96／72／48KiB、完整锚点≥48KiB拒绝、32KiB组门与16KiB完整ToolMessage门保持；保守校准量只检验准入域，不等于SDK报文、token或费用。信息不足须重读；coverage不证明理解／重建正确；POSIX不声称跨进程原子CAS；不可分的超大Grep记录可在只读查找后显式失败；结果库淘汰或上游丢尾无法恢复。真实阅读选择、逐次usage、费用与修复成功率未验证，同一总门内交接／verifier保留量仍待另行设计审阅。

没有provider／Docker／真实试点、预算提高、.env秘密读取、用户temp.py、旧补丁整理／应用、来源写回、提交／push／远端变更。boltons余0、Task10第五批余2保持，连续未正式完成后的停止状态不解除，旧49485不是在线保证或运行许可。下一步可另行审阅同一总门内收尾保留量；真实恢复及每个prepared启动、Docker、来源补丁应用、提交／push仍各需授权。
