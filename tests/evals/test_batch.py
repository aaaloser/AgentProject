import json
from pathlib import Path

from mokioclaw.evals.batch import plan_execution_order


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
    case_dir = tmp_path / "evals" / "cases"
    case_dir.mkdir(parents=True)
    path = case_dir / "demo-case.yaml"
    path.write_text("id: demo-case\n", encoding="utf-8")
    return path


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
