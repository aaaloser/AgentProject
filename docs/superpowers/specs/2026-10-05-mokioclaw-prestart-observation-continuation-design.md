# MokioClaw 未执行 Task 的观测文件保留与接续设计

> 2026-10-06 用户验收更新：用户明确将 N1–N4 原生合成文件门判通过，并授权提交、push最近未同步的阶段B相关实现、测试和交接文档；本轮分别同步既有 main 与 codex/mokioclaw-stage-b，不合并分支。旧“无提交/push”记载按各轮历史读取。下一项先制定并审阅全新合成临时根内、无provider/Docker/真实Agent的 AF_PIPE/Tk 长寿命、EOF/关闭和浏览器恢复验收计划，获批后执行；现有服务/原Task/旧观测文件的停止、保留基线与加载绑定，以及真实启动/新额度仍各自授权。私有运行资料、冻结证据和无关未跟踪文件不纳入同步。

> 2026-10-06 当前：既有批准的 Windows 原生合成文件门 N1–N4 已完成，两个测试文件最终42 passed/0 skipped（8.08s），真实目录共享冲突32、junction、三旧文件holder、17绑定故障点和8关闭路径均有证据。相关324 passed/1 skipped（38.90s），全项目1310 passed/3 skipped/77 deselected/1 warning（190.66s），Ruff --no-cache通过。只S三份测试/合成child变更，产品源码保持；完整377映射见M的native-matrix-hashes.json，实际矩阵与失败历史见native-matrix.md。历史完整清单与native-acceptance.md均保留。现场服务/Task状态未核验，AF_PIPE/Tk/浏览器、正常退出后的旧文件保留基线/加载绑定、真实启动和额度仍分别授权；无provider/Docker/现场操作/提交/子agent，旧boltons余0、Task10第五批余2及停止讨论保持。下方旧“基础5项/原生未执行/矩阵待补”均按历史读取。

> 日期：2026-10-05起，2026-10-06收尾（Asia/Shanghai）。状态：方案A七项实施及N1–N4原生合成文件验收完成；现场门未验收。
> 用户选择方案A后“开始实施”/“继续”批准[七项实施计划](../plans/2026-10-05-mokioclaw-prestart-observation-continuation.md)的本地实施；34步骤已完成，直接实施/作者自审，无子agent或提交。
> 最新相关324/全项目1310 passed、Ruff通过，原生42 passed；详见§16及native-matrix.md。§14–15、native-acceptance.md及下方方案形成/审阅轮文字保留为历史；现场服务与真实运行仍独立授权。

> 本次接续审阅修订（2026-10-05）：仍推荐A，补实磁盘fresh读取、Windows相对目录句柄创建、一次性消费时点、锁顺序与退出失败处置。以下§4–8为修订后的待审合同，§11记录本次检查；§1与§10的“本轮”保留为方案形成时历史。没有接续代码、实施计划或接续测试结果。

## 1. 目标与当前事实

保留 Task `nM9uXVzm-80YmpnpzG5ifFsk`、原合同、baseline/work和已有三份观测文件，在加载已完成的绑定修复后，使这个**从未执行的prepared Task**可以建立新的、独立的观测会话。绑定不是运行，不恢复历史模型调用、摘要、评分或审批，不新增真实额度。

本轮重新完整阅读两树根SKILL及其指定V1、阶段B设计；最新实施以阶段B工作树获批增补为准。实时只读结果：

| 对象 | 本轮事实 |
| --- | --- |
| Task record | prepared、sequence=2、execution_started=false；attempt/instance/worker PID与创建身份均null；owned_request_ids和execution_receipts为空；仅两条state事件 |
| 原spec SHA256 | b28b672e77f65e10ab3cbf63d8b8b413a5f637b8120539db8f87bf79acff6977 |
| 原观测目录 | D:/agent work/project/boltons-mokioclaw-calibration-2026-10-04/observations/nM9uXVzm-80YmpnpzG5ifFsk |
| 三份文件 | calls.jsonl=0字节、scores.json=0字节、status.json=100字节；status白名单为schema_version=1、对应Task、valid=false、reason=stream_incomplete |
| 活跃文件边界 | Get-FileHash对三份文件均返回被其他进程占用；本轮没有取得三份现场SHA256，不填空文件推算值，不声称文件已冻结或旧进程已退出 |
| 主项目/阶段B HEAD | 4134081c0a8fc4786aa28b1e33fe060d69ddcfd5 / 033fedbc48b428a221289f227a999c1beed0c5b4 |
| 两来源 HEAD | 原Task10来源4ca74f958301228cb48cb1e9c7d15463fa1d8e74；boltons干净detached 967864f89791509f9eb36b22b4579d36b72a6df2 |

已有代码的NumericJournal用xb独占创建文件；碰撞拒绝正确，不能直接改为追加或覆盖。CalibrationObservationManager只有当前进程内状态，没有可从文件恢复的模型账本或交接正文。TaskService已持有task-root/.dashboard.lock的OS锁，close先关闭观测、协调资源、关闭准备执行器，最后释放锁；复用此锁，不另造PID锁文件或凭时间判断失效。

RepositoryCatalog.from_paths每次生成随机repo_id；原spec/record仍为VM6ft8DoH9aT0feYNsOjl9tM。63711浏览器上下文是新ID JmLeSM0zDXCbSJnTyCr4LXtg；这只是界面上下文，不是现场运行授权。app.js的restoreTaskFromUrl和pollTask严格核对record.repo_id；不能忽略这个检查或改写spec使之迁就新ID。

## 2. 选择比较与推荐

| 选择 | 做法 | 判断 |
| --- | --- | --- |
| A（推荐） | 原三文件原位保留，同Task新增一个独占观测会话子目录；仅显式未执行接续允许 | 原证据位置和字节保持，新旧账本清晰；增加一次接续门和私有元数据 |
| B | 将三文件移动到archive，再在原位置创建新三文件 | 保存内容但改变证据位置，并增加移动失败/持有句柄/部分归档风险；不推荐 |
| C | 原文件追加、重开或清空；依据0字节允许复用 | 无法恢复原内存状态，可能与旧持有者并写或混合会话；拒绝 |

仅换calibration-root或新建Task会改变任务副本/身份，不能满足本次同Task接续目标。A只支持**一次未执行接续**；不是通用运行恢复、历史浏览或自动多会话重试机制。

## 3. 显式入口与默认行为

拟新增三个必须一起使用的启动参数：

- `--calibration-continue-task <task_id>`：只允许绑定该已有Task，禁止绑定其他Task。
- `--calibration-expected-spec-sha256 <64位小写hex>`：启动者从审阅记录指定原spec指纹；产品不能自行计算后当作用户期望值。
- `--calibration-expected-source-root <绝对路径>`：启动者指定经审阅的原来源根；可信路径核对必须与唯一--repo的规范根一致，不以同SHA替代根身份。

三者必须同时有原--calibration-root、--task-root=root/tasks、--enable-agent、固定镜像；只允许登记一个经用户审阅的来源仓库。本次是D:/agent work/project/boltons-mokioclaw-pilot。参数缺一、非法类型/ID/摘要、来源根不符、无原三文件或已有sessions目录均固定拒绝，不降级、不自动准备替代Task。

无接续参数时继续现有目录和独占拒绝，普通CLI/TUI、只读dashboard、非校准任务的行为保持。新参数不选择provider、不增加预算，不从.env读取配置，不启动模型或命令。

这是拟议接口，**当前不能执行带这些参数的命令**。具体命令待实现和离线验收后写入real_test.md；现有命令不足以重绑这个Task。

## 4. 接管与未执行证明

接续入口先验证参数并以§6的只读目录句柄固定既有根及祖先，再取得现有task-root OS锁；锁句柄须核对归属到同一task-root。持锁后先安全枚举并验证目标spec/record，持有只读文件句柄，再构造TaskStore；不能先用其现有glob/read_text路径读取未经验证的记录或让构造器先reconcile。服务锁须在接续配置之前建立。随后在provider配置和观测窗口启动前完成全部接续检查；TaskStore加载后立即全字段交叉核对。无新观测资源的检查失败可关闭检查句柄并释放锁；已有资源时必须按§6关闭顺序确认无写入者，不能在finally中无条件释放。不得删除.dashboard.lock或依据PID、端口、mtime夺锁。旧启动者须另行获准正常停止63711实例；旧manager.close可能写出无效的最终scores/status，这是原生命周期收尾。**以旧持有者结束后由新实例成功打开并持有的三文件为保留基线**，不强求仍为0/0/100。

可信接续检查与绑定/启动按TaskService现有锁串行，要求：

1. 从安全只读句柄分别读取磁盘spec与record，一次读取的原字节同时用于hash和解析；spec≤64KiB、record≤1MiB，超限即拒绝。JSON拒绝重复键、NaN/Infinity、未知字段与类型替代（bool不得作int），再按当前TaskSpec/TaskRecord及事件契约严格校验、复算request_digest和task_id/created_at。spec原字节SHA256须等于显式期望；record的repo/base/anchor/manifest/created_at与spec一致。磁盘record须与TaskStore当前内存record的全部规范字段一致，不能仅检查selected字段或用TaskStore.get()代替磁盘读取。TaskStore.get_spec()可作现有契约交叉检查，但其路径重读也不能代替同句柄hash/解析；_fixed_spec缓存不能证明fresh。
2. state严格prepared、execution_started严格false；attempt_id、instance_id、worker_pid、worker_created_at、failure_kind、verification_status为空；owned_request_ids及execution_receipts为空。record只允许创建准备的state事件，连续sequence、prepared为最后一项，无预算/执行/审批/验证事件。cleanup_confirmed=false是本未执行Task的正常值，不能为接续伪设true。
3. 通过安全目录句柄有界枚举task-root全部直接项（最多1000项，不完整或超限拒绝）；本次只允许.dashboard.lock与目标Task目录。另一Task、未知文件/目录、链接或资源痕迹均拒绝，不读取其他目录中的正文，不自动清理它们。目标磁盘记录和内存集合严格为同一单Task；active/cleanup_failed/非终态执行归属或不可解释资源记录均在configure_agent/reconcile之前拒绝。接续检查不调用Docker，也不证明全机器无容器。检查通过后仍沿原启动流程配置执行能力，保留原reconcile与运行门；风险不能确认时不ready。观察绑定只对该Task有效。
4. 来源为显式登记的唯一根，干净、HEAD/base/anchor与原合同一致；只读Git重新计算选定scope的manifest及blob，不fetch、不读取ignored文件。本次8项/80098字节、manifest=3ba96496b6d1855ce14b221b0cf299e295ddd5e4acfa74c6013456289637c377。
5. baseline/work的选定普通文件均逐字节等于这些blob；baseline恰为清单，work只额外允许.mokioclaw/task-scratch/NOTEPAD.md与HISTORY_SUMMARY.md两个空文件及必要父目录。多余目录也拒绝，不沿用补丁收集的缓存噪声例外。额外文件、改动、链接/reparse、丢失或不完整扫描均拒绝；不重置/修补副本。目录枚举与文件读取须使用§6安全句柄，拒绝上限沿用已获批准备/工作区门，不靠正文截断完成校验。
6. 启动与首次bind前，原观测目录只含三份普通文件，无sessions或未知项。bind成功后start复核只允许本manager持有创建句柄的唯一sessions/session_id，恰有四个约定文件、不可变session.json指纹匹配，不能重新打开磁盘sessions并“恢复”归属。新journal须仍为初始无调用/交接/评分状态、未finalize、无worker bootstrap；原三文件则一直复核原指纹。calls必须0字节；scores允许0字节，或严格既有schema且同Task、indexes=[]。旧status允许严格初始stream_incomplete结构，或既有finalize完整结构：同Task、valid=false、event_count/started_calls/unknown_calls=0、stream_closed=false、cleanup_confirmed=false，reasons为已知非空子集observer_fault/stream_incomplete/cleanup_unconfirmed/record_invalid。未知结构、任何调用/交接/评分/worker结束证据均拒绝，不从空calls补推usage=0。

原status读取≤4096字节、scores≤65536字节，不解析calls正文；calls非空立即拒绝。JSON沿同一严格解析器：schema_version/event_count/started_calls/unknown_calls必须确为int，valid/stream_closed/cleanup_confirmed必须确为bool；初始与finalize两种结构分别要求精确字段集合。reasons非空、无重复、按现有固定排序且只包含上列允许值；空indexes须确为list。原文件无法按拒绝写/删除共享打开、有不兼容持有句柄或身份检查失败即停；兼容只读者本身不证明有风险，也不声称没有任何其他句柄。旧证据错误只显示固定calibration_observation_invalid，不回显路径、内容或异常。

启动检查通过只恢复进程内catalog，不创建sessions、不绑定Task、不ready；启动前记录指纹保留在私有内存。用户显式绑定时再次fresh核对全部条件和原指纹，然后才消费一次性目录资格。start_agent在run_available的镜像检查之前再次fresh核对合同、磁盘/内存record、来源/副本、原证据与新session身份；成功后才调用原controller.start（它会先launch worker再写running）。不能先launch再补检查。spec与旧证据句柄保持到接续结束；record与work源码检查句柄只在检查期间持有，最终检查后必须在同一服务锁内释放，允许原TaskStore原子替换record及worker正常编辑work。真实运行开始后不再要求work等于baseline；本方案不为外部宿主用户提供record/work跨进程原子CAS。

锁顺序固定为TaskService._lock → manager._lock → store/controller短操作。viewer的bind请求须先在父端服务入口取得服务锁，再检查并进入manager.bind；不能从已经持manager锁的bind回调反向取服务锁。EOF/失效不反向调用服务，取消/启动/绑定/关闭按相同服务锁串行。调用Git或有界读取虽在服务锁内，但不持manager锁等待；异步回调只有检查通过且本manager仍有效时才可建立journal。失败永久撤销本manager，旧回调不能重新ready。

## 5. 重启后的仓库ID

只有§4通过，才将这个唯一已核对的RegisteredRepository的进程内ID设为原spec.repo_id，其root/state不变；重新建立本实例RepositoryCatalog和TaskSource，在公开app创建前令TaskService和launcher使用同一catalog。禁止修改record/spec/request_digest、全局固定ID、给任意来源添加旧ID别名或放宽页面校验。

本次接续仅允许task-root存在这一份目标Task持久记录；其他Task即便终态也拒绝，避免把多个旧repo_id与不明来源关系自动迁移。枚举与检查仍按§4处理；本次现场任务根仅有该目标记录。原记录未持久化来源绝对根，不能仅凭旧repo_id证明原根；信任输入是用户审阅的显式预期根与固定blob合同。恰为一个--repo参数且规范根匹配，重复参数去重后只剩一个也拒绝。恢复用新的RegisteredRepository值和新catalog，不原位修改frozen对象或保留随机ID别名；同时替换service.catalog与service.source，launcher在create_dashboard_app前显式取service.catalog。普通启动继续随机ID；相同SHA的另一根不能通过expected-source-root约束。此输入不来自浏览器，不作通用来源迁移。

浏览器仍执行原repo/base/anchor严格检查，用新端口、**原repo_id**和原Task ID恢复链接；不借POST重新创建。该映射不改变V1/API字段或事件，不扩大观测器权限。

## 6. 会话目录、元数据与文件生命期

```text
<calibration-root>/observations/<task_id>/
  calls.jsonl              # 原文件，只读保留
  scores.json              # 原文件，只读保留
  status.json              # 原文件，只读保留
  sessions/
    <服务生成的随机session_id>/
      session.json         # 新会话来源说明，独占创建且不可变
      calls.jsonl          # 新NumericJournal独占文件
      scores.json
      status.json
```

session_id为secrets生成的128位小写hex，仅目录身份，不能由URL/用户路径指定。**一次性资格在用户bind请求中独占创建sessions成功时消费**，不是到ready或worker启动才消费。启动检查不创建它；bind以前无session的启动检查失败不消费磁盘资格，但本实例仍失败、不能自动重试。sessions、其唯一session_id目录及四个新文件均只能exclusive create；已有sessions（含空/部分创建）拒绝。消费后任何失败均保留部分产物并永久not-ready，不能删除、换ID、在新进程重绑或恢复运行；未运行且新会话断开也不获第二会话。本方案不处理人工移除一次性标记的恶意宿主行为。

绑定事务顺序为：服务锁内fresh复核 → 独占创建并持有sessions目录 → 单次生成session_id并创建其目录 → 独占创建session.json并写入/flush/fsync → 创建新journal三文件并刷新初始状态/fsync → 提交manager.task_id与journal归属 → 发既有成功state回复。viewer握手、全部句柄身份与刷新必须通过才ready；任一步失败作废manager并关闭本次资源，不发送accepted=true。先创建session.json使journal部分失败也有归属说明；元数据之前失败则空/半目录本身就是拒绝标记，不另写补救说明。断电后不保证目录项耐久性；磁盘状态不明确即停，不把fsync当作整个目录事务原子提交。

session.json规范JSON≤16KiB，固定字段：schema_version=1、mode=prestart_continuation、task_id、session_id、UTC created_at、expected_spec_sha256、record_sha256_at_bind、manifest_digest、previous_layout=legacy、previous_files（三个固定文件名各size_bytes/sha256）。不写绝对路径、任务正文、源码、工具参数、provider配置/输出、authkey或旧文件正文；没有自由备注。原仓库ID已有spec，元数据不再复制。只记录旧指纹，不将无效旧status改成通过。

NumericJournal增加内部明确的目录目标，默认仍legacy布局；路径由可信构造器提供，不能接受模型或浏览器目录。会话新三文件沿用原数值schema、512×4KiB、scores≤64KiB/status≤4KiB；计数从空内存开始，因为§4已拒绝任何真实执行，不是清零已消费的预算。对账只用新session，原文件不合并、不补记录、不纳入新complete判据。

旧三文件采用现有open_existing的只读、拒绝写/删除共享语义，但不能直接把现有函数当作完整祖先/目录防竞态能力。新增仅供接续的安全句柄单元，先逐层持有并验证既有目录（包含calibration-root祖先、tasks与目标Task、observations与原Task目录），不追随reparse；同句柄核对卷/文件身份、最终路径、普通目录/文件属性。旧文件须单硬链接，拒绝无法取得链接数或身份的对象。读/hash/复核一直走原句柄；不得close后按路径重开，也不修改只读属性或ACL。

Windows新目录与文件选择**相对已验证父目录句柄的NtCreateFile、FILE_CREATE**，每次名字只为一个已校验组件，创建同时返回句柄；目录要求目录类型，文件要求普通文件类型。既有目录句柄拒绝写/删除共享，所有必要祖先及新目录保留句柄，逐层验证后才在其下写内容；不采用Path.mkdir→再次按路径打开的两步替代。新文件写入、截断及关闭均操作创建时返回并验证的同一句柄。函数不可用、结构/选项不兼容、共享冲突、无法验证或刷新失败均拒绝；仅支持本机可验证文件系统，不回退到路径创建。具体ABI与目录选项组合由批准后的计划锁定并经原生无provider门核验；本次没有调用这些API或声称原生能力通过。依据：[NtCreateFile官方参数](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)、[CreateFileW共享及目录句柄](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)。该组合能否支撑本产品是设计推断，须以实际Windows测试确认。

POSIX使用已持有目录fd的逐组件openat/O_NOFOLLOW和mkdirat；创建后同父fd打开验证，未验证新目录前不写内容，替换/身份不明拒绝。不扩大既有TaskFilesystem一般操作能力；新增助手只处理接续的固定目录/文件。OS锁约束合作服务，这些句柄也不构成抵御宿主管理员、已有可写映射或断电的通用沙箱。

新会话通过后新manager仍只绑定一个Task；新private pipe/authkey、空memory/序号和单一journal全部由新进程生成。不复用旧bootstrap、评分或交接；IPC既有schema与身份不增加session字段，隔离由新认证通道及捕获该manager的回调提供，测试旧通道/回调不能污染新实例。元数据和所在目录给报告提供session归属，不能凭Task ID把不同目录拼账。现有viewer序号长寿命修复和交换失败永久关闭保持。

EOF先撤销ready/valid，清交接内存；只有新session可收尾写入，旧三文件继续只读持有。关闭顺序固定：服务锁内禁止新bind/start → manager停止并撤销回调写权限 → 新journal收尾、封口并确认句柄关闭 → 关闭连接/listener/viewer并确认所有可能写journal的线程已退出或永久失去写资格 → 原worker资源reconcile/准备器停止 → 同旧句柄最后核对hash → 关闭旧文件及目录保护句柄 → 最后释放lease。manager.close的现有0.1秒join、吞掉close异常和TaskService.close的finally释放lease不能作为这一确认的证据，接续模式须补充可核验关闭结果及失败分支。无法确认时保留lease与保护句柄、执行能力关闭并返回固定错误，由启动者审阅；不提前宣称干净退出。进程被强杀时OS最终释放句柄，后续仍按持久sessions标记拒绝，不自动恢复。

没有实际end/usage时新status仍无效，不把未运行观测收尾记完整；原三文件从成功接管至关闭字节不变。会话失败后不重绑；一旦Task曾running/execution_started=true，即便provider_calls=0也不符合本方案。

## 7. 修改落点与实施顺序

| 单元 | 拟修改/新增位置与责任 |
| --- | --- |
| 显式配置 | 阶段Bsrc/mokioclaw/cli/app.py、dashboard/launcher.py：成对参数、明确预期来源输入、先锁/校验再启动窗口/原provider能力；launcher复用接续后的catalog |
| 可信接续校验 | 新dashboard/task_observation_continuation.py：有限读取、fresh合同/未执行/来源与副本证明、旧文件句柄/指纹、新目录及只读元数据；不初始化provider/Docker |
| 安全文件与目录 | 新dashboard/task_observation_handles.py：仅固定接续路径的目录身份、祖先持有、Windows相对句柄独占创建及同句柄读写；默认TaskFilesystem不扩权 |
| 服务接线 | dashboard/task_service.py：现有lease身份及服务锁内接续、catalog/TaskSource一致、磁盘/内存一致、bind/start检查和关闭失败保锁；保留原运行门 |
| 记录加载 | dashboard/task_store.py：接续只用已通过安全读取的目标记录初始化，避免检查后再glob/read_text读入新插入的未知记录；默认加载分支保留。具体接口见实施计划Task3 |
| journal/manager | dashboard/task_diagnostics.py：显式内部新目录、只绑定指定Task、持有接续证据、单会话生命期；默认独占拒绝不变 |
| 回归 | 新tests/dashboard/test_task_observation_continuation.py，既有test_task_diagnostics.py、test_task_diagnostic_viewer.py、test_task_api.py及launcher/CLI测试：真实组件配合成文件/假边界 |

先做接续校验/文件保留单元，再接manager与身份映射，最后CLI/启动流程与全回归；每个单元先失败断言再实现。实际内部接口签名和逐条命令在设计批准后的实施计划锁定，不在本轮写产品代码。core/agent、提示、provider SDK、公开事件/API、冻结tools8/图2均无需改；若需要扩大这些范围先回设计审阅。

## 8. 拟议测试矩阵（本轮未执行）

新增离线测试仅合成Task/spec/blob、临时目录、假模型/执行器、内存通道/假listener及假UI；sticky禁止provider初始化、dotenv/秘密读取、网络、真实命令、Docker、真实AF_PIPE/Tk。来源blob/状态在新测试用注入假Git reader，不执行真实Git命令；误触即失败，即使异常被吞掉也记录失败。

| 测试组 | 必须证明 |
| --- | --- |
| 默认兼容 | 无接续参数维持原独占碰撞拒绝；普通CLI/TUI/只读dashboard不产生session；参数缺一/错误根/无enable拒绝且provider配置提取0次 |
| 正常接续 | 原0/0/初始status与正常close后的空indexes/final status均可接受；同Task/spec/baseline/work不写；新三文件及session.json独占创建；只有显式viewer绑定后ready |
| 未执行门 | execution_started=true但0调用、running/终态、残留attempt/instance/PID/请求/回执、执行事件、另一active Task逐项拒绝；不改record、不发worker/命令 |
| 合同/副本 | SHA256或request_digest不符、record/spec不一致、预算/命令/scope变化、来源dirty/换根、缺blob/manifest差异、工作区改动/额外文件/非空scratch都拒绝；不重置副本 |
| 原文件内容 | 非空calls、未知schema/字段/Task、有效完成status、非空indexes、过大/坏JSON/缺文件/读失败都拒绝；不把非法旧内容复制到错误/日志 |
| 文件保留 | 原三个文件在bind/poll/score/finalize/close及每个失败路径SHA256一致；新输出只在新session；不append/reopen/write/truncate/rename/delete原文件 |
| 锁及并发 | 两服务同root只有持锁者可配置；祖先/锁身份换位拒绝；service→manager锁顺序覆盖同时bind/start/EOF/close，无反向锁死；关闭异常/延迟线程仍不能写或释放lease；不删除锁文件或依据PID超时夺锁 |
| 路径与创建 | 根祖先/各目录/原文件/sessions的symlink/reparse与硬链接、父句柄身份替换、每步返回句柄错位、FILE_CREATE碰撞、IO/fsync/半创建失败；新文件不能在未验证目录写入；旧文件同句柄hash，not-ready且无随机重试 |
| 一次性 | 启动不创建session；bind的sessions创建即消费资格；每个后续失败点/断开/退出/新进程均拒绝第二会话；已有空/部分/完整sessions拒绝；不同Task/同进程重复绑定拒绝，不以新session规避用量门 |
| 仓库身份与页面 | 恰一--repo/仅一持久Task；重复参数、同SHA异根及任意第二记录拒绝；新RegisteredRepository/catalog使service/source/app同对象，随机旧ID无别名；原URL同Task恢复，wrong repo/base/anchor拒绝，app.js保持；普通catalog仍随机 |
| 通道及生命周期 | 新manager/auth通道仅自己的回调；旧bootstrap/错误Task/instance/attempt/重放/跳号/过期评分拒绝；长寿命、EOF撤销ready、摘要清除、journal资格和现有容量门保持 |
| 真实图离线接线 | 沿真实start前门与TaskRunContext配假组件，证明观测绑定本身无claim/invoke；单次后正常数值/交接/正式请求回执/对账只进新session，原总账七槽/1.25/usage缺失/审批/固定验证不变 |
| 隐私 | 合成敏感哨兵不入session.json/数值文件/公开API/事件/日志/异常；查看器无run/cancel/审批能力；旧正文不加载 |

获批实施后指定Python D:/envs/codeagent/Scripts/python.exe、显式PYTHONPATH=src、-B/PYTHONDONTWRITEBYTECODE=1、pytest禁缓存，每次独立--basetemp在所有Git库外。相关组和全项目非Docker、Ruff --no-cache、两树diff、有限秘密格式扫描、10冻结源码/7报告/4诊断/7旧Task hash、四仓HEAD/本地引用/两来源index及新实现指纹均重新核验，报告skip/未覆盖。已有1134 passed是前次绑定修复证据，不能登记为接续实现验收。

原生Windows锁/句柄/管道/窗口调度与创建替换竞态如假对象无法证明，单列现场门，不能凭假测试通过解除。需要无provider原生现场检查时先列明动作及边界，另行确认；不能用真实模型调用探测接续。

原生无provider文件门必须在合成临时根逐项验证：相对父句柄创建同时返回正确句柄；目录改名/删除/改reparse被保护；旧文件写/替换拒绝；持有目录时正常创建子文件与journal写入可用；任何先存可写句柄导致接管失败；各失败点遗留目录使第二进程拒绝；关闭异常/迟到线程与lease释放顺序。假API可覆盖调用契约，不能替代这些OS结果。原生门未批准或不通过时，可完成离线实现审阅，但禁止现场接续与宣布Windows竞态验收。

## 9. 获批后的现场接续流程和停止门

1. 先审阅本设计，再审阅具体实施计划；本会话直接实施、作者自审、不使用子agent。离线验收完成前不重启63711、不操作现有文件或Task。
2. 向启动者告知需要加载新代码，经允许正常停止旧工作台及旧窗口，等待原服务退出。保存退出后的三文件只读size/hash和无效状态；读失败/仍持有/异常状态即停，不删除文件或强夺锁。
3. 新命令用指定Python、阶段B源码、原来源、新根/tasks、原镜像和显式接续参数启动；在lease/fresh检查后恢复原repo_id，展示空原生窗口。原三文件保持，用户再次显式绑定同Task，新session建立。运行策略继续原qwen3.5-flash、150000/20/3072/1 attempt/1200秒，不增加预算或次数。
4. 只读核对新端口、实际源码指纹、同Task合同/目录/原repo ID、新session、viewer长寿命与故障门；原文件hash保持。不伪造数值、评分或worker握手来证明真实就绪。
5. 真实恢复与新增boltons一次额度、最多两次额外无provider容器检查、该prepared Task启动分别确认后才执行其获准动作。每次命令按原请求独立审批；正式固定命令仍先于verifier模型，自测不能替代正式回执。
6. 新会话完整性、交接质量、正式完成、功能交付仍分别判定；第一轮结束即报告并停。会话/身份/源/保护证据/审批/usage/预算任何门失败即按原纪律停止，不自动再开Task/session、不提高预算。

本次设计不授权上述现场动作。旧boltons已用1余0，Task10第五批已用3余2保留；连续未正式完成后的停止讨论状态不解除。63711不是在线保证或运行许可。观测接续不会提高模型修复质量，也不承诺token/费用下降。

## 10. 方案形成轮实际验证与下一步（历史）

本轮未执行新实验、pytest/Ruff、产品模块或真实命令；只读取源码/文档、Git状态和白名单JSON/哈希。对2026-10-05绑定修复清单重新核对361份src/tests、21保护资产、7旧Task资产，均0缺失/0变化；来源index仍boltons29affec1be6aeb08c5ea35f6bc2c48a19974edfd3df231b9f0bca4723f9e35c8、旧源80809046112c918d18367aefeb36a318a39bd5e8ec764d00178b539e1ada1bf4。四仓status/HEAD/本地heads-remotes实时读取，既有修改保留，不fetch/改配置；Git用户ignore不可读提示保持。

尚未验证：三份活跃观测文件SHA256、旧持有者退出、原生安全创建/锁/管道和新会话接线，以及真实usage/交接/正式完成/维护功能/费用/Docker。§8全部是测试计划。下一步需要用户审阅A方案的同Task单次会话、显式合同/来源门、原位文件保护及原repo_id恢复，再形成具体实施计划。无provider/Docker/真实任务、新额度、.env秘密读取、temp.py/旧audit、旧补丁整理/应用、来源/冻结证据写入、提交/push或远端更改。

文档收尾实际核验：两树git diff --check均exit0；10个明确文档/白名单目标全文有限私钥/凭据格式、冲突标记及行尾空白扫描0命中/0缺失，精确.gitignore例外命中新增设计。四仓最终status/HEAD/本地heads-remotes与本轮开始相比，主项目仅多本设计未跟踪条目，其余状态逐字保持（既有dirty文档内容已更新）；361/21/7清单再次0变化/0缺失，Task仍prepared/sequence2/execution_started=false、spec指纹不变。没有新pytest/Ruff或运行时验收；有限格式检查不是完整秘密审计。

## 11. 2026-10-05 接续设计审阅修订与本次实时检查

用户交接要求先核对资料/现场并审阅设计，书面设计批准后才写计划，计划批准后才实施。本次完整重读主项目和阶段B各自根SKILL与两份指定设计，再读本设计、校准§16–17、交接§68–69、进度§107–108、主项目最新摘要/瓶颈及绑定修复计划/real_test末尾。全程本会话直接、无子agent。

审阅发现并已在待审合同中修订六处：

1. TaskStore.get返回内存，get_spec按路径重读；改为有界严格磁盘读取、同句柄hash/解析、全字段与内存比较，不能用缓存证明fresh。
2. 现有open_existing只处理已有文件，没有安全目录创建；选择独立接续助手、Windows相对父句柄FILE_CREATE与目录身份保护，实际ABI/文件系统效果须另过原生无provider门。
3. 明确bind创建sessions即消费一次性资格，启动不消费；半创建/失败/断开后无第二会话。start允许并复核本manager自己创建的session，拒绝磁盘重载session。
4. 明确服务→manager锁顺序，避免bind校验回调反向取锁；spec/旧文件持续保护，record/work检查句柄在原合法写入前释放，不承诺外部用户原子CAS。
5. 现有manager.close只join 0.1秒、部分close异常被吞，service.finally总释放lease；接续模式必须证明无迟到写入者才释放旧句柄与lease，失败保锁而非报告成功退出。
6. 只支持恰一来源参数、task-root仅一份目标记录，catalog/service/TaskSource/app统一恢复原ID，不自动迁移不明其他记录。

方案A可继续进入用户设计审阅，但Windows原生可行性仍有明确验收门，不能在本轮宣称已解决竞态。原位独立会话仍优于移动归档/原文件重开；预算、范围、审批、七槽/1.25、上下文门与固定正式命令不变。

本次真实只读结果（不是接续产品测试）：

| 对象 | 本次核验 |
| --- | --- |
| 四仓HEAD | main 4134081c0a8fc4786aa28b1e33fe060d69ddcfd5；stage 033fedbc48b428a221289f227a999c1beed0c5b4；旧源4ca74f958301228cb48cb1e9c7d15463fa1d8e74；boltons 967864f89791509f9eb36b22b4579d36b72a6df2 |
| 本地heads/remotes | 两实现树各4条、旧源5条、boltons16条，实际读取完整引用；未fetch。来源index仍分别29affec1be6aeb08c5ea35f6bc2c48a19974edfd3df231b9f0bca4723f9e35c8及80809046112c918d18367aefeb36a318a39bd5e8ec764d00178b539e1ada1bf4 |
| 工作树 | main完整status 8805条、stage 51条、旧源1条未跟踪文档、boltons0条；保留pytest旧目录/.zcodeignore/temp.py及stage既有两个%SystemDrive%未跟踪条目，不读取或清理它们。Git用户ignore不可读提示保持 |
| 接受的实现指纹 | source-test-hashes.json SHA256仍98ae4961897cbd51475bb8db6385ec6a66aa77fe1d11611caf9d4493f9813cd3；361源码/测试、21保护、7旧Task资产均0缺失/0变化，清单未覆盖 |
| 当前Task | prepared、sequence2、execution_started=false；attempt/instance/PID/创建身份为空，owned_request_ids/execution_receipts为空，仅两条准备state事件；spec SHA256仍b28b672e77f65e10ab3cbf63d8b8b413a5f637b8120539db8f87bf79acff6977 |
| 合同与副本 | 直接从磁盘JSON复算request_digest匹配；只读Git树复算8文件/80098字节及manifest匹配；baseline/work共16份源码与固定blob逐字节相同，baseline无额外文件，work仅上述两份空scratch文件。此次读取未导入产品模块 |
| 原观测 | 三文件仍0/0/100字节，status无效stream_incomplete；Get-FileHash三次均ReadError、未取得现场SHA256，没有推算替代值。目录无sessions |
| 63711现场 | netstat只读显示127.0.0.1:63711 LISTENING、PID35508。Get-NetTCPConnection查询有错误，不用其空列表推断服务退出；未读取进程环境/完整命令行，监听不证明运行模块指纹或观测ready |

没有产品代码/新测试/实施计划、pytest/Ruff、原生创建探针、provider/网络模型调用、Docker、服务关闭/重启/重绑、Task启动/命令审批、新额度、来源或冻结证据写入、提交/push。旧118/1134只作前次绑定修复证据。旧boltons余0、Task10余2和连续未正式完成停止门保持。

下一步请用户明确批准修订后的书面设计；随后只编写具体实施计划，仍须审阅离线执行范围和原生验收门。旧持有者退出及旧文件保留基线、Windows原生句柄/锁/目录效果、现场长寿命/EOF/关闭、实际模块来源、worker握手/逐次usage/交接/正式完成/费用均未验收。文档收尾检查另记在本节末，不借用§10历史结果。

本次文档收尾：四仓HEAD、全部本地引用及完整status的计数/摘要与检查开始一致（main8805、stage51、旧源1、boltons0；已dirty文档内容更新不增加status条目）。两树git diff --check均exit0；10个明确文档/既有.gitignore目标全文有限私钥/凭据格式、冲突标记、行尾空白扫描0命中/0缺失。矩阵计数器首次误计表头/分隔行导致断言失败，校正计数规则后确认13组、exit0；不是接续产品测试。既有精确.gitignore白名单仍有效，本次不新增或修改白名单。361/21/7清单最终再次0变化/0缺失、清单文件SHA256及两来源index保持。Task最终仍prepared/sequence2/未执行，spec指纹及0/0/100观测大小保持；旧文件hash未取得，不称冻结。已同步两树阶段B设计顶部、主项目摘要/瓶颈/校准与real_test、实施树交接/技术进度；没有实施计划或产品验收结果。有限格式扫描不等于完整秘密审计。

## 12. 2026-10-05 方案A批准与具体实施计划（计划形成时历史）

用户选择推荐A并要求编写实施计划。已按writing-plans形成七项顺序计划：安全句柄、严格接续证明、安全记录加载/仓库身份、单次绑定/journal、执行前fresh与关闭屏障、CLI启动、完整离线接线/回归。计划保留原位旧文件、同Task一次session、service→manager锁顺序与关闭失败保锁；Windows ABI/相对创建选项已落入计划，效果须另过原生合成文件门。接续TaskStore只用已验证记录初始化，防止预检后普通glob读入未知新增记录；这是安全加载的实现细化，不放宽准入。

本轮只读再次核对361/21/7指纹均0变化/0缺失，四仓HEAD/本地引用/完整status及两来源index与上轮一致；Task仍prepared/sequence2/未执行、两state事件、空执行身份/请求/回执，spec指纹保持，旧三文件仍0/0/100且无sessions。本轮未重新尝试旧hash/读取旧status正文或检查监听，旧占用失败/端口记录仅为上轮历史。计划仅文档，不是接续代码或测试成绩；没有pytest/Ruff、原生探针、provider/Docker、服务操作、Task启动、新额度、来源/证据写回、提交/push/fetch或子agent。

下一步审阅具体实施计划并批准七项本地实施/离线范围；原生Windows文件检查、AF_PIPE/Tk现场、正常停止旧持有者/重启/重绑、真实恢复及新增boltons额度/额外容器检查/prepared启动继续分别确认。旧boltons余0、Task10余2和停止讨论门保持。

本轮文档收尾：七任务/34未执行步骤/13矩阵组核对通过，11个明确文档/白名单目标0缺失、有限格式/冲突/行尾空白0命中，两树diff --check exit0，精确计划白名单有效。四仓最终HEAD/全部本地引用保持，完整status仅M新增本计划条目（8806/51/1/0），旧dirty保留；361/21/7指纹最终0变化/0缺失，旧ledger/两来源index/目标spec保持。新计划按作者自审修正相关节点数量、明确元数据嵌套字段、关闭新session句柄顺序及单列原生合成锁子进程；没有独立代理审阅或产品验证。有限格式检查不等于完整秘密审计。

## 13. 2026-10-05 七项实施完成与离线验收（当前）

用户批准七项本地实施后，代码及176项新离线测试已在既有阶段B树S完成，M只更新计划/设计/状态与独立ledger；源与文档用apply_patch编辑，无子agent或提交。安全句柄、严格磁盘/副本证明、verified TaskStore/原repo_id、一次性session与新journal、start两次fresh及API更早门、关闭失败保锁和三个CLI参数均已接线。作者自审修正缓存bool/float、短期close失败、初始化后半异常、跨目录文件cap、Windows转换所有权与POSIX身份失败释放，未处理阻断项0。

最终相关324 passed/1 skipped/1 warning（37.82s，exit0）；全项目1310 passed/3 skipped/40 deselected/1 warning（186.01s，exit0），Ruff --no-cache通过。5原生文件测试未选/未执行，另35 Docker排除；symlink skip与既有httpx弃用warning保留。新测试sticky边界保持；全套既有受控Git/回环夹具不等于零子进程/零网络。完整命令、实际版本、13组node ID、失败修复历史及三项裁决/代价见主项目 .superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/verification.md。

旧361项仅S的7项计划内变化，其余354保持（包含M产品/测试167项）；21保护/7旧Task0变化0缺失、旧ledger保持。新增8 Python及marker纳入最终376条两树清单（M167+S208+marker）；起始361/21/7与最终清单独立保留。四仓HEAD/本地引用、两来源index保持，完整status8806/62/1/0（S起始51），旧dirty保留。本轮未核验旧三文件hash/当前端口进程，旧0/0/100、prepared和63711/PID是历史，不作当前冻结/在线证明。

Windows实际NTFS/句柄/跨进程lease原生门仅编写，AF_PIPE/Tk长寿命/EOF/关闭、实际浏览器、旧持有者退出后的保留基线及加载/同Task绑定、真实恢复/usage/正式完成/费用均未验收。没有现场服务/Task/provider/Docker操作、新额度或远端变更。下一步先另行批准原生合成门，之后现场恢复、新boltons一次额度/额外无provider容器检查/prepared启动继续分别确认；不发布现场执行命令。旧boltons余0、Task10第五批余2及停止讨论保持。

实现细化：/run增加接续专用precheck，避免既有run_available早于start_agent越过image边界；服务仍在image前后各fresh、先关闭record/work临时句柄再launch。初始化factory/reconcile失败同样关闭保护并最后释放lease，未确认则保锁。工作区cap跨目录累计；Windows转交后失败不双close，POSIX创建身份失败关闭新fd并复核父句柄；未确认保留引用。三项裁决与代价：手工ledger需人工核对；API门多一次只读证明；内存ASGI不证明真实浏览器/middleware。13矩阵实际node见独立 [verification.md](../../../.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/verification.md)。

## 14. 2026-10-05 原生合成文件门获批与首次失败

用户“继续下一步，我批准了”批准上一轮单列的五项原生合成文件验收，不扩展到现场服务、旧Task、provider、Docker、AF_PIPE/Tk或真实恢复。首次受限执行在全新系统临时根得到4 failed/1 passed（1.55s，exit1，无skip）；四项在pin_existing固定祖先时失败，跨进程lease/迟到写入测试通过不能替代整门结论。运行前376实现指纹与21保护/7旧Task资产均保持。

同边界合成诊断确认：C:\和C:\Users的原生打开及NTFS/身份检查成功；C:\Users\lyf打开返回Win32 5（访问被拒绝），新建的合成临时目录用相同访问/共享参数可打开，失败释放已取得句柄且cleanup_failed=false。诊断未修改产品或降低其权限/共享要求；访问拒绝与受限执行环境相关目前是待验证推断，尚不能认定产品可行性失败的最终根因。

依“原生可行性失败先修订设计/计划”门，先登记失败，随后只申请在非受限执行环境重跑同一五节点、相同代码/保护参数及sticky边界，使用另一全新临时根；仍仅允许固定合成lease子进程。若审批拒绝、仍失败或出现skip，整门保持未通过并记录具体阻断，禁止借此推进现场恢复。此修订仅区分环境拒绝与产品行为，不改方案A保护合同；历史离线成绩保持。

非受限复测2 failed/2 passed/1 skipped（1.66s，exit1），已越过祖先权限拒绝。相对子文件NtCreateFile返回STATUS_INVALID_PARAMETER（0xc000000d）；同一新合成根单变量比较确认缺少显式SYNCHRONIZE：原0xc0000000失败，补为0xc0100000成功且同句柄write/flush/fsync/read通过。该位为既定FILE_SYNCHRONOUS_IO_NONALERT的必要参数，不增加写/删除共享、删除权限或路径fallback。Microsoft官方NtCreateFile说明该同步选项要求DesiredAccess含SYNCHRONIZE。实施修订仅补此位；已有原生创建节点已在修复前失败，保留RED证据。

原生首节点异常路径未finally关闭已取得的祖先/新目录句柄，可能污染同进程后续节点；锁/迟到写节点独立进程复测1 passed/4 deselected（1.21s）而整组曾失败。先补测试自己拥有句柄/lease的finally释放，再在产品修复前复测定位隔离效果；测试清理不是产品关闭证明，不删除失败根。原生符号链接夹具不可用导致1 skip，仍不判整门通过，不提升系统权限或削弱reparse准入。下一步若需改为本地junction夹具，须在具体方案中说明原生操作、目标限定与覆盖差异。

reparse夹具实施细化：在用户已批准的合成文件门内，符号链接不可用时可尝试同一临时根两个直接子目录之间的junction。唯一新增文件API为DeviceIoControl/FSCTL_SET_REPARSE_POINT及IO_REPARSE_TAG_MOUNT_POINT缓冲区；目录/目标都须为本次系统Temp合成根内普通直接子目录，不接受外部目标、已有reparse或任意命令。不修改权限/Developer Mode/系统配置，不调用mklink或增加子进程，失败仍skip且整门不通过。成功须实际确认reparse属性、pin拒绝，并尝试在已guard的普通目录上设置同根junction而被拒绝。junction覆盖重解析准入/修改拒绝，不伪称符号链接创建能力已通过；保留临时根不删除。

## 15. 2026-10-06 原生基础结果及完整门剩余项（当前）

最终新根原生5 passed（1.37s，exit0，无skip），JUnit记录symlink_winerror=1314、reparse_fixture=junction、guarded_reparse_winerror=32，实际共享冲突而非泛化权限错误。创建修复已有RED→GREEN，测试finally修复单独验证移除跨节点污染。相关324 passed/1 skipped/1 warning（39.52s）；全项目1310 passed/3 skipped/40 deselected/1 warning（189.67s），Ruff --no-cache通过。5原生另跑，非Docker全套仍排除35 Docker和这5项；既有symlink skip/httpx弃用warning保持。首次失败/所有临时根/原生命令、五节点实际覆盖及缺口逐项见[原生记录](../../../.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/native-acceptance.md)。

基础五节点通过不等于原计划完整原生门通过。下一步先补齐同Temp根内各祖先/Task/obs/sessions保护、三旧文件共享holder矩阵、各创建/写/flush/fsync故障后的真实lease接管拒绝、完整新session关闭/旧hash复核/保护释放/lease最后及失败保锁，具体任务N1–N4见既有实施计划。仍只用合成文件和固定锁子进程，不创建现场服务/Agent或真实管道/窗口。用户原生批准持续有效；没有提出重复批准五节点的门。

本轮仅S的task_observation_handles.py与test_task_observation_handles_native.py改变；376条原清单的其余374保持，21保护/7旧Task保持。上一轮完整清单不覆盖，用独立native-source-hash-overrides.json两项覆盖形成当前完整376映射。四仓HEAD/全部本地引用/完整status保持8806/62/1/0，两来源index保持，旧dirty/失败Temp根原位保留。没有当前Task或旧obs正文/实时端口核验、provider/Docker/现场操作/新额度/提交/push/fetch/子agent；历史状态不作当前在线/冻结证明。


## 16. 2026-10-06 N1–N4 原生合成文件门完成

N1–N4沿既有批准完成，最终两个native测试文件42 passed/0 skipped（8.08s，exit0）。八个合成祖先/Task/obs/sessions层级rename/delete/write/reparse修改实际共享冲突32，guard期间相对create成功且旁路无产物；三旧文件分别证明共享只读可接管、share7可写holder拒绝、写/截断/替换/删除拒绝及单硬链接/同句柄hash/最终路径。17绑定故障逐点确认部分布局、消费状态、真实租约排他及正常close后的新owner实际check拒绝；创建之前失败无磁盘标记，已实际创建但未返回handle的异常即使内存consumed=false也由磁盘sessions阻断。

8关闭路径用真实manager.close_confirmed与TaskService.close，服务上下文和pool保持内存边界，无监听/Agent/AF_PIPE/Tk。三个journal写句柄先封口并关闭，再旧同句柄hash，metadata/session/旧保护随后，lease最后。三个新file、metadata、两个新目录close及旧hash证明失败均保锁，第二次close拒绝，固定跨进程child仍取锁失败；迟到线程写入被拒，新文件字节保持。测试故障恢复后的资源清理不当作正常产品关闭重试。底层文件/NTFS/锁为真，Git来源proof仍用受限合成double，不能替代真实来源/管道/窗口验收。

本轮产品源码保持，仅S两测试/child改动加一新原生测试；377有效映射及历史指纹见M的 `.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/native-matrix-hashes.json`，结果/版本/完整命令/失败夹具历史/作者自审/裁决见同目录 `native-matrix.md`。先前final/initial/verification/native-acceptance/native-source覆盖均保留。相关324 passed/1 skipped/1 warning（38.90s），全项目1310 passed/3 skipped/77 deselected/1 warning（190.66s），Ruff --no-cache通过；77=35 Docker+42 native。原生最终JUnit SHA256 `7FD5FF53DDA05BCED711289802078E4CCA9D1E7D626CCB348FD5C46F7343D709`，实际reparse=junction，symlink权限1314未称能力通过。作者自审而非独立审阅，无未处理阻断项。

仅合成文件门通过。下一步独立审阅AF_PIPE/Tk长寿命/EOF/关闭及浏览器的具体受限验收方案，之后现场旧持有者正常退出/保留基线/加载绑定、真实启动/额度继续各自确认。本轮没有读取当前现场Task/旧obs正文、核验监听、操作服务/Agent/provider/Docker或新额度，没有提交/push/fetch/安装/子agent，旧boltons余0、Task10第五批余2及停止讨论保持。

## 17. 2026-10-06 用户判通过、版本同步授权与下一项指示

用户明确“这边先判通过”，接受§16的 N1–N4 合成文件结果；同时要求push最近未同步内容，因此本轮可将相关实现、测试和设计/交接资料分别提交并push到现有 main 与 codex/mokioclaw-stage-b。该授权不允许合并/强推、发布私有运行资料、修改冻结证据或两来源仓库，也不授权现场服务、provider/Docker、真实Agent/Task或新额度。既往各轮无提交/push的记载为历史，本次Git HEAD/引用/index变化仅限这两个实现分支的获准同步。

下一项可直接给出的指示：

> 继续 MokioClaw 阶段B。先完整读取两树根SKILL及其指定设计，制定并审阅无provider的 Windows 原生 AF_PIPE/Tk 与浏览器验收计划：只用全新合成临时根和合成Task，验证认证hello、显式单次绑定、超过原1024 viewer序号门的长寿命轮询、EOF/窗口关闭撤销ready、迟到回调不可写入、关闭失败保锁，以及原repo/task/base/anchor恢复与错误身份拒绝。明确每项实际动作、进程退出/故障处置及证据，计划获批后才执行。不要操作现有服务、原Task或旧观测文件，不调用provider/Docker/真实Agent，不新增额度，不使用子agent；现场正常停止/保留基线/加载绑定和真实启动仍各自确认。

本节是下一项范围指示，不是已批准的管道/窗口/浏览器实施计划。本轮只登记用户验收与同步资料、进行推送前离线检查和版本同步；没有开始下一项现场验收。

本轮推送前独立复核：全项目离线1310 passed/3 skipped/77 deselected/1 warning（196.77s，exit0），原生合成42 passed/0 skipped（7.89s，exit0），Ruff --no-cache通过。全项目3 skip为既有symlink不可用，77排除为35 Docker+42另跑native，1 warning为既有Starlette/httpx弃用提示；原生本次JUnit默认xunit2带26个record_property兼容警告，测试仍通过，报告属性须按实际XML核对，不将警告记为无。377实现、21保护、7旧Task资产及7份既有ledger均无变化，两来源HEAD/status/index保持。有限凭据格式/冲突标记/文件大小检查覆盖M14与S61项；它不是完整秘密审计。未检查或操作当前现场服务/Task/旧观测。
