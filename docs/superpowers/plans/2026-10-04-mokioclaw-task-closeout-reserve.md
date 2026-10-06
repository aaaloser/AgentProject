# MokioClaw 任务收尾保留量逐项实施计划

> 2026-10-04 用户验收：用户明确“先接受这个离线实现吧”，本轮收尾七项离线实现已接受，保留此前内部上下文能力；这不代表整个阶段B或真实维护能力已验收。真实token／费用、摘要质量与维护成功率仍待单独校准；真实停止门保持，boltons余0、Task10第五批余2保留，不授权provider／Docker、真实恢复或每个prepared启动、预算提高、来源应用、提交／push，禁止子agent。本次仅记录验收，不重跑产品测试，381／977等仍为前次实施验证。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已指定在本会话直接逐项实施、禁止子agent；不采用subagent-driven-development、子agent审阅或另建聊天。Steps use checkbox (- [ ]) syntax for tracking.
>
> **状态（2026-10-04）：** 用户已批准本会话逐项实施，七项产品／离线交付已完成，禁止子agent。最终相关381 passed；非Docker977 passed／3 skipped／35 deselected；Ruff通过。具体实测与作者自审见文末及实施树交接§60／进度§99。真实恢复、provider／Docker、预算提高、来源应用及Git发布仍分别授权。

**Goal:** 在原任务总调用／已报告token门内提前结束继续修复，给真实交接、planner、固定验证及verifier留出受限调用机会。

**Architecture:** 纯数值协调器只管理内部用途配额与usage预测，TaskRunContext锁下负责可信接线；共享实际入账保持唯一。任务节点改变工具绑定和循环用途，不修改冻结图路由或普通CLI/TUI。验收采用纯单测加真实图、脚本模型、内存审批帧和假执行器。

**Tech Stack:** 现有Python >=3.13、LangChain／LangGraph、pytest、Ruff；不新增依赖、API控制字段、数据库或日志服务。

**Spec:** 主项目 [完整设计](../specs/2026-10-04-mokioclaw-task-closeout-reserve-design.md)，执行前必须完整读；同时遵守两树根SKILL指定的V1／当前阶段B完整设计，最新实现依据阶段B树，不能将主项目较旧根设计当当前授权。

## Global Constraints

- 产品／测试仅在 C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent 修改；本计划／独立设计在主项目。复用已有工作树，不新建、不重置、不清理、不覆盖既有dirty／untracked内容；项目文件只用apply_patch。
- A2：摘要1、planner2、verifier2，加planner后／verifier后压缩各1，共最多7收尾调用槽；CLOSING不可逆，不跨用途借槽，不因释放剩余槽重新修复。
- B3：alpha=1.25，用整数ceil(5*x/4)实现；E_s=ceil(alpha*max(原输出上限O,本用途单次有效usage最大值))，用途无样本回退全task最大值；R_tokens=sum(n_s*E_s)。预测只限制继续修复，收尾invoke仍逐次走原共享门。
- 首个修复委派C>=8；整个task唯一首次repair可免token预测拒绝，但不免原总门。后续委派重算包含新摘要的完整保留集合；新attempt最低C>=9，含起始planner一次，且已有usage预测允许修复，检查早于begin_attempt。
- 缺失／非法usage停止，不补零；合法0有效。调用／已报告token及最大值跨attempt不清零；最后响应仍可能越门，不能承诺费用、时间、质量或正式完成。
- 保留CodeAgent最多16轮、planner／verifier各最多8轮。末轮前提前摘要／收束；不增加第17或第9次调用，不用本地伪摘要冒充真实模型交接。
- CLOSING verifier首次最多3项工具，一组仅FileReadTool／GrepTool／NotepadReadTool；第二次无工具。固定命令原样独立走网关／逐项审批，先于verifier模型，不给模型额外Bash，不复用自测审批。
- 保留system／完整任务／固定命令锚点、必要状态、最近完整AI→Tool组／失败、tool_call_id、JSON及当前窗口／coverage。96／72／48KiB、32KiB组门、16KiB完整ToolMessage与完整基线>=48KiB拒绝保持；verifier不自动获得CodeAgent结果库。
- 只新增固定公开task_closeout_incomplete；内部reason仅budget_slots_insufficient／phase_limit／invalid_handoff，不入Public Event／日志。closeout_requested只是本地可恢复反馈，不是终态根因。
- 原scope、审批、命令、provider、usage、预算及上下文根因保持优先；固定回执、verification_status、模型verdict与TaskRecord终态分别判定。取消／超时／cleanup不被收尾状态覆盖。
- 不修改冻结src/mokioclaw/tools/*.py、graph/architectures.py、graph/workflow.py或冻结报告／私有诊断证据；不读.env秘密值、不执行用户temp.py、不整理／应用旧Agent补丁。
- C2新增实验只用合成数据、脚本模型／假执行器，先封锁provider／dotenv／网络／Docker／实际命令；禁止入口即使异常被产品捕获也使测试失败。协议仅内存帧，不新开TCP监听。
- 无provider smoke／真实试点／预算提高／Docker／来源写回／提交／push／fetch／远端变化。boltons余0，Task10第五批余2保留与停止状态保持；真实恢复及每prepared启动仍单独确认。
- 后续pytest用D:\envs\codeagent\Scripts\python.exe，显式PYTHONPATH=src、PYTHONDONTWRITEBYTECODE=1、-p no:cacheprovider，每次仓库外独立--basetemp；相关及全项目非Docker回归、Ruff --no-cache、diff／有限秘密格式扫描、冻结哈希须新鲜实测，逐项报告skip。

## Review Focus

1. 有效usage=0与未出现用途必须区分：不能用truthiness把0替换成其它阶段高值；任务1／2有专门断言。
2. 解绑工具后的真实binding和调用选项仍受完整上下文门：不能沿用旧schema或遗留强制tool_choice；任务3覆盖。
3. planner正在处理的响应可能跨越nested CodeAgent调用：保留原planner调用号，不能拿委派后的provider_calls二次入账；任务4覆盖。
4. 读工具数量少仍可能返回长行／巨大结果：既有不可恢复尾部与信息不足必须如实保留，3项不当成正文／token门；任务5／7覆盖。
5. retry准入拒绝与已开始的新attempt是两种事实：前者保留上一attempt，后者如实not_run，不回滚或挪用旧回执；任务6／7覆盖。

## 文件结构与依赖

以下相对代码／测试路径均相对上面的阶段B实施根，行号是规划时定位，不作为执行时固定偏移。已有模块不整文件重构。

| 创建／修改 | 单一职责 |
| --- | --- |
| 新增src/mokioclaw/core/task_closeout.py | 纯数值状态、预测、用途配额与固定异常 |
| 修改src/mokioclaw/core/agent.py | TaskRunContext／_TaskModel可信用途、锁、usage与根因接线 |
| 修改src/mokioclaw/agents/code_agent.py | 任务repair／真实摘要切换，现有完整历史与绑定校验 |
| 修改src/mokioclaw/graph/nodes.py | planner准入／收束、verifier受限读取、两个压缩分支与attempt准入 |
| 修改src/mokioclaw/dashboard/task_worker.py | 新固定kind的worker／父进程透传；原投影不扩字段 |
| 修改tests/dashboard/task_context_fakes.py；新增task_closeout_fakes.py | 可复用保护钩子、带sticky审计的离线夹具 |
| 新增tests/dashboard/test_task_closeout_policy.py | 纯策略、错误、边界 |
| 新增tests/dashboard/test_task_closeout_context.py | 模型包装、usage、根因、worker内存协议 |
| 新增tests/dashboard/test_task_closeout_agents.py | CodeAgent与planner模式／配对 |
| 新增tests/dashboard/test_task_closeout_verifier.py | 固定命令／读取／判定 |
| 新增tests/dashboard/test_task_closeout_flow.py | 两处压缩、attempt、整图与结果 |
| 按真实需要修改既有test_task_context_flow／test_task_provider_context／test_task_workflow／test_task_result.py | 新政策与已有契约交叉回归，不删除既有断言掩盖失败 |

TaskSpec、TaskRecord、TaskResult目前failure_kind为str或None，无枚举允许域；计划不改这些数据字段。父进程确切白名单在task_worker.py。verifier_invalid是既有内部TaskExecutionError，worker当前归一化为task_tool_failed；本计划保留该路径，不顺带新增公开verifier_invalid。

依赖顺序：1 → 2 → 3 → 4 → 5 → 6 → 7。所有步骤仅在计划审阅通过后执行。

## 后续验证命令约定（本轮不执行）

每个“运行Q”步骤分别展开以下命令；Q接收当前任务列出的测试文件／节点，并且每次调用都重新创建basetemp，不复用RED／GREEN目录。无前缀的test_task_*.py按结构表定位到tests/dashboard/；tests/test_task_command_policy.py与tests/test_graph.py始终使用明确根路径：

~~~powershell
Set-Location -LiteralPath 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent'
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$taskBasetemp = Join-Path ([System.IO.Path]::GetTempPath()) ('mokioclaw-closeout-' + [guid]::NewGuid().ToString('N'))
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest <Q的测试目标> -q -p no:cacheprovider --basetemp=$taskBasetemp
~~~

执行前只读确认GetTempPath的最终绝对路径不在四个Git库／来源／证据根内，否则选已确认的仓库外临时目录。<Q的测试目标>是下方明确列出的参数替换位置，不是可直接执行的字面命令；最终记录展开后的命令、exit、数量、时间和实际basetemp。RED必须为预期缺接口／策略断言失败，保护钩子或夹具错误不是合格RED。不安装依赖、不清理旧临时目录。

---

### Task 1: 纯配额策略与严格离线保护

**Files:** Create core/task_closeout.py（完整src前缀见结构表）、tests/dashboard/task_closeout_fakes.py、test_task_closeout_policy.py；Modify tests/dashboard/task_context_fakes.py 的offline_context_guard。

**Interfaces（新增，均仅Python内部）:**

- CloseoutPurpose枚举：REPAIR、HANDOFF、PLANNER、PRE_COMPRESS、VERIFIER、POST_COMPRESS；与公开stage分离。
- CloseoutMode枚举：INACTIVE、REPAIR、CLOSING、FINISHED、FAILED；后两者只描述本地工作流，不直接发布TaskRecord终态。
- TaskCloseoutError(reason: Literal["budget_slots_insufficient","phase_limit","invalid_handoff"])；str(error)固定为task_closeout_incomplete，不接受其它reason。
- TaskCloseout(output_limit: int)：mode、remaining_calls: int、remaining_tokens: int、delegation_admitted: bool只读属性。
- begin_attempt(attempt_id: int) -> None：首次激活／新attempt重建五用途槽；同attempt重复调用幂等，非连续新ID拒绝，usage与首次repair标记不清零。
- estimate(purpose: CloseoutPurpose) -> int：按有效样本存在性和整数系数计算，不用truthiness判断0。
- record_usage(purpose: CloseoutPurpose | None, total: int) -> None：更新numeric最大值；None仍贡献h_all，0有效；拒绝bool／负值。
- admit_delegation(*, calls_left: int, tokens_left: int) -> bool：按将开始的新委派七槽集合判准入；CLOSING拒绝，本委派已经准入则幂等。成功才重建待完成集合并置delegation_admitted；真实接受HANDOFF后该标记释放。首次免预测只在第一次实际repair开始时消费，不在准入／绑定时消费。
- decide_repair(*, calls_left: int, tokens_left: int, iterations_left: int) -> CloseoutMode：按<=边界或末轮锁定CLOSING。
- enter_closing() -> None；claim_invoke(purpose: CloseoutPurpose) -> None；complete_phase(purpose: CloseoutPurpose) -> None：锁定、实际invoke开始时消费、真实完成用途后释放，complete_phase幂等。
- adopt_planner_response(call_no: int, total: int) -> None：只把已开始响应计作PLANNER第一槽，不增加总账；同一调用号重复采用幂等，内部最多保存24个数字身份。
- admit_next_attempt(*, calls_left: int, tokens_left: int) -> bool：C>=9且T>新七槽R_tokens+E_PLANNER+E_REPAIR，不沿用上一attempt已经释放的集合，不修改attempt。
- note_node_return(node: Literal["planner","verifier"]) -> None及monitor_origin只读属性：只记录可信返回位置，供Task6区分两处压缩，不接受模型metadata。
- finish(*, failed: bool) -> None：工作流局部结束，不清usage。
- offline_context_guard(monkeypatch, *, on_forbidden: Callable[[], None] | None = None)：新增可选回调保持旧调用兼容；offline_closeout_guard(monkeypatch) -> ContextManager[OfflineAudit]包装它，退出时检查sticky触碰记录。
- OfflineAudit.hits: list[str]只含固定类别；ScriptedCloseoutModel(script: Sequence[dict[str, Any]])、FakeCloseoutExecutor(script: Sequence[dict[str, Any]])记录数字、ID、工具名称和合成回执，不持久化messages正文。bind_tools返回拥有独立不可变binding的代理，共享脚本位置／实际调用计数，不让后一次绑定覆写前一阶段代理；非法usage夹具必须保留原类型，不被测试构造器预先转成合法int。

- [x] **1. 准备严格测试保护接口。** 在任何新增pytest执行前，建立本项的offline_closeout_guard／OfflineAudit并给旧offline_context_guard增加兼容回调；沿既有入口阻断并补HTTP实际请求阻断，先记录sticky触碰再抛固定异常。这里只准备测试夹具，不实现配额产品代码。
- [x] **2. 写失败断言。** test_task_closeout_policy.py：
~~~python
# test_call_and_token_boundary: 每个场景使用新policy，先begin_attempt(1)。
assert fresh_policy(100).remaining_calls == 7
# fresh_policy是本测试文件构造TaskCloseout(100)并激活attempt=1的局部辅助函数。
# 记录有效repair=0后，E_repair=125，R_tokens=875。
p = fresh_policy(100)
p.claim_invoke(CloseoutPurpose.REPAIR)
p.record_usage(CloseoutPurpose.REPAIR, 0)
assert p.remaining_tokens == 875
assert p.decide_repair(calls_left=8, tokens_left=1001, iterations_left=2) == CloseoutMode.REPAIR
assert p.decide_repair(calls_left=8, tokens_left=1000, iterations_left=2) == CloseoutMode.CLOSING
~~~
另写test_zero_sample_is_not_missing（先record_usage(None,5000)，再实际claim repair并record_usage(REPAIR,0)，estimate(REPAIR)==125）、test_bootstrap_is_once_per_task、test_release_does_not_reopen、test_cross_phase_borrow_rejected、test_adopt_is_idempotent、test_admission_7_8_9_and_retry_8_9_10。每个断言独立夹具，不把已锁定policy拿来测试“恢复repair”。系数1.0／1.5只作独立手算参考oracle的决策对照，生产初值固定1.25，不为它们新增运行配置。

- [x] **3. 运行RED Q：** tests/dashboard/test_task_closeout_policy.py；预期新产品模块／接口不存在或上述行为断言失败，不以缺保护夹具作为RED。
- [x] **4. 实现纯模块。** 使用整数(5*x+3)//4，无provider／dotenv／执行器导入；剩余配额按五用途表。REPAIR不消耗收尾槽。首次标记在实际REPAIR claim时消费，即使SDK失败也不再次给予免预测机会。未激活不影响入口聊天。
- [x] **5. 验证离线审计的负样本。** test_guard_remembers_swallowed_error中仅主动调用已被替换的合成禁止钩子、捕获异常后断言保护上下文退出仍失败，绝不真正初始化provider／连网／启动命令。预期触碰测试使用独立审计实例，不豁免产品路径。
- [x] **6. 运行GREEN Q：** 同文件及test_task_context.py；exit0、无意外保护触碰。作者核对7槽、整数±1、两个压缩槽与局部状态不冒充任务终态；记录本项结果，不提交。

### Task 2: 可信用途、唯一入账、根因与worker透传

**Files:** Modify src/mokioclaw/core/agent.py:44 (_TaskModel)、:115 (TaskRunContext)；dashboard/task_worker.py:28 (run_projected_workflow)、:消费done消息、:487 (_worker_main)；Create test_task_closeout_context.py。

**Interfaces:**

- Consumes Task1的TaskCloseout／CloseoutPurpose／TaskCloseoutError。
- TaskRunContext.closeout: TaskCloseout；model(*, stage: str, purpose: CloseoutPurpose | None = None) -> _TaskModel保留旧stage调用兼容。
- TaskRunContext.begin_attempt原接口保持：成功确认attempt后同步pure begin_attempt；同attempt原early-return仍需幂等激活协调器，不重复set_attempt或作废审批。
- _TaskModel.for_purpose(purpose: CloseoutPurpose) -> _TaskModel；bind_tools保持purpose，保持当前委派身份／真实RequestBinding。
- TaskRunContext.check_known_failure() -> None：已有可信根因／缺usage先停止；不凭预测登记失败。用于新工具组前，不把模型调用总门移到正式命令之前。
- resolve_closeout_failure(error: TaskCloseoutError) -> str：已有根因、usage／实际硬门优先，否则确切task_closeout_incomplete；与原resolve_context_failure同第一根因原则。
- _model_for(state, *, stage: str | None = None, purpose: CloseoutPurpose | None = None)：Task4接入节点时使用；普通分支忽略purpose、沿原模型入口。

- [x] **1. 写失败断言。** test_purpose_binding_keeps_single_accounting：脚本模型HANDOFF一次total=17，断言provider_calls==1、reported_tokens==17、code_agent_calls==1、code_agent_reported_tokens==17、剩余槽少1、snapshot仍恰12字段；bind_tools重绑不计调用。test_failed_invoke_consumes_one_slot只计已开始1次、不伪报usage。
- [x] **2. 写根因／协议断言。** 缺失／bool／负usage后下一invoke与新工具组都零执行；usage=0有效。测试硬门、已有scope／审批／命令根因、上下文输入拒绝和cleanup异常不被新kind覆盖；惰性model未调用时provider构造0次。worker采用FakeConnection（recv/send内存帧）覆盖新kind确切放行、未知kind拒绝、budget_usage一次且12字段不扩、complete缓冲在失败时不发布。
- [x] **3. 运行RED Q：** tests/dashboard/test_task_closeout_context.py；预期接口／透传缺失断言失败，保护触碰不算合格RED。
- [x] **4. 修改锁下接线。** 顺序为原预算／输入协议校验→用途校验→claim成功后实际开始一次入账→SDK invoke→有效usage原总账与numeric最大值一次更新；用途拒绝不计一次实际调用。stage／purpose只接受固定匹配：code_agent对REPAIR/HANDOFF、closing planner对PLANNER、verifier对VERIFIER、context_compressor对前/后压缩；REPAIR的普通planner规划仍允许None，活跃收尾不能通过purpose=None绕过。未激活的entry/chat／既有直接计量测试保持。
- [x] **5. 端到端处理固定异常。** 把TaskCloseoutError在节点／工具dispatch中按类型透传，不经通用异常分支误记task_tool_failed；在_TaskModel根因允许域及worker父进程白名单增加仅一个固定kind。TaskExecutionError旧归一化不改，TaskContextError／provider原公开路径保持；不把任意str(exc)或模型字段当新kind。run_projected_workflow在原usage结束检查后才标记本地FINISHED，异常标记FAILED；均不直接发布资源未清理的TaskRecord终态。
- [x] **6. 运行GREEN Q：** 新文件、test_task_provider_context.py、test_task_workflow.py、test_task_events.py；exit0。若既有夹具带真实回环协议，新增本项场景仍只用内存帧；不把“全项目原有测试使用回环”误称新增模型探针允许网络。

### Task 3: CodeAgent提前交接与完整上下文保持

**Files:** Modify agents/code_agent.py:173 (_run_task_code_agent)、必要任务提示（同文件）；Create test_task_closeout_agents.py的CodeAgent部分；必要复用既有test_task_context_flow.py。

**Interfaces:**

- Consumes context.closeout、check_known_failure、_TaskModel.for_purpose及Task1数值准入。
- 新增_task_code_agent_mode(context, *, iterations_left: int) -> CloseoutMode，先原preflight，再纯策略；run_code_agent公开签名／普通分支保持。
- _run_task_code_agent本身也核对准入，调用方已经准入时不重置／消费第二份配额；通过delegation_admitted识别，不接受工具／模型传来的标记。直接任务入口仅在mode=INACTIVE时幂等激活当前attempt，不在每个委派重置。

- [x] **1. 写失败断言。** test_code_agent_switches_before_eighth_remaining_call用合成usage／24调用任务，断言C=7时无下一REPAIR，仅HANDOFF；test_natural_summary_is_not_called_twice断言真实自然摘要不再invoke；test_last_iteration_is_handoff断言总循环<=16，max_loops=1也不增加一轮。
- [x] **2. 写绑定／信息断言。** 在脚本模型invoke中即时断言HANDOFF绑定无工具／无强制tool_choice，session.binding与实际wrapper一致，完整system／任务／固定命令锚点未变，最近两组及大参数／失败原ID保持；只存数字与ID作为观察结果。非法工具摘要／空摘要失败、零工具副作用／零额外重试；full-binding基线>=48KiB仍零invoke，不用解绑绕过已批准准入域。
- [x] **3. 运行RED Q：** 新文件的CodeAgent测试；预期未切换／重复调用／绑定不一致等断言失败。
- [x] **4. 实现任务模式切换。** REPAIR仍用现有schema；CLOSING重新bind_tools空集合并set_request原anchors与真实binding，再用现有session.prepare。一次真实摘要，保留未完成／未自测／实际失败信息，不写“已正式验收”。模型返回无工具的自然摘要接受一次并complete_phase(HANDOFF)。
- [x] **5. 保留整组边界。** 缺usage／已有根因在尚未执行的工具组前停止；已通过完整现有准入且开始的组完成配对再摘要，scope／审批／真实工具失败仍立即终止，不执行剩余副作用凑配对。新模式不新增自测／写入；finally关闭委派不掩盖第一根因。受限摘要违反协议用固定invalid_handoff，不退回本地旧停止提示冒充摘要。
- [x] **6. 运行GREEN Q：** test_task_closeout_agents.py、test_task_context_flow.py、test_task_context_calibration.py、test_task_scope.py；exit0。对因新准入改变的小预算修复夹具明确断言政策拒绝，不能无说明调大预算删旧安全断言。普通CLI/TUI分支行为回归留在Task7。

### Task 4: planner准入与两槽收束

**Files:** Modify graph/nodes.py:43、:199、:569、:680、:704；Extend test_task_closeout_agents.py的planner部分。

**Interfaces:**

- Consumes前述_task_model用途及pure admission／adopt_planner_response。
- _task_planner_tools(state, writer, *, final_reply: bool) -> list[StructuredTool]：首收束仅TodoWriteTool，最终答复空集合。
- _closeout_delegation_result(context, call: dict[str, Any]) -> dict[str, Any] | None：仅对已注册委派且合法原参数，在已锁定时返回固定{"ok": False, "error": "closeout_requested"}，其余保留既有dispatcher；调用ID仍由原ToolMessage配对。
- _call_code_agent_tool保持原接口，准入检查早于context.model／服务创建／bind；首次准入失败明确抛TaskCloseoutError，已有交接后的后续拒绝才走soft反馈。

- [x] **1. 写失败断言。** test_second_delegation_is_refused_before_model_binding断言服务／binding／repair增量均0；test_multidelegation_group_closes_with_all_ids断言同一AI组两个委派首个交接后第二个原ID得到closeout_requested、无task_tool_failed根因；未知工具与非法已知参数仍按原语义，不笼统豁免ok=false。
- [x] **2. 写调用号断言。** planner.invoke返回后立刻保存该真实调用号和有效numeric usage，随后nested CodeAgent改变总provider_calls。test_pending_planner_response_is_adopted_once断言采用原planner调用号只消费一个planner槽、总调用／token不二次入账，ToolMessage全配对后只再一次无工具收束。
- [x] **3. 运行RED Q：** test_task_closeout_agents.py的planner测试；预期再次委派／重计／错误根因失败。
- [x] **4. 接入工具与循环。** invoke前若C<=未来收束所需槽或迭代只剩2次，提前锁定；未有实际委派时不编造CodeAgent摘要，标记其用途不需要并保留“尚未实施”的真实状态。原有summary已接受时释放摘要槽，若准入后续委派则按七槽重新预测。真正closing调用才消费PLANNER槽，普通规划不提前花掉它。
- [x] **5. 处理已产出组切换。** 首个使closing的委派返回后，采用保存的planner调用号；当前整个AI组仍按已知参数校验、原ID反馈，关闭后续修复／research入口。TodoWriteTool仍不能替换固定验证命令、不自动completed；最多第二次无工具答复。第8轮不存在额外第9次，错误／局部槽耗尽明确phase_limit。自然无工具结束的planner进入closing并complete_phase(PLANNER)，无额外planner调用；真实返回前note_node_return("planner")，没有真实委派时仅释放不需要的HANDOFF而不写假摘要。
- [x] **6. 运行GREEN Q：** test_task_closeout_agents.py、test_task_graph_injection.py、test_task_workflow.py；exit0。作者核对固定命令忽略模型替换、预算未重置、soft反馈未进入公开终态分类。

### Task 5: verifier有限读取与原样正式验证

**Files:** Modify graph/nodes.py:275 (verifier_node)、:747 (_execute_read_only_tool)的任务分支；Create test_task_closeout_verifier.py；Extend test_task_result.py只加必要行为断言。

**Interfaces:**

- _task_verifier_tools(state, *, final_reply: bool) -> list[StructuredTool]：首轮三个只读名称，终轮空集合。
- _validate_closeout_verifier_group(calls: list[dict[str, Any]], tools: list[StructuredTool]) -> None：最多3，先整组结构／ID／原工具参数schema检查，后执行；第4项导致phase_limit并零前项操作。未知工具保留原可恢复反馈但仍占本组项数，不扩模型轮次；已知Bash在closing不执行，固定政策失败。
- Consumes VERIFIER用途与前述TaskCloseoutError；既有run_task_verification、ExecutionRequest／审批／receipt API不变。

- [x] **1. 写失败断言。** test_fixed_commands_precede_budget_blocked_verifier：正式命令已取得可信独立回执、verifier_calls==0且共享门挡住invoke；result仍保留正式passed，任务failed／原budgetkind。test_self_test_receipt_cannot_satisfy_formal_checks：相同字符串自测exit0不替代新请求／审批／固定回执。
- [x] **2. 写受限读取断言。** 一组0／1／3项读取后最终JSON，最多2模型调用；4项零执行；同一组前项合法、末项非法参数先整组拒绝；Bash零实际执行且没有自动审批。长行／Grep上游截断不伪报完整，信息不足模型passed=false仍走原失败／retry语义，非法JSON／bool仍内部verifier_invalid。
- [x] **3. 写审批身份断言。** 拒绝／过期／wrong digest／command_hash／缺失或重复receipt维持拒绝；空固定命令仍不能凭模型自述passed=true通过当前actual_checks规则；一条失败一条未运行不统改not_run。
- [x] **4. 运行RED Q：** test_task_closeout_verifier.py及新增result节点；预期当前额外Bash／第三模型轮等行为不满足。
- [x] **5. 实现工具限制。** 不将用途／预测门移到原固定命令循环之前；首invoke仍共享preflight。固定命令不改字节／顺序／次数／超时。整组读取通过后才执行，完整ToolMessage配对；second invoke空tools，合法bool判定后complete_phase(VERIFIER)，真实返回前note_node_return("verifier")，不在model命令空列表等处伪造实际通过。
- [x] **6. 运行GREEN Q：** test_task_closeout_verifier.py、test_task_result.py、tests/test_task_command_policy.py、test_task_workflow.py；exit0。读取数量门不声称字节／token上界，不为verifier新增偷偷截断或开放ResultRead。

### Task 6: 两处条件压缩与新attempt准入

**Files:** Modify graph/nodes.py:416／:445／:785及planner_node的begin_attempt之前；Create test_task_closeout_flow.py的分支／attempt部分。冻结workflow.py／architectures.py不修改。

**Interfaces:**

- _task_compression_purpose(state) -> CloseoutPurpose：从可信流程位置判断planner后PRE_COMPRESS或verifier后POST_COMPRESS；不能只用context_next_node=="verifier"推断所有情况，更不能接受模型metadata。
- _admit_task_retry(context) -> None：先原根因／usage／实际门，再admit_next_attempt；失败不调用begin_attempt；成功调用原begin_attempt之后才pure begin_attempt。
- Consumes原monitor实际context_should_compress输出、压缩调用以及Task1 complete_phase，原route函数不变。

- [x] **1. 写失败断言。** test_both_monitors_consume_distinct_reserved_slots断言一次closing原图两处各最多一次；monitor确认不压缩才release，模型压缩usage缺失／异常保留原失败，不能吞掉后假完成。压缩invalidJSON的现有local fallback保持，不补额外模型调用。
- [x] **2. 写retry断言。** test_retry_8_calls_keeps_previous_attempt：明确负verdict后C=8拒绝，current_attempt不变、上一可信回执保持；C=9且预测足够可进入新attempt，旧审批失效、work保留、usage最大值与首次免预测机会不重置。test_retry_started_then_no_formal_checks断言已开始新attempt却在规划中停止时当前verification_status如实not_run，旧回执仍属于旧attempt；最大attempt／非明确失败均不得retry。
- [x] **3. 运行RED Q：** test_task_closeout_flow.py分支／attempt测试；预期压缩未分配／retry先开始等失败。
- [x] **4. 接入实际分支通知。** graph节点可信代码维护内部位置，monitor计算完才报告该处是否需要压缩；压缩_wrapper invoke绑定对应用途，再按原节点返回／fallback完成用途。verifier后去final和去planner都覆盖，不能据成功verdict提前释放可能压缩槽。
- [x] **5. 接入attempt准入。** C>=9覆盖最低起始路径，token准入预测额外包含一次起始planner估计，不把最低9当整个attempt保证。拒绝不清已有结果；实际begin_attempt失败保留原task_attempt_invalid／审批契约。原frozen verifier_route仍决定去planner与否。
- [x] **6. 运行GREEN Q：** test_task_closeout_flow.py分支测试、test_task_worker_control.py、test_task_result.py、tests/test_graph.py；exit0。图层400000、普通MOKIO_CONTEXT_TOKEN_LIMIT行为和旧图拓扑均保持。

### Task 7: 真实图离线验收、全回归与交接

**Files:** Extend test_task_closeout_flow.py；必要新增既有workflow/result交叉断言；仅同步主项目独立设计／本计划／brief／瓶颈与阶段B交接／进度／根设计的当前记录。

**Interfaces:** Consumes Task1–6全部行为；真实build_complex_workflow与run_projected_workflow、build_task_result（TaskService.result实际调用的构建器）生成结果；不替换为自造图或手工模拟最终状态。脚本模型只控制模型决策和numeric usage，命令都由假执行器产生独立合成回执，worker协议使用内存通道。

- [x] **1. 写整图失败断言。** 合成同版本源码：缺coverage写入拒绝→续读完成→编辑→自测exit1→唯一编辑修复→自测exit0→真实摘要→planner→原固定命令独立审批／回执→verdict。自然核心3调用尾部、采用已开始planner响应的5槽、含两次压缩7槽分别总12／13／15次；5／7槽包含先于nested修复开始的已采用planner响应，不再加一次Todo凑数。断言实际调用／用途、shared计数、patch结果和固定检查。
- [x] **2. 写失败矩阵。** 摘要前挡／planner前挡／正式命令后verifier前挡／最后压缩挡，usage缺失发生各阶段，巨大参数／diff与最近失败仍完整，政策失败／工具拒绝／provider／cleanup分别真实保留；public输出中不存在原prompt／源码／工具正文／provider文本，snapshot仍12字段。Scripted model的触碰记录必须0。对binding／用途／kind伪造和重复调用号，assert零越权／零额外入账。
- [x] **3. 写兼容断言。** 普通CLI/TUI和入口聊天不受配额；1调用／1000token的TaskSpec仍可创建，尝试修复明确准入失败，不自动加预算；长行／重复读取／结果库淘汰／上游丢尾仍按当前真实完整性；没有CodeAgent委派的planner不生成虚假交接或修改。新增这些针对具体触发的断言，不镜像实现。
- [x] **4. 运行RED／必要修复／GREEN Q：** test_task_closeout_flow.py及上述新增交叉节点；RED只允许本项新增交叉缺口，修复仅在本计划非冻结落点，参数／权限或契约需扩大则先修订计划，不能扩大预算消除失败。
- [x] **5. 运行相关整组Q：** 五个新增test_task_closeout_*.py，加test_task_context.py、test_task_context_flow.py、test_task_context_calibration.py、test_task_result_windows.py、test_task_provider_context.py、test_task_graph_injection.py、test_task_workflow.py、test_task_result.py、test_task_scope.py、test_task_events.py、test_task_worker_control.py、tests/test_task_command_policy.py、tests/test_graph.py。预期exit0、无意外skip、禁止触碰0；以实测数字报告。
- [x] **6. 运行全项目Q：** tests -m "not docker"；新独立basetemp，exit0。报告真实skip原因／位置和Docker deselected，不把历史894 passed／3 skipped／35 deselected预填为本轮结果。
- [x] **7. 运行Ruff。** 指定Python -m ruff check --no-cache src tests，exit0；两树git --no-optional-locks -c core.fsmonitor=false diff --check，exit0（安全目录仅命令级明确指定，不改Git配置）。有限秘密格式扫描只列明确修改／新增目标及新增行，命中只输出类别／行号；不读取.env或无关ignored资产。
- [x] **8. 核对保护证据。** 执行开始新取冻结10源码＋Rich／比较7报告＋boltons诊断4资产的21份SHA256逐项比较；四仓status／HEAD／本地heads-remotes新查，来源／冻结证据不变，未fetch。无未经记录产品改动；实际输出足以核对原dirty保留，不清理或提交。
- [x] **9. 完成作者自审／交接。** 覆盖设计§1–9、五项Review Focus、接口类型／名称一致性、数值／迭代边界、根因／回执／公开原文边界。所有Major／Important先有失败断言再修正，必要修复后重新跑相关及全门；无变化不重复扩大测试。不派子agent或宣称独立审阅。记录实际新验收、skip、未解决token／质量／时间边界、真实额度／恢复授权，更新复用本计划勾选；不提交、push或应用来源补丁。

## 完成门与实施时的停点

只有7项的产品／离线交付全部真实通过，才能称此收尾策略离线实施完成；否则保留完成项与实际失败位置，不把“已写计划”称实现完成。阶段验收在本会话作者自审，用户禁止子agent，不能替换成独立审阅。

遇到需要改冻结文件、提升总预算／输出、公开原文日志、扩大verifier命令、跳过planner或把自测当正式验证的要求，停止依赖步骤并交具体修订供用户审阅。合法输入基线门、verifier长行、预测不准、provider／审批／超时／cleanup仍是明确边界，不能用离线结果保证真实成功。

本次最终状态：Task1–7授权的离线产品交付已完成，勾选对应真实实施／验证记录，不包括provider／Docker／真实试点或Git发布。旧中间失败／草案轮无实验状态保留在交接历史节及ledger；最终实测如下。

## 最终实施与验收记录（2026-10-04）

用户明确“计划ok的，现在开始逐项实施吧，注意不要调用子agent来实施”后，在已有阶段B工作树本会话直接完成七项授权的产品／离线测试计划。没有派发或采用子agent实现／审阅；这是作者自审，不称独立审阅。原dirty／未跟踪内容保留，没有提交或新建工作树。

已落地：core/task_closeout.py只管理数值配额；摘要1、planner2、verifier2及前后条件压缩各1，共最多7槽。1.25整数向上取整估计只决定何时结束repair；首次实际repair只有一次免预测机会，原共享预算／输出／迭代门不变。可信用途、唯一实际入账及决策沿现有context锁；CLOSING不能借槽或重新修复。CodeAgent交接为空工具真实绑定，完整锚点／基线门／最近完整组及原ID保持；空摘要或非法工具摘要明确失败。planner新委派在服务／binding之前检查，合法后续拒绝仅本地closeout_requested；采用nested委派前已开始的planner调用号，不重复计总账。verifier首轮最多3项FileRead／Grep／NotepadRead整组先校验、末轮无工具；正式固定命令仍原样逐项独立审批／回执并先于判定模型，模型额外Bash不执行。两处压缩按可信返回位置计槽，新attempt最低9调用且含起始planner预测，门失败不begin_attempt、不抹旧回执。公开仅新增固定task_closeout_incomplete，内部reason及原文不公开，usage仍12字段。

真实图合成路径覆盖缺coverage写入拒绝→完整续读→写入→自测exit1→唯一编辑修复→自测exit0→交接→planner→独立正式命令→verdict；自然三调用尾部总12次，采用既有planner响应的五槽路径总13次，含两次压缩七槽路径总15次。五／七槽包含已开始的第一planner响应，不能误写为自测后新增5／7次或为了计数补无意义调用。五个收尾阶段的缺usage与下一调用硬门均有整图断言；正式未运行仍not_run，正式命令已过而模型被挡保留passed但任务failed，真实开始attempt2后当前not_run且attempt1回执保留。结果用现有build_task_result（TaskService.result实际调用的构建器）汇总，计划中的TaskResultService名称已澄清，不新增替代服务。

各阶段先运行预期RED再实现；详细失败／夹具纠正保留在主项目.superpowers/sdd/2026-10-04-mokioclaw-task-closeout-reserve/progress.md。作者交叉自审发现投影异常可能留下错误局部终态，先失败断言后修正：budget／最终投影失败标FAILED，最终投影成功后才FINISHED。另完成锁一致性整理和非整除ceil、1.0／1.5独立手算oracle补测；这些补测在策略实现后加入，不冒称各自RED。原小预算安全夹具改为足以触达原断言的合成预算；小预算拒绝另测，真实预算不提高。内存通道夹具恢复顺序曾使旧回环测试失败，已纠正；失败记录不倒改为通过。

最终指定Python、显式PYTHONPATH=src、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider、每次仓库外独立basetemp：相关18文件381 passed、0 failed、34.32秒、exit0，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-closeout-a50ab3126f32418e8eff43c1a7a6157a；全项目tests -m "not docker"为977 passed、3 skipped、35 deselected、175.03秒、exit0，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-closeout-c85ffda58d7e456d964b3a85b3e8375c。skip为test_catalog.py:76及test_grader.py:204／219的symlink创建不可用，35项Docker未运行；两组各1条既有Starlette/httpx弃用警告。Ruff --no-cache src tests exit0。此前361／376／972是补测或锁整理前中间记录，291／894是上一轮内部上下文历史结果，均不替代本次最终验收。

新增合成实验封锁provider构造／dotenv、socket与HTTP、Docker入口、真实执行器及命令，意外触碰sticky审计为0；另有一个专门验证“吞掉禁止钩子异常仍失败”的预期负样本。正式命令字符串只是精确身份数据，均由假执行器返回独立合成回执；旧全项目回归中已有的本地Git／回环夹具按原边界运行，不称全项目每条测试都无网络／无子进程。没有provider／Docker／真实Agent试点、.env秘密值读取、用户temp.py执行、旧Agent补丁整理／应用、来源或冻结证据写回、预算提高、提交／push／fetch／远端变更。

产品验收后重取21份SHA256（冻结tools8＋图2、Rich／Rich–Click报告7、boltons诊断4）逐项与本轮起始相同。四仓新查HEAD／全部本地heads-remotes不变：main4134081c0a8fc4786aa28b1e33fe060d69ddcfd5，阶段B033fedbc48b428a221289f227a999c1beed0c5b4，旧来源4ca74f958301228cb48cb1e9c7d15463fa1d8e74，boltons干净detached967864f89791509f9eb36b22b4579d36b72a6df2；两个来源status逐字保持。Git用户级ignore不可读提示仍在，未改配置。最终文档格式／有限凭据格式核验另见本节末尾补记，不宣称完整秘密审计。

边界仍在：预测可能过早收尾或末次越界，合法大锚点仍可拒绝，verifier三项读取不构成字节／token上界，2轮或摘要可能信息不足；时间、审批、provider、cleanup及POSIX跨进程CAS仍未保证。离线结果不证明真实模型遵守协议、真实费用下降或维护成功率。boltons余0、Task10第五批余2保留与连续两次未正式完成后的停止门保持，旧49485不是在线保证。七项离线交付完成后，下一步只审阅本地差异／记录；真实校准／恢复及每个prepared启动、provider／Docker、来源补丁应用、提交／push仍须分别授权，不自动使用余次。

最终文档补记：24个明确源码／测试／文档／ledger目标全文的有限私钥／凭据格式、冲突标记、行尾空白扫描0命中、缺文件0；两树diff --check均exit0，主项目仅既有real_test.md CRLF提示。计划45项步骤已勾选，未勾选列表步骤0。此为有限格式核验，不宣称完整秘密检测；未改.gitignore／real_test.md、冻结文件或来源。
