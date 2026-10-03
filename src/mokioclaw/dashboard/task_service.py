"""Coordinate fixed-source previews and asynchronous local task preparation."""

from __future__ import annotations

import os
import re
import secrets
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import RLock, Timer
from types import SimpleNamespace
from typing import Callable

from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.task_approval import ApprovalBroker, ExecutionRequest
from mokioclaw.dashboard.git_reader import LocalGitReader
from mokioclaw.dashboard.task_copy import PreparedTask, _validate_task_root, prepare_task
from mokioclaw.dashboard.task_events import project_task_event
from mokioclaw.dashboard.task_executor import DockerCLI, IsolatedCommandExecutor, TaskCommandGateway, TaskExecutionError
from mokioclaw.dashboard.task_models import ExecutionReceipt, PublicTaskEvent, TaskRecord, TaskResult, TaskSpec
from mokioclaw.dashboard.task_result import (
    ResultSnapshotError, build_task_result, load_result_snapshot, save_result_snapshot,
)
from mokioclaw.dashboard.task_source import TaskSource
from mokioclaw.dashboard.task_store import TaskConflict, TaskStore
from mokioclaw.dashboard.task_worker import TaskWorkerLauncher
from mokioclaw.dashboard.task_worker_control import (
    DockerOwnershipCleanup, ProcessIdentity, TaskWorkerController,
)
from mokioclaw.providers.openai_provider import ProviderSettings


class InvalidTaskRequest(ValueError):
    """Task input is incomplete or exceeds the local task limits."""


class TaskRootBusy(RuntimeError):
    """Another dashboard process owns this task directory."""


class FakeTaskRunner:
    """Exercise task states without importing an Agent, provider, or command executor."""

    def __init__(self, *, step_delay: float = 0.05, outcome: str = "completed") -> None:
        if outcome not in {"completed", "failed", "cleanup_failed"}:
            raise ValueError("Unsupported demo outcome")
        self.step_delay = step_delay
        self.outcome = outcome

    def run(self, service: TaskService, task_id: str) -> None:
        try:
            service.publish_demo_event(task_id, {"kind": "stage", "phase": "entry"})
            time.sleep(self.step_delay)
            service.publish_demo_event(task_id, {"kind": "stage", "phase": "planner"})
            time.sleep(self.step_delay)
            service.demo_transition(task_id, "running", "awaiting_approval")
            service.publish_demo_event(task_id, {
                "kind": "approval_request", "status": "waiting", "request_id": secrets.token_urlsafe(18),
            })
            time.sleep(self.step_delay)
            service.publish_demo_event(task_id, {"kind": "approval_decision", "decision": "approved"})
            service.demo_transition(task_id, "awaiting_approval", "running")
            service.publish_demo_event(task_id, {"kind": "stage", "phase": "code_agent"})
            time.sleep(self.step_delay)
            service.demo_transition(task_id, "running", "verifying")
            service.publish_demo_event(task_id, {"kind": "stage", "phase": "verifier"})
            service.publish_demo_event(task_id, {"kind": "verification", "status": "not_run"})
            time.sleep(self.step_delay)
            service.demo_transition(task_id, "verifying", "stopping")
            if self.outcome == "cleanup_failed":
                service.demo_transition(task_id, "stopping", "cleanup_failed", {"failure_kind": "cleanup_failed"})
            elif self.outcome == "failed":
                service.demo_transition(task_id, "stopping", "failed", {
                    "failure_kind": "demo_failure", "cleanup_confirmed": True,
                })
            else:
                service.demo_transition(task_id, "stopping", "completed", {
                    "verification_status": "not_run", "cleanup_confirmed": True,
                })
        except TaskConflict:
            # Cancellation is resolved by demo_transition; a terminal race emits nothing further.
            return
        except Exception:
            # Never expose exception text from a fake or future injected runner.
            with service._lock:
                current = service.store.get(task_id)
                if current.state == "cancelling":
                    service.store.transition(task_id, "cancelling", "cancelled", {"cleanup_confirmed": True})
                else:
                    if current.state in {"running", "awaiting_approval", "verifying"}:
                        service.store.transition(task_id, current.state, "stopping", {})
                        current = service.store.get(task_id)
                    if current.state == "stopping":
                        service.store.transition(task_id, "stopping", "failed", {
                            "failure_kind": "demo_failure", "cleanup_confirmed": True,
                        })


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
    def __init__(
        self, catalog: RepositoryCatalog, reader: LocalGitReader, task_root: Path,
        *, fake_runner: FakeTaskRunner | None = None,
        worker_controller_factory: Callable[[TaskStore], TaskWorkerController] | None = None,
    ) -> None:
        self.catalog = catalog
        self.reader = reader
        self.task_root = _validate_task_root(Path(task_root), catalog)
        self.task_root.mkdir(parents=True, exist_ok=True)
        self.lease = _TaskRootLease(self.task_root)
        try:
            self.store = TaskStore(self.task_root)
            self.worker_controller = worker_controller_factory(self.store) if worker_controller_factory else None
            if self.worker_controller is not None:
                self.worker_controller.reconcile()
        except Exception:
            self.lease.close()
            raise
        self.source = TaskSource(catalog, reader)
        self.prepare = prepare_task
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mokioclaw-prepare")
        self._lock = RLock()
        self._prepared: dict[str, PreparedTask] = {}
        self._specs: dict[str, TaskSpec] = {}
        self._approval_return_states: dict[tuple[str, str], str] = {}
        self.fake_runner = fake_runner
        self.task_image_digest: str | None = None
        self.task_model_name: str | None = None

    def configure_agent(self, provider_settings: ProviderSettings, image_digest: str) -> None:
        """Install the task capability without starting a worker, container, or model."""
        if not isinstance(provider_settings, ProviderSettings) or not isinstance(image_digest, str):
            raise ValueError("Invalid task capability")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None:
            raise ValueError("Invalid task image digest")
        with self._lock:
            if self.worker_controller is not None:
                raise TaskConflict("Task worker is already configured")
            controller = TaskWorkerController(
                store=self.store,
                launcher=TaskWorkerLauncher(provider_settings, start_payload=self.worker_start_payload),
                containers=DockerOwnershipCleanup(),
                broker=ApprovalBroker(on_request=self._on_approval_request),
            )
            controller.reconcile()
            self.worker_controller = controller
            self.task_image_digest = image_digest
            self.task_model_name = provider_settings.model

    def run_available(self) -> bool:
        """Require the explicitly configured image to exist locally before a run."""
        with self._lock:
            image = self.task_image_digest
            if self.worker_controller is None or image is None or self.task_model_name is None:
                return False
        try:
            found = DockerCLI().run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                timeout_seconds=5, max_output_chars=100,
            )
        except (TaskExecutionError, OSError):
            return False
        return found.returncode == 0 and found.stdout.strip() == image

    def run_policy(self, task_id: str) -> dict:
        """Publish only the immutable task and execution limits for final review."""
        with self._lock:
            record = self.store.get(task_id)
            if record.state != "prepared" or self.worker_controller is None or self.task_image_digest is None:
                raise TaskConflict("Task is not ready for run review")
            spec = self._fixed_spec(task_id)
            return {
                "task_id": task_id, "repo_id": spec.repo_id, "base_sha": spec.base_sha,
                "anchor_sha": spec.anchor_sha, "description": spec.description,
                "source_read_scope": list(spec.source_read_scope),
                "source_write_scope": list(spec.source_write_scope),
                "task_scratch_scope": spec.task_scratch_scope,
                "verification_commands": list(spec.verification_commands),
                "max_seconds": spec.max_seconds, "max_attempts": spec.max_attempts,
                "max_provider_calls": spec.max_provider_calls,
                "max_total_tokens": spec.max_total_tokens,
                "max_output_tokens_per_call": spec.max_output_tokens_per_call,
                "model": self.task_model_name, "image_digest": self.task_image_digest,
                "network": "none",
            }

    def _on_approval_request(self, request: ExecutionRequest) -> None:
        with self._lock:
            current = self.store.get(request.task_id)
            controller = self.worker_controller
            work = self.store.root / request.task_id / "workspace" / "work"
            if (controller is None or current.instance_id != controller.instance_id
                    or current.attempt_id != request.attempt_id
                    or current.state not in {"running", "verifying"}
                    or request.image_digest != self.task_image_digest
                    or Path(request.mount_source).resolve(strict=False) != work.resolve(strict=False)):
                raise TaskConflict("Stale task command request")
            self._approval_return_states[(request.task_id, request.command_request_id)] = current.state
            self.store.transition(request.task_id, current.state, "awaiting_approval", {})
            current = self.store.get(request.task_id)
            event = project_task_event({
                "kind": "approval_request", "status": "waiting",
                "request_id": request.command_request_id, "execution_digest": request.canonical_digest(),
            }, request.task_id, request.attempt_id, current.sequence + 1)
            self.store.record_event(request.task_id, request.attempt_id, event)

    def pending_approvals(self, task_id: str) -> list[dict]:
        with self._lock:
            current = self.store.get(task_id)
            controller = self.worker_controller
            if (controller is None or current.instance_id != controller.instance_id
                    or current.state != "awaiting_approval"):
                return []
            return [{
                "attempt_id": item.attempt_id,
                "command_request_id": item.command_request_id,
                "execution_digest": item.canonical_digest(),
                "command": item.command,
                "cwd": item.cwd,
                "timeout_seconds": item.timeout_seconds,
                "image_digest": item.image_digest,
                "mount_target": item.mount_target,
                "network": item.network,
                "cpu_limit": item.cpu_limit,
                "memory_bytes": item.memory_bytes,
                "pids_limit": item.pids_limit,
                "max_output_chars": item.max_output_chars,
                "policy_version": item.policy_version,
            } for item in controller.broker.pending(task_id)
                if item.attempt_id == current.attempt_id]

    def decide_approval(
        self, task_id: str, attempt_id: int, request_id: str, digest: str, approved: bool,
    ) -> bool:
        with self._lock:
            current = self.store.get(task_id)
            controller = self.worker_controller
            previous = self._approval_return_states.get((task_id, request_id))
            if (controller is None or current.instance_id != controller.instance_id
                    or current.state != "awaiting_approval" or current.attempt_id != attempt_id
                    or previous not in {"running", "verifying"}):
                return False
            if not controller.broker.decide(task_id, attempt_id, request_id, digest, approved):
                return False
            self._approval_return_states.pop((task_id, request_id), None)
            self.store.transition(task_id, "awaiting_approval", previous, {})
            current = self.store.get(task_id)
            event = project_task_event({
                "kind": "approval_decision", "decision": "approved" if approved else "denied",
                "request_id": request_id,
            }, task_id, attempt_id, current.sequence + 1)
            self.store.record_event(task_id, attempt_id, event)
            return True

    def cancel_agent(self, task_id: str) -> TaskRecord:
        with self._lock:
            controller = self.worker_controller
            if controller is None:
                raise TaskConflict("Task worker is unavailable")
            result = controller.cancel(task_id)
            for key in tuple(self._approval_return_states):
                if key[0] == task_id:
                    self._approval_return_states.pop(key, None)
            return result

    def close(self) -> None:
        try:
            if self.worker_controller is not None:
                self.worker_controller.reconcile()
        finally:
            try:
                self.pool.shutdown(wait=True, cancel_futures=False)
            finally:
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
            max_provider_calls=_integer(payload, "max_provider_calls", 1, 24),
            max_total_tokens=_integer(payload, "max_total_tokens", 1, 200_000),
            max_output_tokens_per_call=_integer(payload, "max_output_tokens_per_call", 1, 4096), created_at="",
        )
        with self._lock:
            record = self.store.create(spec, idempotency_key)
            if record.state == "draft":
                self._specs[record.task_id] = replace(spec, task_id=record.task_id, created_at=record.created_at)
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

    def result(self, task_id: str) -> TaskResult:
        with self._lock:
            record = self.store.get(task_id)
            if record.state not in {"completed", "failed", "cancelled", "timed_out", "interrupted"}:
                raise TaskConflict("Task result is not ready")
            spec = self._fixed_spec(task_id)
            root = self.store.root / task_id
            try:
                cached = load_result_snapshot(root, record, spec)
                if cached is not None:
                    return cached
                prepared = SimpleNamespace(
                    root=root, baseline=root / "workspace" / "baseline", work=root / "workspace" / "work",
                )
                result = build_task_result(record, spec, prepared)
                save_result_snapshot(root, record, result)
                return result
            except (OSError, ResultSnapshotError) as exc:
                raise TaskConflict("Task result is unavailable") from exc

    def prepared(self, task_id: str) -> PreparedTask:
        try:
            return self._prepared[task_id]
        except KeyError as exc:
            raise TaskConflict("Task has no prepared workspace") from exc

    def publish_demo_event(self, task_id: str, raw: dict) -> None:
        with self._lock:
            current = self.store.get(task_id)
            if current.state == "cancelling":
                self.store.transition(task_id, "cancelling", "cancelled", {"cleanup_confirmed": True})
                raise TaskConflict("Demo was cancelled")
            event = project_task_event(raw, task_id, current.attempt_id, current.sequence + 1)
            self.store.record_event(task_id, current.attempt_id, event)

    def publish_worker_event(self, task_id: str, instance_id: str, summary: dict) -> PublicTaskEvent:
        with self._lock:
            if not isinstance(summary, dict):
                raise TaskConflict("Invalid task worker event")
            current = self.store.get(task_id)
            if (current.instance_id != instance_id or current.state not in {
                "running", "awaiting_approval", "verifying",
            } or summary.get("attempt_id") != current.attempt_id):
                raise TaskConflict("Stale task worker event")
            event = project_task_event(summary, task_id, current.attempt_id, current.sequence + 1)
            return self.store.record_event(task_id, current.attempt_id, event)

    def _fixed_spec(self, task_id: str) -> TaskSpec:
        spec = self._specs.get(task_id)
        if spec is None:
            spec = self.store.get_spec(task_id)
            self._specs[task_id] = spec
        return spec

    def advance_worker_attempt(self, task_id: str, instance_id: str, expected_attempt: int) -> TaskRecord:
        with self._lock:
            current = self.store.get(task_id)
            spec = self._fixed_spec(task_id)
            if (current.instance_id != instance_id or current.state != "verifying"
                    or current.attempt_id != expected_attempt
                    or expected_attempt >= spec.max_attempts):
                raise TaskConflict("Task attempt cannot advance")
            if self.worker_controller is not None and self.worker_controller.broker is not None:
                self.worker_controller.broker.invalidate_attempt(task_id, expected_attempt)
            return self.store.transition(task_id, "verifying", "running", {})

    def worker_start_payload(self, task_id: str) -> dict:
        with self._lock:
            record = self.store.get(task_id)
            spec = self._fixed_spec(task_id)
            work = self.store.root / task_id / "workspace" / "work"
            if (record.state not in {"prepared", "running"} or spec is None
                    or spec.task_id != task_id or not work.is_dir() or work.is_symlink()):
                raise TaskConflict("Task has no runnable fixed specification")
            return {
                "description": spec.description,
                "source_read_scope": list(spec.source_read_scope),
                "source_write_scope": list(spec.source_write_scope),
                "task_scratch_scope": spec.task_scratch_scope,
                "max_attempts": spec.max_attempts,
                "max_provider_calls": spec.max_provider_calls,
                "max_total_tokens": spec.max_total_tokens,
                "max_output_tokens_per_call": spec.max_output_tokens_per_call,
                "verification_commands": list(spec.verification_commands),
            }

    def _record_execution_receipt(self, request: ExecutionRequest, result: dict) -> None:
        controller = self.worker_controller
        if (controller is None or type(result.get("exit_code")) is not int
                or type(result.get("duration_ms")) is not int
                or type(result.get("ok")) is not bool):
            raise TaskConflict("Execution result has no receipt")
        receipt = ExecutionReceipt(
            attempt_id=request.attempt_id, command_request_id=request.command_request_id,
            command_sha256=hashlib.sha256(request.command.encode("utf-8")).hexdigest(),
            execution_digest=request.canonical_digest(), exit_code=result["exit_code"],
            duration_ms=result["duration_ms"], ok=result["ok"],
            output_truncated=result.get("output_truncated") is True,
        )
        self.store.record_execution_receipt(request.task_id, controller.instance_id, receipt)

    def start_agent(self, task_id: str) -> TaskRecord:
        """Start one prepared task only while the fixed local image is available."""
        with self._lock:
            controller = self.worker_controller
            image = self.task_image_digest
            if controller is None or image is None or controller.broker is None:
                raise TaskConflict("Task execution capability is unavailable")
            if not self.run_available():
                raise TaskConflict("Fixed task image is unavailable")
            self._fixed_spec(task_id)
            record = controller.start(task_id)
            work = self.store.root / task_id / "workspace" / "work"
            try:
                executor = IsolatedCommandExecutor(
                    task_root=self.store.root, task_id=task_id, instance_id=controller.instance_id,
                    image_digest=image, register_request=lambda request_id: controller.register_command(task_id, request_id),
                    creation_guard=lambda request: controller.command_creation(task_id, request.attempt_id),
                )
                gateway = TaskCommandGateway(
                    task_id=task_id, attempt_id=record.attempt_id, workspace=work,
                    image_digest=image, broker=controller.broker, executor=executor,
                    record_receipt=self._record_execution_receipt,
                )
                self.pool.submit(self.follow_worker, task_id, gateway)
            except Exception as exc:
                controller.finish(task_id, "failed", "worker_start_failed")
                raise TaskConflict("Task worker could not start") from exc
            return record

    def follow_worker(self, task_id: str, gateway) -> TaskRecord:
        controller = self.worker_controller
        if controller is None:
            raise TaskConflict("Task worker is unavailable")
        with self._lock:
            spec = self._fixed_spec(task_id)
        initial = self.store.get(task_id)
        if (initial.state != "running" or initial.instance_id != controller.instance_id
                or initial.worker_pid is None or initial.worker_created_at is None):
            raise TaskConflict("Task worker identity is unavailable")
        identity = ProcessIdentity(initial.worker_pid, initial.worker_created_at)
        instance_id = initial.instance_id

        def on_event(summary: dict) -> None:
            with self._lock:
                current = self.store.get(task_id)
                if (summary.get("kind") == "stage" and summary.get("phase") == "verifier"
                        and current.state == "running" and summary.get("attempt_id") == current.attempt_id):
                    self.store.transition(task_id, "running", "verifying", {})
                self.publish_worker_event(task_id, instance_id, summary)

        def on_command(request: dict) -> dict:
            current = self.store.get(task_id)
            if (current.instance_id != instance_id or current.attempt_id != request["attempt_id"]
                    or current.state not in {"running", "awaiting_approval", "verifying"}):
                return {"ok": False, "error": "stale_task_attempt"}
            work = self.store.root / task_id / "workspace" / "work"
            return gateway.run(
                workspace=work, command=request["command"],
                timeout_seconds=request["timeout_seconds"], max_output_chars=request["max_output_chars"],
            )

        def on_attempt(previous: int, next_attempt: int) -> None:
            if next_attempt != previous + 1:
                raise TaskConflict("Invalid task attempt")
            gateway.set_attempt(next_attempt)
            self.advance_worker_attempt(task_id, instance_id, previous)

        def on_done(result: dict) -> None:
            controller.finish(task_id, result["outcome"], result.get("failure_kind"))

        deadline = Timer(spec.max_seconds, lambda: controller.finish(task_id, "timed_out", "timed_out"))
        deadline.daemon = True
        deadline.start()
        try:
            controller.launcher.follow(
                identity, on_event, on_done, on_command=on_command, on_attempt=on_attempt,
            )
        except Exception:
            controller.finish(task_id, "failed", "worker_failed")
        finally:
            deadline.cancel()
            deadline.join()
        return self.store.get(task_id)

    def demo_transition(self, task_id: str, expected: str, target: str, update: dict | None = None) -> TaskRecord:
        with self._lock:
            current = self.store.get(task_id)
            if current.state == "cancelling":
                self.store.transition(task_id, "cancelling", "cancelled", {"cleanup_confirmed": True})
                raise TaskConflict("Demo was cancelled")
            return self.store.transition(task_id, expected, target, update or {})

    def start_demo(self, task_id: str) -> TaskRecord:
        with self._lock:
            if self.fake_runner is None:
                raise TaskConflict("Demo is unavailable")
            record = self.store.get(task_id)
            if self.store.has_active_task(exclude_task_id=task_id):
                raise TaskConflict("Another task is active")
            if record.state != "prepared" or task_id not in self._prepared:
                raise TaskConflict("Task is not prepared")
            record = self.store.transition(task_id, "prepared", "running", {})
            self.pool.submit(self.fake_runner.run, self, task_id)
            return record

    def cancel_demo(self, task_id: str) -> TaskRecord:
        with self._lock:
            record = self.store.get(task_id)
            if record.state == "prepared":
                self.store.transition(task_id, "prepared", "cancelling", {})
                return self.store.transition(task_id, "cancelling", "cancelled", {"cleanup_confirmed": True})
            if record.state in {"running", "awaiting_approval", "verifying"}:
                return self.store.transition(task_id, record.state, "cancelling", {})
            return record
