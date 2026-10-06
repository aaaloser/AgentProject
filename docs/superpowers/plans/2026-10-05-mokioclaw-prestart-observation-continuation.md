# MokioClaw 未执行 Task 观测接续 Implementation Plan

> 2026-10-06 用户验收更新：用户明确将 N1–N4 原生合成文件门判通过，并授权提交、push最近未同步的阶段B相关实现、测试和交接文档；本轮分别同步既有 main 与 codex/mokioclaw-stage-b，不合并分支。旧“无提交/push”记载按各轮历史读取。下一项先制定并审阅全新合成临时根内、无provider/Docker/真实Agent的 AF_PIPE/Tk 长寿命、EOF/关闭和浏览器恢复验收计划，获批后执行；现有服务/原Task/旧观测文件的停止、保留基线与加载绑定，以及真实启动/新额度仍各自授权。私有运行资料、冻结证据和无关未跟踪文件不纳入同步。

> 2026-10-06 当前：既有批准的 Windows 原生合成文件门 N1–N4 已完成，两个测试文件最终42 passed/0 skipped（8.08s），真实目录共享冲突32、junction、三旧文件holder、17绑定故障点和8关闭路径均有证据。相关324 passed/1 skipped（38.90s），全项目1310 passed/3 skipped/77 deselected/1 warning（190.66s），Ruff --no-cache通过。只S三份测试/合成child变更，产品源码保持；完整377映射见M的native-matrix-hashes.json，实际矩阵与失败历史见native-matrix.md。历史完整清单与native-acceptance.md均保留。现场服务/Task状态未核验，AF_PIPE/Tk/浏览器、正常退出后的旧文件保留基线/加载绑定、真实启动和额度仍分别授权；无provider/Docker/现场操作/提交/子agent，旧boltons余0、Task10第五批余2及停止讨论保持。下方旧“基础5项/原生未执行/矩阵待补”均按历史读取。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户指定本会话直接实施、作者自审，禁止子agent及提交；此约束优先于技能的代理审阅和提交建议。

**Goal:** 原位保留旧三份观测文件，使指定的从未执行 prepared Task 可建立一次独立观测会话，并恢复同一 Task 的仓库身份。

**Architecture:** 显式接续参数选择受限启动分支；安全目录/文件句柄、既有 OS lease 和严格磁盘校验共同形成接管门。用户绑定时独占创建 sessions 消费一次性资格，所有新观测写入单一新 session；服务锁串行绑定、执行前复核和关闭，只有写入者已被封口且保护核对完成才释放 lease。

**Tech Stack:** 现有 Python/stdlib、Typer、FastAPI、pytest、Ruff；Windows ctypes/Win32/NtCreateFile，POSIX dir_fd。不新增依赖。新增离线测试用假原生 API、假 Git reader、内存通道和脚本模型。

**Spec:** [已批准的方案A及修订合同](../specs/2026-10-05-mokioclaw-prestart-observation-continuation-design.md)，重点 §3–8。2026-10-05 用户“可以，就依你推荐来选择方案A编写实施计划”批准设计并授权编写本计划；**用户“开始实施”/“继续”已批准七项本地实施，现完成代码与离线验收**。原生现场验收另设门。

## Global Constraints

- 实施位置为 `C:/Users/lyf/.codex/worktrees/mokioclaw-stage-b/MokioAgent`（下称 S）；主项目 `D:/MokioAgent/MokioAgent`（下称 M）只存计划、状态文档、精确白名单和独立实施记录。保留全部 dirty/未跟踪项，不 reset/清理/新建替代工作树。
- 本次目标 `nM9uXVzm-80YmpnpzG5ifFsk`、原repo_id `VM6ft8DoH9aT0feYNsOjl9tM`；spec SHA256 `b28b672e77f65e10ab3cbf63d8b8b413a5f637b8120539db8f87bf79acff6977`。来源 `D:/agent work/project/boltons-mokioclaw-pilot`，校准根 `D:/agent work/project/boltons-mokioclaw-calibration-2026-10-04`，task-root为其tasks子目录；HEAD/base/anchor固定 `967864f89791509f9eb36b22b4579d36b72a6df2`，8文件/80098字节/manifest `3ba96496b6d1855ce14b221b0cf299e295ddd5e4acfa74c6013456289637c377`。这些是本次审阅的输入锚点，不写死为所有接续任务的全局ID。
- 固定read=write范围为 `LICENSE`、`boltons/__init__.py`、`boltons/fileutils.py`、`boltons/strutils.py`、`pyproject.toml`、`setup.cfg`、`tests/conftest.py`、`tests/test_fileutils.py`；固定镜像 `sha256:83ff408c0f9ce6007afbc9b468815ae4fbdde79d7a702e4b7eb5ee21c91a72b2`、network=none。这些不授权现场读取外部文件正文或执行镜像。
- 同一个 Task、原 spec/record/request_digest、baseline/work 保留；旧文件保留基线以旧持有者正常退出、新实例成功打开并持有后为准。不能要求旧 close 后仍为 0/0/100，不能移动、清空、追加、拼账或改 ACL/只读属性。
- 三个参数一起使用：`--calibration-continue-task`、`--calibration-expected-spec-sha256`、`--calibration-expected-source-root`；同时有原 calibration-root、task-root=root/tasks、enable-agent 和固定镜像。恰一原始 --repo 参数，重复后去重仍拒绝；仅一份目标持久 Task。
- spec≤64KiB、record≤1MiB、旧 status≤4096 字节、scores≤65536 字节、session.json≤16KiB；task-root 直接项最多1000。不完整/过大即拒绝，不截断后解析。
- state=prepared、sequence=2、execution_started=false、cleanup_confirmed=false；只有 preparing→prepared 两个连续 state 事件。attempt/instance/PID/创建身份/failure/verification 均 null，请求/回执为空；曾执行但零调用仍拒绝。
- baseline 恰为固定 manifest；work 只额外允许 `.mokioclaw/task-scratch/NOTEPAD.md`、`HISTORY_SUMMARY.md` 两个空文件及必要父目录。多余目录也拒绝，不使用补丁收集的缓存例外。沿用准备门：5000文件、4MiB单文件、64MiB清单；工作区门5000普通文件/128MiB/单文件8MiB。
- 一次性资格在 bind 成功独占创建 sessions 时消费；空/部分/完整 sessions 都阻断下一个实例。session_id 为一次 secrets.token_hex(16) 的128位小写hex；碰撞/失败不换ID、不删除、不恢复、不自动重试。
- 默认 legacy xb 碰撞拒绝、普通CLI/TUI、只读dashboard、非校准任务保持；scope、审批、usage缺失停止、七槽/1.25、96/72/48KiB及现有收尾策略保持。viewer序号1–(2**63-1)、worker1–1024、私有帧409600字节、512条×4096字节、24索引、600秒留存等 IPC 门不扩大。
- 真实候选仍 qwen3.5-flash／150000已报告token／20调用／3072输出／1 attempt／1200秒。新会话不恢复旧预算、正文、评分、bootstrap 或批准；不新增真实额度。固定正式验证仍为 `PYTHONPATH=src:. python -m pytest -q tests/test_fileutils.py -p no:cacheprovider --basetemp=/tmp/boltons-fileperms-verify`。
- 不改 frozen `src/mokioclaw/tools/*.py` 八文件、`graph/architectures.py`、`graph/workflow.py`、来源或冻结证据。不改 core/agent、提示、provider SDK、公开事件/API/schema、app.js身份检查、一般 TaskFilesystem 操作。
- 新离线测试 sticky 禁止 provider初始化/配置提取、dotenv/秘密读取、网络、Docker、真实命令、真实Git、AF_PIPE、Tk；误触即记账，异常被吞掉也失败。既有全项目Git/回环夹具保留，不能把全套回归称为零子进程/零网络。
- 指定 `D:/envs/codeagent/Scripts/python.exe`、显式 PYTHONPATH=src、-B/PYTHONDONTWRITEBYTECODE=1、pytest禁缓存，每次全新 basetemp 放所有Git库之外。源码/文档只用 apply_patch 编辑，不提交/push/fetch/改远端/装依赖。
- 本计划批准仅进入七项本地实施和离线验收；Windows原生文件门、真实管道/窗口门、停止/重启/重绑63711、真实恢复、新boltons一次额度、最多两次额外无provider容器检查及prepared启动继续分别确认。旧boltons余0、Task10第五批余2及停止讨论状态保持。

## Review Focus

1. 合法文件检查后，任务根插入另一record或替换原记录：接续加载不能再走 glob/read_text；Task3 `test_verified_store_never_path_reads`、Task5 `test_start_rejects_fresh_drift_before_image` 覆盖。
2. 旧服务正常close产生空indexes/无效final status，或JSON把bool冒充数字：前者可接管，后者严格拒绝；Task2 `test_legacy_finalize_allowed_strict_types` 覆盖。
3. NtCreateFile已消费sessions，但元数据/第三文件/fsync失败：永久not-ready，遗留阻断下一实例；Task4 `test_each_bind_failure_consumes_once` 覆盖。
4. EOF/关闭与慢Git检查或延迟线程同时发生：无反向锁、无迟到写入/重新ready、失败不得先放锁；Task5 `test_close_barrier_retains_lease`、`test_bind_eof_close_lock_order` 覆盖。
5. 重复--repo、同SHA另一来源、随机catalog旧别名或缓存spec：身份不能偷换，service/source/app必须同catalog；Task3/6对应身份测试覆盖。

## 文件与接口边界

所有相对文件名以 S 为根；文档路径明确以 M 或 S 为根。修改现有类的指定方法，不整文件重构。

| 文件 | 责任 |
| --- | --- |
| 新 `src/mokioclaw/dashboard/task_observation_handles.py` | 仅接续路径的安全句柄、目录枚举、相对独占创建、同句柄读写/刷新/身份；不用 TaskFilesystem 的路径创建 |
| 新 `src/mokioclaw/dashboard/task_observation_continuation.py` | 参数值对象、严格合同/旧文件/源与副本复核、保留基线、一次性session元数据及归属 |
| 改 `src/mokioclaw/dashboard/task_store.py` | 可选已验证记录初始化，接续不glob；默认持久加载保持 |
| 改 `src/mokioclaw/dashboard/task_service.py` | 初始化先锁/核对、catalog同步、viewer服务入口、start前复核、关闭失败保锁 |
| 改 `src/mokioclaw/dashboard/task_api.py` | 作者自审裁决增加接续专用早期precheck，保证/run自身的image检查之前已fresh；默认响应/schema保持 |
| 改 `src/mokioclaw/dashboard/task_diagnostics.py` | 新journal使用显式内部session句柄；两段绑定及封口/关闭结果；默认布局保留 |
| 改 `src/mokioclaw/dashboard/launcher.py`、`src/mokioclaw/cli/app.py` | 分组参数校验、原始repo数量、启动接线与同catalog app、固定错误 |
| 新 `tests/dashboard/task_continuation_fakes.py` | 合成Task/spec/blob、FakeHandleBackend/FakeWinApi/FakeLease/FakeGit、sticky审计；不读现场Task或来源 |
| 新 `tests/dashboard/test_task_observation_handles.py`、`test_task_observation_continuation.py` | 假API契约、严格准入、一次性/磁盘变更/文件保护 |
| 新 `tests/dashboard/test_task_observation_handles_native.py` | 默认跳过的原生文件门，仅合成临时根；另行授权后选择 |
| 新 `tests/dashboard/test_task_observation_continuation_native.py` | 已批准文件门 N1–N4 的参数化实际句柄/lease/故障/关闭矩阵；默认跳过，来源仅FakeGit |
| 新 `tests/dashboard/task_continuation_native_lease_child.py` | 仅供获批原生门启动的固定stdlib合成锁子进程；不会在离线测试或模块导入时运行 |
| 改既有诊断三测试、`test_task_api.py`、`test_task_store.py`、`test_catalog.py`、`test_launcher.py`、`test_cli_smoke.py`；新 `test_task_observation_continuation_flow.py` | 真实组件假边界接线/默认兼容/隐私/生命周期 |
| 改 `pyproject.toml` 的 pytest markers | 只登记 `continuation_native_files`，全非Docker命令显式排除此门 |
| M本计划/接续设计/校准设计/阶段B设计/摘要/瓶颈/real_test；S阶段B设计/交接/进度 | 状态和结果记录；M `.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/` 存新记录，不覆盖旧指纹 |

错误统一沿用 `calibration_observation_invalid`；纯参数组合错误 `calibration_config_invalid`。异常用 `from None`，不向API/终端复制路径、正文或异常文本。新内部类型不进入IPC或公开模型。

## 执行命令约定（本轮已运行离线验收）

在 S 运行，每次测试调用前重新创建 `$continuationCaseTemp`，不存在才用；确认解析路径在系统Temp、四Git库之外。下面命令定义本计划每个 RED/GREEN 步骤的共同参数；将 `<节点>` 换成步骤给出的精确文件/node ID，不把尖括号原样执行。

```powershell
Set-Location -LiteralPath 'C:/Users/lyf/.codex/worktrees/mokioclaw-stage-b/MokioAgent'
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$continuationCaseTemp = Join-Path $env:TEMP ('mokioclaw-continuation-' + [guid]::NewGuid().ToString('N'))
& 'D:/envs/codeagent/Scripts/python.exe' -B -m pytest <节点> -q -p no:cacheprovider --basetemp $continuationCaseTemp
```

RED必须为目标断言失败或尚无接口，夹具/导入环境错误不能冒充行为证据；GREEN要求exit0/0 failed，sticky审计0命中。已通过的旧行为测试不伪记RED。实施前重新读两树根SKILL和完整V1/阶段B设计、已批准spec/本计划；核对现有linked worktree与旧361/21/7指纹，另记本次起始清单。

### Task 1: 安全句柄与可验证的原生调用契约

**Files:** 新 handles模块、两个handles测试文件、continuation_fakes；改pyproject marker。测试辅助模块明确位于 `tests/dashboard/task_continuation_fakes.py`。

**Interfaces:** 定义 `FileIdentity(volume_id: int, file_id: int, final_path: Path, is_directory: bool, link_count: int)` 和 `FileFingerprint(name: str, size_bytes: int, sha256: str)` frozen dataclass。`DirectoryHandle`/`FileHandle` 独占拥有一个已验证 OS handle/fd；`FileHandle.stream: BinaryIO` 使用该handle/fd，转换所有权一次。`ObservationHandleBackend` Protocol：`pin_existing(path: Path, *, directory: bool, writable: bool=False, lease: bool=False) -> DirectoryHandle|FileHandle`、`children(parent: DirectoryHandle, *, limit: int) -> tuple[str,...]`、`create_directory(parent: DirectoryHandle, name: str) -> DirectoryHandle`、`create_file(parent: DirectoryHandle, name: str) -> FileHandle`、`verify(handle: DirectoryHandle|FileHandle) -> FileIdentity`。句柄方法 `read_bounded(limit: int) -> bytes`、`fingerprint(limit: int) -> FileFingerprint`、`close() -> None`，错误不吞掉；`make_handle_backend() -> ObservationHandleBackend` 为平台工厂，测试替换该工厂。

- [x] **Step 1: 写假API失败测试。** `test_relative_create_contract` 断言 `RootDirectory == parent.native_handle`、ObjectName只有一个组件、disposition==2(FILE_CREATE)、返回句柄在任何write前verify；对路径分隔符/../冒号/NUL/尾点空格/设备名断言固定拒绝。`test_open_pin_and_identity_rejects` 参数化根祖先/Task/obs/旧文件/sessions的reparse、符号链接、硬链接、卷或file_id/finalpath不符、已有写入者共享冲突；assert no_write且每个临时handle关闭。`test_directory_enumeration_bounded` 覆盖1000/1001、重复/大小写冲突、UTF16坏长度/NextEntryOffset越界/非8字节对齐、未完成枚举，不用路径scandir作为Windows回退。
- [x] **Step 2: RED。** 节点 `tests/dashboard/test_task_observation_handles.py`；假API与FakeHandleBackend不调用真实DLL、锁或文件探针。
- [x] **Step 3: 实现Windows backend。** `WindowsObservationHandleBackend(*, api=None)` 默认仅在使用时绑定ntdll/kernel32；固定ctypes字段：USHORT=c_uint16、ULONG/ACCESS_MASK=c_uint32、NTSTATUS=c_int32、HANDLE/指针=c_void_p、ULONG_PTR=c_size_t、WCHAR=c_wchar且sizeof==2。UNICODE_STRING/OA/IO_STATUS_BLOCK尺寸在x64为16/48/16，x86为8/24/8；IO_STATUS_BLOCK首字段为status/pointer union。argtypes/restype全部声明，buffer和UNICODE_STRING生命期覆盖调用，异常NTSTATUS/无效handle立即拒绝。

  既有目录逐层CreateFileW OPEN_EXISTING、FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT，access=FILE_LIST_DIRECTORY|FILE_TRAVERSE|FILE_READ_ATTRIBUTES|SYNCHRONIZE、share=READ；持父句柄后核对新handle身份/最终路径/无reparse。现有普通文件GENERIC_READ、share=READ、OPEN_REPARSE_POINT；仅lease文件允许READ|WRITE share并读写打开，身份/单硬链接仍核对。Windows初版只接受可核验本地NTFS卷，UNC/remote/类型或身份不可确认拒绝，不宣称其它文件系统通过。

  新目录NtCreateFile：OA.RootDirectory=已验证parent、OBJ_CASE_INSENSITIVE、FILE_CREATE=2、FILE_DIRECTORY_FILE(0x1)|FILE_SYNCHRONOUS_IO_NONALERT(0x20)、上述目录access、share READ。不把FILE_OPEN_REPARSE_POINT拼入该目录选项；不存在的单组件排他创建返回handle后仍核对属性/identity。新文件：FILE_CREATE、FILE_NON_DIRECTORY_FILE(0x40)|FILE_SYNCHRONOUS_IO_NONALERT，GENERIC_READ|GENERIC_WRITE、share READ、FILE_ATTRIBUTE_NORMAL；返回结果只接受STATUS_SUCCESS且Information=FILE_CREATED。普通文件身份、links=1与最终路径验证后才通过msvcrt.open_osfhandle接管为二进制stream；不能再按路径重开。`children` 用GetFileInformationByHandleEx的FileIdBothDirectoryRestartInfo/Info，从64KiB buffer有界解析到ERROR_NO_MORE_FILES；任何其他错误拒绝。同句柄GetFileInformationByHandle/fstat与最终路径交叉核对，短写/flush/fsync失败立即上报，句柄可用性不能靠关闭异常忽略。

  上述ABI/选项依据[Microsoft NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)、[文件身份API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)、[目录枚举结构](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_both_dir_info)；它们支持选型，产品可行性仍是待原生门确认的推断。
- [x] **Step 4: 实现POSIX backend。** 逐组件dir_fd open/O_NOFOLLOW/O_DIRECTORY；新目录mkdir(dir_fd=parent.fd)后同父fd打开核对，未核对前零内容写入；文件O_CREAT|O_EXCL|O_NOFOLLOW，fstat普通/单链接。目录枚举只使用已持fd，父子身份变化fail closed。不声称POSIX共享锁能阻止任意宿主写入，不扩展TaskFilesystem。
- [x] **Step 5: GREEN及测试边界。** 重跑Task1节点。构造FakeWinApi验证字段宽度、选项/状态、返回handle所有权及读/hash不按路径重开；新增原生文件测试标记 `continuation_native_files`，其autouse fixture在环境白名单开关 `MOKIOCLAW_CONTINUATION_NATIVE_FILES` 不等于 `1` 时skip，DLL/临时文件操作仅在fixture之后执行。固定锁子进程文件只实现 `main(argv: Sequence[str]|None=None) -> int`，--root必须指向本次合成Temp根，只打开其既有.dashboard.lock，stdlib msvcrt锁定后stdout固定locked、stdin只接受release、解锁后stdout固定released；不导入产品/provider、不执行命令正文。主入口才运行，不在import时产生副作用。本阶段只编写及作者自审，原生用例/辅助进程不执行。

### Task 2: 严格接续证明、旧文件保留与session元数据

**Files:** 新 continuation模块、test_task_observation_continuation.py；扩充合成fakes。

**Interfaces:** `ContinuationOptions(task_id: str, expected_spec_sha256: str, expected_source_root: Path)` frozen；`parse_continuation_options(*, task_id: str|None, expected_spec_sha256: str|None, expected_source_root: Path|None, calibration_root: Path|None, task_root: Path|None, enable_agent: bool, task_image: str|None, repo_paths: Sequence[Path]) -> ContinuationOptions|None`。`PrestartObservationContinuation.open(options, calibration_root: Path, task_root: Path, *, backend: ObservationHandleBackend|None=None) -> PrestartObservationContinuation` pin祖先和固定目录，不创建session；`lease_stream() -> BinaryIO`安全打开已有.dashboard.lock；`verify_lease(fd: int) -> None`核对同Task根归属。`check(catalog: RepositoryCatalog, reader: LocalGitReader, *, cached_record: TaskRecord|None, session: ObservationSession|None=None) -> ContinuationCheck` 每次fresh，结果包含spec、record、record_sha256、manifest(tuple[ManifestEntry,...])及短期record/work句柄；`ContinuationCheck.close() -> None`只释放这些短期句柄。spec/旧文件/必要目录由continuation持续持有。`create_session(check: ContinuationCheck) -> ObservationSession`单次消费；`verify_preserved() -> None`、`close() -> None`只读核对后释放。

`ObservationSession`持session_id、DirectoryHandle、不可变session.json句柄及sha256；`create_journal_files() -> tuple[FileHandle,FileHandle,FileHandle]`仅一次固定顺序calls/scores/status独占创建；`verify_layout() -> None`同句柄metadata hash与恰四文件检查；`close() -> None`关闭其剩余自有句柄。journal接管三文件写句柄后session不能重开/重复关闭它们。

- [x] **Step 1: 写准入/漂移失败测试。** `test_strict_contract_and_record` 覆盖重复键/NaN/Infinity/未知字段、bool/int/float替代、边界±1、摘要/request_digest/created_at/Task或repo不一致、内存任一字段漂移；assert固定错误且sessions不存在。`test_never_executed_gate` 参数化running/终态/execution_started=true零调用、attempt/instance/PID/请求/receipt/用量或审批事件/sequence不连续，assert record原字节不变、worker_calls==0。`test_scope_copies_exact` 对假Git dirty/异根/缺blob/manifest差异、baseline/work变动、缺文件/额外空目录或缓存/非空scratch断言拒绝且no_reset；扫描未知目录只取元数据，不读取未知正文。
- [x] **Step 2: 写旧文件内容/类型及保留断言。** `test_legacy_finalize_allowed_strict_types` 接受0/0/初始status和空indexes/无效final status，断言实际旧句柄hash与before一致；reasons须排序、非空、无重复且限定四类。`test_legacy_content_rejected_without_leak` 对非空calls立即拒绝且calls.read次数0；valid完成/评分、未知字段/Task、过大/坏JSON/缺文件/读取失败均固定拒绝。敏感哨兵不入错误、日志、元数据；不将空calls解释为usage=0。
- [x] **Step 3: RED。** 节点 `tests/dashboard/test_task_observation_continuation.py`，FakeGit只接受既有inspect/受控只读Git参数；未注册的参数立即失败，sticky计数在teardown断言0。
- [x] **Step 4: 实现check与严格解析。** 同一安全句柄有界读取原bytes，同时hash+严格json.loads（object_pairs_hook拒重键、parse_constant拒非有限值）。按dataclass全部字段精确校验TaskSpec/Record及嵌套事件/receipt的类型、ID/SHA/UTC时间、既有范围与预算上限；本目标两事件data字段集合恰为state，各为preparing/prepared、attempt=null、seq1/2。规范request摘要剔task_id/created_at复算；canonical(asdict(record))全字段与cache比较。安全枚举task-root只允许lock+目标目录；目标记录加载无需读另一目录正文。经显式根验证的临时原ID catalog，用既有TaskSource.preview复算固定scope manifest、检查无blocked项，再只读cat-file blob并复核OID/大小；前后inspect要求干净且HEAD=base=anchor。按清单路径树及必要父目录扫描副本，拒未知项、链接及不完整枚举；不调用prepare/collect_patch、读ignored或写来源。关闭每次检查的临时资源，保留长期旧三文件/不可变spec句柄与实际指纹。
- [x] **Step 5: 实现一次性metadata并GREEN。** sessions创建返回handle即将continuation标记consumed，单次随机ID；session.json exclusive写规范UTF8/flush/fsync后才允许三journal文件。字段恰为schema_version=1、mode=prestart_continuation、task_id、session_id、UTC created_at、expected_spec_sha256、record_sha256_at_bind、manifest_digest、previous_layout=legacy、previous_files（字典，恰为calls.jsonl/scores.json/status.json三个key，每个值恰为size_bytes/sha256）；≤16384字节、无自由文本/路径/旧正文。失败关闭可确认的句柄但留下目录，不写补救文本。`test_metadata_whitelist_and_once` 断言精确key集合、32位小写hex、旧实际hash、startup零创建及第二调用拒绝。重跑Task2全部节点，记录通过及未测原生边界。

### Task 3: 安全加载与原仓库ID恢复

**Files:** 改task_store.py:__init__；task_service.py:__init__/_TaskRootLease/configure_calibration；新测试及test_task_store/test_catalog。

**Interfaces:** `TaskStore(root: Path, *, verified_records: tuple[TaskRecord,...]|None=None)`；非None分支只建立内存_records/_keys，不mkdir/glob/read_text，校验重复身份；默认保持旧loader。`_TaskRootLease(root: Path, *, stream: BinaryIO|None=None)`复用原OS lock/unlock；接续传Task2安全stream并在锁成功后verify_lease。`TaskService(..., *, continuation_options: ContinuationOptions|None=None, calibration_root: Path|None=None, 原有kwargs)`；`self._continuation: PrestartObservationContinuation|None`在校准manager前保存。`restore_continuation_catalog(catalog: RepositoryCatalog, spec: TaskSpec, expected_root: Path) -> RepositoryCatalog`在continuation模块产生新RegisteredRepository值/new catalog，不改frozen对象；service.catalog与TaskSource.service.source.catalog同对象。

- [x] **Step 1: 写失败测试。** `test_verified_store_never_path_reads` monkeypatch Path.glob/read_text/mkdir记录并拒绝，verified分支应零调用；检查前FakeBackend枚举出现第二Task/1001项即拒绝且unknown正文读取0。`test_service_preflight_order` assert调用顺序pin→lease→verify_lease→strict_check→verified_store→full_memory_crosscheck→catalog/source，store/reconcile/provider/viewer/session在之前均0。检查中插入未知Task，后续fresh枚举必须拒绝，普通loader不能替代verified branch。
- [x] **Step 2: 写身份回归及RED。** `test_restore_catalog_same_identity` assert新catalog.get(spec.repo_id).root==expected_root、随机ID查找None、spec/record原字节不变、service.source.catalog is service.catalog；同SHA异根/任何第二记录拒绝。节点为上述三个测试（新continuation文件）及 `tests/dashboard/test_task_store.py`、`tests/dashboard/test_catalog.py`。
- [x] **Step 3: 改初始化顺序。** 先建立service._lock及关闭状态，再按接续分支pin既有目录（不mkdir）/取得原lease/完成strict check，再构造verified TaskStore；保留校验句柄直到内存全字段比较完成，重枚举根。通过全部源/副本/旧文件门才恢复catalog/source；之后才允许controller_factory或configure_agent沿原reconcile流程。非接续分支保留原能力；接续初始化无manager资源失败可释放检查句柄/保护/lease，不能无条件执行原finally；需保锁的关闭错误走Task5分支。只读预检本身没有Docker操作。
- [x] **Step 4: 实现catalog函数及GREEN。** 只接受catalog中恰一规范根匹配项，new RegisteredRepository(spec.repo_id, old.root, old.state)，不保留旧随机alias；绑定后的launcher必须从service.catalog取对象。上述节点exit0，默认catalog仍随机、默认store仍加载历史记录；not-ready/not-consumed、旧文件hash、记录/副本hash断言都保持。

### Task 4: 受服务锁保护的单次绑定与journal接线

**Files:** 改task_diagnostics.py:NumericJournal/manager.bind/receive_viewer/_start_role；改task_service.py:configure_calibration/新增viewer入口；测试continuation与诊断三文件。

**Interfaces:** `NumericJournal(root: Path, task_id: str, *, session: ObservationSession|None=None)`默认legacy；session时接管Task2返回的三写句柄，初始化status后flush/fsync。`is_initial(self) -> bool`检查空records/scores、未_result/未seal及正常初始文件状态。`ViewerBindReservation(task_id: str, sequence: int, generation: int)`内部frozen。manager增加 `continuation_task_id: str|None`、`viewer_handler: Callable[[dict],dict]|None`可选构造参数；`reserve_continuation_bind(frame: dict) -> ViewerBindReservation`锁内校验并消费合法viewer序号、未绑定/valid/hello/指定Task；`commit_continuation_bind(reservation, session: ObservationSession, journal: NumericJournal) -> dict`锁内复核generation/stop/valid，再提交task_id/memory/journal/session，返回既有state；失败固定拒绝。`TaskService.receive_calibration_viewer(manager: CalibrationObservationManager, frame: dict) -> dict`为父端入口。

- [x] **Step 1: 写正常及默认失败回归。** `test_bind_new_session_only` 用真实codec/manager/journal/服务入口+合成文件FakeBackend；hello/poll不创建，显式bind后state.accepted is True且ready；新session恰四文件，初始calls/scores空、无worker/bootstrap/模型调用，旧三文件和spec/record/workhash不变。`test_default_legacy_collision_still_refused` 无接续仍xb拒绝，普通dashboard无session；直接manager.bind在continuation模式返回False不能绕服务门。
- [x] **Step 2: 写每步失败/一次性回归及RED。** `test_each_bind_failure_consumes_once` 对sessions/session_dir/session.json创建/写/flush/fsync、三journal文件各创建/写/刷新/归属提交逐点注入失败。sessions创建前失败不存在标记，但本manager失效；创建后所有失败留下标记，accepted绝非True/not-ready，第二manager/新服务在startup拒绝，随机生成仅一次，无delete/retry。`test_session_owned_not_disk_reloaded` bind后check只接受本manager原句柄四文件/metadata hash，外来session、改metadata/额外目录、重新打开伪归属均拒绝。节点 `tests/dashboard/test_task_observation_continuation.py -k 'bind or session or once or collision'`。
- [x] **Step 3: 实现journal目标。** session分支不mkdir/Path.open，不使用旧三个文件，使用返回的stream；默认NumericJournal目录/schema/限额不变。metadata先于journal创建；失败尽力关闭但向Task5报告未确认资源。新journal对账只用新数值，不装载旧scores/usage/body；初始化成功需三文件flush/fsync通过。is_initial须同时核对内存空records/scores/无result、同创建句柄calls/scores实际0字节、status恰为本Task初始stream_incomplete结构及未seal；仅内存为空不足以放行。
- [x] **Step 4: 实现两段绑定。** _start_role只在viewer角色调用注入viewer_handler，默认仍receive_viewer。服务入口先检查captured manager is current、未closing，取得service锁；合法bind先锁内reservation，释放manager锁，fresh check+创建session/journal，再manager锁内commit。slow Git/IO不持manager锁；EOF可撤销generation，commit失败不得重新ready。其他viewer帧同服务入口转发现有receive_viewer；旧回调永远不能污染新manager。manager.receive_viewer的continuation bind不自行创建journal或反向回调service。错误帧不消费session，失败回复沿原schema不增加字段。
- [x] **Step 5: GREEN。** 重跑Task4节点及 `test_task_diagnostics.py`、`test_task_diagnostic_ipc.py`、`test_task_diagnostic_viewer.py`；保留长寿命8192poll、viewer/worker序号边界、错误role/重放/跳号/过期评分、交换失败永久失效/EOF清正文。旧文件在bind/poll/score/finalize/失败/close各路径hash一致，未运行close保持新status无效。

### Task 5: 执行前fresh门与关闭屏障

**Files:** 改task_service.py:start_agent/close；task_diagnostics.py:journal写入/close、manager回调/poll_terminal/close；测试continuation、diagnostics、task_api。

**Interfaces:** `NumericJournal.seal_and_close(self) -> None`锁内永久seal后关闭所有自有写句柄，确认失败抛固定错误，emit/_write/set_indexes/finalize迟到调用不能写。`ObservationCloseResult(writers_revoked: bool, journal_closed: bool, channels_closed: bool, callbacks_safe: bool)` frozen，`confirmed`属性要求四项True；`CalibrationObservationManager.close_confirmed(self) -> ObservationCloseResult`为接续分支，旧close兼容入口保留。服务 `_closing: bool`、`_close_failed: bool`、`_closed: bool`状态；失败保有_continuation和lease，禁止新bind/start，不由launcher finally隐式重试或宣称正常退出。

- [x] **Step 1: 写start漂移失败测试。** `test_start_rejects_fresh_drift_before_image` 在startup/bind以后逐项改磁盘spec/record/缓存全字段、来源/manifest/work/scratch、旧文件、session布局/metadata；调用真实service.start_agent，assert image_check_calls==0、controller_start_calls==0、approval/command/model_calls==0，固定拒绝、not-ready，原证据未写。prepared零调用但execution_started=true仍拒绝。`test_start_releases_check_handles_before_launch` 假controller检查record/work短期句柄已关、spec/旧文件/保护/lease仍持有；断言日志fresh1→image_check→fresh2→release_short_handles→controller.start，后者才可能launch，运行后合法work变化不再要求baseline相等。
- [x] **Step 2: 写并发/关闭失败测试及RED。** `test_close_barrier_retains_lease` 注入journal close失败、conn/listener/viewer失败、未撤销写资格的延迟线程、reconcile/pool shutdown失败、末次旧hash不符、session元数据/新目录close失败；assert固定错误、not-ready、lease.closed is False、旧保护仍在，no_clean_exit。成功日志顺序为block_bind_start→revoke_callbacks→finalize_new→seal_close_journal→close_channels_confirm_callbacks→reconcile→pool_shutdown→old_hash_check→close_session_guards→close_guards→release_lease。`test_bind_eof_close_lock_order` 用Event/Barrier使慢FakeGit与bind/start/EOF/close交叠，线程有界join；断言无反向锁，EOF撤销generation后不能commit，关闭后任何迟到数值/评分/terminal回调零写。不得靠真实sleep调度或只检查join(0.1)。节点为上述四测试。
- [x] **Step 3: 接start门。** 在服务锁内先查当前manager初始/指定Task且所有合同fresh通过，才调用原run_available；image检查可能等待，之后在controller.start紧前再fresh和manager generation/ready检查，释放短期record/work句柄后按原controller.start执行。两次proof均显式关闭短期资源，不用_fixed_spec缓存证明fresh。保留原镜像/Docker/worker预算/审批/单active门；任何接续校验失败invalidate当前manager且不launch。
- [x] **Step 4: 实现seal及关闭确认。** 服务锁设置closing后manager锁停止并永久撤销所有写回调，只有新journal按既有usage收尾再seal；关闭连接/listener/viewer后所有线程须已退出或永久不能写journal，不能把0.1秒join视为确认。迟到callback先检查stop/generation/seal，连invalidate/_finalize都不能触发磁盘写。成功结果后才reconcile和pool shutdown；不持manager锁等待线程或Git。未运行保持cleanup_confirmed=false、new status invalid。最后同旧句柄hash核对，ObservationSession.close关闭元数据/新目录句柄，continuation.close关闭旧文件/长期目录保护，再lease最后释放。任一步无法确认保持未确认对象引用、lease/仍可持有的保护，不吞异常；资源已确认释放但证据不一致也保锁报告，禁止自动重试。被强杀后的OS释放不构成恢复资格，sessions仍阻断。
- [x] **Step 5: GREEN。** 四节点及 `tests/dashboard/test_task_api.py`、诊断相关回归通过。核对state/API错误结构、not-ready先于Docker、取消/终态仍沿原控制器；任务执行后不会再用prepared准入覆盖正常状态。关闭确认测试覆盖sealed journal还被延迟线程引用的情况，而非简单清空manager.journal变量。

### Task 6: CLI、启动流程与同catalog页面恢复

**Files:** 改cli/app.py:dashboard、dashboard/launcher.py:launch_dashboard；test_cli_smoke.py、test_launcher.py及continuation测试。

**Interfaces:** CLI新增三个同名Typer可选参数；`launch_dashboard(..., calibration_continue_task: str|None=None, calibration_expected_spec_sha256: str|None=None, calibration_expected_source_root: Path|None=None)`保留既有kwargs和默认调用形状。CLI与launcher均调用Task2参数解析，CLI必须在repos fallback/dedup前核对原始数量。launcher将options/calibration_root传service，校准配置取该service的guard，app创建前使用service.catalog。

- [x] **Step 1: 写参数失败测试。** `test_continue_flags_group_and_raw_repo_count` 参数化所有缺项组合、非法Task/SHA、相对expected root、task-root不符、无enable/镜像、零或两个--repo（含同路径重复）拒绝；assertprovider_from_environment/viewer/service/server均0。`test_default_launch_kwargs_unchanged` 覆盖普通CLI/TUI/只读/默认校准，未传接续参数时不创建guard/session，不改变原launch调用。
- [x] **Step 2: 写启动/页面身份测试及RED。** `test_launcher_uses_restored_service_catalog` 假server/socket/UI/reader记录启动顺序，assertpreflight先于ProviderSettings.from_environment与窗口、create_dashboard_app.catalog is service.catalog is service.source.catalog，原repoID有且旧随机ID无。`test_restored_task_api_identity_strict` 真实app配内存ASGI transport（无socket），原Task读取不POST创建，wrong repo/base/anchor沿既有拒绝；读取app.js文本核对严格条件未改，不以Python用例冒充浏览器执行。真实URL恢复点击留待原生/UI门。节点新测试及既有test_launcher/test_cli_smoke。
- [x] **Step 3: 实现接续启动分支。** 先纯参数校验→唯一来源catalog→TaskService接管/核对/恢复catalog→manager和新认证通道/窗口hello→原provider能力/reconcile→app/server。窗口启动前没有session；hello不ready_for_start，bind才建立journal。configure_agent仍不启动模型。失败走Task5确认关闭分支，不在finally强行放锁；CLI错误固定码/exit2，不输出秘密或参数路径。默认启动原顺序/行为不变。
- [x] **Step 4: GREEN。** CLI/launcher节点通过且sticky配置提取0（成功流程仅注入假settings factory计数，不放开真实配置）；所有失败前零服务写入/窗口/网络。sessionauthkey新生成并只在既有private bootstrap内，不写metadata/API，viewer没有run/cancel/审批入口。

### Task 7: 完整离线接线、矩阵验收与交接

**Files:** 新test_task_observation_continuation_flow.py；相关测试/必要文档、新独立ledger/指纹；不得改冻结图或core接口。

**Interfaces:** 沿既有TaskRunContext、TaskWorkerController、真实任务图/父端事件/观测计数接口，注入脚本模型、FakeGit/FakeLease/FakeBackend/内存listener/FakeCloseoutExecutor。不会直接替换准入函数为恒True。新ledger目录 M `.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/`，起始/最终清单单独保存。

- [x] **Step 1: 写真实组件整链测试（已有接线首轮通过，不伪记RED）。** `test_continuation_fake_flow_reconciles_only_new_session` 先prepared→hello→explicit bind（assert model.calls==0、worker启动0），测试内经真实start门用假image/controller launcher进入当前任务上下文及真实图：合成读写/自测exit1→修复exit0→摘要/planner→原固定验证独立请求/逐条合成批准/receipt→verdict。仅假执行器，不能启真实worker进程。assert新calls连续/阶段与usage快照对账、新scores只同新交接索引、旧hash和spec不变，正式命令receipt身份不由自测代替。`test_continuation_missing_usage_and_protocol_fault` 用缺usage/预算门、wrong task/instance/attempt/重放/跳号/旧bootstrap、旧manager回调，assert沿原失败规则、不补usage、不重试session；新journal不能吞旧通道。节点 `tests/dashboard/test_task_observation_continuation_flow.py`。
- [x] **Step 2: 完成最小整合并GREEN。** 只补已列模块接线缺口；如需要改图/core/公开schema/预算或批准范围，先回设计审阅。`test_continuation_privacy_sentinel` 将合成秘密/源码/prompt/工具参数/异常哨兵放各私有输入，断言session.json、数值文件、API/事件/日志/错误无哨兵，查看器保留现有内存正文门/EOF清除。测试哨兵不使用真实配置或旧正文。
- [x] **Step 3: 运行相关整组。** 使用命令约定+新GUID basetemp，节点为 `tests/dashboard/test_task_observation_handles.py`、`tests/dashboard/test_task_observation_continuation.py`、`tests/dashboard/test_task_observation_continuation_flow.py`、`tests/dashboard/test_task_diagnostics.py`、`tests/dashboard/test_task_diagnostic_ipc.py`、`tests/dashboard/test_task_diagnostic_viewer.py`、`tests/dashboard/test_task_api.py`、`tests/dashboard/test_task_store.py`、`tests/dashboard/test_catalog.py`、`tests/dashboard/test_launcher.py`、`tests/test_cli_smoke.py`；辅助fakes不当测试节点。要求exit0，按下表逐行记录测试node ID而非单一总数。
- [x] **Step 4: 全项目与静态检查。** 新basetemp执行 `& 'D:/envs/codeagent/Scripts/python.exe' -B -m pytest tests -m 'not docker and not continuation_native_files' -q -p no:cacheprovider --basetemp $continuationCaseTemp`；执行 `& 'D:/envs/codeagent/Scripts/python.exe' -B -m ruff check --no-cache src tests`。记录pass/skip/deselected/warning/exit/耗时/完整命令，不沿用118/1134。所有native用例明确排除；现有symlink skip按实测报告，不默记通过。
- [x] **Step 5: 作者自审和保护验证。** 两树diff --check、明确目标全文/新增行有限私钥/凭据格式/冲突/空白扫描；旧361清单对计划内变化逐项解释，其余保持；21保护（10冻结源/7报告/4诊断）、7旧Task全部保持。四仓完整status/HEAD/本地heads-remotes与两来源index起始/最终核对，允许计划内dirty内容及新增文件，不fetch/修全局ignore。新最终src/tests清单含新文件，记录Python/依赖实际版本、命令/结果和SHA256，不覆盖旧ledger。不以status或diff忽略未跟踪源码内容。
- [x] **Step 6: 记录结果、停止现场门。** 更新 M接续/校准/阶段B设计、摘要/瓶颈/real_test以及 S阶段B设计/交接/进度；本计划按实际步骤勾选。完成条件是七任务代码与离线合同通过、作者自审无未处理阻断项；另列Windows原生门/GUI/现场/真实能力未验收。不发布当前不可执行的现场命令；新启动参数命令须实现验收后再编写，仍不构成重启或运行授权。

### 设计13组测试覆盖表

| 设计矩阵 | 所属任务/验收 |
| --- | --- |
| 默认兼容 | Task4 legacy碰撞、Task6默认CLI/launcher |
| 正常接续 | Task2初始/final旧格式、Task4单次bind |
| 未执行门 | Task2 never_executed、Task5 start漂移 |
| 合同/副本 | Task2 strict/scope、Task5两次fresh |
| 原文件内容 | Task2 strict legacy/上限/类型 |
| 文件保留 | Task2/4/5每路径同句柄hash；Task7最终清单 |
| 锁及并发 | Task3 preflight/lease归属、Task5并发/关闭屏障；原生门 |
| 路径与创建 | Task1假API契约、Task4每失败点；原生门 |
| 一次性 | Task2创建消费、Task4半创建/新实例拒绝 |
| 仓库身份与页面 | Task3 newcatalog、Task6原始repo/同catalog/API；真实浏览器未验收 |
| 通道及生命周期 | Task4长寿命/旧回调、Task5EOF/关闭、Task7故障流 |
| 真实图离线接线 | Task7真实图+假模型/执行器；真实provider不属于此证据 |
| 隐私 | Task2metadata/错误、Task6能力、Task7哨兵 |

## 原生Windows文件验收门（另行批准，本轮及七项离线回归不执行）

只在四Git库之外全新合成临时根，使用实际本地NTFS卷。该门不会读当前Task/来源/旧obs、提取provider设置、创建服务/Agent、调用Git/Docker/网络/Tk/AF_PIPE；采用sticky禁止边界，文件API与受控合成锁为唯一放开项。先呈报动作、根位置、待执行节点和边界，获明确确认才执行。跨进程锁测试只允许固定参数列表 `[指定Python, '-B', S/tests/dashboard/task_continuation_native_lease_child.py, '--root', 本次合成根]`，不经shell；Popen环境仅SYSTEMROOT/TEMP/TMP及禁字节码/原生门开关，stdin/stdout只交换locked/release/released，不传provider配置。单独原生guard只放开这个白名单子进程，其他subprocess仍sticky失败；最多5秒等待，结束时仅清理该测试自己持有的子进程身份，不影响服务/Agent。七项离线测试禁止启动此子进程。

- `test_native_relative_create_and_child_write`：实际相对parent NtCreateFile同时返回正确handle，独占碰撞拒绝；持目录guard时正常创建子文件及journal写/flush/fsync成功，父路径换位不能导向旁路写入。
- `test_native_pins_reject_rename_delete_reparse`：calibration祖先/Task/obs/sessions目录rename/delete/reparse修改被保护；若本机权限不能建立测试reparse，记录未覆盖并不判该门通过。
- `test_native_legacy_write_replace_and_preexisting_writer`：原三文件写/截断/替换拒绝，原先已打开的可写handle即使允许共享也使接管失败；兼容只读holder可接受。单硬链接要求实测；句柄转换保持身份/最终路径。
- `test_native_partial_session_blocks_next_owner`：各创建/刷新故障留下原位目录，下一个合成实例取得lease后仍拒绝；不删除后重跑同一根。
- `test_native_lease_and_delayed_writer_shutdown`：真实合成OS lease只有一个所有者，延迟线程失去写资格、新句柄关闭/旧hash核对/保护释放/lease最后顺序实测；失败不放锁。单进程模拟不能替代跨进程独占结论。

获准后设置唯一非秘密开关 `MOKIOCLAW_CONTINUATION_NATIVE_FILES=1`，指定Python/-B/无缓存/独立basetemp，节点只选 `tests/dashboard/test_task_observation_handles_native.py -m continuation_native_files`；运行后清除该开关。任一失效/跳过/无法核验不得宣称门通过；不能改用路径mkdir/reopen或减少保护来迁就成功。原生可行性失败先修订设计/计划，不操作63711或用真实模型探测。AF_PIPE/Tk长寿命/EOF/关闭是后续独立现场门。

## 计划作者自审与当前事实

本计划已按获批设计逐项映射，包含安全bootstrap以消除预检后普通glob加载窗口、bind即时消费、start自己的session复核、record/work释放时点、关闭失败保锁、唯一来源原ID及13组矩阵。五项Review Focus均分配具名测试，内部签名/数据类型在消费者任务复用；没有子agent/独立审阅结论。保留决定/验收断言，不预写产品函数体。

本轮只读复核：361源码/测试、21保护、7旧Task资产0缺失/0变化；旧指纹文件SHA256仍98ae4961897cbd51475bb8db6385ec6a66aa77fe1d11611caf9d4493f9813cd3。四仓HEAD/status/全部本地引用与设计审阅末尾一致（main8805条、stage51条、旧源1条、boltons0条）；两来源index保持。当前Task仍prepared/sequence2/execution_started=false、原repoID、空执行身份/请求/回执及两state事件，spec SHA256仍b28b672e77f65e10ab3cbf63d8b8b413a5f637b8120539db8f87bf79acff6977。目录仅旧三文件0/0/100、无sessions，本轮未重新尝试旧文件hash/读取status正文或核对监听；前轮占用失败/63711监听只作历史，不当作当前冻结/在线证明。

**审批下一步：**请审阅本计划七项离线实施范围及单列原生门。实施仍须用户批准；批准后保持本会话直接执行。没有新pytest/Ruff、原生探针、provider/Docker、停止/重启/重绑/Task启动、来源/旧证据修改、提交/push/fetch；历史118/1134不作为本方案成绩。

本轮文档收尾核验：11个明确计划/状态文档/.gitignore目标0缺失，有限私钥/token格式、冲突标记、行尾空白0命中；七任务/34未执行步骤/13矩阵组计数通过，两树diff --check exit0，精确白名单有效。四仓最终HEAD/全部本地引用保持，完整status相对起始仅M增加本计划未跟踪条目（8806/51/1/0）；已有dirty内容按本轮文档范围更新。361/21/7最终再次0变化/0缺失，旧ledger和两来源index及目标spec指纹保持。最后仅追加文档，未运行产品测试；有限格式扫描不是完整秘密审计。

## 2026-10-05 七项实施完成与离线验收（当前）

用户批准七项本地实施后，代码及176项新离线测试已在既有阶段B树S完成，M只更新计划/设计/状态与独立ledger；源与文档用apply_patch编辑，无子agent或提交。安全句柄、严格磁盘/副本证明、verified TaskStore/原repo_id、一次性session与新journal、start两次fresh及API更早门、关闭失败保锁和三个CLI参数均已接线。作者自审修正缓存bool/float、短期close失败、初始化后半异常、跨目录文件cap、Windows转换所有权与POSIX身份失败释放，未处理阻断项0。

最终相关324 passed/1 skipped/1 warning（37.82s，exit0）；全项目1310 passed/3 skipped/40 deselected/1 warning（186.01s，exit0），Ruff --no-cache通过。5原生文件测试未选/未执行，另35 Docker排除；symlink skip与既有httpx弃用warning保留。新测试sticky边界保持；全套既有受控Git/回环夹具不等于零子进程/零网络。完整命令、实际版本、13组node ID、失败修复历史及三项裁决/代价见主项目 .superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/verification.md。

旧361项仅S的7项计划内变化，其余354保持（包含M产品/测试167项）；21保护/7旧Task0变化0缺失、旧ledger保持。新增8 Python及marker纳入最终376条两树清单（M167+S208+marker）；起始361/21/7与最终清单独立保留。四仓HEAD/本地引用、两来源index保持，完整status8806/62/1/0（S起始51），旧dirty保留。本轮未核验旧三文件hash/当前端口进程，旧0/0/100、prepared和63711/PID是历史，不作当前冻结/在线证明。

Windows实际NTFS/句柄/跨进程lease原生门仅编写，AF_PIPE/Tk长寿命/EOF/关闭、实际浏览器、旧持有者退出后的保留基线及加载/同Task绑定、真实恢复/usage/正式完成/费用均未验收。没有现场服务/Task/provider/Docker操作、新额度或远端变更。下一步先另行批准原生合成门，之后现场恢复、新boltons一次额度/额外无provider容器检查/prepared启动继续分别确认；不发布现场执行命令。旧boltons余0、Task10第五批余2及停止讨论保持。

34步骤完成，Task7整链沿Task1–6已有接线首轮7 passed，不伪报RED。三项裁决：手工apply_patch ledger（需手工核对）、task_api更早fresh（多一次只读证明）、内存ASGI真实router（不替代浏览器/middleware验收）。详细矩阵与结果见 [verification.md](../../../.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/verification.md)。原生门仍未执行。

## 2026-10-05 已获批原生门：环境拒绝诊断与复测修订

用户“继续下一步，我批准了”已批准五项合成文件门，现场操作仍须另行批准。首次受限执行4 failed/1 passed（1.55s，exit1，无skip），四项在祖先pin时失败；诊断显示C:\Users\lyf的CreateFileW返回Win32 5，而相同参数在全新合成目录成功。未改源、未减少保护、未删除失败根，尚不能将环境推断当作已证实根因。

后续顺序：先保存首次失败与诊断；以require_escalated申请同一Python、同一五节点、相同保护参数/sticky禁止项、另一全新basetemp的非受限复测，唯一子进程仍为固定合成lease脚本；查看全部结果并区分环境限制与产品失败。拒绝/失败/skip均不通过整门。产品保护若需要改变，须先形成具体修订供审阅；不以path fallback/放宽share/降低祖先保护绕过失败。不得启动63711/Task或模型探测。阶段状态、账本与历史离线结果分别记录。

同合同修复顺序：已取得原生RED及单变量证据后，先补原生测试异常路径finally，另一新根复测旧产品；再仅将相对子文件DesiredAccess补显式SYNCHRONIZE（0xc0100000），保留RootDirectory/FILE_CREATE/options0x60/share1、所有身份检查与保锁要求；新根原生复测和相关/全项目离线回归、Ruff检查，分别记录。原生符号链接无法创建的skip继续阻断整门，不以其余通过代替。仅源与测试在S、文档/ledger在M；源与文档apply_patch，无现场/provider/Docker/提交。该修正补足既定API合同，不改变方案A方向或授权范围。

同文件门夹具修订：符号链接失败后仅尝试同根直接子目录junction，实际DeviceIoControl设置mount-point reparse；严格限定系统Temp合成根、普通子目录及本根目标，实际属性/准入拒绝/guard持有时修改拒绝均要验证。禁止外部目标、mklink/新增子进程、权限或系统设置变更；不能建立则保持skip。此测试夹具不进入产品，不能将junction证据当成符号链接能力或完整现场矩阵。五节点只记录实际覆盖；原计划中各创建/fsync故障、完整关闭失败保锁顺序及所有祖先层级的原生矩阵若未实测，单列剩余项，不靠节点名称宣称完整门已通过。

## 2026-10-06 五项基础检查完成；完整原生矩阵剩余任务

实际最终5 passed/0 skip（1.37s），相关324 passed/1 skipped（39.52s），非Docker非原生全项目1310 passed/3 skipped/40 deselected（189.67s）、既有warning1，Ruff --no-cache通过。实际报告记录junction与共享冲突32。只S两份源/测试改变，376映射以旧完整清单加独立native-source-hash-overrides.json覆盖形成；其余374及21保护/7旧Task保持。当前以native-acceptance.md分开列证据与未覆盖要求，不判完整门通过。

以下继续沿已有用户批准的合成文件门执行，不要求重复批准五节点；保持全新Temp根、固定白名单子进程、sticky禁止项、无来源/旧现场文件操作。先核对有效376映射/28保护/四仓身份，每轮不复用或删除失败根。只在S扩充原生测试/合成工具，产品若需修正先诊断并修订合同；不减保护。

- [x] N1：在本次Temp根内构造多层calibration祖先/Task/obs/sessions，逐层实测rename/delete/写或reparse修改拒绝，检查具体共享冲突；仅攻击测试内路径。实测guard期间正常子文件创建和父路径换位拒绝，旁路目录没有产物。不能对C:\Users等真实祖先尝试修改。
- [x] N2：三旧文件分别参数化，明确只读holder可接管、已打开且允许共享的可写Win32 holder使接管失败，写/截断/替换拒绝、单硬链接检查及同句柄hash/最终路径保持；不能用泛化OSError掩盖权限或非空目录错误。
- [x] N3：用真实Windows文件/句柄与合成Continuation owner，在sessions/session/metadata/三个journal创建、metadata/status写/flush/fsync各故障点注入可识别异常；确认原位部分目录、一次性消费、保护/lease释放或保留符合合同。取得真实OS lease的新owner通过实际check拒绝，不删除后重跑。固定锁child若需支持合成root/tasks，先将校验限定为Temp UUID根内的固定tasks子目录，不开放任意路径或额外命令。
- [x] N4：以实际新session journal和三旧文件guard执行现有关闭流程，记录写资格封闭→新句柄关闭→旧hash同句柄核对→保护释放→lease最后，并实测延迟线程拒写。逐项注入新file/metadata/目录close与旧hash核对失败，真实锁争用证明未释放；再次close不能静默放锁。测试自身只在断言后恢复其故障注入、关闭自己持有的合成句柄/固定子进程，不替代产品关闭证明。不得启动服务监听、Agent、AF_PIPE/Tk或provider。

完成N1–N4才审阅完整原生门；AF_PIPE/Tk长寿命/EOF/关闭、浏览器、旧服务正常退出及保留基线/加载绑定、真实启动与额度各有独立门。不得因基础5 passed执行旧启动命令。

## 2026-10-06 N1–N4 接口与夹具执行裁决

沿用户既有批准执行两个原生测试文件，使用 `-m continuation_native_files`；不再仅选五基础文件。为了不依赖系统长路径设置，测试根直接放在全新basetemp内，以短前缀加32位UUID命名basetemp，合成根仍为 `mokioclaw-continuation-native-` 加32位UUID。路径与保护范围不减少，不改权限或系统设置，不删除失败根。

固定stdlib锁child只增加UUID合成根的固定 `tasks` 子目录；其它子目录拒绝，输入解析不得消除reparse后绕过原路径检查，祖先与lock文件仍核对。环境仅SYSTEMROOT/TEMP/TMP和原生开关/禁字节码，固定参数列表和release协议保持，无shell或额外命令。

N3先通过真实check读取合成spec/record/副本/旧文件，Git与来源identity使用原有受限double，没有真实Git或来源探针。每故障点确认部分布局、consumed、同句柄旧hash和跨进程租约排他；恢复测试注入后，实际TaskService.close关闭未提交/部分session并正常释放租约，下个实际owner取得lease再check，磁盘sessions仍阻断。sessions创建之前失败无标记；OS已经创建而backend尚未返回时内存consumed仍false，但磁盘标记使本owner再次绑定和新owner检查都拒绝。

N4调用真实manager.close_confirmed与TaskService.close，内存服务上下文不启动构造器、监听或worker。顺序按Task5合同：三个journal写句柄封口/关闭→旧hash→metadata/session/旧保护关闭→lease最后；目录保护不是提前释放的新写句柄。故障落在真实stream.close或native CloseHandle边界，旧hash故障先实做同句柄读取。再次close仍拒绝、跨进程租约仍忙；迟到线程的indexes和状态写入被封口，实际新文件字节无变化。测试最后的资源清理不充当产品正常关闭证据。
