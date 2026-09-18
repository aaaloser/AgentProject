from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from mokioclaw.evals.models import CaseResult


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    return value


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_result(result: CaseResult, report_dir: Path) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = _primitive(result)
    results_path = report_dir / "results.json"
    summary_path = report_dir / "summary.json"
    report_path = report_dir / "report.md"
    _atomic_write(results_path, json.dumps([payload], ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    summary = {
        "runs": 1,
        "passed": int(result.success),
        "task_success_rate": float(result.success),
        "first_pass_success_rate": float(result.first_pass_success),
        "average_tool_calls": float(result.tool_calls),
        "average_latency_ms": float(result.latency_ms),
    }
    _atomic_write(summary_path, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write(report_path, _markdown_report(result, summary))
    return {"results": results_path, "summary": summary_path, "report": report_path}


def _display(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def _markdown_report(result: CaseResult, summary: dict[str, Any]) -> str:
    checks = "\n".join(f"- `{check.name}`: {'passed' if check.passed else 'failed'} — {check.detail}" for check in result.grader_checks)
    metadata = result.metadata or {}
    return (
        "# MokioClaw Eval report\n\n"
        f"- Run: `{result.run_id}`\n"
        f"- Case: `{result.case_id}`\n"
        f"- Status: **{result.status.value}**\n"
        f"- Task success: **{summary['passed']}/{summary['runs']}**\n"
        f"- First-pass success: **{'yes' if result.first_pass_success else 'no'}**\n"
        f"- Adapter: `{metadata.get('architecture', 'unavailable')}`\n"
        f"- Model: `{metadata.get('model', 'unavailable')}`\n"
        f"- Input tokens: {_display(result.input_tokens)}\n"
        f"- Output tokens: {_display(result.output_tokens)}\n"
        f"- Estimated cost: {_display(result.estimated_cost)}\n"
        f"- Compression count: {result.compression_count}\n"
        f"- Handoffs: {_display(result.metadata.get('handoff_count'))}\n"
        f"- Verification command runs: {_display(result.metadata.get('verification_command_runs'))}\n"
        f"- Token coverage: {result.metadata.get('token_coverage', 'unavailable')}\n"
        f"- Trace: {_display(result.artifacts.get('trace'))}\n\n"
        "## Grader checks\n\n"
        f"{checks or '- unavailable'}\n"
    )
