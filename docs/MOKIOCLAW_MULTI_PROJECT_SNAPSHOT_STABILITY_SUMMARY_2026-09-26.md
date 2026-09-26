# MokioClaw 多项目快照与评测稳定性阶段总结

> 截至 2026-09-26；范围为已批准实施计划的 Tasks 1–20。本文是交付摘要，方法、逐项审计和限制以同目录的详细阶段报告及冻结机器产物为准。

## 本阶段完成了什么

本阶段先建立可审计的评测底座，再把固定仓库快照实验从 Rich 扩展到 Click 8.4.2。Tasks 1–12 冻结分析规格，区分 provider 故障与 Agent 任务终态，建立可从中断恢复的模型调用、传输与 worker-attempt 账目，以及不可覆盖的 schedule、实验身份、停止规则和确定性分析。Rich 旧批次只新增只读 legacy audit sidecar，三份冻结分析未重算或改写。

Tasks 13–16 固定 Click 源码、离线镜像和来源/依赖身份，对四个候选进行零 Agent-run 验收，并按预注册规则选择来自 option parsing 与 argument conversion 两个子系统的 Case，冻结 72-slot 正式批次。供应商 smoke 与额外资格检查只用于准入，不计 Agent 成绩。此前未通过准入的诊断及 pilot 批次按原状态保留，不并入正式批次。

Tasks 17–19 在 G1、G2、G3 分别获得用户授权后，顺序执行 R1、R2、R3 各 24 个正式槽位。全部 72 个槽位均启动并封账一次，没有补跑、替换、删除或择优保留。最终 Click 分析只在完整封账后于原批次运行一次。Task 20 对 Rich 与 Click 分别核账，再做预注册的跨仓库方向与审计比较，完成阶段报告和全项目验收。

## 关键结果

| 项目 | 本阶段结果 |
|---|---|
| Click 正式规模 | 两 Case × 三架构 × 四资源格 × 三轮；scheduled=72、started=72、closed=72、not_started=0 |
| Click provider 与遥测 | 正式 provider attrition=0；telemetry full=66、partial=6、unavailable=0 |
| Rich 历史审计 | 72 条最终结果中 22 条 setup_failed 均有 worker-stage provider 504 证据；旧 worker-attempt 审计保持 `limited` |
| Multi-Agent Q1 / Plan–Execute Q1 | 两个跨仓库维度均为 `divergent` |
| Plan–Execute Q2 | `inconclusive`；相同的“不确定”标签不算方向得到复现 |
| 总体比较 / 严格审计 | `direction_comparison=inconclusive`；`strict_audit_status=legacy-audit-limited` |

Rich 与 Click 是两个独立实验批次，不合并为一个样本，不计算跨仓库总成功率。两个 Q1 的方向不同只描述这些固定 Case 的结果；本阶段不主张统计显著、普适性、因果解释或严格复制。Rich 的 provider 504 不记为 Agent 任务失败；fixture、reference patch、zero-agent 验收和 provider smoke 不记为 Agent 成绩。ReAct 只作独立 canary，不参与两个正式架构的 Q1/Q2 判定。

## 验证与交付

提交前的完整项目测试为 **468 passed、2 skipped、0 failed**；两项 skip 均为本机 Windows 符号链接能力限制。Ruff、diff 检查、Rich 三份冻结 SHA-256、72-slot 账目和身份复算、相关产物的安全扫描均通过。Click 的六份稳定分析产物及最终比较三份产物在不同绝对路径、时区和 locale 下逐字节一致。Task 20 的报告层适配器位于冻结框架树之外，避免改变正式 Click 身份；它只用哈希绑定的完成态摘要，不读取原始 manifest。

交付范围包括本总结、[详细阶段报告](MOKIOCLAW_MULTI_PROJECT_SNAPSHOT_STABILITY_REPORT_2026-09-22.md)、[技术进度记录](TECHNICAL_IMPLEMENTATION_PROGRESS.md)、批准的设计与实施计划完成标记、报告层适配器及测试，以及[最终比较](../evals/reports/cross-repo-rich-click-20260926-01/comparison.md)所在目录中的四个文件。初版比较、原始 Rich/Click 批次和其他 ignored 实验证据保持原位，不批量加入 Git。用户本轮授权本地提交；未授权 push 或修改远端。
