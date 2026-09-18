from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mokioclaw.evals.models import CaseSpec, GraderCheck
from mokioclaw.evals.workspace import PreparedWorkspace


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skipped(name: str, detail: str) -> GraderCheck:
    return GraderCheck(name=name, passed=False, detail=f"skipped: {detail}")


def _run_command(executor: Any, workspace: Path, command: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        return executor.run(
            workspace=workspace,
            command=command,
            timeout_seconds=timeout_seconds,
            max_output_chars=6000,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def grade_case(
    case: CaseSpec,
    prepared: PreparedWorkspace,
    patch_path: Path,
    eval_root: Path,
    executor: Any,
) -> list[GraderCheck]:
    checks: list[GraderCheck] = []
    protected_ok = True
    for protected in case.grader.protected_paths:
        baseline_digest = _digest(prepared.baseline / protected)
        agent_digest = _digest(prepared.agent / protected)
        if baseline_digest != agent_digest:
            protected_ok = False
            break
    checks.append(
        GraderCheck(
            name="integrity",
            passed=protected_ok,
            detail="protected paths unchanged" if protected_ok else "protected path modified by Agent",
        )
    )
    if not protected_ok:
        checks.extend(
            [
                _skipped("patch_apply", "integrity check failed"),
                _skipped("public_regression", "integrity check failed"),
                _skipped("hidden_tests", "integrity check failed"),
            ]
        )
        return checks

    grading = prepared.run_root / "grading"
    shutil.copytree(prepared.baseline, grading)
    if patch_path.read_text(encoding="utf-8"):
        patch_result = subprocess.run(
            ["git", "apply", "--whitespace=error", str(patch_path)],
            cwd=grading,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "GIT_DIR": "/dev/null"},
        )
        patch_ok = patch_result.returncode == 0
    else:
        patch_ok = True
    checks.append(
        GraderCheck(
            name="patch_apply",
            passed=patch_ok,
            detail="patch applied" if patch_ok else "final patch could not be applied",
        )
    )
    if not patch_ok:
        checks.extend(
            [
                _skipped("public_regression", "patch application failed"),
                _skipped("hidden_tests", "patch application failed"),
            ]
        )
        return checks

    public_ok = True
    for command in case.public_verification.commands:
        result = _run_command(executor, grading, command, case.limits.command_timeout_seconds)
        if not result.get("ok"):
            public_ok = False
            break
    checks.append(
        GraderCheck(
            name="public_regression",
            passed=public_ok,
            detail="public verification passed" if public_ok else "public verification failed",
        )
    )
    if not public_ok:
        checks.append(_skipped("hidden_tests", "public regression failed"))
        return checks

    hidden_source = (eval_root.parent / case.grader.hidden_tests).resolve()
    hidden_target = grading / "tests_hidden"
    shutil.copytree(hidden_source, hidden_target)
    hidden_result = _run_command(executor, grading, "python -m pytest -q tests_hidden", case.limits.command_timeout_seconds)
    hidden_ok = bool(hidden_result.get("ok"))
    checks.append(
        GraderCheck(
            name="hidden_tests",
            passed=hidden_ok,
            detail="hidden verification passed" if hidden_ok else "hidden verification failed",
        )
    )
    return checks
