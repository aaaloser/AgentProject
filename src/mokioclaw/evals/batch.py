from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.models import CaseResult, Limits, LimitsOverride, RunStatus, effective_limits, resolved_case_image
from mokioclaw.evals.protocol import StopController
from mokioclaw.evals.report import write_result
from mokioclaw.evals.runner import EvalRunner
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.evals.worker_ledger import WorkerAttemptLedger, scheduled_run_id

@dataclass(frozen=True)
class BatchSpec:
    project_root: Path
    architectures: list[str]
    case_paths: list[Path]
    repeat: int
    output_dir: Path
    limits_override: LimitsOverride | None = None
    experiment_identity: dict[str, Any] | None = None


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


def _validate_uniform_batch(spec: BatchSpec) -> None:
    cases = [load_case(path) for path in spec.case_paths]
    effective = [effective_limits(case.limits, spec.limits_override) for case in cases]
    if effective and len(set(effective)) != 1:
        raise RuntimeError("selected cases have mixed effective limits; refuse to start a mixed batch")
    images = {resolved_case_image(case) for case in cases}
    if len(images) > 1:
        raise RuntimeError("selected cases have mixed resolved images; refuse to start a mixed batch")


def build_experiment_fingerprint(spec: BatchSpec) -> dict[str, Any]:
    load_dotenv(spec.project_root / ".env")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=spec.project_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    cases: dict[str, Any] = {}
    effective: list[Limits] = []
    image_ids: dict[str, str] = {}
    for path in spec.case_paths:
        case = load_case(path)
        limits = effective_limits(case.limits, spec.limits_override)
        effective.append(limits)
        image = resolved_case_image(case)
        if image not in image_ids:
            image_ids[image] = DockerCommandExecutor(image).image_id()
        cases[case.id] = {
            "yaml_sha256": _sha256_bytes(path.read_bytes()),
            "grader_tree_hash": _tree_hash(spec.project_root / case.grader.hidden_tests, "*"),
            "template_tree_hash": _tree_hash(spec.project_root / "evals" / "repos" / "templates" / case.repository.template, "*"),
            "mutation_sha256": _sha256_bytes((spec.project_root / "evals" / "repos" / "mutations" / case.repository.mutation).read_bytes()),
            "image": image,
            "image_digest": image_ids[image],
        }
    if effective and len(set(effective)) != 1:
        raise RuntimeError("selected cases have mixed effective limits; refuse to start a mixed batch")
    identity = {
        "model": os.getenv("MODEL", ""),
        "base_url_host": urlparse(os.getenv("BASE_URL", "")).hostname or "",
        "temperature": 0.0,
        "architectures": sorted(spec.architectures),
        "case_ids": [path.stem for path in spec.case_paths],
        "effective_limits": asdict(effective[0]) if effective else asdict(Limits()),
        "cases": cases,
        "src_hash": _tree_hash(spec.project_root / "src" / "mokioclaw", "*.py"),
    }
    return {
        "schema_version": 3,
        "identity": identity,
        "identity_fingerprint": _sha256_bytes(json.dumps(identity, sort_keys=True).encode("utf-8")),
        "provenance": {
            "git_commit": commit,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "batch_dir": str(spec.output_dir),
        },
    }


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


def _batch_schedule_sha256(spec: BatchSpec, case_ids: list[str], repeat: int) -> str:
    payload = {
        "order": plan_execution_order(spec.architectures, case_ids, repeat),
        "protocol": "legacy-batch-append-only-v1",
    }
    return _sha256_bytes(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def run_batch(spec: BatchSpec, *, repeat: int | None = None) -> dict[str, Any]:
    _validate_uniform_batch(spec)
    output = spec.output_dir
    output.mkdir(parents=True, exist_ok=True)
    experiment_path = output / "experiment.json"
    fingerprint = build_experiment_fingerprint(spec)
    if experiment_path.exists():
        previous = json.loads(experiment_path.read_text(encoding="utf-8"))
        if previous.get("schema_version") != fingerprint["schema_version"]:
            raise RuntimeError("experiment schema version mismatch: start a new batch instead of resuming")
        if previous.get("identity_fingerprint") != fingerprint["identity_fingerprint"]:
            raise RuntimeError("experiment fingerprint mismatch: start a new batch instead of resuming")
    else:
        experiment_path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = output / "manifest.jsonl"
    completed = _load_completed(manifest_path)
    ledger = WorkerAttemptLedger(output)
    case_ids = [path.stem for path in spec.case_paths]
    batch_repeat = repeat or spec.repeat
    schedule_sha256 = _batch_schedule_sha256(spec, case_ids, batch_repeat)
    limits_by_case = {
        path.stem: asdict(effective_limits(load_case(path).limits, spec.limits_override)) for path in spec.case_paths
    }
    executed: list[dict[str, Any]] = []
    execution_order = plan_execution_order(spec.architectures, case_ids, batch_repeat)
    total = len(execution_order)
    stop_controller = StopController(case_count=len(case_ids)) if len(case_ids) in {1, 2} else None
    stop_status: dict[str, Any] = {"stopped": False, "reason": None}
    for index, (architecture, case_id, current_repeat) in enumerate(execution_order, start=1):
        if (architecture, case_id, current_repeat) in completed:
            continue
        if spec.experiment_identity is not None:
            from mokioclaw.evals.experiment_identity import (
                build_experiment_fingerprint as build_identity_fingerprint,
                verify_experiment_fingerprint,
            )

            verify_experiment_fingerprint(
                output / "experiment-fingerprint.json",
                build_identity_fingerprint(spec.experiment_identity),
            )
        case_path = next(path for path in spec.case_paths if path.stem == case_id)
        slot_id = scheduled_run_id(
            case_id=case_id,
            architecture=architecture,
            cell="default",
            repeat=current_repeat,
            schedule_sha256=schedule_sha256,
        )
        attempt = ledger.launch(slot_id)
        print(f"[{index}/{total}] {architecture}/{case_id}/r{current_repeat} ...", flush=True)
        try:
            result = EvalRunner(project_root=spec.project_root).run_case(
                case_path,
                architecture=architecture,
                limits_override=spec.limits_override,
                scheduled_run_id=slot_id,
                worker_attempt_id=attempt.worker_attempt_id,
                run_root=attempt.directory,
            )
        except Exception as exc:  # failure isolation: record and continue
            result = CaseResult(
                run_id=f"{case_id}-batch-error-{index}",
                case_id=case_id,
                status=RunStatus.SETUP_FAILED,
                success=False,
                scheduled_run_id=slot_id,
                worker_attempt_id=attempt.worker_attempt_id,
                failure_stage="setup",
                failure_reason=type(exc).__name__,
                sanitized_reason=type(exc).__name__,
            )
        result.scheduled_run_id = slot_id
        result.worker_attempt_id = attempt.worker_attempt_id
        report_dir = attempt.directory / "report"
        write_result(result, report_dir)
        ledger.terminal(
            slot_id,
            attempt.worker_attempt_id,
            status=result.status.value,
            agent_attempt_count=result.agent_attempt_count or result.attempts,
        )
        row = {
            "architecture": architecture,
            "case_id": case_id,
            "repeat": current_repeat,
            "run_id": result.run_id,
            "scheduled_run_id": slot_id,
            "worker_attempt_id": attempt.worker_attempt_id,
            "attempt_path": attempt.directory.relative_to(output).as_posix(),
            "status": result.status.value,
            "success": result.success,
            "limits": limits_by_case[case_id],
            "report_dir": report_dir.relative_to(output).as_posix(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        executed.append(row)
        print(f"[{index}/{total}] {architecture}/{case_id}/r{current_repeat} -> {row['status']}", flush=True)
        if stop_controller is not None:
            failure_kind = result.failure_kind.value if result.failure_kind is not None else None
            decision = stop_controller.observe(
                round_name=f"R{current_repeat}",
                failure_kind=failure_kind,
                successful_model_response=result.model_call_count > 0,
                token_usage_present=result.total_tokens is not None,
                transport_observable=(
                    failure_kind != "provider_transport" or result.transport_attempt_count > 0
                ),
            )
            stop_status = {
                "stopped": decision.stopped,
                "reason": decision.reason,
                "consecutive_transport": decision.consecutive_transport,
                "round_transport": decision.round_transport,
            }
            if decision.stopped:
                for pending_architecture, pending_case_id, pending_repeat in execution_order[index:]:
                    if (pending_architecture, pending_case_id, pending_repeat) in completed:
                        continue
                    pending_slot = scheduled_run_id(
                        case_id=pending_case_id,
                        architecture=pending_architecture,
                        cell="default",
                        repeat=pending_repeat,
                        schedule_sha256=schedule_sha256,
                    )
                    ledger.mark_not_started(pending_slot, reason=decision.reason or "batch_stopped")
                break
    return {"manifest": str(manifest_path), "executed": executed, "stop_status": stop_status}
