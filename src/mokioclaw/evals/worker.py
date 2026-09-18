from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mokioclaw.evals.adapters import MokioAgentAdapter, ScriptedPatchAdapter, ToolBudgetExceeded
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.plan_execute_adapter import PlanExecuteAdapter
from mokioclaw.evals.react_adapter import ReactAdapter
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.core.trace import json_safe


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
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one supervised MokioClaw evaluation worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adapter", required=True)
    args = parser.parse_args()
    config = _load_config(args.config)
    output = config.workspace.parent / "run-artifacts.json"
    try:
        artifacts = _adapter(args.adapter, config).run(config)
        if artifacts.tool_calls > config.max_tool_calls:
            raise ToolBudgetExceeded(artifacts.tool_calls)
        _write_artifacts(output, {"status": "completed", **asdict(artifacts)})
        return 0
    except ToolBudgetExceeded as exc:
        _write_artifacts(output, {"status": "budget_exhausted", "tool_calls": exc.tool_calls, "error": str(exc)})
        return 2
    except Exception as exc:
        _write_artifacts(output, {"status": "setup_failed", "tool_calls": 0, "error": f"{type(exc).__name__}: {exc}"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
