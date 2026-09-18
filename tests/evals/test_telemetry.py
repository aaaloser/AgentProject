import time
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


def test_run_worker_timeout_recovers_checkpoint(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    from mokioclaw.evals.models import RunStatus
    from mokioclaw.evals.runner import EvalRunner

    workspace = tmp_path / "run" / "agent"
    workspace.mkdir(parents=True)
    checkpoint_path = tmp_path / "run" / CHECKPOINT_NAME
    write_checkpoint(checkpoint_path, {"attempt": 2, "tool_calls": 37, "last_stage": "verify", "verification_command_runs": 3})
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=workspace, architecture="react", retrieval="grep",
        model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="worker", timeout=600)

    monkeypatch.setattr("mokioclaw.evals.runner.subprocess.run", fake_run)
    worker_result = EvalRunner(project_root=tmp_path)._run_worker(config, tmp_path / "wc.json", "react", 600)
    assert worker_result["status"] is RunStatus.TIMED_OUT
    assert worker_result["tool_calls"] == 37
    assert worker_result["checkpoint"]["attempt"] == 2


def test_run_worker_timeout_corrupt_checkpoint_falls_back(tmp_path: Path, monkeypatch, capsys) -> None:
    import subprocess

    from mokioclaw.evals.runner import EvalRunner

    (tmp_path / "run" / "agent").mkdir(parents=True)
    (tmp_path / "run" / CHECKPOINT_NAME).write_text("{broken", encoding="utf-8")
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=tmp_path / "run" / "agent", architecture="react",
        retrieval="grep", model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )
    monkeypatch.setattr("mokioclaw.evals.runner.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="w", timeout=1)))
    worker_result = EvalRunner(project_root=tmp_path)._run_worker(config, tmp_path / "wc.json", "react", 600)
    assert worker_result["tool_calls"] == 0
    assert "telemetry recovery warning" in capsys.readouterr().err


def test_run_worker_setup_failed_recovers_tool_calls_from_checkpoint(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals.models import RunStatus
    from mokioclaw.evals.runner import EvalRunner

    workspace = tmp_path / "run" / "agent"
    workspace.mkdir(parents=True)
    write_checkpoint(tmp_path / "run" / CHECKPOINT_NAME, {"attempt": 1, "tool_calls": 12, "tool_errors": 2, "verification_command_runs": 1})
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=workspace, architecture="react", retrieval="grep",
        model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )

    class Crashed:
        returncode = 3
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("mokioclaw.evals.runner.subprocess.run", lambda *a, **k: Crashed())
    worker_result = EvalRunner(project_root=tmp_path)._run_worker(config, tmp_path / "wc.json", "react", 600)
    assert worker_result["status"] is RunStatus.SETUP_FAILED
    assert worker_result["tool_calls"] == 12
    assert worker_result["artifacts"]["tool_errors"] == 2
    assert worker_result["artifacts"]["attempts"] == 1
    assert worker_result["checkpoint"]["tool_calls"] == 12


def test_run_worker_budget_merges_checkpoint_into_artifacts(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals.models import RunStatus
    from mokioclaw.evals.runner import EvalRunner

    workspace = tmp_path / "run" / "agent"
    workspace.mkdir(parents=True)
    write_checkpoint(tmp_path / "run" / CHECKPOINT_NAME, {"attempt": 2, "tool_calls": 40, "verification_command_runs": 5, "last_stage": "verify"})
    (tmp_path / "run" / "run-artifacts.json").write_text('{"status": "budget_exhausted", "tool_calls": 41}', encoding="utf-8")
    config = AgentRunConfig(
        run_id="r", case_id="c", task="t", workspace=workspace, architecture="react", retrieval="grep",
        model="", base_url_host="", temperature=0.0, sandbox_image="img",
        max_attempts=3, max_tool_calls=40, timeout_seconds=600,
    )

    class Completed:
        returncode = 2
        stdout = ""
        stderr = ""

    monkeypatch.setattr("mokioclaw.evals.runner.subprocess.run", lambda *a, **k: Completed())
    worker_result = EvalRunner(project_root=tmp_path)._run_worker(config, tmp_path / "wc.json", "react", 600)
    assert worker_result["status"] is RunStatus.BUDGET_EXHAUSTED
    assert worker_result["tool_calls"] == 41
    assert worker_result["artifacts"]["attempt"] == 2
    assert worker_result["artifacts"]["attempts"] == 2
    assert worker_result["artifacts"]["verification_command_runs"] == 5
    assert worker_result["checkpoint"]["last_stage"] == "verify"


def test_apply_worker_metrics_on_interrupted_result_uses_attempts_alias() -> None:
    from mokioclaw.evals.models import CaseResult, RunStatus
    from mokioclaw.evals.runner import _apply_worker_metrics

    result = CaseResult(run_id="r", case_id="c", status=RunStatus.SETUP_FAILED, success=False)
    _apply_worker_metrics(result, {
        "status": RunStatus.SETUP_FAILED, "tool_calls": 12,
        "artifacts": {"attempt": 1, "attempts": 1, "tool_errors": 2, "verification_command_runs": 1},
        "checkpoint": {"attempt": 1, "tool_calls": 12, "tool_errors": 2, "verification_command_runs": 1},
    })
    assert result.attempts == 1
    assert result.tool_calls == 12
    assert result.tool_errors == 2
    assert result.metadata["checkpoint"]["tool_calls"] == 12


def test_apply_worker_metrics_records_checkpoint_metadata() -> None:
    from mokioclaw.evals.models import CaseResult, RunStatus
    from mokioclaw.evals.runner import _apply_worker_metrics

    result = CaseResult(run_id="r", case_id="c", status=RunStatus.TIMED_OUT, success=False)
    _apply_worker_metrics(result, {
        "status": RunStatus.TIMED_OUT, "tool_calls": 37,
        "checkpoint": {"attempt": 2, "last_stage": "verify", "elapsed_seconds": 588.1},
        "artifacts": {"attempts": 2, "verification_command_runs": 3},
    })
    assert result.attempts == 2
    assert result.metadata["verification_command_runs"] == 3
    assert result.metadata["checkpoint"]["last_stage"] == "verify"


def test_checkpoint_overhead_is_recorded_and_bounded(tmp_path: Path) -> None:
    events = [
        {"type": "custom_event", "event": {"type": "tool_call", "name": f"tool-{index}", "args": {"command": "pytest"}}}
        for index in range(200)
    ]

    def timed(checkpoint_path: Path | None) -> tuple[float, int]:
        config = AgentRunConfig(
            run_id="r", case_id="c", task="t", workspace=tmp_path / "agent", architecture="react", retrieval="grep",
            model="", base_url_host="", temperature=0.0, sandbox_image="img",
            max_attempts=3, max_tool_calls=10**6, timeout_seconds=600,
        )
        artifacts = RunArtifacts()
        started = time.perf_counter()
        consume_adapter_events(iter(events), config, artifacts, checkpoint_path=checkpoint_path)
        return time.perf_counter() - started, artifacts.tool_calls

    without_seconds, without_calls = timed(None)
    with_seconds, with_calls = timed(tmp_path / CHECKPOINT_NAME)
    assert with_calls == without_calls == 200
    per_event_ms = (with_seconds - without_seconds) / len(events) * 1000
    assert per_event_ms < 5, (
        f"checkpoint overhead too high: {per_event_ms:.3f} ms/event "
        f"(without={without_seconds:.3f}s, with={with_seconds:.3f}s)"
    )
