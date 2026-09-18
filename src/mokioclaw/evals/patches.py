from __future__ import annotations

import ast
import shutil
import subprocess
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from mokioclaw.evals.workspace import PreparedWorkspace


def _rewrite_diff_paths(diff: str, prepared: PreparedWorkspace, exported: Path) -> str:
    exported_prefix = f"b/{exported.name}/"
    return (
        diff.replace(f"a/{prepared.baseline.name}/", "a/")
        .replace(f"a/{exported.name}/", "a/")
        .replace(exported_prefix, "b/")
    )


def _reject_unsafe_headers(diff: str) -> None:
    for line in diff.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        raw_path = line[4:].split("\t", 1)[0].strip()
        if raw_path == "/dev/null":
            continue
        try:
            decoded_path = ast.literal_eval(raw_path) if raw_path.startswith('"') else raw_path
        except (SyntaxError, ValueError):
            raise ValueError(f"unsafe patch path: {raw_path}") from None
        if not isinstance(decoded_path, str):
            raise ValueError(f"unsafe patch path: {raw_path}")
        path = decoded_path[2:] if decoded_path[:2] in {"a/", "b/"} else decoded_path
        posix_candidate = PurePosixPath(path)
        windows_candidate = PureWindowsPath(path)
        if (
            posix_candidate.is_absolute()
            or windows_candidate.is_absolute()
            or ".." in posix_candidate.parts
            or ".." in windows_candidate.parts
        ):
            raise ValueError(f"unsafe patch path: {raw_path}")


def create_patch(prepared: PreparedWorkspace, output_path: Path) -> Path:
    exported = prepared.run_root / "agent-export"
    baseline_export = prepared.run_root / "baseline-export"
    try:
        shutil.copytree(
            prepared.agent,
            exported,
            ignore=shutil.ignore_patterns(".mokioclaw", "__pycache__", ".pytest_cache"),
        )
        shutil.copytree(
            prepared.baseline,
            baseline_export,
            ignore=shutil.ignore_patterns(".mokioclaw", "__pycache__", ".pytest_cache"),
        )
        result = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--", baseline_export.name, exported.name],
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_DIR": "/dev/null"},
            cwd=prepared.run_root,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(
                result.stderr.decode("utf-8", errors="replace").strip() or "failed to create evaluation patch"
            )
        diff = _rewrite_diff_paths(
            _normalize_diff_bytes(result.stdout),
            PreparedWorkspace(prepared.run_root, baseline_export, prepared.agent),
            exported,
        )
        _reject_unsafe_headers(diff)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(diff.encode("utf-8", errors="surrogateescape"))
        return output_path
    finally:
        shutil.rmtree(exported, ignore_errors=True)
        shutil.rmtree(baseline_export, ignore_errors=True)


def _normalize_diff_bytes(raw: bytes) -> str:
    normalized = raw.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n")
    return normalized.decode("utf-8", errors="surrogateescape")
