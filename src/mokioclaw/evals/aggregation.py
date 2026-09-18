from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mokioclaw.evals.attribution import derive_failure_detail


def _rows(batch_dir: Path) -> list[dict[str, Any]]:
    manifest = batch_dir / "manifest.jsonl"
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]


def aggregate_batch(batch_dir: Path) -> dict[str, Any]:
    limits = None
    experiment_path = batch_dir / "experiment.json"
    if experiment_path.exists():
        experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
        limits = (experiment.get("identity") or {}).get("effective_limits")
    matrix: dict[str, dict[str, list[dict[str, Any]]]] = {}
    by_architecture: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for row in _rows(batch_dir):
        results_path = batch_dir / row["report_dir"] / "results.json"
        if not results_path.exists():
            continue
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            continue
        result = payload[0]
        architecture, case_id = row["architecture"], row["case_id"]
        matrix.setdefault(architecture, {}).setdefault(case_id, []).append(
            {"repeat": row["repeat"], "status": result.get("status"), "success": result.get("success")}
        )
        stats = by_architecture.setdefault(
            architecture,
            {"n": 0, "passed": 0, "first_pass": 0, "tool_calls": 0, "verification_command_runs": 0, "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "token_unavailable": 0},
        )
        stats["n"] += 1
        stats["passed"] += int(bool(result.get("success")))
        stats["first_pass"] += int(bool(result.get("first_pass_success")))
        stats["tool_calls"] += int(result.get("tool_calls", 0) or 0)
        stats["verification_command_runs"] += int((result.get("metadata") or {}).get("verification_command_runs", 0) or 0)
        stats["latency_ms"] += int(result.get("latency_ms", 0) or 0)
        if result.get("input_tokens") is None:
            stats["token_unavailable"] += 1
        else:
            stats["input_tokens"] += int(result.get("input_tokens") or 0)
            stats["output_tokens"] += int(result.get("output_tokens") or 0)
        if not result.get("success"):
            failures.append(
                {
                    "architecture": architecture,
                    "case_id": case_id,
                    "repeat": row["repeat"],
                    "status": result.get("status"),
                    "failure_stage": result.get("failure_stage", ""),
                    "detail_stage": derive_failure_detail(result),
                    "failure_reason": str(result.get("failure_reason", ""))[:400],
                    "trace": (result.get("artifacts") or {}).get("trace", ""),
                }
            )
    return {"matrix": matrix, "by_architecture": by_architecture, "failures": failures, "limits": limits}


def write_batch_report(batch_dir: Path) -> dict[str, Path]:
    summary = aggregate_batch(batch_dir)
    summary_path = batch_dir / "summary.json"
    report_path = batch_dir / "report.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(_markdown(summary), encoding="utf-8")
    return {"summary": summary_path, "report": report_path}


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# MokioClaw Agent ablation batch report",
        "",
        "> The following are **Agent run results**, distinct from fixture/tri-state verification. n=3: all repeats shown as-is; no confidence intervals; no statistical significance claims.",
        "",
    ]
    if summary.get("limits"):
        limits = summary["limits"]
        lines.append(
            "> Limits: "
            f"max_attempts={limits['max_attempts']}, max_tool_calls={limits['max_tool_calls']}, "
            f"agent_timeout_seconds={limits['agent_timeout_seconds']}, command_timeout_seconds={limits['command_timeout_seconds']}"
        )
        lines.append("")
    for architecture, cases in summary["matrix"].items():
        lines.append(f"## {architecture}")
        lines.append("")
        lines.append("| Case | Repeats (r=status) |")
        lines.append("|---|---|")
        for case_id, repeats in cases.items():
            cells = ", ".join(f"r{item['repeat']}={item['status']}" for item in repeats)
            passed_count = sum(1 for item in repeats if item.get("success"))
            lines.append(f"| {case_id} | {cells} (passed {passed_count}/{len(repeats)}) |")
        lines.append("")
    lines.append("## Per-architecture aggregates")
    lines.append("")
    lines.append("| Architecture | n | passed | TS rate | first-pass | avg tool_calls | avg verification_runs | avg latency ms | tokens |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for architecture, stats in summary["by_architecture"].items():
        n = stats["n"] or 1
        if stats["token_unavailable"] == 0:
            tokens = f"{stats['input_tokens']}/{stats['output_tokens']}"
        elif stats["token_unavailable"] == stats["n"]:
            tokens = "unavailable"
        else:
            tokens = f"partial {stats['n'] - stats['token_unavailable']}/{stats['n']}: {stats['input_tokens']}/{stats['output_tokens']}"
        lines.append(
            f"| {architecture} | {stats['n']} | {stats['passed']} | {stats['passed'] / n:.2f} | {stats['first_pass'] / n:.2f} "
            f"| {stats['tool_calls'] / n:.1f} | {stats['verification_command_runs'] / n:.1f} | {stats['latency_ms'] / n:.0f} | {tokens} |"
        )
    lines.append("")
    lines.append("## Failures")
    lines.append("")
    if summary["failures"]:
        for failure in summary["failures"]:
            lines.append(
                f"- `{failure['architecture']}/{failure['case_id']}/r{failure['repeat']}` status={failure['status']} "
                f"stage={failure['failure_stage'] or 'unavailable'} detail={failure['detail_stage'] or 'unattributed'} "
                f"trace={failure['trace'] or 'unavailable'}"
            )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Failure attribution rules")
    lines.append("")
    lines.append("| Evidence (observable) | Label |")
    lines.append("|---|---|")
    lines.append("| status=budget_exhausted | budget_exhausted |")
    lines.append("| integrity check failed | protected_file_violation |")
    lines.append("| patch empty / patch_apply check failed | patch_generation_failure |")
    lines.append("| public_regression check failed | public_regression_failed |")
    lines.append("| hidden_tests failed and no public validation run (verification_command_runs=0) | public_validation_missing |")
    lines.append("| hidden_tests failed and public validation run (verification_command_runs>0) | hidden_contract_miss_after_validation |")
    lines.append("| status=setup_failed, failure_stage=worker | runtime_failure |")
    lines.append("| status=setup_failed, failure_stage in sandbox/setup | infrastructure_failure |")
    lines.append("| status=timed_out | execution_timeout |")
    lines.append("| anything else | unattributed |")
    lines.append("")
    lines.append("Labels describe observable facts only; no causal claims (spec §11.2).")
    return "\n".join(lines) + "\n"
