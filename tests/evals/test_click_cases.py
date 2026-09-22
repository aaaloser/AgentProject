from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.grader import _integrity_violation
from mokioclaw.evals.protocol import CandidateReview, select_case_protocol
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.evals.workspace import prepare_workspace


PROJECT_ROOT = Path(__file__).parents[2]
EVAL_ROOT = PROJECT_ROOT / "evals"
CANDIDATE_ROOT = EVAL_ROOT / "candidates" / "click"
TEMPLATE = EVAL_ROOT / "repos" / "templates" / "click"
IMAGE = "mokioclaw-eval-click:8.4.2"

CANDIDATES = (
    ("01-option-parsing", "click-double-percent-option-prefix-01", "option-parsing"),
    ("02-argument-conversion", "click-choice-unicode-casefold-02", "argument-conversion"),
    ("03-help-rendering", "click-indented-help-heading-03", "help-rendering"),
    ("04-cli-runner-io", "click-runner-charset-output-04", "cli-runner-io"),
)
ALLOWED_DECISIONS = {"two-case-72", "single-case-36", "no-click-case-stop"}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def apply_patch(workspace: Path, patch: Path, *, reverse: bool = False) -> None:
    command = ["git", "apply", "--whitespace=error"]
    if reverse:
        command.append("--reverse")
    command.append(str(patch))
    subprocess.run(
        command,
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )


def patch_paths(path: Path) -> list[str]:
    return [
        line.removeprefix("diff --git a/").split(" b/", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("diff --git a/")
    ]


def changed_lines(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )


def docker_run(workspace: Path, command: str) -> dict:
    return DockerCommandExecutor(IMAGE).run(
        workspace=workspace,
        command=f"PYTHONDONTWRITEBYTECODE=1 {command} -p no:cacheprovider"
        if command.startswith("python -m pytest")
        else f"PYTHONDONTWRITEBYTECODE=1 {command}",
        timeout_seconds=90,
        max_output_chars=12000,
    )


def test_candidate_metadata_freezes_order_subsystem_and_acceptance_commands() -> None:
    observed = []
    for directory, candidate_id, subsystem_id in CANDIDATES:
        value = read_json(CANDIDATE_ROOT / directory / "candidate.json")
        observed.append((value["order"], value["candidate_id"], value["subsystem_id"]))
        assert value["expected_mutation_surface"]
        assert set(value["acceptance_commands"]) == {
            "upstream_owned",
            "public_pytest",
            "standalone_repro",
            "hidden_behavior",
        }
    assert observed == [
        (index, candidate_id, subsystem_id)
        for index, (_, candidate_id, subsystem_id) in enumerate(CANDIDATES, 1)
    ]


@pytest.mark.parametrize("directory,candidate_id,subsystem_id", CANDIDATES)
def test_candidate_has_complete_preregistered_matrix_and_auditable_review(
    directory: str, candidate_id: str, subsystem_id: str
) -> None:
    root = CANDIDATE_ROOT / directory
    candidate = read_json(root / "candidate.json")
    review = read_json(root / "review.json")

    assert patch_paths(root / "mutation.patch") == candidate["expected_mutation_surface"]
    assert patch_paths(root / "reference.patch") == [candidate["upstream_ownership"]["source"]]
    assert patch_paths(root / "broken.patch") == [candidate["upstream_ownership"]["source"]]
    assert changed_lines(root / "reference.patch") <= 40
    assert review["candidate_id"] == candidate_id
    assert review["subsystem_id"] == subsystem_id
    assert review["status"] in {"PASS", "REJECT"}
    assert len(review["localization_steps"]) <= 10
    assert set(review["criteria"]) == {
        "upstream_bug_green",
        "upstream_fix_green",
        "public_bug_red_fix_green",
        "repro_bug_red_fix_green",
        "hidden_bug_red_fix_green",
        "task_non_leaking",
        "localization_within_ten_steps",
        "reference_patch_within_forty_lines",
        "broken_edit_turns_both_public_paths_red",
        "three_runs_within_ninety_seconds",
    }
    assert review["status"] == ("PASS" if all(review["criteria"].values()) else "REJECT")


def test_adaptive_selection_is_mechanical_and_uses_distinct_subsystems() -> None:
    reviews = []
    for directory, candidate_id, subsystem_id in CANDIDATES:
        review = read_json(CANDIDATE_ROOT / directory / "review.json")
        reviews.append(CandidateReview(candidate_id, subsystem_id, review["status"] == "PASS"))
    selected = select_case_protocol(reviews, agent_results_seen=False)
    value = read_json(CANDIDATE_ROOT / "selection.json")

    expected_decision = {
        ("frozen", 72): "two-case-72",
        ("frozen", 36): "single-case-36",
        ("stop", 0): "no-click-case-stop",
    }[(selected.status, selected.run_budget)]
    assert value["decision"] in ALLOWED_DECISIONS
    assert value["decision"] == expected_decision
    assert value["selected_candidate_ids"] == list(selected.case_ids)
    assert value["run_budget"] == selected.run_budget
    assert value["agent_results_seen"] is False
    if len(selected.case_ids) == 2:
        subsystems = {
            next(subsystem for _, candidate, subsystem in CANDIDATES if candidate == candidate_id)
            for candidate_id in selected.case_ids
        }
        assert len(subsystems) == 2


def test_selected_cases_are_non_leaking_and_protect_all_control_plane_paths(tmp_path: Path) -> None:
    selection = read_json(CANDIDATE_ROOT / "selection.json")
    for candidate_id in selection["selected_candidate_ids"]:
        directory = next(
            directory for directory, candidate, _ in CANDIDATES if candidate == candidate_id
        )
        candidate_root = CANDIDATE_ROOT / directory
        case = load_case(EVAL_ROOT / "cases" / f"{candidate_id}.yaml")
        assert case.image == IMAGE
        assert (EVAL_ROOT / "repos" / "mutations" / f"{candidate_id}.patch").read_bytes() == (
            candidate_root / "mutation.patch"
        ).read_bytes()
        assert (
            EVAL_ROOT / "repos" / "reference-patches" / f"{candidate_id}.patch"
        ).read_bytes() == (candidate_root / "reference.patch").read_bytes()
        hidden_files = list((candidate_root / "hidden").glob("test_*.py"))
        assert len(hidden_files) == 1
        frozen_hidden = EVAL_ROOT.parent / case.grader.hidden_tests / hidden_files[0].name
        assert frozen_hidden.read_bytes() == hidden_files[0].read_bytes()
        task = case.task.lower()
        assert "src/click" not in task
        assert ".py" not in task
        assert "casefold" not in task
        assert "utf-8" not in task
        assert "return " not in task
        expected = {
            Path("tests"),
            Path("LICENSE.txt"),
            Path("PROVENANCE.md"),
            Path("pyproject.toml"),
            Path("conftest.py"),
            Path("sitecustomize.py"),
            Path("usercustomize.py"),
            Path("tests_hidden"),
        }
        expected.add(Path(case.public_verification.commands[1].removeprefix("python ")))
        assert set(case.grader.protected_paths) == expected

        prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / candidate_id)
        assert not (prepared.agent / "evals").exists()
        assert not list(prepared.agent.rglob("*_hidden.py"))
        for path in expected - {Path("tests")}:
            target = prepared.agent / path
            if target.exists():
                target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
            else:
                target.write_text("tampered\n", encoding="utf-8")
            assert _integrity_violation(prepared.baseline, prepared.agent, case.grader.protected_paths)
            if target.exists() and not (prepared.baseline / path).exists():
                target.unlink()
            elif (prepared.baseline / path).is_file():
                shutil.copy2(prepared.baseline / path, target)

        protected_test = prepared.agent / "tests" / "test_options.py"
        original_test = protected_test.read_bytes()
        protected_test.write_bytes(original_test + b"\n# tampered\n")
        assert _integrity_violation(prepared.baseline, prepared.agent, case.grader.protected_paths)
        protected_test.write_bytes(original_test)

        protected_test.unlink()
        try:
            protected_test.symlink_to("test_parser.py")
        except OSError:
            protected_test.write_bytes(original_test)
        else:
            assert _integrity_violation(prepared.baseline, prepared.agent, case.grader.protected_paths)
            protected_test.unlink()
            protected_test.write_bytes(original_test)

        (prepared.agent / "tests" / "__pycache__").mkdir(exist_ok=True)
        (prepared.agent / "tests" / "__pycache__" / "runtime.pyc").write_bytes(b"cache")
        (prepared.agent / "tests" / ".pytest_cache").mkdir(exist_ok=True)
        (prepared.agent / "tests" / ".pytest_cache" / "state").write_text("cache", encoding="utf-8")
        assert not _integrity_violation(prepared.baseline, prepared.agent, case.grader.protected_paths)


@pytest.mark.docker
@pytest.mark.timeout(600)
@pytest.mark.parametrize("directory,candidate_id,subsystem_id", CANDIDATES)
def test_candidate_bug_fix_broken_edit_and_timing_matrix(
    tmp_path: Path, directory: str, candidate_id: str, subsystem_id: str
) -> None:
    root = CANDIDATE_ROOT / directory
    candidate = read_json(root / "candidate.json")
    workspace = tmp_path / candidate_id
    shutil.copytree(TEMPLATE, workspace)
    apply_patch(workspace, root / "mutation.patch")

    commands = candidate["acceptance_commands"]
    assert docker_run(workspace, commands["upstream_owned"])["ok"] is True
    assert docker_run(workspace, commands["public_pytest"])["ok"] is False
    assert docker_run(workspace, commands["standalone_repro"])["ok"] is False
    hidden_bug = tmp_path / f"{candidate_id}-hidden-bug"
    shutil.copytree(workspace, hidden_bug)
    shutil.copytree(root / "hidden", hidden_bug / "tests_hidden")
    assert docker_run(hidden_bug, commands["hidden_behavior"])["ok"] is False

    apply_patch(workspace, root / "reference.patch")
    assert docker_run(workspace, commands["upstream_owned"])["ok"] is True
    fixed_public = docker_run(workspace, commands["public_pytest"])
    assert fixed_public["ok"] is True, fixed_public
    assert docker_run(workspace, commands["standalone_repro"])["ok"] is True
    hidden_fixed = tmp_path / f"{candidate_id}-hidden-fixed"
    shutil.copytree(workspace, hidden_fixed)
    shutil.copytree(root / "hidden", hidden_fixed / "tests_hidden")
    assert docker_run(hidden_fixed, commands["hidden_behavior"])["ok"] is True

    apply_patch(workspace, root / "broken.patch")
    assert docker_run(workspace, commands["public_pytest"])["ok"] is False
    assert docker_run(workspace, commands["standalone_repro"])["ok"] is False
    apply_patch(workspace, root / "broken.patch", reverse=True)
    assert docker_run(workspace, commands["public_pytest"])["ok"] is True
    assert docker_run(workspace, commands["standalone_repro"])["ok"] is True

    for command in (commands["public_pytest"], commands["standalone_repro"]):
        results = [docker_run(workspace, command) for _ in range(3)]
        assert all(result["ok"] for result in results), results
        assert all(int(result["duration_ms"]) <= 90_000 for result in results), results
