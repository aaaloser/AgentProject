# MokioClaw 任务 CodeAgent 内部上下文与历史整理设计／测试计划

> 2026-10-04（Asia/Shanghai）；状态：用户已批准输入适用域调整，从任务5接续逐项离线实施。96／72／48 KiB保持；合法但完整锚点超界的TaskSpec明确拒绝。此前基线失败记录保留，不是新的通过证据。
> 适用代码：阶段 B 工作树 `C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent`，HEAD `033fedbc48b428a221289f227a999c1beed0c5b4` 及其既有十一项未提交修改。
> 本文是本轮独立草案，放在主项目供审阅；不将主项目旧阶段 B 设计当作实施树最新授权。当前产品契约仍以实施树 2026-09-28 设计及其获批增补为准。
> 初稿与设计修订均只做只读核对和文档更新；设计修订仅修改本文，之后按确认编写独立实施计划并记录批准状态。未新增／重跑实验、pytest 或 Ruff。本文的测试均为计划，不是已通过结果。
> 执行入口：[具体实施计划](../plans/2026-10-04-mokioclaw-task-codeagent-context.md)。用户已选择本会话逐项离线执行；没有授权 provider／Docker／真实任务或提高总预算。以下初稿／修订记录保留其历史时点，最新停止门与实测见§11。

## 1. 目标与本轮边界

让隔离任务的 CodeAgent 在**每次内部模型调用之前**检查其实际待发送消息与工具 schema，整理较早历史，并使大块正文可显式分窗、续读。保留任务要求、必要状态、最近完整工具组与失败反馈，避免仅凭图层 monitor 推断内部体量。普通 CLI/TUI 的提示、读取默认值、历史、模型调用和返回形状保持原行为。

成功标准是本地输入有界、协议配对有效、正文可恢复读取、真实权限和验证语义保持。不能从正文字符对照或假 usage 推导真实 token、费用、成功率或唯一根因。第一版不增加压缩模型调用，不改变 16 轮工具循环、planner 路由、正式 verifier、attempt 重试、总预算或单次输出设置。

本轮不讨论或设定交接／verifier 保留量。boltons 一次已用完；Task10 第五批已用 3／剩余 2 保留，连续两次未正式完成后的停止讨论状态保持。设计批准、离线实现批准、真实恢复和每个 prepared 任务启动是不同授权阶段。不得消费余次、启动 Docker／provider、执行 temp.py、读取 .env 秘密、改旧补丁／来源／冻结证据、提交或 push。

## 2. 实时核对与依据

下述资料阅读、代码静态观察与首次状态是初稿编写记录。本轮修订重新完整阅读两处根 SKILL 与各自 V1／阶段 B 设计、附件和原草案；另行只读核对四仓 status／HEAD／全部本地 heads/remotes，未 fetch。四仓 HEAD／引用与下表一致；主项目已有本草案未跟踪，阶段 B 仍为原十一项修改。本轮不重新排查真实试点，不把初稿的静态观察或旧探针结果记成新验证。

初稿编写时完整阅读两处根 SKILL、各自完整 V1／阶段 B 设计，再读主项目接续摘要与瓶颈顶部、实施树交接 §51–53／进度 §90–92、私有诊断报告／完整探针／日志／boltons-run1-review.md。随后重新查询四仓 status、HEAD、全部本地 heads/remotes，未 fetch：

| 仓库 | 实时 HEAD／分支 | 开始时状态 |
| --- | --- | --- |
| 主项目 | main／4134081c0a8fc4786aa28b1e33fe060d69ddcfd5 | 四项既有修改、接续摘要未跟踪及原十五个 .pytest_*／.zcodeignore／temp.py |
| 阶段 B | codex/mokioclaw-stage-b／033fedbc48b428a221289f227a999c1beed0c5b4 | 原十一项未提交修改 |
| 原 Task10 来源 | master／4ca74f958301228cb48cb1e9c7d15463fa1d8e74 | 仅原 docs/面试复习手册.md 未跟踪 |
| boltons 来源 | detached／967864f89791509f9eb36b22b4579d36b72a6df2 | 干净 |

主项目与实施树本地 origin/main、origin/HEAD 均为 4134081；原来源 origin/master=4ca74f9、origin/project=0c9ff185ba129ac020bf6dfd11f5817ade2d25a4、origin/theory=ff6d88b732784b178af3128f21c1c9e0ab270515。boltons master／origin/master／origin/HEAD=4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d，另十三条远端跟踪引用也实际列出核对；不代表远端服务器实时状态。Git 提示用户级全局 ignore 文件不可读，仓库命令成功，已显示的仓库状态与预期一致；未改变用户配置。

历史依据：12 项无 provider 探针及 Ruff 是上一轮结果。CodeAgent 内部 messages 追加重送；图层 monitor 在 planner 返回后运行，委派只返回 summary/todos；任务图层阈值固定 400000，MOKIO_CONTEXT_TOKEN_LIMIT 不影响它。完整一次／100 行窗口／重复五次的累计正文为 279063／96818／697257 字符，图层均估 830；65.3% 仅是正文字符下降。100000 字符单行未受 2000 行门约束。真实逐次 token 和具体重复读取轨迹未知。

初稿静态确认：`agents/code_agent.py` 同时累积 messages、produced_messages、tool_events；工具参数不在旧正文指标内。`dashboard/task_tools.py` 的 read 用行数切片，write/edit 的 diff 已静默裁成 4000 字符。`_TaskModel.invoke` 是共享累计预算门；worker 会在正常或异常结束时发布已有 budget_usage 快照。正式固定命令在 verifier 模型之前执行；不能单靠 verifier_calls=0 判定 not_run。

## 3. 方案比较与推荐

| 方案 | 好处 | 代价／不足 | 结论 |
| --- | --- | --- | --- |
| 本地确定性整理：固定锚点＋状态胶囊＋最近完整组＋正文分页 | 不新增 provider 调用；配对、上限、截断与续读可在离线精确验收 | 不能理解旧推理；信息不足要重读，可能增加后续调用；必须明确停止条件 | 推荐第一版 |
| 内部调用模型生成语义摘要 | 可能保留跨文件推理与意图 | 摘要也耗调用／token，可能丢掉关键失败或源码；仍需本地上限、续读与摘要失真验证 | 暂缓 |
| 仅减少读取行数／保留最后 N 条消息／调低图层阈值 | 改动较少 | 长行、巨大参数、多工具回复、tool_call_id 孤儿、内部监控盲区仍可能存在 | 不采用 |

推荐方案不把“减少输入”直接当作“省费用”。所有原文省略均由可信本地代码产生标记；模型不能自行把它解释成读完、修复完成或正式验证通过。

## 4. task-only 接入与限额

新增 `dashboard/task_context.py`：不可变 `TaskContextPolicy`、消息分组／计量／整理、确定性状态胶囊。新增 `dashboard/task_result_windows.py`：内存结果窗口及续读，不落盘。TaskRunContext 持有固定策略与任务工具共享的结果窗口服务；每次 CodeAgent 委派创建独立历史，attempt 变化清空旧句柄。runtime.task_filesystem 标记任务模式；标记与 task_context 不一致时拒绝，不退回普通工具或模型。

`run_code_agent` 在内部循环调用 `prepare_request(...)`，将整理后的列表实际替换当前消息，而非只测量一个影子列表。每轮先调用共享预算的只读预检，已有 usage_unavailable／预算达门优先于新的上下文错误；不提前递增或预扣计数。`_TaskModel` 在锁内再次按原顺序检查 usage／累计预算，再在 stage=code_agent 检查输入，防止入口绕过整理和检查间状态变化；bind_tools 传递规范 schema 计量数据。全部门通过后才递增 provider_calls／阶段计数并 underlying.invoke。其他阶段和普通模型不应用内部输入策略。

第一版采用**规范序列化输入字节限额**，不伪称精确 token 限额。`B = UTF-8 bytes(canonical JSON(messages + bound tool schemas + explicit invocation options)) + 4096`。规范化计入角色、content 字符串／块、全部 tool_calls 参数、ID、name、额外会发给模型的字段；不能用 str(message) 或只加 content。未知且无法可靠计量的块类型 fail closed。JSON 统一 ensure_ascii=False、固定键排序与紧凑分隔；每个实际请求都计量，不省略重复内容。4096 是本地封装裕量，不证明 SDK 最终报文的上界，也不保证任何 provider 的 tokenizer 比例。

| 提议的固定值 | 数值 | 依据与处理 |
| --- | ---: | --- |
| 内部输入硬限额 B_hard | 96 KiB（98304） | 是否容纳锚点、常见两组和必要失败须按下述基线约束验证；越界绝不 invoke |
| 整理触发 B_trigger | 72 KiB（73728） | 工程增长余量，须证明基线加最小两组低于此门，不能假定天然够用 |
| 整理目标 B_target | 48 KiB（49152） | 基线必须低于此门；必要组超目标但不超硬限额时允许发送 |
| 状态胶囊 | 8 KiB | 不保留源码正文／自由推理；必需字段无法装下时停止，不裁任务要求 |
| MAX_TOOL_MESSAGE_JSON | 16 KiB | 单次 ToolMessage 完整 JSON，含转义、路径、ID、状态与续读字段，不能只限制正文长度 |
| MAX_TOOL_GROUP_VISIBLE_RESULT | 32 KiB（32768） | 同一 AI 的全部 ToolMessage 首屏规范 JSON 字节总和上限；独立于单条门，不按调用数乘 16 KiB；按 §6.3 分配 |
| 单页正文 | 至多 8 KiB UTF-8 | 长行、CJK、emoji 同样有界；最终 JSON 门更紧时进一步缩页 |
| FileRead 默认／最大行数 | 100／2000 | 默认先定位，显式请求更多仍受字节门约束；100 来自已测窗口形态，未证明足以完成任务 |
| 内存结果库 | 32 MiB／最多 32 结果 | FIFO 淘汰旧可续读结果，生命周期限当前委派／attempt；不新增磁盘原文资产 |

定义 `B_base`：没有任何历史 AI→Tool 组时，当前一次 CodeAgent 请求中不可删除的 system、完整 task/planner 指令、acceptance criteria、fixed verification commands、最小状态胶囊、实际 bound tool schemas 和 invocation options 的规范序列化输入大小。使用与 B 相同的计量器及一次 4096 封装裕量，不用空 schema 或省略任务锚点的替身。胶囊最小形态仍含必要 task／attempt／todos／整理状态，不能为了压低基线删除必需字段。

固定阈值的可行性在准许运行的输入域内必须同时满足：

1. `B_base < B_target`。
2. `B_base + 最近两组最小合法工具组 < B_trigger`。
3. `B_base + 最近两组常见工具组 + 必要失败反馈 < B_hard`。

各组大小是加入同一完整请求后的规范字节增量，包含 AI 原参数、全部 ToolMessage、ID／配对和 JSON 结构开销；封装裕量不重复相加。失败组已在最近两组内时不重复计数，仍需覆盖失败在两组之外的三组场景。“最小合法组”由已绑定真实 schema 对应的合成合法调用及最小必要反馈构成；“常见组”用预先列明的合成 100 行读取、局部编辑与 diff、待办、小命令反馈及多小结果组合测量，记录夹具尺寸，不据此宣称真实模型调用分布。T1 同时测各实际工具绑定组合、任务锚点允许范围和胶囊增长到 8 KiB 的变体；不能仅以一个很短任务通过就宣布阈值可行。

用户“批准调整”确认：TaskSpec/API合法性不保证完整CodeAgent锚点可运行。完整锚点、最小胶囊和本次真实绑定计得B_base≥49152时，在模型调用及工具副作用之前固定拒绝，公开只沿task_context_error；不裁任务要求、不提高阈值、不改TaskSpec/API字段。CJK／emoji合法上限夹具须改为真实入口的零调用／零写入／零审批拒绝测试，不能xfail。可运行短任务、ASCII边界及不同绑定／胶囊变体仍验证上述三式与核心路径。

这些是工程初值，包括新增的32 KiB组级门，未经真实provider token数据优化。历史正文字符不能直接套入B。合成离线夹具测完整基线、上述三式及三门±1；若准许运行输入域内的三式或核心路径不成立，仍报告并回到设计审阅，不能偷偷放宽阈值或删除锚点。配置不读取MOKIO_CONTEXT_TOKEN_LIMIT，不增加TaskSpec/API/页面预算字段或默认值；调参另审阅。

## 5. 历史整理与协议不变量

一个完整组 = 一条 AIMessage（含全部 tool_calls）＋按原顺序与原 ID 对应的全部 ToolMessage。多工具 AI 的组不可拆；ID 缺失、重复、孤儿结果、未完成组不能作为合法下次请求。绝不裁 AI 参数、改执行参数、补造 ToolMessage 或把工具 JSON 从中间截成字符串。

始终保留：原 system、原 HumanMessage 中完整 task／planner 指令；初始化时在 task-only HumanMessage 明确补入完整 acceptance_criteria 与 TaskRunContext.fixed_verification_commands，不依赖可能裁剪的 layered memory 文本；当前 attempt 与真实 todos 状态；最近两组完整 AI→Tool 组的原始 AI 消息及**首次进入历史时已经有界**的完整结果 JSON；最近一次尚未被后续修正信息取代的可恢复失败组。已有最后失败输出很大时，其有界结果保留可信 error／exit_code／request_id 和失败反馈正文窗口＋续读入口，不伪造失败原因。scope 拒绝／审批拒绝等终止类结果继续先终止，无摘要挽救路径。

每次prepare先把同路径、同 revision、同覆盖区间的旧读取标为已被新读取替代，删除其中已不必要的完整旧重复组；最近两组／必要失败组即使重复也原样保留。然后计量B，达到72KiB才进一步从最旧非必要完整组整体删除，直至目标或只剩必要组。不直接修改必要组内容，也不留下只有 Tool 的历史。短小旧组也按完整组删除，避免大量微小结果绕过上限。重复读不会直接缓存放行或禁止工具：每次仍真实经过 TaskFilesystem 校验，非必要旧重复正文从下一次请求移除，最新窗口保留；不是所有重复结果立即只留一份。

被删组只贡献本地结构化状态：原序号范围、已删组数、工具名／成功或失败状态、已读取的规范相对路径／revision／区间、真实编辑 receipt、最近命令的 request_id／exit_code、可恢复结果引用。文件事实来自工具结果；todos 属模型提出的工作状态，不能提升成验证证据。胶囊标记 history_compacted=true、source_content_omitted=true、需要重读的路径／区间；不从模型文字提炼“已修复”结论。文件清单最多 32 条，历史 receipt 最多 8 条，超出记录省略数；完整任务要求和最近失败核心字段不可省略。胶囊以普通本地生成 HumanMessage 放在原锚点之后，说明它是历史索引、不是新的任务权限。

可信读取覆盖以 `(canonical_path, revision)` 为身份，来自 §6.1 实际交回 CodeAgent 的源码窗口，合并重叠／相邻区间；内部安全读取了完整字节但未交回的部分不能贡献覆盖。胶囊只放 path／revision／coverage_complete／EOF 已覆盖和本地 read receipt 引用，不复制源码。覆盖表是当前 task／attempt／delegation 的有界元数据；淘汰或区间容量不足时撤销相应证明并要求重读，不能把未记录的缺口推断为已覆盖。具体元数据容量与合并实现须在实施计划中给出，不以省略数代替证明。

文件编辑或写入使该路径旧 coverage 失效；命令不能可靠定位改动时全部读取 coverage 失效。revision 改变后不能把旧范围并入新版本。只有同一 revision 从 0/0 无缺口覆盖到已确认 EOF，才产生本地确定性的 `coverage_complete=true` receipt；模型自述不能生成 receipt，它也不证明模型理解正确。历史正文被整理删除后 receipt 可作为曾完整取得该版本的索引，重建所需正文已不在当前输入时仍须重读。

任务 FileWrite 基于旧内容重建完整文件时，**工具侧前置条件**必须核对同一路径、当前 revision 的 coverage_complete receipt，而非仅靠提示。模型是否依赖旧内容不可可靠判断，因此第一版对任务 FileWrite 改写任何已有文件统一应用此门；不新增创建权限。写入前经原 TaskFilesystem 安全访问重新核对版本，版本与 receipt 不符或覆盖不完整则零写入，`retry_same_operation=false`、`recovery=reread_current_revision`；具体内部拒绝码及安全句柄中校验／写入的绑定位置留给实施计划，不增加公开 failure_kind。无法可靠排除校验到写入间替换时按原规则 fail closed，不声称新增事务文件系统。完成覆盖仍只满足读取前置条件，原写 scope／链接／审批等边界全部保留。FileEdit 继续逐字唯一匹配；信息不足用 FileRead 定位／续读，不能以覆盖证明放宽匹配或编辑权限。

若锚点＋胶囊＋必要组本身大于硬限额，或无法验证消息协议，停止并抛固定本地 `TaskContextError`，不返回 ok=true／完成摘要，不绕过 planner、不增加循环或输出限额。在下一次 invoke 前整理不增加 provider 调用。task 分支的 produced_messages 也使用有界历史，不复制原文旧列表；tool_events 在既有 writer 投影后只保留有限状态引用，避免“发送变短但备用列表仍无限增长”。普通分支的返回值保持原样。委派返回的 summary/todos 与现有 graph 契约保持；任务返回的 messages 为有界内部诊断值，不新增公开原文。

## 6. 正文窗口、长行与结果续读

### 6.1 FileReadTool

任务 read 增加 `char_offset=0`、`revision=None`，原 `file_path/offset/limit` 仍可调用；offset 是零起始行，char_offset 是该行零起始 Unicode 码点位置，不能当作字节偏移。首次读取仍经 TaskFilesystem.read_bytes 的既有安全句柄和 8 MiB 文件门，计算原字节 SHA-256 revision；不优化为按路径重新打开，不放宽 scope／链接／reparse／竞态拒绝。

返回保留 ok/path/total_lines/offset/limit/content/complete，增加 content_format、revision、实际起止行与列、window_complete、eof、truncated、next_read，以及可信 coverage_complete／EOF 已覆盖／本地 read receipt 引用。content 保持编号文本格式；续读长行用显式 line_fragment 标记，编号与标记不算源码、不可带入 old_text。每个实际返回的行／片段有固定metadata：原行号、start_char/end_char、fragment标志、line_ending（LF/CRLF/CR/none），不重复存一份正文；按这些位置去掉可信编号／标记并拼接可重建解码后原文。正文不截 Unicode 码点，CRLF 不从中拆开；空文件与 EOF 无多余页。最终 JSON 转义后仍不得超过 16 KiB，并受整组剩余首屏配额约束；编号／metadata 也计入限额。大路径或其它不可省略字段已经超限则停止，不回显半截路径。

单行未读完时 next_read 是同 offset＋新的 char_offset；该行读完后向下一行前进，必须严格取得进展。next_read 包含同 file_path、明确剩余行数 limit 与 revision，不能从调用方传入路径之外扩展范围。完整窗口仍可能 complete=false：**只有本次从文件 0/0 读到 EOF、无省略才 complete=true**；window_complete 仅描述所请求窗口已读完。行门提前结束但文件未结束时亦给下一窗口入口，eof=false。字节门裁剪必须 truncated=true；不能因只请求一行而伪报文件完整。

累计覆盖与单次 complete 分开：每次将最终有界返回中实际取得的源码片段映射为同 revision 的规范半开区间，包含已交回的换行信息；相邻与重叠页合并，重复页不增加虚假覆盖。只有合并后从 0/0 到可信 EOF 连续无缺口，才由本地代码产生 coverage_complete=true receipt；多页最后一页可以 complete=false、eof=true、coverage_complete=true。只读尾页可 eof=true 而 coverage_complete=false；中间缺页，即使已见 EOF 也不能完整。空文件经可信读取可直接完整。100000 字符长行须全部片段及其结束信息覆盖，不能把“limit=1 窗口读完”当作全文覆盖。覆盖提交在最终首屏裁页之后，不以内部 read_bytes 或分页前候选正文计算；状态引用只存位置／版本／结果，不存第二份源码。

续读每次重新授权并安全读取，下列恢复字段仅存在本地任务工具结果，不增加公开 API／事件字段：

| 内部错误 | retry_same_operation | recovery／允许动作 |
| --- | --- | --- |
| task_read_window_invalid | true | 修正 offset／char_offset／limit 后重新调用同一来源；不写文件、不改变权限 |
| task_read_revision_changed | false | reread_current_revision：作废旧 coverage 和续读链，重新定位当前版本并从可信位置读取；不反复重试旧 revision |
| result_unavailable | false | rerun_source_tool_or_reread：按 §6.2 恢复；重复旧句柄永远无效 |

revision 不匹配不返回旧新混合正文。路径／scope／链接／权限拒绝仍为原 task_file_access_denied 等终止路径，审批拒绝／过期亦保持；不能用笼统 retryable 软化它们。这三项新增码表示不同恢复策略，需纳入实施审阅，不授权自动重跑工具或新 attempt。

### 6.2 大 diff、命令反馈及其它工具结果

任务 CodeAgent 的模型可见工具结果按已注册结果结构生成完整 JSON，再由本地窗口服务把明确可分页的正文映射为固定片段；保留 ok/error、真实 exit_code、request_id、type、替换次数等可信字段。不能将返回 JSON 的一段字符当作 JSON。正文片段带 original_length、实际区间、content_truncated 和服务签发的 next_result_read；original_length／区间采用 Unicode 码点（匹配项页用索引），字节门另计。调用方不能自行选择结构字段。未识别的巨大结构字段不机械裁剪，停止上下文错误。FileRead／Notepad 使用原生文件窗口；Grep 的匹配数组首屏受单条／整组门，已执行查找产生的不可变匹配元数据可作为服务生成的结果片段分页，不让 200 个 metadata 绕过 JSON 门。

新增任务工具 `ToolResultReadTool(cursor, limit)`。cursor 是服务生成的不可猜测 continuation capability，绑定 task／attempt／delegation、已真实执行工具的结果身份、明确暴露的固定 segment、下一页位置及片段类型；映射仅留内存。模型只可回传工具实际给出的 cursor 和正整数 limit，不能构造 field、segment、offset、文件路径、命令或任意 JSONPath。limit 按已声明片段类型表示码点数或匹配项数，本地再施加 8／16 KiB 及整组门；缩页后的 next cursor 由服务签发，必须有进展，JSON 仍有效。cursor 不授予新数据访问权，不接受未暴露的内部片段或 provider 文本。跨身份、未知／过期／被淘汰的 cursor 一律 result_unavailable，不回显归属信息，不伪报 complete；不因重新尝试同一失效 cursor 恢复。有效只读 cursor 可在其生命周期内重复取得同一不可变页，不推进隐式共享读指针。

数据来源与续读方式固定区分：

| 来源 | 续读路径与边界 |
| --- | --- |
| FileRead 源码正文 | FileRead 的 next_read＋revision；每次重新授权、安全读取并更新 coverage，绝不经结果库伪装活文件读取 |
| stdout／stderr／diff 等不可变工具结果 | ToolResultRead 的服务 cursor；只读此前真实执行且明确暴露、实际保存的片段 |
| Grep 命中后的源码上下文 | Grep 返回文件位置＋revision，再调用 FileRead；不可变匹配列表续页不等于重新读取当前文件，搜索内部读取也不计全文 coverage |
| Bash 上游丢弃的数据 | 无续读路径；ToolResultRead 只能遍历本层已保存的输出，不能恢复 executor 丢掉的尾部 |

result_unavailable 的恢复为 retry_same_operation=false、recovery=rerun_source_tool_or_reread。需要当前源码则重新 FileRead；需要已失效结果时，仅可重新调用在现有权限下可安全重复的来源工具。不自动重放 FileWrite／FileEdit 等有副作用操作来取旧 diff；不可安全重复且无其它可信读取路径时停止并报告不可恢复。Bash 若确需重跑，必须另建新请求并逐次审批，旧批准不复用；同一命令可重复也不表示已获授权。恢复若遇到真实权限或审批终止，仍按原根因处理。结果库不是授权缓存，每次续读核对当前生命周期与能力归属，重新读文件继续走 TaskFilesystem。该工具仅加入 CodeAgent 所选工具，不加入 planner 或 verifier 只读工具；文件窗口的两项读取恢复码在任务 verifier 已有 FileRead 分发中同样遵循上述不同策略，不改变固定命令或模型判定路径。

任务 edit/write 的 `_diff` 移除静默 [:4000]：在有限文件大小内生成可分页 diff，先做完整 diff 计量／容量预留与私有候选接纳，再执行原写操作；只有实际操作产生的可信结果才可签发 cursor，写失败不能把候选 diff 当作成功 receipt 或可续读的实际补丁。若单结果无法容纳 32 MiB 库，写操作前固定上下文错误，避免写成功却无法交回必要反馈；不将储存容量失败当 scope_denied。结果库只存已授权工具结果，不存 AI 原始响应／prompt，不写 scratch、trace、checkpoint、日志或公开事件。旧结果 FIFO 淘汰要使句柄显式失效；最新失败结果优先保留，必要结果无法接纳时停止。32 MiB 是存储字节上限，不宣称 Python 总进程内存上限，diff 运算还有有限文件输入与对象开销。

Grep 保持当前“一文件字面查找”语义；现有只搜索前 2000 字符的范围需要显式标出 searched_prefix_only，不能因结果为空宣称整行无匹配。命中记录给出可信文件坐标和该次读取 revision，继续看源码须用 FileRead，版本变化即重新定位；不在本增量顺带扩展 glob／递归／regex 语义。NotepadRead 同样分页，scratch 的访问权限和内容留存规则不变，不自动写新的历史摘要到 notepad。

Bash 续读限于网关**实际交回 worker 的输出**，保留已有 output_truncated。执行器在自身 max_output_chars 门外已丢弃的数据，结果库无法恢复；明确 upstream_output_truncated=true、upstream_complete=false，读到库尾也不能报原命令输出完整。不得自动重新执行命令以取尾部；若仍需信息，读取范围内已有文件或另提有界诊断命令，并遵守新请求逐次审批。本增量不修改 ExecutionRequest、执行器输出上限或固定验证命令。此边界明确区分“本层分页可续读”与“上游已丢弃”，不承诺恢复不存在的输出。

### 6.3 巨大 AI 参数与多工具调用

AI 的工具参数永远原样校验／执行，不做省略后执行或写入半个 JSON。单条 ToolMessage 完整规范 JSON≤MAX_TOOL_MESSAGE_JSON=16 KiB；同一 AI 的全部 ToolMessage 首屏完整规范 JSON 字节总和≤MAX_TOOL_GROUP_VISIBLE_RESULT=32 KiB。两门独立，组门只约束模型首屏结果，不包括 AI 原参数；AI 参数和所有封装仍计入请求 B。超过可见配额的正文进入 §6.2 的 Result Window，源码正文则提供 §6.1 原生 next_read，不能强存为绕授权的源码缓存。

第一项工具执行前先整理可删历史，校验整个 AI 组的 ID／协议并计量：锚点＋必要历史＋原 AI 消息（全部原参数）＋整组最小必要反馈。最小反馈按已注册工具固定结果结构给出可证明的空间需求，保留每项 ID／状态／可信错误或退出码／request_id／必要版本与坐标／明确省略标记及续读能力；正文至少保留该工具所需的最小有效反馈，FileRead 非空页需能向前取得源码片段。对未知结果结构不能假定零反馈；未注册工具仍按既有 unknown tool 固定可恢复回复计入最小反馈，不因预检改成终止性未知工具错误。不得按 `tool_count × 16 KiB` 预留；只有真实必需表示无法满足单条／组门或完整请求 B_hard，才在第一项工具前停止，零文件修改、零审批请求。多个小结果只要实际必需反馈与参数能容纳，就允许执行。

执行前为所有 ToolMessage 分配最小反馈空间，剩余首屏配额再按原工具顺序分给正文；每项使用配额也须给尚未执行的工具保留最小反馈。有效组配额取 32 KiB 与请求硬门剩余空间的较小值，按完整请求重新计量，不能因每项都小于 16 KiB 就突破组门或硬门。配额只裁模型可见正文，绝不改变实际执行参数或伪造成功结果；原真实失败优先于分页／容量异常。可预知的 diff／容量需求依 §6.2 在写前检查，无法接纳必需反馈则停止，不承诺所有后续容量故障都可在组首预测，也不把已经执行的副作用说成回滚。任何终止性工具失败即沿原路径停下，不为了凑齐组而继续执行或补造未执行 ToolMessage；部分组不得再次 invoke。

已收到的模型响应仍按原 usage 计量，不能回减成本。最近两组没有办法同时保留时停止，不能偷偷退成一组。无 tool_calls 的最终摘要也做同一上下文／返回体量校验。32 KiB 是待离线验证工程初值，未由真实 provider 用量优化；T8 须证明多个小结果不会因最大值乘法被误拒、大结果分页、真正无法容纳的组在第一项工具之前停止。

## 7. 修改落点与安全不变量

| 文件／组件（均指实施树） | 预期修改 |
| --- | --- |
| 新 dashboard/task_context.py | B_base／阈值校准契约、完整组校验、规范计量、组首屏配额、状态胶囊与可信覆盖 receipt、纯本地整理与 TaskContextError |
| 新 dashboard/task_result_windows.py | 有界内存结果分页、服务签发 cursor／segment、身份、FIFO／失败保留、不同恢复策略 |
| agents/code_agent.py | task-only prepare／响应预检／有界备用历史、重读与窗口提示；普通分支不变 |
| core/agent.py | TaskRunContext 注入与生命周期、_TaskModel code_agent 后备检查；原预算计量不变 |
| dashboard/task_tools.py | FileRead/Notepad 窗口与最终可见区间覆盖、FileWrite 同版本完整覆盖前置条件、diff 预存与标记、Grep 位置／revision／搜索范围声明 |
| dashboard/task_filesystem.py（如安全绑定确需） | 在原安全访问路径内绑定 FileWrite 当前版本校验与写入；是否需要修改及具体方法由实施计划确定，不能绕开既有安全句柄或宣称未证明的竞态保证 |
| dashboard/task_graph.py | 增加独立build_task_result_read_tool，由CodeAgent在bind前加入所选工具；基础planner／verifier注册表不加该工具，共享结果库显式注入任务文件工具；现有Bash网关不变 |
| graph/nodes.py | task-only 分发透传 TaskContextError；只读 FileRead 的两项码按各自恢复策略处理，保持原 scope／审批终止；不改路由 |
| dashboard/task_worker.py | task_context_error 固定映射与父进程白名单、先有真实根因优先契约；预算快照仍按原路径发布 |
| dashboard/task_events.py | 只增加 ToolResultReadTool 固定工具身份；不公开正文／统计／新事件字段 |
| 相关 tests/dashboard、tests/test_graph.py | 下表离线契约／流程回归及普通行为对照；新增测试文件单独列明 |

新增公开失败只用中性 `failure_kind=task_context_error`。TaskContextError 内部 reason 仍仅枚举 input_too_large／invalid_message_group／result_capacity／unsupported_content；不把协议或内容不支持误称限额越界，不冒充 provider 故障。父进程只接受这一固定类别，公开不传内部 reason、路径、字节大小、工具参数、prompt 或原文。现有已读契约不要求公开这些更细上下文原因，本草案不新增多个公开 failure_kind。新类别仍是需审阅的契约扩展，不增加 Public Event 结构／API 预算字段，结果页只通过既有 failure_kind 形状展示。

**终止根因优先契约：TaskContextError 只有在不存在更早且更高优先级的真实终止根因时，才能成为最终 failure_kind。**以下已产生且可信的根因优先于上下文异常，原有类别／verification_status／回执均不得被整理或异常包装覆盖：

- scope／permission／approval 等真实安全终止。
- provider 调用错误。
- usage_unavailable，包括无法获得可靠 usage 的原停止路径。
- 在原预算检查点已成立的 provider_budget_exhausted。
- 已发生的终止性工具执行／网关／回执错误。
- 正式 verification 已产生的真实失败，保留其原结果与既有终止映射；不能改为上下文根因或倒写 not_run。

这只规定上述真实根因相对 TaskContextError 的优先级，不重新排序它们之间的既有决策，不把可恢复的命令 exit1 或匹配失败升级为终止。已有正式失败若还允许下一 attempt，历史验证事实仍保留；后续上下文阻断不能重新解释或抹除它。具体跨节点终止映射与记录位置须在实施计划核对现有 worker／父进程契约，不自行创造 verification 的新公开类别。上下文机制只阻止超界或协议无效的下一步；异常整理／分页／finally 若再出错，保存先有可信根因并按原路径收尾，不以最后抛出的异常替代它。只保留固定类别与可信状态，不新增原始错误日志。

预算／缺失 usage 在原调用前预检及锁内最终门优先，仍只在原时点决定下一次调用，不提前预扣、回减 usage 或把预算门改成新的工具执行门。已收到响应后的上下文检查不得遮盖已识别 provider／usage 故障；工具终止发生后不进入下一次请求整理。worker／父进程仍先清理再终态，预算快照沿既有 finally 路径发布，快照失败也不能把先有根因替换为 task_context_error。T10 验证无先有根因的新错误路径，以及上述根因与整理／分页／收尾异常竞合路径。

冻结 `src/mokioclaw/tools/*.py`、`graph/architectures.py`、`graph/workflow.py` 不改；planner／verifier顺序和路由保持。TaskContextError在CodeAgent工具调用与planner委派异常包装处须按具体类型透传，不能被笼统except改归tool_exception／task_tool_failed；worker按固定新类别处理。scope 拒绝、审批拒绝／过期、网关失败均保留现有终止语义；实际命令非零退出、唯一匹配编辑失败、invalid_task_command、未知工具仍按现有可恢复规则。固定验证取任务原清单，自测成功不更改 verification_status，不自动批准命令。缺失 usage 继续使下一次调用停止并经现有收尾检查失败；累计达到门继续阻止下一次调用，末次响应可越界的语义保持。

## 8. 无 provider 测试计划与验收

本轮不执行下列实验。获批后所有新增实验先使用全合成源码／diff／工具回复，临时目录在任何 Git 库之外；不依赖私有 Task 原文，不运行复制 boltons／Task10 源码。假模型只保存数值、组 ID 与断言结果，不 print 消息正文。自动防护在工作流启动前拦截真实模型构造（create_task_model、ChatOpenAI、普通 create_model）、dotenv、网络 connect/connect_ex、DockerCLI.run、subprocess.run/Popen/os.system 及真实命令执行器；触碰即失败，不静默 mock 成成功。

流程用真实 TaskRunContext／run_code_agent／TaskFilesystem／任务工具／投影，模型决定和 usage 为脚本夹具。涉及命令仅用明确注入的假执行器，假审批只批准夹具确切 task／attempt／request／digest，断言从未执行真实命令；其许可不能带入产品。回归中原有临时 Git 与能力夹具按已有测试边界运行，新增假模型场景的禁止防护不扩散成“全项目不许任何测试夹具子进程”，但全程禁止 provider／Docker。

| 测试组 | 输入与边界 | 必须观察的结果 |
| --- | --- | --- |
| T1 计量与基线可行性 | 真实bound schemas、完整锚点／options与最小胶囊；实际绑定组合、准入域锚点边界／8KiB胶囊；预定义合成两组／独立失败；ASCII/CJK/emoji/转义/块/大args；三门±1 | 规范字节可复算，裕量一次；准入域三式严格成立，合法大TaskSpec完整基线≥48KiB明确零调用拒绝；失败组不双计，不删锚点／不放宽值；硬门等值可发送、+1零invoke，触发等值整理；不把字节记入usage |
| T2 配对与历史 | 两组／多工具同 AI、几十个小组、孤儿／重复 ID／未完成组 | 必要组逐字段保持；旧组整体删除；非法协议拒绝；每页 json.loads 成功 |
| T3 重复与增长 | 同文件重复 5 次及 16 轮、同路径不同 revision、不同窗口／文件 | 每次都经 FS；旧重复正文移除；下一次模型输入 B 有界；备用列表／库容量有界，无跨委派原文留存 |
| T4 长行与累计覆盖 | 100000 字符单行、limit=1；多字节/转义/CRLF/末尾无换行/空文件；连续多页、漏中间页、重叠/重复/乱序页、只读尾页；整组再次缩页 | 页 JSON≤16KiB、正文≤8KiB且组门有界；坐标前进、可复原原文；最终可见区间才计 coverage；无缺口 0/0→EOF 才 coverage_complete，缺页即使 eof=true 也不完整；多页完成不伪报单次 complete，空文件正确；receipt 无第二份源码 |
| T5 版本／身份／恢复策略 | 续读间 edit/write、假命令范围已知/未知改文件；非法坐标；cursor 未知/淘汰/过期/跨 task/attempt/delegation、伪造 segment/field/JSONPath；失效来源可安全重读或不可重复 | 版本变化旧 coverage/续读链失效；不混读；window_invalid 可修参重试同源，revision_changed 须读新版本，result_unavailable 重复旧 cursor 不恢复；来源重读重新授权、Bash 新审批、不重放写操作；不可重复无恢复路径则停止报告；无跨身份内容泄漏 |
| T6 diff／其它结果 | 超 4000 字符 diff、巨大 Notepad/Grep matches、stdout/stderr、上游 output_truncated | 无静默裁剪；已保留结果可分页复原；上游已丢弃明确不完整、不自动重跑；容量不足时写前停止 |
| T7 失败→重读→编辑／写入门 | 可恢复 edit 失败/命令 exit1 后整理；正文删除；模型声称读完但缺页/旧 revision/仅 EOF；多页完整覆盖、覆盖后文件再变；正确重读后 FileWrite | 最近必要失败/exit/error 保留；信息不足重读；无同版本完整 coverage 时 FileWrite 零写入，自述不能造 receipt；完整覆盖且写前版本相同才满足前置条件，版本变化拒绝；FileEdit 唯一匹配不变；假自测 exit0 不等于正式通过 |
| T8 大参数／多调用 | 多个小结果合计低于组门（构造旧 N×16KiB 会误拒而真实必要反馈可容纳的组）；单个大结果/多大结果；巨大原 AI 参数或真正放不下的整组最小反馈；巨大最终摘要 | 多小结果执行，AI 原参数不裁；大正文分页，逐条≤16KiB、组首屏≤32KiB且完整 B≤硬门；后续最小反馈预留；真正不能容纳时第一项工具前停止、零文件修改/零审批；不补造未执行结果，响应 usage 只计一次；不伪报成功 |
| T9 权限 | scope／baseline／来源／scratch混用、symlink／junction／reparse注入、校验后替换、审批拒绝／过期 | 旧拒绝语义保持；分页和结果库不绕权限；无缓存原文越界；没有自动批准 |
| T10 预算与终止根因竞合 | calls/token 达门、缺失/非法 usage、末次越界；分别在真实安全/审批、provider、usage_unavailable、已达预算、终止工具/网关/回执、正式 verification 失败之后注入整理/分页/finally TaskContextError；无先有根因的四内部 reason；可恢复 exit1/匹配失败对照 | 原调用门/计数不变，usage 只计一次；各先有真实根因、验证状态与回执穿过 CodeAgent/planner/worker/parent/收尾不被覆盖；旧失败不倒写 not_run，不升级可恢复结果；只有无先有高优先根因才 task_context_error；四 reason 不公开，清理后终态与快照路径保持 |
| T11 正式流程 | 假自测exit1→修正→exit0→摘要→planner→verifier固定命令→verdict；在三个收尾点分别撞门 | 原 fixed command、独立 request/receipt 与判断保留；verifier零调用但命令已执行场景仍区分；不把自测当正式passed |
| T12 普通与隐私 | CLI/TUI task_context=None，普通读取／长行／返回列表；敏感合成 sentinel | 普通路径旧行为不变；sentinel不进入公开事件／错误／trace/checkpoint／日志；工具新身份不放宽其它字段 |

新增测试建议：`tests/dashboard/test_task_context.py`、`test_task_result_windows.py`；复用／扩展 `test_task_filesystem.py`、`test_task_graph_injection.py`、`test_task_workflow.py`、`test_task_provider_context.py`、`test_task_events.py` 和现有普通 graph 测试。不改／弱化旧断言来使新行为“通过”；任务 read 新默认的明确变更只更新相应 task 契约期望，普通测试不改期望。

获批实现后的验证固定使用 `D:\envs\codeagent\Scripts\python.exe`，阶段 B cwd，显式 `PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`、`-B`、`-p no:cacheprovider`；每次 pytest 独立 `--basetemp` 为系统 TEMP 下新 UUID，启动前解析并证明不在四仓或任何父级 Git 工作树内。先相关测试，再全项目 `pytest -q -m 'not docker'`；Ruff `check --no-cache src tests`、diff --check、新增产物秘密格式扫描只输出命中类别／位置不输出值；冻结工具／图字节哈希及 Rich／Rich–Click 七份证据按既有清单只读核验。能力 skip、Docker deselection、未执行门与实际时长逐项报告，不预设旧 803／3／35 数字会重复。

## 9. 未解决边界、审阅与下一阶段

确定性状态不能替代旧推理；必要历史过大时宁可显式失败。输入字节门不等于真实 tokenizer／SDK 最终报文／费用门，也不能限制累计调用成本。B_base 与最小／常见组不等式尚未测量，96／72／48KiB 和组首屏 32KiB 尚不能宣称可行。结果库有生命周期与淘汰，无法保证任意旧 diff 永久可恢复；失效句柄不能重复重试或自动重放副作用，当前源码走 FileRead，无法安全恢复则停止报告。上游命令已丢弃尾部无法续读。coverage 证明同一 revision 正文已完整取得，不证明当前模型仍持有全部正文、理解或重建正确；FileWrite 前置门也不能证明新内容正确。真实模型是否选择充分窗口、有效重读仍未知，不能从脚本流程承诺费用或成功率。

已审设计决定：推荐本地确定性方案；96／72／48 KiB、B_base 三项可行性约束与两组保留；8／16 KiB 正文／单条 JSON 与独立 32 KiB 整组首屏门；100 行默认；同路径／revision 的累计 coverage receipt 与已有文件 FileWrite 前置门；32 MiB 内存结果库与 ToolResultReadTool(cursor, limit)；公开 task_context_error、四个仅内部 reason 和正式根因优先契约；三个续读码各自的恢复策略。用户已确认修订方向，具体实施细节仍待实施计划审阅，没有进入产品。

必须留给 Implementation Plan 的具体问题：真实所选 schema／锚点的基线夹具及常见组清单；每种工具最小反馈空间的可证明上界、组配额与最终页的分配顺序；覆盖区间坐标／EOF／换行的实现、元数据容量与 fail-closed 淘汰；FileWrite 拒绝的内部码、同安全句柄版本校验与写入绑定及平台竞态限制；cursor 签发／失效／不可变 segment 类型；既有 verification 失败跨 attempt 的终止映射、异常透传及根因保存位置。实施计划不能改变本文阈值、安全边界或创造公开字段；若夹具证明方案不可行或平台无法满足约束，应回到设计审阅。

用户已确认本文，具体实施计划已另行编写，执行范围／方法仍待审阅；设计与测试计划不代表代码已经实施。内部限额与窗口实现及离线回归确认后，再单独设计同一已授权总门内的交接／verifier保留量：先取得整理后最大输入与输出设置的离线范围，仍不凭假 usage 报真实收尾价格、不先增总门、不跳过 planner／正式验收。真实恢复、具体次数／模型／预算、每项 prepared 启动与 Docker 继续分别确认。

## 10. 实际文档核验记录

以下三段是 2026-10-04 初稿编写时的核验记录，保留其历史范围，不计为本次修订的新测试结果。

完成静态自审并修正三处设计歧义：原验收／固定命令明确加入不可删锚点；重复旧组每轮检查但两组保留规则优先；graph/nodes.py需有限任务异常透传和只读续读码处理，不能假设新错误自动穿过原包装。未写产品代码或执行计划中的实验。

主项目和实施树git diff --check均exit0；主项目仅有既有real_test.md的CRLF提示，该文件未改。七份本轮文档的行尾空白检查零项、秘密格式扫描零命中，测试矩阵T1–T12共12组；这只是有限格式检查，不宣称完整秘密检测。初版扫描缺少词边界，误命中既有task标识中的sk-片段；补词边界后重查，无秘密值输出。主项目.gitignore仅另加新草案单文件白名单，新草案Git可见且未跟踪，没有加入index。

25份开始／结束SHA-256一致：实施树既有产品与测试修改、code_agent.py／task_tools.py、全部冻结tools/*.py及architectures.py／workflow.py、四份私有诊断／审阅资产、主项目real_test.md。此处不扩大成“本轮七份Rich／Click报告重新核验”；它们没有被写入，获批代码实现时仍按计划核验。没有重跑pytest／Ruff／旧探针，没有provider／Docker／工作台连接、真实命令／temp.py执行、源码应用、提交／push或远端变化。结束四仓状态／HEAD／本地引用以最终只读输出为准，不用文档快照替代未来查询。

本次设计修订的新记录：仅用 apply_patch 修改本文；六项要求及 T1／T4／T5／T7／T8／T10 已同步，章节结构与原安全边界保留，未编写完整 Implementation Plan。主项目／实施树 diff --check 均 exit0（主项目仍只有既有 real_test.md CRLF 提示）；本文行尾空白零项、有限秘密格式扫描零命中、旧 failure_kind／旧 field 接口零残留，测试矩阵仍为 12 组计划。32 份本轮新取的前后 SHA-256 一致，范围为上述 25 份加七份非目标文档／.gitignore；四仓 status／HEAD／本地 heads/remotes 前后查询一致，Git 全局 ignore 不可读提示仍在，未修改配置。草案仍未跟踪，未加入 index。这些仅为文档与保留性核对，不是阈值可行性、工具行为或离线测试通过证据；没有执行 pytest／Ruff／探针、provider／Docker／真实任务或用户脚本，未改其它文档、产品源码、旧补丁、来源和冻结证据，未提交／push／fetch。

## 12. 用户批准的接续调整

用户“批准调整”确认准许运行输入域与完整锚点拒绝门，从任务5继续本会话离线实施。历史240 passed／2 failed不倒改；新增真实入口拒绝测试并重新记录结果。没有授权真实恢复、预算提高、provider、Docker或提交／push。

## 11. 逐项实施与实测基线门（历史停止记录；后续调整见§12）

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

## 13. 批准调整后的实际实施与验收（修复前历史验收；最终结果见下节）

用户“批准调整”后，从任务5接续，保留96／72／48KiB、原预算／16轮／planner与verifier／attempt路径。现在任务CodeAgent在每次内部调用前实际替换有界历史，锁内按真实绑定schema与调用选项再次检查，完整锚点基线≥48KiB明确拒绝，非法工具组或不能容纳整组最小反馈在第一项工具前停止。单ToolMessage完整规范JSON≤16KiB、整组首屏≤32KiB；最终源码窗口才贡献coverage，已有文件FileWrite要求当前委派／同版本完整证明，同安全句柄写前核对revision；FileEdit仍逐字唯一匹配。

ResultRead只给CodeAgent，不给planner／verifier；结果库仅内存、当前委派，已执行片段才能签发cursor。巨大diff先做私有容量及首屏预留，写失败不公布候选；Bash上游丢尾部明确不可恢复，重跑仍须新请求／审批。已有安全／provider／usage／预算／终止工具／verification_command_failed优先；正常负verdict仍沿图状态，上一attempt的正式回执不抹除。公开只新增task_context_error与固定工具身份，无内部reason／路径／字节／prompt／源码／provider输出字段。

新增实验只使用合成文件／反馈、脚本模型和明确注入的假执行器，封锁provider／dotenv／真实网络／Docker／真实命令；协议新测试为内存帧，审批只对应确切合成请求，不能带入产品。真实图路径观察到缺页写入拒绝→重读同版本完整覆盖→写入→自测exit1→唯一编辑修复→自测exit0→摘要→planner→原固定命令独立请求／回执→verdict。正向12次假模型调用；三个收尾门9／10／11分别挡摘要、planner、verifier。最后一种verifier模型0调用而正式命令已取得第三份回执，不据零调用改not_run。

指定Python、PYTHONPATH=src、无字节码／pytest缓存、仓库外独立basetemp：相关整组287 passed／16.66秒，exit0（mokioclaw-context-22fc7a11a31c4f2db6827207bb587f5e）；全项目非Docker890 passed、3 skipped、35 deselected、169.74秒，exit0（mokioclaw-context-636bec3eb96945fca6fb7661cc37a904）。三项skip为tests/dashboard/test_catalog.py:76及tests/evals/test_grader.py:204、219的symlink创建不可用；35项Docker标记未运行。两组均1条既有Starlette/httpx弃用警告。Ruff --no-cache src tests exit0。以上为修复前历史验收；最终作者自审与修正后回归见下节，不能当作真实模型能力或费用证据。

未解决边界：字节门不等于SDK报文／token／费用；合法TaskSpec可能被基线门拒绝；整理后信息不足仍需重读；覆盖不证明理解／重建正确，POSIX不声称跨进程原子CAS；不可分的超大Grep单项记录可能在只读查找后显式失败；库淘汰不能恢复旧diff或上游丢尾。真实重复读轨迹、逐次token、真实修复成功率及同一总门内交接／verifier保留量仍未验收。没有provider、Docker、真实任务、.env秘密读取、temp.py、旧补丁／来源写回、提交／push／fetch；boltons余0、Task10第五批余2保留，停止讨论不解除。真实恢复／每prepared启动、Docker、来源补丁应用、提交／push和收尾保留量继续分别授权。旧49485地址不作在线保证或运行许可。
当前最终9项schema与实际会话最小胶囊的纯本地校准（6 passed／1.35秒，独立basetemp mokioclaw-context-e0cda26897514c158ffaad03540f7c2a）：短任务B_base=9385、ASCII上限33404；对应最小两组增量1686、预定义保守常见两组25990、独立失败2399；8KiB胶囊变体基线17385／41404，准入域三式成立。CJK／emoji合法上限81304／105254在完整锚点门明确拒绝，真实入口已测零invoke／零写入／零审批。Schema差异与实际胶囊字段使数字不同于旧停门记录，旧81314／105264与2 failed不倒改。保守常见组来自固定100×60码点窗口／40码点参数／8192字节diff／两路各1024字节反馈，独立于真实模型分布；实际首屏还受完整ToolMessage及组配额。原8KiB胶囊增长、语言／转义、绑定／调用选项与硬门±1均有离线断言，不承诺费用下降。

## 14. 最终离线验收与作者自审

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
