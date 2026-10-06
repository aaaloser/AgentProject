# MokioClaw 任务收尾保留量设计草案

> 2026-10-04 用户验收：用户明确“先接受这个离线实现吧”，本轮收尾七项离线实现已接受，保留此前内部上下文能力；这不代表整个阶段B或真实维护能力已验收。真实token／费用、摘要质量与维护成功率仍待单独校准；真实停止门保持，boltons余0、Task10第五批余2保留，不授权provider／Docker、真实恢复或每个prepared启动、预算提高、来源应用、提交／push，禁止子agent。本次仅记录验收，不重跑产品测试，381／977等仍为前次实施验证。

> 日期：2026-10-04（Asia/Shanghai）
> 最新状态：用户已批准[逐项实施计划](../plans/2026-10-04-mokioclaw-task-closeout-reserve.md)并指定本会话直接执行、禁止子agent；七项离线产品交付已完成。最终相关381 passed；非Docker977 passed／3 skipped／35 deselected；Ruff通过。实施实测见本文§10、阶段B交接§60／进度§99。下面方案形成时的“草案／待审”保留为历史，已批准行为以本文策略及配套计划最终记录为准；真实任务、provider／Docker、预算提高和来源／Git发布仍无新增授权。
> 前置：任务 CodeAgent 内部上下文实施已完成离线验收，见同目录 `2026-10-04-mokioclaw-task-codeagent-context-design.md`、阶段 B 交接§57／进度§96。本文只设计后续收尾分配，不重复其实施，也不更改96／72／48KiB等已批准限额。
> 实施位置仍为阶段 B 工作树；主项目两份较旧根设计是历史基线，不能代替当前授权。用户禁止使用子agent。

## 1. 目标与边界

在用户已批准的同一个总调用数／已报告 token 门内，提前结束继续修复的模型循环，让 CodeAgent 交接、planner 收束、正式固定验证和 verifier 判定有机会执行。完成定义仍由真实固定命令请求／回执与合法 verifier 判定共同决定；自测通过、摘要出现或局部补丁正确均不替代正式验收。

这不是总额度增加，也不是收尾成功保证。固定调用槽只对下文受限收尾流程给出调用次数分配边界；token 预测没有硬上界，末次响应仍可能越过总门，时间、审批等待和 provider 故障也可能阻断收尾。真实 boltons 逐次 usage、真实收尾输入与精确被挡节点仍未知，不能为其报价，不能将字符／字节减少换算成费用下降。

适用范围：带真实 TaskRunContext 的维护任务及其 CodeAgent 委派。普通 CLI/TUI、入口聊天分支保持；既有 TaskSpec 合法范围与总预算上限保持，不新增默认真实额度。任务预算小于推荐保留量仍可合法创建，但不保证准入新的修复委派。

本轮批准阶段B工作树产品实施、严格无provider合成测试及必要文档更新；复用现有工作树、本会话逐项、禁止子agent。没有provider smoke、真实Agent网络／命令实验、Docker、真实任务恢复、prepared启动、预算提高、来源或旧Agent补丁写回、提交／push／fetch。boltons余0，Task10第五批余2保留、连续两次未正式完成后的停止状态不解除；49485只是历史地址。

## 2. 现有机制与直接依据

核对阶段 B 当前源码：

- `core/agent.py` 的 TaskRunContext／_TaskModel 对所有阶段共享累计调用与已报告 total_tokens，usage 只在真实开始的 invoke 后入账一次；缺失／非法 usage 标记阻止下一次调用，worker 结束检查也阻止成功。总门是调用前检查，不能预知末次响应。
- `agents/code_agent.py` 的任务分支最多16次模型循环；摘要也占 code_agent 阶段调用。新内部历史整理保留完整 AI→Tool 组与锚点，但没有收尾配额。
- `graph/nodes.py` 的 planner／verifier 各最多8次模型循环。CodeAgent 返回摘要后 planner 仍可再次委派；verifier 可先读工具再作判定。因此“摘要、planner、verifier三次”只是常见路径，不是所有路径硬下界或完整上界。
- verifier 按原样固定命令依次走任务审批／执行网关，取得回执后才第一次调用判定模型。命令失败或拒绝可能先终止。verifier 的“read_only”集合实际包括 BashTool，不能据名称当成所有命令天然无副作用。
- 冻结的 `graph/workflow.py` 在 planner、verifier 返回后均接 context_monitor；两处都可能路由一次压缩模型。图层400000估算阈值不覆盖 CodeAgent 内部历史，不能假设两处永不触发。
- `dashboard/task_result.py` 的 verification_status 按当前 attempt 的可信固定命令回执生成，与任务终态／模型 verdict 不等同。模型未调用但命令已通过时，可以出现 task failed 与 verification_status passed；不能倒改为 not_run，也不能据此宣称任务成功。

本文不改冻结 `tools/*.py`、`graph/architectures.py`、`graph/workflow.py`，不改变压缩路由，不跳过 planner，也不绕过下一次调用的共享预算门。

## 3. 三件事的可行选择

### 3.1 何时结束修复并让出调用机会

| 选项 | 具体规则 | 优点 | 代价／边界 |
| --- | --- | --- | --- |
| A1 最小路径三槽 | 摘要1、planner1、verifier1；另须处理两处可能压缩 | 改动较小，修复可用调用多 | planner 不能更新Todo后再答复，verifier不能先读取再答复；三槽不覆盖压缩，不能称完整保留 |
| A2 有限工具收尾（推荐） | 核心五槽：摘要1、planner2、verifier2；另留前后压缩各1，共最多7槽 | 允许一次Todo反馈、一次证据读取，仍有可核对的调用上界 | 比最小路径更早让出；复杂判定可能读不够，必须明确失败 |
| A3 保留现有循环 | 摘要1、planner最多8、verifier最多8、两处压缩各1，共最多19槽 | 尽量保留原收尾探索能力 | 20调用的任务几乎没有修复空间；只靠3或5槽不可能同时保留原无限制用途 |

推荐 A2。7是选定受限流程的工程分配上界，不是观测到的真实成本、所有任务必用次数或新的默认总预算。第一轮先不允许跨阶段借用已放弃的槽；进入CLOSING之后，不用的槽只从待完成配额中释放，绝不重新开放修复。

### 3.2 如何根据剩余调用与已报告 usage 决定收尾

| 选项 | 具体规则 | 优点 | 代价／边界 |
| --- | --- | --- | --- |
| B1 固定 token 比例 | 例如到已用75%即收尾，同时使用调用槽门 | 最简单，容易解释和测试 | 25%是拍定策略，缺乏真实成本依据；对长输入、短任务和不同阶段都粗糙 |
| B2 纯动态估计 | 按本任务各阶段已报告 usage 预测后续成本，仅凭预测切换 | 利用已有 numeric usage，不新增内容日志 | 未出现阶段无样本；估计偏低会花光调用，偏高会过早停修复 |
| B3 调用槽＋动态触发（推荐） | 调用槽是确定的分配约束；usage 估计只控制继续修复，不作为收尾调用的另一道预测拒绝门 | 同时覆盖“有token但没调用”和“有调用但token不足”；预测失准时仍按原总门尝试收尾 | 仍可能末次越界；冷启动和安全系数需明确，不能许诺完成 |

推荐 B3，使用下文可复现的工程初值；不把预测金额或字节换算写入产品／报告。系数可选1.0（保守性较弱）、1.25（本草案推荐初值）、1.5（更早收尾）。离线能核对决策，不足以挑出真实最优系数。

### 3.3 如何验证不削弱固定验证与审批契约

| 选项 | 具体覆盖 | 优点 | 不足 |
| --- | --- | --- | --- |
| C1 纯配额单测 | 剩余槽、估计、状态转换、±1边界 | 快、易定位 | 无法证明正式请求／回执和 worker 终态没有被误判 |
| C2 真实图＋脚本模型＋假执行器（推荐） | C1加完整图、审批帧、命令身份、独立回执和结果汇总 | 无provider仍覆盖真实接线与安全边界 | 合成usage不是真实成本，不证明真实模型遵守收尾协议 |
| C3 获批后真实校准 | 在C2之后，另行审批每次真实任务／额度 | 可观察真实阶段usage与成功率 | 当前未授权，boltons额度已用完，不能用Task10余次代替 |

推荐本次设计采用 C2 作为未来实施验收门；本轮没有运行它。C3只是后续可能选择，不是本设计自动附带权限。

## 4. 推荐策略的具体状态与配额

新增仅任务内部的收尾协调器，生命周期按真实 attempt 管理，使用 TaskRunContext 现有锁。只接受可信代码给出的阶段／用途；模型文字、工具参数、worker外来帧不得选用途或重置配额。共享预算累计跨 attempt 保持，局部配额不是另一个可消费的预算账户。

逻辑状态：REPAIR（允许受控继续修复）→ CLOSING（不可逆让出）→ FINISHED／FAILED。只有现有 verifier 明确失败路径、max_attempts 允许且新 attempt 准入通过，才可建立下一 attempt 的 REPAIR；终态错误不得借机重试。

| CLOSING 用途 | 最多实际模型调用 | 允许内容 |
| --- | --- | --- |
| CodeAgent交接 | 1 | 不绑定工具；非空摘要，区分修改、自测、未完成事项和需正式验证的内容 |
| planner收束 | 2 | 第一次仅TodoWriteTool；第二次无工具。仍由模型收束，不伪造Todo完成 |
| planner后图层压缩 | 1 | 仅在原路由实际触发时调用；保留现有失败和fallback契约 |
| verifier判定 | 2 | 第一次可请求一组有界读取；第二次无工具并产出合法判定 |
| verifier后图层压缩 | 1 | 仍由原路由决定，包含去final或下一attempt的现有路径 |

verifier CLOSING 工具集合建议仅 FileReadTool、GrepTool、NotepadReadTool；不提供模型自由发起的 BashTool。正式固定命令仍按原任务列表在模型判定前独立执行，逐项审批，没有复用自测审批或自动批准。这个集合收窄是待审行为选择：若要保留额外Bash诊断，须单列方案，其审批不变，命令执行时间／结果体积与失败均会额外影响收尾，不能算作已保证的只读。

现有任务工具已有的结果边界保持；“一组读取”不等于无限工具：建议CLOSING首轮verifier最多3个调用，仅允许上述3种工具，整组先核对结构、参数及各工具现有准入规则再执行。超出则明确收尾失败，不先执行前几个；这是一项新协议限制，3是工程初值，不声称真实任务普遍够用。verifier原工具路径不自动继承CodeAgent的结果库／正文窗口，3项不是正文或token门，长行等大结果风险仍存在；本方案不把它们暗中截断。已有CodeAgent最近完整组／必要失败／锚点、JSON和tool_call_id契约不改变。

局部配额不得扩大CodeAgent16次或planner／verifier各8次的原循环上限。CodeAgent到最后一次允许迭代时，如仍无真实摘要，必须提前切为摘要模式；任务planner若可用迭代不足两次，也须提前收束。已产出的响应切换不能凭空增加第9次planner调用；没有剩余迭代则明确phase_limit失败，不生成假模型摘要。自然完成的真实响应仍正常接受。

## 5. 调用槽与 usage 决策算法

设 C = 总调用门 − 已开始调用数，T = 总已报告token门 − 已报告累计值。调用数、usage与阶段计数均从现有可信上下文读取；无有效usage先按原契约停止，绝不补零。合法数值0仍是有效usage。

待完成用途的次数为 n_s。repair期间保留集合包括摘要1、planner2、两处压缩各1、verifier2，故初始 R_calls=7。只有真实完成对应用途才减少其配额：真实摘要被接受、被指定为收束的planner响应实际产出、监控确认某处不压缩或verifier判定完成。普通repair阶段planner响应不消耗未来收束槽；不能在监控运行前猜测“不压缩”释放两槽。

只在本任务内存保留各可信用途已报告单次 total_tokens 的最大值 h_s，以及全阶段最大值 h_all；不新增原始prompt／源码／工具正文／provider输出或逐次内容日志。code_agent未区分用途的既有数值，可作为首次摘要的保守冷启动来源；后续通过内部可信用途区分，公开stage集合与原聚合usage快照保持。

推荐初值：O取本任务原输出上限，alpha=1.25，E_s = ceil(alpha × max(O, h_s))；无该用途样本则以 h_all 替代 h_s。下一次repair估计 E_repair 同式；R_tokens = sum(n_s × E_s)。O只是非零估计底数，不是total_tokens上界；high-water、安全系数都不能证明未来响应的输入量或真实费用上界。

按顺序处理：

1. 原取消／超时、可信终态根因、缺失usage及共享调用／token总门仍优先适用；收尾政策不能掩盖已有scope拒绝、审批失败或provider错误。
2. 首次修复委派准入至少需 C>=8（一次repair机会加7槽）；调用槽不足时不开始CodeAgent、不伪造摘要，明确政策失败。为避免冷启动猜测让合法任务永远无修复机会，整个task唯一首次repair调用不以token预测拒绝，仍必须通过原总门；这一次响应也可能越界，属于明确保留的风险。后续委派／attempt不重置这一次机会或usage最大值。
3. 已有本task一次有效repair usage之后，在下一次repair invoke前，若 C<=R_calls 或 T<=E_repair+R_tokens，即锁定CLOSING；原循环剩余迭代不足也提前收束。未触发则允许原循环继续；预测不预扣实际token，usage仍仅入账一次。
4. 锁定后保留已完成AI→Tool组，不删原参数或改变配对；不得发起新修复／新自测。已经开始并通过现有整组准入的工具组完成后再进入摘要；其scope／审批／命令失败仍立即走既有终止语义，不为了凑摘要继续副作用。进入任何尚未开始工具组前再次检查usage／已有根因，缺失usage不再执行该组。
5. 进入CLOSING后，即使 T<R_tokens，也不再用预测拒绝实际收尾；每个真实invoke仍逐一通过原共享硬门和对应用途剩余槽。用途槽检查在invoke前，不提前移到verifier的固定命令之前，正式请求／回执与模型调用的先后保持。用完用途槽或响应违反受限收尾协议则失败，不从其它用途借槽重试。
6. 自然返回非空CodeAgent摘要时，不额外再调用摘要模型。如planner仍有充足新委派准入空间，可继续原修复逻辑；后续新委派必须在创建服务／绑定模型之前满足C>=8，并以已有usage满足T>E_repair+R_tokens，否则进入CLOSING。准入预测按新委派将需要的集合重新计算（包含新摘要1和后续planner2），不能沿用上一摘要已经释放后的R_tokens；这里只规划未来用途，不清累计预算或历史usage。若planner一次AI组含多个委派，首个使政策进入CLOSING后，其余已知委派请求逐个给固定、可恢复、无副作用的closeout_requested反馈，配对原ID；不是scope拒绝，不得经通用ok=false变成task_tool_failed。未知工具、非法参数及真正scope拒绝保留原处理。
7. 若切换发生在已产出的planner工具响应中，该已入账invoke可计作收束第一槽，补齐全部原ToolMessage后只剩一次无工具答复；不得再次入账。若切换发生在invoke前，直接绑定收束工具集合，并保留两槽。再次委派的准入必须在实际委派前检查，不能只靠prompt。
8. verifier明确失败后，新attempt准入在begin_attempt之前至少核对 C>=9（一次planner、一次repair、七槽收尾），并用已有usage预测修复是否仍可准入；不足则保留上一attempt及其真实固定回执。9只覆盖最小起始路径；如果准入后planner实际消耗更多调用而未委派，新attempt已经真实开始，须如实保留其not_run，不能回滚或挪用旧attempt回执。累计usage、数值最大值与调用数不清零。token预测可触发早收尾，不替代现有max_attempts／失败类别限制。

示例只说明次数：20次总门，若当前已用13、待完成集合仍为7槽，则下一次repair被阻止，转入收尾。若已自然产出摘要，集合少1；两次监控没有触发压缩时再分别释放1。实际可能只用3次，也可能用满7次；数字不预测150000 token能否足够，不能据此复跑boltons。

## 6. 输出、失败与验证事实

建议新增一个固定公开failure_kind：`task_closeout_incomplete`，表示总门尚未实际耗尽但局部收尾准入／受限协议不能完成。内部原因仅固定枚举budget_slots_insufficient／phase_limit／invalid_handoff，供代码分支与断言；本版不新增公开原因字段或内容日志。既有verifier_invalid、usage_unavailable、provider_budget_exhausted、scope／审批／命令失败保持原分类，实际硬门命中不能改报新kind。

另一可行选择是统一使用既有worker_failed，改动更少但诊断模糊；不推荐把预测触发或局部槽用尽伪报provider_budget_exhausted。新增kind是待审公开契约调整，实施须同步可信根因登记、worker发送／父进程白名单及结果模型允许域；只放行确切枚举，不能接受任意模型字符串。

soft closeout_requested是本地委派反馈，不是终态根因；必须先通过既有usage／错误优先检查，且不得从模型文本登记。正式命令请求／审批／回执独立存在，任何新kind不改写其事实：

| 实际证据 | 结果应保持 |
| --- | --- |
| 没有正式命令请求／回执 | verification_status not_run；即使自测exit0 |
| 部分正式命令已经失败 | 保留已执行失败／未执行项，按既有结果汇总；不能统写not_run |
| 正式命令均通过，但verifier模型被总门挡住 | task failed／原budget根因；可信固定命令状态可为passed，不能宣称verdict或task completed |
| 正式命令均通过，verifier明确passed=false | task未完成；按原明确失败／attempt规则处理 |
| 回执齐全且通过、verifier合法passed=true、后续路由与worker结束检查通过 | 才可形成原成功终态；压缩或cleanup失败不提前完成 |

max_seconds和审批超时保持。调用槽不保留命令执行秒数；10条命令各自超时与总时限可能冲突，不扩大总时限，也不自动缩短／跳过固定命令。planner／verifier输入仍有当前机制的体积与信息不足边界，本草案不偷偷给它们新增上下文截断。读不够或摘要失真须明确失败，不假装证据完整。

## 7. 修改落点（审阅后才实施）

实施计划细化：新attempt预测额外包含一次起始planner；同attempt激活幂等，usage与首次repair机会跨attempt保留。两处压缩由可信节点返回位置区分，不能依赖模型metadata；现有verifier_invalid是内部异常，当前worker归一化为task_tool_failed，计划保留这一路径，不顺带新增该公开kind。TaskSpec／结果模型现为字符串failure字段，未新增允许域或API结构。计划界面与测试接口细节见配套计划Task1–7，具体实施仍待计划审阅。

| 位置（阶段 B src/mokioclaw/） | 计划职责 |
| --- | --- |
| 新增core/task_closeout.py | 纯数值预测、用途配额、状态机与准入；不依赖provider／网络／执行器 |
| core/agent.py | 可信用途绑定与调用前守门、已有usage数值传递、锁下原子转换；不改原入账／跨attempt总门 |
| agents/code_agent.py | repair边界检查、一次摘要模式、完整工具组收束及有界真实交接 |
| graph/nodes.py | planner委派准入／可恢复反馈、受限收束与verifier工具轮、两处压缩槽的真实释放、新attempt开始前检查 |
| dashboard/task_worker.py及必要结果模型／允许域 | 新固定kind端到端白名单及原根因优先；不新增API控制项、日志内容或自动审批 |
| tests对应core／agents／graph／dashboard | 下节纯离线行为与接线测试 |

若真实实现发现需要改冻结文件、总预算、TaskSpec接口、公开usage结构或新增日志字段，应回到设计修订，不将这些改变附带实施。冻结图的两个监控节点不需改路由；节点实现可向上下文报告已发生的分支。

## 8. 未来离线测试与验收计划

边界先明确：仅合成任务／文件／模型输出／usage，依赖注入的脚本模型、假审批通道与假执行器。测试启动前封锁provider构造／dotenv加载、socket与HTTP网络、Docker入口、真实subprocess／实际命令执行。阻断钩子意外触发必须使测试失败；假模型输出、合成审批或回执不能带入产品真实任务，固定命令字符串只作为精确身份数据，绝不执行。

| 测试组 | 关键断言 |
| --- | --- |
| 配额／状态 | C=R_calls−1／相等／+1；首次准入7／8／9；自然摘要释放、不压缩的实际释放、两处都压缩、用途无借用、首次/后续planner响应计槽只一次 |
| token／usage | T=E_repair+R_tokens的±1；stage冷启动／全阶段fallback／合法0；1.0／1.25／1.5可重复决策；预测过高仍尝试收尾，低估／末次越界后下一次停；缺失／bool／负值无下一invoke或新工具组 |
| CodeAgent协议 | 自测exit1→修复→exit0后切换；未自测也能真实报告未完成；大diff／参数、最近失败、最近完整组与ID不丢；摘要无工具／非空；非法工具摘要明确失败、无副作用／无额外重试 |
| planner | 同一AI组多个委派中途切换，全部反馈配对；closeout_requested不会登记task_tool_failed；真正scope／未知／非法参数保留契约；一次Todo后无工具答复、不伪造completed、不跳过planner |
| verifier／审批 | 原固定命令字节身份与顺序不变；自测与正式命令请求ID、审批与回执独立；拒绝／过期／错digest／错command_hash／缺或重复回执保持拒绝；模型额外Bash无执行；1组0／1／3读取和4项整组拒绝 |
| 真实图路径（假模型） | 核心3调用、5调用、7调用三条路径；原两个monitor／compressor节点确实经过；verifier非法JSON／非法bool原失败；缺usage发生在摘要／planner／verifier／压缩时均无下一调用 |
| 结果／attempt | 摘要前挡、planner前挡、正式命令后verifier前挡、部分正式失败、最后压缩挡；task终态与verification_status分别断言；负verdict可准入重试，不足在begin_attempt前停且不清预算；最大attempt仍生效 |
| 原根因／安全 | scope、审批、命令、provider、usage／硬门与soft切换同边界时原根因不被新kind覆盖；cleanup保留第一根因；模型伪造用途／kind／cursor／预算无效；结果窗口与覆盖写入门回归 |
| 兼容／信息边界 | 普通CLI/TUI与入口聊天不受配额；小总预算合法TaskSpec的明确定义；长行／重复读取／缺信息重读仍按已批准上下文规则；只计量数值且公开usage快照字段不变 |

实施步骤的依赖顺序建议：先纯配额策略与失败契约断言，再可信接线与CodeAgent切换，之后planner／verifier／两处压缩分支，最后worker／结果整图验收。此处是设计的测试顺序，不是已批准实施计划，当前没有执行。

获批实施后使用D:\envs\codeagent\Scripts\python.exe，显式PYTHONPATH=src，PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider，每次仓库外独立--basetemp。先相关组，再全项目非Docker；Ruff --no-cache、两树diff --check、有限秘密格式扫描与冻结哈希按既有门验收；逐项报告skip／Docker排除与实际结果。未跑的不能记成pass，历史291／894也不能成为本方案的新验证。

## 9. 设计形成时的证据、未解决边界与待审项（历史）

已为新目标完整读两树根SKILL指定的V1与当前阶段B设计、独立内部上下文设计及最新接续记录；从当前源码核对调用门、planner／verifier、两处压缩、结果回执语义。四仓实时HEAD及本地heads/remotes重新查询，未fetch：main4134081c0a8fc4786aa28b1e33fe060d69ddcfd5，阶段B033fedbc48b428a221289f227a999c1beed0c5b4，旧来源4ca74f958301228cb48cb1e9c7d15463fa1d8e74，boltons干净detached967864f89791509f9eb36b22b4579d36b72a6df2。既有修改保留。

本轮仅设计作者自审／文档检查，无子agent／独立审阅，无新增实验、pytest或Ruff。保护哈希／源码测试摘要与文档格式检查的最终实测写入交接§58、进度§97和瓶颈顶部；不沿用旧测试作为新验收。

未解决：token估计失准及首次repair越界；未知阶段fallback可能很保守、导致过早收尾；2次判定／3项读取不够；合法大输入的内部基线拒绝；摘要质量与planner／verifier输入体积；时间／审批／provider／cleanup风险。调用槽只约束受限用途，不是质量、费用或真实成功保证。禁止自动恢复试点或提高预算。

用户可审阅的主要选择是A2／B3／C2，以及7槽（含两次条件压缩）、1.25工程系数与一次冷启动repair、verifier一组最多3项读取且无额外Bash、新固定task_closeout_incomplete。这些均仍是草案。用户选择／修订后，再写逐项实施计划供批准；真实恢复和每次prepared启动、provider／Docker、来源补丁应用、提交／push继续分别授权。

## 10. 批准计划后的实施与最终离线验收（2026-10-04）

用户明确“计划ok的，现在开始逐项实施吧，注意不要调用子agent来实施”后，在已有阶段B工作树本会话直接完成七项授权的产品／离线测试计划。没有派发或采用子agent实现／审阅；这是作者自审，不称独立审阅。原dirty／未跟踪内容保留，没有提交或新建工作树。

已落地：core/task_closeout.py只管理数值配额；摘要1、planner2、verifier2及前后条件压缩各1，共最多7槽。1.25整数向上取整估计只决定何时结束repair；首次实际repair只有一次免预测机会，原共享预算／输出／迭代门不变。可信用途、唯一实际入账及决策沿现有context锁；CLOSING不能借槽或重新修复。CodeAgent交接为空工具真实绑定，完整锚点／基线门／最近完整组及原ID保持；空摘要或非法工具摘要明确失败。planner新委派在服务／binding之前检查，合法后续拒绝仅本地closeout_requested；采用nested委派前已开始的planner调用号，不重复计总账。verifier首轮最多3项FileRead／Grep／NotepadRead整组先校验、末轮无工具；正式固定命令仍原样逐项独立审批／回执并先于判定模型，模型额外Bash不执行。两处压缩按可信返回位置计槽，新attempt最低9调用且含起始planner预测，门失败不begin_attempt、不抹旧回执。公开仅新增固定task_closeout_incomplete，内部reason及原文不公开，usage仍12字段。

真实图合成路径覆盖缺coverage写入拒绝→完整续读→写入→自测exit1→唯一编辑修复→自测exit0→交接→planner→独立正式命令→verdict；自然三调用尾部总12次，采用既有planner响应的五槽路径总13次，含两次压缩七槽路径总15次。五／七槽包含已开始的第一planner响应，不能误写为自测后新增5／7次或为了计数补无意义调用。五个收尾阶段的缺usage与下一调用硬门均有整图断言；正式未运行仍not_run，正式命令已过而模型被挡保留passed但任务failed，真实开始attempt2后当前not_run且attempt1回执保留。结果用现有build_task_result（TaskService.result实际调用的构建器）汇总，计划中的TaskResultService名称已澄清，不新增替代服务。

各阶段先运行预期RED再实现；详细失败／夹具纠正保留在主项目.superpowers/sdd/2026-10-04-mokioclaw-task-closeout-reserve/progress.md。作者交叉自审发现投影异常可能留下错误局部终态，先失败断言后修正：budget／最终投影失败标FAILED，最终投影成功后才FINISHED。另完成锁一致性整理和非整除ceil、1.0／1.5独立手算oracle补测；这些补测在策略实现后加入，不冒称各自RED。原小预算安全夹具改为足以触达原断言的合成预算；小预算拒绝另测，真实预算不提高。内存通道夹具恢复顺序曾使旧回环测试失败，已纠正；失败记录不倒改为通过。

最终指定Python、显式PYTHONPATH=src、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider、每次仓库外独立basetemp：相关18文件381 passed、0 failed、34.32秒、exit0，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-closeout-a50ab3126f32418e8eff43c1a7a6157a；全项目tests -m "not docker"为977 passed、3 skipped、35 deselected、175.03秒、exit0，basetemp=C:\Users\lyf\AppData\Local\Temp\mokioclaw-closeout-c85ffda58d7e456d964b3a85b3e8375c。skip为test_catalog.py:76及test_grader.py:204／219的symlink创建不可用，35项Docker未运行；两组各1条既有Starlette/httpx弃用警告。Ruff --no-cache src tests exit0。此前361／376／972是补测或锁整理前中间记录，291／894是上一轮内部上下文历史结果，均不替代本次最终验收。

新增合成实验封锁provider构造／dotenv、socket与HTTP、Docker入口、真实执行器及命令，意外触碰sticky审计为0；另有一个专门验证“吞掉禁止钩子异常仍失败”的预期负样本。正式命令字符串只是精确身份数据，均由假执行器返回独立合成回执；旧全项目回归中已有的本地Git／回环夹具按原边界运行，不称全项目每条测试都无网络／无子进程。没有provider／Docker／真实Agent试点、.env秘密值读取、用户temp.py执行、旧Agent补丁整理／应用、来源或冻结证据写回、预算提高、提交／push／fetch／远端变更。

产品验收后重取21份SHA256（冻结tools8＋图2、Rich／Rich–Click报告7、boltons诊断4）逐项与本轮起始相同。四仓新查HEAD／全部本地heads-remotes不变：main4134081c0a8fc4786aa28b1e33fe060d69ddcfd5，阶段B033fedbc48b428a221289f227a999c1beed0c5b4，旧来源4ca74f958301228cb48cb1e9c7d15463fa1d8e74，boltons干净detached967864f89791509f9eb36b22b4579d36b72a6df2；两个来源status逐字保持。Git用户级ignore不可读提示仍在，未改配置。最终文档格式／有限凭据格式核验另见本节末尾补记，不宣称完整秘密审计。

边界仍在：预测可能过早收尾或末次越界，合法大锚点仍可拒绝，verifier三项读取不构成字节／token上界，2轮或摘要可能信息不足；时间、审批、provider、cleanup及POSIX跨进程CAS仍未保证。离线结果不证明真实模型遵守协议、真实费用下降或维护成功率。boltons余0、Task10第五批余2保留与连续两次未正式完成后的停止门保持，旧49485不是在线保证。七项离线交付完成后，下一步只审阅本地差异／记录；真实校准／恢复及每个prepared启动、provider／Docker、来源补丁应用、提交／push仍须分别授权，不自动使用余次。

最终文档补记：24个明确源码／测试／文档／ledger目标全文的有限私钥／凭据格式、冲突标记、行尾空白扫描0命中、缺文件0；两树diff --check均exit0，主项目仅既有real_test.md CRLF提示。计划45项步骤已勾选，未勾选列表步骤0。此为有限格式核验，不宣称完整秘密检测；未改.gitignore／real_test.md、冻结文件或来源。
