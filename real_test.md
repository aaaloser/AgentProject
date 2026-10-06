

# boltons 私有观测工作台启动（2026-10-05）

> 2026-10-06：用户已判 N1–N4 合成文件门通过，并明确授权将最近未同步的阶段B相关代码、测试、设计与交接资料提交并push到既有两个分支。此授权只增加版本同步；本文现场启动命令仍须按接续设计逐项审阅，不能在本轮执行。下一项先编写无provider的合成 AF_PIPE/Tk/浏览器验收计划，获批后执行；旧持有者退出、旧文件保留基线与加载绑定、真实Task启动及新额度分别确认。

> 2026-10-06 当前：既有批准的 Windows 原生合成文件门 N1–N4 已完成，两个测试文件最终42 passed/0 skipped（8.08s），真实目录共享冲突32、junction、三旧文件holder、17绑定故障点和8关闭路径均有证据。相关324 passed/1 skipped（38.90s），全项目1310 passed/3 skipped/77 deselected/1 warning（190.66s），Ruff --no-cache通过。只S三份测试/合成child变更，产品源码保持；完整377映射见M的native-matrix-hashes.json，实际矩阵与失败历史见native-matrix.md。历史完整清单与native-acceptance.md均保留。现场服务/Task状态未核验，AF_PIPE/Tk/浏览器、正常退出后的旧文件保留基线/加载绑定、真实启动和额度仍分别授权；无provider/Docker/现场操作/提交/子agent，旧boltons余0、Task10第五批余2及停止讨论保持。下方旧“基础5项/原生未执行/矩阵待补”均按历史读取。

用于启动带逐次用量记录和本机交接查看窗口的校准工作台。使用阶段 B 源码、指定 Python 和新的校准目录；旧 boltons 私有任务与证据保留在原目录。

先在旧工作台的终端按 Ctrl+C 正常停止服务，再在 PowerShell 中执行以下内容。API key 与 base URL 继续交互输入已验证可用的配置，模型保持 qwen3.5-flash；不从 .env 读取配置，不将秘密值写入本文档。

```powershell

$env:MOKIO_TASK_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'API Key' -AsSecureString)).Password

$env:MOKIO_TASK_MODEL = 'qwen3.5-flash'

$env:MOKIO_TASK_BASE_URL = Read-Host 'Base URL'

Set-Location -LiteralPath 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent'

$env:PYTHONPATH = 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent\src'
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'D:\envs\codeagent\Scripts\python.exe' -B -m mokioclaw dashboard `
    --repo 'D:\agent work\project\boltons-mokioclaw-pilot' `
    --task-root 'D:\agent work\project\boltons-mokioclaw-calibration-2026-10-04\tasks' `
    --calibration-root 'D:\agent work\project\boltons-mokioclaw-calibration-2026-10-04' `
    --task-image 'sha256:83ff408c0f9ce6007afbc9b468815ae4fbdde79d7a702e4b7eb5ee21c91a72b2' `
    --enable-agent `
    --no-browser

```

参数简述：

- 指定 Python 与绝对 PYTHONPATH：确保使用阶段 B 工作树中的当前实现；-B 与 PYTHONDONTWRITEBYTECODE 禁止写入字节码。
- --task-root：新任务副本保存到新校准目录的 tasks 子目录。
- --calibration-root：启用私有观测通道与原生诊断窗口；窗口只负责绑定、查看交接和评分。
- --task-image：沿用原固定镜像；命令隔离和逐条审批规则保持。
- --enable-agent：开启逐任务确认入口，启动工作台不会自动运行任务。
- --no-browser：不自动打开浏览器；手动访问终端给出的新地址，端口不固定。

启动后把终端显示的 http://127.0.0.1:端口/ 地址发回，并确认原生诊断窗口出现。先核对窗口、通道及目录就绪；获准准备新任务后，再绑定 prepared Task 并核对完整策略。窗口未出现或启动报错时，先停止排查，不用真实模型调用测试就绪。

本命令不增加真实运行额度、不自动准备或启动任务、不批准任何命令。恢复、新增 boltons 一次额度、额外 Docker 检查和具体 prepared 任务启动仍分别确认；原 boltons 余 0，Task10 第五批余 2 保留。完整校准合同见 [真实校准方案 §13](docs/superpowers/specs/2026-10-04-mokioclaw-real-calibration-design.md#13-2026-10-05-用户验收与60718工作台只读就绪检查)。

2026-10-05 更新：用户自行重启到63711并绑定原Task后，已批准的两项绑定修复通过离线验收（相关118、全非Docker1134 passed）。正在运行的工作台不会自动加载源码修复；原Task已经建立独占观测文件，直接重启后重绑会碰撞拒绝，不能删除／覆盖文件或创建替代Task规避。上述启动参数保持，但先审阅保留已有空观测文件的未运行Task接续方案，再加载修复并作现场验收；当前不要运行任务。详见[校准方案 §16](docs/superpowers/specs/2026-10-04-mokioclaw-real-calibration-design.md#16-2026-10-05-绑定修复获批实施离线验收及原task接续边界)。

2026-10-05 接续方案已形成、待审：推荐保留原三文件，为同Task建立一次独占观测session，并在核对原来源/合同后恢复原repo_id；详见[保留与接续设计](docs/superpowers/specs/2026-10-05-mokioclaw-prestart-observation-continuation-design.md)。拟新增的三个接续参数尚未实现，当前不要把它们加到命令执行。旧文件仍被持有，需正常停止旧工作台后只读取得保留基线；本轮未停止或重启服务。设计及实施计划获批、离线验收后再更新实际启动命令；不会另建Task、清空文件、增加预算或自动/run。

2026-10-05 本次审阅修订：上述设计§4–8/§11已补实fresh磁盘记录、Windows相对句柄创建、一次性消费时点、锁顺序和关闭失败保锁；仍待用户批准，未编写接续实施计划或改产品。实时netstat仍见63711监听PID35508，三份观测仍0/0/100、Get-FileHash失败；Task未执行，合同/manifest/16份副本匹配。原生文件创建门仍须另行确认/验证，不能据此执行旧命令重绑；现有启动命令及三个未实现参数都不作为本轮重启授权。没有provider/Docker/服务操作/新额度，118/1134保持历史结果。

2026-10-05 当前：用户选择方案A并授权编写实施计划，[七项计划](docs/superpowers/plans/2026-10-05-mokioclaw-prestart-observation-continuation.md)已形成、待审；产品及接续参数尚未实施。Windows原生合成文件门、真实管道/窗口、旧服务正常停止/重启/同Task绑定仍分别确认，原命令不能直接接续。计划批准后先本会话离线实施/验收，无子agent；当前没有pytest/Ruff、原生探针、provider/Docker/服务操作/Task启动或新额度。boltons余0、Task10余2和停止讨论保持；本轮只读Task/spec/旧文件大小及361/21/7指纹保持，未重新核验旧hash或监听。上述旧启动和检查文字按历史读取。

2026-10-05 最新实施结果：用户“开始实施”/“继续”批准七项本地工作，方案A三个参数与安全接续已在阶段B树完成。相关324/full1310 passed、Ruff通过，21保护/7旧Task保持；详见[接续设计§13](docs/superpowers/specs/2026-10-05-mokioclaw-prestart-observation-continuation-design.md)与[实施记录](.superpowers/sdd/2026-10-05-mokioclaw-prestart-observation-continuation/verification.md)。Windows原生5项仅编写未执行，AF_PIPE/Tk/浏览器与现场未验收；本轮未核验旧hash/当前63711/PID，未停止/重启/绑定/运行、provider/Docker/新额度或提交。下一步另行批准原生合成门，通过后才安排保留基线/现场加载；暂不提供现场执行命令。上方命令及尚未实现/待审为历史，不是当前重启授权。boltons余0、Task10余2和停止门保持。
