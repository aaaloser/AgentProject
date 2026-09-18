from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.grader import grade_case
from mokioclaw.evals.models import CaseSpec
from mokioclaw.evals.patches import create_patch
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.evals.workspace import PreparedWorkspace, prepare_workspace


PROJECT_ROOT = Path(__file__).parents[2]
EVAL_ROOT = PROJECT_ROOT / "evals"

CORE_CASES = [
    ("config-cli-precedence-order-01.yaml", "config-cli-precedence-order.patch"),
    ("config-cli-json-output-02.yaml", "config-cli-json-output.patch"),
    ("task-queue-retry-state-leak-01.yaml", "task-queue-retry-state-leak.patch"),
    ("task-queue-retry-policy-refactor-02.yaml", "task-queue-retry-policy-refactor.patch"),
    ("mini-api-client-retry-options-02.yaml", "mini-api-client-retry-options.patch"),
]

EXPECTED_PROTECTED_PATHS = {
    "config-cli-precedence-order-01.yaml": (Path("tests/test_config_cli.py"),),
    "config-cli-json-output-02.yaml": (Path("tests/test_config_cli.py"),),
    "task-queue-retry-state-leak-01.yaml": (Path("tests/test_task_queue.py"),),
    "task-queue-retry-policy-refactor-02.yaml": (Path("tests/test_task_queue.py"),),
    "mini-api-client-retry-options-02.yaml": (Path("tests/test_pagination.py"), Path("tests/test_client.py")),
}


class LocalCommandExecutor:
    def run(self, *, workspace: Path, command: str, timeout_seconds: int, max_output_chars: int):
        started = time.perf_counter()
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
        # Inner pytest runs (hidden tests may use tmp_path) must not touch the
        # default basetemp: mixed-elevation ACLs on Windows can deny access to
        # pytest-of-<user> dirs created by processes with different elevation
        # (see WINDOWS_MIGRATION_WORKLOG_2026-09-14.md §10.1).
        temp_root = workspace.parent / "command-temp"
        temp_root.mkdir(exist_ok=True)
        environment["TEMP"] = str(temp_root)
        environment["TMP"] = str(temp_root)
        completed = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
        return {
            "ok": completed.returncode == 0,
            "timed_out": False,
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[:max_output_chars],
            "stderr": completed.stderr[:max_output_chars],
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }


def case_path(case_name: str) -> Path:
    return EVAL_ROOT / "cases" / case_name


def prepare_clean_case(tmp_path: Path, case_name: str) -> tuple[CaseSpec, PreparedWorkspace]:
    case = load_case(case_path(case_name))
    template = EVAL_ROOT / "repos/templates" / case.repository.template
    run_root = tmp_path / f"{case.id}-clean"
    run_root.mkdir()
    baseline = run_root / "baseline"
    agent = run_root / "agent"
    shutil.copytree(template, baseline)
    shutil.copytree(template, agent)
    return case, PreparedWorkspace(run_root=run_root, baseline=baseline, agent=agent)


def apply_patch_to_workspace(workspace: Path, patch_name: str, patch_dir: str) -> None:
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(EVAL_ROOT / patch_dir / patch_name)],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )


def grade_locally(case: CaseSpec, prepared: PreparedWorkspace):
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    return grade_case(case, prepared, patch, EVAL_ROOT, LocalCommandExecutor())


def grade_in_docker(case: CaseSpec, prepared: PreparedWorkspace):
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    return grade_case(case, prepared, patch, EVAL_ROOT, DockerCommandExecutor("mokioclaw-eval-python:3.13"))


def checks_by_name(checks):
    return {check.name: check for check in checks}


def assert_all_checks_pass(checks) -> None:
    failures = [(check.name, check.detail) for check in checks if not check.passed]
    assert not failures, failures


def assert_public_passes_and_hidden_fails(checks) -> None:
    by_name = checks_by_name(checks)
    assert {"integrity", "patch_apply", "public_regression", "hidden_tests"} <= set(by_name)
    for name in ("integrity", "patch_apply", "public_regression"):
        assert by_name[name].passed is True, (name, by_name[name].detail)
    assert by_name["hidden_tests"].passed is False, by_name["hidden_tests"].detail


def snapshot_files(root: Path) -> dict:
    return {
        path.relative_to(root): path.read_bytes().replace(b"\r\n", b"\n")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("case_name,mutation_patch", CORE_CASES)
def test_core_eval_case_has_clean_mutated_and_reference_states(
    tmp_path: Path,
    case_name: str,
    mutation_patch: str,
) -> None:
    clean_case, clean_prepared = prepare_clean_case(tmp_path, case_name)
    assert_all_checks_pass(grade_locally(clean_case, clean_prepared))

    mutated_case = load_case(case_path(case_name))
    mutated = prepare_workspace(mutated_case, EVAL_ROOT, tmp_path / f"{mutated_case.id}-mutated")
    assert_public_passes_and_hidden_fails(grade_locally(mutated_case, mutated))

    reference_case = load_case(case_path(case_name))
    reference = prepare_workspace(reference_case, EVAL_ROOT, tmp_path / f"{reference_case.id}-reference")
    apply_patch_to_workspace(reference.agent, mutation_patch, "repos/reference-patches")
    assert_all_checks_pass(grade_locally(reference_case, reference))


@pytest.mark.parametrize("case_name,mutation_patch", CORE_CASES)
def test_patch_algebra_round_trips_the_clean_template(
    tmp_path: Path,
    case_name: str,
    mutation_patch: str,
) -> None:
    case = load_case(case_path(case_name))
    template = EVAL_ROOT / "repos/templates" / case.repository.template
    clean = tmp_path / f"{case.id}-patch-algebra"
    shutil.copytree(template, clean)
    before = snapshot_files(clean)

    apply_patch_to_workspace(clean, mutation_patch, "repos/mutations")
    assert snapshot_files(clean) != before

    apply_patch_to_workspace(clean, mutation_patch, "repos/reference-patches")
    assert snapshot_files(clean) == before


@pytest.mark.parametrize("case_name,_", CORE_CASES)
def test_case_protects_its_public_tests(case_name: str, _: str) -> None:
    case = load_case(case_path(case_name))

    assert case.grader.protected_paths == EXPECTED_PROTECTED_PATHS[case_name]


@pytest.mark.parametrize("case_name,_", CORE_CASES)
def test_agent_workspace_does_not_contain_hidden_tests(tmp_path: Path, case_name: str, _: str) -> None:
    case = load_case(case_path(case_name))
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case.id)

    assert not (prepared.agent / "evals").exists()
    assert not list(prepared.agent.rglob("*_hidden.py"))


def test_templates_do_not_contain_control_plane_artifacts() -> None:
    templates = EVAL_ROOT / "repos/templates"

    assert not list(templates.rglob("*_hidden.py"))
    assert not list(templates.rglob("*.patch"))


def test_original_pagination_case_still_protects_its_public_test() -> None:
    case = load_case(EVAL_ROOT / "cases/mini-api-pagination-boundary-01.yaml")

    assert case.grader.protected_paths == (Path("tests/test_pagination.py"),)


@pytest.mark.docker
@pytest.mark.parametrize("case_name,mutation_patch", CORE_CASES)
def test_mutated_state_fails_hidden_in_offline_docker(
    tmp_path: Path,
    case_name: str,
    mutation_patch: str,
) -> None:
    case = load_case(case_path(case_name))
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / f"{case.id}-docker-mutated")

    assert_public_passes_and_hidden_fails(grade_in_docker(case, prepared))


@pytest.mark.docker
@pytest.mark.parametrize("case_name,mutation_patch", CORE_CASES)
def test_reference_state_passes_in_offline_docker(
    tmp_path: Path,
    case_name: str,
    mutation_patch: str,
) -> None:
    case = load_case(case_path(case_name))
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / f"{case.id}-docker-reference")
    apply_patch_to_workspace(prepared.agent, mutation_patch, "repos/reference-patches")

    assert_all_checks_pass(grade_in_docker(case, prepared))
