from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from mokioclaw.evals.provider_failures import FailureKind


EVAL_IMAGE = "mokioclaw-eval-python:3.13"


class RunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    SETUP_FAILED = "setup_failed"


@dataclass(frozen=True)
class RepositorySpec:
    template: str
    mutation: str


@dataclass(frozen=True)
class VerificationSpec:
    commands: Sequence[str]


@dataclass(frozen=True)
class GraderSpec:
    id: str
    hidden_tests: Path
    protected_paths: Sequence[Path] = ()


@dataclass(frozen=True)
class Limits:
    max_attempts: int = 3
    max_tool_calls: int = 40
    agent_timeout_seconds: int = 600
    command_timeout_seconds: int = 120


@dataclass(frozen=True)
class LimitsOverride:
    max_tool_calls: int | None = None
    agent_timeout_seconds: int | None = None


def effective_limits(limits: Limits, override: LimitsOverride | None) -> Limits:
    if override is None:
        return limits
    return replace(
        limits,
        max_tool_calls=override.max_tool_calls if override.max_tool_calls is not None else limits.max_tool_calls,
        agent_timeout_seconds=(
            override.agent_timeout_seconds if override.agent_timeout_seconds is not None else limits.agent_timeout_seconds
        ),
    )


@dataclass(frozen=True)
class Policy:
    network: str = "provider_only"
    writable_paths: Sequence[Path] = (Path("."),)


@dataclass(frozen=True)
class CaseSpec:
    id: str
    category: str
    task: str
    repository: RepositorySpec
    public_verification: VerificationSpec
    grader: GraderSpec
    image: str = ""
    limits: Limits = Limits()
    policy: Policy = Policy()


def resolved_case_image(case: CaseSpec) -> str:
    return case.image.strip() or EVAL_IMAGE


@dataclass(frozen=True)
class AgentRunConfig:
    run_id: str
    case_id: str
    task: str
    workspace: Path
    architecture: str
    retrieval: str
    model: str
    base_url_host: str
    temperature: float
    sandbox_image: str
    max_attempts: int
    max_tool_calls: int
    timeout_seconds: int
    scheduled_run_id: str = ""
    worker_attempt_id: str = ""
    protected_paths: Sequence[str] = ()
    verification_commands: Sequence[str] = ()


@dataclass(frozen=True)
class GraderCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class CaseResult:
    run_id: str
    case_id: str
    status: RunStatus
    success: bool
    scheduled_run_id: str = ""
    worker_attempt_id: str = ""
    agent_attempt_count: int = 0
    first_pass_success: bool = False
    grader_checks: list[GraderCheck] = field(default_factory=list)
    attempts: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    compression_count: int = 0
    failure_stage: str = ""
    failure_reason: str = ""
    failure_kind: FailureKind | None = None
    provider_status: int | None = None
    provider_phase: str | None = None
    retryable: bool = False
    sanitized_reason: str = ""
    telemetry_coverage: str = "unavailable"
    telemetry_unavailable_reason: str | None = None
    model_call_count: int = 0
    transport_attempt_count: int = 0
    failure_detail_stage: str = ""
    needs_review: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
