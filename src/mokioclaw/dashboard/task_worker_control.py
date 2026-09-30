"""Own task workers and Docker containers until cleanup is confirmed."""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from mokioclaw.dashboard.task_executor import DockerCLI, DockerRunner
from mokioclaw.dashboard.task_models import TaskRecord
from mokioclaw.dashboard.task_store import TaskConflict, TaskStore


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created_at: str


class WorkerLauncher(Protocol):
    def launch(self, task_id: str, work: Path) -> ProcessIdentity: ...
    def activate(self, identity: ProcessIdentity) -> None: ...
    def stop(self, identity: ProcessIdentity) -> bool: ...
    def exited(self, identity: ProcessIdentity) -> bool: ...


class ContainerInventory(Protocol):
    def cleanup_owned(self, instance_id: str, task_id: str) -> bool: ...


class DockerOwnershipCleanup:
    """Find containers by both stable ownership labels, including after worker exit."""

    def __init__(self, docker: DockerRunner | None = None) -> None:
        self.docker = docker or DockerCLI()

    def _list(self, instance_id: str, task_id: str) -> tuple[str, ...] | None:
        args = [
            "docker", "ps", "-a", "--filter", f"label=mokioclaw.instance_id={instance_id}",
            "--filter", f"label=mokioclaw.task_id={task_id}", "--format", "{{.ID}}",
        ]
        try:
            result = self.docker.run(args, timeout_seconds=10)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())

    def cleanup_owned(self, instance_id: str, task_id: str) -> bool:
        owned = self._list(instance_id, task_id)
        if owned is None:
            return False
        for container in owned:
            try:
                removed = self.docker.run(["docker", "rm", "-f", container], timeout_seconds=15)
            except Exception:
                return False
            if removed.returncode != 0:
                return False
        return self._list(instance_id, task_id) == ()


class TaskWorkerController:
    """Serialize run, cancel, finish and restart cleanup around durable task state."""

    def __init__(
        self, *, store: TaskStore, instance_id: str | None = None,
        launcher: WorkerLauncher, containers: ContainerInventory, broker=None,
    ) -> None:
        self.store = store
        self.instance_id = instance_id or secrets.token_urlsafe(18)
        self.launcher = launcher
        self.containers = containers
        self.broker = broker
        self._lock = RLock()

    def start(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self.store.get(task_id)
            if record.state != "prepared" or self.store.has_active_task(exclude_task_id=task_id):
                raise TaskConflict("Another task is active or this task is not prepared")
            work = self.store.root / task_id / "workspace" / "work"
            if not work.is_dir() or work.is_symlink():
                raise TaskConflict("Prepared task work is unavailable")
            identity = self.launcher.launch(task_id, work)
            try:
                record = self.store.transition(task_id, "prepared", "running", {
                    "instance_id": self.instance_id,
                    "worker_pid": identity.pid,
                    "worker_created_at": identity.created_at,
                })
                self.launcher.activate(identity)
                return record
            except Exception:
                self.launcher.stop(identity)
                current = self.store.get(task_id)
                if current.state == "running":
                    self.store.transition(task_id, "running", "stopping", {})
                    self._finish_cleanup(task_id, "failed", "worker_start_failed")
                raise TaskConflict("Task worker could not start") from None

    def cancel(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self.store.get(task_id)
            if record.state in {"completed", "failed", "cancelled", "timed_out", "interrupted", "cleanup_failed"}:
                return record
            if record.state == "prepared":
                self.store.transition(task_id, "prepared", "cancelling", {})
                return self.store.transition(task_id, "cancelling", "cancelled", {"cleanup_confirmed": True})
            if record.state in {"running", "awaiting_approval", "verifying"}:
                record = self.store.transition(task_id, record.state, "cancelling", {})
            if record.state != "cancelling":
                raise TaskConflict("Task cannot be cancelled from this state")
            self._invalidate_approval(record)
            return self._finish_cleanup(task_id, "cancelled")

    def finish(self, task_id: str, outcome: str, failure_kind: str | None = None) -> TaskRecord:
        if outcome not in {"completed", "failed", "timed_out", "interrupted"}:
            raise ValueError("Invalid task outcome")
        with self._lock:
            record = self.store.get(task_id)
            if record.state in {"completed", "failed", "cancelled", "timed_out", "interrupted", "cleanup_failed"}:
                return record
            if record.state == "cancelling":
                self._invalidate_approval(record)
                return self._finish_cleanup(task_id, "cancelled")
            if record.state in {"running", "awaiting_approval", "verifying"}:
                record = self.store.transition(task_id, record.state, "stopping", {})
            if record.state != "stopping":
                raise TaskConflict("Task is not executing")
            self._invalidate_approval(record)
            return self._finish_cleanup(task_id, outcome, failure_kind)

    def register_command(self, task_id: str, request_id: str) -> TaskRecord:
        with self._lock:
            return self.store.register_command(task_id, request_id)

    @contextmanager
    def command_creation(self, task_id: str, attempt_id: int):
        """Serialize ownership registration and container start against cleanup."""
        with self._lock:
            record = self.store.get(task_id)
            if (record.instance_id != self.instance_id or record.attempt_id != attempt_id
                    or record.state not in {"running", "verifying"}):
                raise TaskConflict("Stale task command creation")
            yield

    def reconcile(self) -> None:
        with self._lock:
            for task_id, record in tuple(self.store._records.items()):
                if record.state == "cleanup_failed":
                    if self._resources_stopped(record):
                        self.store.transition(task_id, "cleanup_failed", "failed", {
                            "failure_kind": "cleanup_failed", "cleanup_confirmed": True,
                        })
                    continue
                if record.state in {"running", "awaiting_approval", "verifying", "stopping", "cancelling"}:
                    self._invalidate_approval(record)
                    if record.state in {"running", "awaiting_approval", "verifying"}:
                        self.store.transition(task_id, record.state, "stopping", {})
                        record = self.store.get(task_id)
                    outcome = "cancelled" if record.state == "cancelling" else "interrupted"
                    self._finish_cleanup(task_id, outcome)

    def _invalidate_approval(self, record: TaskRecord) -> None:
        if self.broker is not None and record.attempt_id is not None:
            self.broker.invalidate_attempt(record.task_id, record.attempt_id)

    def _resources_stopped(self, record: TaskRecord) -> bool:
        if record.worker_pid is not None and record.worker_created_at is not None:
            identity = ProcessIdentity(record.worker_pid, record.worker_created_at)
            if not self.launcher.exited(identity) and not self.launcher.stop(identity):
                return False
            if not self.launcher.exited(identity):
                return False
        if record.instance_id is None:
            return False
        return self.containers.cleanup_owned(record.instance_id, record.task_id)

    def _finish_cleanup(self, task_id: str, outcome: str, failure_kind: str | None = None) -> TaskRecord:
        record = self.store.get(task_id)
        if self._resources_stopped(record):
            update: dict[str, object] = {"cleanup_confirmed": True}
            if failure_kind:
                update["failure_kind"] = failure_kind
            return self.store.transition(task_id, record.state, outcome, update)
        return self.store.transition(task_id, record.state, "cleanup_failed", {
            "failure_kind": "cleanup_failed",
        })
