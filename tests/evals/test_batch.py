import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mokioclaw.evals.batch import plan_execution_order
from mokioclaw.evals.models import LimitsOverride


def test_plan_execution_order_interleaves_architectures() -> None:
    order = plan_execution_order(["multi-agent", "react"], ["case-a", "case-b"], 2)

    assert order == [
        ("multi-agent", "case-a", 1),
        ("react", "case-a", 1),
        ("multi-agent", "case-b", 1),
        ("react", "case-b", 1),
        ("multi-agent", "case-a", 2),
        ("react", "case-a", 2),
        ("multi-agent", "case-b", 2),
        ("react", "case-b", 2),
    ]


def _write_case(tmp_path: Path) -> Path:
    # run_batch validates case YAML at startup (mixed-limits refusal), so the
    # fixture must be a loadable CaseSpec, not just an id line.
    return _write_case_with_limits(tmp_path / "evals" / "cases", 40)


def test_run_batch_refuses_fingerprint_mismatch(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_path = _write_case(tmp_path)
    spec = BatchSpec(project_root=tmp_path, architectures=["react"], case_paths=[case_path], repeat=1, output_dir=tmp_path / "batch")
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"fields": {}, "fingerprint": "aaa"})
    (spec.output_dir).mkdir(parents=True)
    (spec.output_dir / "experiment.json").write_text(json.dumps({"fields": {}, "fingerprint": "bbb"}), encoding="utf-8")

    try:
        run_batch(spec)
        raised = False
    except RuntimeError as exc:
        raised = "fingerprint mismatch" in str(exc)
    assert raised


def test_run_batch_skips_completed_and_appends_manifest(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch
    from mokioclaw.evals.models import CaseResult, RunStatus

    case_path = _write_case(tmp_path)
    spec = BatchSpec(project_root=tmp_path, architectures=["react"], case_paths=[case_path], repeat=1, output_dir=tmp_path / "batch")
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"fields": {}, "fingerprint": "aaa"})
    manifest = spec.output_dir / "manifest.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"architecture": "react", "case_id": "demo-case", "repeat": 1, "run_id": "r1", "status": "failed", "success": False, "report_dir": "runs/react/demo-case-r1", "completed_at": "t"}) + "\n",
        encoding="utf-8",
    )

    executed: list[tuple[str, str, int]] = []

    def fake_run_case(self, case, architecture="multi-agent"):
        executed.append((architecture, case.stem))
        return CaseResult(run_id=f"{architecture}-x", case_id="demo-case", status=RunStatus.PASSED, success=True)

    monkeypatch.setattr(batch_module.EvalRunner, "run_case", fake_run_case)

    summary = run_batch(spec)

    assert executed == []  # completed triple skipped even though it failed
    assert summary["executed"] == []
    assert manifest.read_text(encoding="utf-8").count("\n") == 1


def _write_case_with_limits(case_dir: Path, max_tool_calls: int) -> Path:
    case_dir.mkdir(parents=True)
    path = case_dir / "demo-case.yaml"
    path.write_text(
        "id: demo-case\ncategory: feature\ntask: t\n"
        "repository:\n  template: t\n  mutation: m\n"
        "public_verification:\n  commands: [python -m pytest -q]\n"
        "grader:\n  id: g\n  hidden_tests: evals/graders/cases/h\n"
        f"limits:\n  max_attempts: 3\n  max_tool_calls: {max_tool_calls}\n"
        "  agent_timeout_seconds: 600\n  command_timeout_seconds: 120\n",
        encoding="utf-8",
    )
    return path


def test_run_batch_refuses_mixed_effective_limits(tmp_path: Path) -> None:
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_a = _write_case_with_limits(tmp_path / "a", 40)
    case_b = _write_case_with_limits(tmp_path / "b", 80)
    spec = BatchSpec(project_root=tmp_path, architectures=["react"], case_paths=[case_a, case_b], repeat=1, output_dir=tmp_path / "batch")
    with pytest.raises(RuntimeError, match="mixed effective limits"):
        run_batch(spec)


def test_run_batch_passes_override_to_runner(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_path = _write_case_with_limits(tmp_path / "a", 40)
    captured: dict = {}

    class FakeRunner:
        def __init__(self, *, project_root) -> None:
            captured["project_root"] = project_root

        def run_case(self, case_path, architecture="multi-agent", limits_override=None):
            captured["limits_override"] = limits_override
            from mokioclaw.evals.models import CaseResult, RunStatus
            return CaseResult(run_id="r1", case_id="demo-case", status=RunStatus.PASSED, success=True)

    monkeypatch.setattr(batch_module, "EvalRunner", FakeRunner)
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"schema_version": 2, "identity": {}, "identity_fingerprint": "aaa", "provenance": {}})
    spec = BatchSpec(
        project_root=tmp_path, architectures=["react"], case_paths=[case_path], repeat=1,
        output_dir=tmp_path / "batch",
        limits_override=LimitsOverride(max_tool_calls=80, agent_timeout_seconds=900),
    )
    run_batch(spec)
    assert captured["limits_override"] == LimitsOverride(max_tool_calls=80, agent_timeout_seconds=900)


def test_batch_cli_parses_limits_flags(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import cli

    captured: dict = {}

    def fake_run_batch(spec, **kwargs):
        captured["spec"] = spec

    monkeypatch.setattr(cli, "run_batch", fake_run_batch)
    result = CliRunner().invoke(
        cli.app,
        ["batch", "--architectures", "react", "--repeat", "1", "--output", str(tmp_path / "b"),
         "--max-tool-calls", "80", "--agent-timeout-seconds", "900"],
    )
    assert result.exit_code == 0
    assert captured["spec"].limits_override == LimitsOverride(max_tool_calls=80, agent_timeout_seconds=900)
