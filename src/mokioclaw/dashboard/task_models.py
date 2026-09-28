"""Public task identity and lifecycle data for the local dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    repo_id: str
    base_sha: str
    anchor_sha: str
    description: str
    source_read_scope: tuple[str, ...]
    source_write_scope: tuple[str, ...]
    task_scratch_scope: str
    manifest_digest: str
    max_seconds: int
    max_attempts: int
    verification_commands: tuple[str, ...]
    max_provider_calls: int
    max_total_tokens: int
    max_output_tokens_per_call: int
    created_at: str


@dataclass(frozen=True)
class PublicTaskEvent:
    task_id: str
    attempt_id: int | None
    sequence: int
    timestamp: str
    kind: str
    data: dict[str, str | int | bool | None]


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    repo_id: str
    base_sha: str
    anchor_sha: str
    manifest_digest: str
    created_at: str
    state: str
    attempt_id: int | None
    sequence: int
    request_digest: str
    idempotency_digest: str
    failure_kind: str | None = None
    verification_status: str | None = None
    worker_pid: int | None = None
    worker_created_at: str | None = None
    instance_id: str | None = None
    owned_request_ids: tuple[str, ...] = ()
    execution_started: bool = False
    cleanup_confirmed: bool = False
    events: tuple[PublicTaskEvent, ...] = ()
