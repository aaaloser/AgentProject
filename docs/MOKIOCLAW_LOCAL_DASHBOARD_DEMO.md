# MokioClaw 本地仓库审查工作台：启动与演示

本页对应本地浏览器工作台 V1。工作台只读取**本次启动明确传入**的本机 Git 工作树，在左栏列仓库、中栏列提交、右栏列提交统计与改动审查优先级。私有本地仓库可以使用；当前没有 GitHub 账户登录、远端仓库同步、页面内 Agent 修复或 PR 回写。

## 1. 启动与停止

准备 Git、Python 依赖和至少一个本地 Git 工作树。从项目根目录在 Windows PowerShell 执行：

```powershell
uv sync --locked
uv run mokioclaw dashboard --repo "D:\path\to\repo-one" --repo "D:\path\to\repo-two"
```

路径可重复传入；同一 Git 顶层目录的别名只显示一次。未传 `--repo` 时默认使用当前目录。如果你想手动打开浏览器：

```powershell
uv run mokioclaw dashboard --repo "D:\path\to\repo-one" --repo "D:\path\to\repo-two" --no-browser
```

终端会打印 `http://127.0.0.1:<临时端口>/`。服务只监听本机回环地址。按 `Ctrl+C` 停止；停止后刷新页面将无法继续读取仓库。启动时若任一目录无效，整个工作台拒绝启动，请修正路径后重试。

本项目指定的 Python 环境已有依赖；若无需创建 uv 项目环境，可在项目根目录直接运行：

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
& 'D:\envs\codeagent\Scripts\python.exe' -m mokioclaw dashboard --repo "D:\path\to\repo-one" --repo "D:\path\to\repo-two"
```

## 2. 可复现的临时仓库演示

下面只在系统临时目录创建**演示仓库**，不会改动项目的 Rich/Click 评测证据。请在全新 PowerShell 终端、项目根目录执行；保留该终端中的 `$repoA`、`$repoB` 变量供后续命令使用。`demo@example.invalid` 是夹具身份，不是实际账号。准备约 1 分钟，需允许本机 Git 在系统临时目录创建提交。

```powershell
$demoRoot = Join-Path $env:TEMP ('mokioclaw-dashboard-demo-' + [guid]::NewGuid().ToString('N'))
$repoA = Join-Path $demoRoot 'history-repo'
$repoB = Join-Path $demoRoot 'review-repo'
New-Item -ItemType Directory -Path $repoA, $repoB | Out-Null
foreach ($repo in @($repoA, $repoB)) {
  git init -q -b main $repo
  git -C $repo config user.name 'Demo Fixture'
  git -C $repo config user.email 'demo@example.invalid'
  Set-Content -LiteralPath (Join-Path $repo '.git/info/exclude') -Value 'ignored-evidence/'
  New-Item -ItemType Directory -Path (Join-Path $repo 'ignored-evidence') | Out-Null
  Set-Content -LiteralPath (Join-Path $repo 'ignored-evidence/keep.txt') -Value 'preserve'
}
1..52 | ForEach-Object {
  Set-Content -LiteralPath (Join-Path $repoA 'sample.txt') -Value "revision $_"
  git -C $repoA add sample.txt
  git -C $repoA commit -q -m "ordinary $_"
}
Set-Content -LiteralPath (Join-Path $repoB 'sample.txt') -Value 'ordinary'
git -C $repoB add sample.txt
git -C $repoB commit -q -m 'ordinary change'
New-Item -ItemType Directory -Path (Join-Path $repoB 'auth') | Out-Null
Set-Content -LiteralPath (Join-Path $repoB 'auth/policy.txt') -Value 'fixture'
git -C $repoB add auth/policy.txt
git -C $repoB commit -q -m 'sensitive path example'
git -C $repoB checkout -q -b demo-side
Set-Content -LiteralPath (Join-Path $repoB 'side.txt') -Value 'side'
git -C $repoB add side.txt
git -C $repoB commit -q -m 'side branch'
git -C $repoB checkout -q main
Set-Content -LiteralPath (Join-Path $repoB 'main.txt') -Value 'main'
git -C $repoB add main.txt
git -C $repoB commit -q -m 'main branch'
git -C $repoB merge --no-ff -q -m 'merge example' demo-side
```

启动工作台：

```powershell
uv run mokioclaw dashboard --repo $repoA --repo $repoB
```

验收路径：

1. 左栏切换 `history-repo` 与 `review-repo`，核对各自 HEAD 和提交历史。仅这两个仓库应出现。
2. 在 `history-repo` 中，第一页为 50 条；点“加载更多”后可看到余下 2 条。选择普通提交，右栏应显示 `low`。
3. 在 `review-repo` 中，选择 `sensitive path example`，右栏应显示 `high` 和敏感维护路径依据；选择 `merge example`，应显示 `manual_review` 与合并提交的信息缺口。普通提交仍为 `low`。
4. 可缩窄浏览器窗口并用 Tab 键检查面板与按钮；提交详情应随当前仓库选择变化。停止服务后，浏览器应显示连接失败。

如果要检查只读性，可在启动前和停止后分别查看同一仓库的 `git show-ref --head`、`git --no-optional-locks status --porcelain=v1 --ignored`、`.git/index` 的 SHA-256、工作树文件和 `ignored-evidence/keep.txt` 的 SHA-256。两次结果应逐项相同。项目自动化验收还对两个临时仓库的引用、index、状态、普通文件和 ignored 文件做前后比较。**不要清理或覆盖项目目录中的 ignored 实验证据。**

## 3. 四种优先级

| 标签 | 含义 |
| --- | --- |
| `high` | 优先安排人工审查：敏感维护路径、至少 10 个文件或至少 500 行改动。 |
| `medium` | 较早安排人工审查：至少 4 个文件、至少 120 行改动，或存在删除/重命名。 |
| `low` | 统计完整，且未命中上述触发条件的普通提交。 |
| `manual_review` | 合并提交、二进制或统计缺失等超出 V1 可靠判定范围，需要人工判断；不能解释为更安全。 |

规则版本为 `review-priority-v1`。规则只用提交统计、路径类型和父提交数量；不读代码正文来推断缺陷，不调用模型，也不产生漏洞结论、修复成功率或概率分数。未提交的工作树改动仅显示 dirty 状态，不计入历史提交的标签。

## 4. 隐私与截图

本机页面会展示仓库绝对路径、提交标题和文件路径；私有仓库也属于敏感内容。演示、录屏和截图请只使用上面的临时夹具，或先遮盖私有路径、提交消息及文件名。不要把密钥、Authorization、完整 endpoint/query、prompt/response、headers、payload 或 `.env` 值放进截图、报告或问题反馈。工作台无访问日志，关闭后进程内目录和详情缓存消失；它不会向 provider 发送仓库内容。

## 5. 故障排查与当前边界

| 现象 | 检查方式 |
| --- | --- |
| `git` 不可用 | 在同一终端运行 `git --version`，确认 Git 位于 PATH。 |
| 启动时拒绝仓库 | 确认每个 `--repo` 路径存在、可读，并位于非 bare Git 工作树内；任何一个失败都不会部分启动。 |
| 页面提示仓库不可用 | 仓库可能在启动后被移动或删除；修复目录并重新启动。其他已登记仓库仍可浏览。 |
| 空历史 | 仓库尚无提交；这不是低风险评估。 |
| `manual_review` | 查看右栏的信息缺口；合并、二进制和浅克隆统计缺失需人工核对。 |
| HEAD 已更新 | 旧分页保持原锚；使用页面刷新提示加载新历史。 |
| 读取超时或输出过大 | 缩小演示仓库范围或重试；接口不会以截断数据生成评估。 |

最终 Rich–Click 对比仍以 `evals/reports/cross-repo-rich-click-20260926-01/` 为准，整体方向为 `inconclusive`、严格审计状态为 `legacy-audit-limited`；本地工作台不是这两批正式 Agent 实验的补跑或新成绩。完整项目测试和环境限制以[技术进度记录](TECHNICAL_IMPLEMENTATION_PROGRESS.md)中本轮结果为准。
