# MokioClaw 本地工作台 CodeAgent 接入设计（阶段 B）

> 2026-10-06 主目录合并验收：在 D:/MokioAgent/MokioAgent 运行的新回归1310 passed/3 skipped/77 deselected/1 warning（213.95s，exit0），原生合成42 passed/0 skipped/0 warning（8.77s，exit0），Ruff --no-cache通过；实际模块来源已核对为主目录src。3 skip为既有symlink不可用，77为35 Docker+42另跑native，1 warning为既有Starlette/httpx弃用提示；本次native使用兼容record_property的JUnit xunit1，实际junction与共享冲突32属性保持，未宣称symlink创建能力通过。主目录代码/测试/pyproject与824e372完整一致，独立420项合并映射覆盖两树，历史清单保留。没有现场服务/原Task/旧观测操作或新真实调用。

> 2026-10-06 主线统一：用户已明确“现在合并吧”，本次将 codex/mokioclaw-stage-b 的已验收实现与历史合并到 main。后续开发使用 D:/MokioAgent/MokioAgent；本文件接纳实施树完整设计及增补，成为主目录当前阶段B设计，原“主项目设计较旧/只读实施树”分工按合并前历史读取。阶段B离线实现与N1–N4已接受，AF_PIPE/Tk/浏览器、旧持有者退出后的保留基线/加载绑定和真实启动/额度仍分别授权；合并不代表整个阶段B真实验收完成。旧阶段B工作树和分支暂保留，不操作其中可能在用的服务或无关文件，不使用子agent。

> 2026-10-06 用户验收更新：用户明确将 N1–N4 原生合成文件门判通过，并授权提交、push最近未同步的阶段B相关实现、测试和交接文档；本轮分别同步既有 main 与 codex/mokioclaw-stage-b，不合并分支。旧“无提交/push”记载按各轮历史读取。下一项先制定并审阅全新合成临时根内、无provider/Docker/真实Agent的 AF_PIPE/Tk 长寿命、EOF/关闭和浏览器恢复验收计划，获批后执行；现有服务/原Task/旧观测文件的停止、保留基线与加载绑定，以及真实启动/新额度仍各自授权。私有运行资料、冻结证据和无关未跟踪文件不纳入同步。

> 2026-10-06 当前：既有批准的 Windows 原生合成文件门 N1–N4 已完成，两个测试文件最终42 passed/0 skipped（8.08s），真实目录共享冲突32、junction、三旧文件holder、17绑定故障点和8关闭路径均有证据。相关324 passed/1 skipped（38.90s），全项目1310 passed/3 skipped/77 deselected/1 warning（190.66s），Ruff --no-cache通过。只S三份测试/合成child变更，产品源码保持；完整377映射见M的native-matrix-hashes.json，实际矩阵与失败历史见native-matrix.md。历史完整清单与native-acceptance.md均保留。现场服务/Task状态未核验，AF_PIPE/Tk/浏览器、正常退出后的旧文件保留基线/加载绑定、真实启动和额度仍分别授权；无provider/Docker/现场操作/提交/子agent，旧boltons余0、Task10第五批余2及停止讨论保持。下方旧“基础5项/原生未执行/矩阵待补”均按历史读取。

> 2026-10-05 接续设计本次审阅已修订、仍待批准：主项目2026-10-05-mokioclaw-prestart-observation-continuation-design.md §4–8/§11补实同句柄磁盘fresh校验、Windows相对父句柄独占创建、bind创建sessions即消费一次性资格、service→manager锁顺序、关闭失败保锁及唯一来源/唯一Task的原repo_id恢复。Task仍prepared/sequence2/未执行，spec/request_digest与8文件manifest及16份副本匹配；361/21/7指纹0变化，旧三文件0/0/100、现场hash仍读取失败。netstat显示63711监听PID35508，未操作实例或确认加载修复。没有接续代码/计划/测试、pytest/Ruff、provider/Docker/重启/重绑/运行或子agent；118/1134是历史绑定修复结果。先批准书面设计，再写计划并审阅；Windows原生门与真实恢复/新额度/Task启动继续分别确认。boltons余0、Task10余2及停止门保持。

> 2026-10-05 观测文件保留接续设计待审：用户要求制定保留文件的方案，已形成主项目docs/superpowers/specs/2026-10-05-mokioclaw-prestart-observation-continuation-design.md。推荐原三文件原位保留、同Task一次独占session、fresh未执行/合同/源码门及原repo_id恢复；三个显式接续参数尚未实现。Task仍prepared/sequence2/execution_started=false、无attempt/worker/请求回执；三文件0/0/100字节，Get-FileHash均被占用，未取得现场hash或冻结确认。必须旧持有者正常退出后才能建立保留基线，不清空/移动/追加、不新建替代Task或自动重试。测试矩阵已写、未执行；361源码测试、21保护及7旧Taskhash保持，四仓HEAD/本地引用与来源index保持。下一步审阅设计后才编写具体实施计划；本轮仅只读/文档，无provider/Docker/重启/重绑/真实任务/新额度或子agent，boltons余0、Task10余2和停止门保持。最新见校准§17/交接§69/进度§108；1134 passed仍为前次绑定修复结果。

> 2026-10-05 观测绑定修复已实施并通过离线回归：用户“可以的，开始修复吧”批准两项计划，本会话直接完成、无子agent。阶段B仅改两份产品和三份测试：viewer序号1–(2**63-1)、worker仍1–1024，严格类型／单调／防重放／未知role拒绝保持；ViewerChannel交换失败永久失效并关闭，已有父端EOF路径撤销ready。最终相关118 passed；全非Docker1134 passed／3 skipped／35 deselected，Ruff通过；两轮RED为10和24个目标失败。63711是用户修复前自行重启并绑定的实例，本轮未重启或操作现场。原Task仍prepared／execution_started=false，已有独占calls／scores／status三文件，前两份0字节；直接重启重绑会碰撞原保护，不能删除、覆盖或另建Task掩盖。下一步先审阅保留已有观测文件的未运行Task接续方案，再安排加载修复及现场验收，真实恢复／新增额度／额外容器检查／prepared启动仍分别确认。没有provider／Docker／真实调用或新额度，boltons余0、Task10余2和停止门保持。最新实测见校准设计§16／交接§68／进度§107；下方待审和无observations均属历史。

> 2026-10-05 绑定失败诊断：用户截图显示绑定失败／calibration_observation_invalid。Task nM9uXVzm-80YmpnpzG5ifFsk仍prepared、无worker／attempt／命令回执，新root无observations。已确认当前codec把viewer与worker序号统一限为1024，而原生窗口每500ms持续poll；纯内存复现立即绑定成功、1023次poll后绑定在1025被拒绝，客户端还未关闭连接。当前窗口从01:06:50启动已远超名义512秒，现象与复现一致；没有现场最后序号，不宣称排除了其他IO／调度故障。新增两项离线修复计划docs/superpowers/plans/2026-10-05-mokioclaw-viewer-binding-fix.md待审：viewer采用独立有界序号并保留单调／防重放，交换失败永久关闭通道并撤销父端就绪。未改产品／prepared／来源／旧证据，未重启、重新绑定、provider／Docker／run或审批，没有新增额度，禁止子agent。旧boltons余0、Task10余2和停止门保持；用户批准修复后先离线验收，再安排重启和绑定，不能用立即绑定绕过长寿命缺陷。当前诊断见校准方案§15／交接§67／技术进度§106；前段‘待绑定后启动’须先过修复门。

> 2026-10-05 新校准任务已准备：用户“那你开始准备任务吧”授权准备，本会话在61771仅预览并创建一次Task nM9uXVzm-80YmpnpzG5ifFsk（repo_id VM6ft8DoH9aT0feYNsOjl9tM），停在prepared。原1149字符说明、八项读写范围、固定命令及150000／20／3072／1 attempt／1200秒保持；新baseline／work八份源码各80098字节，16项与固定提交blob逐字节一致，仅work另有框架生成的两份空白记事文件。没有worker／attempt／命令回执；观测目录尚未建立，原生窗口待用户绑定该Task，不能据此声称观测就绪或正式验证通过。本轮未调用provider／Docker、未/run或审批、未增加额度、不使用子agent。boltons原余0、Task10余2及停止门保持；后续观测绑定、额外容器检查、恢复与新一次额度及该prepared启动须按各自门完成。详见主项目真实校准设计§14、阶段B交接§66／技术进度§105；此前60718／未创建Task文字为历史。

> 2026-10-05 接续：用户“ok的”接受私有观测离线交付。用户提供60718工作台后，本会话仅作只读就绪核对：页面boltons为干净detached，base／anchor／HEAD均967864f89791509f9eb36b22b4579d36b72a6df2，当前页面没有绑定Task；服务进程13544使用uv托管Python，带--enable-agent及原镜像，但task-root仍为旧boltons-mokioclaw-private/tasks，未带--calibration-root。此实例未通过本轮私有观测就绪门；实际模块来源、Tk／私有管道／绑定与真实逐次记录未验收。下一步由启动者使用指定Python、阶段B源码和新校准root/tasks重启并提供新地址，详见真实校准设计§13。地址访问不授权新一次额度／Docker／准备或/run；boltons余0、Task10余2及停止门保持。此轮没有产品修改、新pytest／Ruff、provider／Docker、创建Task、命令审批或运行，不使用子agent；下方待用户验收／未访问工作台文字保留历史。

> 2026-10-04 最新私有观测实施：用户“可以的，开始吧”批准六项离线计划，已在阶段B dirty 工作树本会话直接完成，未使用子agent，待用户验收。逐次白名单／原计数与政策、实际交接单槽／显式超限提示／评分、认证JSON字节IPC／独占数值文件、显式校准开关／prepared绑定及原生查看器接线已落地；公开API／TaskSpec、原总门／七槽／上下文／scope／审批／固定正式验证保持。本轮全非Docker1073 passed／3 skipped／35 deselected，Ruff通过；相关698通过是后补ACK检测前记录，最终全项目已覆盖修正。21保护资产及7旧Task hash、四HEAD／全部本地引用和两来源status保持，主项目产品未改。具体计划最终段、StageB交接§64／技术进度§103为当前状态；下方“未执行／待审”保留历史，不能覆盖本授权。没有provider／Docker／真实AF_PIPE或GUI／工作台／新校准根／真实Task。真实逐次usage、交接语义／费用／正式完成仍未测；当前无需工作台，需要启动时先告知。真实恢复、新一次额度／额外容器检查和每prepared运行仍单独确认；boltons余0、Task10余2与停止门保持。

> 2026-10-04 最新观测计划：用户确认真实校准方向并要求需要启动工作台时告知。主项目docs/superpowers/plans/2026-10-04-mokioclaw-private-calibration-observation.md已形成六项具体计划（数值契约、可信接线、交接内存、认证IPC／文件、原生窗口／绑定、实际图离线回归），全部未执行，待具体计划审阅；此前校准草案‘待方向确认’是历史。选择AF_PIPE＋Tk、显式--calibration-root、32条队列／1秒ACK、私有409600帧及失败清除等细化随计划待审，不改原总门／正式验证／审批。当前无需启动工作台，无新增实验／pytest／Ruff、产品代码、provider／Docker／GUI／真实任务，不使用子agent。最新交接§63／进度§102；离线验收后需要工作台时再告知，真实恢复／新一次额度／额外容器检查及每prepared启动仍单独授权，boltons余0、Task10余2保留。 本计划轮实际两树348份产品／测试Python、21保护资产及7旧Task资产hash保持；四仓HEAD／引用保持，stage／来源status保持，main仅新增本计划；两树diff检查通过、9个明确文档有限格式扫描0命中。

> 2026-10-04 最新校准方案：用户接受离线实现后要求制定真实校准方案，主项目docs/superpowers/specs/2026-10-04-mokioclaw-real-calibration-design.md已形成待审候选。推荐先补仅数值私有记录＋本机内存交接查看，再新boltons同SHA／原说明／原命令／150000 token／20调用／3072输出／1 attempt／1200秒一次；Task10余2不转用。现有聚合事件无法还原逐次usage或交接语义质量。观测实现、恢复／新额度、最多两次额外无provider容器检查及每prepared启动均未批准；本轮仅只读与文档，无新增实验／pytest／Ruff、provider／Docker或真实任务，禁止子agent。最新记录见阶段B交接§62／进度§101，旧‘下一步’按历史读取。

> 2026-10-04 用户验收：用户明确“先接受这个离线实现吧”，本轮收尾七项离线实现已接受，保留此前内部上下文能力；这不代表整个阶段B或真实维护能力已验收。真实token／费用、摘要质量与维护成功率仍待单独校准；真实停止门保持，boltons余0、Task10第五批余2保留，不授权provider／Docker、真实恢复或每个prepared启动、预算提高、来源应用、提交／push，禁止子agent。本次仅记录验收，不重跑产品测试，381／977等仍为前次实施验证。

> 2026-10-04 最新实施状态：用户批准收尾逐项计划，七项离线产品交付已在本树完成，本会话直接执行且未调用子agent。Task-only七槽／1.25数值预测、真实交接、planner与verifier受限收束、两处条件压缩／attempt准入及固定task_closeout_incomplete已实现；原总门、上下文门、审批和正式固定命令保持。最终相关381 passed；非Docker977 passed／3 skipped／35 deselected；Ruff通过，21份保护SHA256与四仓HEAD／引用保持。当前协议与边界以主项目独立收尾设计§4–8／§10、计划最终记录、本树交接§60／进度§99为准；下面“全部未执行／待审／停止”属其形成时历史。作者自审不是独立审阅，真实token／费用／质量未验收；provider／Docker、真实恢复与每prepared启动、预算提高、来源应用及提交／push没有新增授权，boltons余0、Task10余2保留。

> 2026-10-04 最新计划状态：用户选择推荐A2／B3／C2。主项目 docs/superpowers/plans/2026-10-04-mokioclaw-task-closeout-reserve.md 已形成七项可审阅计划，具体参数／接口／失败契约随计划审阅；全部尚未执行。本会话直接逐项、禁止子agent；provider／Docker／真实任务／预算提高／来源写回／提交／push无新授权。最新记录见本树交接§59／进度§98，独立收尾设计已同步选择状态；下面旧草案／待审／部分实施状态均为历史，内部上下文实施已完成仍见§57／§96。

> 2026-10-04 最新文档接续：用户要求先写同一总门内收尾保留量方案并列出三项选择。主项目独立草案 docs/superpowers/specs/2026-10-04-mokioclaw-task-closeout-reserve-design.md 已形成，推荐A2／B3／C2：核心5槽＋两处条件压缩各1、usage动态触发、无provider真实图验收。7槽、1.25系数、首次repair冷启动、verifier工具收窄和新failure_kind均未批准／未实施。内部上下文任务1–8已完成，见本树交接§57／进度§96；下面旧部分实施／任务5停门文字是历史，不代表最新状态。本轮仅文档、无新增实验／pytest／Ruff；禁止子agent、真实停止门及所有独立运行授权保持。新设计记录见交接§58／进度§97。

> 2026-10-04接续授权：用户“批准调整”确认任务CodeAgent的96／72／48KiB保持，合法但完整锚点基线≥48KiB的TaskSpec在内部入口固定拒绝；基线三式适用于准许运行输入域。按主项目2026-10-04内部上下文设计与实施计划从任务5继续离线实施，原基线失败保留为历史。没有provider、Docker、真实恢复、预算提高或提交／push授权。

> 日期：2026-09-28（Asia/Shanghai）
> 状态：用户于 2026-09-28 指示按本设计逐步实施；provider 调用与真实 Agent 试点仍需单独授权
> 前置基线：`2026-09-26-mokioclaw-local-repository-review-dashboard-design.md` 与本地工作台 V1
> 目标：固定提交 → 独立任务副本 → 受控 CodeAgent 工作流 → 人工审阅补丁与验证证据

> 2026-10-04 当前增补：用户已批准任务内部上下文设计及本会话逐项离线实施。纯计量／完整历史整理、结果库、源码窗口／覆盖写入门、显式服务接线已部分实现；完整绑定基线校准在合法CJK／emoji上限夹具失败，按独立设计§4停止任务5后续接入。96／72／48KiB和总预算均未改，任务5未完成、6–8未开始。CodeAgent尚不创建新委派，生产FileWrite没有coverage证明将拒绝；内循环限额、组配额、固定新failure_kind透传、全流程与全项目验收尚未交付，不能将本工作树当作可恢复真实任务版本。详细设计／计划位于主项目docs/superpowers/{specs,plans}/2026-10-04-mokioclaw-task-codeagent-context[-design].md，执行实测见本树交接§55／进度§94。真实停止门、boltons余0、Task10余2保留不变。

## 1. 意图、范围与完成定义

用户从已经登记的本地仓库及其历史提交，手动建立一个维护任务，明确描述目标和可读取的源码范围，然后在本机页面观察任务状态、逐项批准命令、审阅补丁摘要及实际验证结果。任务只在独立副本中产生改动；来源仓库、远端和旧评测证据保持不变。`review-priority-v1` 仍只描述历史提交的人工审查顺序，不自动创建任务，也不充当 Agent 成绩。

本阶段包含本地任务的预览、准备、状态、审批、取消、补丁与验证摘要，以及在满足执行边界后复用完整 CodeAgent 工作流。它不包含 GitHub 登录、PR 回写、来源仓库补丁应用、外网部署、自动任务触发或 Rich/Click 正式槽位补跑。真实 provider 试点是单独的最终门，必须由用户另行明确授权具体仓库、模型／provider、预算和运行次数。假执行器验收不能表述为真实修复能力。

完成阶段 B 的条件是：用户能在页面对一个固定 base SHA 创建、观察并审阅受控任务；运行中的每个命令可追溯到确切批准；任务副本中的补丁与验证结果可追溯；来源仓库的 HEAD、refs、index、工作树和 ignored 夹具在验收前后相同；真实工作流所需的隔离与数据边界通过测试。未达到执行门时，页面只允许预览／准备，不显示可用的真实“运行”入口。

## 2. 已有能力与决定

现有 `dashboard/` 是只读 Git/API/页面路径。`core/agent.py` 的 `stream_agent_events` 有完整工作流事件；`agents/code_agent.py` 的 `run_code_agent` 只是工作节点，依赖图状态和 planner 指令。普通 `BashTool` 可使用主机 shell，现有正则风险分类不覆盖全部命令；验证节点还可能绕过普通 Bash 审批直接调用 `CommandExecutor`。`create_runtime`、`create_model` 会加载环境配置，trace/checkpoint 和原始图事件可能含任务文本、源码或工具输出。评测的 Docker 执行器只保护其实际接入的命令路径，不能直接推断网页工作流已隔离。`GrepTool` 的递归遍历对符号链接还需补路径校验。

比较三条路线后选择：

| 路线 | 判断 |
| --- | --- |
| 直接用来源树作 workspace 调用现有 Agent | 来源改动、主机命令与网页审批边界不可接受；不采用。 |
| `git worktree` 加现有 Agent | 与来源共享 Git 元数据，且 `cwd` 不限制命令访问；不作为 V1 隔离边界。 |
| 固定 SHA 的独立文件副本、任务协调层、受控命令执行器 | 采用；成本是副本准备、路径审计、审批与脱敏事件投影。 |

本阶段复用工作流语义，不另写一套 Agent；同时不要求改动旧 CLI/TUI 的默认行为。任务入口与现有只读提交 API 分开，避免改变 V1 的数据契约和优先级规则。

## 3. 用户流程与权限分层

1. 在某仓库提交详情中选“创建维护任务”，页面明确显示仓库、完整 base SHA、该提交所属历史锚及当前 HEAD。dirty 工作树只作警示；任务输入永远来自提交对象，不包含未提交内容。
2. 输入任务描述并选择源码读取／写入范围；第一版二者相等。页面预览匹配的已跟踪普通文件数量、总字节数、排除项和不支持项。默认不全选；空范围不能准备。用户必须明确确认私有源码的选定范围可能经工具结果进入 provider。
3. 用户创建任务后，接口立即返回 `task_id` 与 `preparing`；独立于 HTTP 请求的可信准备执行器从固定 SHA 复制许可文件到任务副本，记录来源身份、base SHA 与清单摘要。页面轮询到 `prepared` 或 `failed`；准备失败不留下可运行任务。
4. 只有执行门通过且用户单独点击“运行”后，任务才开始；已有 active task 返回 `409 task_busy`，不排队。命令请求先暂停，页面显示完整命令、任务及 attempt 身份、容器工作目录、超时、固定网络边界及批准理由；批准／拒绝只适用此请求一次。页面关闭不等于批准。
5. 页面轮询已脱敏状态和事件摘要。用户可以取消；超时或进程中断留下可审阅的部分结果，但不自动恢复执行。
6. 任务结束后，页面分别展示 Agent 运行状态、补丁摘要、每条实际验证命令及其结果。人工审阅发生在任务副本；本阶段没有“应用到来源仓库”或“创建 PR”操作。

“创建任务”“运行任务”“批准命令”是独立动作。历史提交的 `high`、`medium`、`low`、`manual_review` 不改变任务执行权限，也不推断修复结果。

## 4. 身份与任务数据契约

任务引用启动时已登记的 `repo_id`、完整 `base_sha`、完整 `anchor_sha`，不接收浏览器传来的任意本机路径或修订表达式。创建时重新验证对象格式、base 在 anchor 历史中可达、Git 对象可读。来源 HEAD 后续移动不改写已准备任务的 base。任务 ID 是随机不透明值；任务目录由服务端映射，不从 URL 路径拼接。

`TaskSpec` 的唯一字段契约为 `task_id`、`repo_id`、`base_sha`、`anchor_sha`、`description`、`source_read_scope`、`source_write_scope`、`task_scratch_scope`、`manifest_digest`、`max_seconds`、`max_attempts`、`verification_commands`、`max_provider_calls`、`max_total_tokens`、`max_output_tokens_per_call`、`created_at`。三个 scope 的含义见 §6；第一版 `source_write_scope = source_read_scope`，scratch scope 由服务固定，均使用规范化相对路径。`manifest_digest` 是许可文件按规范化相对路径稳定排序后的 `(relative_path, git_mode, blob_oid, blob_size)` 清单的规范 JSON UTF-8 字节的 SHA-256，不包含 blob 内容；预览和准备须复算一致。`network=none` 是固定执行不变量，不是可由用户修改的 TaskSpec 字段。任务描述与路径可能含私有信息，网页只在对应任务页面显示，URL 只保留不透明任务 ID；`TaskSummary` 不含绝对任务目录、provider 凭据或原始事件。幂等键绑定排除 `task_id/created_at` 后的规范请求摘要：同键同摘要返回同一任务，同键不同摘要拒绝。

状态机为 `draft → preparing → prepared → running ↔ awaiting_approval → verifying → stopping → completed`。准备失败可从 `preparing` 进入 `failed`；取消先进入 `cancelling`，总超时或 worker 崩溃先进入 `stopping`。`completed`、`failed`、`cancelled`、`timed_out`、`interrupted` 是终态；`cleanup_failed` 是**非终态**的资源风险状态并携带同名 `failure_kind`，禁止启动新任务。第一版没有 `queued` 或自动调度：已有任务处于准备、运行、审批、验证或清理时，另一个 `POST /run` 返回 `409 task_busy`，用户稍后主动重试。`completed` 仅表示工作流正常收束，验证通过另有 `verification_status`；provider、工具、验证和补丁失败分别记账。状态变迁与单调事件序号原子记录；重复运行、迟到事件、迟到审批及终态后写入均拒绝。

**终态不变量：**对曾启动执行 worker 的任务，只有控制器确认该 task 的 worker 已退出、其拥有的全部 Docker 命令容器均停止并移除、且不再有可修改 work 的 Agent 执行资源时，才能发布任何终态。取消顺序是 `running/awaiting_approval/verifying → cancelling → 停止 worker → 清理所有归属容器 → 确认清理 → cancelled`；超时、异常和正常完成也先经过 `stopping` 再发布相应终态。清理无法确认时进入 `cleanup_failed`，保留待清理资源身份并阻止后续执行，不能伪装为普通 cancelled/timed_out/failed。后续 reconcile 若完成清理，最终记录 `failed`、`failure_kind=cleanup_failed`；不能自动恢复原运行。这里的“不再修改”限定为 MokioClaw 的 Agent 资源，不声称能阻止本机用户另行编辑任务目录。

每个 worker 记录可核验的进程身份（PID 加创建身份或平台等效机制），每个容器在启动前分配服务生成的 `instance_id`、`task_id`、`command_request_id`；Docker label 与名称使用固定 MokioClaw 命名空间，归属标识在创建容器时写入并记录在任务元数据中，避免“容器已启动但仅靠子进程 PID 才能发现”的窗口。控制器只终止身份完全匹配的 worker／容器，不触碰其它任务或非 MokioClaw 容器。启动、取消、超时和 dashboard 重启均调用 `TaskWorkerController.reconcile()`：先发现当前或先前实例遗留的归属资源，停止并确认移除，再把未完成运行任务标为 `interrupted`；无法确认时保持 `cleanup_failed` 和执行禁用。重启不重放任何批准或自动续跑。run/cancel、approval/cancel 与超时边界按同一任务锁串行决定；同一进程最多一个 active task、最多一个执行 worker。

服务在用户明确指定的 `--task-root` 下保存任务副本与最小元数据。未传此选项时，原有 dashboard 继续只读运行，任务接口返回能力不可用。该目录必须解析为绝对路径，不能位于任何登记来源仓库、其 `.git` 目录或冻结证据目录内。每个任务有不可变 baseline 与可写 work 目录；baseline 不暴露给 Agent。Phase B 不自动删除任务产物：baseline、work、完整本地补丁及摘要会一直留在用户指定的 task-root，可能含私有源码。页面和文档提醒启动者避开同步盘与公开目录；目录权限沿用本机用户，清理由启动者负责。本阶段不设 Web 完整产物下载或自动 GC。
任务的完整 `TaskSpec` 另存于 task-root 内的私有 `spec.json`，用于工作台重启后按原请求摘要恢复固定范围和预算；公开 `record.json` 仍只含摘要与状态。`spec.json` 含任务描述、相对源码范围和验证命令，按任务产物的同一留存与目录隐私规则处理，不经 API、事件或页面原样下载。

## 5. 固定提交与副本准备

可信准备器只用受控、只读 Git 参数枚举 base SHA 下的树对象，并仅对批准范围内的普通 blob 读取内容；不对整个仓库执行 checkout、archive 或 clone。路径大小写折叠后排除文件名 `.env`、前缀 `.env.`、后缀 `.pem`／`.key`、文件名 `id_rsa`／`id_ed25519`／`credentials.json`／`secrets.json`，以及路径段 `.git`／`.mokioclaw` 和本项目的 `evals/reports/` 冻结证据目录；ignored 与未提交文件本来不在提交树中，也不读取。路径规则不能证明其它文件不含秘密，用户仍须审阅批准范围。预览只用树元数据，不读取 blob 内容或秘密值。

第一版上限为：路径选择最多 100 项、普通文件最多 5,000 个、单文件最多 4 MiB、复制总量最多 64 MiB、任务描述最多 4,000 字符、预览有效期 10 分钟、单任务总运行时间最多 30 分钟、单命令最多 600 秒、最多 3 次 Agent 尝试、预先指定的验证命令最多 10 条。provider 预算由用户对每项任务明示，取值上限为 20 次请求、累计 100,000 个已报告 token、单次最多 4,096 个输出 token；下一次调用前检查已知用量，达到阈值即停止。provider 未报告用量时停止并记为 `usage_unavailable`；最后一次调用可能使累计量越过阈值，不能将此机制表述为严格费用上限。超限在预览或准备阶段给出固定错误，不截断后继续执行。

第一版对 Git symlink、gitlink／submodule、非普通文件、Windows 不可安全表示的路径、大小写折叠冲突、路径穿越、过大单文件／总量和 Git LFS 指针一律拒绝或从范围中排除并明确提示；不得静默复制不完整内容后继续运行。每个写入路径在创建前及写后都校验仍位于任务根内。准备后复算 `manifest_digest` 并保存清单；可信补丁收集器只比较此固定 baseline 与 work，不依赖来源树工作状态。新增文件也必须是任务目录内、写入范围内的普通文件，符号链接和越界文件不能进入补丁。

来源仓库在准备前后只读记录 HEAD、refs、index 摘要和工作树状态。预览 base 为 A 后，即使来源 HEAD 前进到 B，只要仓库根身份与 A 的对象／清单仍一致，任务仍只准备 A；页面提示 HEAD 变化而不替换 base。来源目录被移动、仓库身份被替换、base 对象或 blob 在准备中丢失、Git 读取超时／截断、范围不完整都阻断准备。真实任务不扫描或哈希 ignored 私有文件；临时夹具验收另行对 ignored 证据文件做字节级前后比较。

可写 work 在执行期另设**软边界**：最多 5,000 个普通文件、总普通文件字节数 128 MiB、单文件 8 MiB。可信控制器在每次命令前后及执行中的有界周期扫描 work；超限即停止该命令／任务并走资源清理，记录 `workspace_limit_exceeded`。补丁收集遇到超限、symlink 或不可安全读取文件时返回 `patch_unavailable`，不读取／展示半截补丁。Docker 的 CPU／内存／PID 限制不限制宿主 bind mount 磁盘占用；周期监测不能阻止两次采样之间的瞬时增长，因此它不是文件系统硬配额，真实试点须在启动前确认 task-root 所在卷有足够空间或另有卷配额。

2026-10-03 Task 10 预算上限调整：第三批前两次授权试点（交接 §23）证明 100000 已报告 token 门使 Agent 固定验证从未获得执行机会——三次运行（含第二批第 4 轮）全部在 `verifier_calls=0` 时撞门。经用户批准，任务级 provider 预算的取值上限上调为**24 次请求、累计 200,000 个已报告 token**（`task_service` 创建校验同步），上限是门不是默认值：每次真实试点仍须对请求次数与 token 上限逐项明示授权。预算机制本身不变：下一次调用前检查已知用量、达到阈值即停止、缺失用量仍为 `usage_unavailable`、最后一次调用可越过阈值；单次输出 token 上限（4,096）不变。

2026-10-03 第 6 次后 token 门调整（当前有效上限）：第 6 次真实试点在 17 次调用／205032 已报告 token 时触发 200000 token 门，固定验证仍未执行。用户批准仅将任务累计已报告 token 的取值上限从 200000 提高到 **300000**，调用上限继续为 **24**。API 创建校验、真实任务上下文与页面输入约束三处同步；页面默认 1 次调用／1000 token／单次输出 100、输出取值上限 4096 及现有用量检查／缺失用量／末次响应可越界语义不变。离线回归须证明 200001、250000、300000 可创建并持久化、可经真实上下文进入 worker；300001、25 次调用及 API 非法类型仍拒绝，假模型在 200000 后可继续、达到 300000 或末次越界后阻止下一次调用。此次授权只覆盖本地上限调整与无 provider 回归，不授权新真实任务、Docker、提交或 push；六次真实额度仍全部用完。提高门不等于 Grep 修复完成，仍需 Agent 固定验证、补丁人工审阅及另行授权的 POSIX 容器门控。

## 6. 执行、审批与 provider 边界

2026-10-03 预算事件投影一致性修复：用户批准仅将 `budget_usage` 白名单投影的单阶段与总调用上限从 20 同步到 §5 的 24。真实上下文可合法产生 21–24 次用量，worker 收尾与父进程重投影均须接受，并保留原本的完成／预算耗尽／工具失败／worker 失败结局及用量快照；25 次以上、非法类型、身份与字段仍按原契约拒绝或剪除。回归使用真实计数上下文、假模型、真实本机认证回环协议和父进程消费，不调用 provider。此次只修复已确定的本地收尾缺陷；第四批第 5 次缺少预算快照，实际调用／token 仍未知，不据此回填历史或宣称唯一根因。不新增公开诊断文本、预算字段或失败类别，不修改冻结文件、调用计量和试点授权纪律。

2026-10-03 Task 10 预算校验一致性修复：用户确认修复 API 创建校验、真实任务上下文与页面输入约束不同步的问题。`TaskRunContext` 与页面预算输入的上限同步为 24 次请求／200000 已报告 token，与 §5 已批准的任务创建上限一致；默认值、单次输出限制、逐任务预算授权及下一次调用前检查机制均不变。回归须使用真实 `TaskRunContext.from_settings` 走 worker 启动入口（仅工作流流替换为假流、禁止 provider 初始化），覆盖 150000 的实际授权值、22／150000 的中间值、24／200000 的上限及越界拒绝，避免只测试 API 创建或替换上下文构造器后遗漏运行时校验。此修复不新增公开失败类别，不修改冻结工具／图文件或命令审批语义。

2026-10-03 Task 10 验收增强：第四批第 3 次首次达到 completed／patch available／Agent 固定验证 passed，但独立审阅仍发现目录链接与替换竞态、glob 退化、fd 泄漏／漏计数和范围错误返回缺口。用户批准仅增强下一轮任务说明与回归，保持 qwen3.5-flash、150000 token／20 调用、来源／范围／固定镜像／network=none 与原固定验证命令。私有 -d 说明（3928 字符，符合 API 4000 上限）要求在 tests/test_tools.py 加入五组回归：文件／目录链接、glob 与显式路径契约、身份不匹配关闭 fd 并计数、目录枚举前替换、reparse 拒绝。回归不得删减断言或增加跳过，仅两项 Windows POSIX 链接门控允许 skip，固定 Linux 容器应执行；reparse 注入夹具同时设置 attribute=0x400 与 junction tag=0xA0000003。编码／EOF 继续独立复核，同一 fd 字节读取允许 os.read，不要求按路径重开或反复 fdopen。说明内嵌测试经过 AST 等价、缺陷负样本及参照实现正样本检查，不能凭固定命令 passed 自动接受／应用补丁。此为 Task 10 试点验收方向更新，不修改冻结工具／图、公开事件或任务预算机制；真实运行仍需 prepared／run-policy 后逐次确认，独立 Docker 仍另行授权。

2026-10-03 Task 10 第 5 次授权补充：第四批第 4 次按 -d 写入回归但 150000 token 门前未执行自测或 verifier，独立验证拒绝其实现。用户明确批准下一次 -e、qwen3.5-flash、累计 200000 已报告 token／24 次调用；单次输出 3072、1 attempt／1200 秒、五组回归、原固定验证命令与其余边界不变。-e 正文 3999 字符，补充 stat 模块／目录区分、Windows 字段默认值、DirEntry 转 Path、枚举身份锚点提示；五组测试 AST 与 -d 相同。提高门仅增加余量、不保证质量，仍需 prepared／run-policy 后单独确认启动，下一次若仍不正式完成则达到连续两次停止讨论条件。此为一次试点的显式预算授权，不修改默认值或自动批准余次预算。

真实工作流由独立本机 worker 进程承载，使用单独任务目录和经过筛选的环境；不能继承 shell 的全量环境或从 `.env` 自动装载配置。启动者须显式提供 `--task-image`（固定镜像 digest）和 `--enable-agent`，两者缺任一项时真实运行能力关闭；它们仍不能替代页面中针对具体任务的运行确认或用户对真实试点的另行授权。任务 provider 配置仅从启动者显式设置的 `MOKIO_TASK_API_KEY`、`MOKIO_TASK_MODEL`、`MOKIO_TASK_BASE_URL` 三个进程环境变量取得，不回退到旧 `API_KEY` 等环境变量或项目 `.env`。旧 CLI/TUI 仍可沿用旧入口，但任务 worker 必须显式注入这组 provider 设置，并使所有 graph 节点和 CodeAgent 的 `create_model()` 调用使用该设置。provider 凭据只留在可信服务／worker 的内存和受限子进程环境，不进入浏览器、任务 JSON、日志、trace、命令容器或补丁。网页任务禁用 web search，默认关闭原始 trace/checkpoint；只由任务投影器保存白名单摘要。任务开始前展示模型标识、可传输范围及请求数／token 上限；实际费用依 provider 计费而变，界面不把 token 上限称为固定金额。缺配置或预算不足时不调用 provider。服务与 worker 不输出这些环境变量的值。

每次工作流尝试有独立 `attempt_id`（同一 `task_id` 下从 1 单调递增），Public Event 固定带 `task_id/attempt_id/sequence/timestamp`；准备等任务级事件的 `attempt_id=null`。仅 verifier 对当前补丁给出明确未通过、且尚未达到 `max_attempts` 时自动进入下一次 attempt；下一次**沿用当前 work**，不从 baseline 重置，这与现有修复反馈循环一致。provider 异常、基础设施／工具执行失败、审批拒绝／超时、取消和总时限到达均终止运行，不自动重试；planner 节点不私自开启新 attempt。预算跨 attempts 累计。attempt 切换时先作废旧 attempt 的全部待决和已批准但未消费的命令请求，旧批准不能在新 attempt 使用。真实试点重新启动一个新 Task 才能重试上述终止类故障。

所有 Agent shell 命令及 planner/verifier 提出的验证命令都经过同一个 `TaskCommandGateway`。网关构造不可变 `ExecutionRequest`：`task_id`、`attempt_id`、`command_request_id`、完整命令 UTF-8 字节、容器内 cwd、超时、镜像 digest、固定 `network=none`、仅 work 目录挂载策略、环境允许列表策略、CPU／内存／PID／输出限制及策略版本。命令字节在固定字段顺序的规范 JSON 中以标准 base64 表示，其余字段也使用固定类型与编码，整体取 SHA-256 `execution_digest`；用户批准的是此请求的一次性 digest，执行前重算完全一致才可运行。正则风险分类只作提示，绝不是安全放行条件；CLI `auto` 模式在网页任务中禁用。批准请求一旦因取消、超时、attempt 更替或终态失效，不能恢复或复用；两个看起来相同的命令也必须分别批准。用户指定的验证命令仍需在运行前作为任务策略确认；模型生成的新命令不得自动执行。

现有 Click 冻结预检把 `src/mokioclaw/tools/*.py` 与 `graph/architectures.py`、`graph/workflow.py` 的当前字节纳入身份哈希。阶段 B 的网页任务因此通过独立 `dashboard/task_executor.py`、任务工具包装器与任务图适配层注入命令和文件能力，不修改这些冻结哈希文件，也不让 `approval_mode="task"` 的 `RuntimeState` 进入旧 Bash 实现。真实任务路径必须在测试中证明 Bash 与 verifier 均使用任务网关；旧 CLI/TUI 的原有入口与冻结预检保留。

执行器只把 work 目录挂入受限容器；不挂载来源仓库、baseline、用户主目录、Docker socket 或 provider 凭据。默认 `--network none`、非特权用户、只读根文件系统、资源与输出上限、无后台命令、超时后强制清理容器。镜像以固定 digest 选择并记录。现有评测 `DockerCommandExecutor` 可以参考参数，但必须经本阶段独立审计与测试；Docker 不可用或边界不达标时，任务可预览而不能运行。worker 是受信任的本机进程，不宣称能抵御其自身被攻陷；本阶段的隔离主张限定为模型可调用的工具与命令不能访问来源树或宿主私有路径。

Docker 仅隔离命令，不使宿主 Python worker 的文件工具自动安全。Web Task 定义三种互不混淆的 scope：`source_read_scope` 是 work 内已准备源码可读取的文件／目录前缀；`source_write_scope` 是 work 内允许修改、创建、重命名目标和删除的范围，第一版与 read scope 相同；`task_scratch_scope` 固定为 work 内 `.mokioclaw/task-scratch/`，只放 notepad／临时 Agent 数据，不进入源码补丁。baseline、来源仓库、其它 Task 根目录都不属于任何 scope。将来若支持不同的读写范围须先修订契约。

所有 Web Task 的宿主 FileRead/FileWrite/FileEdit/Grep/Search/Notepad 与上下文枚举统一经 `TaskFilesystem`，不能由各工具自行解释路径。它拒绝绝对路径和 `..`，规范化相对路径并核对 task 身份与对应 scope；对读、写、新建、重命名两端、删除、递归遍历和 scratch 操作，**每次访问时**检查全部路径组件，不穿过 symlink、Windows junction 或其它 reparse point。先前一次 `Path.resolve()` 不能代替此检查：即使命令刚把 work 内目录换成链接，后续宿主工具也必须拒绝。实现需防检查到打开之间的替换竞态；若当前 Windows 文件 API 无法可靠保证，就对该操作 fail closed，不能宣称已形成完整文件系统沙箱。Docker 命令只见 work，可能修改其中任何文件；命令后由可信扫描与补丁收集拒绝超出 write/scratch scope 的变化，不能把容器挂载说成逐文件写权限。

命令容器的网络默认关闭，任何依赖下载或外部服务的验证均返回明确“未运行／边界禁止”，而非测试失败。命令批准不会放宽挂载或网络策略。取消与总超时按 §4 的清理顺序终止 worker 及全部归属容器，迟到事件不改变终态。

## 7. API、页面与事件投影

2026-10-04 具体设计／测试计划待审：本轮独立草案保存在主项目 `D:\MokioAgent\MokioAgent\docs\superpowers\specs\2026-10-04-mokioclaw-task-codeagent-context-design.md`，适用代码仍为本实施树033fedb及原十一项修改，不混用主项目旧设计授权。推荐task-only确定性整理＋有版本的文件／内存结果续读；96／72／48KiB规范输入字节门、8／16KiB正文／JSON、100行默认、32MiB内存结果库、ToolResultReadTool与固定task_context_limit_exceeded类别均为待审提案。保留任务／固定验证要求、两组完整AI→Tool、最近失败、JSON与参数原样；必要内容超硬门明确失败，上游已丢弃命令输出明确不可恢复。12组离线测试计划含provider初始化／网络／真实执行禁止断言，本轮没有执行新探针或产品回归。先审阅草案，再编写实施计划与确认离线执行范围；不设收尾保留量、不提高总门、不消费boltons／Task10额度、不恢复真实试点。交接§54／进度§93记录本轮实际边界，后续原文是历史时点。

2026-10-04 上下文／收尾诊断完成与文档接续：获准的无provider诊断12项假模型探针通过，确认CodeAgent内部messages追加并重送，图层monitor在planner结束后才运行且没有收到内部工具历史；任务FileReadTool只有行数门，长行仍可返回大量正文。三组对照累计正文279063／96818／697257字符而图层均估830；65.3%下降不等于真实token或费用节省，不倒推真实重复读取轨迹。自测后通常还需摘要／planner收束／verifier判定调用，阶段共用门没有收尾保留量；正式命令先于verifier模型执行，零verifier调用须联合回执／结果判读。现有产品行为与总门未改。用户随后仅要求整理文档和新会话prompt，下一会话先审阅task-only内部上下文限额／历史整理及正文窗口／长行续读设计，再审议同一总门内收尾余量；具体产品修复与阈值／新试点／Docker仍未批准。保留tool_call_id配对、错误反馈、范围／审批／固定验证／usage停止与普通CLI行为，不扩大原文留存。接续入口D:\MokioAgent\MokioAgent\docs\MOKIOCLAW_NEXT_SESSION_BRIEF_2026-10-04.md；真实结果／诊断／整理分别见交接§51–53与进度§90–92。预算上限仍300000／24，boltons一次已用完，Task10余2次保留且停止讨论。本次没有重新运行探针或产品回归，下列测试数字仍是各轮历史证据。

2026-10-04 boltons独立对照实际结果：用户在49485的Task Z-oFwxjR4UXv0jt7-3_fJTYQ prepared后单独批准启动。11调用／150844已报告token时failed／provider_budget_exhausted，正式固定验证not_run；两条CodeAgent原样固定pytest审批均及时，真实receipt先exit1后exit0。助手独立Task测试9 passed、12288组合等独立oracle10 passed，原八测试AST保留，权限赋值语义审阅通过；补丁2文件+64/-0、七处行尾空白仍待整理，未应用。完整工作流仍未正式完成，不能以自测或独立pytest替代verifier正式验证。新一次额度已用完，旧Task10剩余2保留；最新两次真实运行均未正式完成，停止讨论、不自动提高预算或消耗原额度。建议下一步先无provider分析上下文体量与verifier收尾成本，产品修复或新预算／次数仍需具体授权。watcher已退出、worker与归属容器无残留、来源不变；详见交接§51／进度§90／私有boltons-run1-review.md。下段尚未启动为历史授权时点。

2026-10-04 独立开源试点授权：用户批准改用 boltons Issue480 做一次完整链路对照，并批准克隆准备和最多两条无provider容器预检。新来源D:\agent work\project\boltons-mokioclaw-pilot，固定SHA 967864f89791509f9eb36b22b4579d36b72a6df2；新私有根D:\agent work\project\boltons-mokioclaw-private，实际工作台task-root为其tasks子目录。八项显式read=write范围／80098字节／manifest=3ba96496b6d1855ce14b221b0cf299e295ddd5e4acfa74c6013456289637c377；原固定镜像digest和network=none，qwen3.5-flash／150000已报告token／20调用／输出3072／1 attempt／1200秒，仅此一次、不是新默认预算，也不转用Task10剩余2次。两条预检已实际执行并清理：现有八项测试8 passed；私有权限赋值负样本7 failed／3 passed，确认旧实现缺陷存在且独立验收可拒绝，不表示修复通过。旧来源／冻结证据／既有远端不改，新来源检出后身份保持。固定pytest候选为PYTHONPATH=src:. python -m pytest -q tests/test_fileutils.py -p no:cacheprovider --basetemp=/tmp/boltons-fileperms-verify；保留原测试并添加权限赋值回归，verifier必须实际执行此命令。私有说明1149字符，不提供上游修复片段。工作台需用户带原provider配置重启并登记新来源；prepared后仍单独确认启动、助手逐条审批，真实次数尚未使用。本段只更新已批准的外部试点方向，不改产品API或预算／隔离机制。详细交接§50、进度§89。

2026-10-04 第五批第3次实际验收边界：用户在55302恢复prepared后明确“启动”，先接活跃GET-only watcher再单次运行-g／300000／24。19调用／319633已报告token时failed／provider_budget_exhausted，Agent固定验证not_run，独立审阅拒绝补丁；两条命令审批及时处理，没有过期，但原指定pytest未执行，新增write_file API不符合任务目标。已启动3／剩余2，停止讨论获准恢复后连续第1次未正式完成；如下一次仍未正式完成，按原规则先停止讨论。未提高预算、不自动准备或启动余次、不更换说明；后续说明澄清仍需审阅采用，独立POSIX Docker／来源写回／提交／push权限不扩大。实际watcher读取间隔有大于10秒，不能把本次审批均及时当作每≤10秒操作目标或助手失去响应仍可审批的证明。详见交接§48、进度§87。

2026-10-03 第五批恢复准备：监控加固、早测链路离线诊断和-g候选审阅后，用户明确“可以的”，批准采用-g并恢复下一次准备。-g正文3996字符，首次实现后立即自测／修复，再原样补齐五组回归并重测，全部通过后交planner／verifier执行原固定验证；首轮早测不能替代最终五组与verifier验收。不改变产品调度、阶段预算或自动审批。仍为qwen3.5-flash、300000已报告token／24调用／3072输出／1 attempt／1200秒及原隔离范围，五次已启动2／剩余3。此前连续两次失败已停下讨论，本次确认允许恢复准备；新prepared任务仍须单独启动确认，恢复后仍遵守连续两次未正式完成／provider即死停止讨论纪律。启动前确认GET-only watcher进程与心跳，运行中每≤10秒读取并优先逐条审阅命令。本段不授权独立Docker、来源写回、提交或push。

2026-10-03 私有试点监控加固：第五批第二次助手漏接审批后，用户确认新增私有 GET-only 持续 watcher 与离线测试。辅助工具仅观察绑定任务的状态／pending／分页 events、持续心跳并保存脱敏身份与时间／游标，完整命令只供本机即时审阅；不新增产品 API／Public Event 字段、不取得 CSRF、不自动创建／启动／批准／取消任务、不重放旧身份、不延长 120 秒窗口或改变预算。恢复试点须先确认观察进程与心跳活跃，再按原 prepared／run-policy／逐次启动纪律运行，操作期间持续优先处理审批。25 项离线回归、真实审批组件配假执行器、本轮 803 passed 非 Docker 回归及旧终态任务的 GET 连接／私有 checkpoint 落盘已验证；不是新真实运行验收，不能保证助手停止响应时完成决定。第五批仍已启动 2／剩余 3、停止条件未解除；provider／新试点／独立 Docker 及来源写回权限不扩大。

2026-10-03 第五批实际边界：首轮 -f／300000／24 经单独批准，24 次调用／298304 已报告 token 时触发调用门，verifier 0、固定验证 not_run；完整 24 次快照正常发布，补丁语法错误拒绝。第二次经用户“继续”单次启动，24／305889（末次响应可越界）后，因助手未及时处理第二条命令审批，120 秒过期，failed／task_tool_failed；不能归咎 provider。固定验证 not_run，独立固定范围 3 failed／41 passed／2 skipped／2 deselected，十项边界矩阵 5 failed／2 passed／3 skipped／44 deselected，目录替换竞态读出范围外内容，补丁拒绝。授权五次已启动两次、剩余三次保留，连续两次未正式完成已停止，先讨论监控可靠性和任务推进，不自动增加预算或消耗余次。累计 24 次快照获真实验证，单阶段最高仍 20，单阶段 21–24 仍只有假模型证据。本段记录实际验收与授权边界，不改变预算、审批或失败处理语义。

2026-10-03 第五批授权接续：300000／24 离线调整完成后，用户重启工作台至 127.0.0.1:64306 并新增五次真实运行授权。首轮沿用 -e 正文及五组回归，仅新 -f 说明的 token 字段为 300000，调用 24、qwen3.5-flash、3072 输出、1 attempt／1200 秒、原固定验证命令和所有隔离范围保持；prepared／run-policy 后仍逐次确认启动、由助手逐条判断命令审批，连续两次未正式完成或连续两次 provider 即死均停止讨论。五次额度自真实启动计扣，不自动耗尽，不授权独立 POSIX 容器测试、来源写回、提交或 push；本段更新后续运行授权，不改第四批历史账目。

2026-10-03 第 6 次授权接续：预算投影离线修复完成后，用户明确恢复原剩余最后一次，批准 -e／qwen3.5-flash／200000 已报告 token／24 调用／输出 3072／1 attempt／1200 秒及原固定验证命令与隔离范围，并在 prepared 后单独批准启动。该次已运行，17 次调用／205032 已报告 token 时 provider_budget_exhausted，快照正常发布，固定验证 not_run，补丁独立验证与人工审阅拒绝；未达到 21–24 次新增投影区间，不据此宣布该区间真实验收或推断第 5 次历史用量。累计 6 次授权全部用完，后续真实试点仍需新的次数／模型／预算授权，独立 POSIX Docker 门控也不自动获准。本补充记录用户已批准方向及实际边界，不扩大默认预算、失败自动重试或来源写回权限。

保留 V1 只读 API 和 `review-priority-v1` 输出。新增同源接口的建议契约：

| 接口 | 用途 |
| --- | --- |
| `GET /api/task-session` | 返回进程内写操作令牌及执行能力状态，不含凭据。 |
| `POST /api/task-previews` | 验证 repo/base/anchor/范围，返回有时效的预览 ID、范围摘要和阻断项；不建任务副本。 |
| `POST /api/tasks` | 校验预览 ID、规范请求摘要与幂等键，先持久化 `TaskRecord` 并进入 `preparing`，把准备交给独立后台执行器，立即以 `202` 返回 `task_id`；相同幂等请求返回原任务，不等待 Git blob 复制。 |
| `GET /api/tasks/{id}`、`GET /api/tasks/{id}/events?after=N` | 返回脱敏状态、结果与有界事件摘要；轮询，不使用原始 graph 事件流。 |
| `GET /api/tasks/{id}/result` | 清理完成后返回独立的补丁与固定命令验证摘要；不返回完整补丁或原始输出。 |
| `POST /api/tasks/{id}/run` | 独立启动动作；执行门不通过则拒绝。 |
| `POST /api/tasks/{id}/approvals/{request_id}` | 明确批准或拒绝一条当前待决命令。 |
| `POST /api/tasks/{id}/cancel` | 请求取消并返回当前清理状态；可重复调用，客户端随后轮询终态或 `cleanup_failed`。 |

所有写接口检查 Host、精确 Origin、进程内 CSRF 令牌、JSON 类型与大小、仓库／任务身份和状态；不开放 CORS。服务只绑定 `127.0.0.1`。静态页面不用第三方资源，动态字符串只作为文本节点。任务 API 不提供任意文件读取、原始 prompt/response、完整 endpoint/query、headers、payload、完整 stdout/stderr 或下载原始补丁的路由。错误统一为 `code/message/retryable`，不回显路径或工具异常文本。

事件投影只接受固定枚举：准备进度、运行阶段、审批请求／决定、工具结果类别、验证命令结果、补丁统计和终态。每条有 `task_id`、`attempt_id`（任务级事件为 null）、全任务单调 `sequence`、时间和大小上限；原始事件的未知字段直接丢弃，生成的 Public Event 禁止任何非白名单字段，并拒绝非当前 attempt 的事件及序号倒退／重复。原始 graph 事件先在 worker 内投影，不能直接写磁盘或发浏览器。页面显示修改文件、增删行数及经脱敏的有限补丁摘要；完整补丁只存于任务本地受限产物目录，供后续独立人工审阅，不自动应用。验证逐条显示实际命令、批准请求 ID、退出码、耗时、通过／失败／未运行及截断或脱敏说明；不把模型自述当作验证证据。

2026-09-29 Task 10 诊断补充：任务工具在终止性失败前发布 `tool_failure` 摘要，公开字段仅为固定工具身份与固定失败类别，并沿用任务／attempt／序号身份。工具身份只取任务注册表内的固定名称；无法识别时为 `unknown`。失败类别只允许 `invalid_arguments`、`scope_denied`、`approval_denied_or_expired`、`tool_rejected`、`tool_exception`、`unknown`。只依据可信异常类型或完全匹配的内部错误码分类，不复制模型参数、异常文本、文件路径、命令、prompt、工具输出或 provider 信息；内层工具已报告失败时不重复把外层委派工具标为根因。此摘要用于以后受控任务定位，不能倒推之前五次真实试点的失败工具。

2026-09-29 Task 10 provider 诊断补充：真实任务遇到 SDK 异常时，只按异常类型生成固定终态类别：认证或权限为 `provider_auth_failed`，限流为 `provider_rate_limited`，请求格式错误为 `provider_invalid_request`，连接或超时为 `provider_transport_failed`，服务端错误为 `provider_server_failed`，未知异常仍为 `provider_failed`。任务本地的请求次数或已报告 token 预算耗尽为 `provider_budget_exhausted`；缺少可靠用量仍为 `usage_unavailable`。worker 与父进程仅接受这些明确类别，不复制异常消息、响应体、URL 或密钥；预算、重试次数、发送范围与命令审批边界均不改变。分类仅能用于新运行，不能推断旧任务的具体 provider 根因。

2026-09-30 Task 10 阶段预算诊断补充：用户审阅并同意在任务模型包装器中把每次调用固定归属到 `entry`、`chat`、`planner`、`code_agent`、`verifier`、`context_compressor` 六阶段。每阶段只累计**已启动的模型调用数**及响应 `usage_metadata.total_tokens` 中有效的**已报告 token 数**；调用失败仍计一次启动，但不能推断 provider 已接收或计费次数。缺失用量时保留已知部分值，并沿用 `usage_unavailable` 终态；单次响应可使已报告累计值越过预算。worker 在工作流正常结束或抛错时、终态写入前，仅发布一次 `budget_usage` 完整快照：十二个固定数值字段，沿用 Public Event 身份外壳，当前 `attempt_id` 只标识发布时所在尝试，数值跨该任务所有尝试累计。父进程严格校验阶段字段、数值与任务身份，丢弃未知字段；页面只显示这些固定阶段及数值。worker 在快照前崩溃、被终止或未建立任务上下文时视为用量未知，不将缺失解释为零。该诊断不记录 prompt、源码、工具参数与输出、provider 响应／异常文本、地址或凭据，不补填旧运行，也不改变调用预算、范围或审批。

2026-09-30 Task 10 任务提示补充：隔离任务的 CodeAgent 使用单独、简短的系统提示，优先读取任务或规划给出的准确文件路径，在选定范围内尽早编辑已有文件并运行相关检查；`FileWriteTool` 只改写已有文件，待办状态在确有变化时更新，不要求每个编辑动作前后重复调用。普通 CLI/TUI 继续使用原 CodeAgent 提示。此提示调整不改变工具注册、读写范围、命令审批、provider 预算或重试规则；先由无 provider 假模型测试和全项目回归验证，再用于新的真实任务。既往预算耗尽只是提出这项改进的观察，不能证明提示是其根因。

创建新任务开始时，页面立即解除旧任务 ID 与运行清单、结果、事件、审批的绑定，作废旧轮询响应并从 URL 移除旧 ID。新任务记录必须匹配当前仓库、固定提交及历史锚，才能绑定并加载其清单。创建响应不确定时保留原请求幂等键，先核对任务状态再考虑重试；浏览器控制超时也先核对是否已创建或启动，不盲目重复操作。

2026-09-30 Task 10 编辑诊断校正：任务版 `FileEditTool` 在待替换文本不存在或不唯一时返回固定内部码 `task_edit_match_failed`，公开只归为既有的 `tool_rejected`；真实路径／文件访问拒绝仍返回 `task_file_access_denied`，公开归为 `scope_denied`。内部码不携带路径、片段、匹配次数或源码，公开事件字段和类别集合不变。该分类不能回溯旧任务，也不改变任何失败即终止、预算或权限边界。

2026-09-30 Task 10 试点修复补充：三次聚焦 Grep 的真实试点（交接 §20）暴露两个工作流语义缺陷，经用户指示修正。(1) **补丁收集与运行时噪声**：`collect_patch` 的扫描把 `__pycache__/`、`.pytest_cache/` 目录和 `*.pyc`／`*.pyo` 文件视为运行时噪声，在 baseline 与 work 两侧对称排除——它们不计入范围外变更、不进入补丁，也不影响限额计数；其他任何范围外新增或改动仍整体 `patch_unavailable(change_outside_write_scope)`，fail-closed 语义不变。命令容器创建参数固定注入 `PYTHONDONTWRITEBYTECODE=1`（执行器固定策略层，与只读根文件系统同级；不改变 `ExecutionRequest` 摘要字段，不含宿主环境值）。以缓存目录命名的符号链接／reparse point 仍按既有链接拒绝规则处理。(2) **编辑匹配失败改为可重试**：任务版 `FileEditTool` 的 `task_edit_match_failed`（old_text 不存在或不唯一）不再是终止性失败——该固定错误作为普通工具结果返回给模型供其修正后重试，公开投影沿用既有 `tool_result` 的 `failed` 状态，不发布 `tool_failure`；`task_file_access_denied`、审批拒绝／过期、异常与其余失败类别仍终止运行，`tool_failure` 摘要保留给终止性失败。预算、范围、审批与公开事件字段白名单均不变。任务 CodeAgent 提示补充：小文件优先用 `FileWriteTool` 整文件重写；`FileEditTool` 的 old_text 必须逐字唯一匹配且不带行号前缀。下一轮真实试点的 token 预算建议按设计上限 100000 由授权明确；本轮不启动任何真实运行。

2026-10-02 Task 10 试点修复补充（续）：新一批试点第一轮已批准命令实测暴露第三类可恢复信号被误判为终止性失败——命令在隔离容器内实际执行并以非零退出码结束（例如模型转录的测试代码含语法错误导致 pytest 收集失败），网关返回 `ok=False` 但结果携带 `exit_code`/`stdout`/`stderr` 且无 `error` 字段；此类结果是模型迭代所需的标准输入，不再终止 attempt，作为普通工具结果回传（公开投影沿用 `tool_result` 的 `failed` 状态）。网关级失败（`invalid_task_command`、`task_workspace_mismatch`、`task_executor_failed`、`task_receipt_failed`、审批拒绝／过期等，均带 `error` 字段）仍终止并发布 `tool_failure`。独立只读容器复现确认执行器本身工作正常；同轮实测同时验证了容器级 `PYTHONDONTWRITEBYTECODE=1` 注入有效（执行 pytest 后 work 目录无字节码缓存）。本轮亦不启动真实运行（该结论由已授权试点得出）。 同批第三轮试点另暴露 worker 侧通道校验缺口：模型给 Bash 提供非法参数（如把任务总时长当作命令超时）时，`RemoteTaskGateway` 原样把 `command_request` 发给父进程，父进程消息校验失败会使整个任务以 `worker_failed` 收场。现要求该代理在发送前执行与父进程网关一致的参数校验（命令编码与长度、超时 1–600 秒、输出上限 1–12000），同类参数错误在 worker 本地返回 `invalid_task_command` 并作为可重试的工具结果交还模型；网关其余失败类别仍终止。 第五轮试点再暴露同类问题的最后一种形态：模型幻觉出未注册的工具名时，三个分发点（planner、codeAgent、verifier）都把它当作终止性失败。现统一改为：`unknown tool:` 错误作为普通工具结果回传模型（未执行任何操作、无副作用），不发布 `tool_failure`；已注册工具的真实失败保持原语义。

## 8. 失败处理与验收

预览过期或源码范围在准备前变化时要求重做预览。base 不可达、Git 缺对象、含不支持路径、任务根落在来源仓库内、Docker 不可用、provider 未配置、审批超时或拒绝、worker 崩溃、容器超时、输出过大、`workspace_limit_exceeded`、`patch_unavailable`、补丁含 symlink／秘密疑似内容，都保留明确类别并禁止自动升级到下一动作。准备失败必须清理或隔离未发布的临时副本；不能把部分副本标为 `prepared`。执行资源清理失败保持 `cleanup_failed`，阻止新运行并保留归属标识供 reconcile；不提前发布 `cancelled` 等终态。脱敏器无法确定是否安全时隐藏该字段，不输出原文。关闭浏览器不取消已运行任务，但也不批准等待中的命令；等待达到期限后默认拒绝。

验收分五级：

1. **契约级**：假执行器与临时 Git 仓库证明异步创建立即返回、状态机、幂等、active task 的 `409 task_busy`、跨仓库隔离、CSRF／Origin、attempt 与迟到事件、错误结构和 V1 API 不变。
2. **隔离级**：恶意路径、symlink／junction／reparse、命令后链接替换、rename/delete/递归搜索、跨任务与 baseline 越界、Git 配置、环境变量、磁盘软上限、网络参数、命令逃逸、容器超时与取消的假执行测试；来源 refs/index/工作树和 ignored 夹具字节前后相同。取消／超时／崩溃与完成竞态、残留容器、重启 reconcile、`cleanup_failed` 和终态后 work 不再由 Agent 改动都须覆盖。
3. **真实 Docker、无 provider 沙箱门**：在用户另行允许本机 Docker 测试后，以临时仓库和测试镜像实际运行无 provider 的命令容器，验证固定镜像 digest、network none、仅 work 挂载、非特权与资源限制、来源和 baseline 不可见、取消／超时后容器停止移除，以及残留资源 reconcile。只有参数级假 Docker 测试时明确记为未过此门。
4. **界面级**：两仓库、固定 SHA、范围预览、快速返回的准备、审批拒绝／批准、取消、`cleanup_failed`、补丁及验证摘要的真实回环页面验收；窄屏与键盘可用。
5. **真实试点级**：前四门均通过后，用户另行授权具体仓库、provider、预算与次数；记录真实结果和失败类别，不与 Rich/Click 冻结成绩混算。

实现有代码变化时，用 `D:\envs\codeagent\Scripts\python.exe`、显式 `PYTHONPATH=src` 和每次新建的独立 `--basetemp` 跑相关及全项目 pytest；运行 Ruff、`git diff --check`、目标产物秘密格式扫描和冻结哈希只读核对。旧正式槽位不补跑。任何发现都不能以修改冻结 Rich/Click 分析或 ignored 实验证据来“修复”。

网页任务的 `TodoWriteTool` 可记录模型提出的待办与验收条件，但验证命令只取任务创建时确认的固定清单。模型省略该参数、传空列表或提出其它命令，都不能更换清单或因此使有效的待办规划失败；任务若未指定固定验证命令，清单保持为空。普通 CLI/TUI 的规划工具契约不变。

## 9. 阶段划分与权限门

| 阶段 | 交付 | 进入下一阶段的门 |
| --- | --- | --- |
| B1 任务契约与预览 | 任务模型、状态机、固定 SHA 范围清单和预览身份 | 跨仓库／过期预览、路径阻断和状态迁移测试通过。 |
| B2 固定提交与副本 | 独立 baseline/work、来源不变证明、补丁收集 | 路径／symlink／缺对象／超限测试通过。 |
| B3 假执行页面、受控执行与审批 | 异步任务 API／页面、无 provider 假执行器、worker、命令网关、容器执行策略、取消／超时 | 页面端到端可审阅，未批准不执行；假 Docker／假工作流测试通过。 |
| B3.5 真实 Docker、无 provider 沙箱验收 | 获准后在临时仓库运行无 provider 容器，检查挂载、网络、权限、清理及来源不变 | 实际容器证据齐备；未获 Docker 测试授权时标记未通过，不能进入真实试点。 |
| B4 完整 CodeAgent 接入 | 显式 provider 注入、`TaskFilesystem` 全工具约束、完整工作流、脱敏投影、结果页 | 无 provider 假模型测试与全项目回归通过；真实按钮仍受能力门控制。 |
| B5 真实试点验收 | 用户另行批准的有限运行与审阅记录 | B3.5 与 B4 均通过且明确授权后启动，不构成旧评测补跑或自动写回。 |

用户已授权按本设计逐步实施阶段 B 代码，并要求先提交、推送既有改动。真实 Docker 隔离验收、provider 调用、真实 Agent 任务、后续远端修改和发布仍分别遵守独立权限门。如实现中改变隔离、数据范围或审批语义，应先更新本文件与实施计划。

## 2026-10-04 任务内部上下文接续增补（修复前历史验收；最终结果见下节）

用户“批准调整”后，从任务5接续，保留96／72／48KiB、原预算／16轮／planner与verifier／attempt路径。现在任务CodeAgent在每次内部调用前实际替换有界历史，锁内按真实绑定schema与调用选项再次检查，完整锚点基线≥48KiB明确拒绝，非法工具组或不能容纳整组最小反馈在第一项工具前停止。单ToolMessage完整规范JSON≤16KiB、整组首屏≤32KiB；最终源码窗口才贡献coverage，已有文件FileWrite要求当前委派／同版本完整证明，同安全句柄写前核对revision；FileEdit仍逐字唯一匹配。

ResultRead只给CodeAgent，不给planner／verifier；结果库仅内存、当前委派，已执行片段才能签发cursor。巨大diff先做私有容量及首屏预留，写失败不公布候选；Bash上游丢尾部明确不可恢复，重跑仍须新请求／审批。已有安全／provider／usage／预算／终止工具／verification_command_failed优先；正常负verdict仍沿图状态，上一attempt的正式回执不抹除。公开只新增task_context_error与固定工具身份，无内部reason／路径／字节／prompt／源码／provider输出字段。

新增实验只使用合成文件／反馈、脚本模型和明确注入的假执行器，封锁provider／dotenv／真实网络／Docker／真实命令；协议新测试为内存帧，审批只对应确切合成请求，不能带入产品。真实图路径观察到缺页写入拒绝→重读同版本完整覆盖→写入→自测exit1→唯一编辑修复→自测exit0→摘要→planner→原固定命令独立请求／回执→verdict。正向12次假模型调用；三个收尾门9／10／11分别挡摘要、planner、verifier。最后一种verifier模型0调用而正式命令已取得第三份回执，不据零调用改not_run。

指定Python、PYTHONPATH=src、无字节码／pytest缓存、仓库外独立basetemp：相关整组287 passed／16.66秒，exit0（mokioclaw-context-22fc7a11a31c4f2db6827207bb587f5e）；全项目非Docker890 passed、3 skipped、35 deselected、169.74秒，exit0（mokioclaw-context-636bec3eb96945fca6fb7661cc37a904）。三项skip为tests/dashboard/test_catalog.py:76及tests/evals/test_grader.py:204、219的symlink创建不可用；35项Docker标记未运行。两组均1条既有Starlette/httpx弃用警告。Ruff --no-cache src tests exit0。以上为修复前历史验收；最终作者自审与修正后回归见下节，不能当作真实模型能力或费用证据。

未解决边界：字节门不等于SDK报文／token／费用；合法TaskSpec可能被基线门拒绝；整理后信息不足仍需重读；覆盖不证明理解／重建正确，POSIX不声称跨进程原子CAS；不可分的超大Grep单项记录可能在只读查找后显式失败；库淘汰不能恢复旧diff或上游丢尾。真实重复读轨迹、逐次token、真实修复成功率及同一总门内交接／verifier保留量仍未验收。没有provider、Docker、真实任务、.env秘密读取、temp.py、旧补丁／来源写回、提交／push／fetch；boltons余0、Task10第五批余2保留，停止讨论不解除。真实恢复／每prepared启动、Docker、来源补丁应用、提交／push和收尾保留量继续分别授权。旧49485地址不作在线保证或运行许可。
当前最终9项schema与实际会话最小胶囊的纯本地校准（6 passed／1.35秒，独立basetemp mokioclaw-context-e0cda26897514c158ffaad03540f7c2a）：短任务B_base=9385、ASCII上限33404；对应最小两组增量1686、预定义保守常见两组25990、独立失败2399；8KiB胶囊变体基线17385／41404，准入域三式成立。CJK／emoji合法上限81304／105254在完整锚点门明确拒绝，真实入口已测零invoke／零写入／零审批。Schema差异与实际胶囊字段使数字不同于旧停门记录，旧81314／105264与2 failed不倒改。保守常见组来自固定100×60码点窗口／40码点参数／8192字节diff／两路各1024字节反馈，独立于真实模型分布；实际首屏还受完整ToolMessage及组配额。原8KiB胶囊增长、语言／转义、绑定／调用选项与硬门±1均有离线断言，不承诺费用下降。

## 2026-10-04 任务内部上下文最终离线验收与作者自审

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

## 2026-10-06 合并前主项目说明保留（历史）

以下两段原为旧主目录与实施树并行期间的接续说明，只保留历史事实，不覆盖顶部主线统一说明与已经完成的实施状态。

> 2026-10-04 最新接续记录：本文件是较旧历史基线，当前实现仍以阶段B工作树完整设计及其最新增补为准。用户批准收尾七项计划后已完成离线实施／作者自审；相关381 passed，非Docker977 passed／3 skipped／35 deselected，Ruff通过。详见主项目独立收尾设计§10、计划最终记录和实施树交接§60／进度§99，不据本文件旧参数或旧“提交／推送”文字恢复授权。原总门／固定验证／审批保持，无provider／Docker／真实试点或预算提高，无来源应用／提交／push／fetch；禁止子agent，boltons余0、Task10第五批余2保留，真实恢复与每prepared启动继续单独确认。

2026-10-04 实施树接续说明：本文件保留主项目较早设计基线。阶段 B 工作树 C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent 中的同名设计记录了后续获批调整；该树当前任务预算取值上限为24调用／300000累计已报告token／4096单次输出，默认值及下一次调用检查语义不因本说明改变。旧段落的20／100000是历史初版上限；取值上限不是新试点授权。最新boltons试点只获一次150000／20／3072，已用完，正式验证not_run；Task10余2次保留且真实运行停止讨论。上下文／收尾离线诊断已完成，产品修复尚未批准。本次仅整理文档；接续资料及授权边界见 docs/MOKIOCLAW_NEXT_SESSION_BRIEF_2026-10-04.md、主项目瓶颈顶部，以及阶段B交接§51–53／进度§90–92。新任务仍须完整阅读实施树当前设计并重新核对Git与任务策略。
