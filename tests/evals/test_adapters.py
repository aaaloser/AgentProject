import json
from pathlib import Path

from langchain_core.messages import AIMessage

from mokioclaw.evals.adapters import MokioAgentAdapter, RunArtifacts
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.worker import _write_artifacts


def make_run_config(tmp_path: Path) -> AgentRunConfig:
    return AgentRunConfig(
        run_id="run-test",
        case_id="case-test",
        task="fix pagination",
        workspace=tmp_path,
        architecture="multi-agent",
        retrieval="grep",
        model="test-model",
        base_url_host="provider.example",
        temperature=0.0,
        sandbox_image="mokioclaw-eval-python:3.13",
        max_attempts=3,
        max_tool_calls=40,
        timeout_seconds=600,
        protected_paths=("tests/test_pagination.py",),
    )


def test_mokio_adapter_forces_offline_deny_mode(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_stream(task, **kwargs):
        captured["task"] = task
        captured.update(kwargs)
        yield {"type": "custom_event", "event": {"type": "trace_summary", "tool_calls": 2, "failed_tool_calls": 0}}

    monkeypatch.setattr("mokioclaw.evals.adapters.stream_agent_events", fake_stream)
    executor = object()
    config = make_run_config(tmp_path)

    artifacts = MokioAgentAdapter(executor).run(config)

    assert captured["approval_mode"] == "deny"
    assert captured["checkpoint_mode"] == "off"
    assert captured["trace_mode"] == "on"
    assert captured["allow_web_search"] is False
    assert captured["command_executor"] is executor
    assert "Do not modify, create, delete, or replace any tests" in captured["task"]
    assert "tests/test_pagination.py" in captured["task"]
    assert artifacts.tool_calls == 2


def test_mokio_adapter_sums_usage_records(monkeypatch, tmp_path: Path) -> None:
    def fake_stream(task, **kwargs):
        yield {"type": "custom_event", "event": {"type": "trace_summary", "tool_calls": 1, "trace_dir": "t"}}

    monkeypatch.setattr("mokioclaw.evals.adapters.stream_agent_events", fake_stream)
    monkeypatch.setattr(
        "mokioclaw.evals.adapters.start_usage_collection",
        lambda: [{"input_tokens": 7, "output_tokens": 3}],
    )
    adapter = MokioAgentAdapter(command_executor=None)
    artifacts = adapter.run(make_run_config(tmp_path))

    assert artifacts.input_tokens == 7
    assert artifacts.output_tokens == 3


def test_worker_serializes_langchain_messages_in_run_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "run-artifacts.json"
    payload = {
        "status": "completed",
        "events": [{"type": "graph_event", "event": {"planner": {"messages": [AIMessage(content="done")]}}}],
    }

    _write_artifacts(output, payload)

    saved = json.loads(output.read_text(encoding="utf-8"))
    message = saved["events"][0]["event"]["planner"]["messages"][0]
    assert message["type"] == "ai"
    assert message["data"]["content"] == "done"


def test_record_event_counts_verification_commands() -> None:
    artifacts = RunArtifacts()
    commands = ("python -m pytest -q",)
    MokioAgentAdapter._record_event(
        artifacts,
        {"type": "custom_event", "event": {"type": "verification_command", "command": "python -m pytest -q", "ok": False}},
        verification_commands=commands,
    )
    MokioAgentAdapter._record_event(
        artifacts,
        {"type": "custom_event", "event": {"type": "tool_call", "name": "BashTool", "args": {"command": "python -m pytest -q tests/test_x.py"}}},
        verification_commands=commands,
    )
    MokioAgentAdapter._record_event(
        artifacts,
        {"type": "custom_event", "event": {"type": "tool_call", "name": "ReadFileTool", "args": {"path": "src/a.py"}}},
        verification_commands=commands,
    )

    assert artifacts.verification_command_runs == 2
    assert artifacts.tool_calls == 2


def test_record_event_tracks_latest_graph_stage() -> None:
    artifacts = RunArtifacts()
    MokioAgentAdapter._record_event(artifacts, {"type": "graph_event", "event": {"planner": {}}})
    MokioAgentAdapter._record_event(artifacts, {"type": "graph_event", "event": {"verifier": {"attempts": 1}}})

    assert artifacts.last_stage == "verifier"
    assert artifacts.attempts == 1


def test_run_artifacts_no_longer_has_first_pass_success() -> None:
    assert "first_pass_success" not in RunArtifacts.__dataclass_fields__
    assert "handoff_count" in RunArtifacts.__dataclass_fields__
    assert "verification_command_runs" in RunArtifacts.__dataclass_fields__
