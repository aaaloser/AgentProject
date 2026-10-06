# MokioClaw 私有校准观测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已选择本会话直接实施并禁止子agent，覆盖技能中的委派／独立代理审阅建议；不提交或push。
> 日期：2026-10-04（Asia/Shanghai）。状态：用户“可以的，开始吧”批准本六项离线计划；六项32步骤已实施并完成本轮离线回归，待用户验收。真实工作台／新额度／容器检查／prepared运行仍未授权。

**Goal:** 为一个明确绑定的校准Task提供可对账的逐次数值记录与仅本机内存的实际交接查看／评分，先完成无provider离线验收。

**Architecture:** 可信任务包装器只采集原计数点和政策状态，独立私有通道把白名单数值送到父进程独占文件，把已接受的CodeAgent交接送到单槽内存。Windows原生查看窗口只显示绑定Task并提交枚举评分，公开Task API、原命令IPC、TaskSpec和原预算政策保持；默认没有诊断能力。

**Tech Stack:** 指定Python、pytest、Ruff；标准库dataclasses／JSON／threading／multiprocessing.connection的AF_PIPE认证通道／惰性加载tkinter；不新增依赖，不用pickle传输业务数据、不接LangChain通用trace。

**Spec:** [已确认的真实校准设计](../specs/2026-10-04-mokioclaw-real-calibration-design.md)，重点§4–6；§3、7–9是后续真实运行合同，不由本离线实施执行。

## Global Constraints

- 产品实施只在 C:/Users/lyf/.codex/worktrees/mokioclaw-stage-b/MokioAgent；主项目仅保留计划／状态文档。实施前遵守AGENTS，完整读两树根SKILL指定设计及本spec，实时核对四Git目录；不以HEAD033fedb代表dirty实现。
- 项目修改仅apply_patch；既有修改／未跟踪内容保留。冻结src/mokioclaw/tools/*.py、graph/architectures.py、graph/workflow.py，以及旧来源／证据／Agent补丁，不改不清理。
- 默认关闭；普通CLI/TUI、TaskSpec、公开事件／API及原命令请求／审批／scope拒绝／正式验证协议保持。
- 原候选总门150000累计已报告token／20启动调用／3072输出／1 attempt／1200秒保持；内部96／72／48KiB及七槽／1.25政策不变。有效0保持，缺usage停止，末次越界与下一调用门保持。
- 每Task逐次记录≤512条、每条规范JSON正文≤4096字节；只允许固定结构／数值／枚举／可信不透明身份。UTF-8换行额外1字节。超限、IO或通道故障标为观测无效，不变成provider错误，不掩盖原根因，不自动取消／审批／重试。
- 交接正文仅内存，最多最近一份、≤65536 UTF-8字节；最多24个交接索引／评分；超限不可完整检查，替换未审阅仍unreviewed。关闭／退出清除，确认Task清理后最多600秒；cleanup_failed立即清除正文，质量保持未测。
- 不落原始prompt／源码／工具参数／cursor／provider响应或异常文字／endpoint／headers／凭据；不输出到stdout、日志、checkpoint、trace、公开API、浏览器存储或截图。首轮不增加请求字节／费用推算列。
- 新测试只用合成任务、假模型、假命令／容器、内存IPC和假UI；运行前封锁provider构造／dotenv、实际网络、真实子进程／命令、Docker、实际AF_PIPE和Tk窗口，触碰即sticky审计失败，即使异常被吞掉。
- 本计划不创建真实校准根，不启动工作台或窗口、provider、Docker、真实Agent或容器检查；不读.env秘密值、不执行temp.py或旧audit脚本、不fetch／提交／push／改远端。
- boltons余0、Task10第五批已用3／余2保留和连续两次未正式完成停止门保持。实现验收、真实恢复／新额度／额外容器检查与每prepared启动各自授权；用户确认本计划只授权后续离线实施。

## Review Focus

1. 取消／崩溃发生在started和usage之间：不能补0，未知调用仍计启动；任务2、6断言未配对记录和对账未通过。
2. nested planner响应先于委派、用途最初为null：采用只关联原call_no，不双计账；任务2、6断言只一次started／usage。
3. 控制字符／emoji使IPC的JSON字节膨胀：65536字节正文仍能完整传递，超限不截断冒充通过；任务3、4覆盖六倍转义和边界。
4. 替换交接后提交旧窗口评分、Task／attempt切换或重放认证：拒绝陈旧输入且不泄露其他正文；任务3–5覆盖身份／序列／版本。
5. 磁盘满／队列堵塞／viewer退出与provider故障同时发生：观测无效且正文释放，原任务根因与计数保持；任务4–6验证故障优先级、无自动cancel及无敏感错误文本。

## 文件与接口地图

以下相对路径均在阶段B工作树；源码项统一前缀src/mokioclaw/，测试项按tests/原路径。新增文件有精确白名单需求时只增加对应一项，不批量解除忽略。

| 落点 | 职责 |
| --- | --- |
| 新 core/task_observation.py | 数值契约、schema校验、事件序号、usage正规化和对账，纯逻辑 |
| 改 core/agent.py、core/task_closeout.py | 原invoke计数点接线；政策只读快照／决定通知，默认None |
| 新 dashboard/task_handoff_observation.py | 最近交接内存槽、24项索引和五维评分，不依赖文件／provider／IPC |
| 新 dashboard/task_diagnostic_ipc.py | 私有认证AF_PIPE、JSON帧校验、后台有限队列，传输与命令通道分离 |
| 新 dashboard/task_diagnostics.py | 父进程绑定／生命周期／独占数值文件／只读终态核对，组合上述模块 |
| 新 dashboard/task_diagnostic_viewer.py | 惰性Tk查看器、无provider子进程环境、纯文本及枚举评分 |
| 改 dashboard/task_worker.py、task_service.py、launcher.py、cli/app.py | 显式启用、可信bootstrap和实际交接取样；没有新HTTP原文路由 |
| 新 tests/dashboard/task_observation_fakes.py | sticky保护、假时钟／通道／sink／UI／进程 |
| 新 tests/dashboard/test_task_observation.py、test_task_observation_context.py、test_task_handoff_observation.py、test_task_diagnostic_ipc.py、test_task_diagnostics.py、test_task_diagnostic_viewer.py、test_task_observation_flow.py | 六项验收及实际任务图的无provider接线 |
| 改 tests/dashboard/test_task_launcher.py、tests/test_cli_smoke.py | 默认兼容／启用参数的定向回归；不整体重构既有测试 |

共享类型由拥有模块定义，跨模块只引用，不另造相近名字：

- core/task_observation.py：`ObservationKind`、`ObservationGate`、`ObservationReason`、`ObservationRecord`（冻结dataclass）、`UsageNumbers`、`LedgerNumbers`、`ObservationSink` Protocol（`emit(record: ObservationRecord) -> bool`）。
- core/task_closeout.py：`CloseoutSnapshot`、`CloseoutNotice`（冻结dataclass）；notice为固定kind、purpose或null、既有call_no或null、C／T／iterations或null、reasons元组、snapshot。不能含messages／异常对象。
- task_handoff_observation.py：`HandoffIdentity(task_id: str, attempt_id: int, ordinal: int)`、`HandoffView`、`HandoffScores`；评分恰为modification／self_test／formal_boundary／remaining_information／downstream五键，值限pass／fail／unreviewed／not_applicable。
- task_diagnostic_ipc.py：`DiagnosticBootstrap`（pipe_name: str、authkey: bytes、role: Literal["worker", "viewer"]、task_id: str | None、instance_id: str | None、attempt_id: int | None）；worker必须有完整身份，viewer未绑定前三个身份均null且不能取正文。`ByteConnection` Protocol（send_bytes／recv_bytes／poll／close）、`WorkerDiagnosticClient`。bootstrap不进入TaskSpec、公开事件或数值日志。
- task_diagnostics.py：`CalibrationObservationManager`；task_diagnostic_viewer.py：`ViewerLaunch`（只在内存持有子进程身份／连接）。

规范ObservationRecord精确字段：schema_version=1、task_id、attempt_id、event_sequence、call_no、stage、purpose、kind、utc_time、elapsed_ms、status、gate、reasons、total_tokens、input_tokens、output_tokens、split_status、before、after、policy。before／after为calls_used、reported_tokens、calls_left、tokens_left四整数；tokens_left允许末次越界负数，其余非负。policy为mode、E_repair、R_calls、R_tokens、iterations_left及五个收尾purpose剩余槽，未知iterations=null。无意义字段为null；拒绝／政策事件的usage为null，不能冒充0调用。stage使用现有六阶段，政策源没有阶段时null；目的使用现有六个CloseoutPurpose值，普通planner允许null。

kind固定invoke_started／invoke_finished／invoke_failed／invoke_refused／policy_decision／phase_released／adopt_existing_call；status固定started／valid_usage／usage_unavailable／provider_failed／refused／observed。gate固定known_failure／usage／total_calls／total_tokens／context／phase／delegation／attempt或null；reasons仅calls／tokens／iterations。provider_failed是观察类别，实际细分根因从已有可信Task结果读取，不保留异常文本。utc_time由注入可信时钟产生固定UTC格式；整数排除bool，拒绝任意对象转str／默认JSON编码。

## 统一测试运行方式（本轮已按此方式实施）

每一RED或GREEN均在阶段B根使用以下前置，再运行对应表内argv；每次生成新的Git库外basetemp，不复用旧测试数字：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$observeTestTmp = Join-Path ([IO.Path]::GetTempPath()) ('mokioclaw-observe-' + [guid]::NewGuid().ToString('N'))
& 'D:/envs/codeagent/Scripts/python.exe' -m pytest <本任务测试文件> -q --tb=short -p no:cacheprovider --basetemp=$observeTestTmp
```

文件选择：任务1=test_task_observation.py；2=test_task_observation_context.py；3=test_task_handoff_observation.py；4=test_task_diagnostic_ipc.py及test_task_diagnostics.py；5=test_task_diagnostic_viewer.py／test_task_launcher.py／tests/test_cli_smoke.py；6=test_task_observation_flow.py，除tests/test_cli_smoke.py外均在tests/dashboard/。新接口用测试函数内惰性导入，使缺接口是明确测试失败，不是收集错误。RED预期新接口缺失或指定行为断言失败，不能把依赖、边界触碰或收集错误当成所需RED；GREEN须exit0、sticky hits=0。步骤进度和实测写入本计划末尾，不提交。

### Task 1：纯数值契约与离线保护

**Files:** 新core/task_observation.py、tests/dashboard/task_observation_fakes.py、tests/dashboard/test_task_observation.py。

**Interfaces:**
- `normalize_usage(metadata: object) -> UsageNumbers`：total只接受非负int非bool；input／output均合法且和等于total才保留，否则二者null／split_status=unavailable。total非法为null／usage_unavailable。
- `encode_record(record: ObservationRecord) -> bytes`：固定键规范JSON（UTF-8、sort_keys、紧凑分隔、allow_nan=False），≤4096字节，否则固定安全错误。
- `TaskObservation(task_id: str, sink: ObservationSink, *, utc_clock: Callable[[], datetime], monotonic_clock: Callable[[], float])`；`emit(record: ObservationRecord) -> bool`只分配event_sequence并验证，最多512；`invalidate() -> None`固定无效状态。调用号来自原provider_calls，不自增另一个账本。
- `reconcile(records: Sequence[ObservationRecord], final_usage: Mapping[str, int]) -> ObservationReconciliation`（本模块冻结dataclass：valid、started_calls、unknown_calls、固定reason枚举元组）。
- `offline_observation_guard(monkeypatch)`提供sticky hits；复用既有offline_closeout_guard并额外封锁实际AF_PIPE／Tk／进程入口。

- [x] **Step 1: 写test_usage_zero_invalid_split、test_record_strict_schema_and_caps、test_unpaired_start_unknown、test_swallowed_guard_still_fails。** 断言0有效，True／-1／缺失无效，split不一致不补算；任意额外键／哨兵／NaN／巨大身份拒绝，512允许、513无效；started无finished为unknown且不补0；吞掉禁止钩子异常仍触发sticky失败。
- [x] **Step 2: 用统一方式跑任务1 RED。** 记录指定断言与退出码；其他失败先解决，不推进。
- [x] **Step 3: 实现本任务接口。** 禁止provider／文件／网络依赖；sink返回False或抛错只invalidate，不捕获异常str。任务1所有测试在保护内，负样本由外层显式断言保护失败。
- [x] **Step 4: 用统一方式跑任务1 GREEN。** 对账覆盖六阶段求和／重复call_no／乱序或缺序／重复finished／有效0／usage未知；invalid不能输出pass。test_failed_call_is_paired_but_usage_unknown断言明确invoke_failed可配对started并保留原启动次数、未知用量不补0；完整观察provider异常与实际任务失败并存。相反，缺finished／failed或响应total非法不能满足逐次有效用量门。
- [x] **Step 5: 作者检查契约并更新本计划实测。** 数值记录中加入每类敏感合成哨兵，编码结果不含哨兵，拒绝信息只含固定码；本任务不创建真实诊断文件。

### Task 2：可信调用与政策接线，保持原账本

**Files:** 改core/agent.py、core/task_closeout.py；新tests/dashboard/test_task_observation_context.py。

**Interfaces:**
- TaskRunContext.__init__／from_settings／for_fake_model仅增加keyword `observation: TaskObservation | None = None`，旧参数保留；bind_tools／for_purpose共享同一context／observer。
- `TaskCloseout.snapshot(*, iterations_left: int | None = None) -> CloseoutSnapshot`返回原状态副本，E_repair=现有estimate(REPAIR)、R_calls／R_tokens=现有剩余预测、各槽原值，不读写private变量外的另一个预测器。
- TaskCloseout.__init__增加keyword `observer: Callable[[CloseoutNotice], None] | None = None`；现有decide_repair／admit_delegation／claim_invoke／complete_phase／adopt_planner_response／admit_next_attempt产生可信notice。不改原返回／调用次数／冷启动或公式。
- TaskRunContext用内部`_observe_closeout(notice: CloseoutNotice) -> None`补充锁内总账与当前attempt；_TaskModel.invoke直接构造有限数值记录，观察失败不改变原异常／返回。

- [x] **Step 1: 写test_observer_off_equivalent、test_invoke_lifecycle_usage_and_refusal、test_all_switch_reasons、test_adopt_original_planner_once。** 开关两套合成脚本比较同一response、原计数／槽／root；正常／0／异常／缺usage／末次越界各分开，下一门拒绝无started；C／T／iterations同时触发全部reasons；首次repair保留冷启动实际不触发tokens原因；nested原planner保持purpose=null且adopt只引用已有号。
- [x] **Step 2: 跑任务2 RED。** 包括实际bind_tools和for_purpose链路；不得只测模拟observer自身。
- [x] **Step 3: 实现closeout快照与notice。** 原决定条件在原决定位置读取一次，先通知所依据的快照／原因、再报告真实结果；重复adopt或phase release不制造额外调用／重复政策变化。观察器抛错由安全适配器吞掉并标无效，TaskCloseout仍是纯政策代码。
- [x] **Step 4: 实现_TaskModel与TaskRunContext接线。** 原调用计数增加后、underlying.invoke前记started；成功按原一次usage入账后记finished；非法total记usage_unavailable再沿原根因；异常记failed、无usage。拒绝贴原可信gate，不加第二次budget preflight／claim。
- [x] **Step 5: 跑任务2 GREEN并作者复核。** 补test_cancel_after_started、test_existing_root_wins_observer_failure和两compressor用途／未触发phase_released；取消／进程消失后不补finished，全部开关等价数据保持，报告观察开销而不宣称零开销。

### Task 3：实际交接内存槽与枚举评分

**Files:** 新dashboard/task_handoff_observation.py、tests/dashboard/test_task_handoff_observation.py；改task_worker.py的run_projected_workflow。

**Interfaces:**
- `HandoffMemory(task_id: str)`；`accept(attempt_id: int, summary: str) -> HandoffIdentity | None`、`view(identity: HandoffIdentity) -> HandoffView | None`、`score(identity: HandoffIdentity, scores: HandoffScores) -> bool`、`clear() -> None`。
- HandoffView仅在内存含identity／summary／inspectable；索引只含identity、字节数、固定status（pending／reviewed／unreviewed／oversize／absent）、五维评分。不提供整个历史正文接口。
- `run_projected_workflow(..., handoff_observer: Callable[[int, str], None] | None = None)`新增keyword；只取原raw自定义事件type=handoff_result、from=codeAgent、to=planner的字符串result，使用可信context.current_attempt，不使用event自报Task／attempt。

- [x] **Step 1: 写test_capture_accepted_natural_and_forced、test_replace_and_stale_score、test_utf8_boundary_and_24_indexes、test_public_projection_has_no_summary。** 自然交接与HANDOFF均只收到实际result一次；searchAgent／其他event忽略；替换旧slot、旧评分拒绝；65536完整、65537无正文且不可评分为pass，emoji按UTF-8；25份触发观测无效不扩容；公开投影仍仅原字段。
- [x] **Step 2: 跑任务3 RED。** 用合成实际流事件和现有run_projected_workflow，不接真实旧私有资产。
- [x] **Step 3: 实现HandoffMemory接口。** 评分只允许当前可完整查看的identity；评分键／值严格校验，不接自由文字；未查看被替换保持unreviewed，已评分只留数值，clear销毁当前正文引用。
- [x] **Step 4: 接线run_projected_workflow的可选采集。** 在summarize_agent_event之前取实际交接；观察失败不覆盖graph异常，不改发送到planner的字符串、不回传人工结果。
- [x] **Step 5: 跑任务3 GREEN并作者复核。** 控制字符、伪命令和URL按纯文本保持；clear／异常／非字符串事件无stdout或错误正文，未看／超限不是质量通过。

### Task 4：父进程数值文件、认证IPC与故障限额

**Files:** 新dashboard/task_diagnostic_ipc.py、task_diagnostics.py及test_task_diagnostic_ipc.py／test_task_diagnostics.py。

**Interfaces:**
- `encode_frame(message: Mapping[str, object], *, role: Literal["worker", "viewer"]) -> bytes`／`decode_frame(data: bytes, *, role: Literal["worker", "viewer"]) -> dict`：业务只send_bytes／recv_bytes(JSON)，从不Connection.send／recv(pickle)。
- `WorkerDiagnosticClient(bootstrap: DiagnosticBootstrap, *, connect: Callable[[DiagnosticBootstrap], ByteConnection])`；`emit(record: ObservationRecord) -> bool`、`accept_handoff(attempt_id: int, summary: str) -> bool`、`close() -> None`。生产connect使用AF_PIPE的32字节随机内存authkey；不同role／worker使用不同key，命名随机且无源码／secret。
- `NumericJournal(root: Path, task_id: str)`；`emit(record: ObservationRecord) -> bool`、`write_scores(identity: HandoffIdentity, scores: HandoffScores) -> bool`、`finalize(final_usage: Mapping[str, int], *, stream_closed: bool, cleanup_confirmed: bool) -> ObservationReconciliation`、`close() -> None`。observations/<validated_task_id>/calls.jsonl、scores.json、status.json新建exclusive，拒绝已有文件／symlink／junction／逃逸路径，不能接受模型给出的路径。calls逐行flush；scores在内存只保留≤24项枚举／索引，当前交接可更新评分，在clear／close前一次输出≤64KiB JSON，无原文；status输出≤4KiB固定schema的身份、序列数、started／unknown数、对账结果、stream_closed／cleanup_confirmed和固定reason，不能伪造结束标记。文件存在而不完整或status缺失时观测不能通过。
- `CalibrationObservationManager(root: Path, *, task_lookup: Callable[[str], TaskRecord], clock: Callable[[], float])`；`bind(task_id: str) -> bool`、`worker_bootstrap(task_id: str) -> DiagnosticBootstrap | None`、`poll_terminal() -> None`、`close() -> None`。bind只接受当前root/tasks下prepared新Task，一次选定，开始后不可切换；worker_bootstrap验证running record的instance／attempt与已绑定身份，不给其他Task或旧Task诊断通道。

- [x] **Step 1: 写test_role_auth_binding_and_replay、test_json_frames_and_escape_expansion、test_exclusive_numeric_sink、test_observer_io_and_backpressure。** wrong key／role／Task／instance／attempt拒绝，重放sequence拒绝；worker无bind／score权限，viewer无numeric／summary注入权限；65536个ASCII控制字符六倍转义仍传完整；敏感哨兵只出现在假内存viewer数据，calls／scores／错误／公开事件不含；原命令_MAX_MESSAGE=262144保持。
- [x] **Step 2: 跑任务4 RED。** 临时文件只在该次pytest basetemp内；AF_PIPE／spawn都用注入假对象，sticky真实入口封锁。
- [x] **Step 3: 实现帧与认证适配器。** 私有最大帧409600字节，先限制bytes再JSON严格键／类型／身份验证，重复键拒绝；每连接固定role与Task，不接受任意方法名。摘要数据只有worker→manager→viewer；viewer的bind／score／close是独立本地观测控制，不能回到worker、任务模型或原命令通道。
- [x] **Step 4: 实现父进程journal／manager与有界输送。** worker数值队列最多32条，摘要另一个待送槽且最多一份，不排24份正文；第二份到来而上一份尚未确认送达则观测无效，不静默替换。后台thread输送，不在模型线程做文件／AF_PIPE阻塞；started行父进程立即flush后ACK。ACK超过1秒／队列溢出／写失败则观测无效、停止采样并清除诊断正文，固定醒目标志提示操作者原方式cancel，不自动执行；viewer不可用时父进程仅输出固定安全提示calibration_observation_invalid，无原始exception／正文／认证材料。启动前就绪失败不给第一调用放行。不把ACK缺失补成已落盘；close不无限等待，清理仍依赖原精确worker身份。
- [x] **Step 5: 跑任务4 GREEN并作者复核。** 故障不抛原异常正文；拒绝非法尾帧／未结束流，started未落盘或未配对为未知／观测不完整；512×4096限额始终遵守。score文件至多24索引，每索引只有一份最终有效五维值／不保存原文；两份未送达摘要碰撞、IO失败或status缺失均无效。ACK时延、真实AF_PIPE与磁盘调度未由假通道证明，保留后续现场就绪检查。

### Task 5：显式原生查看器与任务启动／清理接线

**Files:** 新dashboard/task_diagnostic_viewer.py、test_task_diagnostic_viewer.py；改task_worker.py、task_service.py、launcher.py、cli/app.py、既有CLI／launcher定向测试。

**Interfaces:**
- `filtered_viewer_environment(source: Mapping[str, str]) -> dict[str, str]`只保留PATH／SystemRoot／WINDIR／TEMP／TMP／LANG与可信src的PYTHONPATH／PYTHONDONTWRITEBYTECODE=1，不调用filtered_worker_environment，不传任何provider变量或dotenv。
- `launch_viewer(bootstrap: DiagnosticBootstrap, *, spawn: Callable[..., object]) -> ViewerLaunch`：Python -P -B -m mokioclaw.dashboard.task_diagnostic_viewer，认证bootstrap仅stdin，stdout／stderr DEVNULL、可信代码cwd（不是Task work），不把token写argv／URL／磁盘。UI只有Task ID输入／绑定观测、纯文本只读区、五维枚举评分、关闭；无run／cancel／命令／审批／链接执行入口。
- `ViewerController`：`bind(task_id: str) -> bool`、`render(view: HandoffView | None) -> None`、`submit_scores(scores: HandoffScores) -> bool`、`close() -> None`；通过私有viewer role协议调用父进程，本地原文只当前slot，UI clear销毁正文。Tk只在明确入口惰性加载，测试fake widgets。
- CLI dashboard及launch_dashboard新增keyword `calibration_root: Path | None = None`／flag --calibration-root，必须显式--enable-agent且task_root解析后恰为calibration_root/tasks，Windows平台与Tk就绪；无flag路径不创建manager／线程／窗口／文件。
- TaskService新增`configure_calibration(root: Path, *, manager_factory: Callable[..., CalibrationObservationManager] = CalibrationObservationManager) -> CalibrationObservationManager`，在已有TaskService创建后使用其store.get构造manager，随后configure_agent接入回调，避免构造循环；默认不调用该方法。TaskWorkerLauncher增加keyword `diagnostic_bootstrap: Callable[[str], DiagnosticBootstrap | None] | None = None`，activate中的可信start顶层增加可选diagnostic，payload原键保持。_worker_main确认通道ready后才started，_run_real_task将client作为TaskObservation sink及handoff callback；禁止bootstrap泄漏到公开事件／run policy。viewer未绑定时的bootstrap使用任务4定义的null身份，绑定成功后只接父进程确证身份。

- [x] **Step 1: 写test_cli_opt_in_and_default_unchanged、test_viewer_no_credentials_or_controls、test_bind_before_first_invoke、test_cleanup_ttl_and_window_close。** 普通run／TUI／dashboard默认参数保持；错task-root／缺enable／不支持平台／Tk缺失固定安全失败且无provider初始化；绑定prepared后才给selected Task接线，未绑定时校准模式拒绝真实start但不改普通模式。
- [x] **Step 2: 跑任务5 RED。** 用CliRunner／假的launcher、进程、AF_PIPE、Tk，不启动服务／窗口／真实Task或读环境秘密。
- [x] **Step 3: 实现原生viewer与显式入口。** 启动校准窗口先不显示正文；用户输入prepared Task ID并点击绑定，父进程验证成功才显示以后实际交接。不添加HTTP／浏览器原文路由；评分不自动判质量通过，不把人工结果写回Todo／模型。
- [x] **Step 4: 接线父／worker生命周期。** start_agent在controller.start前检查manager已绑定且sink／viewer就绪；activate回调此时record已经running，可绑定instance；worker真实模型前完成诊断ready，私有握手3秒内失败则沿原worker_start_failed清理，不开始模型。manager独立只读轮询TaskStore终态，每≤1秒检查cleanup_confirmed，不调用Docker／finish／cancel；终态确认清理后600秒或窗口关闭即clear。cleanup_failed／viewer退出／TaskService.close立即clear，进程退出无恢复正文能力。
- [x] **Step 5: 跑任务5 GREEN并作者复核。** 599秒仍可审当前正文、600秒清除；stopping而未确认cleanup不能伪报完成，窗口退出立即清除并观测无效；重启没有历史正文／key复用；只关闭自己创建且身份匹配的viewer，不影响worker／原审批。原Task 1200秒计时照常，不暂停或延长。截图／用户复制／OS分页不在应用控制保证内。

### Task 6：实际任务图离线验收与回归交付

**Files:** 新tests/dashboard/test_task_observation_flow.py；必要合成夹具只在task_observation_fakes.py；同步本计划、spec状态、阶段B交接／进度及主项目瓶颈／brief。

**Interfaces:** 消费任务1–5精确接口；复用原实际任务图与ScriptedCloseoutModel／FakeCloseoutExecutor，新增假父／worker／viewer输送，所有外部入口用sticky保护。公开Task输出仍原schema。

- [x] **Step 1: 写test_real_graph_observation_matrix。** 参数化自然结束／预算进入HANDOFF／两处压缩触发及释放／nested采用／正式回执先于verifier／正式passed但模型门被挡／usage非法／有效0／取消／viewer或sink故障。断言唯一started总数=原provider_calls，有效token六阶段求和=最后12字段；未知不补0、拒绝不计调用；交接取真实summary、枚举不回流、原审批／scope拒绝／固定命令不变。
- [x] **Step 2: 跑任务6 RED。** 敏感合成哨兵放prompt、工具参数、正文、异常、摘要；仅允许摘要哨兵在明确绑定的假viewer内存，所有文件／投影／捕获日志／stderr不含。_run_real_task所需ProviderSettings.from_environment用注入的合成settings替身；dotenv、真实settings提取及模型构造仍封锁，fake不得初始化provider或执行固定命令，sticky hits=0。
- [x] **Step 3: 完成缺失接线并跑任务6 GREEN。** 仅修本计划接口／缺陷；若需改政策、提示、冻结文件或scope则停止先改设计审阅。检查默认模式与开启模式实际图的返回／计数／根因等价；不为了观测新增模型／正式命令。
- [x] **Step 4: 跑新观测组及相关原回归。** 使用统一Python／新basetemp；pytest文件argv精确为`tests/dashboard tests/test_cli_smoke.py tests/test_graph.py tests/test_architectures.py tests/test_runtime.py tests/test_tui.py -m "not docker"`（已从实施树目录核对，没有tests/graph或tests/agents目录）。这些既有测试包含原本地Git／回环假服务，不称整组全无子进程／网络；任务5既有CLI／launcher测试同理，新观测实验每条仍全封锁。
- [x] **Step 5: 跑全项目非Docker与Ruff。** 新basetemp，`-m pytest tests -m "not docker" -q --tb=short -p no:cacheprovider --basetemp=$observeTestTmp`；`-m ruff check --no-cache src tests`。报告实际passed／failed／skip原因／deselected／警告／exit／时长／临时目录，Docker不运行，旧381／977不能写成新结果。
- [x] **Step 6: 做保护核验与作者自审。** 两树diff --check、四仓status／HEAD／全部本地heads-remotes、冻结10源码＋既有11证据及7旧Task资产逐项SHA256；有限私钥／凭据／冲突／尾空白扫描只输出文件／行号／类别不显示匹配值；记录本次全部源码／测试hash、指定Python及已安装版本（不安装／联网）。核对spec§4–5每项覆盖，填实际记录，不称独立代理审阅。
- [x] **Step 7: 交付离线实现及下一授权门。** 更新交接／进度／瓶颈，列未验证的真实AF_PIPE／Tk／usage／语义质量／token费用／Docker清理边界。先给用户验收结果；准备请求带原配置的真实工作台启动时再告知。该启动后先无provider就绪核对，真实恢复／新一次额度／最多两次额外容器检查和具体prepared /run仍各自确认，不自动实施真实合同。

## 作者自审与批准范围（以下形成计划时的文字为历史，最新见末节）

已按spec逐节检查：§4.1映射任务1／2／4／6；§4.2映射3／4／5／6；§5默认兼容、泄漏保护、故障及离线门贯穿六项；§6–9真实合同全部保留为下一授权阶段，不遗漏但不在本计划执行。五项Review Focus已各有具体测试；跨模块类型与签名相同，业务传输无pickle，无新增public原文通道，冻结文件无落点。

实现细化选择供本计划一并审阅：Windows AF_PIPE＋标准库Tk、显式--calibration-root与窗口内只绑定prepared身份、32条数值队列／1秒ACK缺口门、私有409600帧（原命令上限不改）、cleanup_failed立即清除。这些均未实施；现场传输／窗口不由假对象测试保证。若Tk不可用则明确阻断，不安装替代包或转成浏览器存储正文。

数值文件需要父进程IO，无法承诺零耗时；后台有界输送避免在invoke持锁时阻塞磁盘／管道，保留真实1200秒计时。观测故障仅固定告警与不完整标记，操作者仍需及时使用原cancel；本计划不承诺故障自动停模。真实性／质量四项结论仍分开，没有完整数据就写未测或失败。

当前六项全部未执行，未开展新离线实验／pytest／Ruff／GUI／网络／provider／Docker。下一步用户审阅本具体计划；批准后保留本会话直接逐项实施、禁止子agent，不再询问执行方式。依据writing-plans的“wait for that review before implementation”，不把校准方向确认当作新增产品接线已经获批。

## 实施实测记录（形成计划时的占位文字，实际结果见下节）

本节当前无产品验收结果。旧381相关／977非Docker仅为已接受上下文／收尾实现的历史证据。计划轮文档及保护检查见阶段B交接§63／技术进度§102；实际执行时记录每项RED／GREEN及最终回归，未执行的步骤保持未勾选。
## 2026-10-04 六项离线实施完成

用户“可以的，开始吧”授权本会话直接执行上述六项；未使用子agent、未提交或push。产品仅阶段B dirty 工作树；主项目只有文档／ledger。历史待审／未执行记录保留，不能用来重复实施或恢复真实运行。

已落地11个本轮源码落点与8个新增测试／夹具文件：纯数值schema／对账；原invoke和政策前后只读通知；最近实际CodeAgent交接单槽／24索引／枚举评分；认证AF_PIPE字节JSON及独占数值journal；显式--calibration-root与prepared绑定；无provider环境的原生查看器；原worker在started之前确认诊断ready、原Task计时／审批／正式回执／cleanup保持。既有CLI／launcher测试无需整体改写，新观测组已覆盖参数分支。没有新TaskSpec／HTTP原文／公开事件字段。

关键限额为512条×4096字节；32条待ACK数值、最多一个待送摘要、65536 UTF8正文、409600私有帧和24索引。started写入／flush后的ACK门含传输写入等待，发送线程旁的独立deadline检测让卡住的写入也标无效；不会阻塞模型线程或自动cancel。超限／故障传播为观测无效，正文清除，原根因保持。bootstrap仅可信内存／stdin，不入数值文件。begin／finish调用号沿原计数点，nested重入结束保留原号；adopt仅引用原planner号，不重复usage。切换既记录依据又记录实际模式，release报告释放后零槽，不改变七槽／1.25／96-72-48KiB政策。

RED／GREEN、夹具纠正及作者自审修正详见主项目.superpowers/sdd/2026-10-04-mokioclaw-private-calibration-observation/progress.md。首轮相关11项失败来自合成Settings注入恢复晚于guard而残留禁止钩子；内部context恢复后定向95 passed／8.80s，再相关698 passed／1 skipped／4 deselected／118.33s、exit0。后补blocked-write测试RED 1 failed／10 passed，加入deadline后IPC／实际flow 30 passed／6.09s；因此相关698是该补测前的通过记录，最终全项目覆盖后补版本。

最终全项目 tests -m "not docker"：1073 passed、3 skipped、35 deselected、0 failed，175.82秒、exit0；basetemp=C:/Users/lyf/AppData/Local/Temp/mokioclaw-observe-ee047d674f1b410cb9ed199d8e029b1e。相关basetemp=C:/Users/lyf/AppData/Local/Temp/mokioclaw-observe-45926f7125d440c38036a4b408426c89。三个skip为catalog:76及grader:204／219的symlink创建不可用；35项Docker没有运行。两组各一条既有Starlette/httpx弃用警告。指定Python3.13.15、显式PYTHONPATH=src、PYTHONDONTWRITEBYTECODE=1、-p no:cacheprovider、每次独立Git库外basetemp；Ruff --no-cache src tests exit0。旧381／977不作为新验证。

本轮新增96项观测测试全部在sticky保护内，禁止provider／dotenv／实际Settings提取／网络／命令／Docker／AF_PIPE／Tk；一个专门验证吞掉禁止钩子仍失败的负样本。所有模型、命令回执、通道、窗口与进程均合成／注入。相关及全项目既有本地Git／回环夹具按原边界运行，不称每个旧回归测试都无子进程或网络。没有provider、Docker、真实GUI／AF_PIPE、真实Task或新校准根；没有.env秘密读取／temp.py／旧audit执行／旧补丁应用／来源或冻结证据写回／预算提高／Git发布。

保护核验：本轮21冻结／诊断资产及7旧Task资产与起始逐项SHA256相同；两来源status、四HEAD和全部本地heads-remotes保持。主项目src／tests未改。本轮352产品／测试hash基线是在任务1及任务2新建四文件后采集，不能冒充实施前348基线；最终361份（主项目及StageB）逐项记录在同目录source-test-hashes.json，比较只出现计划落点。未修改.gitignore／real_test.md、既有未提交和未跟踪内容保留。最终文档格式扫描与diff核验另补交接§64／技术进度§103。

作者自审按requesting-code-review模板单独通读契约、生命周期与实际图；用户禁止代理，未称独立审阅或merge-ready。修正已覆盖nested编号、无效传播、日期／语义／身份及对账、attempt2结束／正文释放、release后状态与阻塞写ACK。未以敏感异常作为错误文本；查阅及认证只在私有role内。尚未判断的行为列明：真实AF_PIPE认证／调度、原生Tk可用性与渲染／关闭时延、实际磁盘／进程调度与ACK开销、OS分页／截图／用户复制、真实逐次usage和交接语义／费用／成功率、真实Docker清理；原因是本轮明确禁止现场启动。窗口跟随父端≤1秒轮询清理，假时钟599／600秒通过不等于现场硬实时保证。

当前无需启动工作台。下一步用户验收本离线实现；拟启动带校准参数的真实工作台前会明确告知，先做无provider就绪核对。真实恢复、新一次boltons额度、最多两次额外无provider容器检查和具体prepared /run仍分别确认。boltons旧余0、Task10第五批余2保留与连续两次未正式完成停止门保持；旧49485不是在线或运行授权。

最终补修及文档核验：超限交接原已拒绝评分，但viewer没有显式提示；RED 1 failed／11 passed后保留无正文的oversize视图并显示不可完整检查，相关四观测组51 passed／5.59s，再跑全项目得到上述1073最终结果。补修前1072／176.53s保留在ledger为中间通过记录，不冒充最终版本。30个明确源码／测试／文档／ledger／hash-manifest／.gitignore目标全文有限私钥／凭据格式、冲突标记及尾空白扫描0真实命中、缺文件0；初扫15处是文件名task-中的sk-子串，纯元数据核对全部为该假命中，补足token边界后0。两树diff --check exit0，main仅既有real_test.md CRLF提示。32步骤已勾选；此为有限格式核验，不是完整秘密审计。最终361份hash已刷新为超限提示补修版本，21及7保护资产和Git引用再次核对保持。
