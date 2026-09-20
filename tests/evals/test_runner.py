from __future__ import annotations

import json
import os
from pathlib import Path

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.models import CaseResult, RunStatus
from mokioclaw.evals.runner import EvalRunner, _apply_worker_metrics, _worker_environment
from mokioclaw.evals.workspace import PreparedWorkspace


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


def test_apply_worker_metrics_marks_tokens_unavailable() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.PASSED, success=False)

    _apply_worker_metrics(result, {"status": RunStatus.PASSED, "tool_calls": 0, "artifacts": {"attempts": 1}})

    assert result.input_tokens is None
    assert result.metadata["token_coverage"] == "unavailable"
