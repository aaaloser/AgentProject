# 私有观测窗口绑定修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户2026-10-05“可以的，开始修复吧”已批准两项离线实施；本会话直接执行，禁止子agent、不提交或push。进度见本计划勾选及专属ledger。

**Goal:** 窗口正常持续轮询后仍可绑定prepared Task，客户端通道失败时父进程失去观测就绪资格。

**Architecture:** 将viewer控制通道的序号范围与worker有限观测流分开；viewer继续严格单调、逐请求应答，不重置或跳过序号。客户端出现编码、发送、等待或回执错误后关闭连接并永久失效，让现有父端EOF路径撤销就绪；不增加原文日志或公开API。

**Tech Stack:** Python、既有JSON字节IPC／AF_PIPE、Tk；离线验收只使用内存通道、假窗口与假执行器。

**Spec:** [当前校准方案§15](../specs/2026-10-04-mokioclaw-real-calibration-design.md)。两项产品离线修复已获批准；用户已自行重启至63711并绑定原Task。真实运行及额外检查仍有独立权限门，本轮不操作现场。

## Global Constraints

- 实施树为C:/Users/lyf/.codex/worktrees/mokioclaw-stage-b/MokioAgent，保留全部dirty；主项目只更新文档和本计划精确白名单。
- 冻结tools/*.py、graph/architectures.py及workflow.py不修改；来源、旧Task、诊断证据和新prepared副本不修改。
- worker序号仍1–1024，viewer改为1–(2**63-1)，包括state回复；类型必须是int，拒绝bool／float、0／负数／超过上限，不回绕。
- viewer的hello必须第一帧，父端要求sequence恰为前值+1；重放、跳号与身份错配仍拒绝。角色未知不能因ACK早返回绕过角色校验。
- 409600私有帧、512条数值记录／每条4096字节、32条待ACK、1秒ACK、64KiB交接、24索引、600秒清理后留存及32字节认证材料均保持。
- 96／72／48KiB、总150000／20／3072／1 attempt／1200秒、七槽／1.25、scope、逐项审批、固定正式验证与缺usage停止均保持。
- 新测试用现有offline_observation_guard封锁provider／dotenv／配置提取、网络、真实AF_PIPE、Tk、Docker与真实命令；边界钩子被吞掉仍失败。测试不连接61771，不操作真实Task。
- 指定D:/envs/codeagent/Scripts/python.exe，显式PYTHONPATH=src，PYTHONDONTWRITEBYTECODE=1，-B及-p no:cacheprovider；每次全新的--basetemp位于四Git库之外。
- 本计划不授权provider、Docker、真实额度／run、命令审批、预算提高、来源应用、提交／push或远端操作。实施通过后由用户在原终端正常重启，先只读恢复原prepared，再单独绑定；不自动新建Task或/run。

## Review Focus

1. 等待绑定超过1024次轮询，及绑定后再经历1200秒运行＋600秒观察：不能耗尽viewer序号。
2. 高序号仍拒绝重放／跳号／未知role；worker与数值记录上限不能随viewer一起扩大。
3. 本地编码失败未发送帧，或等待超时／错序回复：仍关闭原连接，不能让父端保持假就绪。
4. 关闭连接抛异常或父端收到EOF：客户端不能恢复发送，父端无原文日志并撤销ready。
5. 重启有既有observations文件：继续独占拒绝，不能删除／覆盖旧数值证据或另建Task掩盖问题。

### Task 1: 区分viewer序号与worker限额

**Files:** Modify src/mokioclaw/dashboard/task_diagnostic_ipc.py:_validate_frame；Test tests/dashboard/test_task_diagnostic_ipc.py、test_task_diagnostic_viewer.py、test_task_diagnostics.py。

**Interfaces:** 保留encode_frame(message, *, role)、decode_frame(data, *, role)、CalibrationObservationManager.receive_viewer(frame)签名和固定ERROR。_validate_frame(data, role)先校验role，再按role选择序号上限；viewer state使用同一viewer范围，worker及ACK沿其角色边界。

- [x] **Step 1: 编写失败回归。** test_viewer_long_idle_then_bind用真实ViewerChannel／Controller、真实codec和真实manager.receive_viewer连接内存对端，合成prepared记录及外部tmp_path；先hello＋8192次poll，再bind，断言bind=True、manager.ready_for_start(TASK_ID)=True，再8192次poll仍valid。循环不收集全部帧，assert数值文件没有模型调用／交接。test_viewer_sequence_limits逐项断言1024、1025、2**63-1编码／解码可往返，2**63拒绝；worker1025拒绝；两role对0／-1／True／1.0拒绝。
- [x] **Step 2: 运行上述测试取得RED。** 预期现代码在1025被固定ERROR拒绝；不允许因夹具NameError等非目标错误冒充RED。独立basetemp、既有sticky guard和指定Python。
- [x] **Step 3: 最小修改_validate_frame(data, role)。** 仅区分角色限额并先拒绝未知role；保留总帧门和既有载荷校验，不改调用／数值配额，不重置序号、放宽重放或引入日志。
- [x] **Step 4: 验证GREEN及协议边界。** 高序号下manager收到重复帧或跳号立即invalid；未知role的普通帧和ACK均拒绝。重跑三份相关测试；新增纯内存用例必须不创建真实窗口、管道或命令。

### Task 2: 客户端失效传播与最终回归

**Files:** Modify src/mokioclaw/dashboard/task_diagnostic_viewer.py:ViewerChannel.__init__／request；Test tests/dashboard/test_task_diagnostic_viewer.py、test_task_diagnostics.py，必要时test_task_api.py。父端task_diagnostics.py的现有EOF失效语义保留，只有测试证明存在额外缺口时才在本计划范围内修正该缺口。

**Interfaces:** ViewerChannel.request(self, kind, **values)仍返回既有state字典或抛固定ValueError(ERROR)。新增通道内部永久失效状态；任一交换异常关闭所持ByteConnection，关闭异常不得覆盖固定错误，失效后不增加序号／发送／重连。ViewerController仍清空正文并显示invalid；不新增自由文本或run／cancel／审批能力。

- [x] **Step 1: 编写失败回归。** test_viewer_exchange_fault_closes_channel分别注入编码失败、send异常、poll超时、recv异常、非法JSON／错序回复；assert connection.closed、controller.valid=False、正文为空，后续request不再发帧。额外close抛异常也固定ERROR，不能恢复。test_viewer_eof_revokes_parent_ready用合成prepared、真实manager._start_role和队列式假listener／connection运行现有serve路径；正常绑定就绪后注入EOF，等待线程事件，assert not manager.viewer_ready、not manager.valid、not manager.ready_for_start(TASK_ID)。不以测试直接调用manager.invalidate替代EOF传播。
- [x] **Step 2: 运行故障回归取得RED。** 现客户端局部异常不关闭连接，应在closed断言失败；排除fixture错误。EOF测试如已通过，只记既有路径通过，不伪造其RED。
- [x] **Step 3: 实施永久失败／关闭连接。** 在ViewerChannel的交换边界统一处理，维持原hello3秒／普通1秒等待及返回结构，不重连或自动绑定；异常文本不外泄。原父端serve收到EOF后沿既有finally撤销就绪；假listener测试覆盖该路径。
- [x] **Step 4: 聚焦验证。** 新长寿命、故障、EOF、就绪门、journal独占碰撞、默认关闭／普通CLI兼容和敏感哨兵回归通过。TaskService.start_agent在not-ready时于Docker／worker之前拒绝，使用假调用计数断言，不触碰真正启动。
- [x] **Step 5: 最终回归与记录。** 相关三份＋test_task_api.py，全项目tests -m "not docker"，Ruff --no-cache src tests；两树diff --check、明确目标有限秘密格式扫描、21保护／7旧Task及四仓HEAD／引用／来源index核对，更新实施指纹和交接。报告真实skip／Docker排除，不复用1073等旧结果。作者自审，不使用子agent或提交。

相关和全项目命令各使用新的$viewerCaseTemp；本轮已按以下参数实际执行，结果见最终记录和ledger：

```powershell
Set-Location -LiteralPath 'C:/Users/lyf/.codex/worktrees/mokioclaw-stage-b/MokioAgent'
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$viewerCaseTemp = Join-Path $env:TEMP ('mokioclaw-viewer-' + [guid]::NewGuid().ToString('N'))
& 'D:/envs/codeagent/Scripts/python.exe' -B -m pytest tests/dashboard/test_task_diagnostic_ipc.py tests/dashboard/test_task_diagnostic_viewer.py tests/dashboard/test_task_diagnostics.py tests/dashboard/test_task_api.py -q -p no:cacheprovider --basetemp $viewerCaseTemp
$viewerCaseTemp = Join-Path $env:TEMP ('mokioclaw-viewer-' + [guid]::NewGuid().ToString('N'))
& 'D:/envs/codeagent/Scripts/python.exe' -B -m pytest tests -m 'not docker' -q -p no:cacheprovider --basetemp $viewerCaseTemp
& 'D:/envs/codeagent/Scripts/python.exe' -B -m ruff check --no-cache src tests
```

## 修复前诊断证据及未测项（历史）

仅AST抽取当前codec、ViewerChannel／Controller定义到纯内存，未执行模块导入或窗口main；输入合成Task身份，无summary，未使用真实认证材料。首次夹具缺HandoffView类型名而NameError，校正未使用的类型占位后，两条路径有目标结果：立即bind为sequence2／True，1023次poll后bind为sequence1025／False、valid=False，发送停在1024且closed=False；1025 codec固定拒绝。边界审计钩子0命中，无provider初始化、网络、真实管道、命令或产品变更。它证明确定性缺陷及缺关闭行为，不是全产品回归、现场帧抓取或已修复证据；没有取得现场精确最后序号，不能排除现场还有调度／IO故障。

## 自审与审批状态

两项修复已获批准并完成，9步骤全部勾选，无提交步骤；本会话直接实施、作者自审，未使用子agent。最终相关118 passed，非Docker1134 passed／3 skipped／35 deselected，Ruff通过；两轮目标RED分别10／24 failed。五个Review Focus均通过相应离线测试，原保护／scope／预算／正式验证不变。

17个明确源码／测试／文档／ledger／指纹／.gitignore目标有限私钥／凭据格式、冲突及行尾空白扫描0命中／0缺失，两树diff --check exit0。361产品／测试当前指纹与实际一致，21保护和7旧Task资产保持；四仓status／HEAD／本地引用及来源index保持。完整命令／basetemp／skip和边界见专属ledger、校准设计§16、交接§68／技术进度§107。

现场仍待接续：用户修复前重启至63711并成功绑定原prepared，已创建独占观测三文件。加载修复后直接重绑同一Task会碰撞拒绝，不能删除／覆盖或创建替代Task掩盖。先审阅保留现有空观测的未运行Task接续方案，再安排加载修复及原生验收；本轮未重启、provider／Docker／真实任务或新增额度，真实恢复、额外检查及每prepared启动继续单独确认。旧诊断及未执行数字按历史读取。
