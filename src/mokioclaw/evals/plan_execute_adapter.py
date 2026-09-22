from __future__ import annotations

from typing import Any

from mokioclaw.core.agent import stream_eval_workflow_events
from mokioclaw.evals.adapters import _task_with_protected_path_policy, apply_usage_summary, RunArtifacts, consume_adapter_events
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.telemetry import checkpoint_path_for
from mokioclaw.graph.architectures import build_plan_execute_workflow
from mokioclaw.providers.call_journal import CallJournal
from mokioclaw.providers.usage import bind_call_journal, start_usage_collection


class PlanExecuteAdapter:
    def __init__(self, command_executor: Any) -> None:
        self.command_executor = command_executor

    def run(self, config: AgentRunConfig) -> RunArtifacts:
        artifacts = RunArtifacts()
        records = start_usage_collection()
        journal = CallJournal(config.workspace.parent)
        bind_call_journal(journal, provider_host=config.base_url_host)
        events = stream_eval_workflow_events(
            build_plan_execute_workflow(),
            task=_task_with_protected_path_policy(config),
            workspace=config.workspace,
            max_attempts=config.max_attempts,
            command_executor=self.command_executor,
        )
        try:
            consume_adapter_events(
                events,
                config,
                artifacts,
                verification_commands=config.verification_commands,
                checkpoint_path=checkpoint_path_for(config.workspace),
            )
        finally:
            apply_usage_summary(artifacts, journal, records)
        return artifacts
