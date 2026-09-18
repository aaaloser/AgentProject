import json
from pathlib import Path

from mokioclaw.evals.aggregation import aggregate_batch, write_batch_report


def _write_run(batch_dir: Path, arch: str, case: str, repeat: int, *, success: bool, status: str, **overrides) -> None:
    report_dir = batch_dir / "runs" / arch / f"{case}-r{repeat}"
    report_dir.mkdir(parents=True)
    result = {
        "run_id": f"{arch}-{case}-{repeat}",
        "case_id": case,
        "status": status,
        "success": success,
        "first_pass_success": success,
        "tool_calls": 10,
        "latency_ms": 1000,
        "input_tokens": None,
        "output_tokens": None,
        "metadata": {"verification_command_runs": 1},
        "grader_checks": [],
        **overrides,
    }
    (report_dir / "results.json").write_text(json.dumps([result]), encoding="utf-8")
    row = {"architecture": arch, "case_id": case, "repeat": repeat, "run_id": result["run_id"], "status": status, "success": success, "report_dir": f"runs/{arch}/{case}-r{repeat}", "completed_at": "t"}
    with (batch_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def test_aggregate_batch_summarizes_matrix_and_architectures(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _write_run(batch_dir, "react", "case-a", 1, success=True, status="passed")
    _write_run(batch_dir, "multi-agent", "case-a", 1, success=False, status="failed")

    summary = aggregate_batch(batch_dir)

    assert summary["by_architecture"]["react"]["n"] == 1
    assert summary["by_architecture"]["react"]["passed"] == 1
    assert summary["by_architecture"]["multi-agent"]["passed"] == 0
    assert summary["matrix"]["react"]["case-a"][0]["success"] is True
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["detail_stage"] == "unattributed" or summary["failures"][0]["detail_stage"] == ""


def test_markdown_partial_token_coverage_cell_summary_and_rules(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _write_run(batch_dir, "react", "case-a", 1, success=True, status="passed", input_tokens=100, output_tokens=50)
    _write_run(batch_dir, "react", "case-a", 2, success=False, status="failed")

    paths = write_batch_report(batch_dir)
    report = paths["report"].read_text(encoding="utf-8")

    assert "partial 1/2: 100/50" in report
    assert "(passed 1/2)" in report
    assert "## Failure attribution rules" in report
    assert "protected_file_violation" in report
    assert "unattributed" in report


def test_malformed_results_file_is_skipped(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _write_run(batch_dir, "react", "case-a", 1, success=True, status="passed")
    empty_dir = batch_dir / "runs" / "react" / "case-b-r1"
    empty_dir.mkdir(parents=True)
    (empty_dir / "results.json").write_text("[]", encoding="utf-8")
    row = {"architecture": "react", "case_id": "case-b", "repeat": 1, "run_id": "react-case-b-1", "status": "failed", "success": False, "report_dir": "runs/react/case-b-r1", "completed_at": "t"}
    with (batch_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")

    summary = aggregate_batch(batch_dir)

    assert summary["by_architecture"]["react"]["n"] == 1
    assert "case-b" not in summary["matrix"]["react"]


def test_null_grader_checks_is_attributed_without_crash(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _write_run(batch_dir, "react", "case-a", 1, success=False, status="failed", grader_checks=None)

    summary = aggregate_batch(batch_dir)

    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["detail_stage"] in ("", "unattributed")


def _seed_batch_with_experiment(batch_dir: Path, limits: dict | None) -> None:
    # exist_ok: callers pass pytest's already-created tmp_path directly.
    batch_dir.mkdir(parents=True, exist_ok=True)
    if limits is not None:
        (batch_dir / "experiment.json").write_text(
            json.dumps({"schema_version": 2, "identity": {"effective_limits": limits}, "identity_fingerprint": "x", "provenance": {}}),
            encoding="utf-8",
        )


def test_report_header_contains_limits_line(tmp_path: Path) -> None:
    from mokioclaw.evals.aggregation import write_batch_report

    _seed_batch_with_experiment(
        tmp_path,
        {"max_attempts": 3, "max_tool_calls": 80, "agent_timeout_seconds": 900, "command_timeout_seconds": 120},
    )
    paths = write_batch_report(tmp_path)
    text = paths["report"].read_text(encoding="utf-8")
    assert "max_tool_calls=80" in text and "agent_timeout_seconds=900" in text


def test_report_header_without_experiment_has_no_limits_line(tmp_path: Path) -> None:
    from mokioclaw.evals.aggregation import write_batch_report

    _seed_batch_with_experiment(tmp_path, None)
    paths = write_batch_report(tmp_path)
    assert "max_tool_calls=" not in paths["report"].read_text(encoding="utf-8")
