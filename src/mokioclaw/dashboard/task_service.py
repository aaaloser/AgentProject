"""Coordinate fixed-source previews and asynchronous local task preparation."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.task_copy import PreparedTask, _validate_task_root, prepare_task
from mokioclaw.dashboard.task_models import TaskRecord, TaskSpec
from mokioclaw.dashboard.task_source import TaskSource
from mokioclaw.dashboard.task_store import TaskConflict, TaskStore


class InvalidTaskRequest(ValueError):
    """Task input is incomplete or exceeds the local task limits."""


class TaskRootBusy(RuntimeError):
    """Another dashboard process owns this task directory."""


class _TaskRootLease:
    def __init__(self, root: Path) -> None:
        self.path = root / ".dashboard.lock"
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise TaskRootBusy("Task directory is already in use") from exc

    def close(self) -> None:
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt

            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()


def _integer(payload: dict, key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidTaskRequest("Invalid task limit")
    return value


def _scope(payload: dict) -> tuple[str, ...]:
    raw = payload.get("source_read_scope")
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise InvalidTaskRequest("Invalid source scope")
    return tuple(raw)


class TaskService:
    def __init__(self, catalog: RepositoryCatalog, reader: LocalGitReader, task_root: Path) -> None:
        self.catalog = catalog
        self.reader = reader
        self.task_root = _validate_task_root(Path(task_root), catalog)
        self.task_root.mkdir(parents=True, exist_ok=True)
        self.lease = _TaskRootLease(self.task_root)
        try:
            self.store = TaskStore(self.task_root)
        except Exception:
            self.lease.close()
            raise
        self.source = TaskSource(catalog, reader)
        self.prepare = prepare_task
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mokioclaw-prepare")
        self._lock = RLock()
        self._prepared: dict[str, PreparedTask] = {}

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=False)
        self.lease.close()

    def preview(self, payload: dict):
        return self.source.preview(
            payload["repo_id"], payload["base_sha"], payload["anchor_sha"], _scope(payload),
        )

    def create_task(self, payload: dict, idempotency_key: str) -> TaskRecord:
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip() or len(description) > 4000:
            raise InvalidTaskRequest("Invalid task description")
        commands = payload.get("verification_commands")
        if not isinstance(commands, list) or len(commands) > 10 or not all(
            isinstance(value, str) and 0 < len(value) <= 2000 for value in commands
        ):
            raise InvalidTaskRequest("Invalid verification commands")
        scope = _scope(payload)
        preview = self.source.validate_preview(
            payload["preview_id"], payload["repo_id"], payload["base_sha"], payload["anchor_sha"], scope,
        )
        self.source.require_preparable(preview)
        spec = TaskSpec(
            task_id="", repo_id=preview.repo_id, base_sha=preview.base_sha, anchor_sha=preview.anchor_sha,
            description=description, source_read_scope=preview.source_read_scope,
            source_write_scope=preview.source_write_scope, task_scratch_scope=preview.task_scratch_scope,
            manifest_digest=preview.manifest_digest, max_seconds=_integer(payload, "max_seconds", 1, 1800),
            max_attempts=_integer(payload, "max_attempts", 1, 3), verification_commands=tuple(commands),
            max_provider_calls=_integer(payload, "max_provider_calls", 1, 20),
            max_total_tokens=_integer(payload, "max_total_tokens", 1, 100_000),
            max_output_tokens_per_call=_integer(payload, "max_output_tokens_per_call", 1, 4096), created_at="",
        )
        with self._lock:
            record = self.store.create(spec, idempotency_key)
            if record.state == "draft":
                record = self.store.transition(record.task_id, "draft", "preparing", {})
                self.pool.submit(self._prepare, preview, record.task_id)
            return record

    def _prepare(self, preview, task_id: str) -> None:
        try:
            prepared = self.prepare(preview, task_id, self.task_root, self.catalog, self.reader)
            with self._lock:
                if self.store.get(task_id).state == "preparing":
                    self._prepared[task_id] = prepared
                    self.store.transition(task_id, "preparing", "prepared", {})
        except Exception:
            with self._lock:
                if self.store.get(task_id).state == "preparing":
                    self.store.transition(task_id, "preparing", "failed", {"failure_kind": "preparation_failed"})

    def get(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def prepared(self, task_id: str) -> PreparedTask:
        try:
            return self._prepared[task_id]
        except KeyError as exc:
            raise TaskConflict("Task has no prepared workspace") from exc
