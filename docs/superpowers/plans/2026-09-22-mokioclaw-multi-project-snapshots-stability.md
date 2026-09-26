# MokioClaw Multi-Project Snapshot Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改写 Rich v14.3.4 冻结证据的前提下，完成 provider/telemetry/worker-attempt 稳定性强化，建立 Click 8.4.2 独立快照与自适应 36/72-run 实验，并以逐仓库分析后再比较的方式产出可审计、不可择优的方向性结论。

**Architecture:** 保留 `CaseSpec → EvalRunner → Batch Runner → Grader` 主链，但把一次正式槽位、一次 worker 启动、一次 Agent 内部尝试、一次逻辑模型调用和一次传输尝试拆成五层可复算身份。Provider 分类、per-call journal、append-only worker ledger、canonical fingerprint 和停止控制器先离线完成；Click 使用独立 vendor/image/case/schedule/batch root；分析器只读取冻结 analysis spec 与规范化 artifact，Rich–Click comparator 只读取两个仓库各自完成的机器分析，不读取或合并原始 manifest。

**Tech Stack:** Python 3.13.15、dataclasses/Enum、LangChain/OpenAI adapter、Typer/argparse、PyYAML、pytest、Ruff、Docker、SHA-256 canonical JSON、Windows `os.replace`/`fsync`。

**Spec:** `docs/superpowers/specs/2026-09-22-mokioclaw-multi-project-snapshots-stability-design.md`（已批准；实施者必须先完整阅读，本计划所有规则均以该规格为准）

## Global Constraints

- 基线必须保持 `main` 与 `origin/main` 同为 `2c68a12fc49940101ea56e8ac967d6558e74109e`；若新会话开始时不同，先报告差异，不自动 reset、pull、checkout 或清理。
- Rich 根 `evals/reports/snapshots-20260920/` 和 `.superpowers/` 是 ignored 审计证据。任何清理、移动、worktree 或批量 Git 操作前同时检查 tracked、untracked、ignored；不得删除、覆盖或批量纳入 Git。
- Rich 三份冻结分析 SHA-256 必须始终为：`B99BA64320362DED877777CA4BE9130BC08A8619A1BCB5CC3910D4E0721CABEB`、`167FC8EC4B48B03A3FD2F8248E0F653B085DF92498A78CFC4BF23571C98EA4FB`、`6F84A1281593994E7F9FF37F250F00DF366EB7BFEE14C0EC6ED8C638D1D069F2`。
- 不读取、打印或复制 `.env` 的秘密值。API Key、Authorization、完整 endpoint、query、prompt、response、headers、payload 不得进入 Case、config、journal、ledger、trace、报告、fingerprint 或容器参数。只允许持久化脱敏 provider host。
- SDK benchmark/smoke/probe 路径固定 `max_retries=0`。无法观察底层 transport 或发现隐式重试时，配置直接不准入。
- `scheduled_run_id`、`worker_attempt_id`、`agent_attempt_count`、`model_call_index`、`transport_attempt_index` 不得混用。每个正式槽位最多启动一个 worker；失败、provider 5xx、超时或 budget exhaustion 后不得补跑、删除或替换。
- Click 固定 release `8.4.2`、commit `b2e30a175449cfda909ee4fbf4a29a6a071cad53`、BSD-3-Clause；PyPI sdist 交叉校验 SHA-256 固定为 `9a6cea6e60b17ebe0a44c5cc636d94f09bd66142c1cd7d8b4cd731c4917a15f6`。
- Click 与 Rich 的设计材料、vendor、image、Case、schedule、fingerprint、batch root、thresholds 和分析输出完全独立；不得向 Rich 72-run 批次追加任何行。
- 自适应门固定：两个不同 `subsystem_id` 的 PASS 才进入 72-run；审查至少四个候选仍只有一个可用 Case 时进入 36-run；零 Case 时停止 Click，HTTPie 必须另做设计并另行批准。
- G1 才授权 R1，G2 只授权 R2，G3 只授权 R3。G2/G3 只展示完整性、安全性和稳定性，不展示资源格、逐 Case、逐架构效果、Q1/Q2、budget-priority、deep progress 或 ReAct drift。
- Provider smoke 是非 Benchmark，不算 Agent 成绩；fixture red-green、reference patch、zero-agent Case 验收也不算 Agent 成绩。
- 未达到停止阈值的 provider transport 行保留在 scheduled denominator；触发停止后，未启动槽位写 `not_started`，批次封存为 `pilot/incomplete`，只生成一次 incomplete/inconclusive 结案分析。
- 单 Case `n=3` 只允许描述性计数和 delta，不得产生/缩放 S/E/P/Relief/state/Q1/Q2。
- 跨仓库不得混合 pooled counts、成功率或 denominator；Rich 冻结的 Plan–Execute Q2 为 inconclusive，因此本阶段顶层 `direction_comparison` 的机械上限也是 `inconclusive`。
- Windows 测试统一显式设置 `$env:PYTHONPATH=(Resolve-Path 'src')`，并为每次 pytest 使用独立 `--basetemp`。所有命令使用 `D:\envs\codeagent\Scripts\python.exe`。
- 不使用 subagent，除非用户在实施会话明确授权。默认采用 `superpowers:executing-plans` 的 Native 方式。
- 不创建 worktree、不提交、不 push、不修改远端，除非用户分别明确授权。下述每个“提交检查点”仅是建议边界；未获授权时跳过 commit，但继续保留精确变更清单。
- 实施范围不包含 BM25、Embedding、Rerank、AST Index、README 产品化、MCP、FastAPI/SSE 或服务化。

## Review Focus

1. 首次 provider 504 也必须留下 `error` call file、transport file、结构化 `provider_transport` 和 `before_first_model_response`，token 为 null 而非 0。
2. 成功响应缺少 usage 必须触发稳定性停止；timeout/budget/kill 后已完成调用的 usage 仍可恢复为 partial。
3. worker launch 先写 append-only launch event，再闭合 terminal event；固定 Case×架构×repeat 目录不得再覆盖旧 attempt。
4. immediate-stop kind 与 provider transport 阈值必须分开；两 Case每轮 3 个 transport、单 Case每轮 2 个 transport 才是累计停止门，连续两个始终停止。
5. fingerprint 的 identity、metadata-only、per-worker-attempt 三类字段必须分离；绝对路径、时间、hostname 不得污染 hash。
6. `budget_priority_pattern` 必须包含 `Relief(T)`；`Relief(B)=true` 且 `Relief(T)=false` 时必须为 false。
7. provider qualification/sensitivity 按 architecture 独立；ReAct 不得取消 Multi-Agent/Plan–Execute 的资格，也不进入 Q1/Q2 穷举。
8. 复制 fixture 到不同绝对路径并切换 timezone/locale 后，所有 hash-critical 分析产物必须字节一致。
9. Rich legacy sidecar 只能补充审计，不能改写三份冻结分析；22/22 worker-stage 504、工具数 `0×19,13×1,18×1,38×1` 必须机械复算。
10. Comparator 遇到两侧相同的 inconclusive Q2 时，`same_label=true`，但维度和顶层仍为 `inconclusive`。

## File Structure

| 文件 | 职责 |
|---|---|
| `evals/specs/resource-analysis-v1.json`（新） | 冻结资源格、counter、状态、Q1/Q2、provider sensitivity、单 Case 与 canonical 输出规则 |
| `src/mokioclaw/evals/analysis_spec.py`（新） | 加载、校验和 hash 冻结 analysis spec |
| `src/mokioclaw/evals/provider_failures.py`（新） | Provider/worker/config/sandbox 失败分类、phase 与脱敏 |
| `src/mokioclaw/providers/call_journal.py`（新） | crash-consistent model-call/transport-attempt 文件与 coverage 复算 |
| `src/mokioclaw/providers/usage.py`（改） | callback 生命周期接入 journal，同时保留兼容 usage 汇总 |
| `src/mokioclaw/providers/openai_provider.py`（改） | 显式 `max_retries=0`、SDK/config identity 和 callback 接线 |
| `src/mokioclaw/evals/models.py`（改） | 五层身份、结构化失败和 telemetry coverage 字段 |
| `src/mokioclaw/evals/{worker,runner,report}.py`（改） | 最小崩溃 artifact、失败传播、脱敏报告、coverage 恢复 |
| `src/mokioclaw/evals/worker_ledger.py`（新） | append-only launch/terminal ledger、不可覆盖 attempt 目录 |
| `src/mokioclaw/evals/experiment_identity.py`（新） | canonical fingerprint v4 与 identity drift 校验 |
| `src/mokioclaw/evals/protocol.py`（新） | 自适应 Case 门、停止控制器、G1/G2/G3 安全摘要 |
| `src/mokioclaw/evals/{batch,snapshot_schedule,cli}.py`（改） | 预注册 schedule、唯一槽位、轮次执行和硬 gate |
| `src/mokioclaw/evals/snapshot_analysis.py`（改） | spec-driven Click 独立分析、determinism、provider sensitivity、ReAct canary |
| `src/mokioclaw/evals/rich_legacy_audit.py`（新） | Rich 只读 sidecar 机械审计 |
| `src/mokioclaw/evals/cross_repo_comparison.py`（新） | 三维方向比较与独立 strict audit status |
| `evals/images/click/**`、`evals/repos/templates/click/**`（新） | Click 8.4.2 固定快照、镜像、lock 与 provenance |
| `evals/candidates/click/**`（新） | 四类候选的冻结 subsystem、red/green 证据和拒绝理由 |
| `evals/cases/click-*.yaml`、`evals/repos/{mutations,reference-patches}/click-*.patch`（新） | 自适应门最终冻结的 1 或 2 个 Click Case |
| `evals/graders/cases/click/**`（新） | 不进入 Agent workspace 的 Click hidden behavior tests |
| `tests/providers/test_{usage,call_journal,openai_provider}.py`（新/改） | retry、call/transport journal、usage coverage |
| `tests/evals/test_{provider_failures,worker_ledger,experiment_identity,protocol}.py`（新） | 分类、账目、fingerprint、停止与 gate |
| `tests/evals/test_{runner,batch,telemetry,snapshot_analysis}.py`（改） | 主链与分析回归 |
| `tests/evals/test_{rich_legacy_audit,cross_repo_comparison,click_snapshot,click_cases}.py`（新） | 历史审计、比较器与 Click 零 Agent-run 验收 |
| `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`（改） | 阶段进度与 gate 记录入口 |
| `docs/MOKIOCLAW_MULTI_PROJECT_SNAPSHOT_STABILITY_REPORT_2026-09-22.md`（新） | 最终阶段报告与 non-claims |

---

### Task 1: 冻结 analysis spec 并锁定公式回归

**Files:**
- Create: `evals/specs/resource-analysis-v1.json`
- Create: `src/mokioclaw/evals/analysis_spec.py`
- Modify: `src/mokioclaw/evals/snapshot_analysis.py`
- Modify: `tests/evals/test_snapshot_analysis.py`
- Create: `tests/evals/test_analysis_spec.py`

- [x] **Step 1: 先写 spec schema、hash 与 budget-priority 失败测试**

测试必须覆盖：四格 A/B/T/J、`n=6`/`n=3` 分支、冻结 non-resource family、deep rules、Q1/Q2、per-architecture sensitivity、stable ordering；并追加：

```python
def test_budget_priority_requires_relief_on_both_axes() -> None:
    anchor = counts(ts=0, bud=4, tout=0, res=4, deep=0)
    budget = counts(ts=0, bud=0, tout=2, res=2, deep=3, tool_ge_45=2)
    timeout = counts(ts=0, bud=2, tout=2, res=4, deep=0)
    joint = counts(ts=2, bud=0, tout=1, res=1, deep=3, tool_ge_45=2)
    result = map_q1({"A": anchor, "B": budget, "T": timeout, "J": joint})
    assert result["signal"] == "budget-axis directional signal"
    assert result["budget_priority_pattern"] is False
```

- [x] **Step 2: 运行失败测试**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/evals/test_analysis_spec.py tests/evals/test_snapshot_analysis.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t01'
```

Expected: FAIL；spec/loader 不存在，旧 `map_q1` 漏掉 `Relief(T)`，旧 counter 名仍为 `over40`。

- [x] **Step 3: 实现 frozen spec 与严格 loader**

`analysis_spec.py` 提供：

```python
@dataclass(frozen=True)
class LoadedAnalysisSpec:
    payload: dict[str, Any]
    canonical_bytes: bytes
    sha256: str

def canonical_json_bytes(payload: Any) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (text + "\n").encode("utf-8")

def load_analysis_spec(path: Path) -> LoadedAnalysisSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_analysis_spec(payload)
    canonical = canonical_json_bytes(payload)
    return LoadedAnalysisSpec(payload, canonical, hashlib.sha256(canonical).hexdigest())
```

JSON 明确编码 A=`40/600`、B=`80/600`、T=`40/900`、J=`80/900`，`tool_ge_45`，公式常量 2/3/5-of-6，所有允许标签和 precedence；未知/缺失字段拒绝，不静默默认。

- [x] **Step 4: 修正旧公式但不重算 Rich**

将 `budget_priority_pattern` 改为：

```python
relief_b and relief_t and budget["bud"] == 0 and timeout["bud"] >= 1
```

仅修改代码与测试；不得调用 analyzer 写入 `snapshots-20260920`。

- [x] **Step 5: 运行通过并核对 Rich hash 未变**

运行 Task 1 测试后，用 `Get-FileHash` 核对三份冻结 hash。

- [x] **Step 6: 提交检查点（仅获授权时；本次未授权，已按 Global Constraints 跳过）**

精确 add Task 1 的五个文件，检查 staged names 后建议提交：`feat(eval): freeze resource analysis specification`。

---

### Task 2: Provider 失败分类、phase 与脱敏

**Files:**
- Create: `src/mokioclaw/evals/provider_failures.py`
- Modify: `src/mokioclaw/evals/models.py`
- Create: `tests/evals/test_provider_failures.py`

- [x] **Step 1: 写完整映射表测试**

覆盖 401/403、402、429、其他 4xx、500/502/503/504、TLS/DNS/connect/read/protocol、provider-boundary unknown、worker/config/sandbox；同一个异常只能得到一个 `failure_kind`。Phase 用 `(successful_model_responses, tool_activity_count)` 机械计算三个互斥值。

互斥 phase 的精确输出固定为：尚无成功模型响应时 `before_first_model_response`；已有成功模型响应但尚无工具活动时 `after_model_response_before_first_tool`；已有至少一次工具活动时 `after_tool_activity`。

- [x] **Step 2: 写秘密脱敏测试**

异常文本中嵌入假的 key、Authorization、带 query 的假 endpoint、请求/响应正文标记，断言结果只保留异常类、HTTP 状态和 provider host，不保留任一敏感片段；测试输入在内存中构造，不把完整 endpoint 或 query 写入提交产物。

- [x] **Step 3: 运行失败测试**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/evals/test_provider_failures.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t02'
```

- [x] **Step 4: 实现 typed result**

```python
class FailureKind(str, Enum):
    PROVIDER_TRANSPORT = "provider_transport"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_BILLING = "provider_billing"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_UNKNOWN = "provider_unknown"
    WORKER_INTERNAL = "worker_internal"
    CONFIG = "config"
    SANDBOX = "sandbox"

@dataclass(frozen=True)
class FailureClassification:
    failure_kind: FailureKind
    provider_status: int | None
    provider_phase: str | None
    retryable: bool
    sanitized_reason: str
```

分类器必须显式接收 `at_provider_boundary`，不通过异常字符串把 provider unknown 吞成 worker internal。

- [x] **Step 5: 运行通过；提交检查点未获授权，已跳过**

建议提交：`feat(eval): classify and sanitize provider failures`。

---

### Task 3: Crash-consistent model-call 与 transport journal

**Files:**
- Create: `src/mokioclaw/providers/call_journal.py`
- Create: `tests/providers/test_call_journal.py`
- Modify: `src/mokioclaw/evals/telemetry.py`
- Modify: `tests/evals/test_telemetry.py`

- [x] **Step 1: 写原子状态机与崩溃恢复测试**

测试固定路径 `usage-calls/000001.json` 与 `transport-attempts/000001-000001.json`，覆盖 `in_flight → completed`、`in_flight → error`、遗留 in-flight、唯一 tmp、坏 tmp 隔离、并发序号不可复用、文件可机械复算。

- [x] **Step 2: 写 coverage 测试**

覆盖 `full`、`partial`、`unavailable` 和五个原因：`provider_error_before_usage`、`provider_usage_missing`、`worker_killed_before_first_model_response`、`worker_killed_during_call`、`usage_parse_error`。Token 缺失断言为 null，不是 0。

- [x] **Step 3: 运行失败测试**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/providers/test_call_journal.py tests/evals/test_telemetry.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t03'
```

- [x] **Step 4: 实现 durability primitive 与 journal API**

```python
def atomic_json_replace(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory_best_effort(path.parent)
```

`CallJournal` 的公开 API 固定为 `begin_model_call() -> int`、`begin_transport_attempt(model_call_index) -> int`、`complete_model_call(model_call_index, usage, source) -> None`、`fail_model_call(model_call_index, classification) -> None` 和 `summarize() -> TelemetrySummary`。

禁止记录 prompt/response/header/endpoint；audit 时间写单独非 hash-critical 文件。

- [x] **Step 5: 运行通过并做 kill/in-flight fixture 复算；提交检查点未获授权，已跳过**

建议提交：`feat(eval): add crash consistent provider call journal`。

---

### Task 4: Provider callback 接线与显式零重试

**Files:**
- Modify: `src/mokioclaw/providers/usage.py`
- Modify: `src/mokioclaw/providers/openai_provider.py`
- Modify: `src/mokioclaw/evals/{adapters,plan_execute_adapter,react_adapter}.py`
- Modify: `tests/test_usage.py`
- Create: `tests/providers/test_openai_provider.py`
- Modify: `tests/evals/test_adapters.py`

- [x] **Step 1: 写 callback 生命周期测试**

用 fake LangChain response/error 驱动 start/end/error；证明每个逻辑调用只有一个 call index，成功 usage 写 completed，504 写 error，连续调用序号稳定。成功 response 无 usage 必须被标成 `provider_usage_missing` gate failure。

- [x] **Step 2: 写 model config 测试**

mock `ChatOpenAI`，断言 `temperature=0`、`max_retries=0`、callback 注册、base URL 不进入持久化 payload；不得在测试输出中打印 fake key。

- [x] **Step 3: 运行失败测试**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/test_usage.py tests/providers/test_openai_provider.py tests/evals/test_adapters.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t04'
```

- [x] **Step 4: 使用 ContextVar 绑定每个 worker 的 journal**

保留旧 `start_usage_collection()/sum_usage()` 兼容调用，但真实 eval adapter 必须使用 journal summary 作为权威来源；callback 的 `on_llm_start/on_llm_end/on_llm_error` 完整闭合文件。记录 SDK 包名、版本、adapter config version 与 retry policy，供 fingerprint 使用。

- [x] **Step 5: 运行通过；提交检查点未获授权，已跳过**

建议提交：`feat(eval): wire zero retry provider telemetry`。

---

### Task 5: Worker/runner 最小 artifact 与结构化终态

**Files:**
- Modify: `src/mokioclaw/evals/models.py`
- Modify: `src/mokioclaw/evals/worker.py`
- Modify: `src/mokioclaw/evals/runner.py`
- Modify: `src/mokioclaw/evals/report.py`
- Modify: `tests/evals/test_{runner,telemetry,report}.py`

- [x] **Step 1: 写三层身份与中断路径测试**

`CaseResult`/worker artifact 明确含 `scheduled_run_id`、`worker_attempt_id`、`agent_attempt_count`；保留读取旧 `attempts` 的兼容层，但新输出不得把它用于 worker retry。覆盖首次响应前 504、已有响应但无 tool、已有 tool、timeout、budget、worker internal、config、sandbox。

- [x] **Step 2: 写脱敏与 token recovery 测试**

断言 runner 从 call files 恢复 full/partial/unavailable、call/transport counts 和 reason；`failure_reason` 与 markdown 只能是 sanitized reason/provider host。

- [x] **Step 3: 运行失败测试并实施**

worker 启动后立即创建最小 artifact；异常路径在退出前尽最大可能闭合 journal 和 `run-artifacts.json`。`_apply_worker_metrics` 以 journal summary 为准，旧 in-memory usage 仅作兼容 fallback。

- [x] **Step 4: 运行聚焦回归**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/evals/test_runner.py tests/evals/test_telemetry.py tests/evals/test_report.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t05'
```

- [x] **Step 5: 提交检查点未获授权，已跳过**

建议提交：`feat(eval): preserve structured interrupted run evidence`。

---

### Task 6: Append-only worker-attempt ledger 与不可覆盖目录

**Files:**
- Create: `src/mokioclaw/evals/worker_ledger.py`
- Modify: `src/mokioclaw/evals/batch.py`
- Create: `tests/evals/test_worker_ledger.py`
- Modify: `tests/evals/test_batch.py`

- [x] **Step 1: 写账目不变量失败测试**

覆盖：launch 先于 terminal；同一 slot 第二次 launch 拒绝；每个 attempt 目录唯一；terminal 只能闭合已 launch ID；旧行不能覆盖；停止后剩余 schedule 写 `not_started`；`agent_attempt_count` 变化不生成新 worker。

- [x] **Step 2: 定义稳定 ID 与 ledger event**

```python
scheduled_run_id = sha256(canonical_json_bytes({
    "case_id": case_id, "architecture": architecture,
    "cell": cell, "repeat": repeat, "schedule_sha256": schedule_sha256,
})).hexdigest()
```

`worker_attempt_id` 每次 launch 唯一且只出现在 per-attempt/audit 数据；目录固定为 `worker-attempts/{worker_attempt_id}/`。Ledger 用 append-only JSONL 的 `launch` 与 `terminal` 两种 event，每次 append 后 flush+fsync。

- [x] **Step 3: 改造 batch manifest**

result manifest 每个 executed slot 只出现一次，保存相对 attempt path、结构化 status/failure/coverage 和 fingerprint hash。恢复逻辑不得“跳过后继续补齐”正式 pilot；只有从未 launch 且批次仍 open 的下一预注册槽位可启动。

- [x] **Step 4: 运行测试**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/evals/test_worker_ledger.py tests/evals/test_batch.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t06'
```

- [x] **Step 5: 提交检查点未获授权，已跳过**

建议提交：`feat(eval): make worker attempt accounting append only`。

---

### Task 7: Canonical experiment fingerprint v4

**Files:**
- Create: `src/mokioclaw/evals/experiment_identity.py`
- Modify: `src/mokioclaw/evals/batch.py`
- Create: `tests/evals/test_experiment_identity.py`
- Modify: `tests/evals/test_batch.py`

- [x] **Step 1: 写 identity drift 矩阵测试**

Framework/provider/repository/environment/experiment 每一域各改一个字段都拒绝；metadata time/hostname/path 改变不影响 identity hash；worker attempt ID 不进入 identity；数组顺序按字段规范 canonicalize；绝对路径出现即拒绝。

- [x] **Step 2: 写 secret/schema 测试**

扫描 canonical bytes 与 audit payload，不得含 fake API key、scheme/path/query/Authorization；provider 只留 adapter ID 和 host。Schema version 固定 4，旧 v3 不允许续跑新 Click root。

- [x] **Step 3: 实现五域 builder**

输出 `experiment-fingerprint.json`（hash-critical identity）与 `fingerprint-audit.json`（非 hash-critical metadata）。Identity 完整覆盖 spec §11.1，并记录 `analysis_spec_sha256`、schedule hash、Case set hash、image/lock/Dockerfile/resource envelope。

- [x] **Step 4: 每次 worker launch 前复核 hash**

任何漂移调用 Task 8 stop controller 封存 batch，不启动 worker。

- [x] **Step 5: 运行测试；授权后提交检查点**

建议提交：`feat(eval): add canonical experiment fingerprint v4`。

---

### Task 8: 自适应门、停止控制器、schedule 与 gate-safe 摘要

**Files:**
- Create: `src/mokioclaw/evals/protocol.py`
- Modify: `src/mokioclaw/evals/snapshot_schedule.py`
- Modify: `src/mokioclaw/evals/batch.py`
- Modify: `src/mokioclaw/evals/cli.py`
- Create: `tests/evals/test_protocol.py`
- Modify: `tests/evals/test_snapshot_schedule.py`

- [x] **Step 1: 写自适应选择表测试**

固定优先级四候选：两个不同 subsystem PASS→2 Case/72；多个同 subsystem PASS 且至少四候选审完→1 Case/36；只有一个 PASS→36；零 PASS→stop；不能在看到 Agent 结果后重选。

- [x] **Step 2: 写停止规则测试**

所有 immediate kinds 首次停止；transport 连续 2 停止；两 Case一轮累计 3 停止；单 Case一轮累计 2 停止；单个未达门 5xx 保留并继续；missing usage、ledger/fingerprint/artifact drift 立即停止。

- [x] **Step 3: 写 G2/G3 信息泄漏测试**

安全摘要只含 started/closed/not_started、failure kind/phase 总数、coverage、全轮 token totals、完整性与 stop status。递归扫描 key/value，拒绝 architecture、case、cell、Q1/Q2、budget-priority、deep、ReAct drift 等效果字段。

- [x] **Step 4: 冻结 seed `20260922` 的 36/72 schedules**

schedule 文件包括 round、stable slot ID、架构、Case、cell、repeat 和 base permutation；R2/R3 循环错位。已存在且 hash/seed/protocol 不同则拒绝覆盖。

- [x] **Step 5: 运行测试；授权后提交检查点**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest tests/evals/test_protocol.py tests/evals/test_snapshot_schedule.py tests/evals/test_batch.py -v --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-t08'
```

建议提交：`feat(eval): enforce adaptive protocol and hard stops`。

---

### Task 9: Spec-driven Click analyzer、provider sensitivity 与确定性

**Files:**
- Modify: `src/mokioclaw/evals/snapshot_analysis.py`
- Modify: `tests/evals/test_snapshot_analysis.py`
- Create: `tests/evals/fixtures/snapshot-analysis/**`

- [x] **Step 1: 写 golden vectors**

覆盖 state precedence、Q1 五分支、Q2 三布尔量、N 不影响 Relief、含 Relief(T) 的 pattern、两 Case n=6、单 Case n=3 禁止正式标签。

- [x] **Step 2: 写 per-architecture qualification/sensitivity fixtures**

Multi-Agent 与 Plan–Execute 分开构造 5/6 合格、少于 5/6 clean、attrition range 大于 1、缺 ledger、补全后结论不变、补全后 Q1 翻转、补全后 Q2 翻转；ReAct attrition 不改变前两者。

- [x] **Step 3: 实现有界枚举**

每个 provider-failed slot 只枚举 spec 允许的五种终态、deep 0/1、B/J 的 tool_ge_45 0/1；按 architecture 单独笛卡尔积并收集候选 state/Q1/pattern/Q2 booleans。只有集合大小为 1 才 qualified。

最低资格门失败时对应 architecture 输出 `provider-attrition / inconclusive`；最低门通过但补全集合不唯一时输出 `provider-sensitive / inconclusive`，不得把 observed provider rows 当作全零正式结论。

- [x] **Step 4: 实现稳定输出**

生成 `thresholds.json`、`per-case.json`、`pooled.json`、`provider-sensitivity.json`、`react-canary.json`、`report.md`；时间、hostname、绝对路径只进 `analysis-audit.json`。

- [x] **Step 5: 做跨路径/时区/locale 字节测试**

把同一 fixture 复制到两个不同绝对目录，分别设置不同 `TZ`/locale 环境，逐文件比较 bytes 和 SHA-256。Windows 不支持的 locale 只能作为 capability skip，路径 determinism 仍必须执行。

- [x] **Step 6: 运行测试；授权后提交检查点**

建议提交：`feat(eval): add deterministic provider sensitive analysis`。

---

### Task 10: Rich legacy audit sidecar

**Files:**
- Create: `src/mokioclaw/evals/rich_legacy_audit.py`
- Create: `tests/evals/test_rich_legacy_audit.py`
- Output only: `evals/reports/snapshots-20260920/analysis/rich-legacy-audit.json`

- [x] **Step 1: 写只读 fixture 测试**

输入四个 final manifest 和对应 result，复算 72 行、22 setup_failed、22/22 worker-stage 504、工具分布、token coverage，并固定 `historical_worker_attempt_completeness="limited"`。

- [x] **Step 2: 实现 sidecar generator**

只允许创建/原子替换 sidecar；运行前后计算三份冻结分析 hash，并在任一变化时失败。Sidecar 不进入 Rich 方向公式。

- [x] **Step 3: 在真实 Rich 根执行并复核**

执行是只读审计加一个新 sidecar，不修改 manifest/results/三份分析。输出中不包含绝对路径或秘密。

- [x] **Step 4: 运行测试；授权后提交代码检查点**

建议提交只含代码和测试：`feat(eval): add rich legacy audit sidecar`；ignored sidecar 作为外部审计证据保留，不擅自 add。

---

### Task 11: Rich–Click 双轨 comparator

**Files:**
- Create: `src/mokioclaw/evals/cross_repo_comparison.py`
- Create: `tests/evals/test_cross_repo_comparison.py`

- [x] **Step 1: 写输入边界测试**

Comparator 只接受 Rich/Click 已完成机器分析、Click sensitivity、Rich legacy sidecar 和 hash manifest；若传入 raw manifest 或 pooled count 合并请求则拒绝。

- [x] **Step 2: 写三维结果真值表**

固定 `multi_agent_q1`、`plan_execute_q1`、`plan_execute_q2`；覆盖 consistent/divergent/inconclusive/not_applicable、aggregate precedence、Q1 secondary divergence，以及 `strict_audit_status` 的四个精确值：`strict-audit-comparable`、`legacy-audit-limited`、`click-audit-limited`、`both-audit-limited`。

- [x] **Step 3: 锁定已知 Q2 上限**

测试两侧 Q2 都是 `no time-wall migration signal / inconclusive` 时：

```python
assert dimension["same_label"] is True
assert dimension["directional_corroboration"] is False
assert dimension["result"] == "inconclusive"
assert comparison["direction_comparison"] == "inconclusive"
```

- [x] **Step 4: 实现 deterministic JSON/Markdown**

生成 `comparison.json` 与 `comparison.md`，稳定排序且不含执行时刻/绝对路径；audit metadata 分离。

- [x] **Step 5: 运行测试；授权后提交检查点**

建议提交：`feat(eval): compare repositories without pooling counts`。

---

### Task 12: S0 全量离线验证与基建冻结

**Files:**
- Modify: `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`

- [x] **Step 1: 运行非 Docker 全套与 Ruff**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest -m 'not docker' -q --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-s0'
& 'D:\envs\codeagent\Scripts\python.exe' -m ruff check src tests
```

- [x] **Step 2: 运行 secret fixture scan、determinism test、Rich hash check**

扫描对象只包括本阶段新增 artifact 和测试 fake secret；不得读取 `.env` 内容。确认 git diff 不包含 Rich 原始产物、旧 Case/image、README/MCP/service/retrieval 改动。

- [x] **Step 3: 更新 S0 记录**

记录命令、通过/跳过数、capability skips、未解决风险和精确变更文件。不得写“阶段完成”除非所有 S0 acceptance 都有证据。

- [x] **Step 4: 用户检查点**

报告 S0 结果。此检查点不等于 G1，也不授权 provider smoke 或真实 Agent runs。

---

### Task 13: Vendor Click 8.4.2、镜像与 upstream 准入（S1）

**Files:**
- Create: `evals/repos/templates/click/**`
- Create: `evals/repos/templates/click/PROVENANCE.md`
- Create: `evals/images/click/{Dockerfile,requirements.in,requirements.lock}`
- Create: `tests/evals/test_click_snapshot.py`

- [x] **Step 1: 在任何下载前复核工作树与 ignored 证据**

若需要网络下载或 Docker build，使用环境的权限机制请求批准；不要从 `.env` 读取凭据。机械复核 tag→commit、GitHub archive hash、PyPI sdist hash、license hash。

- [x] **Step 2: 按 allowlist vendor**

保留 `src/click/`、`tests/`、`pyproject.toml`、`LICENSE.txt`、`CHANGES.rst` 和测试必需资源；裁剪 docs/CI/dev/examples。所有保留/裁剪/适配和 hash 写 provenance。

- [x] **Step 3: 创建离线 image**

锁定 base digest、dependency hashes、Dockerfile hash；不得安装另一份 Click。容器内 `PYTHONPATH=/workspace/src`，`network none`、1 CPU、512 MiB、128 pids、只读 rootfs、受限 `/tmp`。

- [x] **Step 4: 写并运行 snapshot acceptance**

断言 `click.__file__` 位于 `/workspace/src/click/`；upstream suite 或预注册确定性子集连续三次通过；agent-visible pytest/repro 每次 ≤90s。若使用 metadata-only fallback，必须先删除 site-packages Click 代码并冻结该决定。

- [x] **Step 5: S1 审计与授权后提交检查点**

建议提交：`feat(eval): vendor click 8.4.2 snapshot environment`。

---

### Task 14: 四候选 zero-agent 审查与自适应 Case 冻结（S2）

**Files:**
- Create: `evals/candidates/click/01-option-parsing/**`
- Create: `evals/candidates/click/02-argument-conversion/**`
- Create: `evals/candidates/click/03-help-rendering/**`
- Create: `evals/candidates/click/04-cli-runner-io/**`
- Create/Modify after selection: `evals/cases/click-*.yaml`
- Create/Modify after selection: `evals/repos/{mutations,reference-patches}/click-*.patch`
- Create/Modify after selection: `evals/graders/cases/click/**`
- Create: `tests/evals/test_click_cases.py`

- [x] **Step 1: 在任何 red/green 前冻结 subsystem IDs**

四个候选目录分别只允许 `option-parsing`、`argument-conversion`、`help-rendering`、`cli-runner-io`。每个 `candidate.json` 在测试前记录行为、上游所有权、预计 mutation surface 和 acceptance commands；之后不得改 subsystem。

- [x] **Step 2: 对四个候选逐一执行同一准入矩阵**

每个候选都必须记录 PASS/REJECT 及原因。Bug/fix 两态 upstream-owned tests 绿；public pytest、独立 repro、hidden behavior 在 bug 红/fix 绿；task 不泄漏文件/修法；定位链≤约10步；reference patch≤40 changed lines；broken edit 同时打红两个 public 入口；连续三次≤90s。

- [x] **Step 3: 验证 protected manifest**

覆盖 tests、repro、license、provenance、absent hooks、symlink 与 cache semantics；hidden tests 不进入 Agent workspace。

- [x] **Step 4: 机械运行自适应选择器**

按固定顺序选择第一个 PASS 为 Case 1，随后第一个不同 subsystem PASS 为 Case 2。输出只允许：`two-case-72`、`single-case-36`、`no-click-case-stop`。不得为了 72-run 降低门槛。

- [x] **Step 5: 运行全部 zero-agent Case 测试**

这些测试与 reference patch 结果明确标注为 fixture validation，不计 Agent 成绩。

- [x] **Step 6: S2 用户检查点**

若零 Case，停止并提交 Click rejection evidence；不得自动转 HTTPie。若 1/2 Case，报告预算分支但不运行 provider smoke/真实 Agent。

---

### Task 15: 冻结 Click batch identity 与离线 preflight

**Files:**
- Create: `evals/reports/snapshots-click-842-20260922/schedule.json`
- Create: `evals/reports/snapshots-click-842-20260922/experiment-fingerprint.json`
- Create: `evals/reports/snapshots-click-842-20260922/fingerprint-audit.json`
- Create: `evals/reports/snapshots-click-842-20260922/preflight.json`

- [x] **Step 1: 选择全新独立 batch root**

日期一旦冻结即写入进度记录。不得复用 smoke、Rich 或已封存 pilot root。

- [x] **Step 2: 生成 36 或 72 schedule**

Case set 来自 Task 14 机械输出；seed 固定 `20260922`；四格和三架构全保留。

- [x] **Step 3: 生成并复核 fingerprint**

验证 framework/provider/repository/environment/experiment 五域、analysis spec hash、schedule hash、Case set hash、SDK retry=0、transport observable。每个 hash 都从文件机械计算，不手录猜测。

- [x] **Step 4: 离线 preflight**

验证 image/source resolution、全部 Case acceptance、ledger 空状态、manifest 空状态、secret scan、analysis dry-run refusal（未完成 batch 不得给正式 Q1/Q2）。

- [x] **Step 5: 封存 identity**

从此任何 identity drift 都必须放弃该 root 并创建新 root，不能原地更新。

---

### Task 16: 12-probe stability smoke 与 G1 材料（S3）

**Files:**
- Create: 独立 ignored smoke root（不得位于 Click batch root）
- Create: G1 audit package under the Click batch root without result-effect fields

- [x] **Step 1: 在首次外部 provider 调用前取得用户明确许可**

许可只覆盖 12 个 smoke probes，不覆盖 R1。未获许可时停在此处。

- [x] **Step 2: 执行固定 12-probe 顺序**

先 6 个 single-call，再按 Multi-Agent→Plan–Execute→ReAct 循环两次。任务固定、短小、不改仓库。每次独立不可覆盖 artifact。

- [x] **Step 3: 机械判定 smoke gate**

全部 artifact 存在；5xx≤1；最后连续8个无5xx；每个成功响应有 usage；每个错误结构化脱敏；call/transport 可审计；retry=0；secret scan 通过；smoke root 隔离。

- [x] **Step 4: 生成 G1 包并停止**

G1 包含 smoke、provider/coverage、secret scan、Click provenance/image/lock、Case 决策、batch root、schedule/fingerprint/spec hashes、36/72 预算和停止规则。等待用户明确批准 R1。

---

### Task 17: G1 后执行 R1，封存并提交 G2

**Files:**
- Append only: Click batch schedule state、worker-attempt ledger、result manifest、per-attempt dirs
- Create: G2 integrity package

- [x] **Step 1: 验证 G1 批准与 identity hash**

没有明确 G1 不启动任何 worker。批准后也只执行 R1 的 12 或 24 槽位。

- [x] **Step 2: 按 schedule 逐槽执行并实时套用 stop controller**

每槽最多一个 worker。触发停止条件时立即停止后续 launch，标记剩余 `not_started`，封存 pilot/incomplete，不在原 root 续跑。

- [x] **Step 3: 生成 G2 安全摘要**

只包含 spec §12.2 允许字段；自动泄漏扫描必须通过。不得运行/展示 provisional analyzer 效果输出。

- [x] **Step 4: 停止并等待 G2**

用户拒绝或未回复时不启动 R2；拒绝本身不授权查看隐藏效果结果。

---

### Task 18: G2 后执行 R2，封存并提交 G3

- [x] **Step 1: 验证 G2 只授权 R2**

- [x] **Step 2: 复核 fingerprint，执行下一 12/24 槽位并实时停止**

- [x] **Step 3: 生成累计 24/48 行的 G3 安全摘要**

仍不得展示效果方向、资源格、Case、架构或 ReAct drift。

- [x] **Step 4: 停止并等待 G3**

没有明确 G3 不启动 R3。

---

### Task 19: G3 后执行 R3 与 Click 最终机械分析

- [x] **Step 1: 验证 G3 与 identity 后执行最后 12/24 槽位**

相同停止规则继续有效；任何正式行不得补跑。

- [x] **Step 2: 闭合账目**

schedule、ledger、manifest、attempt dirs、call/transport files 一一复算；secret scan 与 fingerprint integrity 通过后才允许分析。

- [x] **Step 3: 运行一次最终 analyzer**

完整三轮生成正式 Click 分析；预注册停止则只生成一次 incomplete/inconclusive。单 Case分支只生成描述性输出。

- [x] **Step 4: 验证 provider qualification/sensitivity 和 deterministic hashes**

逐 architecture 检查，ReAct 单独 canary；复制 root fixture 做路径 determinism 复核。

---

### Task 20: 跨仓库比较、阶段报告与最终验收

**Files:**
- Create: `evals/reports/cross-repo-rich-click-20260922/{comparison.json,comparison.md}`
- Modify: `docs/TECHNICAL_IMPLEMENTATION_PROGRESS.md`
- Create: `docs/MOKIOCLAW_MULTI_PROJECT_SNAPSHOT_STABILITY_REPORT_2026-09-22.md`

- [x] **Step 1: 最后复核 Rich hash 与 legacy sidecar**

三份冻结 hash 必须完全不变；sidecar 的 22/22 与 limited 状态可复算。

- [x] **Step 2: 运行 comparator**

只读取完成后的机器分析与 sidecar/hash，不读取 raw manifest。确认三个 required dimensions、顶层 direction 与 strict audit status 分离；预期顶层不会越过 inconclusive。

- [x] **Step 3: 写阶段报告**

明确 Click 36/72 实际分支、scheduled/started/not_started、provider attrition、coverage、限制和 non-claims；不得声称统计显著、普适或严格复制；不得合并两个仓库计数。

- [x] **Step 4: 全项目最终验证**

```powershell
$env:PYTHONPATH=(Resolve-Path 'src')
& 'D:\envs\codeagent\Scripts\python.exe' -m pytest -q --basetemp='D:/MokioAgent/pytest-mokioclaw-plan-final'
& 'D:\envs\codeagent\Scripts\python.exe' -m ruff check src tests
git diff --check
```

另做：secret scan、analysis byte determinism、ledger/fingerprint recomputation、Rich hash check、tracked/untracked/ignored inventory。

- [x] **Step 5: 完成定义审计**

逐条勾选设计 §18。任何未满足项必须明确标为 incomplete/blocked，不能用“主要完成”替代。

- [x] **Step 6: 集成选择（需另行授权）**

报告精确变更与验证结果。只有用户明确要求时才 commit/push/创建或合并分支；否则保持工作树并交付文件路径与审计结果。本轮选择后者：不提交、不推送、不创建或合并分支。

---

## Execution Boundaries

1. Tasks 1–12：纯离线实现与测试，可在 implementation plan 获批后开始；不调用 provider，不做真实 Agent runs。
2. Task 13：可能需要网络下载和 Docker build；按环境权限机制单独批准，不扩大到 provider。
3. Tasks 14–15：零 Agent-run Case 与冻结身份；可执行 fixture/reference validation，但不得记为 Agent 成绩。
4. Task 16：首次 provider smoke 前必须取得明确许可；完成后硬停在 G1。
5. Task 17：只在 G1 后执行 R1，完成后硬停在 G2。
6. Task 18：只在 G2 后执行 R2，完成后硬停在 G3。
7. Tasks 19–20：只在 G3 后执行 R3 和最终效果分析。

## Plan Completion Checklist

- [x] 计划中的路径、字段、枚举、阈值与已批准设计的实验语义一致；Click 完整性第五哈希输入及最终比较日期根的兼容性裁定和保留初版证据见 Task 20 ledger 与阶段报告。
- [x] 没有把 Rich 三份分析重算或改写。
- [x] 没有把 provider failure 改写为 Agent 任务失败。
- [x] 没有通过重试、删除或替换优化结果。
- [x] 没有跨仓库 pooled count。
- [x] G1/G2/G3 和外部 provider smoke 均有明确硬停点。
- [x] 每个实现任务都先有失败测试、再实现、再验证；Task 20 报告性适配器的 RED/GREEN 证据见 ledger。
- [x] 所有提交步骤都明确受用户授权约束；Task 20 未获集成授权，保持未提交。

## Task 20 之后的集成授权记录（2026-09-26）

用户在 Tasks 1–20 的本地验收完成后，另行授权本地 Git 提交并要求完成本阶段总结报告。此授权不包含 push、远端修改、原始 ignored 实验批次的批量纳入、任何新 Agent run 或重算冻结分析。上面的 Step 6 和完成清单记录的是 Task 20 验收时的权限状态；后续精确路径提交是单独的集成动作。
