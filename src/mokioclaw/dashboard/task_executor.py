"""Task command gateway; Task 7 supplies the actual isolated executor."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from mokioclaw.dashboard.task_approval import ApprovalBroker, ApprovalRejected, ExecutionRequest


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
