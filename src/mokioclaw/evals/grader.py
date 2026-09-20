from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mokioclaw.evals.models import CaseSpec, GraderCheck
from mokioclaw.evals.workspace import PreparedWorkspace


PROTECTED_CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache"})


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ignored(relative: Path) -> bool:
    return any(part in PROTECTED_CACHE_DIRS for part in relative.parts) or relative.suffix == ".pyc"


def _protected_manifest(root: Path, protected: Path) -> dict[str, tuple[str, str]]:
    target = root / protected
    if not os.path.lexists(target):
        return {".": ("absent", "")}
    if target.is_symlink():
        return {".": ("symlink", os.readlink(target))}
    if target.is_file():
        return {".": ("file", _digest(target) or "")}

    manifest: dict[str, tuple[str, str]] = {".": ("directory", "")}
    for current, dirnames, filenames in os.walk(target, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(target)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            relative = relative_dir / dirname
            child = current_path / dirname
            if _ignored(relative):
                continue
            key = relative.as_posix()
            if child.is_symlink():
                manifest[key] = ("symlink", os.readlink(child))
            else:
                manifest[key] = ("directory", "")
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            relative = relative_dir / filename
            if _ignored(relative):
                continue
            child = current_path / filename
            key = relative.as_posix()
            manifest[key] = ("symlink", os.readlink(child)) if child.is_symlink() else ("file", _digest(child) or "")
    return manifest


def _integrity_violation(baseline: Path, agent: Path, protected_paths) -> str:
    for protected in protected_paths:
        expected = _protected_manifest(baseline, protected)
        actual = _protected_manifest(agent, protected)
        if expected != actual:
            return f"protected path changed: {protected.as_posix()}"
    return ""


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
    violation = _integrity_violation(prepared.baseline, prepared.agent, case.grader.protected_paths)
    protected_ok = not violation
    checks.append(
        GraderCheck(
            name="integrity",
            passed=protected_ok,
            detail="protected paths unchanged" if protected_ok else violation,
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
