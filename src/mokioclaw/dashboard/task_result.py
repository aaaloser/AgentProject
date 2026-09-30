"""Build a bounded public result from trusted task identity and projected evidence."""

from __future__ import annotations

import json
import hashlib
import os
import stat
import tempfile
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING

from mokioclaw.dashboard.task_filesystem import _is_reparse
from mokioclaw.dashboard.task_models import (
    PublicPatchSummary, TaskRecord, TaskResult, TaskSpec, VerificationResult,
)
from mokioclaw.dashboard.task_patch import collect_patch

if TYPE_CHECKING:
    from mokioclaw.dashboard.task_copy import PreparedTask


_MAX_RESULT_BYTES = 2 * 1024 * 1024


class ResultSnapshotError(ValueError):
    """Private result snapshot is unsafe or inconsistent."""


def _fields(model: type) -> set[str]:
    return {field.name for field in fields(model)}


def _result_path(root: Path) -> Path:
    if _is_reparse(root) or not stat.S_ISDIR(root.lstat().st_mode):
        raise ResultSnapshotError("Unsafe task result directory")
    path = root / "result.json"
    if path.exists() or path.is_symlink():
        if _is_reparse(path) or not stat.S_ISREG(path.lstat().st_mode):
            raise ResultSnapshotError("Unsafe task result file")
    return path


def load_result_snapshot(root: Path, record: TaskRecord, spec: TaskSpec) -> TaskResult | None:
    path = _result_path(root)
    if not path.exists():
        return None
    try:
        with path.open("rb") as stream:
            content = stream.read(_MAX_RESULT_BYTES + 1)
        if len(content) > _MAX_RESULT_BYTES:
            raise ResultSnapshotError("Task result is too large")
        envelope = json.loads(content)
        if not isinstance(envelope, dict) or set(envelope) != {"record_sequence", "request_digest", "result"}:
            raise ResultSnapshotError("Invalid task result envelope")
        if envelope["record_sequence"] != record.sequence or envelope["request_digest"] != record.request_digest:
            return None
        raw = envelope["result"]
        if not isinstance(raw, dict) or set(raw) != _fields(TaskResult):
            raise ResultSnapshotError("Invalid task result fields")
        patch = raw["patch_summary"]
        checks = raw["verification_results"]
        files = raw["changed_files"]
        limitations = raw["limitations"]
        if (not isinstance(patch, dict) or set(patch) != _fields(PublicPatchSummary)
                or not isinstance(checks, list) or any(
                    not isinstance(item, dict) or set(item) != _fields(VerificationResult) for item in checks
                ) or not isinstance(files, list) or not all(type(item) is str for item in files)
                or not isinstance(limitations, list) or not all(type(item) is str for item in limitations)):
            raise ResultSnapshotError("Invalid task result contents")
        result = TaskResult(
            **{key: value for key, value in raw.items()
               if key not in {"patch_summary", "verification_results", "changed_files", "limitations"}},
            patch_summary=PublicPatchSummary(**patch),
            verification_results=tuple(VerificationResult(**item) for item in checks),
            changed_files=tuple(files), limitations=tuple(limitations),
        )
        if (result.task_id != record.task_id or result.repo_id != record.repo_id
                or result.base_sha != record.base_sha or result.status != record.state
                or result.failure_kind != record.failure_kind
                or any(check.command not in spec.verification_commands for check in result.verification_results)):
            raise ResultSnapshotError("Task result identity changed")
        return result
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ResultSnapshotError("Task result snapshot is invalid") from exc


def save_result_snapshot(root: Path, record: TaskRecord, result: TaskResult) -> None:
    path = _result_path(root)
    payload = json.dumps({
        "record_sequence": record.sequence, "request_digest": record.request_digest,
        "result": asdict(result),
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_RESULT_BYTES:
        raise ResultSnapshotError("Task result is too large")
    descriptor, temporary = tempfile.mkstemp(prefix=".result-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_task_result(record: TaskRecord, spec: TaskSpec, prepared: PreparedTask) -> TaskResult:
    """Never infer a passing check from model text or an unapproved command."""
    if (record.task_id != spec.task_id or record.repo_id != spec.repo_id
            or record.base_sha != spec.base_sha):
        raise ValueError("Task result identity mismatch")
    limitations: list[str] = []
    if record.cleanup_confirmed:
        patch = collect_patch(prepared, spec.source_write_scope, spec.task_scratch_scope)
        public_patch = PublicPatchSummary(
            patch.status, len(patch.changed_files), patch.added_lines, patch.deleted_lines, patch.reason,
        )
        changed_files = patch.changed_files
        if patch.status == "patch_unavailable":
            limitations.append("patch_unavailable")
    else:
        reason = "cleanup_unconfirmed" if record.execution_started else "workspace_unavailable"
        public_patch = PublicPatchSummary("patch_unavailable", reason=reason)
        changed_files = ()
        limitations.append(reason)

    approvals: set[tuple[int, str]] = set()
    waiting: dict[tuple[int, str], str] = {}
    receipts = {(item.attempt_id, item.command_request_id): item
                for item in record.execution_receipts}
    observed: dict[tuple[int, int], list] = {}
    request_uses: dict[tuple[int, str], int] = {}
    incomplete = False
    for event in record.events:
        attempt = event.attempt_id
        request_id = event.data.get("request_id")
        if type(attempt) is not int:
            continue
        if event.kind == "approval_request" and type(request_id) is str:
            digest = event.data.get("execution_digest")
            if type(digest) is str and (attempt, request_id) not in waiting:
                waiting[(attempt, request_id)] = digest
            else:
                incomplete = True
        elif event.kind == "approval_decision" and event.data.get("decision") == "approved":
            if type(request_id) is str and (attempt, request_id) in waiting:
                approvals.add((attempt, request_id))
        elif event.kind == "verification":
            index = event.data.get("command_index")
            if type(request_id) is str:
                key = (attempt, request_id)
                request_uses[key] = request_uses.get(key, 0) + 1
            if type(index) is int and 0 <= index < len(spec.verification_commands):
                observed.setdefault((attempt, index), []).append(event)
            else:
                incomplete = True

    checks: list[VerificationResult] = []
    for attempt in range(1, (record.attempt_id or 0) + 1):
        for index, command in enumerate(spec.verification_commands):
            candidates = observed.get((attempt, index), ())
            event = candidates[0] if len(candidates) == 1 else None
            data = event.data if event is not None else {}
            request_id = data.get("request_id")
            key = (attempt, request_id)
            receipt = receipts.get(key)
            trustworthy = (
                type(request_id) is str and key in approvals and receipt is not None
                and request_uses.get(key) == 1
                and receipt.execution_digest == waiting.get(key)
                and receipt.command_sha256 == hashlib.sha256(command.encode("utf-8")).hexdigest()
                and type(data.get("exit_code")) is int
                and type(data.get("duration_ms")) is int
                and data.get("status") in {"passed", "failed"}
                and receipt.exit_code == data["exit_code"]
                and receipt.duration_ms == data["duration_ms"]
                and receipt.output_truncated == (data.get("output_truncated") is True)
                and (data["status"] == "passed") == (receipt.ok and receipt.exit_code == 0)
            )
            if candidates and not trustworthy:
                incomplete = True
            checks.append(VerificationResult(
                attempt_id=attempt, command=command,
                command_request_id=request_id if trustworthy else None,
                exit_code=data["exit_code"] if trustworthy else None,
                duration_ms=data["duration_ms"] if trustworthy else None,
                status=data["status"] if trustworthy else "not_run",
                output_redacted=True, output_truncated=data.get("output_truncated") is True if trustworthy else False,
            ))
    if incomplete:
        limitations.append("verification_evidence_incomplete")
    final_checks = [item for item in checks if item.attempt_id == record.attempt_id]
    if not final_checks or any(item.status == "not_run" for item in final_checks):
        verification_status = "not_run"
        limitations.append("verification_not_run")
    elif any(item.status == "failed" for item in final_checks):
        verification_status = "failed"
    else:
        verification_status = "passed"
    if record.state == "completed" and verification_status != "passed":
        limitations.append("completion_unverified")
    if record.state in {"cancelled", "timed_out", "interrupted", "cleanup_failed"}:
        limitations.append("partial_evidence")
    return TaskResult(
        task_id=record.task_id, repo_id=record.repo_id, base_sha=record.base_sha,
        status=record.state, failure_kind=record.failure_kind, changed_files=changed_files,
        patch_summary=public_patch, verification_status=verification_status,
        verification_results=tuple(checks), limitations=tuple(limitations),
    )
