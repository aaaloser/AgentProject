import json
from pathlib import Path

from mokioclaw.evals.models import CaseResult, GraderCheck, RunStatus
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
