from pathlib import Path

from mokioclaw.evals.adapters import RunArtifacts, consume_adapter_events
from mokioclaw.evals.models import AgentRunConfig
from mokioclaw.evals.telemetry import CHECKPOINT_NAME, load_checkpoint, write_checkpoint


def test_write_checkpoint_is_atomic_and_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / CHECKPOINT_NAME
    write_checkpoint(path, {"tool_calls": 37, "attempt": 2})
    payload, warning = load_checkpoint(path)
    assert payload == {"tool_calls": 37, "attempt": 2}
    assert warning == ""
    assert not path.with_name(CHECKPOINT_NAME + ".tmp").exists()


def test_load_checkpoint_missing_returns_empty(tmp_path: Path) -> None:
    assert load_checkpoint(tmp_path / "absent.json") == ({}, "")


def test_load_checkpoint_corrupt_returns_warning_not_raise(tmp_path: Path) -> None:
    path = tmp_path / CHECKPOINT_NAME
    path.write_text('{"tool_calls": 37', encoding="utf-8")
    payload, warning = load_checkpoint(path)
    assert payload == {}
    assert "telemetry recovery warning" in warning


def test_tmp_file_is_not_a_recovery_source(tmp_path: Path) -> None:
    path = tmp_path / CHECKPOINT_NAME
    path.with_name(CHECKPOINT_NAME + ".tmp").write_text('{"tool_calls": 999}', encoding="utf-8")
    payload, warning = load_checkpoint(path)
    assert payload == {}
    assert warning == ""


def test_consume_adapter_events_writes_checkpoint_per_event(tmp_path: Path) -> None:
    events = [
        {"type": "custom_event", "event": {"type": "tool_call", "name": "bash", "args": {"command": "pytest"}}},
        {"type": "custom_event", "event": {"type": "tool_result", "name": "bash", "result": {"ok": True}}},
        {"type": "graph_event", "event": {"verify": {"attempts": 2}}},
    ]
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=tmp_path / "run" / "agent", architecture="react",
        retrieval="grep", model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )
    checkpoint_path = tmp_path / "run" / CHECKPOINT_NAME
    consume_adapter_events(iter(events), config, RunArtifacts(), checkpoint_path=checkpoint_path)
    payload, warning = load_checkpoint(checkpoint_path)
    assert warning == ""
    assert payload["tool_calls"] == 1
    assert payload["attempt"] == 2
    assert payload["last_stage"] == "verify"
    assert payload["last_tool"] == "bash"
    assert set(payload) == {
        "attempt", "tool_calls", "tool_errors", "elapsed_seconds",
        "last_stage", "last_tool", "last_event_timestamp", "verification_command_runs",
    }


def test_budget_tripping_event_is_checkpointed(tmp_path: Path) -> None:
    import pytest
    from mokioclaw.evals.adapters import ToolBudgetExceeded

    events = [{"type": "custom_event", "event": {"type": "tool_call", "name": f"t-{i}"}} for i in range(41)]
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=tmp_path / "agent", architecture="react",
        retrieval="grep", model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )
    checkpoint_path = tmp_path / CHECKPOINT_NAME
    with pytest.raises(ToolBudgetExceeded):
        consume_adapter_events(iter(events), config, RunArtifacts(), checkpoint_path=checkpoint_path)
    payload, warning = load_checkpoint(checkpoint_path)
    assert warning == ""
    assert payload["tool_calls"] == 41


def test_checkpoint_write_failure_does_not_kill_run(tmp_path: Path, monkeypatch) -> None:
    def exploding_write(path: Path, payload: dict) -> None:
        raise RuntimeError("simulated checkpoint write failure")

    monkeypatch.setattr("mokioclaw.evals.adapters.write_checkpoint", exploding_write)
    events = [
        {"type": "custom_event", "event": {"type": "tool_call", "name": "bash", "args": {"command": "pytest"}}},
        {"type": "custom_event", "event": {"type": "tool_result", "name": "bash", "result": {"ok": False}}},
        {"type": "graph_event", "event": {"verify": {"attempts": 1}}},
    ]
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=tmp_path / "run" / "agent", architecture="react",
        retrieval="grep", model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )
    artifacts = RunArtifacts()
    consume_adapter_events(iter(events), config, artifacts, checkpoint_path=tmp_path / "run" / CHECKPOINT_NAME)
    assert len(artifacts.events) == 3
    assert artifacts.tool_calls == 1
    assert artifacts.tool_errors == 1
    assert artifacts.attempts == 1
