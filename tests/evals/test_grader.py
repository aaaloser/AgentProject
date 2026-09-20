from __future__ import annotations

import locale
import subprocess
import time
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.grader import grade_case
from mokioclaw.evals.models import CaseSpec
from mokioclaw.evals.patches import _reject_unsafe_headers, create_patch
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.evals.workspace import PreparedWorkspace, prepare_workspace


PROJECT_ROOT = Path(__file__).parents[2]
EVAL_ROOT = PROJECT_ROOT / "evals"
CASE_PATH = EVAL_ROOT / "cases/mini-api-pagination-boundary-01.yaml"


class LocalCommandExecutor:
    def run(self, *, workspace: Path, command: str, timeout_seconds: int, max_output_chars: int):
        started = time.perf_counter()
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
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


def prepare_case(tmp_path: Path, name: str) -> tuple[CaseSpec, PreparedWorkspace]:
    case = load_case(CASE_PATH)
    prepared = prepare_workspace(case, EVAL_ROOT, tmp_path / name)
    return case, prepared


def check_map(checks):
    return {check.name: check for check in checks}


def test_mutated_workspace_passes_public_tests_but_fails_hidden_grader(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "mutated")
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    checks = grade_case(case, prepared, patch, EVAL_ROOT, LocalCommandExecutor())
    checks_by_name = check_map(checks)

    assert checks_by_name["public_regression"].passed is True
    assert checks_by_name["hidden_tests"].passed is False


def test_reference_patch_passes_all_grader_checks(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "reference")
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(EVAL_ROOT / "repos/reference-patches/mini-api-pagination-boundary.patch")],
        cwd=prepared.agent,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    checks = grade_case(case, prepared, patch, EVAL_ROOT, LocalCommandExecutor())

    assert all(check.passed for check in checks)


def test_created_patch_uses_portable_repository_relative_headers(tmp_path: Path) -> None:
    _, prepared = prepare_case(tmp_path, "portable-headers")
    source = prepared.agent / "src/mini_api/pagination.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    patch = create_patch(prepared, prepared.run_root / "final.patch")
    diff = patch.read_text(encoding="utf-8")

    assert "--- a/src/mini_api/pagination.py" in diff
    assert "+++ b/src/mini_api/pagination.py" in diff
    assert "baseline-export" not in diff
    assert "agent-export" not in diff


def test_created_patch_decodes_git_output_as_utf8_on_windows_locale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "gbk")
    _, prepared = prepare_case(tmp_path, "utf8-diff")
    source = prepared.agent / "src/mini_api/pagination.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed \u201d\n", encoding="utf-8")

    patch = create_patch(prepared, prepared.run_root / "final.patch")
    diff = patch.read_text(encoding="utf-8")

    assert "changed" in diff


def test_created_patch_rewrites_new_file_diff_git_header(tmp_path: Path) -> None:
    _, prepared = prepare_case(tmp_path, "new-file-header")
    (prepared.agent / "NOTEPAD.md").write_text("# changed \u201d\n", encoding="utf-8")

    patch = create_patch(prepared, prepared.run_root / "final.patch")
    diff = patch.read_text(encoding="utf-8")

    assert "diff --git a/NOTEPAD.md b/NOTEPAD.md" in diff
    assert "agent-export" not in diff


def test_created_patch_normalizes_windows_crlf_for_whitespace_error(tmp_path: Path) -> None:
    _, prepared = prepare_case(tmp_path, "crlf-new-file")
    (prepared.agent / "NOTEPAD.md").write_text("# notes\r\n\r\nvalue\r\n", encoding="utf-8")

    patch = create_patch(prepared, prepared.run_root / "final.patch")
    patch_bytes = patch.read_bytes()

    assert b"\r\n" not in patch_bytes
    result = subprocess.run(
        ["git", "apply", "--whitespace=error", str(patch)],
        cwd=prepared.baseline,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    assert result.returncode == 0, result.stderr


def test_quoted_windows_absolute_patch_header_is_rejected() -> None:
    diff = '--- "a/C:\\\\temp\\\\secrets.txt"\n+++ b/safe.txt\n'

    with pytest.raises(ValueError, match="unsafe patch path"):
        _reject_unsafe_headers(diff)


def test_modified_protected_public_test_fails_integrity_check(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "tampered")
    protected = prepared.agent / "tests/test_pagination.py"
    protected.write_text("def test_disabled(): pass\n", encoding="utf-8")
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    checks = grade_case(case, prepared, patch, EVAL_ROOT, LocalCommandExecutor())

    assert check_map(checks)["integrity"].passed is False


def test_protected_directory_detects_missing_modified_and_added_files(tmp_path: Path) -> None:
    for action in ("missing", "modified", "added"):
        case, prepared = prepare_case(tmp_path, action)
        case = replace(case, grader=replace(case.grader, protected_paths=(Path("tests"),)))
        target = prepared.agent / "tests/test_pagination.py"
        if action == "missing":
            target.unlink()
        elif action == "modified":
            target.write_text("def test_disabled(): pass\n", encoding="utf-8")
        else:
            (prepared.agent / "tests/extra.py").write_text("x = 1\n", encoding="utf-8")
        checks = grade_case(
            case, prepared, create_patch(prepared, prepared.run_root / "final.patch"), EVAL_ROOT, LocalCommandExecutor()
        )
        assert check_map(checks)["integrity"].passed is False


def test_protected_manifest_ignores_runtime_caches(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "cache")
    case = replace(case, grader=replace(case.grader, protected_paths=(Path("tests"),)))
    (prepared.agent / "tests/__pycache__").mkdir()
    (prepared.agent / "tests/__pycache__/x.pyc").write_bytes(b"cache")
    (prepared.agent / "tests/.pytest_cache").mkdir()
    (prepared.agent / "tests/.pytest_cache/state").write_text("cache", encoding="utf-8")
    checks = grade_case(
        case, prepared, create_patch(prepared, prepared.run_root / "final.patch"), EVAL_ROOT, LocalCommandExecutor()
    )
    assert check_map(checks)["integrity"].passed is True


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_baseline_absent_protected_path_must_remain_absent(tmp_path: Path, kind: str) -> None:
    case, prepared = prepare_case(tmp_path, f"absent-{kind}")
    case = replace(case, grader=replace(case.grader, protected_paths=(Path("conftest.py"),)))
    target = prepared.agent / "conftest.py"
    if kind == "file":
        target.write_text("x = 1\n", encoding="utf-8")
    elif kind == "directory":
        target.mkdir()
    else:
        try:
            target.symlink_to("missing-target.py")
        except OSError:
            pytest.skip("symlink creation unavailable")
    checks = grade_case(
        case, prepared, create_patch(prepared, prepared.run_root / "final.patch"), EVAL_ROOT, LocalCommandExecutor()
    )
    assert check_map(checks)["integrity"].passed is False


def test_protected_file_replaced_by_symlink_fails_integrity(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "file-to-symlink")
    case = replace(case, grader=replace(case.grader, protected_paths=(Path("tests/test_pagination.py"),)))
    target = prepared.agent / "tests/test_pagination.py"
    target.unlink()
    try:
        target.symlink_to("test_cli.py")
    except OSError:
        pytest.skip("symlink creation unavailable")
    checks = grade_case(
        case, prepared, create_patch(prepared, prepared.run_root / "final.patch"), EVAL_ROOT, LocalCommandExecutor()
    )
    assert check_map(checks)["integrity"].passed is False


def test_protected_directory_new_empty_directory_fails_integrity(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "empty-directory")
    case = replace(case, grader=replace(case.grader, protected_paths=(Path("tests"),)))
    (prepared.agent / "tests/new-empty").mkdir()
    checks = grade_case(
        case, prepared, create_patch(prepared, prepared.run_root / "final.patch"), EVAL_ROOT, LocalCommandExecutor()
    )
    assert check_map(checks)["integrity"].passed is False


@pytest.mark.docker
def test_reference_patch_passes_in_offline_docker_grader(tmp_path: Path) -> None:
    case, prepared = prepare_case(tmp_path, "docker-reference")
    subprocess.run(
        ["git", "apply", "--whitespace=error", str(EVAL_ROOT / "repos/reference-patches/mini-api-pagination-boundary.patch")],
        cwd=prepared.agent,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_DIR": "/dev/null"},
    )
    patch = create_patch(prepared, prepared.run_root / "final.patch")
    checks = grade_case(
        case,
        prepared,
        patch,
        EVAL_ROOT,
        DockerCommandExecutor("mokioclaw-eval-python:3.13"),
    )

    assert all(check.passed for check in checks)
