from __future__ import annotations

import os
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
CASE_PATH = EVAL_ROOT / "cases/rich-markdown-hyperlinks-option-01.yaml"
MUTATION = EVAL_ROOT / "repos/mutations/rich-markdown-hyperlinks-option-01.patch"
REFERENCE = EVAL_ROOT / "repos/reference-patches/rich-markdown-hyperlinks-option-01.patch"


def _case() -> CaseSpec:
    return load_case(CASE_PATH)


def _executor(case: CaseSpec) -> DockerCommandExecutor:
    return DockerCommandExecutor(case.image)


def _grade(case: CaseSpec, prepared: PreparedWorkspace):
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    return grade_case(case, prepared, patch, EVAL_ROOT, _executor(case))


def _checks(checks):
    return {check.name: check for check in checks}


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
