"""Atomic, minimal local task records; runtime cleanup belongs to the controller."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
from pathlib import Path

from mokioclaw.dashboard.task_filesystem import _is_reparse
from mokioclaw.dashboard.task_models import ExecutionReceipt, PublicTaskEvent, TaskRecord, TaskSpec


class TaskConflict(ValueError):
    """A request conflicts with persisted task identity or lifecycle."""


_ACTIVE = frozenset({"preparing", "running", "awaiting_approval", "verifying", "stopping", "cancelling", "cleanup_failed"})
_TERMINAL = frozenset({"completed", "failed", "cancelled", "timed_out", "interrupted"})
_NEXT = {
    "draft": frozenset({"preparing"}),
    "preparing": frozenset({"prepared", "failed", "cancelling"}),
    "prepared": frozenset({"running", "cancelling"}),
    "running": frozenset({"awaiting_approval", "verifying", "stopping", "cancelling"}),
    "awaiting_approval": frozenset({"running", "verifying", "stopping", "cancelling"}),
    "verifying": frozenset({"running", "awaiting_approval", "stopping", "cancelling"}),
    "stopping": frozenset({"completed", "failed", "timed_out", "interrupted", "cleanup_failed"}),
    "cancelling": frozenset({"cancelled", "cleanup_failed"}),
    "cleanup_failed": frozenset({"failed"}),
}
_UPDATABLE = frozenset({
    "attempt_id", "failure_kind", "verification_status", "worker_pid", "worker_created_at", "instance_id",
    "owned_request_ids", "cleanup_confirmed",
})


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TaskStore:
    def __init__(self, root: Path, *, verified_records: tuple[TaskRecord, ...] | None = None):
        self.root = Path(root)
        self._lock = threading.RLock()
        self._records: dict[str, TaskRecord] = {}
        self._keys: dict[str, tuple[str, str]] = {}
        if verified_records is not None:
            for record in verified_records:
                if (type(record) is not TaskRecord or record.task_id in self._records
                        or record.idempotency_digest in self._keys):
                    raise TaskConflict("Invalid task record identity")
                self._records[record.task_id] = record
                self._keys[record.idempotency_digest] = (record.request_digest, record.task_id)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.glob("*/record.json"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["events"] = tuple(PublicTaskEvent(**event) for event in raw.get("events", ()))
            raw["owned_request_ids"] = tuple(raw.get("owned_request_ids", ()))
            raw["execution_receipts"] = tuple(ExecutionReceipt(**item) for item in raw.get("execution_receipts", ()))
            record = TaskRecord(**raw)
            if path.parent.name != record.task_id or record.task_id in self._records:
                raise TaskConflict("Invalid task record identity")
            self._records[record.task_id] = record
            self._keys[record.idempotency_digest] = (record.request_digest, record.task_id)

    def create(self, spec: TaskSpec, idempotency_key: str) -> TaskRecord:
        if spec.task_id or not idempotency_key or len(idempotency_key) > 256:
            raise TaskConflict("Invalid task creation identity")
        request = asdict(spec)
        request.pop("task_id")
        request.pop("created_at")
        request_digest = _digest(request)
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self._lock:
            existing = self._keys.get(key_digest)
            if existing:
                if existing[0] != request_digest:
                    raise TaskConflict("Idempotency key belongs to another request")
                return self._records[existing[1]]
            task_id = secrets.token_urlsafe(18)
            while task_id in self._records:
                task_id = secrets.token_urlsafe(18)
            record = TaskRecord(
                task_id=task_id,
                repo_id=spec.repo_id,
                base_sha=spec.base_sha,
                anchor_sha=spec.anchor_sha,
                manifest_digest=spec.manifest_digest,
                created_at=_timestamp(),
                state="draft",
                attempt_id=None,
                sequence=0,
                request_digest=request_digest,
                idempotency_digest=key_digest,
            )
            self._save_spec(replace(spec, task_id=task_id, created_at=record.created_at))
            self._save(record)
            self._records[task_id] = record
            self._keys[key_digest] = (request_digest, task_id)
            return record

    def get_spec(self, task_id: str) -> TaskSpec:
        with self._lock:
            record = self._records[task_id]
            path = self.root / task_id / "spec.json"
            if (not path.is_file() or _is_reparse(path.parent) or _is_reparse(path)):
                raise TaskConflict("Task has no trusted private specification")
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or set(raw) != {item.name for item in fields(TaskSpec)}:
                    raise ValueError("Invalid specification fields")
                for name in ("source_read_scope", "source_write_scope", "verification_commands"):
                    if not isinstance(raw[name], list) or not all(isinstance(value, str) for value in raw[name]):
                        raise ValueError("Invalid specification scope")
                    raw[name] = tuple(raw[name])
                spec = TaskSpec(**raw)
                request = asdict(spec)
                request.pop("task_id")
                request.pop("created_at")
                if (spec.task_id != task_id or spec.created_at != record.created_at
                        or _digest(request) != record.request_digest):
                    raise ValueError("Specification identity changed")
            except (OSError, TypeError, ValueError) as exc:
                raise TaskConflict("Task private specification is invalid") from exc
            return spec

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            return self._records[task_id]

    def has_active_task(self, *, exclude_task_id: str | None = None) -> bool:
        with self._lock:
            return any(record.state in _ACTIVE for task_id, record in self._records.items() if task_id != exclude_task_id)

    def transition(self, task_id: str, expected: str, target: str, update: dict[str, object]) -> TaskRecord:
        with self._lock:
            current = self._records[task_id]
            if current.state != expected or target not in _NEXT.get(expected, ()):
                raise TaskConflict("Invalid task state transition")
            if unknown := update.keys() - _UPDATABLE:
                raise TaskConflict(f"Invalid task update fields: {sorted(unknown)}")
            changed = dict(update)
            if target == "running":
                desired_attempt = 1 if current.attempt_id is None else current.attempt_id + (expected == "verifying")
                if changed.get("attempt_id", desired_attempt) != desired_attempt:
                    raise TaskConflict("Invalid attempt identity")
                changed["attempt_id"] = desired_attempt
                changed["execution_started"] = True
            elif "attempt_id" in changed:
                raise TaskConflict("Attempt identity may change only when running begins")
            if target == "cleanup_failed" and changed.get("failure_kind") != "cleanup_failed":
                raise TaskConflict("Cleanup failure requires an explicit failure kind")
            if target in _TERMINAL and current.execution_started and not changed.get("cleanup_confirmed", current.cleanup_confirmed):
                raise TaskConflict("Execution resources must be confirmed stopped before terminal state")
            if target == "failed" and expected == "cleanup_failed" and not changed.get("cleanup_confirmed"):
                raise TaskConflict("Failed cleanup requires reconciliation confirmation")
            if changed.get("cleanup_confirmed") and target not in _TERMINAL:
                raise TaskConflict("Cleanup confirmation belongs to a terminal transition")
            event = PublicTaskEvent(task_id, current.attempt_id, current.sequence + 1, _timestamp(), "state", {"state": target})
            record = replace(current, state=target, sequence=event.sequence, events=current.events + (event,), **changed)
            self._save(record)
            self._records[task_id] = record
            return record

    def record_event(self, task_id: str, attempt_id: int | None, event: PublicTaskEvent) -> PublicTaskEvent:
        with self._lock:
            current = self._records[task_id]
            if current.state in _TERMINAL or current.state == "cleanup_failed":
                raise TaskConflict("Task no longer accepts events")
            if event.task_id != task_id or event.attempt_id != attempt_id or attempt_id != current.attempt_id:
                raise TaskConflict("Event task or attempt identity mismatch")
            if event.sequence != current.sequence + 1:
                raise TaskConflict("Event sequence must advance by one")
            if len(json.dumps(asdict(event), ensure_ascii=False)) > 4096:
                raise TaskConflict("Public event is too large")
            record = replace(current, sequence=event.sequence, events=current.events + (event,))
            self._save(record)
            self._records[task_id] = record
            return event

    def register_command(self, task_id: str, request_id: str) -> TaskRecord:
        """Persist container ownership before Docker create can make it visible."""
        if re.fullmatch(r"[A-Za-z0-9_-]{16,64}", request_id) is None:
            raise TaskConflict("Invalid command identity")
        with self._lock:
            current = self._records[task_id]
            if current.state not in {"running", "awaiting_approval", "verifying"}:
                raise TaskConflict("Task cannot create commands")
            if request_id in current.owned_request_ids:
                raise TaskConflict("Command identity was already used")
            record = replace(current, owned_request_ids=current.owned_request_ids + (request_id,))
            self._save(record)
            self._records[task_id] = record
            return record

    def record_execution_receipt(self, task_id: str, instance_id: str, receipt: ExecutionReceipt) -> TaskRecord:
        """Store only parent-observed execution metadata; never command or output text."""
        if (not isinstance(receipt, ExecutionReceipt)
                or re.fullmatch(r"[A-Za-z0-9_-]{16,64}", receipt.command_request_id) is None
                or not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (
                    receipt.command_sha256, receipt.execution_digest,
                )) or type(receipt.exit_code) is not int or type(receipt.duration_ms) is not int
                or receipt.duration_ms < 0 or type(receipt.ok) is not bool
                or type(receipt.output_truncated) is not bool):
            raise TaskConflict("Invalid execution receipt")
        with self._lock:
            current = self._records[task_id]
            if (current.instance_id != instance_id or current.attempt_id != receipt.attempt_id
                    or current.state not in {"running", "verifying"}
                    or receipt.command_request_id not in current.owned_request_ids
                    or any(item.command_request_id == receipt.command_request_id for item in current.execution_receipts)
                    or len(current.execution_receipts) >= 500):
                raise TaskConflict("Execution receipt is stale")
            record = replace(current, execution_receipts=current.execution_receipts + (receipt,))
            self._save(record)
            self._records[task_id] = record
            return record

    def _save(self, record: TaskRecord) -> None:
        directory = self.root / record.task_id
        directory.mkdir(exist_ok=True)
        path = directory / "record.json"
        temporary = directory / f".record-{secrets.token_hex(8)}.tmp"
        payload = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _save_spec(self, spec: TaskSpec) -> None:
        directory = self.root / spec.task_id
        directory.mkdir(exist_ok=True)
        path = directory / "spec.json"
        temporary = directory / f".spec-{secrets.token_hex(8)}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(asdict(spec), stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
