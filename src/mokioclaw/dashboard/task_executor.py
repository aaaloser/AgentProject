"""One-shot task command gateway and isolated Docker command execution."""

from __future__ import annotations

import re
import secrets
import os
import subprocess
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Callable, ContextManager, Protocol

from mokioclaw.dashboard.task_approval import ApprovalBroker, ApprovalRejected, ExecutionRequest
from mokioclaw.dashboard.task_patch import PatchUnsafe, _scan


class TaskExecutionError(RuntimeError):
    """A command could not run inside the fixed task boundary."""


class ReportedTaskToolFailure(TaskExecutionError):
    """The failing inner tool already emitted a safe public diagnostic."""


class DockerCLI:
    """Run Docker CLI operations with bounded output and a filtered environment."""

    def run(
        self, args: list[str], *, timeout_seconds: int, max_output_chars: int = 12000,
    ) -> subprocess.CompletedProcess[str]:
        allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        except OSError as exc:
            raise TaskExecutionError("docker_unavailable") from exc
        buffers: list[bytearray] = [bytearray(), bytearray()]

        def drain(stream, destination: bytearray) -> None:
            while chunk := stream.read(4096):
                if len(destination) < max_output_chars * 4:
                    destination.extend(chunk[: max_output_chars * 4 - len(destination)])
            stream.close()

        threads = [
            Thread(target=drain, args=(process.stdout, buffers[0]), daemon=True),
            Thread(target=drain, args=(process.stderr, buffers[1]), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise TaskExecutionError("docker_command_timeout") from None
        finally:
            for thread in threads:
                thread.join(timeout=5)
        return subprocess.CompletedProcess(
            args, exit_code,
            buffers[0].decode("utf-8", errors="replace")[:max_output_chars],
            buffers[1].decode("utf-8", errors="replace")[:max_output_chars],
        )


class DockerRunner(Protocol):
    def run(
        self, args: list[str], *, timeout_seconds: int, max_output_chars: int = 12000,
    ) -> subprocess.CompletedProcess[str]: ...


_TASK_ID = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


class IsolatedCommandExecutor:
    """Execute one approved command; register ownership before Docker creates it."""

    def __init__(
        self, *, task_root: Path, task_id: str, instance_id: str, image_digest: str,
        docker: DockerRunner | None = None, register_request: Callable[[str], None],
        creation_guard: Callable[[ExecutionRequest], ContextManager[None]] | None = None,
        scan_interval_seconds: float = 0.5,
    ) -> None:
        if not all(_TASK_ID.fullmatch(value) for value in (task_id, instance_id)):
            raise ValueError("Invalid task container identity")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise ValueError("Fixed image digest required")
        if not 0 < scan_interval_seconds <= 5:
            raise ValueError("Invalid workspace scan interval")
        self.task_root = Path(task_root).resolve(strict=False)
        self.task_id = task_id
        self.instance_id = instance_id
        self.image_digest = image_digest
        self.docker = docker or DockerCLI()
        self.register_request = register_request
        self.creation_guard = creation_guard
        self.scan_interval_seconds = scan_interval_seconds

    def _wait_with_workspace_monitor(self, container: str, name: str, work: Path, seconds: int):
        finished = Event()
        response: list[object] = []

        def wait() -> None:
            try:
                response.append(self.docker.run(["docker", "wait", container], timeout_seconds=seconds))
            except Exception as exc:
                response.append(exc)
            finally:
                finished.set()

        thread = Thread(target=wait, daemon=True)
        thread.start()
        overflow = False
        while not finished.wait(self.scan_interval_seconds):
            try:
                _scan(work)
            except (OSError, PatchUnsafe):
                overflow = True
                try:
                    self.docker.run(["docker", "rm", "-f", name], timeout_seconds=15)
                except Exception:
                    pass
                break
        if overflow:
            if not finished.wait(5):
                raise TaskExecutionError("container_cleanup_failed")
            raise TaskExecutionError("workspace_limit_exceeded")
        if not response or isinstance(response[0], Exception):
            raise TaskExecutionError("container_wait_failed")
        return response[0]

    def _check_request(self, request: ExecutionRequest) -> Path:
        expected = self.task_root / self.task_id / "workspace" / "work"
        actual = Path(request.mount_source)
        if (
            request.task_id != self.task_id or request.image_digest != self.image_digest
            or not actual.is_absolute() or actual.resolve(strict=False) != expected
            or request.cwd != "/workspace" or request.mount_target != "/workspace"
            or request.network != "none" or request.env_allowlist != ("PATH", "LANG")
            or request.cpu_limit != 1.0 or request.memory_bytes != 512 * 1024 * 1024
            or request.pids_limit != 64 or request.policy_version != "task-command-v1"
            or type(request.timeout_seconds) is not int or not 1 <= request.timeout_seconds <= 600
            or type(request.max_output_chars) is not int or not 1 <= request.max_output_chars <= 12000
        ):
            raise TaskExecutionError("task_boundary_invalid")
        if not expected.is_dir() or expected.is_symlink() or expected.resolve(strict=True) != expected:
            raise TaskExecutionError("task_workspace_unavailable")
        try:
            _scan(expected)
        except (OSError, PatchUnsafe) as exc:
            raise TaskExecutionError("workspace_limit_exceeded") from exc
        return expected

    def execute(self, request: ExecutionRequest) -> dict:
        work = self._check_request(request)
        try:
            image = self.docker.run(
                ["docker", "image", "inspect", self.image_digest, "--format", "{{.Id}}"],
                timeout_seconds=10,
            )
        except (OSError, TaskExecutionError) as exc:
            raise TaskExecutionError("docker_unavailable") from exc
        if image.returncode != 0 or image.stdout.strip() != self.image_digest:
            raise TaskExecutionError("docker_unavailable")
        if not _TASK_ID.fullmatch(request.command_request_id):
            raise TaskExecutionError("task_boundary_invalid")
        name = f"mokioclaw-task-{self.instance_id}-{self.task_id}-{request.command_request_id}"
        labels = (
            f"mokioclaw.instance_id={self.instance_id}",
            f"mokioclaw.task_id={self.task_id}",
            f"mokioclaw.command_request_id={request.command_request_id}",
        )
        arguments = [
            "docker", "create", "--name", name,
            "--label", labels[0], "--label", labels[1], "--label", labels[2],
            "--network", "none", "--cpus", "1.0", "--memory", "536870912",
            "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={work},dst=/workspace", "--workdir", "/workspace",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint", "/bin/sh", self.image_digest, "-c", request.command,
        ]
        started = time.perf_counter()
        result: dict | None = None
        failure: TaskExecutionError | None = None
        try:
            guard = self.creation_guard(request) if self.creation_guard is not None else nullcontext()
            with guard:
                self.register_request(request.command_request_id)
                created = self.docker.run(arguments, timeout_seconds=15)
                if created.returncode != 0 or not created.stdout.strip():
                    raise TaskExecutionError("container_create_failed")
                container = created.stdout.strip()
                started_result = self.docker.run(["docker", "start", container], timeout_seconds=15)
                if started_result.returncode != 0:
                    raise TaskExecutionError("container_start_failed")
            waited = self._wait_with_workspace_monitor(container, name, work, request.timeout_seconds)
            if waited.returncode != 0 or not waited.stdout.strip().isdigit():
                raise TaskExecutionError("container_wait_failed")
            exit_code = int(waited.stdout.strip())
            logs = self.docker.run(
                ["docker", "logs", "--tail", "200", container], timeout_seconds=10,
                max_output_chars=request.max_output_chars,
            )
            if logs.returncode != 0:
                raise TaskExecutionError("container_logs_failed")
            try:
                _scan(work)
            except (OSError, PatchUnsafe) as exc:
                raise TaskExecutionError("workspace_limit_exceeded") from exc
            result = {
                "ok": exit_code == 0, "exit_code": exit_code, "timed_out": False,
                "stdout": logs.stdout[: request.max_output_chars],
                "stderr": logs.stderr[: request.max_output_chars],
                "output_truncated": (
                    len(logs.stdout) >= request.max_output_chars
                    or len(logs.stderr) >= request.max_output_chars
                ),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
        except TaskExecutionError as exc:
            failure = exc
        except (OSError, subprocess.SubprocessError):
            failure = TaskExecutionError("docker_command_failed")
        try:
            removed = self.docker.run(["docker", "rm", "-f", name], timeout_seconds=15)
            remaining = self.docker.run([
                "docker", "ps", "-a", "--filter", "label=" + labels[0],
                "--filter", "label=" + labels[1], "--filter", "label=" + labels[2],
                "--format", "{{.ID}}",
            ], timeout_seconds=10)
            if remaining.returncode != 0 or remaining.stdout.strip() or (removed.returncode != 0 and result is not None):
                raise TaskExecutionError("container_cleanup_failed")
        except (OSError, subprocess.SubprocessError, TaskExecutionError) as exc:
            raise TaskExecutionError("container_cleanup_failed") from exc
        if failure is not None:
            raise failure
        assert result is not None
        return result


class ApprovedExecutor(Protocol):
    def execute(self, request: ExecutionRequest) -> dict: ...


@dataclass(frozen=True)
class TaskCommandPolicy:
    image_digest: str
    network: str = "none"
    cwd: str = "/workspace"
    mount_target: str = "/workspace"
    env_allowlist: tuple[str, ...] = ("PATH", "LANG")
    cpu_limit: float = 1.0
    memory_bytes: int = 512 * 1024 * 1024
    pids_limit: int = 64
    policy_version: str = "task-command-v1"


class TaskCommandGateway:
    task_gateway = True
    approval_mode = "task"
    shell_platform = "linux"

    def __init__(
        self, *, task_id: str, attempt_id: int, workspace: Path, image_digest: str,
        broker: ApprovalBroker, executor: ApprovedExecutor, policy: TaskCommandPolicy | None = None,
        record_receipt: Callable[[ExecutionRequest, dict], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.workspace = Path(workspace).resolve(strict=False)
        self.policy = policy or TaskCommandPolicy(image_digest=image_digest)
        if self.policy.image_digest != image_digest or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise ValueError("A fixed image digest is required")
        if self.policy.network != "none" or self.policy.cwd != "/workspace" or self.policy.mount_target != "/workspace":
            raise ValueError("Task command isolation policy is invalid")
        if (
            self.policy.env_allowlist != ("PATH", "LANG") or self.policy.cpu_limit != 1.0
            or self.policy.memory_bytes != 512 * 1024 * 1024 or self.policy.pids_limit != 64
            or self.policy.policy_version != "task-command-v1"
        ):
            raise ValueError("Task command resource policy is invalid")
        self.broker = broker
        self.executor = executor
        self.record_receipt = record_receipt
        self._lock = RLock()

    def set_attempt(self, attempt_id: int) -> None:
        with self._lock:
            if attempt_id <= self.attempt_id:
                raise ValueError("Attempt must advance")
            self.broker.invalidate_attempt(self.task_id, self.attempt_id)
            self.attempt_id = attempt_id

    def run(self, *, workspace: Path, command: str, timeout_seconds: int, max_output_chars: int) -> dict:
        if Path(workspace).resolve(strict=False) != self.workspace:
            return {"ok": False, "error": "task_workspace_mismatch"}
        if type(command) is not str or not command.strip() or "\0" in command:
            return {"ok": False, "error": "invalid_task_command"}
        try:
            command_bytes = command.encode("utf-8", errors="strict")
        except UnicodeError:
            return {"ok": False, "error": "invalid_task_command"}
        if len(command_bytes) > 8192 or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
            return {"ok": False, "error": "invalid_task_command"}
        if type(max_output_chars) is not int or not 1 <= max_output_chars <= 12000:
            return {"ok": False, "error": "invalid_task_command"}
        with self._lock:
            attempt_id = self.attempt_id
        request = ExecutionRequest(
            task_id=self.task_id, attempt_id=attempt_id, command_request_id=secrets.token_urlsafe(18),
            command=command, cwd=self.policy.cwd, timeout_seconds=timeout_seconds,
            image_digest=self.policy.image_digest, mount_source=str(self.workspace),
            mount_target=self.policy.mount_target, network=self.policy.network,
            env_allowlist=self.policy.env_allowlist, cpu_limit=self.policy.cpu_limit,
            memory_bytes=self.policy.memory_bytes, pids_limit=self.policy.pids_limit,
            max_output_chars=max_output_chars, policy_version=self.policy.policy_version,
        )
        try:
            decision = self.broker.request(request)
        except ApprovalRejected:
            return {"ok": False, "error": "approval_invalid"}
        if not decision.approved or not self.broker.consume(request):
            return {"ok": False, "error": "approval_denied_or_expired", "command_request_id": request.command_request_id}
        try:
            result = self.executor.execute(request)
        except Exception:
            return {"ok": False, "error": "task_executor_failed", "command_request_id": request.command_request_id}
        if self.record_receipt is not None:
            try:
                self.record_receipt(request, result)
            except Exception:
                return {"ok": False, "error": "task_receipt_failed", "command_request_id": request.command_request_id}
        return {**result, "command_request_id": request.command_request_id}


def run_task_bash(
    gateway: TaskCommandGateway | None, workspace: Path, command: str,
    *, timeout_seconds: int = 120, max_output_chars: int = 6000, run_in_background: bool = False,
) -> dict:
    """Web Task Bash entrypoint; never calls the legacy host Bash implementation."""
    if gateway is None or not getattr(gateway, "task_gateway", False):
        return {"ok": False, "error": "task_command_gateway_unavailable"}
    if run_in_background:
        return {"ok": False, "error": "background_task_command_denied"}
    return gateway.run(
        workspace=workspace, command=command, timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )


def run_task_verification(
    gateway: TaskCommandGateway | None, workspace: Path, command: str,
    *, timeout_seconds: int = 600, max_output_chars: int = 6000,
) -> dict:
    """Web Task verifier entrypoint using the identical one-shot approval gateway."""
    if gateway is None or not getattr(gateway, "task_gateway", False):
        return {"ok": False, "error": "task_command_gateway_unavailable"}
    return gateway.run(
        workspace=workspace, command=command, timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
