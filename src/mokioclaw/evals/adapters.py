from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence

from mokioclaw.core.agent import stream_agent_events
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.telemetry import checkpoint_path_for, write_checkpoint
from mokioclaw.providers.usage import start_usage_collection, sum_usage


@dataclass
class RunArtifacts:
    events: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    compression_count: int = 0
    handoff_count: int = 0
    verification_command_runs: int = 0
    trace_path: str = ""


class AgentAdapter(Protocol):
    def run(self, config: AgentRunConfig) -> RunArtifacts:
        raise NotImplementedError


class ToolBudgetExceeded(RuntimeError):
    def __init__(self, tool_calls: int) -> None:
        self.tool_calls = tool_calls
        super().__init__(f"tool-call budget exceeded: {tool_calls}")


class MokioAgentAdapter:
    def __init__(self, command_executor: Any) -> None:
        self.command_executor = command_executor

    def run(self, config: AgentRunConfig) -> RunArtifacts:
        records = start_usage_collection()
        artifacts = RunArtifacts()
        events = stream_agent_events(
            _task_with_protected_path_policy(config),
            workspace=config.workspace,
            max_attempts=config.max_attempts,
            approval_mode="deny",
            checkpoint_mode="off",
            trace_mode="on",
            command_executor=self.command_executor,
            allow_web_search=False,
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
            usage = sum_usage(records)
            if artifacts.input_tokens is None:
                artifacts.input_tokens = usage["input_tokens"]
            if artifacts.output_tokens is None:
                artifacts.output_tokens = usage["output_tokens"]
        return artifacts

    @staticmethod
    def _record_event(
        artifacts: RunArtifacts,
        event: dict[str, Any],
        verification_commands: Sequence[str] = (),
    ) -> None:
        event_type = event.get("type")
        payload = event.get("event")
        if event_type == "custom_event" and isinstance(payload, dict):
            payload_type = payload.get("type")
            if payload_type == "verification_command":
                artifacts.verification_command_runs += 1
            elif payload_type == "tool_call":
                artifacts.tool_calls += 1
                command = str((payload.get("args") or {}).get("command", ""))
                if any(cmd and cmd in command for cmd in verification_commands):
                    artifacts.verification_command_runs += 1
            elif payload_type == "tool_result":
                result = payload.get("result")
                if isinstance(result, dict) and result.get("ok") is False:
                    artifacts.tool_errors += 1
            elif payload_type == "trace_summary":
                artifacts.trace_path = str(payload.get("trace_dir") or payload.get("trace_path") or "")
                artifacts.tool_calls = max(artifacts.tool_calls, _optional_int(payload.get("tool_calls")) or 0)
                artifacts.tool_errors = max(artifacts.tool_errors, _optional_int(payload.get("failed_tool_calls")) or 0)
                artifacts.input_tokens = _optional_int(payload.get("input_tokens"))
                artifacts.output_tokens = _optional_int(payload.get("output_tokens"))
                artifacts.compression_count = _optional_int(payload.get("compression_count")) or 0
                artifacts.handoff_count = _optional_int(payload.get("handoff_count")) or artifacts.handoff_count
        elif event_type == "graph_event" and isinstance(payload, dict):
            for update in payload.values():
                if isinstance(update, dict) and "attempts" in update:
                    artifacts.attempts = _optional_int(update.get("attempts")) or artifacts.attempts


_record_event = MokioAgentAdapter._record_event


def consume_adapter_events(
    events,
    config: AgentRunConfig,
    artifacts: RunArtifacts,
    *,
    verification_commands: Sequence[str] = (),
    checkpoint_path: Path | None = None,
) -> None:
    started = time.perf_counter()
    last_stage = ""
    last_tool = ""
    try:
        for event in events:
            artifacts.events.append(event)
            _record_event(artifacts, event, verification_commands)
            event_type = event.get("type")
            payload = event.get("event")
            if event_type == "graph_event" and isinstance(payload, dict):
                stage_keys = [key for key, value in payload.items() if isinstance(value, dict)]
                if stage_keys:
                    last_stage = stage_keys[-1]
            elif event_type == "custom_event" and isinstance(payload, dict):
                if payload.get("type") in ("tool_call", "tool_result"):
                    last_tool = str(payload.get("name") or "")
            if checkpoint_path is not None:
                write_checkpoint(
                    checkpoint_path,
                    {
                        "attempt": artifacts.attempts,
                        "tool_calls": artifacts.tool_calls,
                        "tool_errors": artifacts.tool_errors,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "last_stage": last_stage,
                        "last_tool": last_tool,
                        "last_event_timestamp": datetime.now(timezone.utc).isoformat(),
                        "verification_command_runs": artifacts.verification_command_runs,
                    },
                )
            if artifacts.tool_calls > config.max_tool_calls:
                raise ToolBudgetExceeded(artifacts.tool_calls)
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()


def _task_with_protected_path_policy(config: AgentRunConfig) -> str:
    if not config.protected_paths:
        return config.task
    paths = ", ".join(str(path).replace("\\", "/") for path in config.protected_paths)
    return (
        f"{config.task}\n\n"
        "Evaluation policy: Do not modify, create, delete, or replace any tests. "
        f"The protected public files {paths} must remain byte-for-byte unchanged. "
        "Only modify production code required by the task; do not add tests to satisfy coverage."
    )


class ScriptedPatchAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, config: AgentRunConfig) -> RunArtifacts:
        if self.name == "sleeping-script":
            time.sleep(2)
            return RunArtifacts()
        if self.name == "over-budget-script":
            events = [{"type": "custom_event", "event": {"type": "tool_call", "name": f"script-{index}"}} for index in range(41)]
            return RunArtifacts(events=events, tool_calls=41)
        if self.name == "apply-reference":
            target = config.workspace / "src/mini_api/pagination.py"
            content = target.read_text(encoding="utf-8")
            marker = "start < len(items)"
            if content.count(marker) != 1:
                raise RuntimeError("pagination mutation marker is not unique")
            target.write_text(content.replace(marker, "end < len(items)"), encoding="utf-8")
            trace_path = config.workspace.parent / "infrastructure-trace.json"
            trace_path.write_text(
                json.dumps({"adapter": self.name, "run_id": config.run_id}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return RunArtifacts(trace_path=str(trace_path))
        raise ValueError(f"unknown scripted adapter: {self.name}")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
