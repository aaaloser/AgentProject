# MokioClaw 本地工作台 CodeAgent 接入设计（阶段 B）

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

> 2026-10-04 最新接续记录：本文件是较旧历史基线，当前实现仍以阶段B工作树完整设计及其最新增补为准。用户批准收尾七项计划后已完成离线实施／作者自审；相关381 passed，非Docker977 passed／3 skipped／35 deselected，Ruff通过。详见主项目独立收尾设计§10、计划最终记录和实施树交接§60／进度§99，不据本文件旧参数或旧“提交／推送”文字恢复授权。原总门／固定验证／审批保持，无provider／Docker／真实试点或预算提高，无来源应用／提交／push／fetch；禁止子agent，boltons余0、Task10第五批余2保留，真实恢复与每prepared启动继续单独确认。

> 日期：2026-09-28（Asia/Shanghai）
> 状态：用户于 2026-09-28 指示按本设计逐步实施；provider 调用与真实 Agent 试点仍需单独授权
> 前置基线：`2026-09-26-mokioclaw-local-repository-review-dashboard-design.md` 与本地工作台 V1
> 目标：固定提交 → 独立任务副本 → 受控 CodeAgent 工作流 → 人工审阅补丁与验证证据

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

2026-10-04 实施树接续说明：本文件保留主项目较早设计基线。阶段 B 工作树 C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent 中的同名设计记录了后续获批调整；该树当前任务预算取值上限为24调用／300000累计已报告token／4096单次输出，默认值及下一次调用检查语义不因本说明改变。旧段落的20／100000是历史初版上限；取值上限不是新试点授权。最新boltons试点只获一次150000／20／3072，已用完，正式验证not_run；Task10余2次保留且真实运行停止讨论。上下文／收尾离线诊断已完成，产品修复尚未批准。本次仅整理文档；接续资料及授权边界见 docs/MOKIOCLAW_NEXT_SESSION_BRIEF_2026-10-04.md、主项目瓶颈顶部，以及阶段B交接§51–53／进度§90–92。新任务仍须完整阅读实施树当前设计并重新核对Git与任务策略。

可信准备器只用受控、只读 Git 参数枚举 base SHA 下的树对象，并仅对批准范围内的普通 blob 读取内容；不对整个仓库执行 checkout、archive 或 clone。路径大小写折叠后排除文件名 `.env`、前缀 `.env.`、后缀 `.pem`／`.key`、文件名 `id_rsa`／`id_ed25519`／`credentials.json`／`secrets.json`，以及路径段 `.git`／`.mokioclaw` 和本项目的 `evals/reports/` 冻结证据目录；ignored 与未提交文件本来不在提交树中，也不读取。路径规则不能证明其它文件不含秘密，用户仍须审阅批准范围。预览只用树元数据，不读取 blob 内容或秘密值。

第一版上限为：路径选择最多 100 项、普通文件最多 5,000 个、单文件最多 4 MiB、复制总量最多 64 MiB、任务描述最多 4,000 字符、预览有效期 10 分钟、单任务总运行时间最多 30 分钟、单命令最多 600 秒、最多 3 次 Agent 尝试、预先指定的验证命令最多 10 条。provider 预算由用户对每项任务明示，取值上限为 20 次请求、累计 100,000 个已报告 token、单次最多 4,096 个输出 token；下一次调用前检查已知用量，达到阈值即停止。provider 未报告用量时停止并记为 `usage_unavailable`；最后一次调用可能使累计量越过阈值，不能将此机制表述为严格费用上限。超限在预览或准备阶段给出固定错误，不截断后继续执行。

第一版对 Git symlink、gitlink／submodule、非普通文件、Windows 不可安全表示的路径、大小写折叠冲突、路径穿越、过大单文件／总量和 Git LFS 指针一律拒绝或从范围中排除并明确提示；不得静默复制不完整内容后继续运行。每个写入路径在创建前及写后都校验仍位于任务根内。准备后复算 `manifest_digest` 并保存清单；可信补丁收集器只比较此固定 baseline 与 work，不依赖来源树工作状态。新增文件也必须是任务目录内、写入范围内的普通文件，符号链接和越界文件不能进入补丁。

来源仓库在准备前后只读记录 HEAD、refs、index 摘要和工作树状态。预览 base 为 A 后，即使来源 HEAD 前进到 B，只要仓库根身份与 A 的对象／清单仍一致，任务仍只准备 A；页面提示 HEAD 变化而不替换 base。来源目录被移动、仓库身份被替换、base 对象或 blob 在准备中丢失、Git 读取超时／截断、范围不完整都阻断准备。真实任务不扫描或哈希 ignored 私有文件；临时夹具验收另行对 ignored 证据文件做字节级前后比较。

可写 work 在执行期另设**软边界**：最多 5,000 个普通文件、总普通文件字节数 128 MiB、单文件 8 MiB。可信控制器在每次命令前后及执行中的有界周期扫描 work；超限即停止该命令／任务并走资源清理，记录 `workspace_limit_exceeded`。补丁收集遇到超限、symlink 或不可安全读取文件时返回 `patch_unavailable`，不读取／展示半截补丁。Docker 的 CPU／内存／PID 限制不限制宿主 bind mount 磁盘占用；周期监测不能阻止两次采样之间的瞬时增长，因此它不是文件系统硬配额，真实试点须在启动前确认 task-root 所在卷有足够空间或另有卷配额。

## 6. 执行、审批与 provider 边界

真实工作流由独立本机 worker 进程承载，使用单独任务目录和经过筛选的环境；不能继承 shell 的全量环境或从 `.env` 自动装载配置。启动者须显式提供 `--task-image`（固定镜像 digest）和 `--enable-agent`，两者缺任一项时真实运行能力关闭；它们仍不能替代页面中针对具体任务的运行确认或用户对真实试点的另行授权。任务 provider 配置仅从启动者显式设置的 `MOKIO_TASK_API_KEY`、`MOKIO_TASK_MODEL`、`MOKIO_TASK_BASE_URL` 三个进程环境变量取得，不回退到旧 `API_KEY` 等环境变量或项目 `.env`。旧 CLI/TUI 仍可沿用旧入口，但任务 worker 必须显式注入这组 provider 设置，并使所有 graph 节点和 CodeAgent 的 `create_model()` 调用使用该设置。provider 凭据只留在可信服务／worker 的内存和受限子进程环境，不进入浏览器、任务 JSON、日志、trace、命令容器或补丁。网页任务禁用 web search，默认关闭原始 trace/checkpoint；只由任务投影器保存白名单摘要。任务开始前展示模型标识、可传输范围及请求数／token 上限；实际费用依 provider 计费而变，界面不把 token 上限称为固定金额。缺配置或预算不足时不调用 provider。服务与 worker 不输出这些环境变量的值。

每次工作流尝试有独立 `attempt_id`（同一 `task_id` 下从 1 单调递增），Public Event 固定带 `task_id/attempt_id/sequence/timestamp`；准备等任务级事件的 `attempt_id=null`。仅 verifier 对当前补丁给出明确未通过、且尚未达到 `max_attempts` 时自动进入下一次 attempt；下一次**沿用当前 work**，不从 baseline 重置，这与现有修复反馈循环一致。provider 异常、基础设施／工具执行失败、审批拒绝／超时、取消和总时限到达均终止运行，不自动重试；planner 节点不私自开启新 attempt。预算跨 attempts 累计。attempt 切换时先作废旧 attempt 的全部待决和已批准但未消费的命令请求，旧批准不能在新 attempt 使用。真实试点重新启动一个新 Task 才能重试上述终止类故障。

所有 Agent shell 命令及 planner/verifier 提出的验证命令都经过同一个 `TaskCommandGateway`。网关构造不可变 `ExecutionRequest`：`task_id`、`attempt_id`、`command_request_id`、完整命令 UTF-8 字节、容器内 cwd、超时、镜像 digest、固定 `network=none`、仅 work 目录挂载策略、环境允许列表策略、CPU／内存／PID／输出限制及策略版本。命令字节在固定字段顺序的规范 JSON 中以标准 base64 表示，其余字段也使用固定类型与编码，整体取 SHA-256 `execution_digest`；用户批准的是此请求的一次性 digest，执行前重算完全一致才可运行。正则风险分类只作提示，绝不是安全放行条件；CLI `auto` 模式在网页任务中禁用。批准请求一旦因取消、超时、attempt 更替或终态失效，不能恢复或复用；两个看起来相同的命令也必须分别批准。用户指定的验证命令仍需在运行前作为任务策略确认；模型生成的新命令不得自动执行。

现有 Click 冻结预检把 `src/mokioclaw/tools/*.py` 与 `graph/architectures.py`、`graph/workflow.py` 的当前字节纳入身份哈希。阶段 B 的网页任务因此通过独立 `dashboard/task_executor.py`、任务工具包装器与任务图适配层注入命令和文件能力，不修改这些冻结哈希文件，也不让 `approval_mode="task"` 的 `RuntimeState` 进入旧 Bash 实现。真实任务路径必须在测试中证明 Bash 与 verifier 均使用任务网关；旧 CLI/TUI 的原有入口与冻结预检保留。

执行器只把 work 目录挂入受限容器；不挂载来源仓库、baseline、用户主目录、Docker socket 或 provider 凭据。默认 `--network none`、非特权用户、只读根文件系统、资源与输出上限、无后台命令、超时后强制清理容器。镜像以固定 digest 选择并记录。现有评测 `DockerCommandExecutor` 可以参考参数，但必须经本阶段独立审计与测试；Docker 不可用或边界不达标时，任务可预览而不能运行。worker 是受信任的本机进程，不宣称能抵御其自身被攻陷；本阶段的隔离主张限定为模型可调用的工具与命令不能访问来源树或宿主私有路径。

Docker 仅隔离命令，不使宿主 Python worker 的文件工具自动安全。Web Task 定义三种互不混淆的 scope：`source_read_scope` 是 work 内已准备源码可读取的文件／目录前缀；`source_write_scope` 是 work 内允许修改、创建、重命名目标和删除的范围，第一版与 read scope 相同；`task_scratch_scope` 固定为 work 内 `.mokioclaw/task-scratch/`，只放 notepad／临时 Agent 数据，不进入源码补丁。baseline、来源仓库、其它 Task 根目录都不属于任何 scope。将来若支持不同的读写范围须先修订契约。

所有 Web Task 的宿主 FileRead/FileWrite/FileEdit/Grep/Search/Notepad 与上下文枚举统一经 `TaskFilesystem`，不能由各工具自行解释路径。它拒绝绝对路径和 `..`，规范化相对路径并核对 task 身份与对应 scope；对读、写、新建、重命名两端、删除、递归遍历和 scratch 操作，**每次访问时**检查全部路径组件，不穿过 symlink、Windows junction 或其它 reparse point。先前一次 `Path.resolve()` 不能代替此检查：即使命令刚把 work 内目录换成链接，后续宿主工具也必须拒绝。实现需防检查到打开之间的替换竞态；若当前 Windows 文件 API 无法可靠保证，就对该操作 fail closed，不能宣称已形成完整文件系统沙箱。Docker 命令只见 work，可能修改其中任何文件；命令后由可信扫描与补丁收集拒绝超出 write/scratch scope 的变化，不能把容器挂载说成逐文件写权限。

命令容器的网络默认关闭，任何依赖下载或外部服务的验证均返回明确“未运行／边界禁止”，而非测试失败。命令批准不会放宽挂载或网络策略。取消与总超时按 §4 的清理顺序终止 worker 及全部归属容器，迟到事件不改变终态。

## 7. API、页面与事件投影

2026-10-04 本轮设计草案已形成：独立文件 `2026-10-04-mokioclaw-task-codeagent-context-design.md` 记录task-only内部上下文／历史整理、正文与结果窗口、修改落点及12组离线测试计划，待用户审阅。96／72／48KiB输入字节门、8／16KiB正文／JSON、100行默认、32MiB内存库、ToolResultReadTool与固定上下文失败类别均为提案，不是当前实现或新授权；无新增实验／pytest／Ruff、provider／Docker／真实任务。审阅后才编写实施计划并确认执行范围。当前实现继续以阶段B工作树同名设计获批增补为准；本草案不改其总门、公开原文边界或试点额度。

2026-10-04 离线诊断记录：12项真实工作流配假模型／假执行器探针确认CodeAgent内部历史对图层监控不可见、长行未受正文上限约束、交接／verifier没有阶段保留量；窗口组65.3%下降是正文字符而非真实token／费用。自测后通常仍有摘要／planner／verifier模型调用，正式固定命令先于verifier模型，不能仅凭零verifier调用判断未运行。用户本次仅要求整理文档和接续prompt，未批准具体上下文限额／历史整理行为或收尾余量策略；下一步先形成设计与测试计划供审阅，不自动提高预算、启动余次或变更公开原文留存边界。阶段B同名设计与私有context-closeout-diagnosis-2026-10-04.md记录完整证据；本段不修改V1数据或现有API契约。

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
