from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.models import AgentRunConfig, CaseResult, RunStatus
from mokioclaw.evals.runner import EvalRunner, _apply_worker_metrics, _worker_environment
from mokioclaw.evals.workspace import PreparedWorkspace
from mokioclaw.evals.worker import _execute_worker
from mokioclaw.providers.call_journal import CallJournal
from mokioclaw.providers.usage import current_usage_handler, record_provider_tool_activity, start_usage_collection


PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_CASE = PROJECT_ROOT / "evals/cases/mini-api-pagination-boundary-01.yaml"


def case_with(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "case.yaml"
    path.write_text(SOURCE_CASE.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return path


def test_runner_terminates_worker_after_agent_timeout(tmp_path: Path) -> None:
    case_path = case_with(tmp_path, "agent_timeout_seconds: 600", "agent_timeout_seconds: 1")
    runner = EvalRunner(project_root=PROJECT_ROOT, runs_root=tmp_path / "runs")

    result = runner.run_case(case_path, architecture="sleeping-script")

    assert result.status is RunStatus.TIMED_OUT


def test_runner_marks_tool_budget_exhaustion(tmp_path: Path) -> None:
    case_path = case_with(tmp_path, "max_tool_calls: 40", "max_tool_calls: 40")
    runner = EvalRunner(project_root=PROJECT_ROOT, runs_root=tmp_path / "runs")

    result = runner.run_case(case_path, architecture="over-budget-script")

    assert result.status is RunStatus.BUDGET_EXHAUSTED
    assert result.tool_calls == 41


def test_runner_does_not_put_case_or_hidden_paths_in_worker_config(tmp_path: Path) -> None:
    case_path = case_with(tmp_path, "max_tool_calls: 40", "max_tool_calls: 40")
    runner = EvalRunner(project_root=PROJECT_ROOT, runs_root=tmp_path / "runs")

    result = runner.run_case(case_path, architecture="over-budget-script")
    worker_config = Path(result.artifacts["worker_config"])
    payload = json.loads(worker_config.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert "hidden_tests" not in serialized
    assert "graders" not in serialized
    assert Path(payload["workspace"]).name == "agent"
    assert [Path(item).as_posix() for item in payload["protected_paths"]] == [
        "tests/test_pagination.py"
    ]


def test_worker_environment_preserves_windows_system_root(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")

    environment = _worker_environment(PROJECT_ROOT)

    assert environment["SYSTEMROOT"] == r"C:\Windows"


def test_run_config_loads_provider_settings_from_project_dotenv(tmp_path: Path, monkeypatch) -> None:
    for key in ("API_KEY", "MODEL", "BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "API_KEY=test-key\nMODEL=test-model\nBASE_URL=https://provider.example/v1\n",
        encoding="utf-8",
    )
    runner = EvalRunner(project_root=tmp_path)
    case = load_case(SOURCE_CASE)
    prepared = PreparedWorkspace(tmp_path / "run", tmp_path / "baseline", tmp_path / "agent")

    config = runner._run_config(case, prepared, "run-id", "multi-agent", case.limits)

    assert config.model == "test-model"
    assert config.base_url_host == "provider.example"
    assert os.environ["API_KEY"] == "test-key"


def test_run_config_uses_case_image(tmp_path: Path) -> None:
    case = load_case(case_with(tmp_path, "category: bugfix", "image: mokioclaw-eval-rich:14.3.4\ncategory: bugfix"))
    prepared = PreparedWorkspace(tmp_path / "run", tmp_path / "baseline", tmp_path / "agent")

    config = EvalRunner(project_root=PROJECT_ROOT)._run_config(case, prepared, "run-id", "react", case.limits)

    assert config.sandbox_image == "mokioclaw-eval-rich:14.3.4"


def test_apply_worker_metrics_propagates_artifact_fields() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.PASSED, success=False)
    worker_result = {
        "status": RunStatus.PASSED,
        "tool_calls": 21,
        "artifacts": {
            "attempts": 1,
            "tool_errors": 3,
            "input_tokens": 120,
            "output_tokens": 45,
            "compression_count": 2,
            "trace_path": "some/trace",
            "handoff_count": 2,
            "verification_command_runs": 1,
        },
    }

    _apply_worker_metrics(result, worker_result)

    assert result.attempts == 1
    assert result.tool_calls == 21
    assert result.tool_errors == 3
    assert result.input_tokens == 120
    assert result.output_tokens == 45
    assert result.compression_count == 2
    assert result.artifacts["trace"] == "some/trace"
    assert result.metadata["handoff_count"] == 2
    assert result.metadata["verification_command_runs"] == 1
    assert result.metadata["token_coverage"] == "full"


def test_apply_worker_metrics_records_completed_last_stage() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.PASSED, success=False)

    _apply_worker_metrics(result, {
        "status": RunStatus.PASSED,
        "tool_calls": 3,
        "artifacts": {"attempts": 1, "last_stage": "verify"},
    })

    assert result.metadata["last_stage"] == "verify"


def test_apply_worker_metrics_falls_back_to_checkpoint_last_stage() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.TIMED_OUT, success=False)

    _apply_worker_metrics(result, {
        "status": RunStatus.TIMED_OUT,
        "tool_calls": 3,
        "artifacts": {"attempts": 1},
        "checkpoint": {"last_stage": "planner"},
    })

    assert result.metadata["last_stage"] == "planner"


def test_apply_worker_metrics_marks_tokens_unavailable() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.PASSED, success=False)

    _apply_worker_metrics(result, {"status": RunStatus.PASSED, "tool_calls": 0, "artifacts": {"attempts": 1}})

    assert result.input_tokens is None
    assert result.metadata["token_coverage"] == "unavailable"


def worker_config(tmp_path: Path) -> AgentRunConfig:
    workspace = tmp_path / "attempt" / "agent"
    workspace.mkdir(parents=True)
    return AgentRunConfig(
        run_id="legacy-run",
        case_id="case-1",
        task="task",
        workspace=workspace,
        architecture="multi-agent",
        retrieval="grep",
        model="fake-model",
        base_url_host="provider.invalid",
        temperature=0.0,
        sandbox_image="image",
        max_attempts=3,
        max_tool_calls=40,
        timeout_seconds=600,
        scheduled_run_id="scheduled-1",
        worker_attempt_id="worker-1",
    )


def test_worker_writes_minimum_artifact_before_adapter_execution(tmp_path: Path) -> None:
    config = worker_config(tmp_path)
    output = config.workspace.parent / "run-artifacts.json"

    class InspectingAdapter:
        def run(self, config):
            running = json.loads(output.read_text(encoding="utf-8"))
            assert running["status"] == "running"
            assert running["scheduled_run_id"] == "scheduled-1"
            assert running["worker_attempt_id"] == "worker-1"
            raise RuntimeError("worker crashed")

    exit_code = _execute_worker(config, InspectingAdapter(), output)

    assert exit_code == 3
    terminal = json.loads(output.read_text(encoding="utf-8"))
    assert terminal["status"] == "setup_failed"
    assert terminal["failure_kind"] == "worker_internal"
    assert terminal["agent_attempt_count"] == 0
    assert "worker crashed" not in json.dumps(terminal)


@pytest.mark.parametrize(
    ("successful_responses", "tool_activity", "expected_phase", "expected_coverage"),
    [
        (0, False, "before_first_model_response", "unavailable"),
        (1, False, "after_model_response_before_first_tool", "partial"),
        (1, True, "after_tool_activity", "partial"),
    ],
)
def test_worker_preserves_structured_provider_504_phase(
    tmp_path: Path,
    successful_responses: int,
    tool_activity: bool,
    expected_phase: str,
    expected_coverage: str,
) -> None:
    config = worker_config(tmp_path)
    output = config.workspace.parent / "run-artifacts.json"

    class Provider504(RuntimeError):
        status_code = 504

    error = Provider504("Authorization: Bearer FAKE_SECRET https://provider.invalid/v1?q=secret")

    class ProviderFailingAdapter:
        def run(self, config):
            start_usage_collection(CallJournal(config.workspace.parent), provider_host=config.base_url_host)
            handler = current_usage_handler()
            for index in range(successful_responses):
                handler.on_llm_start({}, ["prompt"], run_id=f"ok-{index}")
                response = type("Response", (), {"llm_output": {"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}}})()
                handler.on_llm_end(response, run_id=f"ok-{index}")
            if tool_activity:
                record_provider_tool_activity()
            handler.on_llm_start({}, ["prompt"], run_id="failure")
            handler.on_llm_error(error, run_id="failure")
            raise error

    assert _execute_worker(config, ProviderFailingAdapter(), output) == 3

    terminal = json.loads(output.read_text(encoding="utf-8"))
    assert terminal["failure_kind"] == "provider_transport"
    assert terminal["provider_status"] == 504
    assert terminal["provider_phase"] == expected_phase
    assert terminal["telemetry_coverage"] == expected_coverage
    assert terminal["input_tokens"] == (3 if successful_responses else None)
    serialized = json.dumps(terminal)
    assert "FAKE_SECRET" not in serialized
    assert "/v1" not in serialized


def test_run_worker_timeout_recovers_partial_call_journal_usage(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    config = worker_config(tmp_path)
    journal = CallJournal(config.workspace.parent)
    completed = journal.begin_model_call()
    journal.complete_model_call(completed, {"input_tokens": 7, "output_tokens": 2}, "callback")
    journal.begin_model_call()
    monkeypatch.setattr(
        "mokioclaw.evals.runner.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="worker", timeout=600)),
    )

    worker_result = EvalRunner(project_root=tmp_path)._run_worker(
        config,
        config.workspace.parent / "worker-config.json",
        "multi-agent",
        600,
    )

    assert worker_result["status"] is RunStatus.TIMED_OUT
    assert worker_result["telemetry"]["coverage"] == "partial"
    assert worker_result["telemetry"]["unavailable_reason"] == "worker_killed_during_call"
    assert worker_result["telemetry"]["input_tokens"] == 7


def test_apply_worker_metrics_prefers_journal_summary_and_sets_five_layer_identity() -> None:
    result = CaseResult(
        run_id="legacy-run",
        case_id="case",
        status=RunStatus.TIMED_OUT,
        success=False,
        scheduled_run_id="scheduled-1",
        worker_attempt_id="worker-1",
    )
    _apply_worker_metrics(
        result,
        {
            "status": RunStatus.TIMED_OUT,
            "tool_calls": 4,
            "artifacts": {"attempts": 9, "input_tokens": 999, "output_tokens": 999},
            "telemetry": {
                "coverage": "partial",
                "unavailable_reason": "worker_killed_during_call",
                "input_tokens": 7,
                "output_tokens": 2,
                "total_tokens": 9,
                "model_call_count": 2,
                "completed_call_count": 1,
                "error_call_count": 0,
                "in_flight_call_count": 1,
                "transport_attempt_count": 2,
                "incomplete_temporary_file_count": 0,
            },
        },
    )

    assert result.agent_attempt_count == 9
    assert result.attempts == 9
    assert result.input_tokens == 7
    assert result.output_tokens == 2
    assert result.total_tokens == 9
    assert result.telemetry_coverage == "partial"
    assert result.telemetry_unavailable_reason == "worker_killed_during_call"
    assert result.model_call_count == 2
    assert result.transport_attempt_count == 2
