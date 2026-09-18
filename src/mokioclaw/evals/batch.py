from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.models import CaseResult, LimitsOverride, RunStatus, effective_limits
from mokioclaw.evals.report import write_result
from mokioclaw.evals.runner import EvalRunner
from mokioclaw.evals.sandbox import DockerCommandExecutor

EVAL_IMAGE = "mokioclaw-eval-python:3.13"


@dataclass(frozen=True)
class BatchSpec:
    project_root: Path
    architectures: list[str]
    case_paths: list[Path]
    repeat: int
    output_dir: Path
    limits_override: LimitsOverride | None = None


def plan_execution_order(architectures: list[str], case_ids: list[str], repeat: int) -> list[tuple[str, str, int]]:
    return [
        (architecture, case_id, current_repeat)
        for current_repeat in range(1, repeat + 1)
        for case_id in case_ids
        for architecture in architectures
    ]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_hash(root: Path, pattern: str) -> str:
    entries = []
    for path in sorted(root.rglob(pattern)):
        if path.is_file() and "__pycache__" not in path.parts:
            entries.append([path.relative_to(root).as_posix(), _sha256_bytes(path.read_bytes())])
    return _sha256_bytes(json.dumps(entries, sort_keys=True).encode("utf-8"))


def build_experiment_fingerprint(spec: BatchSpec) -> dict[str, Any]:
    load_dotenv(spec.project_root / ".env")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=spec.project_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    fields = {
        "git_commit": commit,
        "model": os.getenv("MODEL", ""),
        "base_url_host": urlparse(os.getenv("BASE_URL", "")).hostname or "",
        "temperature": 0.0,
        "architectures": sorted(spec.architectures),
        "case_ids": [path.stem for path in spec.case_paths],
        "cases_hash": _tree_hash(spec.project_root / "evals" / "cases", "*.yaml"),
        "graders_hash": _tree_hash(spec.project_root / "evals" / "graders", "*.py"),
        "src_hash": _tree_hash(spec.project_root / "src" / "mokioclaw", "*.py"),
        "image_digest": DockerCommandExecutor(EVAL_IMAGE).image_id(),
    }
    fingerprint = _sha256_bytes(json.dumps(fields, sort_keys=True).encode("utf-8"))
    return {"fields": fields, "fingerprint": fingerprint}


def _load_completed(manifest_path: Path) -> set[tuple[str, str, int]]:
    completed: set[tuple[str, str, int]] = set()
    if not manifest_path.exists():
        return completed
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        completed.add((row["architecture"], row["case_id"], int(row["repeat"])))
    return completed


def run_batch(spec: BatchSpec, *, repeat: int | None = None) -> dict[str, Any]:
    if spec.case_paths:
        effective = [effective_limits(load_case(path).limits, spec.limits_override) for path in spec.case_paths]
        if len(set(effective)) != 1:
            raise RuntimeError("selected cases have mixed effective limits: run a batch whose cases share one limits profile")
    output = spec.output_dir
    output.mkdir(parents=True, exist_ok=True)
    experiment_path = output / "experiment.json"
    fingerprint = build_experiment_fingerprint(spec)
    if experiment_path.exists():
        previous = json.loads(experiment_path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint["fingerprint"]:
            raise RuntimeError("experiment fingerprint mismatch: start a new batch instead of resuming")
    else:
        experiment_path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = output / "manifest.jsonl"
    completed = _load_completed(manifest_path)
    case_ids = [path.stem for path in spec.case_paths]
    executed: list[dict[str, Any]] = []
    total = len(plan_execution_order(spec.architectures, case_ids, repeat or spec.repeat))
    for index, (architecture, case_id, current_repeat) in enumerate(
        plan_execution_order(spec.architectures, case_ids, repeat or spec.repeat), start=1
    ):
        if (architecture, case_id, current_repeat) in completed:
            continue
        case_path = next(path for path in spec.case_paths if path.stem == case_id)
        print(f"[{index}/{total}] {architecture}/{case_id}/r{current_repeat} ...", flush=True)
        try:
            result = EvalRunner(project_root=spec.project_root).run_case(case_path, architecture=architecture, limits_override=spec.limits_override)
        except Exception as exc:  # failure isolation: record and continue
            result = CaseResult(
                run_id=f"{case_id}-batch-error-{index}",
                case_id=case_id,
                status=RunStatus.SETUP_FAILED,
                success=False,
                failure_stage="setup",
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
        report_dir = output / "runs" / architecture / f"{case_id}-r{current_repeat}"
        write_result(result, report_dir)
        row = {
            "architecture": architecture,
            "case_id": case_id,
            "repeat": current_repeat,
            "run_id": result.run_id,
            "status": result.status.value,
            "success": result.success,
            "report_dir": report_dir.relative_to(output).as_posix(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        executed.append(row)
        print(f"[{index}/{total}] {architecture}/{case_id}/r{current_repeat} -> {row['status']}", flush=True)
    return {"manifest": str(manifest_path), "executed": executed}
