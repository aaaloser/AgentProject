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
class ExecutionReceipt:
    attempt_id: int
    command_request_id: str
    command_sha256: str
    execution_digest: str
    exit_code: int
    duration_ms: int
    ok: bool
    output_truncated: bool


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
    execution_receipts: tuple[ExecutionReceipt, ...] = ()
    execution_started: bool = False
    cleanup_confirmed: bool = False
    events: tuple[PublicTaskEvent, ...] = ()


@dataclass(frozen=True)
class PublicPatchSummary:
    status: str
    changed_files: int = 0
    added_lines: int = 0
    deleted_lines: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    attempt_id: int
    command: str
    command_request_id: str | None
    exit_code: int | None
    duration_ms: int | None
    status: str
    output_redacted: bool
    output_truncated: bool


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    repo_id: str
    base_sha: str
    status: str
    failure_kind: str | None
    changed_files: tuple[str, ...]
    patch_summary: PublicPatchSummary
    verification_status: str
    verification_results: tuple[VerificationResult, ...]
    limitations: tuple[str, ...]
