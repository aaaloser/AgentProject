"""One-shot approval identities for isolated task commands."""

from __future__ import annotations

import hashlib
import base64
import json
import re
import time
from dataclasses import asdict, dataclass
from threading import Condition, RLock
from typing import Callable

from mokioclaw.core.approval import ApprovalDecision


class ApprovalRejected(ValueError):
    """An approval identity is invalid, stale, or already used."""


_ID = re.compile(r"[A-Za-z0-9_-]{16,64}\Z")


@dataclass(frozen=True)
class ExecutionRequest:
    task_id: str
    attempt_id: int
    command_request_id: str
    command: str
    cwd: str
    timeout_seconds: int
    image_digest: str
    mount_source: str
    mount_target: str
    network: str
    env_allowlist: tuple[str, ...]
    cpu_limit: float
    memory_bytes: int
    pids_limit: int
    max_output_chars: int
    policy_version: str

    def canonical_digest(self) -> str:
        if not _ID.fullmatch(self.task_id) or not _ID.fullmatch(self.command_request_id):
            raise ApprovalRejected("Invalid request identity")
        if type(self.attempt_id) is not int or self.attempt_id < 1 or not isinstance(self.command, str):
            raise ApprovalRejected("Invalid request content")
        try:
            command_bytes = self.command.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ApprovalRejected("Command cannot be encoded") from exc
        payload = asdict(self)
        payload.pop("command")
        payload["command_utf8_base64"] = base64.b64encode(command_bytes).decode("ascii")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class _Pending:
    request: ExecutionRequest
    digest: str
    deadline: float
    decision: bool | None = None
    invalidated: bool = False
    consumed: bool = False


class ApprovalBroker:
    def __init__(
        self, *, wait_timeout_seconds: float = 120,
        on_request: Callable[[ExecutionRequest], None] | None = None,
    ) -> None:
        if wait_timeout_seconds <= 0 or wait_timeout_seconds > 600:
            raise ValueError("Invalid approval timeout")
        self.wait_timeout_seconds = wait_timeout_seconds
        self._condition = Condition(RLock())
        self._pending: dict[tuple[str, str], _Pending] = {}
        self._seen: set[tuple[str, str]] = set()
        self._invalid_attempts: set[tuple[str, int]] = set()
        self._on_request = on_request

    def request(self, request: ExecutionRequest, *, wait_timeout_seconds: float | None = None) -> ApprovalDecision:
        digest = request.canonical_digest()
        timeout = self.wait_timeout_seconds if wait_timeout_seconds is None else wait_timeout_seconds
        if timeout <= 0 or timeout > 600:
            raise ApprovalRejected("Invalid approval timeout")
        key = (request.task_id, request.command_request_id)
        with self._condition:
            if key in self._seen:
                raise ApprovalRejected("Command request identity was already used")
            self._seen.add(key)
            if (request.task_id, request.attempt_id) in self._invalid_attempts:
                return ApprovalDecision(False, "attempt_invalidated")
            pending = _Pending(request, digest, time.monotonic() + timeout)
            self._pending[key] = pending
        if self._on_request is not None:
            try:
                self._on_request(request)
            except Exception:
                with self._condition:
                    pending.invalidated = True
                    self._condition.notify_all()
                return ApprovalDecision(False, "approval_unavailable")
        with self._condition:
            while pending.decision is None and not pending.invalidated:
                remaining = pending.deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if pending.invalidated:
                return ApprovalDecision(False, "attempt_invalidated")
            if pending.decision is None or time.monotonic() >= pending.deadline:
                pending.invalidated = True
                return ApprovalDecision(False, "approval_timeout")
            return ApprovalDecision(pending.decision, "approved" if pending.decision else "denied")

    def pending(self, task_id: str) -> tuple[ExecutionRequest, ...]:
        with self._condition:
            now = time.monotonic()
            return tuple(
                item.request for (owner, _), item in self._pending.items()
                if owner == task_id and not item.invalidated and not item.consumed
                and item.decision is None and now < item.deadline
            )

    def decide(
        self, task_id: str, attempt_id: int, command_request_id: str, digest: str, approved: bool,
    ) -> bool:
        with self._condition:
            item = self._pending.get((task_id, command_request_id))
            if item is None or item.request.attempt_id != attempt_id or item.digest != digest:
                return False
            if item.invalidated or item.consumed or item.decision is not None or time.monotonic() >= item.deadline:
                return False
            if (task_id, attempt_id) in self._invalid_attempts or type(approved) is not bool:
                return False
            item.decision = approved
            self._condition.notify_all()
            return True

    def consume(self, request: ExecutionRequest) -> bool:
        with self._condition:
            item = self._pending.get((request.task_id, request.command_request_id))
            if item is None or item.digest != request.canonical_digest():
                return False
            if item.invalidated or item.consumed or item.decision is not True or time.monotonic() >= item.deadline:
                return False
            if (request.task_id, request.attempt_id) in self._invalid_attempts:
                return False
            item.consumed = True
            return True

    def invalidate_attempt(self, task_id: str, attempt_id: int) -> None:
        with self._condition:
            self._invalid_attempts.add((task_id, attempt_id))
            for (owner, _), item in self._pending.items():
                if owner == task_id and item.request.attempt_id == attempt_id:
                    item.invalidated = True
            self._condition.notify_all()
