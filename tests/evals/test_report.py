import json
from pathlib import Path

from mokioclaw.evals.models import CaseResult, GraderCheck, RunStatus
from mokioclaw.evals.provider_failures import FailureKind
from mokioclaw.evals.report import _markdown_report, write_result


def passing_case_result() -> CaseResult:
    return CaseResult(
        run_id="run-report-test",
        case_id="mini-api-pagination-boundary-01",
        status=RunStatus.PASSED,
        success=True,
        first_pass_success=True,
        grader_checks=[GraderCheck(name="hidden_tests", passed=True, detail="2 passed")],
        tool_calls=0,
        latency_ms=0,
        input_tokens=None,
        output_tokens=None,
    )


def test_write_result_creates_machine_and_human_readable_artifacts(tmp_path: Path) -> None:
    result = passing_case_result()

    paths = write_result(result, tmp_path)

    raw = json.loads(paths["results"].read_text(encoding="utf-8"))
    markdown = paths["report"].read_text(encoding="utf-8")
    assert raw[0]["status"] == "passed"
    assert raw[0]["input_tokens"] is None
    assert "1/1" in markdown
    assert "unavailable" in markdown
    assert result.run_id in markdown


def test_report_shows_new_metric_lines() -> None:
    result = CaseResult(run_id="r", case_id="c", status=RunStatus.PASSED, success=True, compression_count=2)
    result.metadata["handoff_count"] = 2
    result.metadata["verification_command_runs"] = 1
    result.metadata["token_coverage"] = "unavailable"
    result.artifacts["trace"] = "trace-dir"

    markdown = _markdown_report(result, {"passed": 1, "runs": 1})

    assert "Compression count: 2" in markdown
    assert "Handoffs: 2" in markdown
    assert "Verification command runs: 1" in markdown
    assert "Token coverage: unavailable" in markdown
    assert "Trace: trace-dir" in markdown


def test_report_uses_structured_sanitized_failure_and_five_layer_identity(tmp_path: Path) -> None:
    result = CaseResult(
        run_id="legacy-run",
        scheduled_run_id="scheduled-1",
        worker_attempt_id="worker-1",
        case_id="case",
        status=RunStatus.SETUP_FAILED,
        success=False,
        agent_attempt_count=2,
        attempts=2,
        failure_kind=FailureKind.PROVIDER_TRANSPORT,
        provider_status=504,
        provider_phase="after_tool_activity",
        sanitized_reason="Provider504; http_status=504; provider_host=provider.invalid",
        failure_reason="Provider504; http_status=504; provider_host=provider.invalid",
        telemetry_coverage="partial",
        telemetry_unavailable_reason="provider_error_before_usage",
    )

    paths = write_result(result, tmp_path)
    machine = paths["results"].read_text(encoding="utf-8")
    markdown = paths["report"].read_text(encoding="utf-8")

    assert "scheduled-1" in machine and "worker-1" in machine
    assert "provider_transport" in markdown
    assert "after_tool_activity" in markdown
    assert "provider.invalid" in markdown
    assert "Authorization" not in machine + markdown
    assert "https://" not in machine + markdown
