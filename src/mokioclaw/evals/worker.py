from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mokioclaw.evals.adapters import MokioAgentAdapter, ScriptedPatchAdapter, ToolBudgetExceeded
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.provider_failures import FailureKind, classify_failure
from mokioclaw.evals.plan_execute_adapter import PlanExecuteAdapter
from mokioclaw.evals.react_adapter import ReactAdapter
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.core.trace import json_safe
from mokioclaw.providers.call_journal import CallJournal, atomic_json_replace


SCRIPTED_ADAPTERS = {"apply-reference", "sleeping-script", "over-budget-script"}


def _load_config(path: Path) -> AgentRunConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AgentRunConfig(
        run_id=str(payload["run_id"]),
        case_id=str(payload["case_id"]),
        task=str(payload["task"]),
        workspace=Path(str(payload["workspace"])),
        architecture=str(payload["architecture"]),
        retrieval=str(payload["retrieval"]),
        model=str(payload["model"]),
        base_url_host=str(payload["base_url_host"]),
        temperature=float(payload["temperature"]),
        sandbox_image=str(payload["sandbox_image"]),
        max_attempts=int(payload["max_attempts"]),
        max_tool_calls=int(payload["max_tool_calls"]),
        timeout_seconds=int(payload["timeout_seconds"]),
        scheduled_run_id=str(payload.get("scheduled_run_id") or payload["run_id"]),
        worker_attempt_id=str(payload.get("worker_attempt_id") or payload["run_id"]),
        protected_paths=tuple(str(item) for item in payload.get("protected_paths", ())),
        verification_commands=tuple(str(item) for item in payload.get("verification_commands", ())),
    )


def _adapter(name: str, config: AgentRunConfig):
    if name in SCRIPTED_ADAPTERS:
        return ScriptedPatchAdapter(name)
    if name == "multi-agent":
        return MokioAgentAdapter(DockerCommandExecutor(config.sandbox_image))
    if name == "react":
        return ReactAdapter(DockerCommandExecutor(config.sandbox_image))
    if name == "plan-execute":
        return PlanExecuteAdapter(DockerCommandExecutor(config.sandbox_image))
    raise ValueError(f"unknown evaluation adapter: {name}")


def _write_artifacts(path: Path, payload: dict[str, Any]) -> None:
    atomic_json_replace(path, json_safe(payload))


def _minimum_artifact(config: AgentRunConfig) -> dict[str, Any]:
    return {
        "agent_attempt_count": 0,
        "case_id": config.case_id,
        "scheduled_run_id": config.scheduled_run_id or config.run_id,
        "status": "running",
        "tool_calls": 0,
        "worker_attempt_id": config.worker_attempt_id or config.run_id,
    }


def _telemetry_payload(journal: CallJournal) -> dict[str, Any]:
    return asdict(journal.summarize())


def _execute_worker(config: AgentRunConfig, adapter: Any, output: Path) -> int:
    _write_artifacts(output, _minimum_artifact(config))
    try:
        artifacts = adapter.run(config)
        if artifacts.tool_calls > config.max_tool_calls:
            raise ToolBudgetExceeded(artifacts.tool_calls)
        journal = CallJournal(config.workspace.parent)
        _write_artifacts(
            output,
            {
                "status": "completed",
                "scheduled_run_id": config.scheduled_run_id or config.run_id,
                "worker_attempt_id": config.worker_attempt_id or config.run_id,
                "agent_attempt_count": artifacts.attempts,
                "telemetry": _telemetry_payload(journal),
                **asdict(artifacts),
            },
        )
        return 0
    except ToolBudgetExceeded as exc:
        journal = CallJournal(config.workspace.parent)
        _write_artifacts(
            output,
            {
                **_minimum_artifact(config),
                "status": "budget_exhausted",
                "tool_calls": exc.tool_calls,
                "failure_reason": "tool-call budget exhausted",
                "telemetry": _telemetry_payload(journal),
            },
        )
        return 2
    except Exception as exc:
        journal = CallJournal(config.workspace.parent)
        observed = journal.latest_failure()
        if observed is None:
            classification = classify_failure(
                exc,
                at_provider_boundary=False,
                successful_model_responses=0,
                tool_activity_count=0,
                local_kind=FailureKind.WORKER_INTERNAL,
            )
            observed = {
                "failure_kind": classification.failure_kind.value,
                "provider_phase": classification.provider_phase,
                "provider_status": classification.provider_status,
                "retryable": classification.retryable,
                "sanitized_reason": classification.sanitized_reason,
            }
        telemetry = _telemetry_payload(journal)
        _write_artifacts(
            output,
            {
                **_minimum_artifact(config),
                "status": "setup_failed",
                "failure_kind": observed.get("failure_kind"),
                "provider_phase": observed.get("provider_phase"),
                "provider_status": observed.get("provider_status"),
                "retryable": bool(observed.get("retryable")),
                "sanitized_reason": str(observed.get("sanitized_reason") or type(exc).__name__),
                "failure_reason": str(observed.get("sanitized_reason") or type(exc).__name__),
                "telemetry": telemetry,
                "telemetry_coverage": telemetry["coverage"],
                "input_tokens": telemetry["input_tokens"],
                "output_tokens": telemetry["output_tokens"],
            },
        )
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one supervised MokioClaw evaluation worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adapter", required=True)
    args = parser.parse_args()
    config = _load_config(args.config)
    output = config.workspace.parent / "run-artifacts.json"
    return _execute_worker(config, _adapter(args.adapter, config), output)


if __name__ == "__main__":
    raise SystemExit(main())
