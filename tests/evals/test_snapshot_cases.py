from __future__ import annotations

import os
import shutil
import subprocess
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
RICH_IMAGE = "mokioclaw-eval-rich:14.3.4"
RICH_CASES = (
    (
        "rich-markdown-hyperlinks-option-01.yaml",
        "tests/test_public_repro_markdown_hyperlinks.py",
        "repro_markdown_hyperlinks.py",
        "rich-markdown-hyperlinks-option-01.patch",
    ),
    (
        "rich-table-no-edge-measure-02.yaml",
        "tests/test_public_repro_table_no_edge_measure.py",
        "repro_table_no_edge_measure.py",
        "rich-table-no-edge-measure-02.patch",
    ),
)
CASE_PATH = EVAL_ROOT / "cases/rich-markdown-hyperlinks-option-01.yaml"
TABLE_CASE_PATH = EVAL_ROOT / "cases/rich-table-no-edge-measure-02.yaml"
MUTATION = EVAL_ROOT / "repos/mutations/rich-markdown-hyperlinks-option-01.patch"
REFERENCE = EVAL_ROOT / "repos/reference-patches/rich-markdown-hyperlinks-option-01.patch"
TABLE_REFERENCE = EVAL_ROOT / "repos/reference-patches/rich-table-no-edge-measure-02.patch"

# These upstream golden-output tests encode the exact behavior under the
# synthetic mutation.  They remain protected and are excluded only from the
# unrelated-vendor smoke; the formal Case public command stays full pytest.
UPSTREAM_SMOKE_IGNORES = {
    "rich-markdown-hyperlinks-option-01": (
        "tests/test_markdown_no_hyperlinks.py",
    ),
    "rich-table-no-edge-measure-02": (
        "tests/test_card.py",
        "tests/test_table.py",
    ),
}


def _case() -> CaseSpec:
    return load_case(CASE_PATH)


def _executor(case: CaseSpec) -> DockerCommandExecutor:
    return DockerCommandExecutor(case.image)


def _grade(case: CaseSpec, prepared: PreparedWorkspace):
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    return grade_case(case, prepared, patch, EVAL_ROOT, _executor(case))


def _checks(checks):
    return {check.name: check for check in checks}


def run(executor: DockerCommandExecutor, workspace: Path, command: str) -> dict:
    return executor.run(
        workspace=workspace,
        command=command,
        timeout_seconds=300,
        max_output_chars=12000,
    )


def _apply_reference(case: CaseSpec, prepared: PreparedWorkspace) -> None:
    reference = EVAL_ROOT / "repos/reference-patches" / f"{case.id}.patch"
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(reference)],
        cwd=prepared.agent,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )


def _hidden_workspace(
    case: CaseSpec, prepared: PreparedWorkspace, root: Path, label: str
) -> Path:
    workspace = root / f"{label}-hidden"
    shutil.copytree(prepared.agent, workspace)
    hidden_source = (EVAL_ROOT.parent / case.grader.hidden_tests).resolve()
    shutil.copytree(hidden_source, workspace / "tests_hidden")
    return workspace


def _native_smoke_command(case: CaseSpec, bridge: str) -> str:
    ignores = (bridge,) + UPSTREAM_SMOKE_IGNORES.get(case.id, ())
    return "python -m pytest -q " + " ".join(
        f"--ignore={path}" for path in ignores
    )


def _is_protected(case: CaseSpec, path: str) -> bool:
    candidate = Path(path)
    return any(candidate == protected or protected in candidate.parents for protected in case.grader.protected_paths)


def _replace_production_bytes(path: Path, old: bytes, new: bytes) -> bytes:
    original = path.read_bytes()
    if original.count(old) != 1:
        raise AssertionError(f"expected one production occurrence in {path}")
    path.write_bytes(original.replace(old, new))
    return original


@pytest.mark.docker
@pytest.mark.timeout(300)
@pytest.mark.parametrize("case_name,bridge,repro,mutation_patch", RICH_CASES)
def test_m1_rich_case_contract(
    case_name: str,
    bridge: str,
    repro: str,
    mutation_patch: str,
    tmp_path: Path,
) -> None:
    case = load_case(EVAL_ROOT / "cases" / case_name)
    assert case.image == RICH_IMAGE
    assert (EVAL_ROOT / "repos/mutations" / mutation_patch).is_file()
    assert _is_protected(case, bridge)
    assert _is_protected(case, repro)

    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case.id)
    executor = DockerCommandExecutor(RICH_IMAGE)
    public_pytest, public_repro = case.public_verification.commands

    # The exact upstream golden tests for these synthetic mutations are the
    # target contract.  Record their red signal, then prove the deterministic
    # unrelated-vendor smoke stays green in both states.
    exact_native = run(executor, prepared.agent, public_pytest)
    assert exact_native["ok"] is False, exact_native
    native = run(executor, prepared.agent, _native_smoke_command(case, bridge))
    assert native["ok"] is True, native
    assert run(executor, prepared.agent, public_repro)["ok"] is False

    hidden_workspace = _hidden_workspace(case, prepared, tmp_path, "bug")
    assert run(executor, hidden_workspace, "python -m pytest -q tests_hidden")["ok"] is False

    _apply_reference(case, prepared)
    assert run(executor, prepared.agent, public_pytest)["ok"] is True
    assert run(executor, prepared.agent, public_repro)["ok"] is True
    fixed_hidden = _hidden_workspace(case, prepared, tmp_path, "fixed")
    assert run(executor, fixed_hidden, "python -m pytest -q tests_hidden")["ok"] is True
    import_check = (
        "python -c \"import pathlib, rich; "
        "assert str(pathlib.Path(rich.__file__).resolve()).startswith('/workspace/')\""
    )
    assert run(executor, prepared.agent, import_check)["ok"] is True


@pytest.mark.docker
@pytest.mark.timeout(300)
@pytest.mark.parametrize("case_name,bridge,repro,mutation_patch", RICH_CASES)
def test_broken_production_edit_turns_public_paths_red_and_restores_green(
    case_name: str,
    bridge: str,
    repro: str,
    mutation_patch: str,
    tmp_path: Path,
) -> None:
    case = load_case(EVAL_ROOT / "cases" / case_name)
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case.id)
    _apply_reference(case, prepared)
    executor = DockerCommandExecutor(RICH_IMAGE)
    public_pytest, public_repro = case.public_verification.commands
    assert run(executor, prepared.agent, public_pytest)["ok"] is True
    assert run(executor, prepared.agent, public_repro)["ok"] is True

    if case.id == "rich-markdown-hyperlinks-option-01":
        production = prepared.agent / "rich/markdown.py"
        old = b"self.style = style\r\n        self.hyperlinks = hyperlinks"
        new = b"self.style = style\r\n        self.hyperlinks = True"
    else:
        production = prepared.agent / "rich/table.py"
        old = b"width = 0\r\n        if self.box and self.show_edge:"
        new = b"width = 0\r\n        if self.box:"
    original = _replace_production_bytes(production, old, new)
    assert run(executor, prepared.agent, public_pytest)["ok"] is False
    assert run(executor, prepared.agent, public_repro)["ok"] is False
    production.write_bytes(original)
    assert run(executor, prepared.agent, public_pytest)["ok"] is True
    assert run(executor, prepared.agent, public_repro)["ok"] is True


@pytest.mark.docker
@pytest.mark.timeout(300)
@pytest.mark.parametrize("case_name,bridge,repro,mutation_patch", RICH_CASES)
def test_default_pytest_path_exposes_the_same_public_failure(
    case_name: str,
    bridge: str,
    repro: str,
    mutation_patch: str,
    tmp_path: Path,
) -> None:
    case = load_case(EVAL_ROOT / "cases" / case_name)
    assert case.public_verification.commands[0] == "python -m pytest -q"
    assert case.public_verification.commands[1] == f"python {repro}"
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case.id)
    executor = DockerCommandExecutor(RICH_IMAGE)
    assert run(executor, prepared.agent, case.public_verification.commands[0])["ok"] is False
    assert run(executor, prepared.agent, case.public_verification.commands[1])["ok"] is False


@pytest.mark.docker
@pytest.mark.timeout(300)
@pytest.mark.parametrize("case_name,bridge,repro,mutation_patch", RICH_CASES)
def test_rich_case_fix_meets_three_run_timing_gate(
    case_name: str,
    bridge: str,
    repro: str,
    mutation_patch: str,
    tmp_path: Path,
) -> None:
    case = load_case(EVAL_ROOT / "cases" / case_name)
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / case.id)
    _apply_reference(case, prepared)
    executor = DockerCommandExecutor(RICH_IMAGE)
    for command in case.public_verification.commands:
        results = [run(executor, prepared.agent, command) for _ in range(3)]
        assert all(result["ok"] for result in results), results
        durations = [int(result["duration_ms"]) for result in results]
        print(f"M1 timing {case.id} :: {command} :: {durations} ms")
        assert all(duration <= 90_000 for duration in durations), {
            "command": command,
            "durations_ms": durations,
        }


@pytest.mark.docker
def test_markdown_hyperlinks_mutation_keeps_upstream_green_but_breaks_repro_and_hidden(tmp_path: Path) -> None:
    case = _case()
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / "mutated")
    executor = _executor(case)

    native = executor.run(
        workspace=prepared.agent,
        # The upstream golden-output test is the exact behavior under mutation;
        # exclude it here to measure the unrelated vendor suite independently.
        command=(
            "python -m pytest -q --ignore=tests/test_public_repro_markdown_hyperlinks.py "
            "--ignore=tests/test_markdown_no_hyperlinks.py"
        ),
        timeout_seconds=case.limits.command_timeout_seconds,
        max_output_chars=6000,
    )
    repro = executor.run(
        workspace=prepared.agent,
        command="python repro_markdown_hyperlinks.py",
        timeout_seconds=case.limits.command_timeout_seconds,
        max_output_chars=6000,
    )
    checks = _checks(_grade(case, prepared))

    assert native["ok"] is True, native
    assert repro["ok"] is False
    assert checks["integrity"].passed is True
    assert checks["public_regression"].passed is False


@pytest.mark.docker
def test_markdown_hyperlinks_reference_patch_passes_public_and_hidden(tmp_path: Path) -> None:
    case = _case()
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / "reference")
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(REFERENCE)],
        cwd=prepared.agent,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    checks = _checks(_grade(case, prepared))

    assert all(check.passed for check in checks.values()), checks


@pytest.mark.docker
def test_table_no_edge_mutation_breaks_repro_and_hidden(tmp_path: Path) -> None:
    case = load_case(TABLE_CASE_PATH)
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / "mutated-table")
    executor = _executor(case)
    native = executor.run(
        workspace=prepared.agent,
        # These two upstream golden-render tests directly encode the width
        # contract under mutation; keep the unrelated vendor suite isolated.
        command=(
            "python -m pytest -q --ignore=tests/test_public_repro_table_no_edge_measure.py "
            "--ignore=tests/test_card.py --ignore=tests/test_table.py"
        ),
        timeout_seconds=case.limits.command_timeout_seconds,
        max_output_chars=6000,
    )
    repro = executor.run(
        workspace=prepared.agent,
        command="python repro_table_no_edge_measure.py",
        timeout_seconds=case.limits.command_timeout_seconds,
        max_output_chars=6000,
    )
    checks = _checks(_grade(case, prepared))

    assert native["ok"] is True, native
    assert repro["ok"] is False
    assert checks["integrity"].passed is True
    assert checks["public_regression"].passed is False


@pytest.mark.docker
def test_table_no_edge_reference_patch_passes_public_and_hidden(tmp_path: Path) -> None:
    case = load_case(TABLE_CASE_PATH)
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / "reference-table")
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(TABLE_REFERENCE)],
        cwd=prepared.agent,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    checks = _checks(_grade(case, prepared))

    assert all(check.passed for check in checks.values()), checks
