from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from typing import Any

from dotenv import load_dotenv

from mokioclaw.evals.cases import load_case
from mokioclaw.evals.grader import grade_case
from mokioclaw.evals.models import AgentRunConfig, CaseResult, Limits, LimitsOverride, RunStatus, effective_limits, resolved_case_image
from mokioclaw.evals.provider_failures import FailureKind, classify_failure
from mokioclaw.evals.patches import create_patch
from mokioclaw.evals.sandbox import DockerCommandExecutor
from mokioclaw.evals.telemetry import CHECKPOINT_NAME, load_checkpoint
from mokioclaw.evals.workspace import PreparedWorkspace, prepare_workspace
from mokioclaw.providers.call_journal import CallJournal, atomic_json_replace


class EvalRunner:
    def __init__(self, *, project_root: Path, runs_root: Path | None = None) -> None:
        self.project_root = project_root.resolve()
        self.eval_root = self.project_root / "evals"
        self.runs_root = (runs_root or self.project_root / ".mokioclaw/eval-runs").resolve()

    def run_case(
        self,
        case_path: Path,
        architecture: str = "multi-agent",
        limits_override: LimitsOverride | None = None,
        *,
        scheduled_run_id: str = "",
        worker_attempt_id: str = "",
        run_root: Path | None = None,
    ) -> CaseResult:
        started = time.perf_counter()
        case = load_case(case_path)
        limits = effective_limits(case.limits, limits_override)
        run_id = f"{case.id}-{uuid4().hex[:12]}"
        scheduled_run_id = scheduled_run_id or run_id
        worker_attempt_id = worker_attempt_id or f"worker-{uuid4().hex}"
        run_root = run_root or self.runs_root / run_id
        try:
            prepared = prepare_workspace(case, self.eval_root, run_root)
            config = self._run_config(case, prepared, run_id, architecture, limits, scheduled_run_id, worker_attempt_id)
            worker_config = run_root / "worker-config.json"
            worker_config.write_text(json.dumps(_config_payload(config), sort_keys=True), encoding="utf-8")
            artifacts_path = run_root / "run-artifacts.json"
            worker_result = self._run_worker(config, worker_config, architecture, limits.agent_timeout_seconds)
            base_result = CaseResult(
                run_id=run_id,
                case_id=case.id,
                status=worker_result["status"],
                success=False,
                scheduled_run_id=scheduled_run_id,
                worker_attempt_id=worker_attempt_id,
                attempts=0,
                tool_calls=0,
                tool_errors=0,
                latency_ms=round((time.perf_counter() - started) * 1000),
                artifacts={"worker_config": str(worker_config), "run_artifacts": str(artifacts_path)},
                metadata=self._metadata(config, architecture),
            )
            _apply_worker_metrics(base_result, worker_result)
            if worker_result["status"] is not RunStatus.PASSED:
                base_result.failure_stage = "worker"
                base_result.failure_reason = str(worker_result.get("sanitized_reason") or worker_result.get("reason") or "worker did not complete")
                return base_result

            patch_path = create_patch(prepared, run_root / "final.patch")
            base_result.artifacts["patch"] = str(patch_path)
            executor = DockerCommandExecutor(config.sandbox_image)
            try:
                base_result.metadata["sandbox_image_id"] = executor.image_id()
            except Exception as exc:
                classification = classify_failure(
                    exc,
                    at_provider_boundary=False,
                    successful_model_responses=0,
                    tool_activity_count=0,
                    local_kind=FailureKind.SANDBOX,
                )
                base_result.status = RunStatus.SETUP_FAILED
                base_result.failure_stage = "sandbox"
                _apply_classification(base_result, asdict(classification))
                return base_result
            checks = grade_case(case, prepared, patch_path, self.eval_root, executor)
            base_result.grader_checks = checks
            base_result.success = all(check.passed for check in checks)
            base_result.status = RunStatus.PASSED if base_result.success else RunStatus.FAILED
            base_result.first_pass_success = base_result.success and base_result.attempts <= 1
            if not base_result.success:
                base_result.failure_stage = "grader"
                base_result.failure_reason = next((check.detail for check in checks if not check.passed), "grader failed")
            return base_result
        except FileExistsError as exc:
            classification = classify_failure(
                exc, at_provider_boundary=False, successful_model_responses=0, tool_activity_count=0, local_kind=FailureKind.CONFIG
            )
            return CaseResult(
                run_id=run_id,
                case_id=case.id,
                status=RunStatus.SETUP_FAILED,
                success=False,
                scheduled_run_id=scheduled_run_id,
                worker_attempt_id=worker_attempt_id,
                failure_stage="setup",
                failure_reason=classification.sanitized_reason,
                failure_kind=classification.failure_kind,
                sanitized_reason=classification.sanitized_reason,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            classification = classify_failure(
                exc, at_provider_boundary=False, successful_model_responses=0, tool_activity_count=0, local_kind=FailureKind.CONFIG
            )
            return CaseResult(
                run_id=run_id,
                case_id=case.id,
                status=RunStatus.SETUP_FAILED,
                success=False,
                scheduled_run_id=scheduled_run_id,
                worker_attempt_id=worker_attempt_id,
                failure_stage="setup",
                failure_reason=classification.sanitized_reason,
                failure_kind=classification.failure_kind,
                sanitized_reason=classification.sanitized_reason,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )

    def _run_config(
        self,
        case,
        prepared: PreparedWorkspace,
        run_id: str,
        architecture: str,
        limits: Limits,
        scheduled_run_id: str = "",
        worker_attempt_id: str = "",
    ) -> AgentRunConfig:
        load_dotenv(self.project_root / ".env")
        model = os.getenv("MODEL", "")
        base_url = os.getenv("BASE_URL", "")
        if architecture == "multi-agent" and (not os.getenv("API_KEY") or not model or not base_url):
            raise ValueError("MODEL, BASE_URL, and API_KEY are required for multi-agent evaluation")
        host = urlparse(base_url).hostname or ""
        return AgentRunConfig(
            run_id=run_id,
            case_id=case.id,
            task=case.task,
            workspace=prepared.agent,
            architecture=architecture,
            retrieval="grep",
            model=model,
            base_url_host=host,
            temperature=0.0,
            sandbox_image=resolved_case_image(case),
            max_attempts=limits.max_attempts,
            max_tool_calls=limits.max_tool_calls,
            timeout_seconds=limits.agent_timeout_seconds,
            scheduled_run_id=scheduled_run_id or run_id,
            worker_attempt_id=worker_attempt_id or run_id,
            protected_paths=tuple(str(path) for path in case.grader.protected_paths),
            verification_commands=tuple(case.public_verification.commands),
        )

    def _run_worker(self, config: AgentRunConfig, worker_config: Path, architecture: str, timeout: int) -> dict[str, Any]:
        command = [sys.executable, "-m", "mokioclaw.evals.worker", "--config", str(worker_config), "--adapter", architecture]
        checkpoint_path = config.workspace.parent / CHECKPOINT_NAME
        artifacts_path = config.workspace.parent / "run-artifacts.json"
        if not artifacts_path.exists():
            atomic_json_replace(
                artifacts_path,
                {
                    "agent_attempt_count": 0,
                    "case_id": config.case_id,
                    "scheduled_run_id": config.scheduled_run_id or config.run_id,
                    "status": "launching",
                    "tool_calls": 0,
                    "worker_attempt_id": config.worker_attempt_id or config.run_id,
                },
            )
        environment = _worker_environment(self.project_root)
        for key in ("API_KEY", "MODEL", "BASE_URL"):
            if value := os.getenv(key):
                environment[key] = value
        try:
            completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=timeout, cwd=self.project_root)
        except subprocess.TimeoutExpired:
            checkpoint, warning = load_checkpoint(checkpoint_path)
            if warning:
                print(warning, file=sys.stderr)
            return {
                "status": RunStatus.TIMED_OUT,
                "tool_calls": int(checkpoint.get("tool_calls", 0) or 0),
                "reason": "worker timeout",
                "checkpoint": checkpoint,
                "telemetry": asdict(CallJournal(config.workspace.parent).summarize()),
            }
        payload = json.loads(artifacts_path.read_text(encoding="utf-8")) if artifacts_path.exists() else {}
        if payload.get("status") == "budget_exhausted" or completed.returncode == 2:
            result = self._interrupted_result(
                RunStatus.BUDGET_EXHAUSTED, int(payload.get("tool_calls", 0)),
                payload.get("failure_reason", "tool budget exhausted"), checkpoint_path, payload,
            )
            result["telemetry"] = asdict(CallJournal(config.workspace.parent).summarize())
            return result
        if completed.returncode != 0 or payload.get("status") != "completed":
            result = self._interrupted_result(
                RunStatus.SETUP_FAILED, int(payload.get("tool_calls", 0)),
                payload.get("sanitized_reason") or type(completed).__name__, checkpoint_path, payload,
            )
            result["telemetry"] = asdict(CallJournal(config.workspace.parent).summarize())
            return result
        artifacts = payload
        return {
            "status": RunStatus.PASSED,
            "tool_calls": int(artifacts.get("tool_calls", 0)),
            "artifacts": artifacts,
            "telemetry": asdict(CallJournal(config.workspace.parent).summarize()),
        }

    @staticmethod
    def _interrupted_result(status: RunStatus, tool_calls: int, reason: str, checkpoint_path: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        checkpoint, warning = load_checkpoint(checkpoint_path)
        if warning:
            print(warning, file=sys.stderr)
        merged: dict[str, Any] = {}
        if payload:
            merged.update({key: value for key, value in payload.items() if key != "status"})
        for key in ("attempt", "tool_errors", "verification_command_runs"):
            if key in checkpoint and key not in merged:
                merged[key] = checkpoint[key]
                if key == "attempt":
                    merged.setdefault("attempts", checkpoint[key])
        resolved_tool_calls = tool_calls if tool_calls else int(checkpoint.get("tool_calls", 0) or 0)
        result: dict[str, Any] = {"status": status, "tool_calls": resolved_tool_calls, "reason": reason}
        if merged:
            result["artifacts"] = merged
        result["checkpoint"] = checkpoint
        return result

    @staticmethod
    def _metadata(config: AgentRunConfig, architecture: str) -> dict[str, Any]:
        return {
            "model": config.model or "unavailable",
            "base_url_host": config.base_url_host or "unavailable",
            "temperature": config.temperature,
            "architecture": architecture,
            "retrieval": config.retrieval,
            "sandbox_image": config.sandbox_image,
        }


def _apply_worker_metrics(result: CaseResult, worker_result: dict[str, Any]) -> None:
    artifacts = worker_result.get("artifacts", {}) or {}
    result.attempts = int(artifacts.get("attempts", 0) or 0)
    result.agent_attempt_count = int(artifacts.get("agent_attempt_count", result.attempts) or result.attempts)
    result.tool_calls = int(worker_result.get("tool_calls", 0) or 0)
    result.tool_errors = int(artifacts.get("tool_errors", 0) or 0)
    telemetry = worker_result.get("telemetry") or artifacts.get("telemetry") or {}
    result.input_tokens = telemetry.get("input_tokens", artifacts.get("input_tokens"))
    result.output_tokens = telemetry.get("output_tokens", artifacts.get("output_tokens"))
    result.total_tokens = telemetry.get("total_tokens")
    result.telemetry_coverage = str(telemetry.get("coverage") or ("full" if result.input_tokens is not None else "unavailable"))
    result.telemetry_unavailable_reason = telemetry.get("unavailable_reason")
    result.model_call_count = int(telemetry.get("model_call_count", 0) or 0)
    result.transport_attempt_count = int(telemetry.get("transport_attempt_count", 0) or 0)
    result.compression_count = int(artifacts.get("compression_count", 0) or 0)
    trace_path = artifacts.get("trace_path") or ""
    if trace_path:
        result.artifacts["trace"] = str(trace_path)
    result.metadata["handoff_count"] = int(artifacts.get("handoff_count", 0) or 0)
    result.metadata["verification_command_runs"] = int(artifacts.get("verification_command_runs", 0) or 0)
    last_stage = str(artifacts.get("last_stage") or (worker_result.get("checkpoint") or {}).get("last_stage") or "")
    result.metadata["last_stage"] = last_stage
    result.metadata["token_coverage"] = result.telemetry_coverage
    _apply_classification(result, artifacts)
    if worker_result.get("checkpoint"):
        result.metadata["checkpoint"] = worker_result["checkpoint"]


def _apply_classification(result: CaseResult, payload: dict[str, Any]) -> None:
    kind = payload.get("failure_kind")
    if isinstance(kind, FailureKind):
        result.failure_kind = kind
    elif kind:
        result.failure_kind = FailureKind(str(kind))
    result.provider_status = payload.get("provider_status")
    result.provider_phase = payload.get("provider_phase")
    result.retryable = bool(payload.get("retryable", False))
    result.sanitized_reason = str(payload.get("sanitized_reason") or "")
    if result.sanitized_reason:
        result.failure_reason = result.sanitized_reason


def _config_payload(config: AgentRunConfig) -> dict[str, Any]:
    payload = dict(config.__dict__)
    payload["workspace"] = str(config.workspace)
    return payload


def _worker_environment(project_root: Path) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP")
        if key in os.environ
    }
    project_src = str(project_root / "src")
    existing = os.environ.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(part for part in (project_src, existing) if part)
    return environment
