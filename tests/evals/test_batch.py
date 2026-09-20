import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mokioclaw.evals.batch import BatchSpec, plan_execution_order
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
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"schema_version": 3, "identity": {}, "identity_fingerprint": "aaa", "provenance": {}})
    (spec.output_dir).mkdir(parents=True)
    (spec.output_dir / "experiment.json").write_text(
        json.dumps({"schema_version": 3, "identity": {}, "identity_fingerprint": "bbb", "provenance": {}}), encoding="utf-8"
    )

    try:
        run_batch(spec)
        raised = False
    except RuntimeError as exc:
        raised = "fingerprint mismatch" in str(exc)
    assert raised


def test_resume_rejects_schema_v2_even_if_fingerprint_text_matches(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_path = _write_case_with_limits(tmp_path / "a", 40)
    spec = BatchSpec(tmp_path, ["react"], [case_path], 1, tmp_path / "batch")
    spec.output_dir.mkdir()
    (spec.output_dir / "experiment.json").write_text(
        json.dumps({"schema_version": 2, "identity_fingerprint": "same"}), encoding="utf-8"
    )
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda _: {
        "schema_version": 3, "identity": {}, "identity_fingerprint": "same", "provenance": {}
    })
    with pytest.raises(RuntimeError, match="schema version"):
        run_batch(spec)


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


def _write_case_with_limits(case_dir: Path, max_tool_calls: int, image: str = "") -> Path:
    # exist_ok: callers such as _seed_case_tree pre-create the directory.
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / "demo-case.yaml"
    path.write_text(
        f"image: {json.dumps(image)}\n"
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


def test_run_batch_refuses_mixed_resolved_images_before_creating_output(tmp_path: Path) -> None:
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_a = _write_case_with_limits(tmp_path / "a", 40, image="image:a")
    case_b = _write_case_with_limits(tmp_path / "b", 40, image="image:b")
    spec = BatchSpec(tmp_path, ["react"], [case_a, case_b], 1, tmp_path / "batch")
    with pytest.raises(RuntimeError, match="mixed resolved images"):
        run_batch(spec)
    assert not spec.output_dir.exists()


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
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"schema_version": 3, "identity": {}, "identity_fingerprint": "aaa", "provenance": {}})
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


class _FakeImage:
    def __init__(self, image: str) -> None:
        pass

    def image_id(self) -> str:
        return "sha256:fake-digest"


def _identity_spec(tmp_path: Path, case_dir: Path) -> BatchSpec:
    return BatchSpec(
        project_root=tmp_path, architectures=["react"], case_paths=[case_dir / "cases" / "demo-case.yaml"],
        repeat=1, output_dir=tmp_path / "batch",
    )


def _seed_case_tree(tmp_path: Path) -> Path:
    (tmp_path / "evals" / "cases").mkdir(parents=True)
    _write_case_with_limits(tmp_path / "evals" / "cases", 40)
    (tmp_path / "evals" / "graders" / "cases" / "h").mkdir(parents=True)
    (tmp_path / "evals" / "graders" / "cases" / "h" / "test_h.py").write_text("def test_h(): pass\n", encoding="utf-8")
    (tmp_path / "evals" / "repos" / "templates" / "t").mkdir(parents=True)
    (tmp_path / "evals" / "repos" / "templates" / "t" / "f.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "evals" / "repos" / "mutations").mkdir(parents=True)
    (tmp_path / "evals" / "repos" / "mutations" / "m").write_text("diff\n", encoding="utf-8")
    (tmp_path / "src" / "mokioclaw").mkdir(parents=True)
    (tmp_path / "src" / "mokioclaw" / "a.py").write_text("y = 2\n", encoding="utf-8")
    return tmp_path


def _patch_external(monkeypatch, commit: str) -> None:
    from mokioclaw.evals import batch as batch_module

    monkeypatch.setattr(batch_module, "DockerCommandExecutor", _FakeImage)

    def fake_check(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = commit
            stderr = ""

        return R()

    monkeypatch.setattr(batch_module.subprocess, "run", fake_check)


def test_fingerprint_v3_records_per_case_image_digest(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import build_experiment_fingerprint

    _seed_case_tree(tmp_path)
    _write_case_with_limits(tmp_path / "evals" / "cases", 40, image="image:rich")
    _patch_external(monkeypatch, "abc123")

    class ImageByName:
        def __init__(self, image: str) -> None:
            self.image = image

        def image_id(self) -> str:
            return f"sha256:{self.image.replace(':', '-')}"

    monkeypatch.setattr(batch_module, "DockerCommandExecutor", ImageByName)
    payload = build_experiment_fingerprint(_identity_spec(tmp_path, tmp_path / "evals"))
    case_identity = payload["identity"]["cases"]["demo-case"]
    assert payload["schema_version"] == 3
    assert "image_digest" not in payload["identity"]
    assert case_identity["image"] == "image:rich"
    assert case_identity["image_digest"] == "sha256:image-rich"


def test_fingerprint_ignores_unselected_files_and_commit(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals.batch import build_experiment_fingerprint

    _seed_case_tree(tmp_path)
    _patch_external(monkeypatch, "commit-1")
    spec = _identity_spec(tmp_path, tmp_path / "evals")
    first = build_experiment_fingerprint(spec)

    # 无关文件：未选中的 case YAML + 其他 grader/template 变化
    (tmp_path / "evals" / "cases" / "other-case.yaml").write_text("id: other-case\n", encoding="utf-8")
    (tmp_path / "evals" / "repos" / "templates" / "other").mkdir()
    (tmp_path / "evals" / "repos" / "templates" / "other" / "g.py").write_text("z = 3\n", encoding="utf-8")
    # 无关 commit（provenance 采集变化，材料未变）
    _patch_external(monkeypatch, "commit-2")
    second = build_experiment_fingerprint(spec)

    assert first["identity_fingerprint"] == second["identity_fingerprint"]
    assert second["provenance"]["git_commit"] == "commit-2"
    assert first["provenance"]["git_commit"] == "commit-1"


def test_fingerprint_changes_with_selected_material_or_limits(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals.batch import BatchSpec, build_experiment_fingerprint

    _seed_case_tree(tmp_path)
    _patch_external(monkeypatch, "commit-1")
    spec = _identity_spec(tmp_path, tmp_path / "evals")
    base = build_experiment_fingerprint(spec)

    _patch_external(monkeypatch, "commit-1")
    override_spec = BatchSpec(
        project_root=tmp_path, architectures=["react"], case_paths=[spec.case_paths[0]],
        repeat=1, output_dir=tmp_path / "batch", limits_override=LimitsOverride(max_tool_calls=80),
    )
    assert build_experiment_fingerprint(override_spec)["identity_fingerprint"] != base["identity_fingerprint"]

    _patch_external(monkeypatch, "commit-1")
    (tmp_path / "evals" / "cases" / "demo-case.yaml").write_text(
        (tmp_path / "evals" / "cases" / "demo-case.yaml").read_text(encoding="utf-8") + "policy:\n  network: provider_only\n",
        encoding="utf-8",
    )
    assert build_experiment_fingerprint(spec)["identity_fingerprint"] != base["identity_fingerprint"]


def test_fingerprint_identity_fields(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals.batch import build_experiment_fingerprint

    _seed_case_tree(tmp_path)
    _patch_external(monkeypatch, "abc123")
    payload = build_experiment_fingerprint(_identity_spec(tmp_path, tmp_path / "evals"))

    assert payload["schema_version"] == 3
    identity = payload["identity"]
    assert identity["effective_limits"] == {"max_attempts": 3, "max_tool_calls": 40, "agent_timeout_seconds": 600, "command_timeout_seconds": 120}
    assert identity["architectures"] == ["react"]
    assert payload["provenance"]["git_commit"] == "abc123"
    demo = identity["cases"]["demo-case"]
    assert set(demo) == {
        "yaml_sha256", "grader_tree_hash", "template_tree_hash", "mutation_sha256", "image", "image_digest"
    }


def test_resume_allowed_when_identity_matches_but_commit_changed(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_path = _write_case_with_limits(tmp_path / "a", 40)
    spec = BatchSpec(project_root=tmp_path, architectures=["react"], case_paths=[case_path], repeat=1, output_dir=tmp_path / "batch")
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"schema_version": 3, "identity": {}, "identity_fingerprint": "same", "provenance": {"git_commit": "c1"}})
    spec.output_dir.mkdir(parents=True)
    (spec.output_dir / "experiment.json").write_text(
        json.dumps({"schema_version": 3, "identity": {}, "identity_fingerprint": "same", "provenance": {"git_commit": "c2"}}), encoding="utf-8"
    )
    # completed triple already in the manifest: resume is allowed and nothing re-runs
    (spec.output_dir / "manifest.jsonl").write_text(
        json.dumps({"architecture": "react", "case_id": "demo-case", "repeat": 1, "run_id": "r1", "status": "failed", "success": False, "report_dir": "runs/react/demo-case-r1", "completed_at": "t"}) + "\n",
        encoding="utf-8",
    )
    assert run_batch(spec)["executed"] == []  # identity 一致 → 不拒绝续跑


def test_manifest_row_records_limits(tmp_path: Path, monkeypatch) -> None:
    from mokioclaw.evals import batch as batch_module
    from mokioclaw.evals.batch import BatchSpec, run_batch

    case_path = _write_case_with_limits(tmp_path / "a", 40)
    spec = BatchSpec(
        project_root=tmp_path, architectures=["react"], case_paths=[case_path], repeat=1,
        output_dir=tmp_path / "batch", limits_override=LimitsOverride(max_tool_calls=80),
    )
    monkeypatch.setattr(batch_module, "build_experiment_fingerprint", lambda s: {"schema_version": 3, "identity": {}, "identity_fingerprint": "aaa", "provenance": {}})

    class FakeRunner:
        def __init__(self, *, project_root) -> None:
            pass

        def run_case(self, case_path, architecture="multi-agent", limits_override=None):
            from mokioclaw.evals.models import CaseResult, RunStatus
            return CaseResult(run_id="r1", case_id="demo-case", status=RunStatus.PASSED, success=True)

    monkeypatch.setattr(batch_module, "EvalRunner", FakeRunner)
    run_batch(spec)
    row = json.loads((spec.output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["limits"] == {"max_attempts": 3, "max_tool_calls": 80, "agent_timeout_seconds": 600, "command_timeout_seconds": 120}
