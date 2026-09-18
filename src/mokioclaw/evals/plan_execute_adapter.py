from __future__ import annotations

from typing import Any

from mokioclaw.core.agent import stream_eval_workflow_events
from mokioclaw.evals.adapters import _task_with_protected_path_policy, RunArtifacts, consume_adapter_events
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.graph.architectures import build_plan_execute_workflow
from mokioclaw.providers.usage import start_usage_collection, sum_usage


class PlanExecuteAdapter:
    def __init__(self, command_executor: Any) -> None:
        self.command_executor = command_executor

    def run(self, config: AgentRunConfig) -> RunArtifacts:
        artifacts = RunArtifacts()
        records = start_usage_collection()
        events = stream_eval_workflow_events(
            build_plan_execute_workflow(),
            task=_task_with_protected_path_policy(config),
            workspace=config.workspace,
            max_attempts=config.max_attempts,
            command_executor=self.command_executor,
        )
        try:
            consume_adapter_events(events, config, artifacts, verification_commands=config.verification_commands)
        finally:
            usage = sum_usage(records)
            if artifacts.input_tokens is None:
                artifacts.input_tokens = usage["input_tokens"]
            if artifacts.output_tokens is None:
                artifacts.output_tokens = usage["output_tokens"]
        return artifacts
